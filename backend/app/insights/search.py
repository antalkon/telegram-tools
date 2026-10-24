"""Full-text search over every indexed message and comment (SQLite FTS5)."""

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.common import active_jobs, cards, exclusion_opts, sql
from app.insights.sources import list_sources, message_link, thread_label
from app.models import iso
from app.insights.users import _dt

HL_START, HL_END = "\x02", "\x03"  # highlight markers, split on the client (no HTML in the API)


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


def _excluded_sql(opts: dict[str, bool]) -> str:
    parts = ["SELECT peer_id FROM peer_notes WHERE ignored"]
    if opts.get("hide_bots"):
        parts.append("SELECT id FROM tg_peers WHERE is_bot")
    if opts.get("hide_deleted"):
        parts.append("SELECT id FROM tg_peers WHERE is_deleted")
    if opts.get("hide_channels"):
        parts.append("SELECT id FROM tg_peers WHERE kind != 'user'")
    return " UNION ".join(parts)


async def search_messages(
    db: AsyncSession,
    *,
    q: str = "",
    source_ids: list[int] | None = None,
    family: str = "all",
    sender_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "relevance",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    srcs = {s["id"]: s for s in await list_sources(db)}
    act = await active_jobs(db)
    if family != "all":
        act = {sid: jid for sid, jid in act.items() if srcs.get(sid, {}).get("family") == family}
    scope = act  # facets show every source in scope, before the source filter
    if source_ids:
        act = {sid: jid for sid, jid in act.items() if sid in source_ids}
    by_job = {jid: sid for sid, jid in scope.items()}
    match = fts_query(q) if q.strip() else None
    if q.strip() and match is None:
        return {"total": 0, "items": [], "facets": [], "top_senders": [], "query": None}

    where = ["c.job_id IN :jobs", f"c.sender_id NOT IN ({_excluded_sql(await exclusion_opts(db))})"]
    params: dict[str, Any] = {}
    if sender_id is not None:
        where.append("c.sender_id = :sender")
        params["sender"] = sender_id
    if date_from:
        where.append("c.date >= :dfrom")
        params["dfrom"] = date_from.isoformat()
    if date_to:
        where.append("c.date < :dto")
        params["dto"] = (date_to + timedelta(days=1)).isoformat()
    if match:
        frm = "comments_fts JOIN comments c ON c.rowid = comments_fts.rowid"
        where.insert(0, "comments_fts MATCH :match")
        params["match"] = match
        text_col = f"highlight(comments_fts, 0, '{HL_START}', '{HL_END}')"
    else:
        frm = "comments c"
        where.append("c.text IS NOT NULL")
        text_col = "c.text"
    cond = " AND ".join(where)
    order = {"newest": "c.date DESC", "oldest": "c.date ASC"}.get(sort, "bm25(comments_fts)" if match else "c.date DESC")

    jobs = list(act.values())
    total = (await sql(db, f"SELECT count(*) FROM {frm} WHERE {cond}", jobs, **params))[0][0]
    rows = await sql(db, f"""
        SELECT c.job_id, c.msg_id, c.post_id, c.sender_id, c.date, {text_col}
        FROM {frm} WHERE {cond} ORDER BY {order} LIMIT :lim OFFSET :off""", jobs, lim=limit, off=offset, **params)
    facets = await sql(db, f"SELECT c.job_id, count(*) FROM {frm} WHERE {cond} GROUP BY c.job_id ORDER BY 2 DESC",
                       list(scope.values()), **params) if match or sender_id or date_from or date_to else []
    senders = await sql(db, f"SELECT c.sender_id, count(*) FROM {frm} WHERE {cond} GROUP BY c.sender_id ORDER BY 2 DESC LIMIT 8",
                        jobs, **params) if match else []

    people = await cards(db, [r[3] for r in rows] + [r[0] for r in senders])
    items = []
    for job_id, msg_id, post_id, sender, dt, body in rows:
        s = srcs.get(by_job.get(job_id), {})
        items.append({
            "job_id": job_id, "msg_id": msg_id, "post_id": post_id, "date": iso(_dt(dt)), "text": body,
            "sender": people[sender],
            "source": {k: s.get(k) for k in ("id", "title", "username", "photo_id", "type", "family")},
            "thread": thread_label(s, post_id) if s else None,
            "link": message_link(s, msg_id, post_id) if s else None,
        })
    return {
        "total": total,
        "items": items,
        "query": match,
        "facets": [{"source_id": by_job[j], "title": srcs.get(by_job[j], {}).get("title"), "count": n}
                   for j, n in facets if j in by_job],
        "top_senders": [people[p] | {"count": n} for p, n in senders],
    }


async def message_context(db: AsyncSession, job_id: int, msg_id: int, around: int = 6) -> dict[str, Any]:
    """Messages around one hit: the same comment thread for channels, neighbours for chats."""
    srcs = {s["job_id"]: s for s in await list_sources(db, include_hidden=True)}
    s = srcs.get(job_id, {})
    same_thread = "AND post_id = (SELECT post_id FROM comments WHERE job_id = :j AND msg_id = :m)" if s.get("family") == "channel" else ""
    before = await sql(db, f"SELECT msg_id, sender_id, date, text, post_id, reply_to FROM comments WHERE job_id = :j AND msg_id < :m {same_thread} "
                           "ORDER BY msg_id DESC LIMIT :n", j=job_id, m=msg_id, n=around)
    after = await sql(db, f"SELECT msg_id, sender_id, date, text, post_id, reply_to FROM comments WHERE job_id = :j AND msg_id >= :m {same_thread} "
                          "ORDER BY msg_id LIMIT :n", j=job_id, m=msg_id, n=around + 1)
    rows = list(reversed(before)) + list(after)
    people = await cards(db, [r[1] for r in rows])
    return {"items": [{"msg_id": m, "sender": people[p], "date": iso(_dt(d)), "text": t, "focus": m == msg_id,
                       "reply_to": r, "link": message_link(s, m, pid) if s else None} for m, p, d, t, pid, r in rows]}
