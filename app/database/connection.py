import aiosqlite
import os
import json
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class Database:
    """Core database connection and schema management."""

    def __init__(self, db_path: str = "data/books.db"):
        self.db_path = db_path
        self.db = None
        self._initialized = False

    async def init(self):
        if self._initialized:
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)

        # Optimize SQLite settings
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.execute("PRAGMA cache_size=-64000")
        await self.db.execute("PRAGMA temp_store=MEMORY")
        await self.db.execute("PRAGMA mmap_size=268435456")

        await self._create_tables()
        self._initialized = True

    @asynccontextmanager
    async def get_connection(self):
        if not self.db:
            await self.init()
        try:
            yield self.db
        except Exception:
            await self.db.rollback()
            raise

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT \'\',
                type TEXT NOT NULL DEFAULT \'txt\',
                file_path TEXT NOT NULL UNIQUE,
                file_fingerprint TEXT DEFAULT '',
                file_size INTEGER DEFAULT 0,
                encoding TEXT,
                total_chapters INTEGER DEFAULT 0,
                total_duration INTEGER,
                cover_path TEXT,
                category TEXT DEFAULT \'默认\',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                start_line INTEGER,
                start_byte INTEGER,
                end_byte INTEGER,
                source_file TEXT,
                audio_file TEXT,
                duration INTEGER,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                UNIQUE(book_id, chapter_number)
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                line_number INTEGER,
                original_text TEXT,
                new_text TEXT,
                applied BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT DEFAULT \'\',
                category TEXT DEFAULT \'general\',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS book_tags (
                book_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (book_id, tag),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
            CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);
            CREATE INDEX IF NOT EXISTS idx_books_type ON books(type);
            CREATE INDEX IF NOT EXISTS idx_chapters_book_id ON chapters(book_id);
            CREATE INDEX IF NOT EXISTS idx_book_tags_tag ON book_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_categories_name ON categories(name);
            CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
        """)

        # Migration: add category column if missing.
        # The column is checked first so a migration that has already run does
        # not produce a warning on every startup; a migration that genuinely
        # fails is now reported instead of being silently swallowed.
        try:
            cursor = await self.db.execute("PRAGMA table_info(books)")
            column_names = {row[1] for row in await cursor.fetchall()}
            if "category" not in column_names:
                await self.db.execute("ALTER TABLE books ADD COLUMN category TEXT DEFAULT \'默认\'")
                logger.info("Schema migration: added missing column books.category")
        except Exception as e:
            logger.warning(
                "Schema migration failed (ensure books.category column): %s", e, exc_info=True
            )

        # Migration: add file_fingerprint column if missing.
        # Ops-reported bug: the original DDL never declared file_fingerprint,
        # yet app/database/books.py:97 (exists_by_fingerprint) and
        # scanners/txt_scanner.py read/write it. A prod DB migrated from the old
        # schema therefore raised "no such column: file_fingerprint" during
        # background scans. Same guarded pattern as the category migration.
        try:
            cursor = await self.db.execute("PRAGMA table_info(books)")
            column_names = {row[1] for row in await cursor.fetchall()}
            if "file_fingerprint" not in column_names:
                await self.db.execute(
                    "ALTER TABLE books ADD COLUMN file_fingerprint TEXT DEFAULT ''"
                )
                logger.info("Schema migration: added missing column books.file_fingerprint")
        except Exception as e:
            logger.warning(
                "Schema migration failed (ensure books.file_fingerprint column): %s", e, exc_info=True
            )

        # Migrate existing categories from books table to categories table
        try:
            cursor = await self.db.execute(
                "SELECT DISTINCT category FROM books WHERE category IS NOT NULL AND category != \'\'"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await self.db.execute(
                    "INSERT OR IGNORE INTO categories (name) VALUES (?)", (row[0],)
                )
            await self.db.commit()
        except Exception as e:
            logger.warning(
                "Schema migration failed (backfill categories from books.category): %s",
                e, exc_info=True,
            )

        # Create FTS5 tables
        try:
            await self.db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
                    title, author,
                    content=\'books\',
                    content_rowid=\'id\'
                )
            """)

            await self.db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chapters_fts USING fts5(
                    title,
                    content=\'chapters\',
                    content_rowid=\'id\'
                )
            """)

            # Create triggers for FTS sync
            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
                    INSERT INTO books_fts(rowid, title, author) VALUES (new.id, new.title, new.author);
                END
            """)

            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
                    INSERT INTO books_fts(books_fts, rowid, title, author) VALUES(\'delete\', old.id, old.title, old.author);
                END
            """)

            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
                    INSERT INTO books_fts(books_fts, rowid, title, author) VALUES(\'delete\', old.id, old.title, old.author);
                    INSERT INTO books_fts(rowid, title, author) VALUES (new.id, new.title, new.author);
                END
            """)

            # chapters_fts has exactly the same external-content layout as
            # books_fts (content=\'chapters\', content_rowid=\'id\') but indexes a
            # single column: title. It previously had NO triggers at all, so the
            # index never received inserts/updates/deletes. The three triggers
            # below mirror books_ai / books_ad / books_au one-for-one.
            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS chapters_ai AFTER INSERT ON chapters BEGIN
                    INSERT INTO chapters_fts(rowid, title) VALUES (new.id, new.title);
                END
            """)

            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS chapters_ad AFTER DELETE ON chapters BEGIN
                    INSERT INTO chapters_fts(chapters_fts, rowid, title) VALUES(\'delete\', old.id, old.title);
                END
            """)

            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS chapters_au AFTER UPDATE ON chapters BEGIN
                    INSERT INTO chapters_fts(chapters_fts, rowid, title) VALUES(\'delete\', old.id, old.title);
                    INSERT INTO chapters_fts(rowid, title) VALUES (new.id, new.title);
                END
            """)
        except Exception as e:
            logger.warning(f"FTS5 creation warning: {e}", exc_info=True)

        # Free-text search is only as good as the index. The triggers above
        # cover everything written from now on; rows that already existed (or
        # were written while the index was out of sync) still need indexing.
        #
        # IMPORTANT: for an external-content FTS5 table a plain
        # "SELECT ... FROM chapters_fts" reads the *content* table (chapters),
        # NOT the index. Measured on the live data: chapters=13, plain
        # chapters_fts count=13, but chapters_fts_docsize=0 and every MATCH
        # returned 0 rows -- the index was in fact empty. So the usual
        # "WHERE id NOT IN (SELECT rowid FROM chapters_fts)" guard matches
        # nothing and would insert 0 rows forever (verified). The authoritative
        # list of indexed documents is the %_docsize shadow table, which holds
        # one row per indexed rowid; that is what we filter against.
        #
        # Idempotency: already-indexed rowids are excluded by the NOT IN guard,
        # so a second run inserts 0 rows and the index is never duplicated.
        async def _scalar_int(sql: str) -> int:
            cursor = await self.db.execute(sql)
            row = await cursor.fetchone()
            return row[0] if row else 0

        try:
            has_docsize = bool(await _scalar_int(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chapters_fts_docsize'"
            ))
            if has_docsize:
                missing_rows = await _scalar_int(
                    """SELECT COUNT(*) FROM chapters c
                       WHERE c.id NOT IN (SELECT rowid FROM chapters_fts_docsize)"""
                )
                orphaned_rows = await _scalar_int(
                    """SELECT COUNT(*) FROM chapters_fts_docsize d
                       WHERE d.rowid NOT IN (SELECT id FROM chapters)"""
                )
            else:
                missing_rows = orphaned_rows = 0

            if missing_rows:
                await self.db.execute("""
                    INSERT INTO chapters_fts(rowid, title)
                    SELECT c.id, c.title FROM chapters c
                    WHERE c.id NOT IN (SELECT rowid FROM chapters_fts_docsize)
                """)
                await self.db.commit()
                logger.info(
                    "FTS backfill: indexed %s missing chapter row(s) into chapters_fts",
                    missing_rows,
                )

            if orphaned_rows:
                # Index entries whose chapter row no longer exists (deleted
                # before the triggers existed). "rebuild" re-creates the index
                # from the content table, which also drops those orphans.
                await self.db.execute(
                    "INSERT INTO chapters_fts(chapters_fts) VALUES('rebuild')"
                )
                await self.db.commit()
                logger.info(
                    "FTS backfill: rebuilt chapters_fts, dropped %s orphaned index row(s)",
                    orphaned_rows,
                )
        except Exception as e:
            logger.warning("FTS backfill failed (chapters_fts): %s", e, exc_info=True)

        # books_fts has the same external-content gap, with a nastier failure
        # mode: books that existed before the FTS triggers were created were
        # never indexed (books_fts has never had a backfill). Any UPDATE that
        # touches one of those rows -- metadata refresh on re-scan, category
        # edit, the file_fingerprint migration path itself -- fires the
        # books_au trigger, whose FTS 'delete' command requires the rowid to
        # be present in the index. For a missing %_docsize entry FTS5 raises
        # SQLITE_CORRUPT ("database disk image is malformed") and the UPDATE
        # fails. Verified on a legacy-schema DB: books_fts_docsize=0, UPDATE
        # fails, backfill then UPDATE succeeds. Same NOT IN guard keeps the
        # backfill idempotent.
        try:
            has_books_docsize = bool(await _scalar_int(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='books_fts_docsize'"
            ))
            if has_books_docsize:
                missing_book_rows = await _scalar_int(
                    """SELECT COUNT(*) FROM books b
                       WHERE b.id NOT IN (SELECT rowid FROM books_fts_docsize)"""
                )
                if missing_book_rows:
                    await self.db.execute("""
                        INSERT INTO books_fts(rowid, title, author)
                        SELECT b.id, b.title, b.author FROM books b
                        WHERE b.id NOT IN (SELECT rowid FROM books_fts_docsize)
                    """)
                    await self.db.commit()
                    logger.info(
                        "FTS backfill: indexed %s missing book row(s) into books_fts",
                        missing_book_rows,
                    )
        except Exception as e:
            logger.warning("FTS backfill failed (books_fts): %s", e, exc_info=True)

        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()
            self._initialized = False
