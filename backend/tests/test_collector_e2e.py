"""Full collector run (runner -> tool -> DB -> query/export) against a fake Telegram client."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from telethon import errors
from telethon.tl import functions, types

from app.db import SessionLocal, init_db
from app.jobs import runner as runner_mod
from app.models import Account, Comment, Job, TgPeer
from app.telegram.peers import avatar_path
from app.tools.comment_collector import collector as _registers_tool  # noqa: F401
from app.tools.comment_collector.queries import list_participants

CH, GR = 1001, 2002
T0 = datetime(2026, 1, 1, tzinfo=UTC)

CHANNEL = types.Channel(id=CH, title="Test Channel", photo=types.ChatPhotoEmpty(), date=T0, access_hash=1,
                        broadcast=True, username="testchan")
GROUP = types.Channel(id=GR, title="Test Chat", photo=types.ChatPhotoEmpty(), date=T0, access_hash=2, megagroup=True)


def user(uid, name, photo=None, **kw):
    p = types.UserProfilePhoto(photo_id=photo, dc_id=2) if photo else None
    return types.User(id=uid, first_name=name, access_hash=uid, photo=p, **kw)


ALICE = user(10, "Alice", photo=777, username="alice", premium=True)
BOB = user(11, "Bob")
CAROL = user(12, "Carol", username="carol")


def msg(mid, sender, *, root_of=None, reply_to=None, top=None, minutes=0):
    kw = {}
    if root_of:
        kw["fwd_from"] = types.MessageFwdHeader(date=T0, from_id=types.PeerChannel(CH), channel_post=root_of,
                                                saved_from_peer=types.PeerChannel(CH), saved_from_msg_id=root_of)
        from_id = types.PeerChannel(CH)
    else:
        from_id = types.PeerUser(sender.id)
    if reply_to:
        kw["reply_to"] = types.MessageReplyHeader(reply_to_msg_id=reply_to, reply_to_top_id=top)
    m = types.Message(id=mid, peer_id=types.PeerChannel(GR), date=T0 + timedelta(minutes=minutes),
                      message=f"m{mid}", from_id=from_id, **kw)
    m._sender = CHANNEL if root_of else sender
    return m


GROUP_HISTORY = [
    msg(1, None, root_of=100),
    msg(2, ALICE, reply_to=1, minutes=1),
    msg(3, BOB, reply_to=2, top=1, minutes=2),
    msg(4, CAROL),  # plain chat
    msg(5, BOB, reply_to=4, minutes=3),  # reply in plain chat
    msg(6, None, root_of=101),
    msg(7, ALICE, reply_to=6, minutes=10),
    msg(8, ALICE, reply_to=6, minutes=11),
]


class FakeClient:
    flood_sleep_threshold = 60

    def __init__(self, flood_once=False, group_private=False):
        self.flood_once = flood_once
        self.group_private = group_private

    async def get_entity(self, ref):
        assert ref == "testchan"
        return CHANNEL

    async def __call__(self, req):
        assert isinstance(req, functions.channels.GetFullChannelRequest)
        return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=GR, participants_count=500), chats=[CHANNEL, GROUP])

    async def get_messages(self, entity, limit=0):
        if entity is GROUP:
            if self.group_private:
                raise errors.ChannelPrivateError(request=None)
            return SimpleNamespace(total=len(GROUP_HISTORY))
        return SimpleNamespace(total=2)

    async def iter_messages(self, entity, reverse=True, offset_id=0, reply_to=None, **_):
        if entity is GROUP:
            source = GROUP_HISTORY
        elif reply_to is None:  # channel posts
            source = [SimpleNamespace(id=100, replies=types.MessageReplies(replies=2, replies_pts=0)),
                      SimpleNamespace(id=101, replies=types.MessageReplies(replies=2, replies_pts=0))]
            source = [types.Message(id=s.id, peer_id=types.PeerChannel(CH), date=T0, message="", replies=s.replies)
                      for s in source]
        else:
            roots = {100: 1, 101: 6}
            source = [m for m in GROUP_HISTORY if m.reply_to and (m.reply_to.reply_to_top_id or m.reply_to.reply_to_msg_id) == roots[reply_to]]
        for m in source:
            if m.id <= offset_id:
                continue
            if self.flood_once and m.id == 5:
                self.flood_once = False
                raise errors.FloodWaitError(request=None, capture=0)
            yield m

    async def download_profile_photo(self, entity, file, download_big=False):
        with open(file, "wb") as f:
            f.write(b"\xff\xd8jpeg")
        return file


async def run_job(monkeypatch, client, **params):
    await init_db()

    async def fake_get_client(_account_id):
        return client

    monkeypatch.setattr(runner_mod.manager, "get_client", fake_get_client)
    async with SessionLocal() as db:
        acc = Account(phone="+1", api_id=1, api_hash_enc="x", session_enc="x")
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    runner = runner_mod.JobRunner()
    job = await runner.submit("comment-collector", acc.id, {"channel": "https://t.me/testchan", **params})
    await runner._tasks[job.id]
    async with SessionLocal() as db:
        return await db.get(Job, job.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy, client", [
    ("auto", FakeClient()),
    ("auto", FakeClient(flood_once=True)),  # resumes after FloodWait without double counting
    ("auto", FakeClient(group_private=True)),  # falls back to per-post
    ("per_post", FakeClient()),
])
async def test_full_run(monkeypatch, strategy, client):
    job = await run_job(monkeypatch, client, strategy=strategy)
    assert job.status == "done", job.error
    assert job.result["comments"] == 4
    assert job.result["unique_users"] == 2
    assert job.result["posts_with_comments"] == 2
    expected = "per_post" if strategy == "per_post" or client.group_private else "fast"
    assert job.result["strategy"] == expected

    async with SessionLocal() as db:
        total, rows = await list_participants(db, job.id)
        assert total == 2
        alice, bob = rows
        assert (alice["username"], alice["comments"], alice["posts"], alice["is_premium"]) == ("alice", 3, 2, True)
        assert alice["photo_id"] == "777"  # avatar downloaded
        assert (bob["name"], bob["comments"]) == ("Bob", 1)
        n_comments = (await db.execute(select(func.count()).select_from(Comment).where(Comment.job_id == job.id))).scalar_one()
        assert n_comments == 4
        assert (await db.get(TgPeer, 12)) is None  # Carol only chatted in the group: not a commenter
        _, search = await list_participants(db, job.id, search="@ALI")
        assert [r["peer_id"] for r in search] == [10]
    assert avatar_path(777).exists()


@pytest.mark.asyncio
async def test_bad_channel_type(monkeypatch):
    class GroupClient(FakeClient):
        async def get_entity(self, ref):
            return GROUP

    job = await run_job(monkeypatch, GroupClient())
    assert job.status == "failed"
    assert "группа" in job.error
