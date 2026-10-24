"""Full export / import / wipe, favourites, and the Telegram request pacing."""

import io
import json
import time
import zipfile

import pytest
from sqlalchemy import text
from telethon import errors
from telethon.client.users import UserMethods
from telethon.sessions import StringSession
from telethon.tl import functions

from app.insights import dossier, users
from app.jobs.runner import JobsBlocked, runner
from app.telegram import limits
from app.telegram.manager import PacedClient
from tests.test_api_access import client, login
from tests.test_dossier import make_pdf
from tests.test_insights import db  # noqa: F401  (seeded demo base)

COUNTED = ("jobs", "comments", "job_participants", "tg_peers", "peer_notes", "peer_files")


async def counts(db) -> dict[str, int]:  # noqa: F811
    return {t: (await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one() for t in COUNTED}


async def fts_ok(db) -> None:  # noqa: F811
    await db.execute(text("INSERT INTO comments_fts(comments_fts) VALUES ('integrity-check')"))
    await db.rollback()  # it is a write statement: don't hold the lock


def rewrite(archive: bytes, table: str, change) -> bytes:
    """The same archive with the rows of one table passed through `change`."""
    src, out = zipfile.ZipFile(io.BytesIO(archive)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for name in src.namelist():
            body = src.read(name)
            if name == f"tables/{table}.jsonl":
                rows = [change(json.loads(line)) for line in body.decode().splitlines() if line]
                body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
            dst.writestr(name, body)
    return out.getvalue()


async def upload(c, archive: bytes, mode: str):
    return await c.post("/api/data/import", files={"file": ("backup.zip", archive, "application/zip")},
                        data={"mode": mode, "safety_copy": "false"})


@pytest.mark.asyncio
async def test_export_wipe_import_roundtrip(db):  # noqa: F811
    await db.execute(text("DELETE FROM peer_files"))
    await db.commit()
    _, people = await users.list_users(db, limit=1)
    pid = people[0]["peer_id"]
    await dossier.add_file(db, pid, "passport.pdf", make_pdf("Passport 4510"))
    await users.set_note(db, pid, ["vip"], "note", True, None)
    before = await counts(db)

    async with client() as c:
        assert (await c.get("/api/data/export")).status_code == 401
        await login(c)
        res = await c.get("/api/data/export", params={"avatars": "false"})
        assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
        archive = res.content
        zf = zipfile.ZipFile(io.BytesIO(archive))
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["tables"]["comments"] == before["comments"] and manifest["files"] == 1
        assert "tables/api_tokens.jsonl" not in zf.namelist() and "tables/accounts.jsonl" not in zf.namelist()

        info = await c.post("/api/data/inspect", files={"file": ("b.zip", archive, "application/zip")})
        assert info.json()["same_key"] is True and info.json()["tables"]["jobs"] == before["jobs"]
        bad = await c.post("/api/data/inspect", files={"file": ("b.zip", b"not a zip", "application/zip")})
        assert bad.status_code == 422

        # wipe: needs the confirmation word
        assert (await c.post("/api/data/wipe", json={"confirm": "да"})).status_code == 422
        res = await c.post("/api/data/wipe", json={"confirm": "УДАЛИТЬ", "safety_copy": False})
        assert res.status_code == 200, res.text
        db.expire_all()
        assert all(v == 0 for v in (await counts(db)).values())
        assert not list(dossier.file_path(1).parent.glob("*.pdf"))

        # replace: everything is back, search index included
        res = await upload(c, archive, "replace")
        assert res.status_code == 200, res.text
        assert await counts(db) == before
        await fts_ok(db)
        prof = await users.user_profile(db, pid)
        assert prof["peer"]["starred"] and prof["peer"]["tags"] == ["vip"] and len(prof["dossier"]["files"]) == 1
        fid = prof["dossier"]["files"][0]["id"]
        assert dossier.file_path(fid).read_bytes()[:8] == b"%PDF-1.4"
        _, found = await users.list_users(db, search="4510")  # PDF text searchable again
        assert [r["peer_id"] for r in found] == [pid]

        # merge of the same archive: nothing new
        res = (await upload(c, archive, "merge")).json()
        assert res["tables"]["jobs"]["added"] == 0 and res["tables"]["comments"]["added"] == 0
        assert await counts(db) == before

        # merge keeps a local edit, overwrite takes the archive's version
        await db.execute(text("UPDATE tg_peers SET first_name = 'Локально' WHERE id = :p"), {"p": pid})
        await db.commit()
        await upload(c, archive, "merge")
        name = lambda: db.execute(text("SELECT first_name FROM tg_peers WHERE id = :p"), {"p": pid})  # noqa: E731
        db.expire_all()
        assert (await name()).scalar_one() == "Локально"
        await upload(c, archive, "overwrite")
        assert (await name()).scalar_one() != "Локально"

        # another installation: a job with the same id but made at another time is a different job;
        # it gets a new id and its comments follow it
        job_id, n_comments = (await db.execute(text(
            "SELECT job_id, count(*) FROM comments GROUP BY job_id ORDER BY 2 DESC LIMIT 1"))).one()
        other = rewrite(archive, "jobs", lambda r: r | {"created_at": "2001-01-01 00:00:00.000000"} if r["id"] == job_id else r)
        res = (await upload(c, other, "merge")).json()
        assert res["tables"]["jobs"]["added"] == 1 and res["tables"]["comments"]["added"] == n_comments
        new_id = (await db.execute(text("SELECT id FROM jobs WHERE created_at LIKE '2001-01-01%'"))).scalar_one()
        assert new_id != job_id
        assert (await db.execute(text("SELECT count(*) FROM comments WHERE job_id = :j"), {"j": new_id})).scalar_one() == n_comments
        await fts_ok(db)
        assert res["orphans_removed"] == 0


@pytest.mark.asyncio
async def test_import_refused_while_jobs_blocked_and_bad_archives(db):  # noqa: F811
    async with client() as c:
        await login(c)
        res = await upload(c, b"garbage", "merge")
        assert res.status_code == 422
        fake = io.BytesIO()
        with zipfile.ZipFile(fake, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"format": "tg-toolkit-backup", "version": 99}))
        res = await upload(c, fake.getvalue(), "merge")
        assert res.status_code == 422 and "новой версией" in res.json()["detail"]

    runner.blocked = "Идёт импорт данных"
    try:
        with pytest.raises(JobsBlocked):
            await runner.submit("username-check", None, {"username": "durov"})
    finally:
        runner.blocked = None


@pytest.mark.asyncio
async def test_favorites(db):  # noqa: F811
    async with client() as c:
        await login(c)
        sources = (await c.get("/api/sources")).json()
        sid = sources[0]["id"]
        assert not sources[0]["starred"]
        assert (await c.put(f"/api/favorites/{sid}", json={"starred": True})).json() == {"peer_id": sid, "starred": True}
        _, people = await users.list_users(db, limit=1)
        await c.put(f"/api/favorites/{people[0]['peer_id']}", json={"starred": True})
        await c.put("/api/favorites/-1009999", json={"starred": True})  # a channel that is not a source
        fav = (await c.get("/api/favorites")).json()
        assert [s["id"] for s in fav["sources"]] == [sid]
        assert [u["peer_id"] for u in fav["users"]] == [people[0]["peer_id"]]
        assert [ch["peer_id"] for ch in fav["channels"]] == [-1009999]
        assert next(s for s in (await c.get("/api/sources")).json() if s["id"] == sid)["starred"]
        await c.put(f"/api/favorites/{sid}", json={"starred": False})
        assert (await c.get("/api/favorites")).json()["sources"] == []


@pytest.mark.asyncio
async def test_limits_profiles_api(db):  # noqa: F811
    async with client() as c:
        await login(c)
        cur = (await c.get("/api/settings/limits")).json()
        assert cur["profile"] == "standard" and cur["heavy_interval"] == 0
        res = (await c.put("/api/settings/limits", json={"profile": "optimized"})).json()
        assert res["profile"] == "optimized" and res["heavy_interval"] == 3.0 and limits.current().job_pause == 20
        res = (await c.put("/api/settings/limits", json={"profile": "custom", "custom": {
            "heavy_interval": 999, "avatar_concurrency": 2.7, "adaptive": True, "bogus": 1}})).json()
        assert res["heavy_interval"] == 120 and res["avatar_concurrency"] == 2 and res["adaptive"] and "bogus" not in res
        # switching away and back keeps the custom values
        await c.put("/api/settings/limits", json={"profile": "standard"})
        assert (await c.put("/api/settings/limits", json={"profile": "custom"})).json()["heavy_interval"] == 120
        await c.put("/api/settings/limits", json={"profile": "standard"})
        assert (await c.get("/api/settings/limits/stats")).json()["hours"] == 24


def test_request_kinds():
    assert limits.kind_of(functions.contacts.ResolveUsernameRequest("x")) == "heavy"
    assert limits.kind_of(functions.messages.GetHistoryRequest(None, 0, None, 0, 100, 0, 0, 0)) == "history"
    assert limits.kind_of(functions.help.GetConfigRequest()) == "other"


@pytest.mark.asyncio
async def test_pacer_spaces_requests():
    lim = limits.Limits("custom", limits.clean({"request_interval": 0.02, "heavy_interval": 0.15}))
    p = limits.Pacer()
    t0 = time.monotonic()
    for _ in range(3):
        await p.wait("heavy", lim)
    assert time.monotonic() - t0 >= 0.29  # two gaps of 0.15 s
    t0 = time.monotonic()
    await p.wait("history", lim)  # other kinds only keep the general gap
    assert time.monotonic() - t0 < 0.1
    p.flooded("heavy", 0)
    assert p.slowdown() == {"heavy": 1.0}


@pytest.mark.asyncio
async def test_paced_client_logs_and_sleeps_through_floodwaits(monkeypatch):
    calls, wait = [], [0]

    async def fake_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        calls.append(flood_sleep_threshold)
        if len(calls) == 1:
            raise errors.FloodWaitError(request=request, capture=wait[0])
        return "ok"

    monkeypatch.setattr(UserMethods, "_call", fake_call)
    client = PacedClient(StringSession(), 1, "0" * 32)
    client.account_id = 777
    req = functions.contacts.ResolveUsernameRequest("durov")
    assert await client._call(None, req) == "ok"
    assert calls == [0, 0]  # Telethon never sleeps on its own: every FloodWait passes through here
    st = limits.stats()
    assert st["by_method"][0]["method"] == "ResolveUsername"

    calls.clear()
    wait[0] = 5
    client.flood_sleep_threshold = 0  # callers that handle FloodWaits themselves get it raised
    with pytest.raises(errors.FloodWaitError):
        await client._call(None, req)
