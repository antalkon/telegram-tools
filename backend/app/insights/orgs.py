"""Companies and sole traders by ИНН / ОГРН from the public search of the Russian state register
(egrul.nalog.ru, ЕГРЮЛ / ЕГРИП). Results are cached: the register changes slowly and the site is shared."""

import asyncio
import re
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgLookup, iso, utcnow
from app.telegram.contacts import valid_inn, valid_ogrn

URL = "https://egrul.nalog.ru/"
TTL = timedelta(days=30)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TG-Toolkit; +https://github.com/antalkon/telegram-tools)"}
_lock = asyncio.Lock()  # one request at a time to the register


class OrgLookupError(Exception):
    pass


def normalize(query: str) -> str:
    q = re.sub(r"\D", "", query or "")
    if not (len(q) in (10, 12) and valid_inn(q)) and not (len(q) in (13, 15) and valid_ogrn(q)):
        raise OrgLookupError("Нужен ИНН (10 или 12 цифр) или ОГРН (13 или 15 цифр) с верной контрольной суммой")
    return q


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {"name": r.get("n"), "short_name": r.get("c"), "inn": r.get("i"), "ogrn": r.get("o"), "kpp": r.get("p"),
            "kind": "ИП" if r.get("k") == "fl" else "ЮЛ", "registered": r.get("r"), "closed": r.get("e"),
            "head": r.get("g"), "region": r.get("rn"),
            "url": f"https://egrul.nalog.ru/index.html?query={r.get('i') or r.get('o')}"}


async def _fetch(q: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as http:
        r = await http.post(URL, data={"query": q, "vyp3CaptchaToken": "", "page": "", "nameEq": "on", "region": "",
                                       "PreventChromeAutocomplete": ""})
        r.raise_for_status()
        token = r.json()
        if token.get("captchaRequired"):
            raise OrgLookupError("Сайт ФНС просит капчу — попробуйте позже")
        for _ in range(6):
            await asyncio.sleep(1)
            res = await http.get(f"{URL}search-result/{token['t']}", params={"r": int(time.time() * 1000)})
            res.raise_for_status()
            data = res.json()
            if data.get("status") != "wait":
                return [_row(x) for x in data.get("rows") or []]
    raise OrgLookupError("ФНС не ответила вовремя — попробуйте позже")


async def lookup(db: AsyncSession, query: str, refresh: bool = False) -> dict[str, Any]:
    q = normalize(query)
    cached = await db.get(OrgLookup, q)
    if cached and not refresh and not cached.error and (utcnow() - cached.checked_at.replace(tzinfo=utcnow().tzinfo)) < TTL:
        return {"query": q, "found": cached.found, "orgs": cached.data.get("orgs", []), "checked_at": iso(cached.checked_at), "cached": True}
    async with _lock:
        try:
            orgs = await _fetch(q)
            error = None
        except (httpx.HTTPError, ValueError, KeyError) as e:
            orgs, error = [], f"ФНС недоступна: {type(e).__name__}"
        except OrgLookupError as e:
            orgs, error = [], str(e)
    stmt = sqlite_insert(OrgLookup).values(query=q, found=bool(orgs), data={"orgs": orgs}, error=error, checked_at=utcnow())
    await db.execute(stmt.on_conflict_do_update(index_elements=["query"], set_={
        "found": stmt.excluded.found, "data": stmt.excluded.data, "error": stmt.excluded.error, "checked_at": stmt.excluded.checked_at}))
    await db.commit()
    if error:
        raise OrgLookupError(error)
    return {"query": q, "found": bool(orgs), "orgs": orgs, "checked_at": iso(utcnow()), "cached": False}


async def cached_many(db: AsyncSession, queries: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Already looked-up orgs for these ИНН/ОГРН (no requests)."""
    from sqlalchemy import select

    rows = (await db.execute(select(OrgLookup).where(OrgLookup.query.in_(queries or [""]), OrgLookup.error.is_(None)))).scalars()
    return {r.query: r.data.get("orgs", []) for r in rows}
