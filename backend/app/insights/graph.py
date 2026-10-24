"""Whole-database views: the audience graph and the dashboard overview."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.common import active_jobs, cards, excluded_ids, sql
from app.insights.sources import _user_sets, list_sources
from app.models import Account, Job


async def audience_graph(db: AsyncSession, mode: str = "people", min_sources: int = 2, limit: int = 300,
                         source_ids: list[int] | None = None, family: str = "all", active_only: bool = False) -> dict[str, Any]:
    act = await active_jobs(db)
    if source_ids:
        act = {s: j for s, j in act.items() if s in source_ids}
    if family != "all":
        fam = {s["id"]: s["family"] for s in await list_sources(db)}
        act = {s: j for s, j in act.items() if fam.get(s) == family}
    by_job = {jid: sid for sid, jid in act.items()}
    sources = {s["id"]: s for s in await list_sources(db) if s["id"] in act}
    nodes = [{"id": f"s:{s['id']}", "type": "source", "peer_id": s["id"], "label": s["title"],
              "photo_id": s["photo_id"], "value": s["people"], "source_type": s["type"]} for s in sources.values()]

    if mode == "sources":
        sets = await _user_sets(db, act, active_only)
        ids = list(sets)
        links = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                shared = len(sets[a] & sets[b])
                if shared:
                    links.append({"source": f"s:{a}", "target": f"s:{b}", "kind": "shared", "weight": shared,
                                  "jaccard": round(shared / (len(sets[a] | sets[b]) or 1), 4)})
        return {"nodes": nodes, "links": links, "hidden_users": 0}

    rows = await sql(db, """
        SELECT peer_id, count(*) AS n, sum(comments) AS c FROM job_participants WHERE job_id IN :jobs AND comments >= :a
        GROUP BY peer_id HAVING count(*) >= :m ORDER BY n DESC, c DESC""", list(by_job), m=min_sources, a=1 if active_only else 0)
    skip = await excluded_ids(db)
    rows = [r for r in rows if r[0] not in skip]
    shown = rows[:limit]
    people = await cards(db, [r[0] for r in shown])
    for pid, n, c in shown:
        p = people[pid]
        nodes.append({"id": f"u:{pid}", "type": "user", "peer_id": pid, "label": p["name"], "photo_id": p["photo_id"],
                      "value": c, "sources": n})
    links = []
    if shown:
        ids = [r[0] for r in shown]
        for i in range(0, len(ids), 800):
            for pid, job_id, c in await sql(
                db, "SELECT peer_id, job_id, comments FROM job_participants WHERE job_id IN :jobs AND peer_id IN :ids AND comments >= :a",
                list(by_job), ids=ids[i:i + 800], a=1 if active_only else 0,
            ):
                links.append({"source": f"u:{pid}", "target": f"s:{by_job[job_id]}", "kind": "comments", "weight": c})
    return {"nodes": nodes, "links": links, "hidden_users": max(0, len(rows) - len(shown)), "matching_users": len(rows)}


async def overview(db: AsyncSession) -> dict[str, Any]:
    act = await active_jobs(db)
    jobs = list(act.values())
    skip = await excluded_ids(db)
    per = [r for r in await sql(db, "SELECT peer_id, count(*), sum(comments) FROM job_participants WHERE job_id IN :jobs GROUP BY peer_id", jobs)
           if r[0] not in skip]
    users, comments, multi = len(per), sum(r[2] for r in per), sum(1 for r in per if r[1] > 1)
    since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")
    daily = await sql(db, "SELECT date(date) AS d, count(*), count(DISTINCT sender_id) FROM comments "
                          "WHERE job_id IN :jobs AND date >= :since GROUP BY d ORDER BY d", jobs, since=since)
    top = [(p, c, n) for p, n, c in sorted(per, key=lambda r: -r[2])[:8]]
    top_multi = [(p, n, c) for p, n, c in sorted((r for r in per if r[1] > 1), key=lambda r: (-r[1], -r[2]))[:8]]
    info = await cards(db, [r[0] for r in top] + [r[0] for r in top_multi])
    srcs = await list_sources(db)
    return {
        "totals": {
            "sources": len(act),
            "channels": sum(1 for s in srcs if s["family"] == "channel"),
            "chats": sum(1 for s in srcs if s["family"] == "chat"),
            "members": sum(1 for r in per if r[2] == 0),
            "users": users,
            "comments": comments,
            "multi_source_users": multi,
            "jobs": (await db.execute(select(func.count()).select_from(Job))).scalar_one(),
            "accounts": (await db.execute(select(func.count()).select_from(Account))).scalar_one(),
        },
        "activity": {"bucket": "day", "points": [{"t": d, "comments": c, "users": u} for d, c, u in daily]},
        "top_users": [info[p] | {"comments": c, "sources": n} for p, c, n in top],
        "top_crossover": [info[p] | {"comments": c, "sources": n} for p, n, c in top_multi],
        "sources": srcs[:8],
    }
