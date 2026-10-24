"""Helpers turning Telethon entities into rows of the `tg_peers` cache and avatar files."""

import time
from typing import Any

from telethon import TelegramClient, utils
from telethon.tl import types

from app.config import get_settings


def _photo_id(entity: Any) -> int | None:
    photo = getattr(entity, "photo", None)
    return getattr(photo, "photo_id", None)


def _usernames(entity: Any) -> list[str]:
    names = [u.username for u in (getattr(entity, "usernames", None) or []) if getattr(u, "active", True)]
    if entity_username := getattr(entity, "username", None):
        names.insert(0, entity_username)
    return list(dict.fromkeys(names))


def peer_row(entity: Any) -> dict[str, Any]:
    """Normalize a User / Channel / Chat entity into a dict matching models.TgPeer."""
    usernames = _usernames(entity)
    base: dict[str, Any] = {
        "id": utils.get_peer_id(entity),
        "username": usernames[0] if usernames else None,
        "usernames": usernames,
        "photo_id": _photo_id(entity),
        "is_verified": bool(getattr(entity, "verified", False)),
        "is_scam": bool(getattr(entity, "scam", False)),
        "is_fake": bool(getattr(entity, "fake", False)),
    }
    if isinstance(entity, types.User):
        return base | {
            "kind": "user",
            "first_name": entity.first_name,
            "last_name": entity.last_name,
            "title": None,
            "is_bot": bool(entity.bot),
            "is_premium": bool(entity.premium),
            "is_deleted": bool(entity.deleted),
            "phone": entity.phone,
        }
    return base | {
        "kind": "channel" if isinstance(entity, (types.Channel, types.ChannelForbidden)) else "chat",
        "first_name": None,
        "last_name": None,
        "title": getattr(entity, "title", None),
        "is_bot": False,
        "is_premium": False,
        "is_deleted": False,
        "phone": None,
    }


MISS_TTL = 24 * 3600  # don't retry a photo that failed to download for a day


def avatar_path(photo_id: int):
    return get_settings().avatars_dir / f"{photo_id}.jpg"


def _miss_path(photo_id: int):
    return get_settings().avatars_dir / f"{photo_id}.miss"


def recently_missed(photo_id: int) -> bool:
    p = _miss_path(photo_id)
    return p.exists() and time.time() - p.stat().st_mtime < MISS_TTL


def mark_missed(photo_id: int) -> None:
    _miss_path(photo_id).touch()


async def download_avatar(client: TelegramClient, entity: Any) -> bool:
    """Download the small profile photo once per photo_id. Returns True if a file exists afterwards."""
    photo_id = _photo_id(entity)
    if not photo_id:
        return False
    path = avatar_path(photo_id)
    if path.exists():
        return True
    tmp = path.with_suffix(".part")
    try:
        result = await client.download_profile_photo(entity, file=str(tmp), download_big=False)
    except BaseException:  # includes timeouts/cancellation: never leave a half-written file
        tmp.unlink(missing_ok=True)
        raise
    if result:
        tmp.replace(path)
        return True
    tmp.unlink(missing_ok=True)
    mark_missed(photo_id)
    return False
