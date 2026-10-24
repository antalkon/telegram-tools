"""Read a public channel without an account: the t.me/s/<name> web preview Telegram serves to browsers.

Only channels with a username and the preview enabled have one. It shows posts (text, views, date,
forwarded-from, links) newest last, 20 per page, older pages via ?before=<post id>. Comments and members
are not there.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://t.me/s/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TG-Toolkit; +https://github.com/antalkon/telegram-tools)",
           "Accept-Language": "en"}


class PreviewUnavailable(Exception):
    pass


@dataclass
class WebPost:
    post_id: int
    date: datetime | None
    text: str | None
    views: int | None
    media: bool
    links: list[str] = field(default_factory=list)
    fwd_name: str | None = None
    fwd_username: str | None = None


def count(raw: str | None) -> int | None:
    """"5.84M" → 5840000, "1.2K" → 1200, "980" → 980."""
    if not raw:
        return None
    m = re.fullmatch(r"([\d.,]+)\s*([KMB]?)", raw.strip(), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return round(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()])


def channel_id_from_view(token: str | None) -> int | None:
    """Marked channel id from a post's data-view token (base64 JSON whose "c" is minus the bare id)."""
    if not token:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        bare = abs(int(data["c"]))
        return -(1_000_000_000_000 + bare)
    except (ValueError, KeyError, TypeError):
        return None


def parse_page(html: str, username: str) -> tuple[dict[str, Any], list[WebPost]]:
    """(channel info, posts on the page). Raises PreviewUnavailable when the page is not a channel preview."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".tgme_channel_info_header_title")
    if title_el is None:
        raise PreviewUnavailable(f"У @{username} нет публичного веб-превью: это не канал, он приватный или превью отключено")
    info: dict[str, Any] = {"title": title_el.get_text(strip=True), "username": username,
                            "about": None, "subscribers": None, "id": None}
    if desc := soup.select_one(".tgme_channel_info_description"):
        info["about"] = desc.get_text("\n", strip=True) or None
    for c in soup.select(".tgme_channel_info_counter"):
        kind = (c.select_one(".counter_type") or c).get_text(strip=True).lower()
        if kind.startswith("subscriber") or kind.startswith("member"):
            info["subscribers"] = count((c.select_one(".counter_value") or c).get_text(strip=True))

    posts: list[WebPost] = []
    for m in soup.select(".tgme_widget_message[data-post]"):
        try:
            post_id = int(m["data-post"].rsplit("/", 1)[1])
        except (ValueError, IndexError):
            continue
        info["id"] = info["id"] or channel_id_from_view(m.get("data-view"))
        text_el = m.select_one(".tgme_widget_message_text")
        text = None
        links: list[str] = []
        if text_el is not None:
            for br in text_el.find_all("br"):
                br.replace_with("\n")
            text = text_el.get_text().strip() or None
            links = [a["href"] for a in text_el.find_all("a", href=True) if a["href"].startswith("http")]
        links += [a["href"] for a in m.select(".tgme_widget_message_inline_button[href], .tgme_widget_message_link_preview[href]")]
        time_el = m.select_one(".tgme_widget_message_date time[datetime]")
        date = datetime.fromisoformat(time_el["datetime"]) if time_el else None
        fwd_name = fwd_username = None
        if fwd := m.select_one(".tgme_widget_message_forwarded_from_name"):
            fwd_name = fwd.get_text(strip=True) or "скрыто"  # the source hid itself
            if (href := fwd.get("href")) and (um := re.match(r"https?://t\.me/([A-Za-z0-9_]{4,32})", href)):
                fwd_username = um.group(1)
        media = m.select_one(".tgme_widget_message_photo_wrap, .tgme_widget_message_video_player, "
                             ".tgme_widget_message_document, .tgme_widget_message_voice, .tgme_widget_message_roundvideo") is not None
        posts.append(WebPost(post_id, date, text, count((m.select_one(".tgme_widget_message_views") or m).get_text(strip=True))
                             if m.select_one(".tgme_widget_message_views") else None,
                             media, list(dict.fromkeys(links)), fwd_name, fwd_username))
    return info, posts


async def fetch_page(client: httpx.AsyncClient, username: str, before: int | None = None) -> str:
    r = await client.get(BASE + username, params={"before": before} if before else None, headers=HEADERS,
                         follow_redirects=False, timeout=30)
    if r.status_code in (301, 302, 303, 307, 308):
        raise PreviewUnavailable(f"У @{username} нет публичного веб-превью: канал приватный, это чат или превью отключено")
    if r.status_code == 429:
        raise PreviewUnavailable("t.me ограничил частоту запросов — попробуйте позже или соберите через аккаунт")
    r.raise_for_status()
    return r.text
