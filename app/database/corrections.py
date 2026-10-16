import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class CorrectionRepository:
    """Corrections table operations."""

    def __init__(self, db):
        self.db = db

    async def add(self, book_id: int, type: str, line_number=None, original_text=None, new_text=None) -> int:
        cursor = await self.db.execute(
            """INSERT INTO corrections
               (book_id, type, line_number, original_text, new_text)
               VALUES (?, ?, ?, ?, ?)""",
            (book_id, type, line_number, original_text, new_text)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_by_book(self, book_id: int) -> List[Dict]:
        cursor = await self.db.execute(
            "SELECT * FROM corrections WHERE book_id = ? ORDER BY created_at DESC",
            (book_id,)
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
