"""Panel notifications: every event is stored for the in-panel bell and, if configured,
delivered to Telegram — the account's Saved Messages or a bot chat."""

import html
import logging
from typing import Any

import httpx

from app.db import SessionLocal
from app.models import Event, Setting
from app.security import decrypt, encrypt

log = logging.getLogger(__name__)
KEY = "notifications"

DEFAULTS: dict[str, Any] = {
    "target": "none",  # none | saved | bot
    "account_id": None,  # for "saved": which account's Saved Messages
    "bot_token_enc": None,
    "bot_chat_id": None,
    "panel_url": None,  # e.g. https://panel.example.com — links in messages
    "new_users": True,
    "watch": True,
    "failures": True,
    "min_new_users": 1,
}


async def get_settings() -> dict[str, Any]:
    async with SessionLocal() as db:
        row = await db.get(Setting, KEY)
        return DEFAULTS | (row.value if row else {})


def public_settings(s: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in s.items() if k != "bot_token_enc"}
    out["bot_token_set"] = bool(s.get("bot_token_enc"))
    return out


async def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cur = await get_settings()
    if "bot_token" in patch:
        token = (patch.pop("bot_token") or "").strip()
        cur["bot_token_enc"] = encrypt(token) if token else None
    cur |= {k: v for k, v in patch.items() if k in DEFAULTS}
    async with SessionLocal() as db:
        row = await db.get(Setting, KEY) or Setting(key=KEY)
        row.value = cur
        db.add(row)
        await db.commit()
    return cur


async def send_text(text: str, settings: dict[str, Any] | None = None) -> None:
    """Deliver an HTML-formatted message to the configured target; raises on failure."""
    s = settings or await get_settings()
    if s["target"] == "saved":
        from app.telegram.manager import manager  # local import: avoids a cycle at startup

        if not s.get("account_id"):
            raise RuntimeError("Не выбран аккаунт для «Избранного»")
        client = await manager.get_client(int(s["account_id"]))
        await client.send_message("me", text, parse_mode="html", link_preview=False)
    elif s["target"] == "bot":
        if not s.get("bot_token_enc") or not s.get("bot_chat_id"):
            raise RuntimeError("Укажите токен бота и chat_id")
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                f"https://api.telegram.org/bot{decrypt(s['bot_token_enc'])}/sendMessage",
                json={"chat_id": s["bot_chat_id"], "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Bot API: {data.get('description', r.status_code)}")


def _peer_line(p: dict[str, Any]) -> str:
    name = html.escape(p.get("name") or "?")
    if p.get("username"):
        return f'• <a href="https://t.me/{p["username"]}">{name}</a> @{p["username"]}'
    return f"• {name} <code>{p['peer_id']}</code>"


def format_event(kind: str, title: str, payload: dict[str, Any], panel_url: str | None) -> str:
    icon = {"new_users": "🆕", "watch": "⭐", "job_failed": "⚠️"}.get(kind, "ℹ️")
    lines = [f"{icon} <b>{html.escape(title)}</b>"]
    if payload.get("detail"):
        lines.append(html.escape(payload["detail"]))
    people = payload.get("people") or []
    lines += [_peer_line(p) for p in people[:15]]
    if len(people) > 15 or payload.get("more"):
        lines.append(f"…и ещё {payload.get('count', len(people)) - min(15, len(people))}")
    if panel_url and payload.get("path"):
        lines.append(f'\n<a href="{panel_url.rstrip("/")}{payload["path"]}">Открыть в панели</a>')
    return "\n".join(lines)


async def emit(kind: str, title: str, payload: dict[str, Any] | None = None, *, source_id: int | None = None,
               job_id: int | None = None, monitor_id: int | None = None, deliver: bool = True) -> Event:
    payload = payload or {}
    s = await get_settings()
    wants = {"new_users": s["new_users"], "watch": s["watch"], "job_failed": s["failures"]}.get(kind, True)
    if kind == "new_users" and payload.get("count", 0) < (s.get("min_new_users") or 1):
        wants = False
    event = Event(kind=kind, title=title, payload=payload, source_id=source_id, job_id=job_id, monitor_id=monitor_id)
    if deliver and wants and s["target"] != "none":
        try:
            await send_text(format_event(kind, title, payload, s.get("panel_url")), s)
            event.delivery = "sent"
        except Exception as e:  # delivery problems must never break the job that emitted the event
            log.warning("notification delivery failed: %s", e)
            event.delivery, event.delivery_error = "error", str(e)[:500]
    async with SessionLocal() as db:
        db.add(event)
        await db.commit()
        await db.refresh(event)
    return event
