"""Book repository with optimized queries and proper typing."""

import aiosqlite
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BookRepository:
    """Books table operations with optimized queries."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.db.row_factory = aiosqlite.Row

    async def add(self, book_data: Dict) -> int:
        """Insert a new book. Returns inserted row id (or 0 if duplicate)."""
        cursor = await self.db.execute(
            """INSERT OR IGNORE INTO books
               (title, author, type, file_path, file_size, encoding, total_chapters, cover_path, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                book_data["title"],
                book_data.get("author", ""),
                book_data["type"],
                book_data["file_path"],
                book_data.get("file_size", 0),
                book_data.get("encoding"),
                book_data.get("total_chapters", 0),
                book_data.get("cover_path"),
                book_data.get("category", "默认"),
            )
        )
        await self.db.commit()
        # INSERT OR IGNORE: on conflict rowcount is 0 and lastrowid keeps the
        # previous insert's rowid — returning it would make callers attach
        # chapters to the wrong book.
        if cursor.rowcount == 0:
            return 0
        return cursor.lastrowid

    async def get(self, book_id: int) -> Optional[Dict]:
        """Get a single book by ID."""
        cursor = await self.db.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all(self, page: int = 1, per_page: int = 50) -> List[Dict]:
        """Get all books with pagination."""
        offset = (page - 1) * per_page
        cursor = await self.db.execute(
            "SELECT * FROM books ORDER BY title LIMIT ? OFFSET ?",
            (per_page, offset)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def count(self) -> int:
        """Count total books."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM books")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def search(self, key: str, page: int = 1, per_page: int = 50) -> List[Dict]:
        """Search books by title or author."""
        offset = (page - 1) * per_page
        like_key = f"%{key}%"
        cursor = await self.db.execute(
            """SELECT * FROM books
               WHERE title LIKE ? OR author LIKE ?
               ORDER BY title
               LIMIT ? OFFSET ?""",
            (like_key, like_key, per_page, offset)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def search_count(self, key: str) -> int:
        """Count search results."""
        like_key = f"%{key}%"
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM books WHERE title LIKE ? OR author LIKE ?",
            (like_key, like_key)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def exists(self, file_path: str) -> bool:
        """Check if a book with the given file path exists."""
        cursor = await self.db.execute(
            "SELECT 1 FROM books WHERE file_path = ? LIMIT 1", (file_path,)
        )
        return await cursor.fetchone() is not None

    async def exists_by_fingerprint(self, fingerprint: str) -> bool:
        """Check if a book with the given fingerprint (filename|size) exists."""
        cursor = await self.db.execute(
            "SELECT 1 FROM books WHERE file_fingerprint = ? LIMIT 1", (fingerprint,)
        )
        return await cursor.fetchone() is not None

    async def delete(self, book_id: int) -> bool:
        """Delete a book and its chapters/tags."""
        await self.db.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        await self.db.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
        await self.db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        await self.db.commit()
        return True

    async def clear(self) -> bool:
        """Delete all books, chapters, and tags."""
        await self.db.execute("DELETE FROM chapters")
        await self.db.execute("DELETE FROM book_tags")
        await self.db.execute("DELETE FROM books")
        await self.db.commit()
        return True

    async def delete_by_dir(self, dir_path: str) -> int:
        """Delete books whose file_path starts with dir_path. Returns count deleted."""
        escaped = dir_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cursor = await self.db.execute(
            "SELECT id FROM books WHERE file_path LIKE ? ESCAPE '\\'", (escaped + "%",)
        )
        book_ids = [row[0] for row in await cursor.fetchall()]
        if not book_ids:
            return 0
        placeholders = ",".join("?" * len(book_ids))
        await self.db.execute(f"DELETE FROM chapters WHERE book_id IN ({placeholders})", book_ids)
        await self.db.execute(f"DELETE FROM book_tags WHERE book_id IN ({placeholders})", book_ids)
        await self.db.execute(f"DELETE FROM books WHERE id IN ({placeholders})", book_ids)
        await self.db.commit()
        return len(book_ids)
