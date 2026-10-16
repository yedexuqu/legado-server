import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CategoryRepository:
    """Book category operations."""

    def __init__(self, db):
        self.db = db

    async def get_all(self) -> List[Dict]:
        cursor = await self.db.execute(
            """SELECT c.name, COUNT(b.id) as count
               FROM categories c
               LEFT JOIN books b ON b.category = c.name
               GROUP BY c.name ORDER BY count DESC"""
        )
        rows = await cursor.fetchall()
        return [{"name": row[0], "count": row[1]} for row in rows]

    async def create(self, name: str) -> bool:
        try:
            await self.db.execute(
                "INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,)
            )
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Create category error: {e}")
            return False

    async def delete(self, name: str) -> bool:
        try:
            await self.db.execute("DELETE FROM categories WHERE name = ?", (name,))
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Delete category error: {e}")
            return False

    async def exists(self, name: str) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM categories WHERE name = ?", (name,)
        )
        return await cursor.fetchone() is not None

    async def get_books(self, category: str, page: int = 1, per_page: int = 50) -> List[Dict]:
        offset = (page - 1) * per_page
        cursor = await self.db.execute(
            "SELECT * FROM books WHERE category = ? ORDER BY title LIMIT ? OFFSET ?",
            (category, per_page, offset)
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_count(self, category: str) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM books WHERE category = ?", (category,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def update_book(self, book_id: int, category: str) -> bool:
        await self.db.execute(
            "UPDATE books SET category = ? WHERE id = ?", (category, book_id)
        )
        await self.db.commit()
        return True

    async def batch_update(self, old_category: str, new_category: str) -> int:
        cursor = await self.db.execute(
            "UPDATE books SET category = ? WHERE category = ?",
            (new_category, old_category)
        )
        await self.db.commit()
        return cursor.rowcount

    async def backfill(self, dir_path: str, category: str) -> int:
        cursor = await self.db.execute(
            "UPDATE books SET category = ? WHERE file_path LIKE ? AND (category = ? OR category IS NULL)",
            (category, dir_path + "%", "默认")
        )
        await self.db.commit()
        return cursor.rowcount
