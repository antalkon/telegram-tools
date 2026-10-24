"""API tokens, the docs behind the login, and the MCP server over Streamable HTTP."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp_server import mcp
from tests.test_insights import db  # noqa: F401  (seeded demo base)

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def login(c: AsyncClient) -> None:
    await c.post("/api/auth/login", json={"password": "admin"})


@pytest.mark.asyncio
async def test_tokens_scopes_and_docs(db):  # noqa: F811
    async with client() as c:
        assert (await c.get("/api/settings/tokens")).status_code == 401
        assert (await c.get("/api/openapi.json")).status_code == 401
        docs = await c.get("/api/docs")
        assert docs.status_code == 303 and docs.headers["location"] == "/login?next=/api/docs"

        await login(c)
        read = (await c.post("/api/settings/tokens", json={"name": "агент", "scope": "read"})).json()
        full = (await c.post("/api/settings/tokens", json={"name": "скрипт", "scope": "full", "expires_days": 30})).json()
        assert read["token"].startswith("tgt_") and read["prefix"] == read["token"][:10] and full["expires_at"]
        listed = (await c.get("/api/settings/tokens")).json()
        assert {t["name"] for t in listed} >= {"агент", "скрипт"} and all("token" not in t for t in listed)

        assert "Scalar.createApiReference" in (await c.get("/api/docs")).text
        spec = (await c.get("/api/openapi.json")).json()
        assert {"session", "token"} <= set(spec["components"]["securitySchemes"]) and "/api/users" in spec["paths"]
        assert not any(p.startswith("/mcp") for p in spec["paths"])

    async with client() as c:  # no cookie: tokens only
        r = {"Authorization": f"Bearer {read['token']}"}
        w = {"Authorization": f"Bearer {full['token']}"}
        assert (await c.get("/api/auth/me", headers=r)).json() == {"user": "admin", "via": "token", "scope": "read"}
        assert (await c.get("/api/users", headers=r, params={"limit": 1})).status_code == 200
        pid = (await c.get("/api/users", headers=r, params={"limit": 1})).json()["items"][0]["peer_id"]
        note = {"tags": ["api"]}
        assert (await c.put(f"/api/users/{pid}/note", headers=r, json=note)).status_code == 403
        assert (await c.put(f"/api/users/{pid}/note", headers=w, json=note)).status_code == 200
        assert (await c.get("/api/users", headers={"Authorization": "Bearer tgt_wrong"})).status_code == 401
        # a token can't mint or list tokens
        assert (await c.get("/api/settings/tokens", headers=w)).status_code == 401

    async with client() as c:
        await login(c)
        assert (await c.delete(f"/api/settings/tokens/{read['id']}")).status_code == 200
        last_used = {t["id"]: t["last_used_at"] for t in (await c.get("/api/settings/tokens")).json()}
        assert last_used[full["id"]] is not None
    async with client() as c:
        assert (await c.get("/api/users", headers={"Authorization": f"Bearer {read['token']}"})).status_code == 401


async def rpc(c: AsyncClient, token: str, method: str, params: dict | None = None):
    r = await c.post("/mcp", headers=MCP_HEADERS | {"Authorization": f"Bearer {token}"},
                     json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def call(c: AsyncClient, token: str, tool: str, **args):
    res = await rpc(c, token, "tools/call", {"name": tool, "arguments": args})
    payload = res.get("structuredContent", {})
    return res["isError"], payload.get("result", payload), res["content"]


@pytest.mark.asyncio
async def test_mcp_tools(db):  # noqa: F811
    async with mcp.session_manager.run(), client() as c:
        await login(c)
        read = (await c.post("/api/settings/tokens", json={"name": "r", "scope": "read"})).json()["token"]
        full = (await c.post("/api/settings/tokens", json={"name": "f", "scope": "full"})).json()["token"]
        c.cookies.clear()

        assert (await c.post("/mcp", headers=MCP_HEADERS, json={})).status_code == 401
        init = await rpc(c, read, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                 "clientInfo": {"name": "test", "version": "1"}})
        assert init["serverInfo"]["name"] == "tg-toolkit" and "peer_id" in init["instructions"]
        names = {t["name"] for t in (await rpc(c, read, "tools/list"))["tools"]}
        assert {"search_messages", "get_user_profile", "search_people", "update_user_metadata", "rerun_source"} <= names

        err, srcs, content = await call(c, read, "list_sources")
        assert not err and len(srcs) == 5 and json.loads(content[0]["text"])  # text content for clients without structured output
        err, page, _ = await call(c, read, "list_users", limit=3, min_sources=2)
        assert not err and len(page["items"]) == 3
        pid = page["items"][0]["peer_id"]
        err, prof, _ = await call(c, read, "get_user_profile", peer_id=pid)
        assert not err and prof["peer"]["peer_id"] == pid
        err, hits, _ = await call(c, read, "search_messages", sender_id=pid, limit=2)
        assert not err and hits["total"] > 0

        err, _, content = await call(c, read, "update_user_metadata", peer_id=pid, city="Казань")
        assert err and "full-access" in content[0]["text"]
        err, saved, _ = await call(c, full, "update_user_metadata", peer_id=pid, city="Казань", full_name="Агентов Агент")
        assert not err and saved["city"] == "Казань"
        err, found, _ = await call(c, read, "search_people", query="агентов")
        assert not err and found["items"][0]["peer_id"] == pid

        err, _, content = await call(c, read, "get_user_profile", peer_id=999999999999)
        assert err and "not found" in content[0]["text"]
