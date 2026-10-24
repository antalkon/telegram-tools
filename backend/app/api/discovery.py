"""Channels of the people in the base: run the finder, browse what it found, dismiss or index it."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.insights import _file
from app.api.jobs import job_out
from app.api.sources import _account
from app.db import get_db
from app.insights.common import active_jobs, cards, sql
from app.jobs.runner import runner
from app.models import FoundChannel, Job, iso
from app.security import require_admin
from app.telegram.peers import avatar_path
from app.jobs.scheduler import _pick_account
from app.tools.channel_finder.finder import TOOL_ID, FinderInput, load_blocks

router = APIRouter(tags=["discovery"], dependencies=[Depends(require_admin)])

FAMILY = {"channel": "channel", "supergroup": "chat", "forum": "chat", "gigagroup": "chat", "group": "chat"}
SAMPLE = 6


class FinderIn(BaseModel):
    account_id: int | None = None
    options: dict[str, Any] = {}


@router.post("/tools/channel-finder/jobs")
async def start_finder(body: FinderIn, db: AsyncSession = Depends(get_db)):
    running = (await db.execute(select(Job.id).where(Job.tool == TOOL_ID, Job.status.in_(("queued", "running"))))).first()
    if running:
        raise HTTPException(409, f"Поиск уже идёт (задача #{running[0]})")
    try:
        params = FinderInput.model_validate(body.options).model_dump(mode="json")
    except ValidationError as e:
        raise HTTPException(422, "; ".join(str(err["msg"]) for err in e.errors())) from e
    return job_out(await runner.submit(TOOL_ID, await _account(db, body.account_id), params))


@router.get("/discovery/stats")
async def discovery_stats(db: AsyncSession = Depends(get_db)):
    jobs = list((await active_jobs(db)).values())
    people, checked, personal, with_bio = (await sql(db, """
        SELECT count(*), coalesce(sum(t.profile_checked_at IS NOT NULL), 0), coalesce(sum(t.personal_channel_id IS NOT NULL), 0),
               coalesce(sum(t.about IS NOT NULL), 0)
        FROM tg_peers t WHERE t.kind = 'user' AND NOT t.is_bot AND NOT t.is_deleted
          AND t.id IN (SELECT peer_id FROM job_participants WHERE job_id IN :jobs)""", jobs))[0]
    found, dismissed = (await db.execute(text(
        "SELECT count(*), coalesce(sum(dismissed), 0) FROM found_channels"))).one()
    last = (await db.execute(select(Job).where(Job.tool == TOOL_ID).order_by(Job.id.desc()).limit(1))).scalar()
    blocks = await load_blocks(await _pick_account(db, last.account_id if last else None))
    return {"people": people, "checked": checked, "personal": personal, "with_bio": with_bio,
            "found": found, "dismissed": dismissed, "last_job": job_out(last) if last else None,
            # request kinds Telegram has banned for a while: kind -> until
            "blocked": {k: v.isoformat() for k, v in blocks.items()}}


def _photo(photo_id: int | None) -> str | None:
    return str(photo_id) if photo_id and avatar_path(photo_id).exists() else None


def _link(f: FoundChannel) -> str | None:
    if f.username:
        return f"https://t.me/{f.username}"
    if f.invite_hash:
        return f"https://t.me/+{f.invite_hash}"
    return None


async def _rows(db: AsyncSession) -> list[dict[str, Any]]:
    found = (await db.execute(select(FoundChannel))).scalars().all()
    links = (await db.execute(text("SELECT key, user_id, via FROM found_channel_links ORDER BY rowid"))).all()
    sources = set(await active_jobs(db, include_hidden=True))
    by_key: dict[str, dict[str, Any]] = {}
    for key, uid, via in links:
        b = by_key.setdefault(key, {"users": [], "via": {"personal": 0, "bio": 0, "sender": False}})
        if via == "sender":
            b["via"]["sender"] = True
            continue
        b["via"][via] += 1
        if uid not in b["users"]:
            b["users"].append(uid)
    out = []
    for f in found:
        b = by_key.get(f.key, {"users": [], "via": {"personal": 0, "bio": 0, "sender": False}})
        out.append({
            "key": f.key, "peer_id": f.peer_id, "type": f.type, "family": FAMILY.get(f.type or "", None),
            "title": f.title or (f"@{f.username}" if f.username else "Без названия"), "username": f.username,
            "link": _link(f), "members_count": f.members_count, "about": (f.about or "")[:400] or None,
            "photo_id": _photo(f.photo_id), "private": f.private, "dismissed": f.dismissed,
            "found_at": iso(f.found_at), "checked_at": iso(f.checked_at),
            "is_source": f.peer_id in sources, "via": b["via"], "users": len(b["users"]), "user_ids": b["users"],
        })
    return out


CHANNEL_COLUMNS = [("title", "Название"), ("type", "Тип"), ("username", "Username"), ("link", "Ссылка"),
                   ("members_count", "Участников"), ("users", "Указали людей"), ("via", "Откуда"), ("about", "Описание"),
                   ("is_source", "Уже источник"), ("peer_id", "ID")]


@router.get("/discovery/channels")
async def found_channels(
    status: Literal["new", "sources", "dismissed", "all"] = "new",
    type: Literal["all", "channel", "chat", "private"] = "all",
    via: Literal["all", "personal", "bio", "sender"] = "all",
    q: str = Query("", max_length=100),
    sort: Literal["users", "members", "found", "title"] = "users",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    format: Literal["csv", "xlsx", "json"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await _rows(db)
    counts = {"new": 0, "sources": 0, "dismissed": 0, "all": len(rows)}
    for r in rows:
        counts["dismissed" if r["dismissed"] else "sources" if r["is_source"] else "new"] += 1
    needle = q.strip().lower().lstrip("@")

    def keep(r) -> bool:
        if status == "new" and (r["dismissed"] or r["is_source"]):
            return False
        if status == "sources" and not r["is_source"]:
            return False
        if status == "dismissed" and not r["dismissed"]:
            return False
        if type == "private" and not r["private"]:
            return False
        if type in ("channel", "chat") and r["family"] != type:
            return False
        if via == "sender" and not r["via"]["sender"]:
            return False
        if via in ("personal", "bio") and not r["via"][via]:
            return False
        return not needle or needle in (r["title"] or "").lower() or needle in (r["username"] or "").lower() \
            or needle in (r["about"] or "").lower()

    rows = [r for r in rows if keep(r)]
    order = {
        "users": lambda r: (-r["users"], -(r["members_count"] or 0)),
        "members": lambda r: (-(r["members_count"] or 0), -r["users"]),
        "found": lambda r: r["found_at"] or "",
        "title": lambda r: (r["title"] or "").lower(),
    }
    rows.sort(key=order[sort], reverse=sort == "found")
    if format:
        export = [r | {"via": ", ".join(k for k, v in r["via"].items() if v), "is_source": "да" if r["is_source"] else ""}
                  for r in rows]
        return _file(export, format, "found-channels", CHANNEL_COLUMNS)
    page = rows[offset:offset + limit]
    people = await cards(db, [u for r in page for u in r["user_ids"][:SAMPLE]])
    for r in page:
        r["people"] = [people[u] for u in r.pop("user_ids")[:SAMPLE]]
    return {"total": len(rows), "counts": counts, "items": page}


@router.get("/discovery/channels/{key}/users")
async def found_channel_users(key: str, db: AsyncSession = Depends(get_db)):
    links = (await db.execute(text(
        "SELECT user_id, group_concat(via) FROM found_channel_links WHERE key = :k AND via != 'sender' GROUP BY user_id"),
        {"k": key})).all()
    people = await cards(db, [u for u, _ in links])
    return [people[u] | {"via": v.split(",")} for u, v in links]


class DismissIn(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=5000)
    dismissed: bool = True


@router.post("/discovery/channels/dismiss")
async def dismiss_found(body: DismissIn, db: AsyncSession = Depends(get_db)):
    await db.execute(update(FoundChannel).where(FoundChannel.key.in_(body.keys)).values(dismissed=body.dismissed))
    await db.commit()
    return {"ok": True}
