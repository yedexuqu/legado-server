import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConfigRepository:
    """Config table operations with in-memory cache."""

    def __init__(self, db):
        self.db = db
        self._cache = {}

    async def load_cache(self):
        """Load all config into memory cache. Call after db.init()."""
        cursor = await self.db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        self._cache = {row[0]: row[1] for row in rows}
        await self._insert_defaults()

    async def _insert_defaults(self):
        """Insert default configuration values."""
        defaults = [
            ("book_dirs", json.dumps(["/books"]), "书籍目录（JSON数组）", "general"),
            ("page_size", "50", "每页显示数量", "general"),
            ("auto_scan", "true", "启动时自动扫描", "general"),
            ("book_source_url", "", "书源导出地址（留空自动检测，填反代地址如 https://books.example.com）", "general"),
            ("ai_api_base", "https://api.openai.com/v1", "AI API地址", "ai"),
            ("ai_api_key", "", "AI API密钥", "ai"),
            ("ai_model", "gpt-3.5-turbo", "AI模型", "ai"),
            ("ai_enabled_features", json.dumps([]), "AI启用功能", "ai"),
            ("txt_encoding", "auto", "TXT默认编码（auto=自动检测）", "scanner"),
            ("chapter_patterns", json.dumps([
                r"^第[一二三四五六七八九十百千万零○\d]+章",
                r"^第[一二三四五六七八九十百千万零○\d]+节",
                r"^正文第[一二三四五六七八九十百千万零○\d]+章",
                r"^第[一二三四五六七八九十百千万零○\d]+卷",
                r"^卷[一二三四五六七八九十百千万零○\d]+",
                r"^[一二三四五六七八九十]+、",
                r"^\d+[\.、]",
                r"^【.*?】",
                r"^Chapter\s+\d+",
                r"^CHAPTER\s+\d+",
                r"^Part\s+",
                r"^\s{4,}"
            ]), "章节识别正则（JSON数组）", "scanner"),
            ("min_chapter_score", "2", "章节识别最小分数", "scanner"),
            ("regex_book_name_patterns", json.dumps([
                r"《(.+?)》",
                r"^(?:书名|标题|题目)[：:]\s*(.+)",
                r"^(.+?)[-_](.+)$",
                r"^(.+?)[（(](.+?)[）)]$"
            ]), "书名识别正则（JSON数组）", "scanner"),
            ("regex_author_patterns", json.dumps([
                r"作者[：:]\s*(.+)",
                r"^(?:作者|作者名)[：:]\s*(.+)"
            ]), "作者识别正则（JSON数组）", "scanner"),
            ("theme", "light", "主题（light/dark）", "display"),
            ("books_per_row", "6", "每行显示书籍数量", "display"),
            ("show_cover", "true", "显示封面", "display"),
        ]

        for key, value, description, category in defaults:
            await self.db.execute(
                """INSERT OR IGNORE INTO config (key, value, description, category)
                   VALUES (?, ?, ?, ?)""",
                (key, value, description, category)
            )
        await self.db.commit()

    async def get(self, key: str, default: Any = None) -> Any:
        """Get config value with caching."""
        if key in self._cache:
            value = self._cache[key]
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        cursor = await self.db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            self._cache[key] = row[0]
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                return row[0]
        return default

    async def set(self, key: str, value: Any, description: str = None, category: str = "general") -> bool:
        """Set config value."""
        json_value = json.dumps(value) if isinstance(value, (list, dict)) else str(value)

        if description:
            await self.db.execute(
                """INSERT OR REPLACE INTO config (key, value, description, category, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (key, json_value, description, category)
            )
        else:
            await self.db.execute(
                """INSERT INTO config (key, value, category, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
                (key, json_value, category)
            )
        await self.db.commit()

        self._cache[key] = json_value
        return True

    async def delete(self, key: str) -> bool:
        """Delete config value."""
        await self.db.execute("DELETE FROM config WHERE key = ?", (key,))
        await self.db.commit()
        self._cache.pop(key, None)
        return True

    async def get_all(self) -> Dict[str, Dict]:
        """Get all config grouped by category."""
        cursor = await self.db.execute(
            "SELECT key, value, description, category FROM config ORDER BY category, key"
        )
        rows = await cursor.fetchall()

        result = {}
        for key, value, description, category in rows:
            if category not in result:
                result[category] = {}

            try:
                parsed_value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                parsed_value = value

            # Mask API key for security
            if key == "ai_api_key" and parsed_value:
                parsed_value = f"{parsed_value[:4]}...{parsed_value[-4:]}" if len(parsed_value) > 8 else "****"

            result[category][key] = {
                "value": parsed_value,
                "description": description
            }

        return result

    async def get_by_category(self, category: str) -> Dict:
        """Get config for a specific category."""
        all_config = await self.get_all()
        return all_config.get(category, {})
