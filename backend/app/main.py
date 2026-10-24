import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

import app.tools.channel_finder.finder  # noqa: F401  (registers the tool)
import app.tools.chat_indexer.indexer  # noqa: F401  (registers the tool)
import app.tools.comment_collector.collector  # noqa: F401  (registers the tool)
from app.api import accounts, auth, comment_collector, discovery, insights, jobs, monitoring, sources, tokens
from app.config import get_settings
from app.db import init_db
from app.jobs.runner import runner
from app.jobs.scheduler import scheduler
from app.mcp_server import http_app as mcp_http_app, mcp
from app.security import COOKIE_NAME, require_admin, verify_token
from app.telegram.manager import manager
from app.telegram.peers import avatar_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# the MCP transport logs every stateless request at INFO
for _name in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager", "mcp.server.lowlevel.server"):
    logging.getLogger(_name).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if not s.secret_key:
        raise RuntimeError("TGT_SECRET_KEY is empty — set a long random string in .env")
    if s.admin_password == "admin" or s.secret_key.startswith("change-me"):
        logging.warning("Default TGT_ADMIN_PASSWORD / TGT_SECRET_KEY in use — set them in .env before exposing the panel")
    await init_db()
    await runner.recover()
    if s.scheduler_enabled:
        scheduler.start()
    async with mcp.session_manager.run():
        yield
    await scheduler.stop()
    await manager.shutdown()


VERSION = "1.1.0"
API_DESCRIPTION = """HTTP API of the TG Toolkit panel: everything the web UI does is available here.

**Authorization.** Create a token in the panel under *Настройки → API-токены* and send it as
`Authorization: Bearer tgt_…`. A *read* token may only make `GET` requests; a *full* token may do
everything except managing tokens. In the browser the panel session cookie works as well.

**MCP.** AI agents can use the same data through the MCP server at `/mcp` (Streamable HTTP) with the same token.
"""

# Docs live under /api so they work through the dev proxy too; both are behind the panel login.
app = FastAPI(title="TG Toolkit API", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

for r in (auth.router, accounts.router, jobs.router, comment_collector.router, comment_collector.jobs_router,
          comment_collector.indexer_router, insights.router, monitoring.router, sources.router, discovery.router,
          tokens.router):
    app.include_router(r, prefix="/api")

# MCP endpoint (POST/GET/DELETE /mcp); token auth happens inside.
app.router.routes.append(Route("/mcp", endpoint=mcp_http_app(), methods=["GET", "POST", "DELETE"]))


def openapi_schema() -> dict:
    if app.openapi_schema is None:
        app.openapi_schema = get_openapi(title=app.title, version=app.version, description=API_DESCRIPTION, routes=app.routes)
    return app.openapi_schema


@app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(require_admin)])
async def openapi_json():
    return openapi_schema()


SCALAR_VERSION = "1.73.1"
SCALAR_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TG Toolkit API</title>
  <link rel="icon" href="/favicon.svg">
</head>
<body>
  <div id="app"></div>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference@%s/dist/browser/standalone.js"></script>
  <script>
    Scalar.createApiReference('#app', {
      url: '/api/openapi.json',
      theme: 'default',
      darkMode: true,
      // nothing leaves the panel: no Scalar cloud tools, AI chat or telemetry
      showDeveloperTools: 'never',
      agent: { disabled: true },
      mcp: { disabled: true },
      telemetry: false,
      withDefaultFonts: false,
      authentication: { preferredSecurityScheme: 'token' },
      metaData: { title: 'TG Toolkit API' },
    })
  </script>
</body>
</html>""" % SCALAR_VERSION


@app.get("/api/docs", include_in_schema=False)
async def api_docs(request: Request):
    """Scalar API reference; needs the panel session (sends you to the login page otherwise)."""
    if not verify_token(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/login?next=/api/docs", status_code=303)
    return HTMLResponse(SCALAR_PAGE, headers={"Cache-Control": "no-store"})


@app.get("/api/media/avatars/{photo_id}.jpg", dependencies=[Depends(require_admin)])
async def avatar(photo_id: int):
    path = avatar_path(photo_id)
    if not path.exists():
        raise HTTPException(404)
    # photo_id changes whenever the photo does, so the file is immutable.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.get("/api/health")
async def health():
    return {"ok": True}


dist = get_settings().frontend_dist
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        file = dist / path
        if path and file.is_file() and dist in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(dist / "index.html")
