"""Cross-source insights on seeded demo data: views must agree with each other."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.insights import graph, sources, users
from app.models import Job, JobParticipant, PeerNote, Setting
from scripts import seed_demo


@pytest_asyncio.fixture
async def db():
    await init_db()
    async with SessionLocal() as s:
        for model in (Job, PeerNote, Setting):  # isolate from other test modules
            await s.execute(delete(model))
        await s.commit()
        await seed_demo.clear(s)
        await seed_demo.seed(s)
        yield s


@pytest.mark.asyncio
async def test_sources_and_overlap_agree(db):
    srcs = await sources.list_sources(db)
    assert len(srcs) == 5 and all(s["users"] > 0 for s in srcs)
    matrix = await sources.overlap_matrix(db, None)
    for pair in matrix["pairs"][:4]:
        shared = await sources.overlap_users(db, [pair["a"], pair["b"]])
        assert len(shared) == pair["shared"]
    assert sum(r["users"] for r in matrix["users_by_source_count"]) == matrix["total_users"]


@pytest.mark.asyncio
async def test_users_list_profile_and_filters(db):
    total, rows = await users.list_users(db, min_sources=2, limit=20)
    assert total > 0 and all(r["sources"] >= 2 and len(r["source_ids"]) == r["sources"] for r in rows)
    assert [r["comments"] for r in rows] == sorted((r["comments"] for r in rows), reverse=True)

    top = rows[0]
    prof = await users.user_profile(db, top["peer_id"])
    assert prof["totals"]["comments"] == top["comments"]
    assert prof["totals"]["sources"] == top["sources"]
    assert all(1 <= s["rank"] <= s["of"] for s in prof["sources"])

    t_spam, spam = await users.list_users(db, tag="спам")
    assert t_spam == 1 and spam[0]["tags"] == ["спам"]
    spam_prof = await users.user_profile(db, spam[0]["peer_id"])
    assert spam_prof["signals"]["spam_score"] >= 40  # duplicates + links

    await users.set_note(db, top["peer_id"], ["тест", " тест ", "VIP"], "заметка", True)
    _, starred = await users.list_users(db, starred=True, search="заметка")
    assert [r["peer_id"] for r in starred] == [top["peer_id"]]
    assert {"tag": "тест", "count": 1} in await users.all_tags(db)


@pytest.mark.asyncio
async def test_graphs_are_consistent(db):
    _, rows = await users.list_users(db, min_sources=2, limit=1)
    ego = await users.ego_graph(db, rows[0]["peer_id"])
    ids = {n["id"] for n in ego["nodes"]}
    assert len(ids) == len(ego["nodes"])  # no duplicate nodes
    assert all(link["source"] in ids and link["target"] in ids for link in ego["links"])
    assert sum(1 for n in ego["nodes"] if n["type"] == "source") == rows[0]["sources"]
    assert any(link["kind"] == "reply" for link in ego["links"])

    g = await graph.audience_graph(db, "people", min_sources=2, limit=50)
    gids = {n["id"] for n in g["nodes"]}
    assert all(link["source"] in gids and link["target"] in gids for link in g["links"])
    assert g["matching_users"] == (await users.list_users(db, min_sources=2, limit=1))[0]

    sg = await graph.audience_graph(db, "sources")
    assert all(n["type"] == "source" for n in sg["nodes"]) and sg["links"]


@pytest.mark.asyncio
async def test_analytics_shapes(db):
    sid = (await sources.list_sources(db))[0]["id"]
    a = await sources.source_analytics(db, sid)
    assert len(a["heatmap"]) == 7 and all(len(row) == 24 for row in a["heatmap"])
    assert sum(map(sum, a["heatmap"])) == a["source"]["comments"]
    assert sum(d["users"] for d in a["distribution"]) == a["source"]["users"]
    assert sum(p["comments"] for p in a["timeline"]["points"]) == a["source"]["comments"]
    assert 0 < a["concentration"]["top10pct"] <= 1


@pytest.mark.asyncio
async def test_clear_keeps_real_data(db):
    db.add(Job(tool="comment-collector", status="done", source_id=-1001111, input={"channel": "t.me/real"}))
    await db.commit()
    await seed_demo.clear(db)
    left = (await db.execute(select(Job.source_id))).scalars().all()
    assert left == [-1001111]
    assert not (await db.execute(select(JobParticipant))).first()


@pytest.mark.asyncio
async def test_api_requires_auth_and_exports(db):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/users")).status_code == 401
        await c.post("/api/auth/login", json={"password": "admin"})
        r = await c.get("/api/users", params={"min_sources": 3, "limit": 5})
        assert r.status_code == 200 and r.json()["total"] >= len(r.json()["items"])
        x = await c.get("/api/users", params={"format": "csv", "tag": "спам"})
        assert x.status_code == 200 and "Метки" in x.content.decode("utf-8-sig").splitlines()[0]
        assert (await c.get("/api/sources/123/analytics")).status_code == 404
        assert (await c.get("/api/overlap", params={"ids": "a,b"})).status_code == 422


@pytest.mark.asyncio
async def test_ignore_people_everywhere(db):
    _, rows = await users.list_users(db, min_sources=2, limit=1)
    top = rows[0]["peer_id"]
    conn_before = await users.connections(db, top)
    neighbour = conn_before["co_commenters"][0]["peer_id"]
    await users.set_note(db, top, None, None, None, ignored=True)

    _, after = await users.list_users(db, min_sources=2, limit=50)
    assert top not in [r["peer_id"] for r in after]
    t_ign, ign = await users.list_users(db, show_ignored=True)
    assert t_ign == 1 and ign[0]["peer_id"] == top and ign[0]["ignored"]
    g = await graph.audience_graph(db, "people", min_sources=1, limit=3000)
    assert f"u:{top}" not in {n["id"] for n in g["nodes"]}
    ov = await graph.overview(db)
    assert top not in [u["peer_id"] for u in ov["top_users"] + ov["top_crossover"]]
    assert all(top not in [u["peer_id"] for u in a["top_users"]] for a in [await sources.source_analytics(db, s["id"]) for s in await sources.list_sources(db)])
    # the ignored person also disappears from other people's connections
    assert top not in [c["peer_id"] for c in (await users.connections(db, neighbour))["co_commenters"]]


@pytest.mark.asyncio
async def test_hide_channel_and_auto_exclusions(db):
    from app.models import Setting

    srcs = await sources.list_sources(db)
    hide = srcs[0]["id"]
    await users.set_note(db, hide, None, None, None, ignored=True)
    visible = await sources.list_sources(db)
    assert hide not in [s["id"] for s in visible] and len(visible) == 4
    everything = await sources.list_sources(db, include_hidden=True)
    assert [s["hidden"] for s in everything if s["id"] == hide] == [True]
    assert (await sources.source_analytics(db, hide))["source"]["id"] == hide  # own page still opens
    assert hide not in [s["id"] for s in (await sources.overlap_matrix(db, None))["sources"]]

    total_before, _ = await users.list_users(db)
    db.add(Setting(key="exclusions", value={"hide_bots": True, "hide_deleted": True}))
    await db.commit()
    total_after, rows = await users.list_users(db, limit=1000)
    assert total_after < total_before and not any(r["is_bot"] or r["is_deleted"] for r in rows)


@pytest.mark.asyncio
async def test_delete_source_api(db):
    from app.main import app

    sid = (await sources.list_sources(db))[0]["id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/auth/login", json={"password": "admin"})
        r = await c.delete(f"/api/sources/{sid}")
        assert r.status_code == 200 and r.json()["deleted_jobs"] == 1
        assert sid not in [s["id"] for s in (await c.get("/api/sources", params={"include_hidden": True})).json()]
        assert (await c.put("/api/settings/exclusions", json={"hide_channels": True})).json()["hide_channels"] is True


@pytest.mark.asyncio
async def test_restart_during_avatars_keeps_the_run(db):
    from app.jobs.runner import JobRunner

    job = (await db.execute(select(Job).where(Job.status == "done"))).scalars().first()
    job.status, job.result = "running", {}
    job.progress = (job.progress or {}) | {"phase": "avatars"}
    other = Job(tool="comment-collector", status="running", input={"channel": "x"}, progress={"phase": "scan"})
    db.add(other)
    await db.commit()
    await JobRunner().recover()
    await db.refresh(job)
    await db.refresh(other)
    assert job.status == "done" and job.result["unique_users"] > 0 and job.progress["avatars_interrupted"]
    assert other.status == "failed"
