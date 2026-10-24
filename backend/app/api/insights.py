from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.insights import dossier, graph, graph_export, sources, users
from app.insights.common import EXCLUSION_DEFAULTS, EXCLUSIONS_KEY, cards, exclusion_opts
from app import reports
from app.jobs.runner import runner
from app.models import ChannelPost, Event, Job, Monitor, PeerDossier, PeerFile, PeerNote, Setting, SourceMember, ThreadRoot
from app.security import require_admin
from app.tools.comment_collector import export

router = APIRouter(tags=["insights"], dependencies=[Depends(require_admin)])

USER_COLUMNS = [
    ("peer_id", "ID"), ("kind", "Тип"), ("name", "Имя"), ("username", "Username"), ("link", "Ссылка"),
    ("comments", "Сообщений и комментариев"), ("sources", "Источников"), ("member", "Участник чатов"), ("posts", "Обсуждений"),
    ("first_at", "Первое сообщение"), ("last_at", "Последнее сообщение"),
    ("is_premium", "Premium"), ("is_bot", "Бот"), ("is_scam", "Scam/Fake"), ("is_deleted", "Удалён"),
    ("tags", "Метки"), ("note", "Заметка"),
    ("phone", "Телефон (Telegram)"), ("bio_phones", "Телефоны из bio"),
    ("full_name", "ФИО"), ("email", "Email"), ("contact_phone", "Телефон (вручную)"), ("country", "Страна"),
    ("city", "Город"), ("address", "Адрес"), ("passport", "Паспорт"),
]


def _ids(raw: str | None) -> list[int]:
    try:
        return [int(x) for x in raw.split(",") if x.strip()] if raw else []
    except ValueError as e:
        raise HTTPException(422, "ids: список чисел через запятую") from e


def _file(rows, fmt: str, name: str, columns) -> Response:
    for r in rows:
        for k in ("tags", "bio_phones"):
            if isinstance(r.get(k), list):
                r[k] = ", ".join(r[k])
    if fmt == "xlsx":
        body, media = export.to_xlsx(rows, columns=columns), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "json":
        body, media = export.to_json(rows, {}), "application/json"
    else:
        body, media = export.to_csv(rows, columns=columns), "text/csv; charset=utf-8"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


# ---------- overview / graph ----------

@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    return await graph.overview(db)


@router.get("/graph")
async def get_graph(
    mode: Literal["people", "sources"] = "people",
    min_sources: int = Query(2, ge=1, le=50),
    limit: int = Query(300, ge=10, le=3000),
    ids: str | None = None,
    family: Literal["all", "channel", "chat"] = "all",
    active_only: bool = False,
    format: Literal["gexf", "graphml"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """format=gexf|graphml downloads the graph for Gephi, Maltego, yEd."""
    data = await graph.audience_graph(db, mode, min_sources, limit, _ids(ids) or None, family, active_only)
    return _graph_file(data, format, f"graph-{mode}") if format else data


def _graph_file(data: dict, fmt: str, name: str) -> Response:
    return Response(graph_export.render(data, fmt, name), media_type=graph_export.MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


# ---------- sources ----------

@router.get("/sources")
async def get_sources(include_hidden: bool = False, db: AsyncSession = Depends(get_db)):
    return await sources.list_sources(db, include_hidden)


class HiddenIn(BaseModel):
    hidden: bool


@router.put("/sources/{source_id}/hidden")
async def set_source_hidden(source_id: int, body: HiddenIn, db: AsyncSession = Depends(get_db)):
    await users.set_note(db, source_id, None, None, None, ignored=body.hidden)
    return {"hidden": body.hidden}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, db: AsyncSession = Depends(get_db)):
    """Remove everything collected for a source: runs, messages, participants, members, monitors, events."""
    job_ids = (await db.execute(select(Job.id).where(Job.source_id == source_id))).scalars().all()
    if any(runner.is_active(j) for j in job_ids):
        raise HTTPException(409, "По источнику идёт сбор — сначала остановите его")
    await db.execute(delete(Job).where(Job.source_id == source_id))  # comments/participants cascade
    await db.execute(delete(ThreadRoot).where(ThreadRoot.source_id == source_id))
    await db.execute(delete(SourceMember).where(SourceMember.source_id == source_id))
    await db.execute(delete(Monitor).where(Monitor.source_id == source_id))
    await db.execute(delete(Event).where(Event.source_id == source_id))
    await db.execute(delete(PeerNote).where(PeerNote.peer_id == source_id))
    await db.execute(delete(ChannelPost).where(ChannelPost.channel_id == source_id))
    await db.commit()
    return {"deleted_jobs": len(job_ids)}


# ---------- exclusions ----------

class ExclusionsIn(BaseModel):
    hide_bots: bool | None = None
    hide_deleted: bool | None = None
    hide_channels: bool | None = None


@router.get("/settings/exclusions")
async def get_exclusions(db: AsyncSession = Depends(get_db)):
    return await exclusion_opts(db)


@router.put("/settings/exclusions")
async def put_exclusions(body: ExclusionsIn, db: AsyncSession = Depends(get_db)):
    value = await exclusion_opts(db) | {k: v for k, v in body.model_dump(exclude_none=True).items() if k in EXCLUSION_DEFAULTS}
    row = await db.get(Setting, EXCLUSIONS_KEY) or Setting(key=EXCLUSIONS_KEY)
    row.value = value
    db.add(row)
    await db.commit()
    return value


@router.get("/ignored")
async def get_ignored(db: AsyncSession = Depends(get_db)):
    """Ignored people and hidden channels, for the settings page."""
    ids = (await db.execute(select(PeerNote.peer_id).where(PeerNote.ignored.is_(True)).order_by(PeerNote.updated_at.desc()))).scalars().all()
    found = await cards(db, ids)
    return [found[i] for i in ids]


@router.get("/sources/{source_id}/analytics")
async def get_source_analytics(source_id: int, db: AsyncSession = Depends(get_db)):
    data = await sources.source_analytics(db, source_id)
    if data is None:
        raise HTTPException(404, "Источник ещё не собран")
    return data


@router.get("/overlap")
async def get_overlap(ids: str | None = None, active_only: bool = False, db: AsyncSession = Depends(get_db)):
    return await sources.overlap_matrix(db, _ids(ids) or None, active_only)


@router.get("/overlap/users")
async def get_overlap_users(
    ids: str,
    min_sources: int | None = Query(None, ge=1),
    active_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    format: Literal["csv", "xlsx", "json"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await sources.overlap_users(db, _ids(ids), min_sources, active_only)
    if format:
        return _file(rows, format, "overlap", USER_COLUMNS)
    return {"total": len(rows), "items": rows[offset:offset + limit]}


# ---------- users ----------

@router.get("/users")
async def get_users(
    search: str = "",
    sort: str = "-comments",
    min_sources: int = Query(1, ge=1),
    source_id: int | None = None,
    tag: str | None = None,
    starred: bool = False,
    kind: Literal["all", "user", "channel"] = "all",
    show_ignored: bool = False,
    presence: Literal["all", "active", "silent"] = "all",
    family: Literal["all", "channel", "chat"] = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    format: Literal["csv", "xlsx", "json"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    args = dict(search=search, sort=sort, min_sources=min_sources, source_id=source_id, tag=tag, starred=starred, kind=kind,
                show_ignored=show_ignored, presence=presence, family=family)
    if format:
        _, rows = await users.list_users(db, **args, limit=None)
        details = {d.peer_id: dossier.dossier_out(d) for d in (await db.execute(select(PeerDossier))).scalars()}
        for r in rows:
            d = details.get(r["peer_id"], {})
            r |= {k: d.get(k) for k in dossier.FIELDS if k != "phone"} | {"contact_phone": d.get("phone")}
        return _file(rows, format, "users", USER_COLUMNS)
    total, rows = await users.list_users(db, **args, offset=offset, limit=limit)
    return {"total": total, "items": rows}


@router.get("/users/{peer_id}")
async def get_user(peer_id: int, db: AsyncSession = Depends(get_db)):
    data = await users.user_profile(db, peer_id)
    if data is None:
        raise HTTPException(404, "Пользователь не найден")
    return data


@router.get("/users/{peer_id}/activity")
async def get_user_activity(peer_id: int, db: AsyncSession = Depends(get_db)):
    return await users.user_activity(db, peer_id)


@router.get("/users/{peer_id}/comments")
async def get_user_comments(peer_id: int, source_id: int | None = None, limit: int = Query(100, le=1000),
                            db: AsyncSession = Depends(get_db)):
    return await users.user_comments(db, peer_id, source_id, limit)


@router.get("/users/{peer_id}/connections")
async def get_user_connections(peer_id: int, limit: int = Query(30, le=200), db: AsyncSession = Depends(get_db)):
    return await users.connections(db, peer_id, limit)


@router.get("/users/{peer_id}/graph")
async def get_user_graph(peer_id: int, limit: int = Query(25, ge=5, le=100),
                         format: Literal["gexf", "graphml"] | None = None, db: AsyncSession = Depends(get_db)):
    data = await users.ego_graph(db, peer_id, limit)
    return _graph_file(data, format, f"user-{peer_id}") if format else data


class NoteIn(BaseModel):
    tags: list[str] | None = Field(None, max_length=20)
    note: str | None = Field(None, max_length=4000)
    starred: bool | None = None
    ignored: bool | None = None


@router.put("/users/{peer_id}/note")
async def put_user_note(peer_id: int, body: NoteIn, db: AsyncSession = Depends(get_db)):
    n = await users.set_note(db, peer_id, body.tags, body.note, body.starred, body.ignored)
    return {"tags": n.tags, "note": n.note, "starred": n.starred, "ignored": n.ignored}


# ---------- hand-entered details and attached PDFs ----------

class DossierIn(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    country: str | None = Field(None, max_length=128)
    city: str | None = Field(None, max_length=128)
    address: str | None = Field(None, max_length=255)
    passport: str | None = Field(None, max_length=64)


@router.put("/users/{peer_id}/dossier")
async def put_user_dossier(peer_id: int, body: DossierIn, db: AsyncSession = Depends(get_db)):
    """Only the fields sent are changed; an empty string clears one."""
    return await dossier.set_dossier(db, peer_id, body.model_dump(exclude_unset=True))


@router.post("/users/{peer_id}/files")
async def upload_user_files(peer_id: int, files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    out = []
    for f in files:
        data = await f.read(dossier.MAX_FILE_BYTES + 1)
        if len(data) > dossier.MAX_FILE_BYTES:
            raise HTTPException(413, f"{f.filename}: файл больше {dossier.MAX_FILE_BYTES // 1024 // 1024} МБ")
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, f"{f.filename}: это не PDF")
        out.append(await dossier.add_file(db, peer_id, f.filename or "document.pdf", data))
    return out


@router.get("/users/{peer_id}/files/{file_id}")
async def get_user_file(peer_id: int, file_id: int, download: bool = False, db: AsyncSession = Depends(get_db)):
    f = await db.get(PeerFile, file_id)
    path = dossier.file_path(file_id)
    if f is None or f.peer_id != peer_id or not path.exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, media_type="application/pdf", filename=f.filename,
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "private, no-store"})


@router.delete("/users/{peer_id}/files/{file_id}")
async def delete_user_file(peer_id: int, file_id: int, db: AsyncSession = Depends(get_db)):
    if not await dossier.delete_file(db, peer_id, file_id):
        raise HTTPException(404, "Файл не найден")
    return {"ok": True}


@router.get("/search/people")
async def search_people(q: str = Query("", max_length=300), limit: int = Query(20, ge=1, le=100),
                        db: AsyncSession = Depends(get_db)):
    """People whose hand-entered details or attached PDFs match the query."""
    return await dossier.search_people(db, q, limit)


# ---------- PDF reports ----------

def _pdf(body: bytes | None, name: str) -> Response:
    if body is None:
        raise HTTPException(404, "Нет данных для отчёта")
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


@router.get("/users/{peer_id}/report.pdf")
async def user_report_pdf(peer_id: int, db: AsyncSession = Depends(get_db)):
    """The person's profile as a PDF: Telegram data, metadata, activity, channels, contacts, history, messages."""
    return _pdf(await reports.user_report(db, peer_id), f"user-{peer_id}")


@router.get("/sources/{source_id}/report.pdf")
async def source_report_pdf(source_id: int, db: AsyncSession = Depends(get_db)):
    """A channel's or chat's analytics as a PDF: summary, activity, top people, posts, ads, contacts."""
    return _pdf(await reports.source_report(db, source_id), f"source-{source_id}")


@router.get("/tags")
async def get_tags(db: AsyncSession = Depends(get_db)):
    return await users.all_tags(db)
