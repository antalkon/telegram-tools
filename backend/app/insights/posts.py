"""Collected channel posts, ads in them, and contacts found in texts (posts, descriptions, messages, bios)."""

from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.common import cards, sql
from app.insights.orgs import cached_many
from app.insights.sources import list_sources, message_link
from app.models import ChannelPost, TgPeer, iso
from app.telegram.contacts import extract_contacts, merge_contacts
from app.telegram.resolve import public_link


def _channel_filter(channel: str | int | None):
    """A channel by marked id or @username."""
    if channel is None or channel == "":
        return None
    s = str(channel).strip().lstrip("@")
    if s.lstrip("-").isdigit():
        return or_(ChannelPost.channel_id == int(s), ChannelPost.channel_key == s)
    return or_(ChannelPost.username == s.lower(), ChannelPost.channel_key == f"@{s.lower()}")


def post_out(p: ChannelPost) -> dict[str, Any]:
    return {
        "channel_key": p.channel_key, "channel_id": p.channel_id, "username": p.username, "post_id": p.post_id,
        "date": iso(p.date), "text": p.text, "views": p.views, "forwards": p.forwards, "replies": p.replies,
        "media": p.media, "links": p.links or [], "via": p.via,
        "forwarded_from": {"id": p.fwd_from, "name": p.fwd_from_name, "username": p.fwd_from_username}
        if (p.fwd_from or p.fwd_from_name or p.fwd_from_username) else None,
        "ad": {"erid": p.erid, "advertiser": p.advertiser, "inn": p.advertiser_inn} if (p.erid or p.advertiser_inn) else None,
        "link": public_link(p.username, p.channel_id or 0, p.post_id),
    }


async def post_channels(db: AsyncSession) -> list[dict[str, Any]]:
    """Channels with collected posts, newest collection first."""
    rows = (await db.execute(select(
        ChannelPost.channel_key, func.max(ChannelPost.channel_id), func.max(ChannelPost.username), func.count(),
        func.sum(func.iif(or_(ChannelPost.erid.is_not(None), ChannelPost.advertiser_inn.is_not(None)), 1, 0)),
        func.max(ChannelPost.collected_at), func.max(ChannelPost.date), func.min(ChannelPost.date),
        func.avg(ChannelPost.views), func.group_concat(func.distinct(ChannelPost.via)),
    ).group_by(ChannelPost.channel_key).order_by(func.max(ChannelPost.collected_at).desc()))).all()
    peers = {p.id: p for p in (await db.execute(select(TgPeer).where(
        TgPeer.id.in_([r[1] for r in rows if r[1]] or [0])))).scalars()}
    out = []
    for key, cid, username, n, ads, collected, newest, oldest, avg_views, via in rows:
        peer = peers.get(cid)
        out.append({"key": key, "channel_id": cid, "username": username,
                    "title": (peer.title if peer else None) or (f"@{username}" if username else key),
                    "posts": n, "ads": ads or 0, "collected_at": iso(collected), "newest": iso(newest), "oldest": iso(oldest),
                    "avg_views": round(avg_views) if avg_views else None, "via": (via or "").split(",")})
    return out


async def list_posts(db: AsyncSession, *, channel: str | int | None = None, q: str = "", ads_only: bool = False,
                     forwarded_only: bool = False, sort: str = "date", offset: int = 0, limit: int = 50) -> dict[str, Any]:
    stmt = select(ChannelPost)
    if (cond := _channel_filter(channel)) is not None:
        stmt = stmt.where(cond)
    if q.strip():
        stmt = stmt.where(func.ulower(ChannelPost.text).like(f"%{q.strip().lower()}%"))
    if ads_only:
        stmt = stmt.where(or_(ChannelPost.erid.is_not(None), ChannelPost.advertiser_inn.is_not(None)))
    if forwarded_only:
        stmt = stmt.where(or_(ChannelPost.fwd_from.is_not(None), ChannelPost.fwd_from_name.is_not(None)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {"views": ChannelPost.views.desc().nulls_last(), "forwards": ChannelPost.forwards.desc().nulls_last(),
             "oldest": ChannelPost.date.asc()}.get(sort, ChannelPost.date.desc())
    rows = (await db.execute(stmt.order_by(order).offset(offset).limit(limit))).scalars().all()
    return {"total": total, "items": [post_out(p) for p in rows]}


async def ads_summary(db: AsyncSession, channel: str | int | None = None) -> list[dict[str, Any]]:
    """Advertisers seen in ad-marked posts: how many posts, in which channels, last seen; with register data."""
    stmt = select(ChannelPost.advertiser_inn, func.max(ChannelPost.advertiser), func.count(),
                  func.count(func.distinct(ChannelPost.channel_key)), func.max(ChannelPost.date),
                  func.group_concat(func.distinct(ChannelPost.channel_key))).where(
        or_(ChannelPost.erid.is_not(None), ChannelPost.advertiser_inn.is_not(None)))
    if (cond := _channel_filter(channel)) is not None:
        stmt = stmt.where(cond)
    rows = (await db.execute(stmt.group_by(func.coalesce(ChannelPost.advertiser_inn, ChannelPost.advertiser))
                             .order_by(func.count().desc()).limit(200))).all()
    orgs = await cached_many(db, [r[0] for r in rows if r[0]])
    return [{"inn": inn, "advertiser": name, "posts": n, "channels": nch, "last_at": iso(last),
             "channel_keys": (keys or "").split(",")[:20], "org": (orgs.get(inn) or [None])[0] if inn else None}
            for inn, name, n, nch, last, keys in rows]


async def channel_contacts(db: AsyncSession, channel_id: int | None, username: str | None = None) -> dict[str, Any]:
    """Contacts in a channel's description and in its collected posts."""
    peer = await db.get(TgPeer, channel_id) if channel_id else None
    about = peer.about if peer else None
    items = [(extract_contacts(about), {"kind": "about"})] if about else []
    cond = _channel_filter(channel_id if channel_id else username)
    if cond is not None:
        for p in (await db.execute(select(ChannelPost.post_id, ChannelPost.text, ChannelPost.links, ChannelPost.username,
                                          ChannelPost.channel_id).where(cond).order_by(ChannelPost.date.desc()).limit(5000))).all():
            c = extract_contacts(p.text, p.links)
            c.pop("erid", None)  # ad tokens are listed with the ads
            if c:
                items.append((c, {"kind": "post", "post_id": p.post_id, "link": public_link(p.username, p.channel_id or 0, p.post_id)}))
    merged = merge_contacts(items)
    inns = [x["value"] for x in merged.get("inn", [])]
    orgs = await cached_many(db, inns)
    for x in merged.get("inn", []):
        x["org"] = (orgs.get(x["value"]) or [None])[0]
    return {"about": about, "contacts": merged}


async def user_contacts(db: AsyncSession, peer_id: int, jobs: list[int]) -> dict[str, Any]:
    """Contacts a person wrote in their bio and in their messages across sources."""
    peer = await db.get(TgPeer, peer_id)
    items = [(extract_contacts(peer.about), {"kind": "bio"})] if peer and peer.about else []
    by_job = {s["job_id"]: s for s in await list_sources(db, include_hidden=True)}
    rows = await sql(db, "SELECT job_id, msg_id, post_id, text FROM comments WHERE job_id IN :jobs AND sender_id = :p "
                         "AND text IS NOT NULL ORDER BY date DESC LIMIT 5000", jobs, p=peer_id)
    for job_id, msg_id, post_id, body in rows:
        c = extract_contacts(body)
        c.pop("erid", None)
        if c:
            s = by_job.get(job_id, {})
            items.append((c, {"kind": "message", "source": s.get("title"), "link": message_link(s, msg_id, post_id) if s else None}))
    merged = merge_contacts(items)
    orgs = await cached_many(db, [x["value"] for x in merged.get("inn", [])])
    for x in merged.get("inn", []):
        x["org"] = (orgs.get(x["value"]) or [None])[0]
    return merged


async def forward_sources(db: AsyncSession, channel_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Channels whose posts get forwarded most (in one channel's posts, or across everything collected)."""
    where = "WHERE fwd_from IS NOT NULL" + (" AND channel_id = :c" if channel_id else "")
    rows = (await db.execute(text(f"""
        SELECT fwd_from, max(fwd_from_name), max(fwd_from_username), count(*) FROM channel_posts {where}
        GROUP BY fwd_from ORDER BY count(*) DESC LIMIT :n"""), {"c": channel_id, "n": limit})).all()
    info = await cards(db, [r[0] for r in rows])
    return [info[r[0]] | {"fallback_name": r[1], "fallback_username": r[2], "posts": r[3]} for r in rows]
