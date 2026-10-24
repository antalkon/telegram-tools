"""In-process job runner: one asyncio task per job, progress kept in memory, flushed to the DB
periodically and fanned out to SSE subscribers."""

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import Any

from sqlalchemy import select, text, update
from telethon import TelegramClient

from app.db import SessionLocal
from app.models import Job, utcnow
from app.telegram.manager import manager
from app.tools.base import get_tool

log = logging.getLogger(__name__)

FLUSH_INTERVAL = 1.0
TERMINAL = {"done", "failed", "cancelled"}
# Account the running job acts as; lets shared helpers remember per-account access hashes.
current_account: ContextVar[int | None] = ContextVar("current_account", default=None)


class JobContext:
    def __init__(self, runner: "JobRunner", job_id: int, account_id: int | None) -> None:
        self.runner = runner
        self.job_id = job_id
        self.account_id = account_id
        self.progress: dict[str, Any] = {}
        self.signals: set[str] = set()  # e.g. "skip_avatars", sent from the UI
        self._last_flush = 0.0

    async def client(self) -> TelegramClient:
        if self.account_id is None:
            raise RuntimeError("Для задачи не выбран аккаунт")
        return await manager.get_client(self.account_id)

    async def set_result(self, result: dict[str, Any]) -> None:
        """Store the result before optional trailing phases, so an interruption keeps it."""
        async with SessionLocal() as db:
            await db.execute(update(Job).where(Job.id == self.job_id).values(result=result))
            await db.commit()

    async def set_source(self, peer_id: int) -> None:
        """Record which chat this job collects from (used to group jobs across tools)."""
        async with SessionLocal() as db:
            await db.execute(update(Job).where(Job.id == self.job_id).values(source_id=peer_id))
            await db.commit()

    async def update(self, force: bool = False, **fields: Any) -> None:
        self.progress.update(fields)
        self.runner.publish(self.job_id, {"status": "running", "progress": self.progress})
        now = time.monotonic()
        if force or now - self._last_flush >= FLUSH_INTERVAL:
            self._last_flush = now
            async with SessionLocal() as db:
                await db.execute(update(Job).where(Job.id == self.job_id).values(progress=dict(self.progress)))
                await db.commit()


class JobRunner:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._contexts: dict[int, JobContext] = {}
        self._subs: dict[int, set[asyncio.Queue]] = {}
        self._account_locks: dict[int, asyncio.Lock] = {}

    async def recover(self) -> None:
        """Jobs that were running when the server stopped can't be resumed in-process. Ones that
        only had avatars left already saved their data: those count as done."""
        async with SessionLocal() as db:
            jobs = (await db.execute(select(Job).where(Job.status.in_(["queued", "running"])))).scalars().all()
            for job in jobs:
                job.finished_at = utcnow()
                if (job.progress or {}).get("phase") == "avatars":
                    job.status, job.error = "done", None
                    job.progress = (job.progress or {}) | {"phase": "done", "avatars_interrupted": True}
                    if not job.result:
                        users, comments = (await db.execute(text(
                            "SELECT count(*), coalesce(sum(comments), 0) FROM job_participants WHERE job_id = :j"),
                            {"j": job.id})).one()
                        job.result = {"channel": job.progress.get("channel"), "comments": comments,
                                      "unique_users": users, "posts_total": job.progress.get("posts_total"),
                                      "strategy": job.progress.get("strategy")}
                else:
                    job.status, job.error = "failed", "Сервер был перезапущен во время выполнения"
            await db.commit()

    async def submit(self, tool_id: str, account_id: int | None, params: dict[str, Any]) -> Job:
        tool = get_tool(tool_id)
        tool.Input.model_validate(params)
        async with SessionLocal() as db:
            job = Job(tool=tool_id, account_id=account_id, input=params, progress={"phase": "queued"})
            db.add(job)
            await db.commit()
            await db.refresh(job)
        self._tasks[job.id] = asyncio.create_task(self._run(job.id, tool_id, account_id, params))
        return job

    def cancel(self, job_id: int) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def signal(self, job_id: int, name: str) -> bool:
        ctx = self._contexts.get(job_id)
        if ctx is None:
            return False
        ctx.signals.add(name)
        return True

    async def wait(self, job_id: int) -> None:
        """Until the job's task ends; returns at once if it already finished (its task is gone by then)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await task

    def is_active(self, job_id: int) -> bool:
        task = self._tasks.get(job_id)
        return bool(task and not task.done())

    # ---------- pub/sub ----------

    def subscribe(self, job_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue) -> None:
        self._subs.get(job_id, set()).discard(q)

    def publish(self, job_id: int, event: dict[str, Any]) -> None:
        for q in self._subs.get(job_id, ()):
            if q.full():  # slow consumer: drop the oldest, progress events are cumulative anyway
                q.get_nowait()
            q.put_nowait(event)

    # ---------- execution ----------

    async def _finish(self, ctx: JobContext, status: str, *, result: dict | None = None, error: str | None = None):
        ctx.progress["phase"] = status
        async with SessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == ctx.job_id)
                .values(status=status, progress=dict(ctx.progress), result=result or {}, error=error, finished_at=utcnow())
            )
            await db.commit()
        self.publish(ctx.job_id, {"status": status, "progress": ctx.progress, "result": result, "error": error})

    async def _run(self, job_id: int, tool_id: str, account_id: int | None, params: dict[str, Any]) -> None:
        tool = get_tool(tool_id)
        ctx = JobContext(self, job_id, account_id)
        self._contexts[job_id] = ctx
        current_account.set(account_id)
        # One job per Telegram account at a time: parallel scraping on one account just earns FloodWaits.
        lock = self._account_locks.setdefault(account_id or 0, asyncio.Lock())
        try:
            async with lock:
                async with SessionLocal() as db:
                    await db.execute(update(Job).where(Job.id == job_id).values(status="running", started_at=utcnow()))
                    await db.commit()
                await ctx.update(force=True, phase="starting")
                result = await tool.run(ctx, tool.Input.model_validate(params))
            await self._finish(ctx, "done", result=result)
        except asyncio.CancelledError:
            await self._finish(ctx, "cancelled")
        except Exception as e:
            log.exception("job %s failed", job_id)
            await self._finish(ctx, "failed", error=str(e) or type(e).__name__)
        finally:
            self._tasks.pop(job_id, None)
            self._contexts.pop(job_id, None)


runner = JobRunner()
