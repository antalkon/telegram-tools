"""Per-account access hashes, so a user or channel seen once can be addressed again after a restart."""

from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import utils
from telethon.tl import types

from app.jobs.runner import current_account
from app.models import PeerAccess


async def save_access(db: AsyncSession, entities: list[Any], account_id: int | None = None) -> None:
    """Remember the access hashes of users / channels for the account the current job acts as."""
    account_id = account_id if account_id is not None else current_account.get()
    if account_id is None:
        return
    rows = [{"account_id": account_id, "peer_id": utils.get_peer_id(e), "access_hash": e.access_hash}
            for e in entities if isinstance(e, (types.User, types.Channel)) and getattr(e, "access_hash", None)
            and not getattr(e, "min", False)]  # "min" entities carry a hash that only works in their chat
    for i in range(0, len(rows), 300):
        stmt = sqlite_insert(PeerAccess).values(rows[i:i + 300])
        await db.execute(stmt.on_conflict_do_update(index_elements=["account_id", "peer_id"],
                                                    set_={"access_hash": stmt.excluded.access_hash}))

