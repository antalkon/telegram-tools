from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobParticipant, TgPeer, iso
from app.telegram.peers import avatar_path

SORTS = {
    "comments": JobParticipant.comments,
    "posts": JobParticipant.posts,
    "first_at": JobParticipant.first_at,
    "last_at": JobParticipant.last_at,
    "name": func.ulower(func.coalesce(TgPeer.first_name, TgPeer.title, "")),
    "username": func.ulower(func.coalesce(TgPeer.username, "")),
}


def _display_name(p: TgPeer | None) -> str:
    if p is None:
        return "Неизвестно"
    if p.kind != "user":
        return p.title or "Канал"
    if p.is_deleted:
        return "Удалённый аккаунт"
    return " ".join(x for x in (p.first_name, p.last_name) if x) or "Без имени"


def _row(part: JobParticipant, peer: TgPeer | None) -> dict[str, Any]:
    username = peer.username if peer else None
    has_avatar = bool(peer and peer.photo_id and avatar_path(peer.photo_id).exists())
    return {
        "peer_id": part.peer_id,
        "kind": peer.kind if peer else ("user" if part.peer_id > 0 else "channel"),
        "name": _display_name(peer),
        "first_name": peer.first_name if peer else None,
        "last_name": peer.last_name if peer else None,
        "username": username,
        "usernames": peer.usernames if peer else [],
        "link": f"https://t.me/{username}" if username else None,
        "phone": peer.phone if peer else None,
        "photo_id": str(peer.photo_id) if has_avatar else None,
        "comments": part.comments,
        "posts": part.posts,
        "first_at": iso(part.first_at),
        "last_at": iso(part.last_at),
        "is_bot": bool(peer and peer.is_bot),
        "is_premium": bool(peer and peer.is_premium),
        "is_verified": bool(peer and peer.is_verified),
        "is_scam": bool(peer and (peer.is_scam or peer.is_fake)),
        "is_deleted": bool(peer and peer.is_deleted),
        "member": bool(part.member),
        "role": part.role,
    }


async def list_participants(
    db: AsyncSession,
    job_id: int,
    *,
    search: str = "",
    sort: str = "-comments",
    kind: str = "all",
    presence: str = "all",
    offset: int = 0,
    limit: int | None = 100,
) -> tuple[int, list[dict[str, Any]]]:
    q = (
        select(JobParticipant, TgPeer)
        .outerjoin(TgPeer, TgPeer.id == JobParticipant.peer_id)
        .where(JobParticipant.job_id == job_id)
    )
    if search:
        s = search.strip().lstrip("@").lower()
        like = f"%{s}%"
        conds = [
            func.ulower(TgPeer.username).like(like),
            func.ulower(TgPeer.first_name).like(like),
            func.ulower(TgPeer.last_name).like(like),
            func.ulower(TgPeer.title).like(like),
        ]
        if s.lstrip("-").isdigit():
            conds.append(JobParticipant.peer_id == int(s))
        q = q.where(or_(*conds))
    if kind == "user":
        q = q.where(JobParticipant.peer_id > 0)
    elif kind == "channel":
        q = q.where(JobParticipant.peer_id < 0)
    if presence == "active":
        q = q.where(JobParticipant.comments > 0)
    elif presence == "silent":
        q = q.where(JobParticipant.comments == 0)
    elif presence == "admins":
        q = q.where(JobParticipant.role.in_(("admin", "creator")))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()

    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"), JobParticipant.comments)
    q = q.order_by(col.desc() if desc else col.asc(), JobParticipant.peer_id)
    q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    rows = (await db.execute(q)).all()
    return total, [_row(part, peer) for part, peer in rows]
