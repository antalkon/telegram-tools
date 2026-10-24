"""Helpers turning Telethon entities into rows of the `tg_peers` cache and avatar files."""

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from telethon import TelegramClient, utils
from telethon.tl import types

from app.config import get_settings
from app.telegram.contacts import tg_phone

BATCH = 400


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
            "phone": tg_phone(entity.phone),
            "tg_created_at": None,
        }
    # Channel.date is the creation date unless the account is a member (then it's the join date)
    created = getattr(entity, "date", None) if getattr(entity, "left", False) else None
    return base | {
        "tg_created_at": created,
        "kind": "channel" if isinstance(entity, (types.Channel, types.ChannelForbidden)) else "chat",
        "first_name": None,
        "last_name": None,
        "title": getattr(entity, "title", None),
        "is_bot": False,
        "is_premium": False,
        "is_deleted": False,
        "phone": None,
    }


TRACKED = ("first_name", "last_name", "title", "username", "photo_id", "phone")


async def upsert_peers(db, entities: list[Any]) -> None:
    """Insert or refresh peers, logging what changed since last time to `peer_history`.
    A phone, once seen, is kept: Telegram leaves it out whenever the profile is seen without access to
    it ("min" users from chat messages, another account, privacy changes). Same for a creation date."""
    from app.models import PeerHistory, TgPeer, utcnow

    entities = [e for e in entities if isinstance(e, (types.User, types.Channel, types.ChannelForbidden, types.Chat))]
    rows = {r["id"]: r | {"_min": bool(getattr(e, "min", False))} for e in entities for r in [peer_row(e)]}
    if not rows:
        return
    now = utcnow()
    ids = list(rows)
    history = []
    for i in range(0, len(ids), 900):
        old = (await db.execute(select(TgPeer.id, *(getattr(TgPeer, f) for f in TRACKED))
                                .where(TgPeer.id.in_(ids[i:i + 900])))).all()
        for row in old:
            new = rows[row[0]]
            for f, before in zip(TRACKED, row[1:], strict=True):
                after = new.get(f)
                # only real changes: a first sighting, or a value missing from a partial ("min") profile, is not one
                if before is None or after is None or before == after or (new["_min"] and f == "photo_id"):
                    continue
                history.append({"peer_id": row[0], "field": "photo" if f == "photo_id" else f,
                                "old": str(before), "new": str(after), "changed_at": now})
    values = [{k: v for k, v in r.items() if k != "_min"} for r in rows.values()]
    for i in range(0, len(values), BATCH):
        stmt = sqlite_insert(TgPeer).values(values[i:i + BATCH])
        cols = {c: stmt.excluded[c] for c in values[0] if c not in ("id", "phone", "tg_created_at")}
        cols["phone"] = func.coalesce(stmt.excluded.phone, TgPeer.phone)
        cols["tg_created_at"] = func.coalesce(TgPeer.tg_created_at, stmt.excluded.tg_created_at)
        cols["updated_at"] = now
        await db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=cols))
    if history:
        await db.execute(sqlite_insert(PeerHistory), history)


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
