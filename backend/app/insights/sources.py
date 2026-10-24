"""Collected sources (channels and chats): list, per-source analytics and audience overlap."""

from datetime import datetime, timedelta
from itertools import combinations
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.common import COLLECTOR, active_jobs, cards, excluded_ids, hidden_sources, peers_by_id, photo, sql
from app.models import Job, JobParticipant, Monitor, iso
from app.telegram.resolve import public_link

# source type -> broad family used by filters
FAMILY = {"channel": "channel", "supergroup": "chat", "forum": "chat", "gigagroup": "chat", "group": "chat"}


def source_type_of(job: Job) -> str:
    ch = (job.result or {}).get("channel") or (job.progress or {}).get("channel") or {}
    return ch.get("type") or ("channel" if job.tool == COLLECTOR else "supergroup")


def thread_label(src: dict[str, Any], post_id: int) -> str:
    """Human name of a discussion: channel post, forum topic, or a day in a plain chat."""
    if src.get("thread_unit") == "topic":
        return (src.get("topics") or {}).get(str(post_id)) or f"Тема #{post_id}"
    if src.get("thread_unit") == "day":
        return (datetime(1970, 1, 1) + timedelta(days=post_id)).strftime("%d.%m.%Y")
    return f"Пост #{post_id}"


def message_link(src: dict[str, Any], msg_id: int, post_id: int) -> str | None:
    if src.get("family") == "channel":
        return f"https://t.me/{src['username']}/{post_id}?comment={msg_id}" if src.get("username") else None
    return public_link(src.get("username"), src["id"], msg_id)

BUCKETS = {
    "day": "date(date)",
    "week": "date(date, '-6 days', 'weekday 1')",
    "month": "strftime('%Y-%m-01', date)",
}


async def _user_sets(db: AsyncSession, jobs: dict[int, int], active_only: bool = False) -> dict[int, set[int]]:
    """source_id -> set of people found there (writers and, for chats, members)."""
    by_job = {jid: sid for sid, jid in jobs.items()}
    out: dict[int, set[int]] = {sid: set() for sid in jobs}
    skip = await excluded_ids(db)
    rows = await sql(db, "SELECT job_id, peer_id FROM job_participants WHERE job_id IN :jobs AND comments >= :a",
                     list(by_job), a=1 if active_only else 0)
    for job_id, peer_id in rows:
        if peer_id not in skip:
            out[by_job[job_id]].add(peer_id)
    return out


async def list_sources(db: AsyncSession, include_hidden: bool = False) -> list[dict[str, Any]]:
    act = await active_jobs(db, include_hidden)
    hidden = await hidden_sources(db) if include_hidden else set()
    if not act:
        return []
    jobs = {j.id: j for j in (await db.execute(select(Job).where(Job.id.in_(act.values())))).scalars()}
    stats = {
        r[0]: r[1:]
        for r in (
            await db.execute(
                select(JobParticipant.job_id, func.sum(cast(JobParticipant.comments > 0, Integer)), func.sum(JobParticipant.comments),
                       func.sum(cast(JobParticipant.member, Integer)), func.count())
                .where(JobParticipant.job_id.in_(act.values()))
                .group_by(JobParticipant.job_id)
            )
        ).all()
    }
    monitors = {m.source_id: m for m in (await db.execute(select(Monitor).where(Monitor.source_id.in_(act.keys())))).scalars()}
    running = {sid for (sid,) in (await db.execute(
        select(Job.source_id).where(Job.source_id.in_(act.keys()), Job.status.in_(("queued", "running"))))).all()}
    runs = dict(
        (await db.execute(select(Job.source_id, func.count()).where(Job.source_id.in_(act.keys())).group_by(Job.source_id))).all()
    )
    peers = await peers_by_id(db, act.keys())
    out = []
    for sid, jid in act.items():
        job = jobs[jid]
        res = job.result or {}
        ch = res.get("channel") or (job.progress or {}).get("channel") or {}
        users, comments, members, people = stats.get(jid, (0, 0, 0, 0))
        peer = peers.get(sid)
        kind = source_type_of(job)
        m = monitors.get(sid)
        username = ch.get("username") or (peer.username if peer else None)
        out.append({
            "id": sid,
            "type": kind,
            "family": FAMILY.get(kind, "chat"),
            "tool": job.tool,
            "title": ch.get("title") or (peer.title if peer else str(sid)),
            "username": username,
            "link": public_link(username, sid),
            "photo_id": photo(peer),
            "subscribers": ch.get("subscribers"),
            "group_title": ch.get("group_title"),
            "linked_channel": ch.get("linked_channel"),
            "job_id": jid,
            "partial": job.status != "done",
            "collected_at": res.get("updated_at") or iso(job.finished_at),
            "users": users or 0,  # people who wrote
            "members": members or 0,  # chats: people in the member list
            "people": people or 0,
            "comments": comments or 0,  # comments (channels) / messages (chats)
            "members_status": res.get("members_status"),
            "thread_unit": res.get("thread_unit") or "post",
            "topics": res.get("topics") or {},
            "posts_total": res.get("posts_total") or (job.progress or {}).get("posts_total"),
            "posts_with_comments": res.get("posts_with_comments"),
            "runs": runs.get(sid, 1),
            "hidden": sid in hidden,
            "running": sid in running,
            "options": {k: v for k, v in (job.input or {}).items() if k not in ("channel", "mode", "monitor_id")},
            "input": (job.input or {}).get("channel"),
            "monitor": {"id": m.id, "enabled": m.enabled, "interval_minutes": m.interval_minutes} if m else None,
        })
    out.sort(key=lambda s: -s["people"])
    return out


def _auto_bucket(first: str | None, last: str | None) -> str:
    if not first or not last:
        return "day"
    span = (datetime.fromisoformat(last[:19]) - datetime.fromisoformat(first[:19])).days
    return "day" if span <= 120 else "week" if span <= 900 else "month"


async def timeline(db: AsyncSession, jobs: list[int], bucket: str = "auto", where: str = "", **params) -> dict[str, Any]:
    if bucket not in BUCKETS:
        span = await sql(db, f"SELECT min(date), max(date) FROM comments WHERE job_id IN :jobs {where}", jobs, **params)
        bucket = _auto_bucket(*span[0]) if span else "day"
    rows = await sql(
        db,
        f"SELECT {BUCKETS[bucket]} AS b, count(*), count(DISTINCT sender_id) FROM comments "
        f"WHERE job_id IN :jobs {where} GROUP BY b ORDER BY b",
        jobs,
        **params,
    )
    return {"bucket": bucket, "points": [{"t": b, "comments": c, "users": u} for b, c, u in rows]}


async def heatmap(db: AsyncSession, jobs: list[int], where: str = "", **params) -> list[list[int]]:
    """7x24 matrix [weekday Mon=0][hour] in UTC; the client shifts it to local time."""
    grid = [[0] * 24 for _ in range(7)]
    rows = await sql(
        db,
        f"SELECT CAST(strftime('%w', date) AS INT), CAST(strftime('%H', date) AS INT), count(*) "
        f"FROM comments WHERE job_id IN :jobs {where} GROUP BY 1, 2",
        jobs,
        **params,
    )
    for wd, hour, n in rows:
        grid[(wd + 6) % 7][hour] = n  # SQLite: 0=Sunday
    return grid


async def source_analytics(db: AsyncSession, source_id: int) -> dict[str, Any] | None:
    act = await active_jobs(db, include_hidden=True)  # a hidden channel's own page still works
    job_id = act.get(source_id)
    if job_id is None:
        return None
    info = next(s for s in await list_sources(db, include_hidden=True) if s["id"] == source_id)
    hidden = await hidden_sources(db)
    jobs = [job_id]

    # who comments how much
    counts = [r[0] for r in await sql(db, "SELECT comments FROM job_participants WHERE job_id IN :jobs AND comments > 0 ORDER BY comments DESC", jobs)]
    total = sum(counts) or 1
    edges = [(1, 1, "1"), (2, 5, "2–5"), (6, 20, "6–20"), (21, 100, "21–100"), (101, 10**9, "100+")]
    distribution = [
        {"label": label, "users": sum(1 for c in counts if lo <= c <= hi), "comments": sum(c for c in counts if lo <= c <= hi)}
        for lo, hi, label in edges
    ]

    def top_share(frac: float) -> float:
        n = max(1, round(len(counts) * frac))
        return round(sum(counts[:n]) / total, 4) if counts else 0.0

    concentration = {"top1pct": top_share(0.01), "top10pct": top_share(0.10), "top10users": round(sum(counts[:10]) / total, 4) if counts else 0}

    seg = (await sql(db, """
        SELECT count(*),
               sum(CASE WHEN p.is_premium THEN 1 ELSE 0 END),
               sum(CASE WHEN p.username IS NOT NULL THEN 1 ELSE 0 END),
               sum(CASE WHEN p.is_bot THEN 1 ELSE 0 END),
               sum(CASE WHEN p.is_deleted THEN 1 ELSE 0 END),
               sum(CASE WHEN jp.peer_id < 0 THEN 1 ELSE 0 END)
        FROM job_participants jp LEFT JOIN tg_peers p ON p.id = jp.peer_id WHERE jp.job_id IN :jobs""", jobs))[0]
    segments = dict(zip(["total", "premium", "with_username", "bots", "deleted", "channels"], [x or 0 for x in seg]))

    username = info.get("username")

    def thread_link(pid: int, first_msg: int) -> str | None:
        if info["family"] == "channel":
            return f"https://t.me/{username}/{pid}" if username else None
        return public_link(username, source_id, pid if info["thread_unit"] == "topic" else first_msg)

    top_posts = [
        {"post_id": pid, "comments": c, "users": u, "first_at": f, "label": thread_label(info, pid), "link": thread_link(pid, m)}
        for pid, c, u, f, m in await sql(db, """
            SELECT post_id, count(*), count(DISTINCT sender_id), min(date), min(msg_id) FROM comments
            WHERE job_id IN :jobs GROUP BY post_id ORDER BY 2 DESC LIMIT 15""", jobs)
    ]
    roles = dict(await sql(db, "SELECT coalesce(role, 'member'), count(*) FROM job_participants WHERE job_id IN :jobs AND member GROUP BY 1", jobs))
    audience = {
        "members": info["members"], "authors": info["users"],
        "silent": (await sql(db, "SELECT count(*) FROM job_participants WHERE job_id IN :jobs AND member AND comments = 0", jobs))[0][0],
        "outside": (await sql(db, "SELECT count(*) FROM job_participants WHERE job_id IN :jobs AND NOT member AND comments > 0", jobs))[0][0],
        "admins": roles.get("admin", 0) + roles.get("creator", 0),
    }

    # monthly active commenters split into first-timers vs returning
    active = dict(await sql(db, "SELECT strftime('%Y-%m', date), count(DISTINCT sender_id) FROM comments WHERE job_id IN :jobs GROUP BY 1", jobs))
    new = dict(await sql(db, "SELECT strftime('%Y-%m', first_at), count(*) FROM job_participants WHERE job_id IN :jobs AND first_at IS NOT NULL GROUP BY 1", jobs))
    cohorts = [{"month": m, "new": new.get(m, 0), "returning": max(0, a - new.get(m, 0))} for m, a in sorted(active.items())]

    skip = await excluded_ids(db)
    top_rows = [r for r in await sql(
        db, "SELECT peer_id, comments, posts FROM job_participants WHERE job_id IN :jobs AND comments > 0 ORDER BY comments DESC LIMIT :n",
        jobs, n=10 + len(skip),
    ) if r[0] not in skip][:10]
    top_cards = await cards(db, [r[0] for r in top_rows])
    tops = [top_cards[pid] | {"comments": c, "posts": p} for pid, c, p in top_rows]

    return {
        "source": info,
        "timeline": await timeline(db, jobs),
        "heatmap": await heatmap(db, jobs),
        "distribution": distribution,
        "concentration": concentration,
        "segments": segments,
        "top_posts": top_posts,
        "audience": audience,
        "cohorts": cohorts,
        "top_users": tops,
        "overlap": await overlap_with(db, source_id, {s: j for s, j in act.items() if s == source_id or s not in hidden}),
    }


async def overlap_with(db: AsyncSession, source_id: int, act: dict[int, int]) -> list[dict[str, Any]]:
    sets = await _user_sets(db, act)
    mine = sets.get(source_id, set())
    out = []
    for sid, users in sets.items():
        if sid == source_id:
            continue
        shared = len(mine & users)
        if shared:
            out.append({"id": sid, "shared": shared, "jaccard": round(shared / len(mine | users), 4),
                        "share_of_mine": round(shared / len(mine), 4) if mine else 0})
    out.sort(key=lambda r: -r["shared"])
    return out


async def overlap_matrix(db: AsyncSession, ids: list[int] | None, active_only: bool = False) -> dict[str, Any]:
    act = await active_jobs(db)
    if ids:
        act = {sid: jid for sid, jid in act.items() if sid in ids}
    sets = await _user_sets(db, act, active_only)
    order = sorted(sets, key=lambda s: -len(sets[s]))
    pairs = []
    for a, b in combinations(order, 2):
        shared = len(sets[a] & sets[b])
        union = len(sets[a] | sets[b]) or 1
        pairs.append({"a": a, "b": b, "shared": shared, "jaccard": round(shared / union, 4)})
    counts: dict[int, int] = {}
    for users in sets.values():
        for u in users:
            counts[u] = counts.get(u, 0) + 1
    in_n = {}
    for n in counts.values():
        in_n[n] = in_n.get(n, 0) + 1
    return {
        "sources": [{"id": s, "users": len(sets[s])} for s in order],
        "pairs": pairs,
        "users_by_source_count": [{"sources": k, "users": v} for k, v in sorted(in_n.items())],
        "total_users": len(counts),
    }


async def overlap_users(db: AsyncSession, ids: list[int], min_sources: int | None = None,
                        active_only: bool = False) -> list[dict[str, Any]]:
    """Users present in at least `min_sources` of `ids` (default: all of them)."""
    act = {sid: jid for sid, jid in (await active_jobs(db)).items() if sid in ids}
    by_job = {jid: sid for sid, jid in act.items()}
    need = min(min_sources or len(act), len(act)) if act else 1
    rows = await sql(db, "SELECT peer_id, job_id, comments FROM job_participants WHERE job_id IN :jobs AND comments >= :a",
                     list(by_job), a=1 if active_only else 0)
    skip = await excluded_ids(db)
    per: dict[int, dict[int, int]] = {}
    for peer_id, job_id, comments in rows:
        if peer_id in skip:
            continue
        per.setdefault(peer_id, {})[by_job[job_id]] = comments
    hits = {p: m for p, m in per.items() if len(m) >= need}
    info = await cards(db, hits)
    out = [info[p] | {"sources": len(m), "comments": sum(m.values()), "by_source": {str(k): v for k, v in m.items()}}
           for p, m in hits.items()]
    out.sort(key=lambda r: (-r["sources"], -r["comments"]))
    return out
