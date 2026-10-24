"""Everyone found by any tool, merged across sources: list, profile, connections, ego graph."""

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.common import active_jobs, cards, exclusion_opts, excluded_ids, excluded_select, peer_card, sql
from app.insights.sources import heatmap, list_sources, message_link, thread_label, timeline
from app.models import JobParticipant, PeerNote, TgPeer, iso

SORTS = {
    "comments": "comments",
    "sources": "sources",
    "posts": "posts",
    "first_at": "first_at",
    "last_at": "last_at",
    "name": "name",
}


async def list_users(
    db: AsyncSession,
    *,
    search: str = "",
    sort: str = "-comments",
    min_sources: int = 1,
    source_id: int | None = None,
    tag: str | None = None,
    starred: bool = False,
    kind: str = "all",
    show_ignored: bool = False,
    presence: str = "all",
    family: str = "all",
    offset: int = 0,
    limit: int | None = 100,
) -> tuple[int, list[dict[str, Any]]]:
    """presence: all | active (wrote something) | silent (only in member lists).
    family: all | channel | chat — which sources count."""
    act = await active_jobs(db)
    if family != "all":
        fam = {s["id"]: s["family"] for s in await list_sources(db)}
        act = {sid: jid for sid, jid in act.items() if fam.get(sid) == family}
    jobs = list(act.values())
    agg = (
        select(
            JobParticipant.peer_id.label("peer_id"),
            func.sum(JobParticipant.comments).label("comments"),
            func.count().label("sources"),
            func.sum(JobParticipant.posts).label("posts"),
            func.min(JobParticipant.first_at).label("first_at"),
            func.max(JobParticipant.last_at).label("last_at"),
            func.max(cast(JobParticipant.member, Integer)).label("member"),
        )
        .where(JobParticipant.job_id.in_(jobs or [-1]))
        .group_by(JobParticipant.peer_id)
        .having(func.count() >= min_sources)
        .subquery()
    )
    name = func.ulower(func.coalesce(TgPeer.first_name, TgPeer.title, "") + " " + func.coalesce(TgPeer.last_name, ""))
    q = select(agg, TgPeer, PeerNote).outerjoin(TgPeer, TgPeer.id == agg.c.peer_id).outerjoin(PeerNote, PeerNote.peer_id == agg.c.peer_id)
    if show_ignored:
        q = q.where(PeerNote.ignored.is_(True))
    else:
        q = q.where(agg.c.peer_id.not_in(excluded_select(await exclusion_opts(db))))
    if source_id is not None and source_id in act:
        q = q.where(agg.c.peer_id.in_(select(JobParticipant.peer_id).where(JobParticipant.job_id == act[source_id])))
    if search:
        s = search.strip().lstrip("@").lower()
        like = f"%{s}%"
        conds = [func.ulower(TgPeer.username).like(like), name.like(like), func.ulower(TgPeer.title).like(like),
                 func.ulower(PeerNote.note).like(like)]
        if s.lstrip("-").isdigit():
            conds.append(agg.c.peer_id == int(s))
        q = q.where(or_(*conds))
    if tag:
        q = q.where(text("EXISTS (SELECT 1 FROM json_each(peer_notes.tags) WHERE json_each.value = :tag)").bindparams(tag=tag))
    if starred:
        q = q.where(PeerNote.starred.is_(True))
    if kind == "user":
        q = q.where(agg.c.peer_id > 0)
    elif kind == "channel":
        q = q.where(agg.c.peer_id < 0)
    if presence == "active":
        q = q.where(agg.c.comments > 0)
    elif presence == "silent":
        q = q.where(agg.c.comments == 0)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    key = sort.lstrip("-")
    col = name if key == "name" else agg.c[SORTS.get(key, "comments")]
    q = q.order_by(col.desc() if sort.startswith("-") else col.asc(), agg.c.peer_id).offset(offset)
    if limit is not None:
        q = q.limit(limit)
    rows = (await db.execute(q)).all()

    # which sources each listed user appears in
    by_job = {jid: sid for sid, jid in act.items()}
    ids = [r.peer_id for r in rows]
    where_sources: dict[int, list[int]] = {}
    if ids:
        for i in range(0, len(ids), 800):
            part = ids[i:i + 800]
            for peer_id, job_id in (await db.execute(
                select(JobParticipant.peer_id, JobParticipant.job_id)
                .where(JobParticipant.job_id.in_(jobs), JobParticipant.peer_id.in_(part))
                .order_by(JobParticipant.comments.desc()))).all():
                where_sources.setdefault(peer_id, []).append(by_job[job_id])
    out = []
    for r in rows:
        card = peer_card(r.TgPeer, r.peer_id, r.PeerNote)
        out.append(card | {
            "comments": r.comments, "sources": r.sources, "posts": r.posts, "member": bool(r.member),
            "first_at": iso(r.first_at), "last_at": iso(r.last_at),
            "source_ids": where_sources.get(r.peer_id, []),
            "note": r.PeerNote.note if r.PeerNote else None,
        })
    return total, out


async def _user_jobs(db: AsyncSession, peer_id: int) -> tuple[dict[int, int], list[int]]:
    act = await active_jobs(db)
    mine = (await db.execute(
        select(JobParticipant.job_id).where(JobParticipant.peer_id == peer_id, JobParticipant.job_id.in_(list(act.values()) or [-1]))
    )).scalars().all()
    return act, list(mine)


def _signals(texts: list[str | None], dates: list[str]) -> dict[str, Any]:
    """Cheap behavioural hints: spam/bot-like patterns and how a user writes."""
    n = len(texts)
    if not n:
        return {}
    words = [t for t in texts if t]
    lengths = [len(t) for t in words]
    common = Counter(t.strip().lower() for t in words if t.strip()).most_common(1)
    dup_text, dup_n = common[0] if common else (None, 0)
    per_day = Counter(d[:10] for d in dates)
    links = sum(1 for t in words if "http" in t or "t.me/" in t)
    score = 0
    if n >= 5 and dup_n / n > 0.3:
        score += 40
    if n >= 5 and links / n > 0.3:
        score += 30
    if per_day and max(per_day.values()) >= 50:
        score += 20
    if lengths and sum(lengths) / len(lengths) < 6 and n >= 10:
        score += 10
    return {
        "comments": n,
        "avg_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "media_only_share": round((n - len(words)) / n, 3),
        "duplicate_share": round(dup_n / n, 3),
        "top_duplicate": dup_text[:120] if dup_text and dup_n > 1 else None,
        "link_share": round(links / n, 3),
        "active_days": len(per_day),
        "max_per_day": max(per_day.values()) if per_day else 0,
        "spam_score": min(score, 100),
    }


async def user_profile(db: AsyncSession, peer_id: int) -> dict[str, Any] | None:
    act, jobs = await _user_jobs(db, peer_id)
    peer = await db.get(TgPeer, peer_id)
    if not jobs and peer is None:
        return None
    note = await db.get(PeerNote, peer_id)
    by_job = {jid: sid for sid, jid in act.items()}
    sources = {s["id"]: s for s in await list_sources(db)}
    per_source = []
    for jp in (await db.execute(select(JobParticipant).where(JobParticipant.peer_id == peer_id, JobParticipant.job_id.in_(jobs or [-1]))
                                .order_by(JobParticipant.comments.desc()))).scalars():
        s = sources.get(by_job[jp.job_id], {})
        rank = (await sql(db, "SELECT count(*) + 1 FROM job_participants WHERE job_id IN :jobs AND comments > :c", [jp.job_id], c=jp.comments))[0][0] \
            if jp.comments else None
        per_source.append({
            "source": s, "comments": jp.comments, "posts": jp.posts,
            "first_at": iso(jp.first_at), "last_at": iso(jp.last_at),
            "member": bool(jp.member), "role": jp.role,
            "rank": rank, "of": s.get("users"),
            "share": round(jp.comments / s["comments"], 4) if s.get("comments") else 0,
        })
    rows = await sql(db, "SELECT text, date FROM comments WHERE job_id IN :jobs AND sender_id = :p ORDER BY date DESC LIMIT 5000", jobs, p=peer_id)
    channels = await sql(db, """
        SELECT f.key, f.peer_id, f.title, f.username, f.invite_hash, f.type, f.members_count, f.private, group_concat(l.via)
        FROM found_channel_links l JOIN found_channels f ON f.key = l.key
        WHERE l.user_id = :p AND l.via != 'sender' GROUP BY f.key""", p=peer_id)
    sources_ids = set(await active_jobs(db, include_hidden=True))
    return {
        "peer": peer_card(peer, peer_id, note),
        "note": note.note if note else None,
        "about": peer.about if peer else None,
        "profile_checked_at": iso(peer.profile_checked_at) if peer else None,
        # channels found through this person: the one in the profile first, then bio mentions
        "channels": sorted(
            [{"key": k, "peer_id": pid, "title": t or (f"@{u}" if u else "Приватный"), "username": u, "type": ty,
              "members_count": m, "private": bool(pr), "via": via.split(","), "is_source": pid in sources_ids,
              "link": f"https://t.me/{u}" if u else f"https://t.me/+{inv}" if inv else None}
             for k, pid, t, u, inv, ty, m, pr, via in channels],
            key=lambda c: "personal" not in c["via"]),
        "totals": {
            "comments": sum(p["comments"] for p in per_source),
            "posts": sum(p["posts"] for p in per_source),
            "sources": len(per_source),
            "active_sources": sum(1 for p in per_source if p["comments"]),
            "member_of": sum(1 for p in per_source if p["member"]),
            "first_at": min((p["first_at"] for p in per_source if p["first_at"]), default=None),
            "last_at": max((p["last_at"] for p in per_source if p["last_at"]), default=None),
        },
        "sources": per_source,
        "signals": _signals([r[0] for r in rows], [str(r[1]) for r in rows]),
    }


async def user_activity(db: AsyncSession, peer_id: int) -> dict[str, Any]:
    _, jobs = await _user_jobs(db, peer_id)
    return {
        "timeline": await timeline(db, jobs, "auto", "AND sender_id = :p", p=peer_id),
        "heatmap": await heatmap(db, jobs, "AND sender_id = :p", p=peer_id),
    }


async def user_comments(db: AsyncSession, peer_id: int, source_id: int | None, limit: int = 100) -> list[dict[str, Any]]:
    act, jobs = await _user_jobs(db, peer_id)
    if source_id is not None:
        jobs = [j for j in jobs if act.get(source_id) == j]
    by_job = {jid: sid for sid, jid in act.items()}
    sources = {s["id"]: s for s in await list_sources(db)}
    rows = await sql(db, """
        SELECT c.job_id, c.msg_id, c.post_id, c.date, c.text, c.reply_to, t.sender_id
        FROM comments c LEFT JOIN comments t ON t.job_id = c.job_id AND t.msg_id = c.reply_to
        WHERE c.job_id IN :jobs AND c.sender_id = :p ORDER BY c.date DESC LIMIT :lim""", jobs, p=peer_id, lim=limit)
    reply_cards = await cards(db, {r[6] for r in rows if r[6] is not None})
    out = []
    for job_id, msg_id, post_id, date, text_, reply_to, reply_sender in rows:
        s = sources.get(by_job[job_id], {})
        out.append({
            "source": {"id": s.get("id"), "title": s.get("title"), "username": s.get("username"), "photo_id": s.get("photo_id"),
                       "type": s.get("type"), "family": s.get("family")},
            "msg_id": msg_id, "post_id": post_id, "date": iso(_dt(date)), "text": text_,
            "thread": thread_label(s, post_id) if s else None,
            "reply_to": reply_cards.get(reply_sender) if reply_sender is not None else None,
            "link": message_link(s, msg_id, post_id) if s else None,
        })
    return out


def _dt(v):
    return datetime.fromisoformat(v) if isinstance(v, str) else v


async def connections(db: AsyncSession, peer_id: int, limit: int = 30) -> dict[str, Any]:
    """People this user meets: under the same posts, and in direct reply chains."""
    _, jobs = await _user_jobs(db, peer_id)
    skip = await excluded_ids(db)
    fetch = limit + min(len(skip), 300)  # over-fetch so ignored people don't shorten the lists
    co = await sql(db, """
        WITH mine AS (SELECT DISTINCT job_id, post_id FROM comments WHERE job_id IN :jobs AND sender_id = :p)
        SELECT c.sender_id, count(DISTINCT c.job_id || ':' || c.post_id) AS shared, count(*) AS their_comments
        FROM comments c JOIN mine m ON c.job_id = m.job_id AND c.post_id = m.post_id
        WHERE c.sender_id != :p GROUP BY c.sender_id ORDER BY shared DESC, their_comments DESC LIMIT :lim""",
        jobs, p=peer_id, lim=fetch)
    my_posts = (await sql(db, "SELECT count(DISTINCT job_id || ':' || post_id) FROM comments WHERE job_id IN :jobs AND sender_id = :p", jobs, p=peer_id))[0][0] or 1
    replies = await sql(db, """
        SELECT other, sum(outgoing), sum(incoming) FROM (
            SELECT t.sender_id AS other, 1 AS outgoing, 0 AS incoming
            FROM comments c JOIN comments t ON t.job_id = c.job_id AND t.msg_id = c.reply_to
            WHERE c.job_id IN :jobs AND c.sender_id = :p
            UNION ALL
            SELECT c.sender_id, 0, 1
            FROM comments t JOIN comments c ON c.job_id = t.job_id AND c.reply_to = t.msg_id
            WHERE t.job_id IN :jobs AND t.sender_id = :p
        ) WHERE other != :p GROUP BY other ORDER BY sum(outgoing) + sum(incoming) DESC LIMIT :lim""",
        jobs, p=peer_id, lim=fetch)
    co = [r for r in co if r[0] not in skip][:limit]
    replies = [r for r in replies if r[0] not in skip][:limit]
    info = await cards(db, [r[0] for r in co] + [r[0] for r in replies])
    return {
        "co_commenters": [info[o] | {"shared_posts": s, "their_comments": n, "overlap": round(s / my_posts, 3)} for o, s, n in co],
        "dialogs": [info[o] | {"replied_to": out_, "replied_by": in_} for o, out_, in_ in replies],
    }


async def ego_graph(db: AsyncSession, peer_id: int, limit: int = 25) -> dict[str, Any]:
    """User -> channels they comment in -> people they meet there (threads + replies)."""
    act, jobs = await _user_jobs(db, peer_id)
    by_job = {jid: sid for sid, jid in act.items()}
    conn = await connections(db, peer_id, limit)
    people = {c["peer_id"]: c for c in conn["co_commenters"]}
    for d in conn["dialogs"][:15]:
        people.setdefault(d["peer_id"], d)
    me = (await cards(db, [peer_id]))[peer_id]
    sources = {s["id"]: s for s in await list_sources(db)}

    nodes = [{"id": f"u:{peer_id}", "type": "focus", "peer_id": peer_id, "label": me["name"], "photo_id": me["photo_id"], "value": 1}]
    links = []
    mine = (await db.execute(select(JobParticipant.job_id, JobParticipant.comments)
                             .where(JobParticipant.peer_id == peer_id, JobParticipant.job_id.in_(jobs or [-1])))).all()
    for job_id, c in mine:
        s = sources.get(by_job[job_id], {})
        nodes.append({"id": f"s:{s['id']}", "type": "source", "peer_id": s["id"], "label": s["title"], "photo_id": s.get("photo_id"),
                      "value": s.get("people", 1), "source_type": s.get("type")})
        links.append({"source": f"u:{peer_id}", "target": f"s:{s['id']}", "kind": "comments", "weight": c})
    for pid, p in people.items():
        nodes.append({"id": f"u:{pid}", "type": "user", "peer_id": pid, "label": p["name"], "photo_id": p["photo_id"], "value": p.get("shared_posts", 1)})
    if people:
        for pid, job_id, c in (await db.execute(select(JobParticipant.peer_id, JobParticipant.job_id, JobParticipant.comments)
                                                .where(JobParticipant.job_id.in_(jobs), JobParticipant.peer_id.in_(list(people))))).all():
            links.append({"source": f"u:{pid}", "target": f"s:{by_job[job_id]}", "kind": "comments", "weight": c})
    for c in conn["co_commenters"]:
        links.append({"source": f"u:{peer_id}", "target": f"u:{c['peer_id']}", "kind": "thread", "weight": c["shared_posts"]})
    for d in conn["dialogs"][:15]:
        links.append({"source": f"u:{peer_id}", "target": f"u:{d['peer_id']}", "kind": "reply", "weight": d["replied_to"] + d["replied_by"]})
    return {"nodes": nodes, "links": links}


async def set_note(db: AsyncSession, peer_id: int, tags: list[str] | None, note: str | None, starred: bool | None,
                   ignored: bool | None = None) -> PeerNote:
    obj = await db.get(PeerNote, peer_id) or PeerNote(peer_id=peer_id, tags=[])
    if ignored is not None:
        obj.ignored = ignored
    if tags is not None:
        obj.tags = sorted({t.strip()[:32] for t in tags if t.strip()})[:20]
    if note is not None:
        obj.note = note.strip()[:4000] or None
    if starred is not None:
        obj.starred = starred
    db.add(obj)
    await db.commit()
    return obj


async def all_tags(db: AsyncSession) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for tags in (await db.execute(select(PeerNote.tags))).scalars():
        counter.update(tags or [])
    return [{"tag": t, "count": n} for t, n in counter.most_common()]
