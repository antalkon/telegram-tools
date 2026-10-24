"""Hand-entered profile details and attached PDFs: storage, search in the people list and the search API."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.insights import dossier, users
from app.main import app
from tests.test_insights import db  # noqa: F401  (seeded demo base)


def make_pdf(*lines: str) -> bytes:
    """Smallest valid one-page PDF with a Helvetica text layer."""
    stream = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({t}) Tj 0 -16 Td" for t in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_extract_pdf():
    pages, body = dossier.extract_pdf(make_pdf("Contract 42", "Signed by Ivanov"))
    assert pages == 1 and "Contract 42" in body and "Ivanov" in body
    assert dossier.extract_pdf(b"%PDF-1.4 broken") == (None, None)


@pytest.mark.asyncio
async def test_dossier_search_and_files(db):  # noqa: F811
    for table in ("peer_dossiers", "peer_files", "dossier_fts"):
        await db.execute(text(f"DELETE FROM {table}"))
    await db.commit()
    _, rows = await users.list_users(db, limit=2)
    pid, other = rows[0]["peer_id"], rows[1]["peer_id"]
    await dossier.set_dossier(db, pid, {"full_name": "Петров Пётр Петрович", "email": "petr.petrov@example.org",
                                        "phone": "+7 (999) 123-45-67", "country": "Россия", "city": "Казань",
                                        "address": "ул. Баумана, д. 5, кв. 12", "passport": "92 10 654321"})
    for q in ("петров", "petr.petrov@example.org", "79991234567", "9210654321", "Баумана", "казань"):
        _, found = await users.list_users(db, search=q)
        assert [r["peer_id"] for r in found] == [pid], q

    prof = await users.user_profile(db, pid)
    assert prof["dossier"]["city"] == "Казань" and prof["dossier"]["files"] == []

    # clearing a field drops it from the index, the rest stays
    await dossier.set_dossier(db, pid, {"city": ""})
    assert (await users.list_users(db, search="казань"))[0] == 0
    assert (await dossier.get_dossier(db, pid))["country"] == "Россия"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/auth/login", json={"password": "admin"})
        r = await c.post(f"/api/users/{other}/files", files=[
            ("files", ("договор аренды.pdf", make_pdf("Lease agreement", "Tenant Sidorov"), "application/pdf"))])
        assert r.status_code == 200, r.text
        f = r.json()[0]
        assert f["pages"] == 1 and f["has_text"] and f["filename"] == "договор аренды.pdf"
        bad = await c.post(f"/api/users/{other}/files", files=[("files", ("x.pdf", b"hello", "application/pdf"))])
        assert bad.status_code == 415

        got = await c.get(f"/api/users/{other}/files/{f['id']}")
        assert got.status_code == 200 and got.content.startswith(b"%PDF") and "inline" in got.headers["content-disposition"]
        assert (await c.get(f"/api/users/{pid}/files/{f['id']}")).status_code == 404  # someone else's file

        s = (await c.get("/api/search/people", params={"q": "sidorov"})).json()
        assert s["total"] == 1 and s["items"][0]["peer_id"] == other
        assert s["items"][0]["matches"][0]["filename"] == "договор аренды.pdf" and "\x02Sidorov\x03" in s["items"][0]["matches"][0]["snippet"]
        assert (await c.get("/api/search/people", params={"q": "аренды"})).json()["total"] == 1  # file name is indexed
        assert (await c.get("/api/search/people", params={"q": "79991234567"})).json()["items"][0]["peer_id"] == pid

        x = await c.get("/api/users", params={"format": "csv", "search": "петров"})
        assert "Петров Пётр Петрович" in x.text and "92 10 654321" in x.text

        await c.post("/api/maintenance/reindex-search")
        assert (await c.get("/api/search/people", params={"q": "sidorov"})).json()["total"] == 1

        assert (await c.delete(f"/api/users/{other}/files/{f['id']}")).status_code == 200
        assert not dossier.file_path(f["id"]).exists()
        assert (await c.get("/api/search/people", params={"q": "sidorov"})).json()["total"] == 0
