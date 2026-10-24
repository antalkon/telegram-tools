from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(get_settings().db_url, connect_args={"timeout": 30})


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
    # SQLite's lower() only folds ASCII; search needs Cyrillic & co.
    dbapi_conn.run_async(
        lambda c: c.create_function("ulower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)
    )


SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# Columns added after the first release: (table, column, DDL type). create_all() never alters
# existing tables, so these are added in place on startup.
_ADDED_COLUMNS = [
    ("jobs", "source_id", "BIGINT"),
    ("comments", "reply_to", "INTEGER"),
    ("peer_notes", "ignored", "BOOLEAN NOT NULL DEFAULT 0"),
    ("job_participants", "member", "BOOLEAN NOT NULL DEFAULT 0"),
    ("job_participants", "role", "VARCHAR(16)"),
    ("monitors", "tool", "VARCHAR(64) NOT NULL DEFAULT 'comment-collector'"),
    ("monitors", "options", "JSON NOT NULL DEFAULT '{}'"),
    ("tg_peers", "about", "TEXT"),
    ("tg_peers", "personal_channel_id", "BIGINT"),
    ("tg_peers", "profile_checked_at", "DATETIME"),
    ("tg_peers", "bio_phones", "JSON NOT NULL DEFAULT '[]'"),
    ("tg_peers", "tg_created_at", "DATETIME"),
    ("comments", "fwd_from", "BIGINT"),
]

# Full-text index over message/comment texts (external content: the text lives in `comments`).
# unicode61 folds case for Cyrillic too; triggers keep it in sync, cascaded deletes included.
_FTS = [
    "CREATE VIRTUAL TABLE comments_fts USING fts5(text, content='comments', content_rowid='rowid', "
    "tokenize='unicode61 remove_diacritics 2')",
    "CREATE TRIGGER comments_fts_ai AFTER INSERT ON comments BEGIN "
    "INSERT INTO comments_fts(rowid, text) VALUES (new.rowid, new.text); END",
    "CREATE TRIGGER comments_fts_ad AFTER DELETE ON comments BEGIN "
    "INSERT INTO comments_fts(comments_fts, rowid, text) VALUES ('delete', old.rowid, old.text); END",
    "CREATE TRIGGER comments_fts_au AFTER UPDATE OF text ON comments BEGIN "
    "INSERT INTO comments_fts(comments_fts, rowid, text) VALUES ('delete', old.rowid, old.text); "
    "INSERT INTO comments_fts(rowid, text) VALUES (new.rowid, new.text); END",
]


# Search over hand-entered profile details and attached PDFs. Rows are written by app.insights.dossier
# (one 'meta' row per person, one row per file), so it keeps its own content.
_DOSSIER_FTS = ("CREATE VIRTUAL TABLE IF NOT EXISTS dossier_fts USING fts5(body, peer_id UNINDEXED, file_id UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2')")


async def rebuild_search_index() -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO comments_fts(comments_fts) VALUES ('rebuild')")


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            cols = {r[1] for r in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).all()}
            if cols and column not in cols:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        await conn.run_sync(Base.metadata.create_all)
        # create_all() skips indexes of tables that already existed.
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_comments_job_post ON comments (job_id, post_id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_comments_job_reply ON comments (job_id, reply_to)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_comments_job_date ON comments (job_id, date)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_participants_peer ON job_participants (peer_id)")
        has_fts = (await conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name = 'comments_fts'")).first()
        if not has_fts:
            for ddl in _FTS:
                await conn.exec_driver_sql(ddl)
            await conn.exec_driver_sql("INSERT INTO comments_fts(comments_fts) VALUES ('rebuild')")
        await conn.exec_driver_sql(_DOSSIER_FTS)
        # Telegram profile phones were stored as bare digits before; now +digits
        await conn.exec_driver_sql("UPDATE tg_peers SET phone = '+' || phone WHERE phone IS NOT NULL AND phone NOT LIKE '+%'")
        # Backfill source ids for jobs finished before the column existed.
        await conn.exec_driver_sql(
            "UPDATE jobs SET source_id = COALESCE(json_extract(result, '$.channel.id'), json_extract(progress, '$.channel.id')) "
            "WHERE source_id IS NULL"
        )
