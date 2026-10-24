import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from telethon import TelegramClient, errors, utils
from telethon.tl import functions, types

from app.db import SessionLocal
from app.jobs.runner import JobContext
from app import notify
from app.insights.common import active_jobs, cards, excluded_ids
from app.models import Comment, Job, JobParticipant, PeerNote, ThreadRoot, iso, utcnow
from app.telegram import limits
from app.telegram.links import ChannelRef, LinkError, parse_channel_link
from app.telegram.access import save_access
from app.telegram.peers import avatar_path, download_avatar, mark_missed, recently_missed, upsert_peers
from app.tools.base import Tool, register
from app.tools.comment_collector.aggregate import CommentAggregator

BATCH = 500
AVATAR_TIMEOUT = 30  # seconds per photo; cross-DC downloads can stall
AVATAR_BUDGET = 15 * 60  # the rest is picked up by the next run
# Errors meaning "the discussion group's history is not readable by this account".
_NO_GROUP_ACCESS = (
    errors.ChannelPrivateError,
    errors.ChatAdminRequiredError,
    errors.ChannelInvalidError,
    errors.ChatForbiddenError,
)


class CollectorInput(BaseModel):
    channel: str = Field(min_length=1, max_length=256)
    strategy: Literal["auto", "fast", "per_post"] = "auto"
    download_avatars: bool = True
    # incremental: only comments newer than the channel's last collection, appended into it
    mode: Literal["full", "incremental"] = "full"
    monitor_id: int | None = None

    @field_validator("channel")
    @classmethod
    def _valid_link(cls, v: str) -> str:
        try:
            parse_channel_link(v)
        except LinkError as e:
            raise ValueError(str(e)) from e
        return v.strip()


class UserFacingError(Exception):
    pass


def keep_forward_source(msg: Any, entities: dict[int, Any]) -> None:
    """Remember the channel a message was forwarded from, when Telegram sent its entity along
    (its access hash lets the channel finder read it later)."""
    if getattr(msg, "fwd_from", None) is None:
        return
    chat = getattr(getattr(msg, "forward", None), "chat", None)
    if isinstance(chat, (types.Channel, types.Chat)):
        entities[utils.get_peer_id(chat)] = chat


async def save_about(peer_id: int, about: str | None) -> None:
    """A channel's / chat's description (for contacts, ИНН, links in it)."""
    async with SessionLocal() as db:
        await db.execute(text("UPDATE tg_peers SET about = :a WHERE id = :p"), {"a": about or None, "p": peer_id})
        await db.commit()


async def _resolve_channel(client: TelegramClient, ref: ChannelRef) -> types.Channel:
    try:
        if ref.username:
            entity = await client.get_entity(ref.username)
        elif ref.invite_hash:
            invite = await client(functions.messages.CheckChatInviteRequest(ref.invite_hash))
            entity = getattr(invite, "chat", None)
            if entity is None:
                raise UserFacingError("Это приватный канал: сначала вступите в него этим аккаунтом")
        else:
            entity = await client.get_entity(types.PeerChannel(ref.channel_id))
    except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError) as e:
        raise UserFacingError(f"Канал {ref.display} не найден") from e
    except (errors.InviteHashExpiredError, errors.InviteHashInvalidError) as e:
        raise UserFacingError("Ссылка-приглашение недействительна") from e
    except ValueError as e:
        raise UserFacingError(f"Не удалось найти {ref.display}: аккаунт не имеет к нему доступа") from e
    if not isinstance(entity, types.Channel):
        raise UserFacingError(f"{ref.display} — это не канал")
    if entity.megagroup:
        raise UserFacingError(f"{ref.display} — это группа, а не канал: добавьте её как чат (индексатор чатов)")
    return entity


async def _iter_with_floodwait(ctx: JobContext, make_iter) -> AsyncIterator[Any]:
    """Iterate Telethon messages, surviving long FloodWaits by resuming after the last seen id."""
    last_id = 0
    while True:
        try:
            async for msg in make_iter(last_id):
                last_id = msg.id
                yield msg
            return
        except errors.FloodWaitError as e:
            until = datetime.now(UTC) + timedelta(seconds=e.seconds)
            await ctx.update(force=True, flood_wait_until=until.isoformat())
            await asyncio.sleep(e.seconds + 1)
            await ctx.update(force=True, flood_wait_until=None)


class CommentCollector(Tool):
    id = "comment-collector"
    title = "Сборщик комментаторов"
    description = "Все пользователи, оставлявшие комментарии под постами канала"
    Input = CollectorInput

    async def run(self, ctx: JobContext, params: CollectorInput) -> dict[str, Any]:
        started = time.monotonic()
        client = await ctx.client()
        await ctx.update(force=True, phase="resolve")

        channel = await _resolve_channel(client, parse_channel_link(params.channel))
        full = await client(functions.channels.GetFullChannelRequest(channel))
        linked_id = full.full_chat.linked_chat_id
        group = next((c for c in full.chats if c.id == linked_id), None) if linked_id else None
        if group is None:
            raise UserFacingError("У канала не подключены комментарии (нет группы обсуждений)")

        await self._save_peers([channel, group])
        await save_about(utils.get_peer_id(channel), getattr(full.full_chat, "about", None))
        if params.download_avatars:
            try:
                await asyncio.wait_for(download_avatar(client, channel), AVATAR_TIMEOUT)
            except Exception:
                pass  # the channel picture is cosmetic
        photo_id = getattr(channel.photo, "photo_id", None)
        channel_info = {
            "id": utils.get_peer_id(channel),
            "title": channel.title,
            "username": channel.username,
            "photo_id": str(photo_id) if photo_id else None,  # 64-bit: a JS number would round it
            "subscribers": full.full_chat.participants_count,
            "group_title": group.title,
            "group_username": group.username,
        }
        source_id = channel_info["id"]
        await ctx.set_source(source_id)
        posts_total = (await client.get_messages(channel, limit=0)).total
        await ctx.update(force=True, channel=channel_info, posts_total=posts_total)

        previous = await self._base_job(source_id)  # latest finished collection of this channel
        incremental = params.mode == "incremental" and previous is not None
        target = previous.id if incremental else ctx.job_id  # incremental runs write into the base job
        before = await self._participant_ids(previous.id) if previous else None

        agg = CommentAggregator(channel.id)
        entities: dict[int, Any] = {}
        strategy = params.strategy
        last_group_id = 0
        if incremental:
            agg.roots.update(await self._known_roots(source_id))
            last_group_id = (previous.result or {}).get("last_group_msg_id") or await self._max_msg_id(previous.id)
        try:
            if strategy in ("auto", "fast"):
                try:
                    group_total = (await client.get_messages(group, limit=0)).total
                except _NO_GROUP_ACCESS:
                    if strategy == "fast":
                        raise UserFacingError("Нет доступа к истории группы обсуждений — используйте режим «по постам»")
                    strategy = "per_post"
                else:
                    strategy = "fast"
                    if incremental:
                        latest = await client.get_messages(group, limit=1)
                        group_total = max(0, (latest[0].id if latest else 0) - last_group_id)
                    last_group_id = await self._scan_group(ctx, client, group, group_total, agg, entities, target, since=last_group_id)
                    if incremental:
                        await self._resolve_old_threads(client, group, agg, entities, target)
            if strategy == "per_post":
                known = await self._known_post_max(previous.id) if incremental else None
                await self._scan_posts(ctx, client, channel, posts_total, agg, entities, target, known)
        except asyncio.CancelledError:
            # Stopped by the user: keep what was collected so far, then let the runner mark it cancelled.
            await self._flush_comments(target, agg)
            if incremental:
                await self._merge_into_base(previous, agg, entities, last_group_id)
            else:
                await self._persist(target, agg, entities)
            raise

        await ctx.update(force=True, phase="saving")
        await self._save_roots(source_id, agg)
        if incremental:
            entities, totals = await self._merge_into_base(previous, agg, entities, last_group_id)
        else:
            entities = await self._persist(target, agg, entities)

        new_ids = [p for p in agg.participants if before is not None and p not in before]
        result: dict[str, Any] = {
            "channel": channel_info,
            "strategy": strategy,
            "mode": "incremental" if incremental else "full",
            "upgraded_to_full": params.mode == "incremental" and not incremental,
            "posts_total": posts_total,
            "duration_sec": round(time.monotonic() - started, 1),
            "last_group_msg_id": last_group_id or None,
            "new_users": len(new_ids) if before is not None else None,
            "new_user_ids": new_ids[:500],
        }
        if incremental:
            result |= {"base_job_id": previous.id, "new_comments": agg.total, **totals}
        else:
            result |= {"comments": agg.total, "unique_users": len(agg.participants),
                       "posts_with_comments": len(agg.posts_with_comments), "orphaned": agg.orphaned}
        await self._notify(ctx, params, channel_info, agg, new_ids, before is not None,
                           previous.id if incremental else ctx.job_id)

        if params.download_avatars:
            await ctx.set_result(result)  # data is complete; avatars are a bonus
            result["avatars"] = await self._download_avatars(ctx, client, list(entities.values()))
        return result

    async def _notify(self, ctx, params, ch, agg: CommentAggregator, new_ids: list[int], compared: bool, view_job: int) -> None:
        """New commenters (vs the previous collection) and comments from starred people."""
        title = ch["title"]
        async with SessionLocal() as db:
            skip = await excluded_ids(db)  # ignored people / hidden categories are not news
        new_ids = [p for p in new_ids if p not in skip]
        if compared and new_ids:
            async with SessionLocal() as db:
                people = list((await cards(db, new_ids[:15])).values())
            await notify.emit(
                "new_users",
                f"{title}: +{len(new_ids)} новых комментаторов",
                {"count": len(new_ids), "people": people, "peer_ids": new_ids[:500], "more": len(new_ids) > 15,
                 "path": f"/tools/comment-collector/jobs/{ctx.job_id}"},
                source_id=ch["id"], job_id=ctx.job_id, monitor_id=params.monitor_id,
            )
        if not compared and params.mode == "full":
            return  # first collection: everyone is "new", starred people are not news either
        async with SessionLocal() as db:
            starred = set((await db.execute(
                select(PeerNote.peer_id).where(PeerNote.starred.is_(True), PeerNote.ignored.is_(False),
                                              PeerNote.peer_id.in_(list(agg.participants) or [0]))
            )).scalars())
            if not starred:
                return
            people = [c | {"comments": agg.participants[c["peer_id"]].comments} for c in (await cards(db, starred)).values()]
        await notify.emit(
            "watch",
            f"{title}: избранные оставили комментарии",
            {"count": len(people), "people": people, "path": "/users?starred=1",
             "detail": ", ".join(f"{p['name']} — {p['comments']}" for p in people[:10])},
            source_id=ch["id"], job_id=ctx.job_id, monitor_id=params.monitor_id,
        )

    # ---------- strategies ----------

    async def _scan_group(self, ctx, client, group, group_total, agg: CommentAggregator, entities, target: int,
                          since: int = 0) -> int:
        """Scan the discussion group after message `since`; returns the last message id seen."""
        await ctx.update(force=True, phase="scan", strategy="fast", messages_total=group_total, messages_scanned=0)
        scanned = 0
        last_id = since
        t0 = time.monotonic()
        # Oldest -> newest, so a thread root is always seen before its comments.
        it = _iter_with_floodwait(
            ctx, lambda last: client.iter_messages(group, reverse=True, offset_id=max(last, since), wait_time=0)
        )
        async for msg in it:
            scanned += 1
            last_id = max(last_id, msg.id)
            agg.feed_group_message(msg)
            # Cache senders of every reply; non-commenters are filtered out before saving.
            if getattr(msg, "reply_to", None) and msg.sender is not None:
                entities[utils.get_peer_id(msg.sender)] = msg.sender
            keep_forward_source(msg, entities)
            if scanned % 200 == 0:
                await self._flush_comments(target, agg)
                await ctx.update(
                    messages_scanned=scanned,
                    comments=agg.total,
                    unique_users=len(agg.participants), posts_with_comments=len(agg.posts_with_comments),
                    posts_done=len(agg.roots),
                    rate=round(scanned / max(time.monotonic() - t0, 0.001)),
                )
        await self._flush_comments(target, agg)
        await ctx.update(
            force=True, messages_scanned=scanned, comments=agg.total,
            unique_users=len(agg.participants), posts_with_comments=len(agg.posts_with_comments), posts_done=len(agg.roots),
        )
        return last_id

    async def _scan_posts(self, ctx, client, channel, posts_total, agg: CommentAggregator, entities, target: int,
                          known: dict[int, int] | None = None) -> None:
        """known: post id -> newest comment id already stored (incremental runs skip the rest)."""
        await ctx.update(force=True, phase="scan", strategy="per_post", posts_done=0, messages_scanned=0)
        posts_done = 0
        scanned = 0
        t0 = time.monotonic()
        posts = _iter_with_floodwait(
            ctx, lambda last: client.iter_messages(channel, reverse=True, offset_id=last)
        )
        async for post in posts:
            posts_done += 1
            replies = getattr(post, "replies", None)
            seen_max = (known or {}).get(post.id, 0)
            fresh = known is None or (getattr(replies, "max_id", None) or 0) > seen_max
            if isinstance(post, types.Message) and replies and replies.replies and fresh:
                comments = _iter_with_floodwait(
                    ctx,
                    lambda last, pid=post.id, floor=seen_max: client.iter_messages(
                        channel, reply_to=pid, reverse=True, offset_id=max(last, floor)),
                )
                async for msg in comments:
                    scanned += 1
                    agg.feed_post_comment(msg, post.id)
                    if msg.sender is not None:
                        entities[utils.get_peer_id(msg.sender)] = msg.sender
                    keep_forward_source(msg, entities)
            if posts_done % 10 == 0 or posts_done == posts_total:
                await self._flush_comments(target, agg)
                await ctx.update(
                    posts_done=posts_done,
                    messages_scanned=scanned,
                    comments=agg.total,
                    unique_users=len(agg.participants), posts_with_comments=len(agg.posts_with_comments),
                    rate=round(scanned / max(time.monotonic() - t0, 0.001)),
                )
        await self._flush_comments(target, agg)
        await ctx.update(force=True, posts_done=posts_done, comments=agg.total, unique_users=len(agg.participants),
                         posts_with_comments=len(agg.posts_with_comments))

    async def _resolve_old_threads(self, client, group, agg: CommentAggregator, entities, target: int) -> None:
        """New comments under posts whose root lies before the scanned range: fetch those roots by id."""
        tops = agg.unresolved_tops()
        for i in range(0, len(tops), 100):
            for msg in await client.get_messages(group, ids=tops[i:i + 100]):
                if msg is not None:
                    agg.feed_group_message(msg)  # a root flushes its buffered replies
        await self._flush_comments(target, agg)

    # ---------- persistence ----------

    async def _persist(self, job_id: int, agg: CommentAggregator, entities: dict[int, Any]) -> dict[int, Any]:
        entities = {pid: e for pid, e in entities.items() if pid in agg.participants or pid in agg.fwd_sources}
        await self._save_peers(list(entities.values()))
        await self._save_participants(job_id, agg)
        return entities

    async def _base_job(self, source_id: int) -> Job | None:
        async with SessionLocal() as db:
            job_id = (await active_jobs(db, include_hidden=True)).get(source_id)
            return await db.get(Job, job_id) if job_id else None

    async def _participant_ids(self, job_id: int) -> set[int]:
        async with SessionLocal() as db:
            return set((await db.execute(select(JobParticipant.peer_id).where(JobParticipant.job_id == job_id))).scalars())

    async def _max_msg_id(self, job_id: int) -> int:
        async with SessionLocal() as db:
            return (await db.execute(text("SELECT coalesce(max(msg_id), 0) FROM comments WHERE job_id = :j"), {"j": job_id})).scalar_one()

    async def _known_post_max(self, job_id: int) -> dict[int, int]:
        async with SessionLocal() as db:
            rows = await db.execute(text("SELECT post_id, max(msg_id) FROM comments WHERE job_id = :j GROUP BY post_id"), {"j": job_id})
            return dict(rows.all())

    async def _known_roots(self, source_id: int) -> dict[int, int]:
        async with SessionLocal() as db:
            rows = await db.execute(select(ThreadRoot.root_msg_id, ThreadRoot.post_id).where(ThreadRoot.source_id == source_id))
            return dict(rows.all())

    async def _save_roots(self, source_id: int, agg: CommentAggregator) -> None:
        rows = [{"source_id": source_id, "root_msg_id": r, "post_id": p} for r, p in agg.roots.items()]
        async with SessionLocal() as db:
            for i in range(0, len(rows), BATCH):
                await db.execute(sqlite_insert(ThreadRoot).values(rows[i:i + BATCH]).on_conflict_do_nothing())
            await db.commit()

    async def _merge_into_base(self, base: Job, agg: CommentAggregator, entities: dict[int, Any],
                               last_group_id: int) -> tuple[dict[int, Any], dict[str, Any]]:
        """Recount the base job's participants from its (now longer) comment list."""
        entities = {pid: e for pid, e in entities.items() if pid in agg.participants or pid in agg.fwd_sources}
        await self._save_peers(list(entities.values()))
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM job_participants WHERE job_id = :j"), {"j": base.id})
            await db.execute(text("""
                INSERT INTO job_participants (job_id, peer_id, comments, posts, first_at, last_at)
                SELECT job_id, sender_id, count(*), count(DISTINCT post_id), min(date), max(date)
                FROM comments WHERE job_id = :j GROUP BY sender_id"""), {"j": base.id})
            comments, users, posts = (await db.execute(text(
                "SELECT count(*), count(DISTINCT sender_id), count(DISTINCT post_id) FROM comments WHERE job_id = :j"),
                {"j": base.id})).one()
            job = await db.get(Job, base.id)
            totals = {"comments": comments, "unique_users": users, "posts_with_comments": posts}
            job.result = (job.result or {}) | totals | {
                "updated_at": iso(utcnow()),
                "last_group_msg_id": max(last_group_id or 0, (job.result or {}).get("last_group_msg_id") or 0) or None,
            }
            await db.commit()
        return entities, {"total_comments": comments, "total_users": users, "posts_with_comments": posts}

    async def _flush_comments(self, job_id: int, agg: CommentAggregator) -> None:
        recs = agg.drain_new()
        if not recs:
            return
        async with SessionLocal() as db:
            for i in range(0, len(recs), BATCH):
                await db.execute(
                    sqlite_insert(Comment).on_conflict_do_nothing(),
                    [
                        {"job_id": job_id, "msg_id": r.msg_id, "post_id": r.post_id,
                         "sender_id": r.sender_id, "date": r.date, "text": r.text, "reply_to": r.reply_to,
                         "fwd_from": r.fwd_from}
                        for r in recs[i:i + BATCH]
                    ],
                )
            await db.commit()

    async def _save_peers(self, entities: list[Any]) -> None:
        entities = [e for e in entities if e is not None]
        if not entities:
            return
        async with SessionLocal() as db:
            await upsert_peers(db, entities)
            await save_access(db, entities)
            await db.commit()

    async def _save_participants(self, job_id: int, agg: CommentAggregator) -> None:
        rows = [
            {"job_id": job_id, "peer_id": pid, "comments": s.comments, "posts": len(s.posts),
             "first_at": s.first_at, "last_at": s.last_at}
            for pid, s in agg.participants.items()
        ]
        if not rows:
            return
        async with SessionLocal() as db:
            for i in range(0, len(rows), BATCH):
                await db.execute(sqlite_insert(JobParticipant), rows[i:i + BATCH])
            await db.commit()

    async def _download_avatars(self, ctx: JobContext, client, entities: list[Any]) -> dict[str, int]:
        """Fetch missing profile pictures. Cached files and photos that failed recently are skipped,
        each photo is fetched once, FloodWaits pause all workers (with a visible countdown)."""
        todo: dict[int, Any] = {}
        cached = 0
        for e in entities:
            pid = getattr(getattr(e, "photo", None), "photo_id", None)
            if not pid:
                continue
            if avatar_path(pid).exists():
                cached += 1
            elif not recently_missed(pid):
                todo.setdefault(pid, e)
        stats = {"downloaded": 0, "cached": cached, "failed": 0, "skipped": 0}
        await ctx.update(force=True, phase="avatars", avatars_total=len(todo), avatars_done=0, avatars_cached=cached)
        if not todo:
            return stats

        started = time.monotonic()
        resume_at = 0.0  # shared FloodWait gate
        sem = asyncio.Semaphore(limits.current().avatar_concurrency)
        done = 0
        # Surface FloodWaits as exceptions instead of Telethon silently sleeping up to a minute per file.
        saved_threshold = client.flood_sleep_threshold
        client.flood_sleep_threshold = 0

        def stopping() -> bool:
            return "skip_avatars" in ctx.signals or time.monotonic() - started > AVATAR_BUDGET

        async def one(pid: int, entity) -> None:
            nonlocal done, resume_at
            async with sem:
                for _ in range(4):
                    if stopping():
                        stats["skipped"] += 1
                        break
                    if (wait := resume_at - time.monotonic()) > 0:
                        await asyncio.sleep(wait)
                        continue
                    try:
                        ok = await asyncio.wait_for(download_avatar(client, entity), AVATAR_TIMEOUT)
                        stats["downloaded" if ok else "failed"] += 1
                        break
                    except errors.FloodWaitError as e:
                        resume_at = max(resume_at, time.monotonic() + e.seconds + 1)
                        until = datetime.now(UTC) + timedelta(seconds=e.seconds + 1)
                        await ctx.update(force=True, flood_wait_until=until.isoformat())
                    except (TimeoutError, errors.RPCError, ValueError, OSError):
                        mark_missed(pid)  # deleted photo, expired reference, stalled DC… initials instead
                        stats["failed"] += 1
                        break
                else:
                    stats["failed"] += 1
            done += 1
            await ctx.update(avatars_done=done, flood_wait_until=None if resume_at <= time.monotonic() else ctx.progress.get("flood_wait_until"))

        try:
            await asyncio.gather(*(one(pid, e) for pid, e in todo.items()))
        finally:
            client.flood_sleep_threshold = saved_threshold
        await ctx.update(force=True, avatars_done=done, flood_wait_until=None, avatars_skipped=stats["skipped"])
        return stats


register(CommentCollector())
