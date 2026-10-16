"""Regression tests for the missing ``books.file_fingerprint`` column.

Ops-reported bug: the original DDL never declared ``file_fingerprint`` even
though ``BookRepository.exists_by_fingerprint`` and both scanners read/write
it.  A database created by an older build therefore made every background scan
log ``sqlite3.OperationalError: no such column: file_fingerprint``.

These tests pin both repair paths:
  * a fresh database gets the column straight from the initial DDL;
  * a legacy database (pre-fix schema -- the prod situation) is upgraded by the
    idempotent ``ALTER TABLE`` migration on startup.

The legacy test also pins a second latent bug found while writing these
tests: books that predate the FTS triggers were never indexed into
``books_fts``, and any UPDATE of such a row fires the ``books_au`` trigger
whose FTS ``delete`` command requires the rowid in the index -- FTS5 answers
that with ``sqlite3.DatabaseError: database disk image is malformed``.
Startup now backfills missing book rowids into ``books_fts``, so the UPDATE
below only passes when that backfill ran.
"""
import sqlite3

import pytest

from app.database import DatabaseManager


LEGACY_BOOKS_DDL = """
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT DEFAULT '',
        type TEXT NOT NULL DEFAULT 'txt',
        file_path TEXT NOT NULL UNIQUE,
        file_size INTEGER DEFAULT 0,
        encoding TEXT,
        total_chapters INTEGER DEFAULT 0,
        total_duration INTEGER,
        cover_path TEXT,
        category TEXT DEFAULT '默认',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def _books_columns(db_path) -> set:
    """Read the books column names with an independent (sync) connection."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_fresh_database_has_file_fingerprint_column(tmp_path):
    """A brand-new database must declare the column in its initial DDL."""
    db_path = tmp_path / "fresh.db"
    dm = DatabaseManager(str(db_path))
    await dm.init()
    await dm.close()
    assert "file_fingerprint" in _books_columns(db_path)


@pytest.mark.asyncio
async def test_legacy_database_is_migrated_and_fingerprint_queries_work(tmp_path):
    """A pre-fix database must be upgraded on startup, after which fingerprint
    lookups/updates work instead of raising OperationalError."""
    db_path = tmp_path / "legacy.db"
    # Simulate the prod situation: schema created before file_fingerprint existed.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(LEGACY_BOOKS_DDL)
        conn.execute(
            "INSERT INTO books (title, file_path) VALUES (?, ?)",
            ("旧书", "/books/old.txt"),
        )
        conn.commit()
    finally:
        conn.close()
    assert "file_fingerprint" not in _books_columns(db_path)

    dm = DatabaseManager(str(db_path))
    await dm.init()
    try:
        # Migration ran: the column now exists ...
        assert "file_fingerprint" in _books_columns(db_path)
        # ... fingerprint lookups no longer raise, and dedup works end to end.
        assert await dm.books.exists_by_fingerprint("老书|123") is False
        # The startup backfill indexed the pre-existing book row into the
        # external-content FTS index; without it the UPDATE below dies with
        # "database disk image is malformed" (see module docstring).
        cursor = await dm.db.execute("SELECT COUNT(*) FROM books_fts_docsize")
        assert (await cursor.fetchone())[0] == 1
        fp = "/books/old.txt|4096"
        await dm.db.execute(
            "UPDATE books SET file_fingerprint = ? WHERE file_path = ?",
            (fp, "/books/old.txt"),
        )
        await dm.db.commit()
        assert await dm.books.exists_by_fingerprint(fp) is True
    finally:
        await dm.close()
