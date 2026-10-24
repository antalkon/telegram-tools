"""Full export of the panel's data to one ZIP, import of such a ZIP (replace everything, or merge into what
is there), and wiping the data.

The archive holds `manifest.json`, one `tables/<table>.jsonl` per table with rows exactly as SQLite stores
them, the attached PDFs (`files/<id>.pdf`) and, optionally, avatars (`avatars/<photo_id>.jpg`). Work is done
with the stdlib sqlite3 module in a worker thread: it is much faster than the ORM for millions of rows.

Merging two different installations: jobs, files, monitors… have auto-increment ids that mean different
things on each side, so they are matched by a natural key (a job by tool + creation time) and renumbered,
and the rows that point to them (comments, participants…) follow the new numbers.
"""

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.db import _FTS, Base

FORMAT = "tg-toolkit-backup"
VERSION = 1
ImportMode = Literal["replace", "merge", "overwrite"]

NEVER = {"api_tokens"}  # tokens stay on the panel that issued them
SECRET = {"accounts"}  # Telegram sessions: exported only when asked, readable only with the same TGT_SECRET_KEY
TRANSIENT_SETTINGS = ("finder_blocks:",)  # per-account FloodWait blocks: meaningless elsewhere

# Tables with auto-increment ids, and how the same row is recognised in another database.
NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "accounts": ("tg_user_id",),
    "jobs": ("tool", "created_at"),
    "monitors": ("channel", "created_at"),
    "events": ("kind", "title", "created_at"),
    "peer_files": ("peer_id", "filename", "size", "created_at"),
    "peer_history": ("peer_id", "field", "new", "changed_at"),
}
# Columns that hold such an id: (table, column) -> referenced table.
REFS: dict[tuple[str, str], str] = {
    ("jobs", "account_id"): "accounts",
    ("comments", "job_id"): "jobs",
    ("job_participants", "job_id"): "jobs",
    ("monitors", "account_id"): "accounts",
    ("monitors", "last_job_id"): "jobs",
    ("events", "job_id"): "jobs",
    ("events", "monitor_id"): "monitors",
    ("peer_access", "account_id"): "accounts",
}
FIRST = ["accounts", "jobs", "monitors", "events", "peer_files"]  # referenced tables go before the rows that point to them

_FILE = re.compile(r"^files/(\d+)\.pdf$")
_AVATAR = re.compile(r"^avatars/(\d+)\.jpg$")
_TABLE = re.compile(r"^tables/([a-z_]+)\.jsonl$")
BATCH = 1000
KEEP_BACKUPS = 3


class BackupError(Exception):
    pass


def db_path() -> Path:
    return get_settings().data_dir / "toolkit.db"


def key_fingerprint() -> str:
    """Tells whether encrypted values (sessions, bot token) from an archive can be read here."""
    return hashlib.sha256(("backup:" + get_settings().secret_key).encode()).hexdigest()[:16]


def tables() -> list[str]:
    names = [t.name for t in Base.metadata.sorted_tables if t.name not in NEVER]
    return [n for n in FIRST if n in names] + [n for n in names if n not in FIRST]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _pk(table: str) -> list[str]:
    return [c.name for c in Base.metadata.tables[table].primary_key.columns]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=60, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


# ---------- export ----------

def export_zip(dest: Path, include_avatars: bool = True, include_accounts: bool = False) -> dict[str, Any]:
    s = get_settings()
    conn = _connect()
    counts: dict[str, int] = {}
    try:
        conn.execute("BEGIN")  # one consistent snapshot across all tables
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for table in tables():
                if table in SECRET and not include_accounts:
                    continue
                cols = _columns(conn, table)
                n = 0
                with zf.open(f"tables/{table}.jsonl", "w") as raw, io.TextIOWrapper(raw, "utf-8") as out:
                    for row in conn.execute(f"SELECT {', '.join(cols)} FROM {table}"):
                        rec = dict(zip(cols, row))
                        if table == "settings" and rec["key"].startswith(TRANSIENT_SETTINGS):
                            continue
                        out.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                        n += 1
                counts[table] = n
            # who the accounts are, without their sessions: lets an import re-link jobs to the same accounts
            identities = [{"id": i, "tg_user_id": u, "username": n}
                          for i, u, n in conn.execute("SELECT id, tg_user_id, username FROM accounts")]
            conn.execute("COMMIT")
            files = 0
            for (fid,) in conn.execute("SELECT id FROM peer_files"):
                p = s.files_dir / f"{fid}.pdf"
                if p.exists():
                    zf.write(p, f"files/{fid}.pdf", compress_type=zipfile.ZIP_STORED)
                    files += 1
            avatars = 0
            if include_avatars:
                for p in s.avatars_dir.glob("*.jpg"):
                    if p.stem.isdigit():
                        zf.write(p, f"avatars/{p.name}", compress_type=zipfile.ZIP_STORED)
                        avatars += 1
            manifest = {
                "format": FORMAT, "version": VERSION, "created_at": datetime.now(UTC).isoformat(),
                "tables": counts, "files": files, "avatars": avatars, "accounts": identities,
                "includes_sessions": include_accounts, "key_fingerprint": key_fingerprint(),
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return manifest


# ---------- safety copy ----------

def snapshot() -> str:
    """Copy of the database next to it (data/backups), the last few kept. Returns the file name."""
    folder = get_settings().data_dir / "backups"
    folder.mkdir(exist_ok=True)
    name = f"toolkit-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    src, dst = _connect(), sqlite3.connect(folder / name)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(folder.glob("toolkit-*.db"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return name


# ---------- import ----------

def read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (KeyError, ValueError) as e:
        raise BackupError("Это не архив экспорта TG Toolkit: нет manifest.json") from e
    if manifest.get("format") != FORMAT:
        raise BackupError("Это не архив экспорта TG Toolkit")
    if int(manifest.get("version", 0)) > VERSION:
        raise BackupError("Архив сделан более новой версией панели — сначала обновите её")
    return manifest


def _rows(zf: zipfile.ZipFile, table: str):
    with zf.open(f"tables/{table}.jsonl") as raw:
        for line in io.TextIOWrapper(raw, "utf-8"):
            if line.strip():
                yield json.loads(line)


def _drop_fts_triggers(conn: sqlite3.Connection) -> None:
    # per-row index upkeep would dominate bulk writes; the index is rebuilt in one go afterwards
    for name in ("comments_fts_ai", "comments_fts_ad", "comments_fts_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")


def _restore_fts(conn: sqlite3.Connection) -> None:
    for ddl in _FTS[1:]:
        conn.execute(ddl)
    conn.execute("INSERT INTO comments_fts(comments_fts) VALUES ('rebuild')")


class _Importer:
    def __init__(self, conn: sqlite3.Connection, zf: zipfile.ZipFile, manifest: dict[str, Any], mode: ImportMode):
        self.conn, self.zf, self.manifest, self.mode = conn, zf, manifest, mode
        self.present = {m.group(1) for n in zf.namelist() if (m := _TABLE.match(n))}
        self.same_key = manifest.get("key_fingerprint") == key_fingerprint()
        self.maps: dict[str, dict[int, int | None]] = {}
        self.stats: dict[str, dict[str, int]] = {}
        self.warnings: list[str] = []
        self.added: dict[str, set[int]] = {}  # ids given to new rows of renumbered tables

    def importable(self) -> list[str]:
        out = [t for t in tables() if t in self.present]
        if "accounts" in out and not self.same_key:
            out.remove("accounts")
            self.warnings.append("Telegram-аккаунты пропущены: архив сделан с другим TGT_SECRET_KEY, их сессии здесь не расшифровать. "
                                 "Подключите аккаунты заново.")
        return out

    def _account_map_from_manifest(self) -> None:
        """Accounts not imported: point the archive's account ids at local accounts of the same Telegram user."""
        local = {u: i for i, u in self.conn.execute("SELECT id, tg_user_id FROM accounts") if u}
        self.maps["accounts"] = {a["id"]: local.get(a.get("tg_user_id")) for a in self.manifest.get("accounts", [])}

    def _remap(self, table: str, rec: dict[str, Any]) -> bool:
        """Rewrite ids that point to renumbered rows. False: the row points nowhere and is dropped."""
        for (t, col), parent in REFS.items():
            if t != table or rec.get(col) is None:
                continue
            m = self.maps.get(parent)
            if m is None:
                continue  # parent kept its ids
            new = m.get(rec[col])
            if new is None and not Base.metadata.tables[table].c[col].nullable:
                return False
            rec[col] = new
        if table == "jobs" and isinstance(rec.get("result"), str) and "base_job_id" in rec["result"]:
            res = json.loads(rec["result"])
            if res.get("base_job_id") in self.maps.get("jobs", {}):
                res["base_job_id"] = self.maps["jobs"][res["base_job_id"]]
                rec["result"] = json.dumps(res, ensure_ascii=False)
        return True

    def _clean(self, table: str, rec: dict[str, Any]) -> bool:
        if table == "settings":
            if rec["key"].startswith(TRANSIENT_SETTINGS):
                return False
            if rec["key"] == "notifications" and not self.same_key and rec.get("value"):
                value = json.loads(rec["value"])
                if value.get("bot_token_enc"):
                    value["bot_token_enc"] = None
                    self.warnings.append("Токен бота для уведомлений не перенесён (другой TGT_SECRET_KEY) — введите его заново.")
                rec["value"] = json.dumps(value, ensure_ascii=False)
        return True

    def run(self) -> None:
        todo = self.importable()
        if "accounts" not in todo:
            self._account_map_from_manifest()
        if self.mode == "replace":
            for table in reversed(todo):
                self.conn.execute(f"DELETE FROM {table}")
        for table in todo:
            if self.mode == "replace" or table not in NATURAL_KEYS:
                self._plain(table)
            else:
                self._keyed(table)

    def _plain(self, table: str) -> None:
        local = set(_columns(self.conn, table))
        pk = _pk(table)
        st = self.stats.setdefault(table, {"added": 0, "updated": 0, "skipped": 0})
        batch: list[dict[str, Any]] = []
        cols: list[str] | None = None

        def flush() -> None:
            if not batch:
                return
            names = ", ".join(cols)
            sql = f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' * len(cols))})"
            if self.mode == "merge":
                sql += " ON CONFLICT DO NOTHING"
            elif self.mode == "overwrite":
                rest = [c for c in cols if c not in pk]
                sql += (f" ON CONFLICT({', '.join(pk)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in rest)
                        if rest else " ON CONFLICT DO NOTHING")
            before = self.conn.total_changes
            self.conn.executemany(sql, [[r.get(c) for c in cols] for r in batch])
            changed = self.conn.total_changes - before
            if self.mode == "merge":
                st["added"] += changed
                st["skipped"] += len(batch) - changed
            else:
                st["added"] += changed  # upserts count as one change either way
            batch.clear()

        for rec in _rows(self.zf, table):
            if not self._clean(table, rec) or not self._remap(table, rec):
                st["skipped"] += 1
                continue
            rec = {k: v for k, v in rec.items() if k in local}
            if cols is None:
                cols = list(rec)
            elif list(rec) != cols:
                flush()
                cols = list(rec)
            batch.append(rec)
            if len(batch) >= BATCH:
                flush()
        flush()

    def _keyed(self, table: str) -> None:
        """Tables with auto-increment ids, in merge modes: match by natural key, renumber new rows."""
        keys = NATURAL_KEYS[table]
        local_cols = set(_columns(self.conn, table))
        existing = {tuple(r[1:]): r[0] for r in self.conn.execute(f"SELECT id, {', '.join(keys)} FROM {table}")}
        next_id = (self.conn.execute(f"SELECT coalesce(max(id), 0) FROM {table}").fetchone()[0] or 0) + 1
        m = self.maps.setdefault(table, {})
        st = self.stats.setdefault(table, {"added": 0, "updated": 0, "skipped": 0})
        for rec in _rows(self.zf, table):
            old_id = rec["id"]
            if not self._clean(table, rec) or not self._remap(table, rec):
                st["skipped"] += 1
                m[old_id] = None
                continue
            rec = {k: v for k, v in rec.items() if k in local_cols}
            nat = tuple(rec.get(k) for k in keys)
            local_id = existing.get(nat) if all(v is not None for v in nat) else None
            if local_id is not None:
                m[old_id] = local_id
                if self.mode == "overwrite":
                    rest = [c for c in rec if c != "id"]
                    self.conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in rest)} WHERE id = ?",
                                      [rec[c] for c in rest] + [local_id])
                    st["updated"] += 1
                else:
                    st["skipped"] += 1
                continue
            rec["id"] = next_id
            m[old_id] = next_id
            self.added.setdefault(table, set()).add(next_id)
            existing[nat] = next_id
            next_id += 1
            self.conn.execute(f"INSERT INTO {table} ({', '.join(rec)}) VALUES ({', '.join('?' * len(rec))})", list(rec.values()))
            st["added"] += 1

    def copy_files(self) -> dict[str, int]:
        s = get_settings()
        out = {"files": 0, "avatars": 0}
        fmap = self.maps.get("peer_files")  # None: ids were kept as they are (replace mode)
        if self.mode == "replace" and "peer_files" in self.present:
            for p in s.files_dir.glob("*.pdf"):
                p.unlink(missing_ok=True)
        for name in self.zf.namelist():
            if m := _FILE.match(name):
                fid = int(m.group(1))
                new = fid if fmap is None else fmap.get(fid)
                if new is None or (fmap is not None and new not in self.added.get("peer_files", set())
                                   and self.mode != "overwrite"):
                    continue  # the row was dropped, or an existing file is kept
                dest = s.files_dir / f"{new}.pdf"
            elif m := _AVATAR.match(name):
                dest = s.avatars_dir / f"{m.group(1)}.jpg"
                if dest.exists():  # photo ids are immutable: same id, same picture
                    continue
            else:
                continue
            with self.zf.open(name) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out["files" if name.startswith("files/") else "avatars"] += 1
        return out


def import_zip(archive: Path, mode: ImportMode, safety_copy: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as e:
        raise BackupError("Файл повреждён или это не ZIP-архив") from e
    with zf:
        manifest = read_manifest(zf)
        backup = snapshot() if safety_copy and mode == "replace" else None
        conn = _connect()
        imp = _Importer(conn, zf, manifest, mode)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")  # ids are remapped by hand; checked below
            conn.execute("BEGIN IMMEDIATE")
            _drop_fts_triggers(conn)
            imp.run()
            orphans = _drop_orphans(conn)
            _restore_fts(conn)
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        copied = imp.copy_files()
    return {"mode": mode, "tables": imp.stats, "warnings": imp.warnings, "orphans_removed": orphans, "backup": backup,
            "archive_created_at": manifest.get("created_at"), "seconds": round(time.monotonic() - started, 1), **copied}


def _drop_orphans(conn: sqlite3.Connection) -> int:
    """Rows whose foreign key points nowhere (e.g. a job of a skipped account is fine — that column is nullable —
    but a comment of a job that is not there is not)."""
    n = 0
    for table, rowid, parent, _fk in conn.execute("PRAGMA foreign_key_check").fetchall():
        col = next((f[3] for f in conn.execute(f"PRAGMA foreign_key_list({table})") if f[2] == parent), None)
        if col and Base.metadata.tables[table].c[col].nullable:
            conn.execute(f"UPDATE {table} SET {col} = NULL WHERE rowid = ?", (rowid,))
        else:
            conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
        n += 1
    return n


# ---------- wipe ----------

def wipe(keep_accounts: bool = True, keep_settings: bool = True, safety_copy: bool = True) -> dict[str, Any]:
    """Delete the collected data (and files). Accounts and settings / API tokens stay unless asked."""
    s = get_settings()
    backup = snapshot() if safety_copy else None
    keep = set()
    if keep_accounts:
        keep |= {"accounts", "peer_access"}
    if keep_settings:
        keep |= {"settings", "api_tokens"}
    conn = _connect()
    deleted: dict[str, int] = {}
    keep_photos: set[str] = set()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        _drop_fts_triggers(conn)
        for t in reversed([t.name for t in Base.metadata.sorted_tables]):
            if t in keep:
                continue
            deleted[t] = conn.execute(f"DELETE FROM {t}").rowcount
        conn.execute("DELETE FROM dossier_fts")
        if "settings" in keep:
            conn.execute("DELETE FROM settings WHERE key LIKE 'finder_blocks:%'")
        if keep_accounts:
            keep_photos = {str(p) for (p,) in conn.execute("SELECT photo_id FROM accounts WHERE photo_id IS NOT NULL")}
        _restore_fts(conn)
        conn.execute("COMMIT")
        try:
            conn.execute("VACUUM")  # give the space back
        except sqlite3.OperationalError:
            pass
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    for p in s.files_dir.glob("*.pdf"):
        p.unlink(missing_ok=True)
    for p in s.avatars_dir.iterdir():
        if p.is_file() and p.stem not in keep_photos:
            p.unlink(missing_ok=True)
    return {"deleted": {k: v for k, v in deleted.items() if v}, "backup": backup}


def temp_path(suffix: str) -> Path:
    folder = get_settings().data_dir / "tmp"
    folder.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, dir=folder)
    os.close(fd)
    return Path(name)
