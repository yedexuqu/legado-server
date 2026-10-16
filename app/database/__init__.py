from .connection import Database
from .books import BookRepository
from .chapters import ChapterRepository
from .tags import TagRepository
from .categories import CategoryRepository
from .config import ConfigRepository
from .corrections import CorrectionRepository


class DatabaseManager:
    """Unified entry point for all database operations.

    Provides both new repository-style access (db.books.get(...)) and
    backward-compatible method access (db.get_book(...)) for scanners
    and other legacy code.
    """

    def __init__(self, db_path: str = "data/books.db"):
        self._db = Database(db_path)

    def _bind_repositories(self):
        """Bind repositories to the underlying connection."""
        conn = self._db.db
        self.books = BookRepository(conn)
        self.chapters = ChapterRepository(conn)
        self.tags = TagRepository(conn)
        self.categories = CategoryRepository(conn)
        self.config = ConfigRepository(conn)
        self.corrections = CorrectionRepository(conn)

    async def init(self):
        """Initialize database connection, schema, and config cache."""
        await self._db.init()
        self._bind_repositories()
        await self.config.load_cache()

    async def close(self):
        await self._db.close()

    @property
    def db(self):
        """Direct access to the underlying aiosqlite connection."""
        return self._db.db

    @property
    def get_connection(self):
        """Expose get_connection for code that uses the context manager."""
        return self._db.get_connection

    # ── Backward-compatible methods for scanners and legacy code ──

    async def get_config(self, key, default=None):
        return await self.config.get(key, default)

    async def set_config(self, key, value, description=None, category="general"):
        return await self.config.set(key, value, description, category)

    async def get_all_config(self):
        return await self.config.get_all()

    async def add_book(self, book_data):
        return await self.books.add(book_data)

    async def add_chapter(self, chapter_data):
        return await self.chapters.add(chapter_data)

    async def get_books(self, page=1, per_page=50, category=None):
        if category:
            return await self.categories.get_books(category, page, per_page)
        return await self.books.get_all(page, per_page)

    async def get_book_count(self, category=None):
        if category:
            return await self.categories.get_count(category)
        return await self.books.count()

    async def get_book(self, book_id):
        return await self.books.get(book_id)

    async def search_books(self, key, page=1, per_page=50):
        return await self.books.search(key, page, per_page)

    async def search_count(self, key):
        return await self.books.search_count(key)

    async def get_chapters(self, book_id):
        return await self.chapters.get_all(book_id)

    async def get_chapter(self, book_id, chapter_num):
        return await self.chapters.get(book_id, chapter_num)

    async def get_chapter_content(self, chapter_id):
        return await self.chapters.get_content(chapter_id)

    async def book_exists(self, file_path):
        return await self.books.exists(file_path)

    async def fingerprint_exists(self, fingerprint: str) -> bool:
        """Check if a book with the given fingerprint (filename|size) exists."""
        return await self.books.exists_by_fingerprint(fingerprint)
        return await self.books.exists(file_path)

    async def delete_book(self, book_id):
        return await self.books.delete(book_id)

    async def clear_books(self):
        return await self.books.clear()

    async def delete_books_by_dir(self, dir_path):
        return await self.books.delete_by_dir(dir_path)

    async def get_book_tags(self, book_id):
        return await self.tags.get_by_book(book_id)

    async def add_book_tag(self, book_id, tag):
        return await self.tags.add(book_id, tag)

    async def remove_book_tag(self, book_id, tag):
        return await self.tags.remove(book_id, tag)

    async def get_books_by_tag(self, tag, page=1, per_page=50):
        return await self.tags.get_books_by_tag(tag, page, per_page)

    async def get_book_tag_count(self, tag):
        return await self.tags.get_book_tag_count(tag)

    async def get_popular_tags(self, limit=20):
        return await self.tags.get_popular(limit)

    async def rename_tag(self, old_tag, new_tag):
        return await self.tags.rename(old_tag, new_tag)

    async def delete_tag(self, tag):
        return await self.tags.delete(tag)

    async def merge_tags(self, source_tag, target_tag):
        return await self.tags.merge(source_tag, target_tag)

    async def get_categories(self):
        return await self.categories.get_all()

    async def get_books_by_category(self, category, page=1, per_page=50):
        return await self.categories.get_books(category, page, per_page)

    async def get_book_count_by_category(self, category):
        return await self.categories.get_count(category)

    async def update_book_category(self, book_id, category):
        return await self.categories.update_book(book_id, category)

    async def batch_update_category(self, old_category, new_category):
        return await self.categories.batch_update(old_category, new_category)

    async def backfill_category(self, dir_path, category):
        return await self.categories.backfill(dir_path, category)
