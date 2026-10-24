"""Channel finder: channels and chats of the people already in the base.

Three signals, cheapest first:
- *sender*: channels that wrote in collected sources «as a channel» (already in the DB, no requests);
- *personal*: the channel a user pinned to their profile (`UserFull.personal_channel_id`);
- *bio*: t.me links, invite links and @mentions in the profile bio, resolved to keep channels and
  chats only (users and bots are dropped). Every username is resolved once and cached.

Read-only: nothing is joined, nothing is sent. Found channels are offered for indexing in the UI.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from telethon import errors, utils
from telethon.tl import functions, types

from app.db import SessionLocal
from app.insights.common import active_jobs, excluded_ids, sql
from app.jobs.runner import JobContext
from app.models import FoundChannel, FoundChannelLink, PeerAccess, Setting, TgPeer, UsernameLookup, utcnow
from app.telegram.access import save_access
from app.telegram.bio import Ref, extract_refs
from app.telegram.peers import download_avatar, peer_row
from app.telegram.resolve import source_type
from app.tools.base import Tool, register
from app.tools.comment_collector.collector import AVATAR_TIMEOUT, BATCH

log = logging.getLogger(__name__)

TOOL_ID = "channel-finder"
MAX_WAIT = 300  # a longer FloodWait postpones the rest of that phase to the next run
TRANSPORT_BACKOFF = (30, 60, 120)  # waits after a transport-level 429 before giving up for a while
TRANSPORT_BLOCK = timedelta(minutes=15)
DETAILS_LIMIT = 500
DETAILS_TTL = timedelta(days=7)


class FinderInput(BaseModel):
    source_ids: list[int] = []  # empty: every enabled source
    presence: Literal["all", "active"] = "all"  # active: only people who wrote something
    recheck: bool = False  # read profiles that were already checked again
    limit: int = Field(2000, ge=1, le=100_000)  # profiles per run, most active people first
    check_bio: bool = True
    resolve_mentions: bool = True
    include_senders: bool = True
    use_usernames: bool = True  # no stored access to a user: find them by @username (spends the resolve limit)
    fetch_details: bool = True
    download_avatars: bool = True


# Telegram rate-limits each method separately: a ban on username lookups (often many hours after a
# few hundred of them) must not stop profile reading. Kinds: resolve | full_user | invite | full_channel.
BLOCKS_KEY = "finder_blocks:{}"


class Blocked(Exception):
    """This kind of request is under a FloodWait longer than MAX_WAIT."""

    def __init__(self, kind: str) -> None:
        self.kind = kind


async def load_blocks(account_id: int | None) -> dict[str, datetime]:
    async with SessionLocal() as db:
        row = await db.get(Setting, BLOCKS_KEY.format(account_id))
    now = datetime.now(UTC)
    out = {k: datetime.fromisoformat(v) for k, v in ((row.value if row else {}) or {}).items()}
    return {k: v for k, v in out.items() if v > now}


async def _save_blocks(account_id: int | None, blocks: dict[str, datetime]) -> None:
    async with SessionLocal() as db:
        stmt = sqlite_insert(Setting).values(key=BLOCKS_KEY.format(account_id), value={k: v.isoformat() for k, v in blocks.items()})
        await db.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value}))
        await db.commit()


def _chat_kind(entity: Any) -> str | None:
    """channel | chat for something a username can point to, None for users."""
    if isinstance(entity, types.Channel):
        return "channel" if entity.broadcast else "chat"
    if isinstance(entity, types.Chat):
        return "chat"
    return None


def found_row(entity: Any) -> dict[str, Any]:
    pid = utils.get_peer_id(entity)
    try:
        kind = source_type(entity)
    except Exception:
        kind = None
    return {"key": str(pid), "peer_id": pid, "type": kind, "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None), "photo_id": getattr(getattr(entity, "photo", None), "photo_id", None),
            "members_count": getattr(entity, "participants_count", None), "private": False}


async def upsert_found(db, rows: list[dict[str, Any]]) -> set[str]:
    """Insert / refresh found channels; known values are never overwritten with blanks. Returns new keys."""
    if not rows:
        return set()
    rows = list({r["key"]: r for r in rows}.values())
    existing = set((await db.execute(select(FoundChannel.key).where(FoundChannel.key.in_([r["key"] for r in rows])))).scalars())
    cols = ["peer_id", "type", "title", "username", "invite_hash", "members_count", "about", "photo_id", "private", "checked_at"]
    for r in rows:
        stmt = sqlite_insert(FoundChannel).values({c: r.get(c) for c in ["key", *cols] if c in r} | {"found_at": utcnow()})
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={c: func.coalesce(stmt.excluded[c], FoundChannel.__table__.c[c]) for c in cols if c in r}))
    return {r["key"] for r in rows} - existing


async def add_links(db, links: set[tuple[str, int, str]]) -> None:
    rows = [{"key": k, "user_id": u, "via": v} for k, u, v in links]
    for i in range(0, len(rows), BATCH):
        await db.execute(sqlite_insert(FoundChannelLink).values(rows[i:i + BATCH]).on_conflict_do_nothing())


class ChannelFinder(Tool):
    id = TOOL_ID
    title = "Каналы пользователей"
    description = "Личные каналы из профилей, ссылки и @упоминания в bio"
    Input = FinderInput

    async def run(self, ctx: JobContext, params: FinderInput) -> dict[str, Any]:
        started = time.monotonic()
        client = await ctx.client()
        await ctx.update(force=True, phase="select")
        self.use_usernames = params.use_usernames
        self.ctx = ctx
        self.blocks = await load_blocks(ctx.account_id)  # bans left over from earlier runs
        stats: dict[str, Any] = {"via_username": 0, "waiting_username": 0, "checked": 0, "personal": 0, "with_bio_refs": 0, "no_access": 0, "senders": 0,
                                 "resolved": 0, "resolve_cached": 0, "deferred": 0, "details": 0, "new_channels": 0}
        self.entities: dict[int, Any] = {}  # channels seen this run, by marked id (for details / avatars)
        self.new_keys: set[str] = set()

        async with SessionLocal() as db:
            act = await active_jobs(db)
            jobs = [act[s] for s in params.source_ids if s in act] if params.source_ids else list(act.values())
            skip = await excluded_ids(db)
        if not jobs:
            raise RuntimeError("Нет источников: сначала добавьте каналы или чаты")

        if params.include_senders:
            await self._senders(jobs, stats)
        users = await self._candidates(jobs, params, skip)
        await ctx.update(force=True, phase="profiles", users_total=len(users), users_done=0, found=0)
        # phases are independent: one failing (network, unexpected Telegram error) doesn't lose the others
        failures: dict[str, str] = {}
        phases = [("profiles", lambda: self._profiles(ctx, client, users, stats))]
        if params.check_bio and params.resolve_mentions:
            phases.append(("resolve", lambda: self._resolve(ctx, client, stats)))
        if params.fetch_details:
            phases.append(("details", lambda: self._details(ctx, client, stats)))
        for name, phase in phases:
            try:
                await phase()
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("channel finder: phase %s failed", name)
                failures[name] = str(e) or type(e).__name__
        if failures and len(failures) == len(phases):
            raise RuntimeError("; ".join(f"{k}: {v}" for k, v in failures.items()))
        now = datetime.now(UTC)
        blocks = {k: v for k, v in self.blocks.items() if v > now}
        postponed = round(max(blocks.values()).timestamp() - now.timestamp()) if blocks else None

        async with SessionLocal() as db:
            total = (await db.execute(select(func.count()).select_from(FoundChannel))).scalar()
        result = stats | {"users_total": len(users), "found_total": total, "new_channels": len(self.new_keys),
                          "postponed_sec": postponed,
                          "blocked": {k: v.isoformat() for k, v in blocks.items()}, "failures": failures, "duration_sec": round(time.monotonic() - started, 1)}
        if params.download_avatars and self.entities:
            await ctx.set_result(result)
            await ctx.update(force=True, phase="avatars", avatars_total=len(self.entities), avatars_done=0)
            done = 0
            for e in self.entities.values():
                try:
                    await asyncio.wait_for(download_avatar(client, e), AVATAR_TIMEOUT)
                except Exception:
                    pass
                done += 1
                if done % 10 == 0:
                    await ctx.update(avatars_done=done)
        return result

    async def _call(self, kind: str, request_factory):
        """Run a request, sleeping through short FloodWaits (with a visible countdown). A long one
        blocks this kind of request for the rest of the run and for later runs until it expires."""
        until = self.blocks.get(kind)
        if until and until > datetime.now(UTC):
            raise Blocked(kind)
        backoff = iter(TRANSPORT_BACKOFF)
        while True:
            try:
                return await request_factory()
            except errors.InvalidBufferError as e:
                # HTTP 429 from the transport: "too many requests" without a FloodWait duration
                if getattr(e, "code", None) != 429:
                    raise
                wait = next(backoff, None)
                if wait is None:
                    self.blocks[kind] = datetime.now(UTC) + TRANSPORT_BLOCK
                    await _save_blocks(self.ctx.account_id, self.blocks)
                    await self.ctx.update(force=True, blocked={k: v.isoformat() for k, v in self.blocks.items()})
                    raise Blocked(kind) from e
                until = datetime.now(UTC) + timedelta(seconds=wait)
                await self.ctx.update(force=True, flood_wait_until=until.isoformat())
                await asyncio.sleep(wait)
                await self.ctx.update(force=True, flood_wait_until=None)
            except errors.FloodWaitError as e:
                until = datetime.now(UTC) + timedelta(seconds=e.seconds)
                if e.seconds > MAX_WAIT:
                    self.blocks[kind] = until
                    await _save_blocks(self.ctx.account_id, self.blocks)
                    await self.ctx.update(force=True, blocked={k: v.isoformat() for k, v in self.blocks.items()})
                    raise Blocked(kind) from e
                await self.ctx.update(force=True, flood_wait_until=until.isoformat())
                await asyncio.sleep(e.seconds + 1)
                await self.ctx.update(force=True, flood_wait_until=None)

    # ---------- who to check ----------

    async def _candidates(self, jobs: list[int], params: FinderInput, skip: set[int]) -> list[int]:
        async with SessionLocal() as db:
            rows = await sql(db, f"""
                SELECT p.peer_id FROM job_participants p JOIN tg_peers t ON t.id = p.peer_id
                WHERE p.job_id IN :jobs AND t.kind = 'user' AND NOT t.is_bot AND NOT t.is_deleted
                  {"AND p.comments > 0" if params.presence == "active" else ""}
                  {"" if params.recheck else "AND t.profile_checked_at IS NULL"}
                GROUP BY p.peer_id ORDER BY sum(p.comments) DESC, max(p.last_at) DESC""", jobs)
        return [r[0] for r in rows if r[0] not in skip][:params.limit]

    async def _senders(self, jobs: list[int], stats) -> None:
        """Channels that wrote in the sources as themselves: already known, no requests needed."""
        async with SessionLocal() as db:
            rows = await sql(db, """
                SELECT DISTINCT t.id, t.title, t.username, t.photo_id FROM job_participants p JOIN tg_peers t ON t.id = p.peer_id
                WHERE p.job_id IN :jobs AND t.kind = 'channel' AND p.comments > 0""", jobs)
            found = [{"key": str(r[0]), "peer_id": r[0], "title": r[1], "username": r[2], "photo_id": r[3]} for r in rows]
            self.new_keys |= await upsert_found(db, found)
            await add_links(db, {(f["key"], f["peer_id"], "sender") for f in found})
            await db.commit()
        stats["senders"] = len(found)

    # ---------- profiles ----------

    async def _profiles(self, ctx, client, users: list[int], stats) -> None:
        pending: list[tuple[int, Any]] = []  # (user id, UserFull response | None when unreadable)

        async def flush():
            if not pending:
                return
            now = utcnow()
            async with SessionLocal() as db:
                peers, found, links = [], [], set()
                for uid, res in pending:
                    if res is None:
                        await db.execute(update(TgPeer).where(TgPeer.id == uid).values(profile_checked_at=now))
                        continue
                    fu = res.full_user
                    chats = {utils.get_peer_id(c): c for c in res.chats}
                    peers += [u for u in res.users if u.id == uid]
                    personal = utils.get_peer_id(types.PeerChannel(fu.personal_channel_id)) if getattr(fu, "personal_channel_id", None) else None
                    if personal and isinstance(chats.get(personal), types.Channel):
                        ch = chats[personal]
                        self.entities[personal] = ch
                        found.append(found_row(ch))
                        links.add((str(personal), uid, "personal"))
                        stats["personal"] += 1
                    peers += list(chats.values())
                    if extract_refs(fu.about):
                        stats["with_bio_refs"] += 1
                    await db.execute(update(TgPeer).where(TgPeer.id == uid).values(
                        about=fu.about or None, personal_channel_id=personal, profile_checked_at=now))
                await _save_peer_rows(db, peers)
                self.new_keys |= await upsert_found(db, found)
                await add_links(db, links)
                await db.commit()
            pending.clear()

        async with SessionLocal() as db:
            hashes: dict[int, int] = {}
            names: dict[int, str] = {}
            for i in range(0, len(users), 900):
                chunk = users[i:i + 900]
                hashes |= dict((await db.execute(select(PeerAccess.peer_id, PeerAccess.access_hash).where(
                    PeerAccess.account_id == ctx.account_id, PeerAccess.peer_id.in_(chunk)))).all())
                names |= dict((await db.execute(select(TgPeer.id, TgPeer.username).where(
                    TgPeer.id.in_(chunk), TgPeer.username.is_not(None)))).all())

        async def address(uid: int):
            if uid in hashes:
                return types.InputUser(uid, hashes[uid])
            try:
                peer = await client.get_input_entity(types.PeerUser(uid))  # Telethon's in-memory cache
                return types.InputUser(peer.user_id, peer.access_hash)
            except (ValueError, TypeError, AttributeError):
                pass
            if self.use_usernames and uid in names:  # costs a ResolveUsername
                try:
                    peer = await self._call("resolve", lambda: client.get_input_entity(names[uid]))
                    if isinstance(peer, types.InputPeerUser) and peer.user_id == uid:
                        stats["via_username"] += 1
                        return types.InputUser(peer.user_id, peer.access_hash)
                except Blocked:
                    stats["waiting_username"] += 1  # not marked checked: retried once the ban ends
                except (ValueError, errors.RPCError):
                    pass
            return None

        try:
            for i, uid in enumerate(users, 1):
                peer = await address(uid)
                if peer is None:
                    stats["no_access"] += 1
                else:
                    try:
                        res = await self._call("full_user", lambda: client(functions.users.GetFullUserRequest(peer)))
                        pending.append((uid, res))
                    except Blocked:
                        break  # profiles are banned for now: the rest stay unchecked for the next run
                    except errors.RPCError:  # deactivated / invalid: nothing to read, don't retry
                        pending.append((uid, None))
                    stats["checked"] += 1
                if len(pending) >= 50:
                    await flush()
                if i % 10 == 0 or i == len(users):
                    await ctx.update(users_done=i, found=stats["personal"], no_access=stats["no_access"])
        finally:
            await flush()

    # ---------- bio mentions ----------

    async def _resolve(self, ctx, client, stats) -> None:
        """Resolve every bio reference not seen before (across all stored bios, so a postponed run
        picks up where it stopped) and link the channels / chats to the users mentioning them."""
        async with SessionLocal() as db:
            bios = (await db.execute(select(TgPeer.id, TgPeer.about, TgPeer.username).where(
                TgPeer.kind == "user", TgPeer.about.is_not(None)))).all()
            by_ref: dict[str, tuple[Ref, set[int]]] = {}
            for uid, about, own in bios:
                for ref in extract_refs(about):
                    if own and ref.username and ref.username.lower() == own.lower():
                        continue
                    by_ref.setdefault(ref.key, (ref, set()))[1].add(uid)
            cache = {r.username: r for r in (await db.execute(select(UsernameLookup).where(
                UsernameLookup.username.in_(list(by_ref) or [""])))).scalars()}
            # usernames of peers already in the DB need no request
            known = {u.lower(): (k, i) for i, k, u in (await db.execute(select(TgPeer.id, TgPeer.kind, TgPeer.username).where(
                func.lower(TgPeer.username).in_([k for k in by_ref if not k.startswith("+")] or [""])))).all()}
        todo = [k for k in by_ref if k not in cache]
        await ctx.update(force=True, phase="resolve", resolve_total=len(todo), resolve_done=0)
        stats["resolve_cached"] = len(by_ref) - len(todo)

        lookups: list[dict[str, Any]] = []
        found: list[dict[str, Any]] = []

        async def save():
            async with SessionLocal() as db:
                for row in lookups:
                    stmt = sqlite_insert(UsernameLookup).values(row)
                    await db.execute(stmt.on_conflict_do_update(index_elements=["username"], set_={
                        "kind": stmt.excluded.kind, "peer_id": stmt.excluded.peer_id, "checked_at": stmt.excluded.checked_at}))
                self.new_keys |= await upsert_found(db, found)
                await db.commit()
            lookups.clear()
            found.clear()

        try:
            for i, key in enumerate(todo, 1):
                ref, _users = by_ref[key]
                try:
                    kind, peer_id = await self._lookup(ctx, client, ref, known.get(key), found)
                except Blocked:
                    stats["deferred"] += 1  # not cached: looked up by a later run
                    continue
                lookups.append({"username": key, "kind": kind, "peer_id": peer_id, "checked_at": utcnow()})
                stats["resolved"] += 1
                if i % 20 == 0:
                    await save()
                    await ctx.update(resolve_done=i)
        finally:
            await save()
            await self._link_bio(by_ref)
            await ctx.update(force=True, resolve_done=stats["resolved"])

    async def _lookup(self, ctx, client, ref: Ref, known, found: list) -> tuple[str, int | None]:
        if known is not None:  # (kind, id) of a peer already in tg_peers
            kind, pid = known
            if kind == "user":
                return "user", pid
            found.append({"key": str(pid), "peer_id": pid, "username": ref.username})
            return ("channel" if kind == "channel" else "chat"), pid
        if ref.invite:
            try:
                inv = await self._call("invite", lambda: client(functions.messages.CheckChatInviteRequest(ref.invite)))
            except (errors.InviteHashExpiredError, errors.InviteHashInvalidError, errors.RPCError):
                return "none", None
            chat = getattr(inv, "chat", None)
            if chat is not None and _chat_kind(chat):
                self.entities[utils.get_peer_id(chat)] = chat
                found.append(found_row(chat) | {"invite_hash": ref.invite})
                return _chat_kind(chat), utils.get_peer_id(chat)
            if isinstance(inv, types.ChatInvite):
                kind = "channel" if inv.broadcast else "supergroup" if inv.megagroup else "group"
                found.append({"key": f"+{ref.invite}", "peer_id": None, "type": kind, "title": inv.title,
                              "invite_hash": ref.invite, "members_count": inv.participants_count,
                              "about": getattr(inv, "about", None), "private": True})
                return "invite", None
            return "none", None
        try:
            res = await self._call("resolve", lambda: client(functions.contacts.ResolveUsernameRequest(ref.username)))
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
            return "none", None
        except errors.RPCError:
            return "none", None
        async with SessionLocal() as db:
            await _save_peer_rows(db, [*res.users, *res.chats])
            await db.commit()
        peer = res.peer
        if isinstance(peer, types.PeerUser):
            return "user", peer.user_id
        chat = next((c for c in res.chats if utils.get_peer_id(c) == utils.get_peer_id(peer)), None)
        if chat is None or not _chat_kind(chat):
            return "none", None
        self.entities[utils.get_peer_id(chat)] = chat
        found.append(found_row(chat))
        return _chat_kind(chat), utils.get_peer_id(chat)

    async def _link_bio(self, by_ref: dict[str, tuple[Ref, set[int]]]) -> None:
        async with SessionLocal() as db:
            cache = {r.username: r for r in (await db.execute(select(UsernameLookup).where(
                UsernameLookup.username.in_(list(by_ref) or [""])))).scalars()}
            links = set()
            for key, (ref, users) in by_ref.items():
                hit = cache.get(key)
                if hit is None or hit.kind in ("user", "none"):
                    continue
                fkey = f"+{ref.invite}" if hit.kind == "invite" else str(hit.peer_id)
                links |= {(fkey, u, "bio") for u in users}
            present = set((await db.execute(select(FoundChannel.key).where(
                FoundChannel.key.in_(list({k for k, _, _ in links}) or [""])))).scalars())
            await add_links(db, {link for link in links if link[0] in present})
            await db.commit()

    # ---------- channel details ----------

    async def _details(self, ctx, client, stats) -> None:
        """Members count, description and exact type of found channels not checked recently."""
        async with SessionLocal() as db:
            stale = (await db.execute(select(FoundChannel).where(
                FoundChannel.peer_id.is_not(None), FoundChannel.private.is_(False),
                (FoundChannel.checked_at.is_(None)) | (FoundChannel.checked_at < utcnow() - DETAILS_TTL),
            ).limit(DETAILS_LIMIT))).scalars().all()
            hashes = dict((await db.execute(select(PeerAccess.peer_id, PeerAccess.access_hash).where(
                PeerAccess.account_id == ctx.account_id, PeerAccess.peer_id.in_([f.peer_id for f in stale] or [0])))).all())
        await ctx.update(force=True, phase="details", details_total=len(stale), details_done=0)
        for i, f in enumerate(stale, 1):
            entity = self.entities.get(f.peer_id)
            if entity is None and f.peer_id in hashes:
                entity = types.InputPeerChannel(int(str(f.peer_id)[4:]), hashes[f.peer_id])
            if entity is None:
                try:
                    entity = await client.get_input_entity(f.peer_id)
                except (ValueError, TypeError):
                    entity = None
            if entity is None and f.username:
                try:
                    entity = await self._call("resolve", lambda: client.get_entity(f.username))
                except Blocked:
                    continue  # stays unchecked until usernames can be looked up again
                except (ValueError, errors.RPCError):
                    entity = None
            row: dict[str, Any] = {"key": f.key, "checked_at": utcnow()}
            if entity is not None:
                try:
                    full = await self._call("full_channel", lambda: client(functions.channels.GetFullChannelRequest(entity)))
                    ch = next((c for c in full.chats if utils.get_peer_id(c) == f.peer_id), None)
                    if ch is not None:
                        self.entities[f.peer_id] = ch
                        row |= found_row(ch)
                    row |= {"members_count": full.full_chat.participants_count, "about": (full.full_chat.about or None)}
                    async with SessionLocal() as db:
                        await _save_peer_rows(db, full.chats)
                        await db.commit()
                    stats["details"] += 1
                except Blocked:
                    break
                except (errors.ChannelPrivateError, errors.ChannelInvalidError, errors.RPCError):
                    pass
            async with SessionLocal() as db:
                await upsert_found(db, [row])
                await db.commit()
            if i % 5 == 0:
                await ctx.update(details_done=i)
        await ctx.update(force=True, details_done=len(stale))


async def _save_peer_rows(db, entities: list[Any]) -> None:
    rows = [peer_row(e) for e in entities if isinstance(e, (types.User, types.Channel, types.Chat))]
    for r in rows:
        stmt = sqlite_insert(TgPeer).values(r)
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["id"], set_={c: stmt.excluded[c] for c in r if c != "id"} | {"updated_at": utcnow()}))
    await save_access(db, entities)


register(ChannelFinder())
