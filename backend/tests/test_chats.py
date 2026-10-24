"""Chat indexer (messages + members), mixed channel/chat insights and full-text search."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from telethon import errors
from telethon.tl import functions, types

from app.db import SessionLocal, init_db, rebuild_search_index
from app.insights import search, sources, users
from app.insights.common import active_jobs
from app.jobs import runner as runner_mod
from app.jobs import scheduler
from app.models import Account, Event, Job, JobParticipant, Monitor, PeerNote, Setting, SourceMember, ThreadRoot
from app.telegram.links import parse_channel_link
from app.tools.chat_indexer import indexer as _registers_indexer  # noqa: F401
from app.tools.chat_indexer.indexer import day_number, message_record
from app.tools.comment_collector import collector as _registers_collector  # noqa: F401
from tests.test_collector_e2e import ALICE, FakeClient

GR = 3003
T0 = datetime(2026, 3, 2, 10, tzinfo=UTC)
CHAT = types.Channel(id=GR, title="Test Group", photo=types.ChatPhotoEmpty(), date=T0, access_hash=3,
                     megagroup=True, username="testgroup")
FORUM = types.Channel(id=GR, title="Test Forum", photo=types.ChatPhotoEmpty(), date=T0, access_hash=3,
                      megagroup=True, forum=True, username="testgroup")


def person(uid, name, role=types.ChannelParticipant, **kw):
    u = types.User(id=uid, first_name=name, access_hash=uid, **kw)
    if role is types.ChannelParticipantCreator:
        u.participant = role(user_id=uid, admin_rights=types.ChatAdminRights())
    elif role is types.ChannelParticipantAdmin:
        u.participant = role(user_id=uid, promoted_by=1, date=T0, admin_rights=types.ChatAdminRights())
    else:
        u.participant = role(user_id=uid, date=T0 - timedelta(days=30))
    return u


# Alice is the same person (id 10) as the channel commenter in test_collector_e2e
ANNA = person(10, "Alice", username="alice")
IVAN = person(21, "Иван", role=types.ChannelParticipantAdmin)
OLGA = person(22, "Ольга", role=types.ChannelParticipantCreator)
SILENT = person(23, "Молчун")
NEWBIE = person(24, "Новичок")


def chat_msg(mid, sender, text_, *, hours=0, reply_to=None, top=None, forum_topic=False):
    kw = {}
    if reply_to:
        kw["reply_to"] = types.MessageReplyHeader(reply_to_msg_id=reply_to, reply_to_top_id=top, forum_topic=forum_topic or None)
    m = types.Message(id=mid, peer_id=types.PeerChannel(GR), date=T0 + timedelta(hours=hours), message=text_,
                      from_id=types.PeerUser(sender.id) if sender else None, **kw)
    m._sender = sender
    return m


HISTORY = [
    types.MessageService(id=1, peer_id=types.PeerChannel(GR), date=T0, action=types.MessageActionChatCreate(title="x", users=[])),
    chat_msg(2, OLGA, "Добро пожаловать в группу!"),
    chat_msg(3, ANNA, "Привет всем, кто продаёт ВЕЛОСИПЕД?", hours=1),
    chat_msg(4, IVAN, "Я продаю велосипеды, пишите", hours=2, reply_to=3),
    chat_msg(5, None, "анонимный админ"),  # no from_id: skipped
    chat_msg(6, ANNA, "спасибо, Иван", hours=30, reply_to=4),
]
MEMBERS = [ANNA, IVAN, OLGA, SILENT]


class ChatClient(FakeClient):
    def __init__(self, entity=CHAT, history=HISTORY, members=MEMBERS, hidden_members=False):
        super().__init__()
        self.entity = entity
        self.history = list(history)
        self.members = list(members)
        self.hidden_members = hidden_members
        self.min_ids: list[int] = []

    async def get_entity(self, ref):
        if ref == "testchan":
            return await super().get_entity(ref)
        assert ref == "testgroup"
        return self.entity

    async def __call__(self, req):
        if isinstance(req, functions.messages.GetForumTopicsRequest):
            return SimpleNamespace(topics=[types.ForumTopic(id=7, date=T0, title="Продажа", icon_color=0, top_message=7,
                                                            read_inbox_max_id=0, read_outbox_max_id=0, unread_count=0,
                                                            unread_mentions_count=0, unread_reactions_count=0, from_id=types.PeerUser(22),
                                                            notify_settings=types.PeerNotifySettings(), peer=types.PeerChannel(GR),
                                                            unread_poll_votes_count=0)])
        if req.channel is not self.entity:
            return await super().__call__(req)
        return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=None, participants_count=len(self.members),
                                                         can_view_participants=True, participants_hidden=False),
                               chats=[self.entity])

    async def get_messages(self, entity, limit=0, **_):
        if entity is not self.entity:
            return await super().get_messages(entity, limit)
        if limit == 1:
            return [max(self.history, key=lambda m: m.id)]
        return SimpleNamespace(total=len(self.history))

    async def iter_messages(self, entity, limit=None, offset_id=0, min_id=0, **kw):
        if entity is not self.entity:
            async for m in super().iter_messages(entity, offset_id=offset_id, **kw):
                yield m
            return
        self.min_ids.append(min_id)
        n = 0
        for m in sorted(self.history, key=lambda m: -m.id):  # newest first, like Telegram
            if (offset_id and m.id >= offset_id) or m.id <= min_id:
                continue
            if limit is not None and n >= limit:
                return
            n += 1
            yield m

    async def iter_participants(self, entity, limit=None, filter=None):
        if self.hidden_members:
            raise errors.ChatAdminRequiredError(request=None)
        for u in self.members:
            yield u


@pytest_asyncio.fixture
async def env(monkeypatch):
    await init_db()
    async with SessionLocal() as db:
        for model in (Job, Monitor, Event, ThreadRoot, Setting, PeerNote, SourceMember, Account):
            await db.execute(delete(model))
        acc = Account(phone="+1", api_id=1, api_hash_enc="x", session_enc="x")
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    runner = runner_mod.JobRunner()
    monkeypatch.setattr(scheduler, "runner", runner)
    client = ChatClient()

    async def get_client(_):
        return client

    monkeypatch.setattr(runner_mod.manager, "get_client", get_client)
    return SimpleNamespace(account_id=acc.id, runner=runner, client=client)


async def index(env, tool="chat-indexer", link="@testgroup", **params) -> Job:
    job = await env.runner.submit(tool, env.account_id, {"channel": link, **params})
    await env.runner._tasks[job.id]
    async with SessionLocal() as db:
        return await db.get(Job, job.id)


async def people(job_id):
    async with SessionLocal() as db:
        rows = (await db.execute(select(JobParticipant.peer_id, JobParticipant.comments, JobParticipant.member, JobParticipant.role)
                                 .where(JobParticipant.job_id == job_id))).all()
    return {r[0]: r[1:] for r in rows}


def test_message_record_threads():
    plain = message_record(HISTORY[3], forum=False)
    assert plain["post_id"] == day_number(T0) and plain["reply_to"] == 3 and plain["sender_id"] == 21
    assert message_record(HISTORY[0], forum=False) is None  # service message
    assert message_record(HISTORY[4], forum=False) is None  # anonymous admin
    in_topic = chat_msg(9, ANNA, "x", reply_to=7, forum_topic=True)
    reply_in_topic = chat_msg(10, IVAN, "y", reply_to=9, top=7, forum_topic=True)
    assert (message_record(in_topic, True)["post_id"], message_record(in_topic, True)["reply_to"]) == (7, None)
    assert (message_record(reply_in_topic, True)["post_id"], message_record(reply_in_topic, True)["reply_to"]) == (7, 9)
    assert message_record(chat_msg(11, ANNA, "z"), True)["post_id"] == 1  # General


def test_numeric_links():
    assert parse_channel_link("-1001234567890").channel_id == 1234567890
    assert parse_channel_link("-4567890").chat_id == 4567890


@pytest.mark.asyncio
async def test_full_index(env):
    job = await index(env)
    assert job.status == "done", job.error
    r = job.result
    assert (r["comments"], r["unique_users"], r["members"], r["people"]) == (4, 3, 4, 4)
    assert r["type"] == "supergroup" and r["thread_unit"] == "day" and r["last_msg_id"] == 6
    assert r["members_status"] == "ok"
    p = await people(job.id)
    assert p[10] == (2, True, "member") and p[21] == (1, True, "admin") and p[22] == (1, True, "creator")
    assert p[23] == (0, True, "member")  # never wrote: still found via the member list

    async with SessionLocal() as db:
        src = (await sources.list_sources(db))[0]
        assert (src["family"], src["users"], src["members"], src["people"], src["comments"]) == ("chat", 3, 4, 4, 4)
        a = await sources.source_analytics(db, src["id"])
        assert a["audience"] == {"members": 4, "authors": 3, "silent": 1, "outside": 0, "admins": 2}
        assert a["top_posts"][0]["label"] == "02.03.2026" and a["top_posts"][0]["link"] == "https://t.me/testgroup/2"
        total, rows = await users.list_users(db, presence="silent")
        assert total == 1 and rows[0]["peer_id"] == 23 and rows[0]["member"] is True
        assert (await users.list_users(db, presence="active"))[0] == 3
        feed = await users.user_comments(db, 10, None)
        assert feed[0]["link"] == "https://t.me/testgroup/6" and feed[0]["thread"] == "03.03.2026"
        conn = await users.connections(db, 10)
        assert {d["peer_id"]: (d["replied_to"], d["replied_by"]) for d in conn["dialogs"]} == {21: (1, 1)}


@pytest.mark.asyncio
async def test_hidden_members_and_depth(env):
    env.client.hidden_members = True
    job = await index(env, max_messages=100)
    assert job.status == "done", job.error
    assert job.result["members_status"] == "hidden" and job.result["members"] == 0
    assert job.result["unique_users"] == 3  # messages still indexed

    job = await index(env, since="2026-03-03")  # only Alice's message on day 2
    assert job.result["comments"] == 1


@pytest.mark.asyncio
async def test_forum_topics(env):
    env.client.entity = FORUM
    env.client.history = [chat_msg(7, OLGA, "тема"), chat_msg(8, ANNA, "в теме", reply_to=7, forum_topic=True)]
    job = await index(env)
    assert job.result["type"] == "forum" and job.result["topics"] == {"7": "Продажа", "1": "General"}
    async with SessionLocal() as db:
        a = await sources.source_analytics(db, job.source_id)
        assert {t["label"] for t in a["top_posts"]} == {"Продажа", "General"}


@pytest.mark.asyncio
async def test_incremental_chat(env):
    base = await index(env)
    env.client.history.append(chat_msg(7, NEWBIE, "Новенький тут", hours=40))
    env.client.members.append(NEWBIE)
    env.client.members.remove(SILENT)  # left the group
    async with SessionLocal() as db:
        db.add(PeerNote(peer_id=10, starred=True, tags=[]))
        await db.commit()
    env.client.history.append(chat_msg(8, ANNA, "и снова я", hours=41))

    inc = await index(env, mode="incremental")
    assert inc.status == "done", inc.error
    assert env.client.min_ids[-1] == 6  # only messages after the last indexed one
    assert inc.result["mode"] == "incremental" and inc.result["new_comments"] == 2
    assert inc.result["new_user_ids"] == [24] and inc.result["new_authors"] == 1
    p = await people(base.id)
    assert 23 not in p and p[24] == (1, True, "member") and p[10][0] == 3
    async with SessionLocal() as db:
        b = await db.get(Job, base.id)
        assert b.result["comments"] == 6 and b.result["last_msg_id"] == 8
        assert (await active_jobs(db))[base.source_id] == base.id
        kinds = sorted(e.kind for e in (await db.execute(select(Event))).scalars())
        assert kinds == ["new_users", "watch"]


@pytest.mark.asyncio
async def test_channel_and_chat_together(env):
    chan = await index(env, tool="comment-collector", link="@testchan")
    chat = await index(env)
    assert chan.status == chat.status == "done"
    async with SessionLocal() as db:
        _, rows = await users.list_users(db, min_sources=2)
        assert [r["peer_id"] for r in rows] == [ALICE.id]  # commenter in the channel + member of the chat
        assert (await users.list_users(db, family="chat"))[0] == 4
        m = await sources.overlap_matrix(db, None)
        assert m["pairs"][0]["shared"] == 1
        prof = await users.user_profile(db, ALICE.id)
        assert prof["totals"]["sources"] == 2 and prof["totals"]["member_of"] == 1
        types_ = {s["source"]["family"] for s in prof["sources"]}
        assert types_ == {"channel", "chat"}


@pytest.mark.asyncio
async def test_search(env):
    await index(env, tool="comment-collector", link="@testchan")
    job = await index(env)
    async with SessionLocal() as db:
        res = await search.search_messages(db, q="велосипед")  # prefix + case folding, Cyrillic
        assert res["total"] == 2
        assert {i["msg_id"] for i in res["items"]} == {3, 4}
        assert "\x02ВЕЛОСИПЕД\x03" in next(i["text"] for i in res["items"] if i["msg_id"] == 3)
        assert res["facets"] == [{"source_id": job.source_id, "title": "Test Group", "count": 2}]
        assert [s["peer_id"] for s in res["top_senders"]][:2] in ([10, 21], [21, 10])
        assert (await search.search_messages(db, q="велосипед -продаю"))["total"] == 1
        assert (await search.search_messages(db, q='"продаю велосипеды"'))["total"] == 1
        assert (await search.search_messages(db, q="велосипед", sender_id=21))["total"] == 1
        assert (await search.search_messages(db, q="m2"))["items"][0]["link"] == "https://t.me/testchan/100?comment=2"
        assert (await search.search_messages(db, q="велосипед", family="channel"))["total"] == 0
        assert (await search.search_messages(db, q="", date_from=datetime(2026, 3, 3).date()))["total"] == 1
        ctx = await search.message_context(db, job.id, 4, around=1)
        assert [i["msg_id"] for i in ctx["items"]] == [3, 4, 6] and ctx["items"][1]["focus"]

        db.add(PeerNote(peer_id=21, ignored=True, tags=[]))  # ignored people drop out of search too
        await db.commit()
        assert (await search.search_messages(db, q="велосипед"))["total"] == 1

    await rebuild_search_index()
    async with SessionLocal() as db:
        await db.execute(delete(Job).where(Job.id == job.id))  # cascades through comments → FTS triggers
        await db.commit()
        assert (await db.execute(text("SELECT count(*) FROM comments_fts WHERE comments_fts MATCH 'велосипед*'"))).scalar() == 0


def test_fts_query_syntax():
    assert search.fts_query('кот "рыжий пёс" -собака') == '"рыжий пёс" AND "кот"* NOT "собака"*'
    assert search.fts_query("-только") is None
    assert search.fts_query('a"b OR c') == '"a"* AND "b"* AND "OR"* AND "c"*'  # operators are just words


@pytest.mark.asyncio
async def test_chat_monitor_uses_its_tool(env):
    await index(env)
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        m = Monitor(channel="@testgroup", tool="chat-indexer", options={"collect_members": False},
                    interval_minutes=60, next_run_at=now - timedelta(minutes=1))
        db.add(m)
        await db.commit()
    started = await scheduler.tick(now)
    await env.runner._tasks[started[0]]
    async with SessionLocal() as db:
        job = await db.get(Job, started[0])
        assert job.tool == "chat-indexer" and job.input["collect_members"] is False and job.status == "done", job.error
        assert job.result["members_status"] == "skipped"
