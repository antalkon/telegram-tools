"""Enrichment: profile history, account age, posts via t.me/s, contacts / ИНН / ads, discovery through
forwards, mentions and similar channels, graph and PDF exports, the username check."""

import base64
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from telethon.tl import functions, types

from app.db import SessionLocal, init_db
from app.insights import graph, graph_export, orgs, posts
from app.main import app
from app.models import ChannelPost, FoundChannel, FoundChannelLink, Job, OrgLookup, PeerHistory, TgPeer, UsernameCheck
from app.telegram import age, limits
from app.telegram.contacts import ad_marking, extract_contacts, valid_inn, valid_ogrn
from app.telegram.peers import upsert_peers
from app.telegram.web_preview import channel_id_from_view, count, parse_page
from app.tools.channel_posts import posts as posts_tool
from app.tools.username_check import check as check_tool
from tests.test_finder import FinderClient, env, fenv, find  # noqa: F401
from tests.test_chats import index
from tests.test_insights import db  # noqa: F401


def view_token(channel_bare: int, post: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"c": -channel_bare, "p": post}).encode()).decode().rstrip("=")


def page(posts_html: str) -> str:
    return f"""<html><body>
    <div class="tgme_channel_info_header_title"><span>Тест Канал</span></div>
    <div class="tgme_channel_info_description">Связь: +7 999 123-45-67, ИНН 7707083893</div>
    <div class="tgme_channel_info_counter"><span class="counter_value">12.5K</span> <span class="counter_type">subscribers</span></div>
    {posts_html}</body></html>"""


def web_post(pid: int, body: str, *, fwd: str = "", views: str = "1.2K") -> str:
    return f"""<div class="tgme_widget_message" data-post="testchan/{pid}" data-view="{view_token(777, pid)}">{fwd}
      <div class="tgme_widget_message_text">{body}</div>
      <span class="tgme_widget_message_views">{views}</span>
      <a class="tgme_widget_message_date"><time datetime="2026-10-0{pid % 9 + 1}T10:00:00+00:00"></time></a></div>"""


def test_parsers():
    assert count("5.84M") == 5_840_000 and count("1.2K") == 1200 and count("980") == 980 and count("") is None
    assert channel_id_from_view(view_token(1006503122, 5)) == -1001006503122
    info, items = parse_page(page(web_post(3, 'Реклама. ООО «Ромашка», ИНН 7707083893<br/><a href="https://shop.ru/?erid=2Vtzqx1aB">купить</a>')
                                  + web_post(2, "репост", fwd='<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/other_chan/9">Другой</a>')),
                             "testchan")
    assert (info["title"], info["subscribers"], info["id"]) == ("Тест Канал", 12500, -1000000000777)
    assert items[0].text.startswith("Реклама. ООО «Ромашка»") and items[0].links == ["https://shop.ru/?erid=2Vtzqx1aB"]
    assert (items[1].fwd_name, items[1].fwd_username) == ("Другой", "other_chan")
    assert ad_marking(items[0].text, items[0].links) == {"erid": "2Vtzqx1aB", "advertiser": "ООО «Ромашка»", "inn": "7707083893"}

    c = extract_contacts("mail me a.b@c.io, https://x.org/p, ИНН 7707083893, ИНН 1234567890, UQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG")
    assert c["emails"] == ["a.b@c.io"] and c["sites"] == ["https://x.org/p"] and c["inn"] == ["7707083893"] and c["wallet_ton"]
    assert valid_inn("7707083893") and not valid_inn("1234567890") and valid_ogrn("1027700132195") and not valid_ogrn("1027700132194")

    assert age.estimate(100_000_000) == {"kind": "approx", "date": "2015-03-01"}
    assert age.estimate(7_000_000_000)["kind"] == "after" and age.estimate(1000)["kind"] == "before"
    assert age.estimate(-1001) is None


@pytest.mark.asyncio
async def test_profile_history():
    await init_db()
    async with SessionLocal() as db:
        for m in (TgPeer, PeerHistory):
            await db.execute(delete(m).where((m.id if m is TgPeer else m.peer_id) == 888))
        await upsert_peers(db, [types.User(id=888, first_name="Old", username="old_name", access_hash=1)])
        await upsert_peers(db, [types.User(id=888, first_name="New", username="new_name", access_hash=1)])
        await upsert_peers(db, [types.User(id=888, first_name="New", min=True, access_hash=1)])  # partial: no change
        await db.commit()
        rows = {(h.field, h.old, h.new) for h in (await db.execute(select(PeerHistory).where(PeerHistory.peer_id == 888))).scalars()}
        assert rows == {("first_name", "Old", "New"), ("username", "old_name", "new_name")}
        await db.execute(delete(TgPeer).where(TgPeer.id == 888))
        await db.execute(delete(PeerHistory).where(PeerHistory.peer_id == 888))
        await db.commit()


@pytest.mark.asyncio
async def test_web_posts_contacts_and_ads(db, monkeypatch):  # noqa: F811
    from app.jobs.runner import runner

    await db.execute(delete(ChannelPost))
    await db.execute(delete(OrgLookup))
    await db.commit()
    pages = {None: page(web_post(5, "Реклама. ООО «Ромашка», ИНН 7707083893 erid: 2Vtzqx1aB") + web_post(4, "пишите @partner_chan")),
             4: page(web_post(3, "старый пост", fwd='<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/other_chan/1">O</a>')),
             3: page("")}

    async def fake_fetch(_http, username, before=None):
        assert username == "testchan"
        return pages[before]

    monkeypatch.setattr(posts_tool, "fetch_page", fake_fetch)
    monkeypatch.setitem(limits.current().values, "web_page_delay", 0)
    job = await runner.submit("channel-posts", None, {"channel": "https://t.me/testchan", "via": "web", "limit": 100})
    await runner.wait(job.id)
    async with SessionLocal() as s:
        done = await s.get(Job, job.id)
    assert done.status == "done", done.error
    assert done.result["posts"] == 3 and done.result["ads"] == 1 and done.result["channel"]["id"] == -1000000000777

    listed = await posts.list_posts(db, channel="@testchan")
    assert [p["post_id"] for p in listed["items"]] == [5, 4, 3]
    assert listed["items"][0]["ad"] == {"erid": "2Vtzqx1aB", "advertiser": "ООО «Ромашка»", "inn": "7707083893"}
    assert listed["items"][2]["forwarded_from"]["username"] == "other_chan"
    assert (await posts.list_posts(db, channel=-1000000000777, ads_only=True))["total"] == 1

    async def fake_org(q):
        return [{"name": "ООО «РОМАШКА»", "short_name": "ООО «РОМАШКА»", "inn": q, "ogrn": "1027700132195"}]

    monkeypatch.setattr(orgs, "_fetch", fake_org)
    found = await orgs.lookup(db, "7707083893")
    assert found["found"] and not found["cached"] and (await orgs.lookup(db, "7707083893"))["cached"]
    with pytest.raises(orgs.OrgLookupError):
        await orgs.lookup(db, "1234567890")
    ads = await posts.ads_summary(db)
    assert ads[0]["inn"] == "7707083893" and ads[0]["org"]["short_name"] == "ООО «РОМАШКА»"

    contacts = await posts.channel_contacts(db, -1000000000777)
    assert contacts["contacts"]["phones"][0]["value"] == "+79991234567" and contacts["contacts"]["inn"][0]["count"] == 2

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/auth/login", json={"password": "admin"})
        r = await c.post("/api/tools/channel-posts/jobs", json={"channel": "@testchan", "via": "web", "limit": 5})
        assert r.status_code == 200 and r.json()["account_id"] is None  # no Telegram account needed
        await runner.wait(r.json()["id"])
        x = await c.get("/api/posts", params={"channel": "@testchan", "format": "csv"})
        assert "Ромашка" in x.text


@pytest.mark.asyncio
async def test_discovery_forwards_mentions_similar(fenv):  # noqa: F811
    similar = types.Channel(id=600, title="Похожий", photo=types.ChatPhotoEmpty(), date=datetime(2020, 1, 1, tzinfo=UTC),
                            access_hash=600, broadcast=True, username="similar_one")
    fwd = types.Channel(id=601, title="Первоисточник", photo=types.ChatPhotoEmpty(), date=datetime(2020, 1, 1, tzinfo=UTC),
                        access_hash=601, broadcast=True, username="origin_chan")

    class Client(FinderClient):
        async def __call__(self, req):
            if isinstance(req, functions.channels.GetChannelRecommendationsRequest):
                self.calls.append("similar")
                return SimpleNamespace(chats=[similar])
            if isinstance(req, functions.contacts.ResolveUsernameRequest) and req.username == "origin_chan":
                self.calls.append("resolve:origin_chan")
                return types.contacts.ResolvedPeer(peer=types.PeerChannel(601), chats=[fwd], users=[])
            return await super().__call__(req)

    client = Client()
    fenv.client.__class__ = Client
    fenv.client.calls = client.calls
    chat = await index(fenv)
    async with SessionLocal() as s:
        await s.execute(text("UPDATE comments SET fwd_from = -1000000000601 WHERE job_id = :j AND sender_id = 21"), {"j": chat.id})
        await s.execute(text("UPDATE comments SET text = 'смотрите @origin_chan' WHERE job_id = :j AND sender_id = 22"), {"j": chat.id})
        await upsert_peers(s, [fwd])
        await s.commit()
    job = await find(fenv, check_bio=False, include_senders=False)
    assert job.status == "done", job.error
    assert job.result["forwards"] == 1 and job.result["mentions"] >= 1
    async with SessionLocal() as s:
        links = set((await s.execute(select(FoundChannelLink.key, FoundChannelLink.user_id, FoundChannelLink.via))).all())
        titles = {f.key: f.title for f in (await s.execute(select(FoundChannel))).scalars()}
    assert ("-1000000000601", 21, "forward") in links and ("-1000000000601", 22, "mention") in links
    assert titles["-1000000000601"] == "Первоисточник"
    # the chat source is a group, so no "similar channels" request is made for it
    assert "similar" not in client.calls


@pytest.mark.asyncio
async def test_graph_and_pdf_exports(db):  # noqa: F811
    data = await graph.audience_graph(db, "people", 2, 50)
    gexf = ET.fromstring(graph_export.to_gexf(data))
    gml = ET.fromstring(graph_export.to_graphml(data))
    ns = {"g": "http://gexf.net/1.3", "m": "http://graphml.graphdrawing.org/xmlns"}
    assert len(gexf.findall(".//g:node", ns)) == len(data["nodes"]) and len(gml.findall(".//m:edge", ns)) == len(data["links"])

    pid = next(n["peer_id"] for n in data["nodes"] if n["type"] == "user")
    sid = next(n["peer_id"] for n in data["nodes"] if n["type"] == "source")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/auth/login", json={"password": "admin"})
        for url in (f"/api/users/{pid}/report.pdf", f"/api/sources/{sid}/report.pdf"):
            r = await c.get(url)
            assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
        g = await c.get("/api/graph", params={"format": "gexf", "min_sources": 2})
        assert g.status_code == 200 and b"<gexf" in g.content
        assert (await c.get(f"/api/users/{pid}/graph", params={"format": "graphml"})).content.startswith(b"<?xml")
        assert (await c.get("/api/users/999999999/report.pdf")).status_code == 404


@pytest.mark.asyncio
async def test_username_check(monkeypatch):
    from app.jobs.runner import runner

    await init_db()
    sites = [{"name": "Alpha", "cat": "social", "uri_check": "https://a/{account}"},
             {"name": "Beta", "cat": "coding", "uri_check": "https://b/{account}"},
             {"name": "Gamma", "cat": "tech", "uri_check": "https://c/{account}"}]

    async def fake_sites(_http):
        return sites

    async def fake_check(_http, site, username):
        return {"Alpha": True, "Beta": False, "Gamma": None}[site["name"]], site["uri_check"].replace("{account}", username)

    monkeypatch.setattr(check_tool, "load_sites", fake_sites)
    monkeypatch.setattr(check_tool, "check_site", fake_check)
    assert check_tool.verdict({"e_code": 200, "e_string": "profile", "m_code": 404, "m_string": "nope"}, 200, "<b>profile</b>") is True
    assert check_tool.verdict({"e_code": 200, "e_string": "profile", "m_code": 404, "m_string": "nope"}, 404, "") is False
    assert check_tool.verdict({"e_code": 200, "e_string": "profile", "m_code": 404, "m_string": "nope"}, 403, "blocked") is None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/auth/login", json={"password": "admin"})
        assert (await c.post("/api/tools/username-check/jobs", json={"usernames": ["bad name!"]})).status_code == 422
        job = (await c.post("/api/tools/username-check/jobs", json={"usernames": ["@Durov"]})).json()
        await runner.wait(job["id"])
        res = (await c.get("/api/usernames/durov/sites")).json()
    assert res["checked"] == 2 and res["found"] == [{"site": "Alpha", "category": "social", "url": "https://a/Durov"}]
    async with SessionLocal() as s:
        await s.execute(delete(UsernameCheck))
        await s.commit()
