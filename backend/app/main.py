import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import app.tools.channel_finder.finder  # noqa: F401  (registers the tool)
import app.tools.chat_indexer.indexer  # noqa: F401  (registers the tool)
import app.tools.comment_collector.collector  # noqa: F401  (registers the tool)
from app.api import accounts, auth, comment_collector, discovery, insights, jobs, monitoring, sources
from app.config import get_settings
from app.db import init_db
from app.jobs.runner import runner
from app.jobs.scheduler import scheduler
from app.security import require_admin
from app.telegram.manager import manager
from app.telegram.peers import avatar_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


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
    yield
    await scheduler.stop()
    await manager.shutdown()


app = FastAPI(title="TG Toolkit", lifespan=lifespan)

for r in (auth.router, accounts.router, jobs.router, comment_collector.router, comment_collector.jobs_router,
          comment_collector.indexer_router, insights.router, monitoring.router, sources.router, discovery.router):
    app.include_router(r, prefix="/api")


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
