"""Monitoring: starts incremental re-collections of watched sources (channels, chats) on their interval."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import notify
from app.db import SessionLocal
from app.jobs.runner import TERMINAL, runner
from app.models import Account, Job, Monitor

log = logging.getLogger(__name__)
TICK_SECONDS = 30


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


async def _pick_account(db, preferred: int | None) -> int | None:
    if preferred and (acc := await db.get(Account, preferred)) and acc.status == "active":
        return acc.id
    acc = (await db.execute(select(Account).where(Account.status == "active").order_by(Account.id))).scalars().first()
    return acc.id if acc else None


async def start_monitor(monitor_id: int, now: datetime | None = None) -> Job | None:
    """Launch one incremental run now (the scheduler and the «run now» button both use this)."""
    now = now or datetime.now(UTC)
    async with SessionLocal() as db:
        m = await db.get(Monitor, monitor_id)
        if m is None:
            return None
        if m.last_job_id and runner.is_active(m.last_job_id):
            return None  # previous run still going
        account_id = await _pick_account(db, m.account_id)
        m.last_run_at = now
        m.next_run_at = now + timedelta(minutes=m.interval_minutes)
        if account_id is None:
            m.last_status, m.last_error = "failed", "Нет активного Telegram-аккаунта"
            await db.commit()
            return None
        await db.commit()
    params = (m.options or {}) | {"channel": m.channel, "mode": "incremental", "monitor_id": m.id}
    job = await runner.submit(m.tool or "comment-collector", account_id, params)
    async with SessionLocal() as db:
        m = await db.get(Monitor, monitor_id)
        m.last_job_id, m.last_status, m.last_error = job.id, "running", None
        await db.commit()
    return job


async def reconcile() -> None:
    """Copy the outcome of finished runs onto their monitors; report failures once."""
    async with SessionLocal() as db:
        running = (await db.execute(select(Monitor).where(Monitor.last_status == "running"))).scalars().all()
        for m in running:
            job = await db.get(Job, m.last_job_id) if m.last_job_id else None
            if job is None or job.status not in TERMINAL:
                continue
            m.last_status = job.status
            m.last_error = job.error
            m.last_new_users = (job.result or {}).get("new_users")
            if job.source_id and not m.source_id:
                m.source_id = job.source_id
            ch = (job.result or {}).get("channel") or (job.progress or {}).get("channel") or {}
            if ch.get("title"):
                m.title = ch["title"]
            await db.commit()
            if job.status == "failed" and m.notify:
                await notify.emit("job_failed", f"Мониторинг «{m.title or m.channel}» не сработал",
                                  {"detail": job.error, "path": "/monitoring"}, source_id=m.source_id, job_id=job.id, monitor_id=m.id)


async def tick(now: datetime | None = None) -> list[int]:
    """Start every enabled monitor that is due. Returns the started job ids."""
    now = now or datetime.now(UTC)
    if runner.blocked:  # data import or wipe in progress
        return []
    await reconcile()
    async with SessionLocal() as db:
        due = [m.id for m in (await db.execute(select(Monitor).where(Monitor.enabled.is_(True)))).scalars()
               if m.next_run_at is None or _aware(m.next_run_at) <= now]
    started = []
    for monitor_id in due:
        try:
            if job := await start_monitor(monitor_id, now):
                started.append(job.id)
        except Exception:
            log.exception("monitor %s failed to start", monitor_id)
    return started


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(5)  # let startup settle
        while True:
            try:
                await tick()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)


scheduler = Scheduler()
