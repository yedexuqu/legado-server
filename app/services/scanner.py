"""Scanner service — wraps TxtScanner + Mp3Scanner with unified instance management."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ScannerService:
    """Manages TXT and MP3 scanners as a single unit."""

    def __init__(self, db, ai_corrector):
        from ..scanners.txt_scanner import TxtScanner
        from ..scanners.mp3_scanner import Mp3Scanner
        self.txt = TxtScanner(db, ai_corrector)
        self.mp3 = Mp3Scanner(db)
        self._db = db
        self._scan_lock = False  # Prevent concurrent scans

    async def scan_all(self) -> int:
        """Scan all configured book directories.

        Returns:
            Number of directories processed
        """
        if self._scan_lock:
            logger.warning("Scan already in progress, skipping")
            return 0

        self._scan_lock = True
        scanned = 0
        totals = {"books_written": 0, "chapters_written": 0, "commits": 0}
        try:
            book_dirs = await self._db.config.get("book_dirs", ["/books"])
            for item in book_dirs:
                if isinstance(item, dict):
                    dir_path = item.get("path", "")
                    category = item.get("category", "默认")
                else:
                    dir_path = str(item).strip()
                    category = "默认"

                if dir_path and os.path.exists(dir_path):
                    try:
                        # Fresh counters per directory: TxtScanner writes each
                        # book in a single transaction, so the log below shows
                        # how much write traffic the scan actually produced.
                        self.txt.reset_stats()
                        await self.txt.scan(dir_path, category=category)
                        await self.mp3.scan(dir_path, category=category)
                        self._report_write_stats(dir_path, totals)
                        scanned += 1
                    except Exception as e:
                        logger.error(f"Scan error in {dir_path}: {e}", exc_info=True)
                elif dir_path:
                    logger.warning(f"Directory not found: {dir_path}")
        finally:
            self._scan_lock = False

        logger.info(
            "Scan completed: %s directories processed, %s book(s) / %s chapter(s) "
            "written in %s commit(s)",
            scanned, totals["books_written"], totals["chapters_written"], totals["commits"],
        )
        return scanned

    def _report_write_stats(self, dir_path: str, totals: dict) -> dict:
        """Log (and accumulate) the write counters TxtScanner kept for a scan."""
        stats = getattr(self.txt, "stats", None) or {}
        commits = stats.get("commits", 0)
        books = stats.get("books_written", 0)
        chapters = stats.get("chapters_written", 0)
        totals["books_written"] += books
        totals["chapters_written"] += chapters
        totals["commits"] += commits
        logger.info(
            "Scan writes in %s: %s book(s), %s chapter(s), %s commit(s) "
            "(books are committed atomically, so commits should equal books)",
            dir_path, books, chapters, commits,
        )
        return totals

    async def scan_dir(self, dir_path: str) -> bool:
        """Scan a single directory.

        Args:
            dir_path: Directory path to scan

        Returns:
            True if scan was successful
        """
        if not dir_path or not os.path.exists(dir_path):
            logger.warning(f"Directory not found: {dir_path}")
            return False

        totals = {"books_written": 0, "chapters_written": 0, "commits": 0}
        try:
            self.txt.reset_stats()
            await self.txt.scan(dir_path)
            await self.mp3.scan(dir_path)
            self._report_write_stats(dir_path, totals)
            return True
        except Exception as e:
            logger.error(f"Scan error in {dir_path}: {e}", exc_info=True)
            return False
