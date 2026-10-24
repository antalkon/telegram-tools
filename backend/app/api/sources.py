"""Sources as one concept: add by link (any type), re-run with options, search their messages."""

import os
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.insights import _file, _ids
from app.api.jobs import job_out
from app.config import get_settings
from app.db import get_db, rebuild_search_index
from app.insights import search
from app.insights.common import SOURCE_TOOLS, active_jobs
from app.jobs.runner import runner
from app.jobs.scheduler import _pick_account
from app.models import Job
from app.security import require_admin
from app.telegram.links import LinkError, parse_channel_link
from app.telegram.manager import manager
from app.telegram.resolve import UserFacingError, preview
from app.tools.base import get_tool

router = APIRouter(tags=["sources"], dependencies=[Depends(require_admin)])

# options a user may change per run, by tool (everything else comes from the tool's defaults)
OPTION_KEYS = {
    "comment-collector": {"strategy", "download_avatars"},
    "chat-indexer": {"since", "max_messages", "index_messages", "collect_members", "download_avatars"},
}


class ResolveIn(BaseModel):
    link: str = Field(min_length=1, max_length=256)
    account_id: int | None = None


async def _account(db: AsyncSession, preferred: int | None) -> int:
    acc = await _pick_account(db, preferred)
    if acc is None:
        raise HTTPException(400, "Нет активного Telegram-аккаунта — подключите его в «Аккаунтах»")
    return acc


@router.post("/sources/resolve")
async def resolve_source(body: ResolveIn, db: AsyncSession = Depends(get_db)):
    """What the link points to (type, size, member visibility) — read-only, nothing is collected."""
    try:
        ref = parse_channel_link(body.link)
    except LinkError as e:
        raise HTTPException(422, str(e)) from e
    client = await manager.get_client(await _account(db, body.account_id))
    try:
        info = await preview(client, ref)
    except UserFacingError as e:
        raise HTTPException(400, str(e)) from e
    act = await active_jobs(db, include_hidden=True)
    info["exists"] = info["id"] in act
    if info["linked_chat"]:
        info["linked_chat"]["exists"] = info["linked_chat"]["id"] in act
    return info


class AddIn(BaseModel):
    link: str = Field(min_length=1, max_length=256)
    tool: Literal["comment-collector", "chat-indexer"]
    account_id: int | None = None
    options: dict[str, Any] = {}
    # channels: also index the discussion group as a chat
    linked_link: str | None = Field(None, max_length=256)


def _params(tool: str, link: str, mode: str, options: dict[str, Any]) -> dict[str, Any]:
    params = {"channel": link, "mode": mode} | {k: v for k, v in options.items() if k in OPTION_KEYS[tool]}
    try:
        return get_tool(tool).Input.model_validate(params).model_dump(mode="json", exclude_none=True)
    except ValidationError as e:
        raise HTTPException(422, "; ".join(str(err["msg"]) for err in e.errors())) from e


@router.post("/sources/add")
async def add_source(body: AddIn, db: AsyncSession = Depends(get_db)):
    account = await _account(db, body.account_id)
    jobs = [await runner.submit(body.tool, account, _params(body.tool, body.link, "full", body.options))]
    if body.linked_link and body.tool == "comment-collector":
        chat_opts = {k: v for k, v in body.options.items() if k in OPTION_KEYS["chat-indexer"]}
        jobs.append(await runner.submit("chat-indexer", account, _params("chat-indexer", body.linked_link, "full", chat_opts)))
    return [job_out(j) for j in jobs]


class RunIn(BaseModel):
    mode: Literal["full", "incremental"] = "incremental"
    options: dict[str, Any] = {}
    account_id: int | None = None


@router.post("/sources/{source_id}/run")
async def run_source(source_id: int, body: RunIn, db: AsyncSession = Depends(get_db)):
    """Дозабор (incremental) or full re-index of a known source, reusing its last settings."""
    job_id = (await active_jobs(db, include_hidden=True)).get(source_id)
    base = await db.get(Job, job_id) if job_id else None
    if base is None:
        raise HTTPException(404, "Источник не найден")
    running = (await db.execute(select(Job.id).where(Job.source_id == source_id, Job.status.in_(("queued", "running"))))).first()
    if running:
        raise HTTPException(409, f"По источнику уже идёт задача #{running[0]}")
    inp = base.input or {}
    options = {k: v for k, v in inp.items() if k in OPTION_KEYS[base.tool]} | body.options  # None clears an option
    account = await _account(db, body.account_id or base.account_id)
    job = await runner.submit(base.tool, account, _params(base.tool, inp.get("channel"), body.mode, options))
    return job_out(job)


# ---------- search ----------

SEARCH_COLUMNS = [("date", "Дата"), ("source", "Источник"), ("thread", "Обсуждение"), ("sender", "Автор"),
                  ("username", "Username"), ("sender_id", "ID автора"), ("text", "Текст"), ("link", "Ссылка")]


@router.get("/search/messages")
async def search_messages(
    q: str = Query("", max_length=300),
    source_ids: str | None = None,
    family: Literal["all", "channel", "chat"] = "all",
    sender_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["relevance", "newest", "oldest"] = "relevance",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    format: Literal["csv", "xlsx", "json"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    args = dict(q=q, source_ids=_ids(source_ids) or None, family=family, sender_id=sender_id,
                date_from=date_from, date_to=date_to, sort=sort)
    if format:
        data = await search.search_messages(db, **args, limit=50_000)
        rows = [{"date": (r["date"] or "")[:16].replace("T", " "), "source": r["source"]["title"], "thread": r["thread"],
                 "sender": r["sender"]["name"], "username": r["sender"]["username"], "sender_id": r["sender"]["peer_id"],
                 "text": (r["text"] or "").replace(search.HL_START, "").replace(search.HL_END, ""), "link": r["link"]}
                for r in data["items"]]
        return _file(rows, format, "messages", SEARCH_COLUMNS)
    return await search.search_messages(db, **args, offset=offset, limit=limit)


@router.get("/messages/context")
async def message_context(job_id: int, msg_id: int, around: int = Query(6, ge=1, le=30), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None or job.tool not in SOURCE_TOOLS:
        raise HTTPException(404, "Сообщение не найдено")
    return await search.message_context(db, job_id, msg_id, around)


# ---------- maintenance ----------

@router.get("/maintenance/stats")
async def maintenance_stats(db: AsyncSession = Depends(get_db)):
    path = get_settings().data_dir / "toolkit.db"
    size = sum(os.path.getsize(p) for p in (path, path.with_name("toolkit.db-wal")) if p.exists())
    avatars = get_settings().avatars_dir
    counts = (await db.execute(text(
        "SELECT (SELECT count(*) FROM comments), (SELECT count(*) FROM jobs), (SELECT count(*) FROM tg_peers), "
        "(SELECT count(*) FROM source_members)"))).one()
    act = await active_jobs(db, include_hidden=True)
    stale = (await db.execute(text(
        "SELECT count(*), coalesce(sum(n), 0) FROM (SELECT j.id, (SELECT count(*) FROM comments c WHERE c.job_id = j.id) AS n "
        "FROM jobs j WHERE j.tool IN ('comment-collector', 'chat-indexer') AND j.source_id IS NOT NULL "
        "AND coalesce(json_extract(j.input, '$.mode'), 'full') != 'incremental' AND j.id NOT IN (" +
        (",".join(str(j) for j in act.values()) or "-1") + ")) WHERE n > 0"))).one()
    return {
        "db_bytes": size,
        "avatars": sum(1 for _ in avatars.glob("*.jpg")),
        "avatars_bytes": sum(p.stat().st_size for p in avatars.glob("*.jpg")),
        "messages": counts[0], "jobs": counts[1], "peers": counts[2], "members": counts[3],
        "stale_runs": stale[0], "stale_messages": stale[1],
    }


@router.post("/maintenance/reindex-search")
async def reindex_search():
    await rebuild_search_index()
    return {"ok": True}


@router.post("/maintenance/prune")
async def prune_old_runs(db: AsyncSession = Depends(get_db)):
    """Drop the data of superseded full runs (history rows stay); analytics only ever use the latest."""
    act = await active_jobs(db, include_hidden=True)
    keep = set(act.values())
    old = [j for j in (await db.execute(select(Job.id).where(
        Job.tool.in_(SOURCE_TOOLS), Job.source_id.is_not(None), Job.status.in_(("done", "cancelled", "failed"))))).scalars()
        if j not in keep]
    # incremental runs store nothing themselves (they append into their base job)
    for i in range(0, len(old), 500):
        part = old[i:i + 500]
        await db.execute(text(f"DELETE FROM comments WHERE job_id IN ({','.join(map(str, part))})"))
        await db.execute(text(f"DELETE FROM job_participants WHERE job_id IN ({','.join(map(str, part))})"))
    await db.commit()
    return {"pruned_runs": len(old)}
