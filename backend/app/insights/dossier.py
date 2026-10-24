"""Hand-entered details about a person and the PDFs attached to their profile, both full-text searchable."""

import asyncio
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.insights.common import cards, fts_query
from app.models import PeerDossier, PeerFile, iso
from app.telegram.contacts import digits_query

log = logging.getLogger(__name__)

FIELDS = ("full_name", "email", "phone", "country", "city", "address", "passport")
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000  # per file, more is almost surely garbage from a broken text layer
HL_START, HL_END = "\x02", "\x03"


def file_path(file_id: int) -> Path:
    return get_settings().files_dir / f"{file_id}.pdf"


def _digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _meta_body(d: PeerDossier) -> str:
    """Searchable text of the details; phone and passport also go in as bare digits so
    "+7 (999) 123-45-67" is found by 79991234567 and "45 10 123456" by 4510123456."""
    parts = [getattr(d, f) or "" for f in FIELDS]
    parts += [_digits(d.phone), _digits(d.passport)]
    return " ".join(p for p in parts if p)


def dossier_out(d: PeerDossier | None) -> dict[str, Any]:
    return {f: getattr(d, f) if d else None for f in FIELDS} | {"updated_at": iso(d.updated_at) if d else None}


def file_out(f: PeerFile) -> dict[str, Any]:
    return {"id": f.id, "filename": f.filename, "size": f.size, "pages": f.pages,
            "has_text": bool(f.text), "created_at": iso(f.created_at)}


async def get_dossier(db: AsyncSession, peer_id: int) -> dict[str, Any]:
    d = await db.get(PeerDossier, peer_id)
    files = (await db.execute(select(PeerFile).where(PeerFile.peer_id == peer_id).order_by(PeerFile.created_at.desc()))).scalars()
    return dossier_out(d) | {"files": [file_out(f) for f in files]}


async def _index_meta(db: AsyncSession, d: PeerDossier) -> None:
    await db.execute(text("DELETE FROM dossier_fts WHERE peer_id = :p AND file_id IS NULL"), {"p": d.peer_id})
    body = _meta_body(d)
    if body:
        await db.execute(text("INSERT INTO dossier_fts(body, peer_id, file_id) VALUES (:b, :p, NULL)"), {"b": body, "p": d.peer_id})


async def _index_file(db: AsyncSession, f: PeerFile) -> None:
    # the file name is searchable too: scans have no text, but "паспорт.pdf" still tells something
    body = f"{Path(f.filename).stem}\n{f.text or ''}"
    await db.execute(text("INSERT INTO dossier_fts(body, peer_id, file_id) VALUES (:b, :p, :f)"),
                     {"b": body, "p": f.peer_id, "f": f.id})


async def set_dossier(db: AsyncSession, peer_id: int, values: dict[str, str | None]) -> dict[str, Any]:
    d = await db.get(PeerDossier, peer_id) or PeerDossier(peer_id=peer_id)
    for k, v in values.items():
        if k in FIELDS:
            setattr(d, k, (v or "").strip() or None)
    db.add(d)
    await db.flush()
    await _index_meta(db, d)
    await db.commit()
    return dossier_out(d)


def extract_pdf(data: bytes) -> tuple[int | None, str | None]:
    """(pages, text layer) of a PDF; text is None when there is none (scans) or it can't be read."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")  # many "protected" PDFs only restrict printing; real passwords fail below
        chunks, size = [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            chunks.append(t)
            size += len(t)
            if size > MAX_TEXT_CHARS:
                break
        body = re.sub(r"[ \t ]+", " ", "\n".join(chunks)).strip()[:MAX_TEXT_CHARS]
        return len(reader.pages), body or None
    except Exception as e:  # noqa: BLE001  (a broken PDF is still stored, just not searchable)
        log.warning("PDF text extraction failed: %s", e)
        return None, None


async def add_file(db: AsyncSession, peer_id: int, filename: str, data: bytes) -> dict[str, Any]:
    pages, body = await asyncio.to_thread(extract_pdf, data)
    name = Path(filename or "document.pdf").name[:255] or "document.pdf"
    f = PeerFile(peer_id=peer_id, filename=name, size=len(data), pages=pages, text=body)
    db.add(f)
    await db.flush()
    path = file_path(f.id)
    try:
        await asyncio.to_thread(path.write_bytes, data)
        await _index_file(db, f)
        await db.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return file_out(f)


async def delete_file(db: AsyncSession, peer_id: int, file_id: int) -> bool:
    f = await db.get(PeerFile, file_id)
    if f is None or f.peer_id != peer_id:
        return False
    await db.delete(f)
    await db.execute(text("DELETE FROM dossier_fts WHERE file_id = :f"), {"f": file_id})
    await db.commit()
    file_path(file_id).unlink(missing_ok=True)
    return True


async def reindex(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM dossier_fts"))
    for d in (await db.execute(select(PeerDossier))).scalars():
        await _index_meta(db, d)
    for f in (await db.execute(select(PeerFile))).scalars():
        await _index_file(db, f)
    await db.commit()


async def _phone_hits(db: AsyncSession, digits: str) -> dict[int, list[tuple[int | None, str]]]:
    """People whose Telegram profile phone or bio phones contain these digits."""
    rows = (await db.execute(text(
        "SELECT id, phone, bio_phones FROM tg_peers WHERE replace(phone, '+', '') LIKE :d OR CAST(bio_phones AS TEXT) LIKE :d LIMIT 200"),
        {"d": f"%{digits}%"})).all()
    out: dict[int, list[tuple[int | None, str]]] = {}
    for pid, phone, bio in rows:
        if phone and digits in phone:
            out.setdefault(pid, []).append((None, f"телефон в Telegram: {HL_START}{phone}{HL_END}"))
        for p in json.loads(bio) if isinstance(bio, str) else bio or []:
            if digits in p:
                out.setdefault(pid, []).append((None, f"телефон в bio: {HL_START}{p}{HL_END}"))
    return out


async def search_people(db: AsyncSession, q: str, limit: int = 20) -> dict[str, Any]:
    """People whose details, attached PDFs or Telegram phones match, best first, with a snippet per hit."""
    hits: dict[int, list[tuple[int | None, str]]] = {}
    if digits := digits_query(q):
        hits |= await _phone_hits(db, digits)
    if match := fts_query(q):
        rows = (await db.execute(text(f"""
            SELECT peer_id, file_id, snippet(dossier_fts, 0, '{HL_START}', '{HL_END}', '…', 16), bm25(dossier_fts) AS rank
            FROM dossier_fts WHERE dossier_fts MATCH :m ORDER BY rank LIMIT 500"""), {"m": match})).all()
        for peer_id, file_id, snip, _ in rows:
            hits.setdefault(peer_id, []).append((file_id, snip))
    ids = list(hits)[:limit]
    names = {f.id: f.filename for f in (await db.execute(
        select(PeerFile).where(PeerFile.id.in_([fid for i in ids for fid, _ in hits[i] if fid is not None] or [-1])))).scalars()}
    people = await cards(db, ids)
    return {
        "total": len(hits),
        "items": [people[i] | {"matches": [{"file_id": fid, "filename": names.get(fid) if fid else None, "snippet": s}
                                           for fid, s in hits[i][:3]]} for i in ids],
    }
