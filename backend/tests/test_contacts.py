"""Phones: parsing from bios, Telegram profile phones kept across updates, search by digits."""

import pytest
from sqlalchemy import delete
from telethon.tl import types

from app.db import SessionLocal, init_db
from app.insights import dossier
from app.models import TgPeer
from app.telegram.contacts import digits_query, extract_phones, tg_phone
from app.telegram.peers import upsert_peers


def test_extract_phones():
    bio = "Пишите: +7 (999) 123-45-67 или 8 912 345 67 89, офис +44 20 7946 0958. Год 2024, id 123456789"
    assert extract_phones(bio) == ["+79991234567", "+79123456789", "+442079460958"]
    assert extract_phones("t.me/joinchat/12345678901 и 31.12.2024") == []
    assert extract_phones(None) == []


def test_digits_query():
    assert digits_query("+7 (999) 123-45-67") == "79991234567"
    assert digits_query("8 999 123 45 67") == "79991234567"
    assert digits_query("12345") == "12345"
    assert digits_query("1234") is None and digits_query("иван 12345") is None
    assert tg_phone("79991234567") == "+79991234567" and tg_phone(None) is None


@pytest.mark.asyncio
async def test_phone_kept_when_later_hidden():
    await init_db()
    async with SessionLocal() as db:
        await db.execute(delete(TgPeer).where(TgPeer.id == 777))
        await upsert_peers(db, [types.User(id=777, first_name="Олег", phone="79991234567", access_hash=1)])
        await db.commit()
        # the same person seen later in a chat ("min" user): no phone, new name
        await upsert_peers(db, [types.User(id=777, first_name="Олег П.", min=True, access_hash=1)])
        await db.commit()
        p = await db.get(TgPeer, 777)
        await db.refresh(p)
        assert (p.phone, p.first_name) == ("+79991234567", "Олег П.")

        found = await dossier.search_people(db, "8 999 123-45-67")
        assert found["items"][0]["peer_id"] == 777 and "Telegram" in found["items"][0]["matches"][0]["snippet"]
        await db.execute(delete(TgPeer).where(TgPeer.id == 777))  # don't leak into other tests
        await db.commit()
