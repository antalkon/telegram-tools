import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.jobs import get_job_or_404, job_out
from app.db import get_db
from app.jobs.runner import runner
from app.models import Account, Comment, iso
from app.security import require_admin
from app.tools.comment_collector import export
from app.insights.common import SOURCE_TOOLS
from app.insights.sources import message_link, thread_label
from app.tools.chat_indexer.indexer import IndexerInput
from app.tools.comment_collector.collector import CollectorInput
from app.tools.comment_collector.queries import list_participants

TOOL_ID = "comment-collector"
router = APIRouter(prefix="/tools/comment-collector", tags=["comment-collector"], dependencies=[Depends(require_admin)])
# the same participant views for any source job (channel comments or chat messages)
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_admin)])


class CreateJobIn(CollectorInput):
    account_id: int


@router.post("/jobs")
async def create_job(body: dict, db: AsyncSession = Depends(get_db)):
    try:
        data = CreateJobIn.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    acc = await db.get(Account, data.account_id)
    if not acc:
        raise HTTPException(400, "Выберите подключённый Telegram-аккаунт")
    job = await runner.submit(TOOL_ID, data.account_id, data.model_dump(exclude={"account_id"}))
    return job_out(job)


async def _collector_job(db: AsyncSession, job_id: int):
    job = await get_job_or_404(db, job_id)
    if job.tool not in SOURCE_TOOLS:
        raise HTTPException(404, "Задача не найдена")
    return job


class CreateIndexJobIn(IndexerInput):
    account_id: int


indexer_router = APIRouter(prefix="/tools/chat-indexer", tags=["chat-indexer"], dependencies=[Depends(require_admin)])


@indexer_router.post("/jobs")
async def create_index_job(body: dict, db: AsyncSession = Depends(get_db)):
    try:
        data = CreateIndexJobIn.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    if not await db.get(Account, data.account_id):
        raise HTTPException(400, "Выберите подключённый Telegram-аккаунт")
    job = await runner.submit("chat-indexer", data.account_id, data.model_dump(mode="json", exclude={"account_id"}))
    return job_out(job)


@router.get("/jobs/{job_id}/participants")
@jobs_router.get("/{job_id}/participants")
async def participants(
    job_id: int,
    search: str = "",
    sort: str = "-comments",
    kind: Literal["all", "user", "channel"] = "all",
    presence: Literal["all", "active", "silent", "admins"] = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    await _collector_job(db, job_id)
    total, rows = await list_participants(db, job_id, search=search, sort=sort, kind=kind, presence=presence,
                                          offset=offset, limit=limit)
    return {"total": total, "items": rows}


@router.get("/jobs/{job_id}/participants/{peer_id}/comments")
@jobs_router.get("/{job_id}/participants/{peer_id}/comments")
async def participant_comments(job_id: int, peer_id: int, limit: int = Query(100, le=500), db: AsyncSession = Depends(get_db)):
    job = await _collector_job(db, job_id)
    rows = (
        await db.execute(
            select(Comment)
            .where(Comment.job_id == job_id, Comment.sender_id == peer_id)
            .order_by(Comment.date.desc())
            .limit(limit)
        )
    ).scalars().all()
    ch = (job.result or job.progress or {}).get("channel") or {}
    src = {"id": ch.get("id") or job.source_id, "username": ch.get("username"),
           "family": "channel" if job.tool == TOOL_ID else "chat"} | {k: (job.result or {}).get(k) for k in ("thread_unit", "topics")}
    return [
        {
            "msg_id": c.msg_id,
            "post_id": c.post_id,
            "date": iso(c.date),
            "text": c.text,
            "thread": thread_label(src, c.post_id) if job.tool != TOOL_ID else None,
            "link": message_link(src, c.msg_id, c.post_id),
        }
        for c in rows
    ]


@router.get("/jobs/{job_id}/export")
@jobs_router.get("/{job_id}/export")
async def export_job(
    job_id: int,
    format: Literal["csv", "xlsx", "json"] = "csv",
    kind: Literal["all", "user", "channel"] = "all",
    presence: Literal["all", "active", "silent", "admins"] = "all",
    db: AsyncSession = Depends(get_db),
):
    job = await _collector_job(db, job_id)
    _, rows = await list_participants(db, job_id, kind=kind, presence=presence, limit=None)
    ch = (job.result or {}).get("channel") or (job.progress or {}).get("channel") or {}
    base = re.sub(r"[^\w-]+", "_", ch.get("username") or ch.get("title") or f"job{job_id}").strip("_")
    chat = job.tool != TOOL_ID
    name = f"{'members' if chat else 'commenters'}_{base}_{job_id}.{format}"
    columns = export.CHAT_COLUMNS if chat else export.COLUMNS
    if format == "csv":
        body, media = export.to_csv(rows, columns), "text/csv; charset=utf-8"
    elif format == "xlsx":
        body, media = export.to_xlsx(rows, "Участники" if chat else "Комментаторы", columns), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body, media = export.to_json(rows, {"job": job_out(job)}), "application/json"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
