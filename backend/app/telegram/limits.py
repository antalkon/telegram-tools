"""How hard the panel pushes Telegram: a profile of pacing settings, applied to every request of every
account (see PacedClient), plus the FloodWaits Telegram answered with, to tune them by."""

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

KEY = "telegram_limits"
Profile = Literal["standard", "optimized", "custom"]
Kind = Literal["heavy", "history", "file", "other"]

# Requests Telegram limits hardest (ResolveUsername is notorious), then message reading, then files.
HEAVY = {"ResolveUsernameRequest", "GetFullUserRequest", "GetFullChannelRequest", "GetFullChatRequest",
         "CheckChatInviteRequest", "GetChannelRecommendationsRequest", "JoinChannelRequest", "ImportChatInviteRequest",
         "GetUsersRequest", "GetChannelsRequest"}
HISTORY = {"GetHistoryRequest", "GetRepliesRequest", "SearchRequest", "GetMessagesRequest", "GetParticipantsRequest",
           "GetForumTopicsRequest", "GetDiscussionMessageRequest"}
FILE = {"GetFileRequest", "GetCdnFileRequest", "GetUserPhotosRequest"}

# Numeric settings: (min, max). Intervals are seconds between two requests of that kind on one account.
FIELDS: dict[str, tuple[float, float]] = {
    "request_interval": (0, 10),
    "history_interval": (0, 30),
    "heavy_interval": (0, 120),
    "file_interval": (0, 10),
    "jitter": (0, 1),  # +0…100% random extra to each pause, so the rhythm does not look scripted
    "flood_sleep_threshold": (0, 600),  # sleep through FloodWaits up to this long inside a request
    "avatar_concurrency": (1, 8),
    "details_limit": (0, 5000),  # channel finder: full profiles per run
    "details_ttl_days": (1, 365),  # channel finder: re-check a profile after
    "web_page_delay": (0.5, 30),  # t.me/s pages
    "job_pause": (0, 3600),  # pause between two jobs on the same account
}
INTEGER = {"flood_sleep_threshold", "avatar_concurrency", "details_limit", "details_ttl_days", "job_pause"}
FLAGS = ("adaptive",)  # after a FloodWait, slow that kind of request down for a while

PROFILES: dict[str, dict[str, Any]] = {
    # how the panel always worked: no extra pauses, Telethon sleeps through short FloodWaits
    "standard": {
        "request_interval": 0, "history_interval": 0, "heavy_interval": 0, "file_interval": 0, "jitter": 0,
        "flood_sleep_threshold": 60, "avatar_concurrency": 3, "details_limit": 500, "details_ttl_days": 7,
        "web_page_delay": 1.5, "job_pause": 0, "adaptive": False,
    },
    # slower and steadier: fewer FloodWaits and less attention from Telegram's anti-spam
    "optimized": {
        "request_interval": 0.3, "history_interval": 1.0, "heavy_interval": 3.0, "file_interval": 0.3, "jitter": 0.3,
        "flood_sleep_threshold": 120, "avatar_concurrency": 2, "details_limit": 200, "details_ttl_days": 14,
        "web_page_delay": 2.5, "job_pause": 20, "adaptive": True,
    },
}

ADAPTIVE_FACTOR = 2.0  # each FloodWait doubles that kind's pause …
ADAPTIVE_MAX = 60.0  # … up to a minute
ADAPTIVE_DECAY = 15 * 60  # and it returns to normal after 15 quiet minutes


@dataclass
class Limits:
    profile: str = "standard"
    values: dict[str, Any] = field(default_factory=lambda: dict(PROFILES["standard"]))

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["values"][name]
        except KeyError as e:
            raise AttributeError(name) from e

    def interval(self, kind: Kind) -> float:
        return {"heavy": self.heavy_interval, "history": self.history_interval, "file": self.file_interval}.get(kind, 0.0)

    def out(self) -> dict[str, Any]:
        return {"profile": self.profile, **self.values, "presets": PROFILES}


_current = Limits()


def current() -> Limits:
    return _current


def clean(raw: dict[str, Any]) -> dict[str, Any]:
    """Known keys only, numbers clamped to their range (custom profile)."""
    out = dict(PROFILES["standard"])
    for k, (lo, hi) in FIELDS.items():
        if k in raw and isinstance(raw[k], (int, float)) and not isinstance(raw[k], bool):
            v = min(max(float(raw[k]), lo), hi)
            out[k] = int(v) if k in INTEGER else v
    for k in FLAGS:
        if k in raw:
            out[k] = bool(raw[k])
    return out


def _build(value: dict[str, Any]) -> Limits:
    profile = value.get("profile") if value.get("profile") in ("standard", "optimized", "custom") else "standard"
    values = clean(value.get("custom") or {}) if profile == "custom" else dict(PROFILES[profile])
    return Limits(profile, values)


async def load(db: AsyncSession) -> Limits:
    global _current
    row = await db.get(Setting, KEY)
    _current = _build(row.value if row else {})
    return _current


async def save(db: AsyncSession, profile: str, custom: dict[str, Any] | None) -> Limits:
    global _current
    row = await db.get(Setting, KEY) or Setting(key=KEY)
    value = dict(row.value or {})
    value["profile"] = profile
    if custom is not None:
        value["custom"] = clean(custom)
    elif profile == "custom" and "custom" not in value:
        value["custom"] = dict(_current.values)  # start from what is in effect now
    row.value = value
    db.add(row)
    await db.commit()
    _current = _build(value)
    return _current


def kind_of(request: Any) -> Kind:
    name = type(request[0] if isinstance(request, list) and request else request).__name__
    if name in HEAVY:
        return "heavy"
    if name in HISTORY:
        return "history"
    if name in FILE:
        return "file"
    return "other"


class Pacer:
    """Spaces out one account's requests. Callers reserve a time slot under a lock and sleep outside it,
    so parallel workers (avatar downloads) queue up instead of bursting."""

    def __init__(self) -> None:
        self._next: dict[str, float] = {}
        self._extra: dict[str, tuple[float, float]] = {}  # kind -> (added pause, when it was raised)
        self._lock = asyncio.Lock()

    def _pause(self, base: float, limits: Limits, kind: str) -> float:
        extra, since = self._extra.get(kind, (0.0, 0.0))
        if extra and time.monotonic() - since > ADAPTIVE_DECAY:
            self._extra.pop(kind, None)
            extra = 0.0
        pause = base + (extra if limits.adaptive else 0.0)
        return pause * (1 + random.uniform(0, limits.jitter)) if pause > 0 else 0.0

    async def wait(self, kind: Kind, limits: Limits) -> None:
        async with self._lock:
            now = time.monotonic()
            at = now
            for key, base in (("all", limits.request_interval), (kind, limits.interval(kind))):
                at = max(at, self._next.get(key, 0.0))
            for key, base in (("all", limits.request_interval), (kind, limits.interval(kind))):
                self._next[key] = at + self._pause(base, limits, key)
        if at > now:
            await asyncio.sleep(at - now)

    def flooded(self, kind: Kind, seconds: int) -> None:
        extra, _ = self._extra.get(kind, (0.0, 0.0))
        self._extra[kind] = (min(max(extra * ADAPTIVE_FACTOR, 1.0), ADAPTIVE_MAX), time.monotonic())
        self._next[kind] = max(self._next.get(kind, 0.0), time.monotonic() + seconds)

    def slowdown(self) -> dict[str, float]:
        now = time.monotonic()
        return {k: round(v, 1) for k, (v, since) in self._extra.items() if now - since <= ADAPTIVE_DECAY}


_pacers: dict[int, Pacer] = {}


def pacer(account_id: int | None) -> Pacer:
    return _pacers.setdefault(account_id or 0, Pacer())


# ---------- FloodWait journal (in memory: what Telegram answered lately, per account and method) ----------

_floods: deque[dict[str, Any]] = deque(maxlen=500)
_requests: dict[int, int] = {}


def count_request(account_id: int | None) -> None:
    _requests[account_id or 0] = _requests.get(account_id or 0, 0) + 1


def record_flood(account_id: int | None, request: Any, seconds: int) -> None:
    name = type(request[0] if isinstance(request, list) and request else request).__name__
    _floods.append({"at": time.time(), "account_id": account_id, "method": name.removesuffix("Request"), "seconds": seconds})


def stats(hours: int = 24) -> dict[str, Any]:
    since = time.time() - hours * 3600
    recent = [f for f in _floods if f["at"] >= since]
    by_method: dict[str, dict[str, Any]] = {}
    for f in recent:
        m = by_method.setdefault(f["method"], {"method": f["method"], "count": 0, "max_seconds": 0, "total_seconds": 0})
        m["count"] += 1
        m["max_seconds"] = max(m["max_seconds"], f["seconds"])
        m["total_seconds"] += f["seconds"]
    return {
        "hours": hours,
        "floods": len(recent),
        "wait_seconds": sum(f["seconds"] for f in recent),
        "requests": sum(_requests.values()),  # since the server started
        "by_method": sorted(by_method.values(), key=lambda m: -m["total_seconds"]),
        "last": [{**f, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f["at"]))} for f in list(recent)[-10:][::-1]],
        "slowdown": {str(a): p.slowdown() for a, p in _pacers.items() if p.slowdown()},
    }
