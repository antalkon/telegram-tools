"""Is the same username registered on other public sites? Checks the WhatsMyName list
(github.com/WebBreacher/WhatsMyName, CC BY-SA 4.0): one request per site, no Telegram account needed.

Only presence is checked (the page of that name exists), nothing is collected from the sites. Adult and
dating sites are left out.
"""

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import get_settings
from app.db import SessionLocal
from app.jobs.runner import JobContext
from app.models import UsernameCheck, utcnow
from app.tools.base import Tool, register

TOOL_ID = "username-check"
DATA_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
DATA_TTL = timedelta(days=7)
SKIP_CATEGORIES = {"xx NSFW xx", "dating", "archived"}
CONCURRENCY = 16
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}


class CheckInput(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=20)

    @field_validator("usernames")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out = []
        for u in v:
            u = u.strip().lstrip("@")
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,64}", u):
                raise ValueError(f"Неверный username: {u!r}")
            out.append(u)
        return list(dict.fromkeys(out))


async def load_sites(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """The WhatsMyName site list, cached in the data dir for a week (stale copy if GitHub is down)."""
    path = get_settings().data_dir / "wmn-data.json"
    fresh = path.exists() and datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC) < DATA_TTL
    if not fresh:
        try:
            r = await http.get(DATA_URL, timeout=30)
            r.raise_for_status()
            json.loads(r.text)  # don't cache garbage
            path.write_text(r.text, encoding="utf-8")
        except (httpx.HTTPError, ValueError):
            if not path.exists():
                raise RuntimeError("Не удалось скачать список сайтов WhatsMyName") from None
    data = json.loads(path.read_text(encoding="utf-8"))
    return [s for s in data["sites"] if s.get("cat") not in SKIP_CATEGORIES and "{account}" in s.get("uri_check", "")]


def verdict(site: dict[str, Any], status: int, body: str) -> bool | None:
    """True: the account exists, False: it doesn't, None: can't tell (blocked, changed site…)."""
    if status == site.get("e_code") and site.get("e_string", "") in body:
        return True
    if status == site.get("m_code") or (site.get("m_string") and site["m_string"] in body):
        return False
    return None


async def check_site(http: httpx.AsyncClient, site: dict[str, Any], username: str) -> tuple[bool | None, str]:
    name = username
    for ch in site.get("strip_bad_char", "") or "":
        name = name.replace(ch, "")
    url = site["uri_check"].replace("{account}", name)
    pretty = (site.get("uri_pretty") or site["uri_check"]).replace("{account}", name)
    headers = HEADERS | (site.get("headers") or {})
    try:
        if site.get("post_body"):
            r = await http.post(url, content=site["post_body"].replace("{account}", name), headers=headers, timeout=TIMEOUT)
        else:
            r = await http.get(url, headers=headers, timeout=TIMEOUT)
        return verdict(site, r.status_code, r.text), pretty
    except (httpx.HTTPError, UnicodeDecodeError):
        return None, pretty


class UsernameChecker(Tool):
    id = TOOL_ID
    title = "Username на других сайтах"
    description = "Есть ли такой же username на ~600 публичных сайтах (база WhatsMyName)"
    Input = CheckInput

    async def run(self, ctx: JobContext, params: CheckInput) -> dict[str, Any]:
        started = time.monotonic()
        async with httpx.AsyncClient(follow_redirects=True, http2=False) as http:
            sites = await load_sites(http)
            total = len(sites) * len(params.usernames)
            await ctx.update(force=True, phase="scan", checks_total=total, checks_done=0, found=0)
            sem = asyncio.Semaphore(CONCURRENCY)
            done = found = 0
            summary: dict[str, int] = {}
            for username in params.usernames:
                rows: list[dict[str, Any]] = []

                async def one(site: dict[str, Any], username: str = username, rows: list = rows) -> None:
                    nonlocal done, found
                    async with sem:
                        hit, url = await check_site(http, site, username)
                    done += 1
                    if hit is not None:
                        rows.append({"username": username.lower(), "site": site["name"][:128], "category": site.get("cat"),
                                     "url": url, "found": hit, "checked_at": utcnow()})
                    if hit:
                        found += 1
                    if done % 20 == 0:
                        await ctx.update(checks_done=done, found=found)

                await asyncio.gather(*(one(s) for s in sites))
                async with SessionLocal() as db:
                    await db.execute(delete(UsernameCheck).where(UsernameCheck.username == username.lower()))
                    for i in range(0, len(rows), 300):
                        await db.execute(sqlite_insert(UsernameCheck), rows[i:i + 300])
                    await db.commit()
                summary[username] = sum(1 for r in rows if r["found"])
        await ctx.update(force=True, checks_done=done, found=found)
        return {"usernames": params.usernames, "sites": len(sites), "found": summary,
                "duration_sec": round(time.monotonic() - started, 1)}


register(UsernameChecker())
