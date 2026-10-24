"""Shared building blocks for cross-source insights.

A *source* is a chat collected by a tool: a channel (its comments, by the comment collector) or a
group / supergroup / forum (its messages and members, by the chat indexer). A source can be
collected many times; insights always use one job per source — the latest finished run, falling
back to the latest stopped (partial) run.
"""

import re
from typing import Any

from sqlalchemy import bindparam, func, or_, select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, PeerNote, Setting, TgPeer
from app.tools.comment_collector.queries import _display_name
from app.telegram.peers import avatar_path

COLLECTOR = "comment-collector"
INDEXER = "chat-indexer"
SOURCE_TOOLS = (COLLECTOR, INDEXER)


EXCLUSIONS_KEY = "exclusions"
EXCLUSION_DEFAULTS = {"hide_bots": False, "hide_deleted": False, "hide_channels": False}


async def exclusion_opts(db: AsyncSession) -> dict[str, bool]:
    row = await db.get(Setting, EXCLUSIONS_KEY)
    return EXCLUSION_DEFAULTS | (row.value if row else {})


def excluded_select(opts: dict[str, bool]):
    """Peer ids left out of analytics: ignored by hand plus the automatic categories."""
    parts = [select(PeerNote.peer_id.label("id")).where(PeerNote.ignored.is_(True))]
    conds = []
    if opts.get("hide_bots"):
        conds.append(TgPeer.is_bot.is_(True))
    if opts.get("hide_deleted"):
        conds.append(TgPeer.is_deleted.is_(True))
    if opts.get("hide_channels"):
        conds.append(TgPeer.kind != "user")
    if conds:
        parts.append(select(TgPeer.id.label("id")).where(or_(*conds)))
    return union(*parts) if len(parts) > 1 else parts[0]


async def excluded_ids(db: AsyncSession) -> set[int]:
    return set((await db.execute(excluded_select(await exclusion_opts(db)))).scalars())


async def starred_ids(db: AsyncSession) -> set[int]:
    """Favourites: people, sources and channels marked with a star (all share PeerNote.starred)."""
    return set((await db.execute(select(PeerNote.peer_id).where(PeerNote.starred.is_(True)))).scalars())


async def hidden_sources(db: AsyncSession) -> set[int]:
    return set((await db.execute(select(PeerNote.peer_id).where(PeerNote.ignored.is_(True), PeerNote.peer_id < 0))).scalars())


async def active_jobs(db: AsyncSession, include_hidden: bool = False) -> dict[int, int]:
    """source_id -> job_id used for insights (hidden channels left out unless asked for)."""
    rows = (
        await db.execute(
            select(Job.id, Job.source_id, Job.status)
            .where(
                Job.tool.in_(SOURCE_TOOLS),
                Job.source_id.is_not(None),
                Job.status.in_(("done", "cancelled")),
                # incremental runs append into their base job instead of holding a snapshot
                func.coalesce(func.json_extract(Job.input, "$.mode"), "full") != "incremental",
            )
            .order_by(Job.id)
        )
    ).all()
    best: dict[int, tuple[int, str]] = {}
    for job_id, source_id, status in rows:
        cur = best.get(source_id)
        if cur is None or status == "done" or cur[1] != "done":
            best[source_id] = (job_id, status)
    hidden = set() if include_hidden else await hidden_sources(db)
    return {sid: jid for sid, (jid, _) in best.items() if sid not in hidden}


def photo(peer: TgPeer | None) -> str | None:
    return str(peer.photo_id) if peer and peer.photo_id and avatar_path(peer.photo_id).exists() else None


def peer_card(peer: TgPeer | None, peer_id: int, note: PeerNote | None = None) -> dict[str, Any]:
    card = {
        "peer_id": peer_id,
        "kind": peer.kind if peer else ("user" if peer_id > 0 else "channel"),
        "name": _display_name(peer),
        "username": peer.username if peer else None,
        "usernames": peer.usernames if peer else [],
        "photo_id": photo(peer),
        "phone": peer.phone if peer else None,
        "is_bot": bool(peer and peer.is_bot),
        "is_premium": bool(peer and peer.is_premium),
        "is_verified": bool(peer and peer.is_verified),
        "is_scam": bool(peer and (peer.is_scam or peer.is_fake)),
        "is_deleted": bool(peer and peer.is_deleted),
    }
    card["link"] = f"https://t.me/{card['username']}" if card["username"] else None
    card["tags"] = note.tags if note else []
    card["starred"] = bool(note and note.starred)
    card["ignored"] = bool(note and note.ignored)
    return card


async def peers_by_id(db: AsyncSession, ids) -> dict[int, TgPeer]:
    ids = list(ids)
    out: dict[int, TgPeer] = {}
    for i in range(0, len(ids), 900):  # SQLite variable limit
        for p in (await db.execute(select(TgPeer).where(TgPeer.id.in_(ids[i:i + 900])))).scalars():
            out[p.id] = p
    return out


async def notes_by_id(db: AsyncSession, ids) -> dict[int, PeerNote]:
    ids = list(ids)
    out: dict[int, PeerNote] = {}
    for i in range(0, len(ids), 900):
        for n in (await db.execute(select(PeerNote).where(PeerNote.peer_id.in_(ids[i:i + 900])))).scalars():
            out[n.peer_id] = n
    return out


async def cards(db: AsyncSession, ids) -> dict[int, dict[str, Any]]:
    ids = list(dict.fromkeys(ids))
    peers = await peers_by_id(db, ids)
    notes = await notes_by_id(db, ids)
    return {i: peer_card(peers.get(i), i, notes.get(i)) for i in ids}


async def sql(db: AsyncSession, query: str, jobs: list[int] | None = None, **params) -> list[Any]:
    """Run raw SQL; `:jobs` and any other list parameter expand into `IN (...)` lists."""
    if jobs is not None:
        params["jobs"] = jobs
    stmt = text(query)
    for name, value in params.items():
        if isinstance(value, (list, tuple, set)):
            params[name] = list(value) or [-1]  # IN () is a syntax error in SQLite
            stmt = stmt.bindparams(bindparam(name, expanding=True))
    return (await db.execute(stmt, params)).all()


def fts_query(raw: str) -> str | None:
    """User syntax -> FTS5: words match by prefix, "quoted phrases" exactly, -word excludes."""
    phrases = re.findall(r'"([^"]+)"', raw)
    rest = re.sub(r'"[^"]*"', " ", raw)
    must, never = [], []
    for p in phrases:
        words = re.findall(r"\w+", p)
        if words:
            must.append('"' + " ".join(words) + '"')
    for tok in rest.split():
        neg = tok.startswith("-") and len(tok) > 1
        for w in re.findall(r"\w+", tok):
            (never if neg else must).append(f'"{w}"*')
    if not must:
        return None
    q = " AND ".join(must)
    for n in never:
        q += f" NOT {n}"
    return q
