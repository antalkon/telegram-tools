"""Channel posts (through the account or the public web preview), ads, contacts, the company register, and
the same username on other sites."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.insights import _file
from app.api.jobs import job_out
from app.api.sources import _account
from app.db import get_db
from app.insights import orgs, posts
from app.insights.users import _user_jobs
from app.jobs.runner import runner
from app.security import require_admin
from app.models import UsernameCheck, iso
from app.tools.channel_posts.posts import TOOL_ID, PostsInput
from app.tools.username_check.check import TOOL_ID as CHECK_TOOL, CheckInput

router = APIRouter(tags=["posts"], dependencies=[Depends(require_admin)])

POST_COLUMNS = [("date", "Дата"), ("channel", "Канал"), ("post_id", "Пост"), ("text", "Текст"), ("views", "Просмотры"),
                ("forwards", "Репосты"), ("replies", "Комментарии"), ("forwarded_from", "Переслано из"),
                ("erid", "erid"), ("advertiser", "Рекламодатель"), ("advertiser_inn", "ИНН рекламодателя"), ("link", "Ссылка")]


class PostsJobIn(BaseModel):
    channel: str = Field(min_length=1, max_length=256)
    via: Literal["account", "web"] = "account"
    limit: int = Field(1000, ge=1, le=100_000)
    since: date | None = None
    account_id: int | None = None


@router.post("/tools/channel-posts/jobs")
async def start_posts(body: PostsJobIn, db: AsyncSession = Depends(get_db)):
    """via=web needs no Telegram account: public channels only, through t.me/s/."""
    try:
        params = PostsInput.model_validate(body.model_dump(exclude={"account_id"})).model_dump(mode="json")
    except ValidationError as e:
        raise HTTPException(422, "; ".join(str(err["msg"]) for err in e.errors())) from e
    account = None if body.via == "web" else await _account(db, body.account_id)
    return job_out(await runner.submit(TOOL_ID, account, params))


@router.get("/posts/channels")
async def get_post_channels(db: AsyncSession = Depends(get_db)):
    return await posts.post_channels(db)


@router.get("/posts")
async def get_posts(
    channel: str | None = None,
    q: str = Query("", max_length=200),
    ads_only: bool = False,
    forwarded_only: bool = False,
    sort: Literal["date", "oldest", "views", "forwards"] = "date",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    format: Literal["csv", "xlsx", "json"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    args = dict(channel=channel, q=q, ads_only=ads_only, forwarded_only=forwarded_only, sort=sort)
    if format:
        data = await posts.list_posts(db, **args, limit=100_000)
        rows = [p | {"channel": f"@{p['username']}" if p["username"] else p["channel_key"],
                     "forwarded_from": (p["forwarded_from"] or {}).get("username") or (p["forwarded_from"] or {}).get("name"),
                     "erid": (p["ad"] or {}).get("erid"), "advertiser": (p["ad"] or {}).get("advertiser"),
                     "advertiser_inn": (p["ad"] or {}).get("inn")} for p in data["items"]]
        return _file(rows, format, "posts", POST_COLUMNS)
    return await posts.list_posts(db, **args, offset=offset, limit=limit)


@router.get("/posts/ads")
async def get_ads(channel: str | None = None, db: AsyncSession = Depends(get_db)):
    """Advertisers from ad-marked posts (erid / «Реклама … ИНН»)."""
    return await posts.ads_summary(db, channel)


@router.get("/posts/forward-sources")
async def get_forward_sources(channel_id: int | None = None, limit: int = Query(50, le=500), db: AsyncSession = Depends(get_db)):
    return await posts.forward_sources(db, channel_id, limit)


@router.get("/channels/{channel_id}/contacts")
async def get_channel_contacts(channel_id: int, username: str | None = None, db: AsyncSession = Depends(get_db)):
    """Phones, e-mails, sites, wallets, ИНН/ОГРН in a channel's description and collected posts."""
    return await posts.channel_contacts(db, channel_id or None, username)


@router.get("/users/{peer_id}/contacts")
async def get_user_contacts(peer_id: int, db: AsyncSession = Depends(get_db)):
    """Contacts a person wrote in their bio and messages."""
    _, jobs = await _user_jobs(db, peer_id)
    return await posts.user_contacts(db, peer_id, jobs)


@router.get("/orgs/{query}")
async def get_org(query: str, refresh: bool = False, db: AsyncSession = Depends(get_db)):
    """Company / sole trader by ИНН or ОГРН from the public ЕГРЮЛ/ЕГРИП search (cached for 30 days)."""
    try:
        return await orgs.lookup(db, query, refresh)
    except orgs.OrgLookupError as e:
        raise HTTPException(422 if "Нужен" in str(e) else 502, str(e)) from e


# ---------- the same username on other sites ----------

class UsernameCheckIn(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=20)


@router.post("/tools/username-check/jobs")
async def start_username_check(body: UsernameCheckIn):
    """Check usernames on ~600 public sites (WhatsMyName list). No Telegram account is used."""
    try:
        params = CheckInput.model_validate(body.model_dump()).model_dump()
    except ValidationError as e:
        raise HTTPException(422, "; ".join(str(err["msg"]) for err in e.errors())) from e
    return job_out(await runner.submit(CHECK_TOOL, None, params))


@router.get("/usernames/{username}/sites")
async def get_username_sites(username: str, db: AsyncSession = Depends(get_db)):
    """Last check of a username: sites where it exists, how many were checked, when."""
    u = username.strip().lstrip("@").lower()
    rows = (await db.execute(select(UsernameCheck).where(UsernameCheck.username == u)
                             .order_by(UsernameCheck.category, UsernameCheck.site))).scalars().all()
    return {"username": u, "checked": len(rows), "checked_at": iso(max((r.checked_at for r in rows), default=None)),
            "found": [{"site": r.site, "category": r.category, "url": r.url} for r in rows if r.found]}
