import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db import SessionLocal, get_db
from app.jobs.runner import TERMINAL, runner
from app.models import Job, iso
from app.security import require_admin
from app.tools.base import all_tools

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_admin)])


def _str_photo(data: dict | None) -> dict | None:
    """Older jobs stored the channel photo id as a number; JS would round the 64-bit value."""
    ch = (data or {}).get("channel")
    if isinstance(ch, dict) and isinstance(ch.get("photo_id"), int):
        return data | {"channel": ch | {"photo_id": str(ch["photo_id"])}}
    return data


def job_out(j: Job) -> dict:
    return {
        "id": j.id,
        "tool": j.tool,
        "status": j.status,
        "account_id": j.account_id,
        "input": j.input,
        "progress": _str_photo(j.progress),
        "result": _str_photo(j.result),
        "error": j.error,
        "created_at": iso(j.created_at),
        "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at),
    }


async def get_job_or_404(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job


@router.get("/tools")
async def list_tools():
    return [{"id": t.id, "title": t.title, "description": t.description} for t in all_tools()]


@router.get("/jobs")
async def list_jobs(tool: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    q = select(Job).order_by(Job.id.desc()).limit(min(limit, 200))
    if tool:
        q = q.where(Job.tool == tool)
    return [job_out(j) for j in (await db.execute(q)).scalars().all()]


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    return job_out(await get_job_or_404(db, job_id))


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    return {"cancelled": runner.cancel(job_id)}


@router.post("/jobs/{job_id}/skip-avatars")
async def skip_avatars(job_id: int):
    return {"ok": runner.signal(job_id, "skip_avatars")}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    if runner.is_active(job_id):
        raise HTTPException(409, "Задача ещё выполняется — сначала отмените её")
    await db.execute(delete(Job).where(Job.id == job_id))
    await db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int, request: Request):
    async with SessionLocal() as db:
        job = await get_job_or_404(db, job_id)
        snapshot = job_out(job)
    queue = runner.subscribe(job_id)

    async def gen():
        try:
            yield {"event": "state", "data": json.dumps(snapshot)}
            if snapshot["status"] in TERMINAL:
                return
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    continue  # sse-starlette sends pings itself
                yield {"event": "progress", "data": json.dumps(ev, default=str)}
                if ev.get("status") in TERMINAL:
                    return
        finally:
            runner.unsubscribe(job_id, queue)

    return EventSourceResponse(gen(), ping=10)
