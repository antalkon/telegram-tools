"""Avatar phase: cache reuse, one fetch per photo, FloodWait gate, failures remembered, skip signal."""

import asyncio

import pytest
from telethon import errors
from telethon.tl import types

from app.telegram.peers import avatar_path, mark_missed, recently_missed
from app.tools.comment_collector.collector import CommentCollector


def person(uid, photo):
    return types.User(id=uid, first_name=f"u{uid}", access_hash=1,
                      photo=types.UserProfilePhoto(photo_id=photo, dc_id=2) if photo else None)


class Ctx:
    def __init__(self):
        self.signals = set()
        self.progress = {}
        self.updates = []

    async def update(self, force=False, **kw):
        self.progress |= kw
        self.updates.append(kw)


class Client:
    flood_sleep_threshold = 60

    def __init__(self, flood_on=(), fail_on=(), hang_on=()):
        self.calls = []
        self.flood_on, self.fail_on, self.hang_on = set(flood_on), set(fail_on), set(hang_on)

    async def download_profile_photo(self, entity, file, download_big=False):
        pid = entity.photo.photo_id
        self.calls.append(pid)
        assert self.flood_sleep_threshold == 0  # FloodWaits must surface, not sleep silently
        if pid in self.flood_on:
            self.flood_on.discard(pid)
            raise errors.FloodWaitError(request=None, capture=0)
        if pid in self.fail_on:
            raise errors.FileReferenceExpiredError(request=None)
        if pid in self.hang_on:
            await asyncio.sleep(3600)
        with open(file, "wb") as f:
            f.write(b"jpg")
        return file


@pytest.mark.asyncio
async def test_cache_dedup_flood_and_failures(monkeypatch):
    avatar_path(9001).write_bytes(b"old")  # already cached from a previous run
    monkeypatch.setattr("app.tools.comment_collector.collector.AVATAR_TIMEOUT", 0.2)
    client = Client(flood_on={9002}, fail_on={9003}, hang_on={9005})
    ents = [person(1, 9001), person(2, 9002), person(3, 9003), person(4, 9004), person(5, 9004), person(6, 9005), person(7, None)]
    ctx = Ctx()
    stats = await CommentCollector()._download_avatars(ctx, client, ents)

    assert stats == {"downloaded": 2, "cached": 1, "failed": 2, "skipped": 0}
    assert 9001 not in client.calls and client.calls.count(9004) == 1  # cached skipped, shared photo once
    assert client.calls.count(9002) == 2  # retried after the FloodWait
    assert any(u.get("flood_wait_until") for u in ctx.updates)  # countdown shown
    assert ctx.progress["avatars_total"] == 4 and ctx.progress["avatars_cached"] == 1
    assert recently_missed(9003) and recently_missed(9005)  # broken + stalled remembered
    assert client.flood_sleep_threshold == 60  # restored

    again = Client()
    await CommentCollector()._download_avatars(Ctx(), again, ents)
    assert again.calls == []  # nothing left to fetch: cached or recently failed


@pytest.mark.asyncio
async def test_skip_signal_stops_downloads():
    ctx = Ctx()
    ctx.signals.add("skip_avatars")
    client = Client()
    stats = await CommentCollector()._download_avatars(ctx, client, [person(i, 9100 + i) for i in range(5)])
    assert client.calls == [] and stats["skipped"] == 5


def test_miss_marker():
    mark_missed(9200)
    assert recently_missed(9200) and not recently_missed(9201)
