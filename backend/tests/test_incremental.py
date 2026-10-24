"""Incremental re-collection, monitoring scheduler and notification delivery."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from telethon.tl import types

from app import notify
from app.db import SessionLocal, init_db
from app.insights.common import active_jobs
from app.jobs import runner as runner_mod
from app.jobs import scheduler
from app.models import Account, Comment, Event, Job, JobParticipant, Monitor, PeerNote, Setting, ThreadRoot
from tests.test_collector_e2e import ALICE, BOB, CH, GROUP, GROUP_HISTORY, T0, FakeClient, msg, user

DAVE = user(13, "Dave", username="dave")


class GrowingClient(FakeClient):
    """Fake whose discussion history can be extended between runs."""

    def __init__(self, history, **kw):
        super().__init__(**kw)
        self.history = list(history)
        self.fetched_ids: list[int] = []

    async def get_messages(self, entity, limit=0, ids=None):
        if ids is not None:
            self.fetched_ids += list(ids)
            by_id = {m.id: m for m in self.history}
            return [by_id.get(i) for i in ids]
        if entity is GROUP and limit == 1:
            return [max(self.history, key=lambda m: m.id)]
        if entity is GROUP:
            if self.group_private:
                from telethon import errors

                raise errors.ChannelPrivateError(request=None)
            return SimpleNamespace(total=len(self.history))
        return SimpleNamespace(total=len(self._posts()))

    def _posts(self):
        roots = {m.fwd_from.channel_post: m.id for m in self.history if m.fwd_from}
        posts = []
        for post_id, root in roots.items():
            thread = [m for m in self.history if m.reply_to and (m.reply_to.reply_to_top_id or m.reply_to.reply_to_msg_id) == root]
            posts.append(types.Message(id=post_id, peer_id=types.PeerChannel(CH), date=T0, message="",
                                       replies=types.MessageReplies(replies=len(thread), replies_pts=0,
                                                                    max_id=max((m.id for m in thread), default=None))))
        return posts

    async def iter_messages(self, entity, reverse=True, offset_id=0, reply_to=None, **_):
        if entity is GROUP:
            source = sorted(self.history, key=lambda m: m.id)
        elif reply_to is None:
            source = self._posts()
        else:
            root = next(m.id for m in self.history if m.fwd_from and m.fwd_from.channel_post == reply_to)
            source = [m for m in self.history if m.reply_to and (m.reply_to.reply_to_top_id or m.reply_to.reply_to_msg_id) == root]
        for m in source:
            if m.id > offset_id:
                yield m


NEW_MESSAGES = [
    msg(9, DAVE, reply_to=1, minutes=30),  # new person, under an OLD post (root outside the new range)
    msg(10, ALICE, reply_to=7, top=6, minutes=31),  # reply-to-reply under an old post
    msg(11, None, root_of=102),  # brand new post
    msg(12, DAVE, reply_to=11, minutes=40),
]


@pytest_asyncio.fixture
async def clean(monkeypatch):
    await init_db()
    async with SessionLocal() as db:
        for model in (Job, Monitor, Event, ThreadRoot, Setting, PeerNote, Account):
            await db.execute(delete(model))
        acc = Account(phone="+1", api_id=1, api_hash_enc="x", session_enc="x")
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    runner = runner_mod.JobRunner()
    monkeypatch.setattr(scheduler, "runner", runner)
    return SimpleNamespace(account_id=acc.id, runner=runner)


def use_client(monkeypatch, client):
    async def get_client(_):
        return client

    monkeypatch.setattr(runner_mod.manager, "get_client", get_client)


async def run(env, **params) -> Job:
    job = await env.runner.submit("comment-collector", env.account_id, {"channel": "@testchan", **params})
    await env.runner.wait(job.id)
    async with SessionLocal() as db:
        return await db.get(Job, job.id)


async def participants(job_id):
    async with SessionLocal() as db:
        rows = (await db.execute(select(JobParticipant.peer_id, JobParticipant.comments).where(JobParticipant.job_id == job_id))).all()
        return dict(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("forget_roots", [False, True])
async def test_incremental_fast(clean, monkeypatch, forget_roots):
    client = GrowingClient(GROUP_HISTORY)
    use_client(monkeypatch, client)
    base = await run(clean)
    assert base.result["mode"] == "full" and base.result["last_group_msg_id"] == 8

    client.history += NEW_MESSAGES
    if forget_roots:  # e.g. a channel collected before roots were remembered
        async with SessionLocal() as db:
            await db.execute(delete(ThreadRoot))
            await db.commit()
    async with SessionLocal() as db:
        db.add(PeerNote(peer_id=ALICE.id, starred=True, tags=[]))
        await db.commit()

    inc = await run(clean, mode="incremental")
    assert inc.status == "done", inc.error
    r = inc.result
    assert (r["mode"], r["base_job_id"], r["new_comments"], r["new_users"], r["new_user_ids"]) == ("incremental", base.id, 3, 1, [DAVE.id])
    assert r["total_comments"] == 7 and r["total_users"] == 3
    assert (1 in client.fetched_ids) == forget_roots  # old root fetched by id only when unknown

    assert await participants(base.id) == {ALICE.id: 4, BOB.id: 1, DAVE.id: 2}
    assert await participants(inc.id) == {}
    async with SessionLocal() as db:
        assert (await active_jobs(db))[-1000000001001] == base.id
        assert (await db.get(Job, base.id)).result["last_group_msg_id"] == 12
        events = (await db.execute(select(Event).order_by(Event.id))).scalars().all()
    assert [e.kind for e in events] == ["new_users", "watch"]
    assert events[0].payload["peer_ids"] == [DAVE.id] and events[0].payload["people"][0]["username"] == "dave"

    # nothing new -> nothing to report, nothing duplicated
    again = await run(clean, mode="incremental")
    assert again.result["new_comments"] == 0 and again.result["new_users"] == 0
    assert await participants(base.id) == {ALICE.id: 4, BOB.id: 1, DAVE.id: 2}
    async with SessionLocal() as db:
        assert (await db.execute(select(Event))).scalars().all().__len__() == 2


@pytest.mark.asyncio
async def test_incremental_per_post_only_reads_fresh_threads(clean, monkeypatch):
    client = GrowingClient(GROUP_HISTORY, group_private=True)
    use_client(monkeypatch, client)
    base = await run(clean)
    assert base.result["strategy"] == "per_post" and base.result["comments"] == 4
    client.history += NEW_MESSAGES
    inc = await run(clean, mode="incremental")
    assert inc.result["new_comments"] == 3 and inc.result["new_user_ids"] == [DAVE.id]
    async with SessionLocal() as db:
        n = len((await db.execute(select(Comment).where(Comment.job_id == base.id))).scalars().all())
    assert n == 7


@pytest.mark.asyncio
async def test_incremental_without_history_runs_full(clean, monkeypatch):
    use_client(monkeypatch, GrowingClient(GROUP_HISTORY))
    job = await run(clean, mode="incremental")
    assert job.result["mode"] == "full" and job.result["upgraded_to_full"] is True
    assert job.result["new_users"] is None
    async with SessionLocal() as db:
        assert not (await db.execute(select(Event))).scalars().all()


@pytest.mark.asyncio
async def test_scheduler_runs_due_monitors(clean, monkeypatch):
    client = GrowingClient(GROUP_HISTORY)
    use_client(monkeypatch, client)
    await run(clean)
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        due = Monitor(channel="@testchan", interval_minutes=60, next_run_at=now - timedelta(minutes=1))
        later = Monitor(channel="@other", interval_minutes=60, next_run_at=now + timedelta(minutes=30))
        off = Monitor(channel="@off", interval_minutes=60, enabled=False, next_run_at=now - timedelta(days=1))
        db.add_all([due, later, off])
        await db.commit()
        due_id = due.id

    client.history += NEW_MESSAGES
    started = await scheduler.tick(now)
    assert len(started) == 1
    await clean.runner.wait(started[0])
    await scheduler.reconcile()
    async with SessionLocal() as db:
        m = await db.get(Monitor, due_id)
        assert (m.last_status, m.last_new_users, m.source_id, m.title) == ("done", 1, -1000000001001, "Test Channel")
        assert scheduler._aware(m.next_run_at) == now + timedelta(minutes=60)
        ev = (await db.execute(select(Event))).scalars().first()
        assert ev.monitor_id == due_id
    assert await scheduler.tick(now + timedelta(minutes=5)) == []  # not due again yet


@pytest.mark.asyncio
async def test_scheduler_reports_failures(clean, monkeypatch):
    class Broken(GrowingClient):
        async def get_entity(self, ref):
            return GROUP  # "this is a group" -> job fails

    use_client(monkeypatch, Broken(GROUP_HISTORY))
    async with SessionLocal() as db:
        db.add(Monitor(channel="@testchan", interval_minutes=60))
        await db.commit()
    [job_id] = await scheduler.tick()
    await clean.runner.wait(job_id)
    await scheduler.reconcile()
    async with SessionLocal() as db:
        m = (await db.execute(select(Monitor))).scalars().one()
        assert m.last_status == "failed" and "группа" in m.last_error
        assert [e.kind for e in (await db.execute(select(Event))).scalars()] == ["job_failed"]


@pytest.mark.asyncio
async def test_notification_delivery(clean, monkeypatch):
    sent = []

    async def fake_send(text, settings=None):
        if "boom" in text:
            raise RuntimeError("chat not found")
        sent.append(text)

    monkeypatch.setattr(notify, "send_text", fake_send)
    await notify.save_settings({"target": "bot", "bot_token": "123:abc", "bot_chat_id": "42", "min_new_users": 2,
                                "panel_url": "https://panel.test"})
    s = notify.public_settings(await notify.get_settings())
    assert s["bot_token_set"] and "bot_token_enc" not in s

    people = [{"peer_id": 1, "name": "<Ann>", "username": "ann"}]
    e1 = await notify.emit("new_users", "Chan: +1", {"count": 1, "people": people})  # below threshold
    e2 = await notify.emit("new_users", "Chan: +5", {"count": 5, "people": people, "path": "/x"})
    e3 = await notify.emit("watch", "boom", {"people": people})
    assert (e1.delivery, e2.delivery, e3.delivery) == (None, "sent", "error")
    assert e3.delivery_error == "chat not found"
    assert "&lt;Ann&gt;" in sent[0] and "https://panel.test/x" in sent[0]
    await notify.save_settings({"bot_token": ""})
    assert not notify.public_settings(await notify.get_settings())["bot_token_set"]
