"""Tag repository with optimized queries and proper error handling."""

import aiosqlite
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class TagRepository:
    """Book tags operations with optimized queries."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_book(self, book_id: int) -> List[str]:
        """Get all tags for a book."""
        cursor = await self.db.execute(
            "SELECT tag FROM book_tags WHERE book_id = ? ORDER BY tag", (book_id,)
        )
        return [row[0] for row in await cursor.fetchall()]

    async def add(self, book_id: int, tag: str) -> bool:
        """Add a tag to a book. Returns True on success."""
        try:
            await self.db.execute(
                "INSERT OR IGNORE INTO book_tags (book_id, tag) VALUES (?, ?)",
                (book_id, tag)
            )
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Add tag error: book_id={book_id}, tag={tag}, error={e}")
            return False

    async def remove(self, book_id: int, tag: str) -> bool:
        """Remove a tag from a book."""
        await self.db.execute(
            "DELETE FROM book_tags WHERE book_id = ? AND tag = ?",
            (book_id, tag)
        )
        await self.db.commit()
        return True

    async def get_books_by_tag(self, tag: str, page: int = 1, per_page: int = 50) -> List[Dict]:
        """Get books with a specific tag, paginated."""
        offset = (page - 1) * per_page
        cursor = await self.db.execute(
            """SELECT b.* FROM books b
               JOIN book_tags bt ON b.id = bt.book_id
               WHERE bt.tag = ?
               ORDER BY b.title LIMIT ? OFFSET ?""",
            (tag, per_page, offset)
        )
        rows = await cursor.fetchall()
        if not rows:
            return []
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_book_tag_count(self, tag: str) -> int:
        """Count books with a specific tag."""
        cursor = await self.db.execute(
            "SELECT COUNT(DISTINCT b.id) FROM books b JOIN book_tags bt ON b.id = bt.book_id WHERE bt.tag = ?",
            (tag,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_popular(self, limit: int = 20) -> List[Dict]:
        """Get popular tags (pre-created + used), merged and limited."""
        # Get from tags table (pre-created)
        cursor = await self.db.execute("SELECT name FROM tags ORDER BY name")
        pre_created = [row[0] for row in await cursor.fetchall()]

        # Get from book_tags table (used)
        cursor = await self.db.execute(
            "SELECT tag, COUNT(*) as count FROM book_tags GROUP BY tag ORDER BY count DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        used = [{"name": row[0], "count": row[1]} for row in rows]

        # Merge: pre-created first, then used
        result = []
        seen = set()
        for name in pre_created:
            if name not in seen:
                count = next((t["count"] for t in used if t["name"] == name), 0)
                result.append({"name": name, "count": count})
                seen.add(name)
        for t in used:
            if t["name"] not in seen:
                result.append(t)
                seen.add(t["name"])

        return result[:limit]

    async def create(self, name: str) -> bool:
        """Create a new tag in the tags table."""
        try:
            await self.db.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,)
            )
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Create tag error: {e}")
            return False

    async def delete_from_tags_table(self, name: str) -> bool:
        """Delete a tag from the tags table."""
        try:
            await self.db.execute("DELETE FROM tags WHERE name = ?", (name,))
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Delete tag error: {e}")
            return False

    async def exists_in_tags_table(self, name: str) -> bool:
        """Check if a tag exists in the tags table."""
        cursor = await self.db.execute(
            "SELECT 1 FROM tags WHERE name = ? LIMIT 1", (name,)
        )
        return await cursor.fetchone() is not None

    async def rename(self, old_tag: str, new_tag: str) -> int:
        """Rename a tag in both book_tags and tags tables. Returns count of updated rows."""
        cursor = await self.db.execute(
            "UPDATE book_tags SET tag = ? WHERE tag = ?", (new_tag, old_tag)
        )
        await self.db.execute(
            "UPDATE tags SET name = ? WHERE name = ?", (new_tag, old_tag)
        )
        await self.db.commit()
        return cursor.rowcount

    async def delete(self, tag: str) -> int:
        """Delete a tag from book_tags. Returns count of deleted rows."""
        cursor = await self.db.execute(
            "DELETE FROM book_tags WHERE tag = ?", (tag,)
        )
        await self.db.commit()
        return cursor.rowcount

    async def merge(self, source_tag: str, target_tag: str) -> int:
        """Merge source_tag into target_tag. Returns count of merged entries.

        First removes target_tag from books that have source_tag (to avoid conflicts),
        then updates source_tag to target_tag.
        """
        # Get book_ids that have source_tag
        cursor = await self.db.execute(
            "SELECT book_id FROM book_tags WHERE tag = ?", (source_tag,)
        )
        book_ids = [row[0] for row in await cursor.fetchall()]

        if not book_ids:
            return 0

        # Remove target_tag from those books (avoid duplicate key)
        placeholders = ",".join("?" * len(book_ids))
        await self.db.execute(
            f"DELETE FROM book_tags WHERE tag = ? AND book_id IN ({placeholders})",
            [target_tag] + book_ids
        )

        # Rename source_tag to target_tag
        cursor = await self.db.execute(
            "UPDATE book_tags SET tag = ? WHERE tag = ?", (target_tag, source_tag)
        )

        # Remove source from tags table
        await self.db.execute("DELETE FROM tags WHERE name = ?", (source_tag,))
        await self.db.commit()
        return cursor.rowcount
