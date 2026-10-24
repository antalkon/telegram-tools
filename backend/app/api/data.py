"""Whole-database export / import / wipe, and the Telegram request-pacing profile."""

import asyncio
import shutil
import zipfile
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app import backup
from app.db import SessionLocal, get_db
from app.insights import dossier
from app.jobs.runner import runner
from app.security import Principal, require_admin, require_session
from app.telegram import limits
from app.telegram.manager import manager

router = APIRouter(tags=["data"])

# one export / import / wipe at a time
_busy = asyncio.Lock()


def _need_full(p: Principal) -> None:
    if p.scope != "full":
        raise HTTPException(403, "Нужен токен с полным доступом")


async def _exclusive(what: str):
    if _busy.locked():
        raise HTTPException(409, "Уже идёт экспорт, импорт или очистка — дождитесь окончания")
    if runner.active():
        raise HTTPException(409, "Сейчас идут задачи сбора — дождитесь их окончания или остановите их")
    await _busy.acquire()
    runner.blocked = f"Идёт {what} данных — новые задачи можно будет запустить после"


def _release() -> None:
    runner.blocked = None
    _busy.release()


@router.get("/data/export", summary="Download everything as a ZIP")
async def export_data(avatars: bool = True, accounts: bool = False, principal: Principal = Depends(require_admin)):
    """All collected data, people's details and attached PDFs; avatars optional. API tokens are never included.
    `accounts=true` adds the Telegram sessions (panel session only; they open only with the same TGT_SECRET_KEY)."""
    _need_full(principal)
    if accounts and principal.kind != "session":
        raise HTTPException(403, "Сессии Telegram выгружаются только из панели")
    if _busy.locked():
        raise HTTPException(409, "Уже идёт импорт или очистка — дождитесь окончания")
    dest = backup.temp_path(".zip")
    async with _busy:
        try:
            await asyncio.to_thread(backup.export_zip, dest, avatars, accounts)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
    name = f"tg-toolkit-{datetime.now(UTC).strftime('%Y-%m-%d-%H%M')}.zip"
    return FileResponse(dest, media_type="application/zip", filename=name,
                        background=BackgroundTask(dest.unlink, missing_ok=True))


@router.post("/data/inspect", dependencies=[Depends(require_session)], summary="What an archive contains")
async def inspect_archive(file: UploadFile = File(...)):
    """Reads the manifest only, so the import dialog can show what will be imported."""
    path = await _save_upload(file)
    try:
        with zipfile.ZipFile(path) as zf:
            m = backup.read_manifest(zf)
    except zipfile.BadZipFile as e:
        raise HTTPException(422, "Файл повреждён или это не ZIP-архив") from e
    except backup.BackupError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        path.unlink(missing_ok=True)
    return {"created_at": m.get("created_at"), "tables": m.get("tables", {}), "files": m.get("files", 0),
            "avatars": m.get("avatars", 0), "includes_sessions": m.get("includes_sessions", False),
            "same_key": m.get("key_fingerprint") == backup.key_fingerprint()}


async def _save_upload(file: UploadFile):
    path = backup.temp_path(".zip")
    with open(path, "wb") as out:
        await asyncio.to_thread(shutil.copyfileobj, file.file, out, 1024 * 1024)
    return path


@router.post("/data/import", dependencies=[Depends(require_session)], summary="Import an export archive")
async def import_data(
    file: UploadFile = File(...),
    mode: Literal["replace", "merge", "overwrite"] = Form(...),
    safety_copy: bool = Form(True),
):
    """mode: `replace` — delete the current data and load the archive; `merge` — add what is missing, keep
    existing records as they are; `overwrite` — add what is missing and replace matching records with the
    archive's version. Before `replace` a copy of the database is saved to data/backups."""
    path = await _save_upload(file)
    await _exclusive("импорт")
    try:
        result = await asyncio.to_thread(backup.import_zip, path, mode, safety_copy)
    except backup.BackupError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        _release()
        path.unlink(missing_ok=True)
    await _after_change()
    return result


class WipeIn(BaseModel):
    confirm: str = Field(description='Must be "УДАЛИТЬ"')
    keep_accounts: bool = True
    keep_settings: bool = True
    safety_copy: bool = True


@router.post("/data/wipe", dependencies=[Depends(require_session)], summary="Delete all collected data")
async def wipe_data(body: WipeIn):
    if body.confirm.strip().upper() != "УДАЛИТЬ":
        raise HTTPException(422, "Для подтверждения введите УДАЛИТЬ")
    await _exclusive("очистка")
    try:
        result = await asyncio.to_thread(backup.wipe, body.keep_accounts, body.keep_settings, body.safety_copy)
    finally:
        _release()
    await _after_change()
    return result


async def _after_change() -> None:
    """Caches that mirror the database: search index of people's details, pacing profile, live clients."""
    async with SessionLocal() as db:
        await dossier.reindex(db)
        await limits.load(db)
    await manager.shutdown()  # accounts may have changed; clients reconnect on demand


# ---------- Telegram limits ----------

class LimitsIn(BaseModel):
    profile: Literal["standard", "optimized", "custom"]
    custom: dict[str, Any] | None = Field(None, description="Values for the custom profile; see `presets` for the keys")


@router.get("/settings/limits", dependencies=[Depends(require_admin)], summary="Telegram request pacing")
async def get_limits(db: AsyncSession = Depends(get_db)):
    return (await limits.load(db)).out() | {"fields": {k: {"min": lo, "max": hi} for k, (lo, hi) in limits.FIELDS.items()}}


@router.put("/settings/limits", dependencies=[Depends(require_admin)], summary="Choose the pacing profile")
async def put_limits(body: LimitsIn, db: AsyncSession = Depends(get_db)):
    lim = await limits.save(db, body.profile, body.custom)
    return lim.out() | {"fields": {k: {"min": lo, "max": hi} for k, (lo, hi) in limits.FIELDS.items()}}


@router.get("/settings/limits/stats", dependencies=[Depends(require_admin)], summary="FloodWaits lately")
async def limits_stats(hours: int = 24):
    return limits.stats(max(1, min(hours, 24 * 7)))
