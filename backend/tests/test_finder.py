"""Channel finder: personal channels, bio links / @mentions, senders, caching and the API views."""

import struct
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from telethon import errors
from telethon.tl import functions, types

from app.api import discovery
from app.db import SessionLocal
from app.insights import users
from app.models import FoundChannel, Job, FoundChannelLink, PeerAccess, TgPeer, UsernameLookup
from app.telegram.bio import extract_refs
from app.tools.channel_finder import finder as _registers_finder  # noqa: F401
from tests.test_chats import ChatClient, T0, env as chat_env, index  # noqa: F401

env = chat_env


def channel(cid, title, username=None, broadcast=True):
    return types.Channel(id=cid, title=title, photo=types.ChatPhotoEmpty(), date=T0, access_hash=cid,
                         broadcast=broadcast or None, megagroup=None if broadcast else True, username=username)


PERSONAL = channel(500, "Блог Алисы", "alice_blog")
BLOG = channel(501, "Blog One", "blog_one")
TALK = channel(502, "Talk", "talk_chat", broadcast=False)

BIOS = {
    10: ("Пишу в t.me/blog_one, болтаем в @talk_chat, друг @friend_user, бот @helper_bot", PERSONAL.id),
    21: ("Связь: @ivan_contact, закрытый канал https://t.me/+INV123", None),
    22: (None, None),
}
RESOLVE = {
    "blog_one": BLOG, "talk_chat": TALK,
    "friend_user": types.User(id=99, first_name="Friend", access_hash=99),
    "ivan_contact": types.User(id=21, first_name="Иван", access_hash=21),
}


class FinderClient(ChatClient):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []
        self.flood_resolve = 0
        self.transport_429 = False

    async def __call__(self, req):
        if isinstance(req, functions.users.GetFullUserRequest):
            uid = req.id.user_id
            self.calls.append(f"full:{uid}")
            if uid == 23:
                raise errors.UserIdInvalidError(request=None)
            about, personal = BIOS[uid]
            return SimpleNamespace(
                full_user=SimpleNamespace(about=about, personal_channel_id=personal),
                users=[types.User(id=uid, first_name="x", access_hash=uid)], chats=[PERSONAL] if personal else [])
        if isinstance(req, functions.contacts.ResolveUsernameRequest):
            self.calls.append(f"resolve:{req.username}")
            if self.flood_resolve:
                raise errors.FloodWaitError(request=None, capture=self.flood_resolve)
            hit = RESOLVE.get(req.username)
            if hit is None:
                raise errors.UsernameNotOccupiedError(request=None)
            if isinstance(hit, types.User):
                return types.contacts.ResolvedPeer(peer=types.PeerUser(hit.id), chats=[], users=[hit])
            return types.contacts.ResolvedPeer(peer=types.PeerChannel(hit.id), chats=[hit], users=[])
        if isinstance(req, functions.messages.CheckChatInviteRequest):
            self.calls.append(f"invite:{req.hash}")
            if self.transport_429:
                raise errors.InvalidBufferError(struct.pack("<i", -429))
            return types.ChatInvite(title="Секретный", photo=types.PhotoEmpty(id=0), participants_count=40, color=0,
                                    broadcast=True, channel=True)
        if isinstance(req, functions.channels.GetFullChannelRequest) and req.channel in (PERSONAL, BLOG, TALK):
            self.calls.append(f"details:{req.channel.id}")
            return SimpleNamespace(full_chat=SimpleNamespace(participants_count=req.channel.id * 2, about=f"about {req.channel.title}"),
                                   chats=[req.channel])
        return await super().__call__(req)


@pytest_asyncio.fixture
async def fenv(env, monkeypatch):
    async with SessionLocal() as db:
        for model in (FoundChannelLink, FoundChannel, UsernameLookup, PeerAccess, TgPeer):
            await db.execute(delete(model))
        await db.commit()
    client = FinderClient()

    async def get_client(_):
        return client

    from app.jobs import runner as runner_mod
    monkeypatch.setattr(runner_mod.manager, "get_client", get_client)
    env.client = client
    return env


async def find(env, **options):
    job = await env.runner.submit("channel-finder", env.account_id, options)
    await env.runner.wait(job.id)
    async with SessionLocal() as db:
        return await db.get(Job, job.id)


def test_extract_refs():
    refs = extract_refs("Канал: https://t.me/my_channel, чат t.me/+AbCdEf123 и @news_ru; почта a@mail.ru, бот @helper_bot, "
                        "пост t.me/durov/123, cool_blog.t.me, t.me/joinchat/XYZ12345 и снова @MY_CHANNEL")
    assert [r.key for r in refs] == ["my_channel", "+AbCdEf123", "durov", "cool_blog", "+XYZ12345", "news_ru"]
    assert extract_refs(None) == [] and extract_refs("t.me/c/123/45 и t.me/addlist/abc") == []


@pytest.mark.asyncio
async def test_finder_end_to_end(fenv):
    chat = await index(fenv)  # Alice (10), Иван (21), Ольга (22), Молчун (23); access hashes get stored
    assert chat.status == "done", chat.error
    async with SessionLocal() as db:
        stored = set((await db.execute(select(PeerAccess.peer_id).where(PeerAccess.account_id == fenv.account_id))).scalars())
    assert {10, 21, 22, 23} <= stored

    job = await find(fenv)
    assert job.status == "done", job.error
    r = job.result
    assert (r["users_total"], r["checked"], r["personal"], r["no_access"]) == (4, 4, 1, 0)
    assert r["with_bio_refs"] == 2 and r["deferred"] == 0
    # bots are skipped without a request; users found in bios are resolved once and then cached
    resolved = [c for c in fenv.client.calls if c.startswith("resolve:")]
    assert sorted(resolved) == ["resolve:blog_one", "resolve:friend_user", "resolve:ivan_contact", "resolve:talk_chat"]
    assert "invite:INV123" in fenv.client.calls

    async with SessionLocal() as db:
        found = {f.key: f for f in (await db.execute(select(FoundChannel))).scalars()}
        links = set((await db.execute(select(FoundChannelLink.key, FoundChannelLink.user_id, FoundChannelLink.via))).all())
        alice = await db.get(TgPeer, 10)
    assert set(found) == {str(-1000000000500), str(-1000000000501), str(-1000000000502), "+INV123"}
    assert found["-1000000000500"].type == "channel" and found["-1000000000500"].members_count == 1000
    assert found["-1000000000502"].type == "supergroup" and found["-1000000000502"].about == "about Talk"
    assert found["+INV123"].private and found["+INV123"].members_count == 40 and found["+INV123"].peer_id is None
    assert ("-1000000000500", 10, "personal") in links and ("-1000000000501", 10, "bio") in links
    assert ("-1000000000502", 10, "bio") in links and ("+INV123", 21, "bio") in links
    assert alice.personal_channel_id == -1000000000500 and "blog_one" in alice.about and alice.profile_checked_at

    # second run: every profile already checked, every username cached -> no requests at all
    fenv.client.calls.clear()
    again = await find(fenv)
    assert again.status == "done" and again.result["users_total"] == 0
    assert not [c for c in fenv.client.calls if not c.startswith("details:")]

    async with SessionLocal() as db:
        page = await discovery.found_channels(status="new", type="all", via="all", q="", sort="users", offset=0,
                                              limit=100, format=None, db=db)
        assert page["total"] == 4 and page["counts"]["new"] == 4
        top = page["items"][0]
        assert top["key"] in ("-1000000000500", "-1000000000501", "-1000000000502") and top["people"][0]["peer_id"] == 10
        private = await discovery.found_channels(status="new", type="private", via="all", q="", sort="users", offset=0,
                                                 limit=100, format=None, db=db)
        assert [i["link"] for i in private["items"]] == ["https://t.me/+INV123"]
        chats = await discovery.found_channels(status="new", type="chat", via="bio", q="talk", sort="users", offset=0,
                                               limit=100, format=None, db=db)
        assert [i["title"] for i in chats["items"]] == ["Talk"]

        await discovery.dismiss_found(discovery.DismissIn(keys=["-1000000000501"]), db=db)
        page = await discovery.found_channels(status="new", type="all", via="all", q="", sort="users", offset=0,
                                              limit=100, format=None, db=db)
        assert page["counts"]["dismissed"] == 1 and "-1000000000501" not in [i["key"] for i in page["items"]]

        prof = await users.user_profile(db, 10)
        assert prof["about"].startswith("Пишу") and prof["channels"][0]["via"] == ["personal"]
        assert {c["title"] for c in prof["channels"]} == {"Блог Алисы", "Blog One", "Talk"}
        stats = await discovery.discovery_stats(db=db)
        assert (stats["people"], stats["checked"], stats["personal"], stats["found"]) == (4, 4, 1, 4)


@pytest.mark.asyncio
async def test_finder_without_access_uses_username(fenv):
    await index(fenv)
    async with SessionLocal() as db:
        await db.execute(delete(PeerAccess))
        await db.commit()

    async def get_input_entity(ref):
        if ref == "alice":  # resolved by @username
            return types.InputPeerUser(10, 10)
        raise ValueError("not cached")

    fenv.client.get_input_entity = get_input_entity
    job = await find(fenv, use_usernames=True, check_bio=False)
    r = job.result
    assert job.status == "done", job.error
    assert (r["checked"], r["via_username"], r["no_access"]) == (1, 1, 3)  # only Alice has a username
    assert not [c for c in fenv.client.calls if c.startswith("resolve:")]  # bio resolving was off


@pytest.mark.asyncio
async def test_finder_postpones_long_floodwait(fenv):
    """A long ban on username lookups only parks those lookups: profiles, invites and channel
    details still go through, and later runs skip the banned call until the ban ends."""
    await index(fenv)
    fenv.client.flood_resolve = 3600
    job = await find(fenv)
    r = job.result
    assert job.status == "done", job.error
    assert 3590 <= r["postponed_sec"] <= 3600 and set(r["blocked"]) == {"resolve"}
    assert r["checked"] == 4 and r["personal"] == 1 and r["deferred"] == 4  # the 4 usernames; the invite went through
    assert "details:500" in fenv.client.calls
    async with SessionLocal() as db:
        cached = {u.username for u in (await db.execute(select(UsernameLookup))).scalars()}
        assert cached == {"+INV123"}  # usernames not cached: looked up once the ban ends
        stats = await discovery.discovery_stats(db=db)
        assert set(stats["blocked"]) == {"resolve"}

    fenv.client.calls.clear()
    again = await find(fenv)
    assert again.result["deferred"] == 4 and set(again.result["blocked"]) == {"resolve"}
    assert not [c for c in fenv.client.calls if c.startswith(("resolve:", "invite:"))]


@pytest.mark.asyncio
async def test_finder_survives_transport_429(fenv, monkeypatch):
    """Telegram's transport-level «429 Too Many Requests» backs off, then parks that request kind
    instead of failing the whole run."""
    from app.tools.channel_finder import finder
    monkeypatch.setattr(finder, "TRANSPORT_BACKOFF", (0, 0))
    await index(fenv)
    fenv.client.transport_429 = True
    job = await find(fenv)
    assert job.status == "done", job.error
    r = job.result
    assert set(r["blocked"]) == {"invite"} and r["deferred"] == 1 and not r["failures"]
    assert len([c for c in fenv.client.calls if c.startswith("invite:")]) == 3  # first try + 2 retries
    assert "details:501" in fenv.client.calls  # later phases still ran
