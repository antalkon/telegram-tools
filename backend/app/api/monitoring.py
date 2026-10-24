from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify
from app.db import get_db
from app.insights.common import active_jobs, cards, photo
from app.jobs.scheduler import start_monitor
from app.models import Event, Job, Monitor, TgPeer, iso
from app.security import require_admin
from app.telegram.links import LinkError, parse_channel_link

router = APIRouter(tags=["monitoring"], dependencies=[Depends(require_admin)])


async def monitor_out(db: AsyncSession, m: Monitor) -> dict:
    peer = await db.get(TgPeer, m.source_id) if m.source_id else None
    return {
        "id": m.id, "source_id": m.source_id, "channel": m.channel, "tool": m.tool, "options": m.options or {},
        "title": m.title or (peer.title if peer else None) or m.channel,
        "username": peer.username if peer else None, "photo_id": photo(peer),
        "account_id": m.account_id, "interval_minutes": m.interval_minutes,
        "enabled": m.enabled, "notify": m.notify,
        "last_run_at": iso(m.last_run_at), "next_run_at": iso(m.next_run_at),
        "last_job_id": m.last_job_id, "last_status": m.last_status, "last_error": m.last_error,
        "last_new_users": m.last_new_users, "created_at": iso(m.created_at),
    }


class MonitorIn(BaseModel):
    source_id: int | None = None
    channel: str | None = Field(None, max_length=256)
    account_id: int | None = None
    interval_minutes: int = Field(360, ge=15, le=60 * 24 * 14)
    enabled: bool = True
    notify: bool = True
    run_now: bool = True
    tool: Literal["comment-collector", "chat-indexer"] | None = None  # for a link; known sources keep theirs
    options: dict = {}

    @field_validator("channel")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        if v:
            try:
                parse_channel_link(v)
            except LinkError as e:
                raise ValueError(str(e)) from e
            return v.strip()
        return v


class MonitorPatch(BaseModel):
    account_id: int | None = None
    interval_minutes: int | None = Field(None, ge=15, le=60 * 24 * 14)
    enabled: bool | None = None
    notify: bool | None = None
    options: dict | None = None


@router.get("/monitors")
async def list_monitors(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Monitor).order_by(Monitor.id))).scalars().all()
    return [await monitor_out(db, m) for m in rows]


@router.post("/monitors")
async def create_monitor(body: MonitorIn, db: AsyncSession = Depends(get_db)):
    channel, title, tool = body.channel, None, body.tool or "comment-collector"
    if body.source_id is not None:
        if existing := (await db.execute(select(Monitor).where(Monitor.source_id == body.source_id))).scalars().first():
            raise HTTPException(409, f"Источник уже на мониторинге (#{existing.id})")
        job_id = (await active_jobs(db, include_hidden=True)).get(body.source_id)
        job = await db.get(Job, job_id) if job_id else None
        peer = await db.get(TgPeer, body.source_id)
        if job is None and peer is None:
            raise HTTPException(404, "Источник не найден")
        channel = f"@{peer.username}" if peer and peer.username else (job.input or {}).get("channel") if job else None
        title = peer.title if peer else None
        tool = job.tool if job else tool
    if not channel:
        raise HTTPException(422, "Укажите канал или чат")
    m = Monitor(source_id=body.source_id, channel=channel, title=title, account_id=body.account_id, tool=tool,
                options={k: v for k, v in body.options.items() if k in ("collect_members", "index_messages", "download_avatars")},
                interval_minutes=body.interval_minutes, enabled=body.enabled, notify=body.notify,
                next_run_at=datetime.now(UTC) + timedelta(minutes=body.interval_minutes))
    db.add(m)
    await db.commit()
    await db.refresh(m)
    if body.run_now and body.enabled:
        await start_monitor(m.id)
        await db.refresh(m)
    return await monitor_out(db, m)


@router.patch("/monitors/{monitor_id}")
async def patch_monitor(monitor_id: int, body: MonitorPatch, db: AsyncSession = Depends(get_db)):
    m = await db.get(Monitor, monitor_id)
    if not m:
        raise HTTPException(404, "Монитор не найден")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(m, k, v)
    if "interval_minutes" in data or data.get("enabled"):
        base = m.last_run_at or datetime.now(UTC)
        base = base.replace(tzinfo=UTC) if base.tzinfo is None else base
        m.next_run_at = max(datetime.now(UTC), base + timedelta(minutes=m.interval_minutes))
    await db.commit()
    return await monitor_out(db, m)


@router.delete("/monitors/{monitor_id}")
async def delete_monitor(monitor_id: int, db: AsyncSession = Depends(get_db)):
    m = await db.get(Monitor, monitor_id)
    if m:
        await db.delete(m)
        await db.commit()
    return {"ok": True}


@router.post("/monitors/{monitor_id}/run")
async def run_monitor(monitor_id: int, db: AsyncSession = Depends(get_db)):
    job = await start_monitor(monitor_id)
    if job is None:
        m = await db.get(Monitor, monitor_id)
        if m is None:
            raise HTTPException(404, "Монитор не найден")
        raise HTTPException(409, m.last_error or "Предыдущий запуск ещё идёт")
    return {"job_id": job.id}


# ---------- events ----------

def event_out(e: Event) -> dict:
    return {"id": e.id, "created_at": iso(e.created_at), "kind": e.kind, "title": e.title, "payload": e.payload,
            "source_id": e.source_id, "job_id": e.job_id, "monitor_id": e.monitor_id, "read": e.read,
            "delivery": e.delivery, "delivery_error": e.delivery_error}


@router.get("/events")
async def list_events(unread: bool = False, limit: int = Query(50, le=200), db: AsyncSession = Depends(get_db)):
    q = select(Event).order_by(Event.id.desc()).limit(limit)
    if unread:
        q = q.where(Event.read.is_(False))
    events = (await db.execute(q)).scalars().all()
    total_unread = (await db.execute(select(func.count()).select_from(Event).where(Event.read.is_(False)))).scalar_one()
    return {"unread": total_unread, "items": [event_out(e) for e in events]}


class ReadIn(BaseModel):
    ids: list[int] | None = None  # None = all


@router.post("/events/read")
async def mark_read(body: ReadIn, db: AsyncSession = Depends(get_db)):
    q = update(Event).values(read=True)
    if body.ids is not None:
        q = q.where(Event.id.in_(body.ids or [-1]))
    await db.execute(q)
    await db.commit()
    return {"ok": True}


# ---------- notification settings ----------

class NotifyIn(BaseModel):
    target: Literal["none", "saved", "bot"] | None = None
    account_id: int | None = None
    bot_token: str | None = Field(None, max_length=200)
    bot_chat_id: str | None = Field(None, max_length=64)
    panel_url: str | None = Field(None, max_length=300)
    new_users: bool | None = None
    watch: bool | None = None
    failures: bool | None = None
    min_new_users: int | None = Field(None, ge=1, le=10000)


@router.get("/settings/notifications")
async def get_notify_settings():
    return notify.public_settings(await notify.get_settings())


@router.put("/settings/notifications")
async def put_notify_settings(body: NotifyIn):
    return notify.public_settings(await notify.save_settings(body.model_dump(exclude_unset=True)))


@router.post("/settings/notifications/test")
async def test_notify():
    s = await notify.get_settings()
    if s["target"] == "none":
        raise HTTPException(400, "Выберите, куда отправлять уведомления")
    try:
        await notify.send_text("✅ <b>TG Toolkit</b>\nТестовое уведомление — доставка работает.", s)
    except Exception as e:
        raise HTTPException(400, f"Не удалось отправить: {e}") from e
    return {"ok": True}


# ---------- peers by id (for event / run details) ----------

@router.get("/peers")
async def get_peers(ids: str, db: AsyncSession = Depends(get_db)):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:500]
    except ValueError as e:
        raise HTTPException(422, "ids: числа через запятую") from e
    found = await cards(db, id_list)
    return [found[i] for i in id_list]
