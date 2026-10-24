"""Chat indexer: message history and member list of a group / supergroup / forum.

Writes into the same tables as the comment collector (`comments` holds messages, `job_participants`
everyone found), so people, overlaps, graphs, search and monitoring treat chats like channels.
A message's `post_id` is its "discussion": the topic id in forums, the UTC day number elsewhere.
"""

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from telethon import errors, utils
from telethon.tl import functions, types

from app import notify
from app.db import SessionLocal
from app.insights.common import cards, excluded_ids
from app.jobs.runner import JobContext
from app.models import Comment, Job, PeerNote, SourceMember, iso, utcnow
from app.telegram.links import LinkError, parse_channel_link
from app.telegram.peers import download_avatar
from app.telegram.resolve import UserFacingError, full_info, resolve_chat, source_type
from app.tools.base import register
from app.tools.comment_collector.collector import AVATAR_TIMEOUT, BATCH, CommentCollector

TOOL_ID = "chat-indexer"
MEMBERS_LIMIT = 50_000  # Telegram itself stops listing big groups at ~10k
_NO_MEMBERS = (errors.ChatAdminRequiredError, errors.ChannelPrivateError, errors.ChatForbiddenError,
               errors.ChannelInvalidError)


class IndexerInput(BaseModel):
    channel: str = Field(min_length=1, max_length=256)  # link to the chat (same key as the collector)
    mode: Literal["full", "incremental"] = "full"
    since: date | None = None  # full runs: only messages from this day on
    max_messages: int | None = Field(None, ge=100, le=10_000_000)  # full runs: only the newest N
    index_messages: bool = True
    collect_members: bool = True
    download_avatars: bool = True
    monitor_id: int | None = None

    @field_validator("channel")
    @classmethod
    def _valid_link(cls, v: str) -> str:
        try:
            parse_channel_link(v)
        except LinkError as e:
            raise ValueError(str(e)) from e
        return v.strip()


def day_number(d: datetime) -> int:
    return int((d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp() // 86400)


def message_record(msg: Any, forum: bool) -> dict[str, Any] | None:
    """Row for `comments`, or None for service messages and anonymous admins."""
    if not isinstance(msg, types.Message) or msg.from_id is None:
        return None
    rt = msg.reply_to if isinstance(msg.reply_to, types.MessageReplyHeader) else None
    if rt is not None and rt.reply_to_peer_id is not None:
        rt = None  # reply to a message in another chat
    reply_to = rt.reply_to_msg_id if rt else None
    if forum:
        if rt and rt.forum_topic:
            thread = rt.reply_to_top_id or rt.reply_to_msg_id
            if not rt.reply_to_top_id:
                reply_to = None  # plain message in a topic: "replies" to the topic root
        else:
            thread = 1  # General
    else:
        thread = day_number(msg.date)
    return {"msg_id": msg.id, "post_id": thread, "sender_id": utils.get_peer_id(msg.from_id),
            "date": msg.date, "text": msg.message or None, "reply_to": reply_to}


def member_role(user: Any) -> str | None:
    p = getattr(user, "participant", None)
    if isinstance(p, (types.ChannelParticipantCreator, types.ChatParticipantCreator)):
        return "creator"
    if isinstance(p, (types.ChannelParticipantAdmin, types.ChatParticipantAdmin)):
        return "admin"
    if isinstance(p, (types.ChannelParticipantBanned, types.ChannelParticipantLeft)):
        return None
    return "member"


async def rebuild_participants(job_id: int, source_id: int) -> None:
    """Everyone in a chat source = message authors (from `comments`) ∪ the stored member list."""
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM job_participants WHERE job_id = :j"), {"j": job_id})
        await db.execute(text("""
            INSERT INTO job_participants (job_id, peer_id, comments, posts, first_at, last_at, member, role)
            SELECT :j, sender_id, count(*), count(DISTINCT post_id), min(date), max(date), 0, NULL
            FROM comments WHERE job_id = :j GROUP BY sender_id"""), {"j": job_id})
        await db.execute(text("""
            INSERT INTO job_participants (job_id, peer_id, comments, posts, member, role)
            SELECT :j, peer_id, 0, 0, 1, role FROM source_members WHERE source_id = :s
            ON CONFLICT (job_id, peer_id) DO UPDATE SET member = 1, role = excluded.role"""), {"j": job_id, "s": source_id})
        await db.commit()


async def _totals(job_id: int) -> dict[str, int]:
    async with SessionLocal() as db:
        messages, threads = (await db.execute(text(
            "SELECT count(*), count(DISTINCT post_id) FROM comments WHERE job_id = :j"), {"j": job_id})).one()
        authors, members, people = (await db.execute(text(
            "SELECT coalesce(sum(comments > 0), 0), coalesce(sum(member), 0), count(*) FROM job_participants WHERE job_id = :j"),
            {"j": job_id})).one()
    return {"comments": messages, "unique_users": authors, "members": members, "people": people,
            "posts_with_comments": threads}


class ChatIndexer(CommentCollector):
    """Reuses the collector's persistence helpers (peers, avatars, base job lookup)."""

    id = TOOL_ID
    title = "Индексатор чатов"
    description = "Сообщения и участники групп, супергрупп и форумов"
    Input = IndexerInput

    async def run(self, ctx: JobContext, params: IndexerInput) -> dict[str, Any]:
        started = time.monotonic()
        client = await ctx.client()
        await ctx.update(force=True, phase="resolve")

        entity = await resolve_chat(client, parse_channel_link(params.channel))
        kind = source_type(entity)
        if kind == "channel":
            raise UserFacingError("Это канал: люди в нём видны только через комментарии — добавьте его как канал "
                                  "или проиндексируйте его группу обсуждений")
        full = await full_info(client, entity)
        fc = full.full_chat
        forum = kind == "forum"
        await self._save_peers([entity])
        if params.download_avatars:
            try:
                await asyncio.wait_for(download_avatar(client, entity), AVATAR_TIMEOUT)
            except Exception:
                pass
        photo_id = getattr(getattr(entity, "photo", None), "photo_id", None)
        members_count = getattr(fc, "participants_count", None)
        if members_count is None and isinstance(getattr(fc, "participants", None), types.ChatParticipants):
            members_count = len(fc.participants.participants)
        linked_id = getattr(fc, "linked_chat_id", None)
        linked = next((c for c in full.chats if c.id == linked_id), None) if linked_id else None
        info = {
            "id": utils.get_peer_id(entity),
            "type": kind,
            "title": entity.title,
            "username": getattr(entity, "username", None),
            "photo_id": str(photo_id) if photo_id else None,
            "subscribers": members_count,
            # a discussion group points back to its channel
            "linked_channel": {"id": utils.get_peer_id(linked), "title": linked.title, "username": linked.username} if linked else None,
        }
        source_id = info["id"]
        await ctx.set_source(source_id)
        await ctx.update(force=True, channel=info)

        previous = await self._base_job(source_id)
        incremental = params.mode == "incremental" and previous is not None
        target = previous.id if incremental else ctx.job_id
        before = await self._participant_ids(previous.id) if previous else None
        prev_result = (previous.result or {}) if previous else {}
        floor = (prev_result.get("last_msg_id") or await self._max_msg_id(previous.id)) if incremental else 0

        entities: dict[int, Any] = {}
        authors: dict[int, int] = {}  # sender -> messages in this run
        state = {"last_id": floor, "scanned": 0}
        topics = prev_result.get("topics") or {}
        try:
            if forum:
                topics |= await self._topics(client, entity)
            if params.index_messages:
                await self._scan(ctx, client, entity, forum, params, incremental, floor, target, entities, authors, state)
            members = {"status": "skipped"}
            if params.collect_members:
                members = await self._members(ctx, client, entity, fc, source_id, entities)
        except asyncio.CancelledError:
            await rebuild_participants(target, source_id)  # keep what was indexed so far
            raise

        await ctx.update(force=True, phase="saving")
        await self._save_peers(list(entities.values()))
        await rebuild_participants(target, source_id)
        totals = await _totals(target)
        after = await self._participant_ids(target)
        new_ids = [p for p in after if before is not None and p not in before]
        last_id = max(state["last_id"], prev_result.get("last_msg_id") or 0) or None
        summary = {"channel": info, "type": kind, "thread_unit": "topic" if forum else "day", "topics": topics,
                   "last_msg_id": last_id, "members_status": members["status"], "members_fetched": members.get("fetched")}

        result: dict[str, Any] = summary | {
            "mode": "incremental" if incremental else "full",
            "upgraded_to_full": params.mode == "incremental" and not incremental,
            "duration_sec": round(time.monotonic() - started, 1),
            "new_users": len(new_ids) if before is not None else None,
            "new_user_ids": new_ids[:500],
            "new_authors": sum(1 for p in new_ids if p in authors),
        }
        if incremental:
            async with SessionLocal() as db:
                job = await db.get(Job, previous.id)
                job.result = (job.result or {}) | totals | summary | {"updated_at": iso(utcnow())}
                await db.commit()
            result |= {"base_job_id": previous.id, "new_comments": state["scanned"],
                       "total_comments": totals["comments"], "total_users": totals["people"],
                       "posts_with_comments": totals["posts_with_comments"], "members": totals["members"]}
        else:
            result |= totals | {"since": params.since.isoformat() if params.since else None, "max_messages": params.max_messages}

        await self._notify_chat(ctx, params, info, new_ids, authors, before is not None, kind)
        if params.download_avatars:
            await ctx.set_result(result)
            result["avatars"] = await self._download_avatars(ctx, client, list(entities.values()))
        return result

    # ---------- messages ----------

    async def _scan(self, ctx, client, entity, forum, params: IndexerInput, incremental: bool, floor: int, target: int,
                    entities, authors, state) -> None:
        """Newest -> oldest down to `floor` (incremental) / `since` / `max_messages` (full)."""
        limit = None if incremental else params.max_messages
        since = None if incremental or not params.since else datetime.combine(params.since, datetime.min.time(), UTC)
        latest = await client.get_messages(entity, limit=1)
        latest_id = latest[0].id if latest else 0
        if incremental:
            total = max(0, latest_id - floor)
        else:
            total = (await client.get_messages(entity, limit=0)).total
            total = min(total, limit) if limit else total
        state["last_id"] = max(state["last_id"], latest_id)
        await ctx.update(force=True, phase="scan", strategy="history", messages_total=total, messages_scanned=0,
                         comments=0, unique_users=0)
        buf: list[dict[str, Any]] = []
        t0 = time.monotonic()
        offset = 0

        async def flush():
            if not buf:
                return
            async with SessionLocal() as db:
                for i in range(0, len(buf), BATCH):
                    await db.execute(sqlite_insert(Comment).on_conflict_do_nothing(),
                                     [r | {"job_id": target} for r in buf[i:i + BATCH]])
                await db.commit()
            buf.clear()

        while True:
            try:
                left = None if limit is None else limit - state["scanned"]
                if left is not None and left <= 0:
                    break
                async for msg in client.iter_messages(entity, limit=left, offset_id=offset, min_id=floor, wait_time=0):
                    offset = msg.id
                    if since and msg.date < since:
                        limit = state["scanned"]  # reached the start date
                        break
                    state["scanned"] += 1
                    rec = message_record(msg, forum)
                    if rec is None:
                        continue
                    buf.append(rec)
                    authors[rec["sender_id"]] = authors.get(rec["sender_id"], 0) + 1
                    if msg.sender is not None:
                        entities[rec["sender_id"]] = msg.sender
                    if state["scanned"] % 500 == 0:
                        await flush()
                        await ctx.update(messages_scanned=state["scanned"], comments=state["scanned"],
                                         unique_users=len(authors),
                                         rate=round(state["scanned"] / max(time.monotonic() - t0, 0.001)))
                break
            except errors.FloodWaitError as e:
                until = datetime.now(UTC) + timedelta(seconds=e.seconds)
                await ctx.update(force=True, flood_wait_until=until.isoformat())
                await asyncio.sleep(e.seconds + 1)
                await ctx.update(force=True, flood_wait_until=None)
            finally:
                await flush()
        await ctx.update(force=True, messages_scanned=state["scanned"], comments=state["scanned"], unique_users=len(authors))

    async def _topics(self, client, entity) -> dict[str, str]:
        """Forum topic titles by id (JSON keys are strings)."""
        out: dict[str, str] = {}
        offset_date, offset_id, offset_topic = None, 0, 0
        try:
            for _ in range(50):
                res = await client(functions.messages.GetForumTopicsRequest(
                    peer=entity, offset_date=offset_date, offset_id=offset_id, offset_topic=offset_topic, limit=100))
                got = [t for t in res.topics if isinstance(t, types.ForumTopic)]
                for t in got:
                    out[str(t.id)] = t.title
                if len(res.topics) < 100 or not got:
                    break
                last = got[-1]
                offset_date, offset_id, offset_topic = last.date, last.top_message, last.id
        except errors.RPCError:
            pass  # titles are cosmetic
        out.setdefault("1", "General")
        return out

    # ---------- members ----------

    async def _members(self, ctx, client, entity, fc, source_id: int, entities) -> dict[str, Any]:
        hidden = getattr(fc, "participants_hidden", False) or getattr(fc, "can_view_participants", True) is False
        total = getattr(fc, "participants_count", None)
        await ctx.update(force=True, phase="members", members_total=total, members_done=0)
        seen: dict[int, tuple[str, datetime | None]] = {}
        flt = types.ChannelParticipantsAdmins() if hidden and isinstance(entity, types.Channel) else None
        status = "hidden" if hidden else "ok"
        for _attempt in range(4):
            try:
                async for u in client.iter_participants(entity, limit=MEMBERS_LIMIT, filter=flt):
                    role = member_role(u)
                    if role is None:
                        continue
                    pid = utils.get_peer_id(u)
                    seen[pid] = (role, getattr(getattr(u, "participant", None), "date", None))
                    entities.setdefault(pid, u)
                    if len(seen) % 200 == 0:
                        await ctx.update(members_done=len(seen))
                break
            except errors.FloodWaitError as e:
                until = datetime.now(UTC) + timedelta(seconds=e.seconds)
                await ctx.update(force=True, flood_wait_until=until.isoformat())
                await asyncio.sleep(e.seconds + 1)
                await ctx.update(force=True, flood_wait_until=None)
            except _NO_MEMBERS:
                status = "hidden"
                break
        if status == "ok" and total and len(seen) < total * 0.9:
            status = "partial"  # Telegram lists at most ~10k members of big groups
        await ctx.update(force=True, members_done=len(seen), members_status=status)

        now = utcnow()
        rows = [{"source_id": source_id, "peer_id": pid, "role": role, "joined_at": joined, "seen_at": now}
                for pid, (role, joined) in seen.items()]
        async with SessionLocal() as db:
            if status == "ok":
                await db.execute(delete(SourceMember).where(SourceMember.source_id == source_id))  # left people drop out
            for i in range(0, len(rows), BATCH):
                stmt = sqlite_insert(SourceMember).values(rows[i:i + BATCH])
                await db.execute(stmt.on_conflict_do_update(
                    index_elements=["source_id", "peer_id"],
                    set_={"role": stmt.excluded.role, "joined_at": stmt.excluded.joined_at, "seen_at": stmt.excluded.seen_at}))
            await db.commit()
        return {"status": status, "fetched": len(seen)}

    # ---------- notifications ----------

    async def _notify_chat(self, ctx, params: IndexerInput, ch, new_ids: list[int], authors: dict[int, int],
                           compared: bool, kind: str) -> None:
        title = ch["title"]
        async with SessionLocal() as db:
            skip = await excluded_ids(db)
        new_ids = [p for p in new_ids if p not in skip]
        path = f"/tools/{TOOL_ID}/jobs/{ctx.job_id}"
        if compared and new_ids:
            writers = sum(1 for p in new_ids if p in authors)
            async with SessionLocal() as db:
                people = list((await cards(db, new_ids[:15])).values())
            detail = f"написали: {writers}, новые участники: {len(new_ids) - writers}"
            await notify.emit("new_users", f"{title}: +{len(new_ids)} новых людей",
                              {"count": len(new_ids), "people": people, "peer_ids": new_ids[:500], "more": len(new_ids) > 15,
                               "path": path, "detail": detail},
                              source_id=ch["id"], job_id=ctx.job_id, monitor_id=params.monitor_id)
        if not compared:
            return
        async with SessionLocal() as db:
            starred = set((await db.execute(select(PeerNote.peer_id).where(
                PeerNote.starred.is_(True), PeerNote.ignored.is_(False), PeerNote.peer_id.in_(list(authors) or [0])))).scalars())
            if not starred:
                return
            people = [c | {"comments": authors[c["peer_id"]]} for c in (await cards(db, starred)).values()]
        await notify.emit("watch", f"{title}: избранные написали в чат",
                          {"count": len(people), "people": people, "path": f"/search?source={ch['id']}",
                           "detail": ", ".join(f"{p['name']} — {p['comments']}" for p in people[:10])},
                          source_id=ch["id"], job_id=ctx.job_id, monitor_id=params.monitor_id)


register(ChatIndexer())
