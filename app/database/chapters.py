"""Chapter repository with optimized content reading."""

import aiosqlite
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ChapterRepository:
    """Chapters table operations with optimized content reading."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.db.row_factory = aiosqlite.Row

    async def add(self, chapter_data: Dict) -> int:
        """Insert a new chapter."""
        cursor = await self.db.execute(
            """INSERT OR IGNORE INTO chapters
               (book_id, chapter_number, title, start_line, start_byte, end_byte, source_file, audio_file, duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chapter_data["book_id"],
                chapter_data["chapter_number"],
                chapter_data["title"],
                chapter_data.get("start_line"),
                chapter_data.get("start_byte"),
                chapter_data.get("end_byte"),
                chapter_data.get("source_file"),
                chapter_data.get("audio_file"),
                chapter_data.get("duration"),
            )
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get(self, book_id: int, chapter_num: int) -> Optional[Dict]:
        """Get a single chapter by book ID and chapter number."""
        cursor = await self.db.execute(
            "SELECT * FROM chapters WHERE book_id = ? AND chapter_number = ?",
            (book_id, chapter_num)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all(self, book_id: int) -> List[Dict]:
        """Get all chapters for a book, ordered by chapter number."""
        cursor = await self.db.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_number",
            (book_id,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_content(self, chapter_id: int) -> str:
        """Read chapter content from source file with streaming to reduce memory usage."""
        cursor = await self.db.execute(
            """SELECT b.file_path, b.encoding, c.source_file,
                      c.start_line, c.chapter_number, c.book_id
               FROM chapters c JOIN books b ON c.book_id = b.id
               WHERE c.id = ?""",
            (chapter_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return ""

        book_path, encoding, source_file, start_line, chapter_number, book_id = row
        encoding = encoding or 'utf-8'

        # Use source_file if available (merged books), otherwise use book's file_path
        file_path = source_file if source_file else book_path

        # Get next chapter's start_line for boundary
        cursor2 = await self.db.execute(
            """SELECT start_line, source_file FROM chapters
               WHERE book_id = ? AND chapter_number = ?""",
            (book_id, chapter_number + 1)
        )
        next_row = await cursor2.fetchone()

        next_start_line = None
        if next_row:
            next_start_line, next_source_file = next_row
            # If next chapter is in a different file, read to end of current file
            if next_source_file and next_source_file != file_path:
                next_start_line = None

        try:
            # Stream file line by line to reduce memory usage for large files
            content_parts = []
            current_line = 0

            # Try primary encoding, fallback to alternatives on failure
            encodings_to_try = [encoding]
            if encoding not in ('utf-8', 'utf-8-sig'):
                encodings_to_try.append('utf-8')
            if encoding != 'gb18030':
                encodings_to_try.append('gb18030')

            for enc in encodings_to_try:
                try:
                    content_parts = []
                    current_line = 0
                    with open(file_path, 'r', encoding=enc, errors='replace') as f:
                        for line in f:
                            if start_line is not None:
                                if current_line >= start_line:
                                    if next_start_line is not None and current_line >= next_start_line:
                                        break
                                    content_parts.append(line)
                            else:
                                if next_start_line is not None and current_line >= next_start_line:
                                    break
                                content_parts.append(line)
                            current_line += 1
                    result = ''.join(content_parts)
                    # Check if replacement chars indicate encoding failure
                    if result.count('\ufffd') < len(result) * 0.01:
                        return result
                except (UnicodeDecodeError, UnicodeError):
                    continue

            return ''.join(content_parts) if content_parts else ''
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            return f"[文件不存在: {file_path}]"
        except PermissionError:
            logger.error(f"Permission denied: {file_path}")
            return f"[无权读取: {file_path}]"
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return f"[读取错误: {str(e)}]"

    async def get_content_range(self, chapter_id: int, max_chars: int = 5000) -> str:
        """Read first N characters of chapter content (for preview)."""
        content = await self.get_content(chapter_id)
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."
