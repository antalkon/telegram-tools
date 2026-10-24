"""Contacts in free text: phone numbers, e-mails, links, crypto wallets, Russian company ids
(ИНН / ОГРН, checksum-verified) and ad marking (erid). Also the phone Telegram shows in a profile."""

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

import phonenumbers

DEFAULT_REGION = "RU"  # numbers written without a country code ("8 999 …") are read as Russian


def tg_phone(raw: str | None) -> str | None:
    """Telegram gives the profile phone as bare digits; store it as +digits."""
    digits = re.sub(r"\D", "", raw or "")
    return f"+{digits}" if digits else None


def extract_phones(text: str | None) -> list[str]:
    """Valid phone numbers in free text, as E.164 (+79991234567), in order of appearance."""
    if not text:
        return []
    out: list[str] = []
    for m in phonenumbers.PhoneNumberMatcher(text, DEFAULT_REGION, leniency=phonenumbers.Leniency.VALID):
        e164 = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
        if e164 not in out:
            out.append(e164)
    return out


_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b")
_URL = re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.I)
_TG_HOSTS = {"t.me", "telegram.me", "telegram.dog", "www.t.me"}
_WALLETS = {
    "ton": re.compile(r"\b(?:EQ|UQ)[A-Za-z0-9_-]{46}\b"),
    "eth": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),  # also USDT/USDC on ERC-20, BSC
    "tron": re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b"),  # USDT TRC-20
    "btc": re.compile(r"\bbc1[ac-hj-np-z02-9]{11,71}\b"),
}
# ids only next to their name: bare 10-12 digit numbers are mostly something else
_INN = re.compile(r"ИНН\s*[:№]?\s*(\d{10}|\d{12})\b", re.I)
_OGRN = re.compile(r"ОГРН(?:ИП)?\s*[:№]?\s*(\d{13}|\d{15})\b", re.I)
_ERID = re.compile(r"\berid[\s:=]*([A-Za-z0-9]{6,40})\b", re.I)
_AD = re.compile(r"\bРеклама[.:,]?\s+(?:\S+\s+){0,1}?(«[^»]{2,80}»|(?:ООО|АО|ПАО|ЗАО|ИП|ОАО)\s[^,\n]{2,80}|[^,\n]{2,60}?)\s*,?\s*ИНН", re.I)


def valid_inn(v: str) -> bool:
    d = [int(c) for c in v]

    def check(coefs: list[int], n: int) -> int:
        return sum(c * x for c, x in zip(coefs, d[:n], strict=False)) % 11 % 10

    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8], 9) == d[9]
    if len(d) == 12:
        return (check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 10) == d[10]
                and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 11) == d[11])
    return False


def valid_ogrn(v: str) -> bool:
    if len(v) == 13:
        return int(v[:12]) % 11 % 10 == int(v[12])
    if len(v) == 15:
        return int(v[:14]) % 13 % 10 == int(v[14])
    return False


def extract_contacts(text: str | None, links: list[str] | None = None) -> dict[str, list[str]]:
    """Every kind of contact found in a text (plus the URLs of its hidden links), each list in order
    of appearance without duplicates. Keys are only present when something was found."""
    if not text and not links:
        return {}
    body = text or ""
    urls = list(dict.fromkeys([*_URL.findall(body), *(links or [])]))
    out: dict[str, list[str]] = {
        "phones": extract_phones(body),
        "emails": list(dict.fromkeys(m.lower() for m in _EMAIL.findall(body))),
        "sites": list(dict.fromkeys(u.rstrip(".,;:!?") for u in urls if (urlparse(u).hostname or "").lower() not in _TG_HOSTS)),
        "inn": list(dict.fromkeys(v for v in _INN.findall(body) if valid_inn(v))),
        "ogrn": list(dict.fromkeys(v for v in _OGRN.findall(body) if valid_ogrn(v))),
        "erid": list(dict.fromkeys([*_ERID.findall(body), *(m for u in urls for m in _ERID.findall(u.replace("?", " ").replace("&", " ")))])),
    }
    for kind, rx in _WALLETS.items():
        out[f"wallet_{kind}"] = list(dict.fromkeys(rx.findall(body)))
    return {k: v for k, v in out.items() if v}


def ad_marking(text: str | None, links: list[str] | None = None) -> dict[str, Any] | None:
    """{"erid", "advertiser", "inn"} of a post marked as an ad, or None."""
    c = extract_contacts(text, links)
    if not c.get("erid") and not (text and re.search(r"\bРеклама\b", text) and c.get("inn")):
        return None
    m = _AD.search(text or "")
    adv = m.group(1).strip() if m else None
    if adv and adv.startswith("«") and adv.endswith("»"):
        adv = adv[1:-1]
    return {"erid": (c.get("erid") or [None])[0], "advertiser": adv,
            "inn": (c.get("inn") or [None])[0]}


def merge_contacts(items: list[tuple[dict[str, list[str]], Any]], limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Contacts of many texts → per kind: value, how many texts have it, and up to 3 example refs."""
    counts: dict[str, Counter] = {}
    refs: dict[tuple[str, str], list[Any]] = {}
    for contacts, ref in items:
        for kind, values in contacts.items():
            for v in values:
                counts.setdefault(kind, Counter())[v] += 1
                r = refs.setdefault((kind, v), [])
                if len(r) < 3:
                    r.append(ref)
    return {kind: [{"value": v, "count": n, "refs": refs[(kind, v)]} for v, n in c.most_common(limit)]
            for kind, c in counts.items()}


def digits_query(search: str) -> str | None:
    """The digits of a search that looks like a phone number (at least 5 digits, nothing but separators)."""
    s = search.strip()
    if not re.fullmatch(r"[+\d\s()\-.]+", s):
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) < 5:
        return None
    # "8 999 …" is how Russian numbers are often typed; stored numbers are +7…
    return "7" + digits[1:] if len(digits) == 11 and digits[0] == "8" else digits


BACKFILL_KEY = "contacts_backfill_v1"


async def backfill_bio_phones() -> int:
    """Once: phones from bios read before bio_phones existed. Returns how many people got some."""
    from sqlalchemy import select, update

    from app.db import SessionLocal
    from app.models import Setting, TgPeer

    async with SessionLocal() as db:
        if await db.get(Setting, BACKFILL_KEY):
            return 0
        n = 0
        for pid, about in (await db.execute(select(TgPeer.id, TgPeer.about).where(TgPeer.about.is_not(None)))).all():
            if phones := extract_phones(about):
                await db.execute(update(TgPeer).where(TgPeer.id == pid).values(bio_phones=phones))
                n += 1
        db.add(Setting(key=BACKFILL_KEY, value={"people": n}))
        await db.commit()
        return n
