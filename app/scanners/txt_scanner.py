import re
import os
import json
import logging
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import chardet

logger = logging.getLogger(__name__)

# ── Metadata hygiene ─────────────────────────────────────────────────────────
# A TXT file often contains very long "lines" (whole paragraphs up to the whole
# book when the file has no line breaks at all).  The book-name/author regexes
# are line based, so a chunk of body text could be captured and stored as the
# title/author.  Real data showed titles of 1000+ characters (13 179 max), which
# blew the home page HTML up to ~594 KB.  Everything that leaves this module as
# title/author is therefore normalised and hard-capped here.
MAX_TITLE_LENGTH = 200
MAX_AUTHOR_LENGTH = 100
MAX_CHAPTER_TITLE_LENGTH = 200
# Only this much of a single line is ever fed to the metadata regexes.
MAX_METADATA_SCAN_LINE = 500
METADATA_ELLIPSIS = "…"

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def clean_metadata_text(text, max_length: int, ellipsis: str = METADATA_ELLIPSIS) -> str:
    """Normalise a title/author/chapter-title string and cap its length.

    - removes newlines, tabs and remaining control characters
    - collapses whitespace runs (including full-width U+3000) to single spaces
    - truncates to ``max_length`` characters, appending an ellipsis when cut

    Short, already-clean values -- the normal case -- come back unchanged.
    """
    if text is None:
        return ""
    value = _CONTROL_CHARS_RE.sub("", str(text))
    value = value.replace("\u3000", " ")
    value = _WHITESPACE_RUN_RE.sub(" ", value).strip()
    if max_length and max_length > 0 and len(value) > max_length:
        head = value[: max_length - len(ellipsis)].rstrip()
        value = head + ellipsis
    return value


GENERIC_NAMES = {
    '新建 文本文档', '新建文件夹', '新建 文本文档.txt', '新建文件夹.txt',
    '新建文本文档', '新建文件夹.txt', '新建', '未命名',
    'untitled', 'new folder', 'new text document', 'txt', 'text', 'document', 'book',
}

MERGE_NUMBER_PATTERN = re.compile(
    r'^(.+?)[\s._-]*('
    r'\d+'
    r'|[一二三四五六七八九十百千万零①②③④⑤⑥⑦⑧⑨⑩]+'
    r'|[(]\d+[)]'
    r'|[-—]\d+[-—]'
    r')$'
)

CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
          '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
          '百': 100, '千': 1000, '万': 10000,
          '①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5,
          '⑥': 6, '⑦': 7, '⑧': 8, '⑨': 9, '⑩': 10,
          '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
          '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20}


def chinese_to_int(s: str) -> int:
    if not s:
        return 0
    result = 0
    current = 0
    for c in s:
        if c in CN_NUM:
            val = CN_NUM[c]
            if val >= 10:
                if current == 0:
                    current = 1
                result += current * val
                current = 0
            else:
                current = val
    result += current
    return result


def extract_sort_key(filename: str) -> Tuple[str, int]:
    name = os.path.splitext(filename)[0]
    m = MERGE_NUMBER_PATTERN.match(name)
    if m:
        base = m.group(1).strip()
        num_str = m.group(2)
        if num_str.isascii() and num_str.isdigit():
            num = int(num_str)
        else:
            num = chinese_to_int(num_str)
        base = re.sub(r'[\s._-]+$', '', base)
        return (base, num)
    m = re.match(r'^(.+?)[\s._-]*(\d+)[\s._-]*[~～-][\s._-]*(\d+)$', name)
    if m:
        base = m.group(1).strip()
        start_num = int(m.group(2))
        return (base, start_num)
    return (name, 0)


# Default patterns as module-level constants for fallback
DEFAULT_CHAPTER_PATTERNS = [
    r'^第[一二三四五六七八九十百千万零○\d]+章',
    r'^第[一二三四五六七八九十百千万零○\d]+节',
    r'^正文第[一二三四五六七八九十百千万零○\d]+章',
    r'^第[一二三四五六七八九十百千万零○\d]+卷',
    r'^卷[一二三四五六七八九十百千万零○\d]+',
    r'^[一二三四五六七八九十]+、',
    r'^\d+[\.、]',
    r'^【.*?】',
    r'^Chapter\s+\d+',
    r'^CHAPTER\s+\d+',
    r'^Part\s+',
    r'^\s{4,}',
]

DEFAULT_BOOK_NAME_PATTERNS = [
    r'《(.+?)》',
    r'^(?:书名|标题|题目)[：:]\s*(.+)',
    r'^(.+?)[-_](.+)$',
    r'^(.+?)[（(](.+?)[）)]$',
]

DEFAULT_AUTHOR_PATTERNS = [
    r'作者[：:]\s*(.+)',
    r'^(?:作者|作者名)[：:]\s*(.+)',
]


class TxtScanner:
    def __init__(self, db, ai_corrector=None):
        self.db = db
        self.ai_corrector = ai_corrector
        self._regex_config_cache = None
        # Write accounting for the current scan, consumed by ScannerService to
        # log how much write traffic a scan produced.  "commits" is the proof
        # of the batching below: one book must cost exactly one commit.
        self.stats = {"books_written": 0, "chapters_written": 0, "commits": 0}

    def reset_stats(self):
        """Reset the per-scan write counters."""
        self.stats = {"books_written": 0, "chapters_written": 0, "commits": 0}
        return self.stats

    async def _get_regex_config(self) -> Dict:
        """Load regex patterns from DB config. Cached per scan session."""
        if self._regex_config_cache is not None:
            return self._regex_config_cache
        try:
            chapter_patterns = await self.db.get_config("chapter_patterns", DEFAULT_CHAPTER_PATTERNS)
            if isinstance(chapter_patterns, str):
                chapter_patterns = json.loads(chapter_patterns)
            min_score_raw = await self.db.get_config("min_chapter_score", "2")
            try:
                min_score = int(min_score_raw)
            except (TypeError, ValueError):
                min_score = 2
            book_name_patterns = await self.db.get_config("regex_book_name_patterns", DEFAULT_BOOK_NAME_PATTERNS)
            if isinstance(book_name_patterns, str):
                book_name_patterns = json.loads(book_name_patterns)
            author_patterns = await self.db.get_config("regex_author_patterns", DEFAULT_AUTHOR_PATTERNS)
            if isinstance(author_patterns, str):
                author_patterns = json.loads(author_patterns)
            self._regex_config_cache = {
                "chapter_patterns": chapter_patterns or DEFAULT_CHAPTER_PATTERNS,
                "min_chapter_score": min_score,
                "book_name_patterns": book_name_patterns or DEFAULT_BOOK_NAME_PATTERNS,
                "author_patterns": author_patterns or DEFAULT_AUTHOR_PATTERNS,
            }
        except Exception:
            self._regex_config_cache = {
                "chapter_patterns": DEFAULT_CHAPTER_PATTERNS,
                "min_chapter_score": 2,
                "book_name_patterns": DEFAULT_BOOK_NAME_PATTERNS,
                "author_patterns": DEFAULT_AUTHOR_PATTERNS,
            }
        return self._regex_config_cache

    async def _get_ai_config(self) -> Dict:
        try:
            features = await self.db.get_config("ai_enabled_features", [])
            if isinstance(features, str):
                features = json.loads(features)
            return {
                "book_name": "extract_book_name" in features,
                "category": "extract_category" in features,
                "tags": "extract_tags" in features,
                "detect_chapters": "detect_chapters" in features,
                "fix_ocr": "fix_ocr" in features,
                "merge_duplicates": "merge_duplicates" in features,
            }
        except Exception:
            return {"book_name": False, "category": False, "tags": False,
                    "detect_chapters": False, "fix_ocr": False, "merge_duplicates": False}

    async def _read_content_sample(self, file_path: str, encoding: str = 'utf-8', max_chars: int = 500) -> str:
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                return f.read(max_chars)
        except Exception:
            return ""

    async def scan(self, dir_path: str, category: str = None):
        for root, dirs, files in os.walk(dir_path):
            txt_files = [f for f in files if f.lower().endswith('.txt')]
            if not txt_files:
                continue
            groups: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
            for f in txt_files:
                base, sort_key = extract_sort_key(f)
                groups[base].append((sort_key, f))
            for base in groups:
                groups[base].sort(key=lambda x: x[0])
            for base_name, file_list in groups.items():
                file_paths = [os.path.join(root, f) for _, f in file_list]
                if await self.db.book_exists(file_paths[0]):
                    continue
                # Dedup: skip if same filename+size already exists (different path)
                basename = os.path.basename(file_paths[0])
                fsize = os.path.getsize(file_paths[0])
                fp = f"{basename}|{fsize}"
                if await self.db.fingerprint_exists(fp):
                    print(f"Skipping duplicate: {basename} (same name+size exists)")
                    continue
                if len(file_paths) == 1:
                    await self._process_file(file_paths[0], category=category)
                else:
                    await self._process_merged_files(file_paths, base_name, category=category)

    async def _process_merged_files(self, file_paths: List[str], base_name: str, category: str = None):
        try:
            all_chapters = []
            total_size = 0
            encoding = None
            ai_config = await self._get_ai_config()
            can_ai = self.ai_corrector and self.ai_corrector.api_key
            regex_config = await self._get_regex_config()

            for fp in file_paths:
                if not os.path.exists(fp):
                    continue
                enc = self._detect_encoding(fp)
                if encoding is None:
                    encoding = enc
                file_size = os.path.getsize(fp)
                total_size += file_size

                if file_size > 10 * 1024 * 1024:
                    chapters = await self._process_large_file(fp, enc, regex_config)
                else:
                    try:
                        with open(fp, 'r', encoding=enc, errors='ignore') as f:
                            content = f.read()
                    except Exception as e:
                        print(f"Error reading {fp}: {e}")
                        continue

                    if ai_config["fix_ocr"] and can_ai:
                        try:
                            fixed = await self.ai_corrector.fix_ocr_errors(content[:1000], "")
                            if fixed and len(fixed) > 100:
                                content = fixed + content[3000:]
                        except Exception:
                            pass

                    chapters = self._detect_chapters(content, enc, regex_config)

                    if ai_config["detect_chapters"] and can_ai:
                        try:
                            sample = content[:800]
                            ai_ch = await self.ai_corrector.detect_chapters(sample)
                            if ai_ch and not ai_ch.get("error") and "chapters" in ai_ch:
                                ai_list = ai_ch["chapters"]
                                if ai_list:
                                    existing_titles = {ch["title"] for ch in chapters}
                                    for ach in ai_list:
                                        if ach.get("title") not in existing_titles:
                                            chapters.append({
                                                "title": ach["title"],
                                                "line": ach.get("line", 0),
                                                "start_byte": 0,
                                                "end_byte": None
                                            })
                                    chapters.sort(key=lambda x: x.get("line", 0))
                        except Exception:
                            pass

                offset = len(all_chapters)
                for ch in chapters:
                    ch['_source_file'] = fp
                    ch['_chapter_offset'] = offset
                all_chapters.extend(chapters)

            if not all_chapters:
                return

            encoding = encoding or 'utf-8'

            if ai_config["merge_duplicates"] and can_ai and len(all_chapters) > 1:
                try:
                    merged = await self.ai_corrector.merge_duplicates(all_chapters)
                    if merged and len(merged) > 0:
                        all_chapters = merged
                except Exception:
                    pass

            if ai_config["book_name"] and can_ai:
                try:
                    content_sample = await self._read_content_sample(file_paths[0], encoding)
                    ai_result = await self.ai_corrector.extract_book_name(base_name, content_sample)
                    if ai_result and not ai_result.get("error"):
                        title = ai_result.get("title", "").strip()
                        if not title:
                            title = self._clean_merged_title(base_name)
                    else:
                        title = self._clean_merged_title(base_name)
                except Exception:
                    title = self._clean_merged_title(base_name)
            else:
                title = self._clean_merged_title(base_name)

            _fp2 = f"{os.path.basename(file_paths[0])}|{total_size}"
            book_data = {
                "title": clean_metadata_text(title, MAX_TITLE_LENGTH),
                "author": clean_metadata_text("", MAX_AUTHOR_LENGTH),
                "type": "txt",
                "file_path": file_paths[0],
                "file_size": total_size,
                "encoding": encoding,
                "total_chapters": len(all_chapters),
                "category": category or "默认",
                "file_fingerprint": _fp2
            }

            chapter_rows = [
                {
                    "chapter_number": i,
                    "title": clean_metadata_text(chapter.get("title") or "", MAX_CHAPTER_TITLE_LENGTH),
                    "start_line": chapter.get("line"),
                    "start_byte": chapter.get("start_byte"),
                    "end_byte": chapter.get("end_byte"),
                    "source_file": chapter.get("_source_file")
                }
                for i, chapter in enumerate(all_chapters, 1)
            ]

            # One transaction per book: 1 commit instead of 1 + len(chapters).
            book_id = await self._store_book_with_chapters(book_data, chapter_rows)
            if not book_id:
                return

            await self._ai_extract_metadata(book_id, book_data["title"], "", file_paths[0], encoding)
            print(f"Merged: {book_data['title']} ({len(file_paths)} files, {len(all_chapters)} chapters)")

        except Exception as e:
            print(f"Error processing merged files {file_paths}: {e}")

    def _clean_merged_title(self, base_name: str) -> str:
        name = re.sub(r'[\s._-]+$', '', base_name or '')
        name = re.sub(r'^\d+[\s._、]+', '', name)
        cleaned = clean_metadata_text(name, MAX_TITLE_LENGTH)
        if cleaned:
            return cleaned
        return clean_metadata_text(base_name, MAX_TITLE_LENGTH)

    async def _store_book_with_chapters(self, book_data: Dict, chapters: List[Dict]) -> Optional[int]:
        """Persist one book and all of its chapters in a single transaction.

        ``db.add_book``/``db.add_chapter`` each commit their own row, so a book
        with N chapters used to cost 1 + N commits (N fsyncs).  Here the book row
        is inserted and every chapter goes through one ``executemany`` followed
        by a single ``commit``, which means:

          * write cost drops from 1 + N commits to 1 commit per book, and
          * the book is atomic: if anything raises, the whole book (row and
            chapters) is rolled back instead of leaving half a book behind.

        Falls back to the per-row repository API when the raw aiosqlite
        connection is not reachable, so mock/stub databases keep working.
        """
        conn = getattr(self.db, "db", None)
        batch_capable = conn is not None and hasattr(conn, "executemany")

        if not batch_capable:
            book_id = await self.db.add_book(book_data)
            if not book_id:
                return None
            for chapter in chapters:
                chapter_data = dict(chapter)
                chapter_data["book_id"] = book_id
                await self.db.add_chapter(chapter_data)
            self.stats["books_written"] += 1
            self.stats["chapters_written"] += len(chapters)
            self.stats["commits"] += 1 + len(chapters)
            return book_id

        try:
            cursor = await conn.execute(
                "SELECT id FROM books WHERE file_path = ?", (book_data["file_path"],)
            )
            existing = await cursor.fetchone()
            if existing:
                logger.warning(
                    "Book already in library, skipping: %s", book_data["file_path"]
                )
                return None

            # Dedup: check fingerprint (filename|size)
            _fp = book_data.get("file_fingerprint", "")
            if _fp:
                cursor = await conn.execute(
                    "SELECT id FROM books WHERE file_fingerprint = ? LIMIT 1", (_fp,)
                )
                dup = await cursor.fetchone()
                if dup:
                    logger.info("Duplicate detected (fingerprint match), skipping: %s",
                                book_data["file_path"])
                    return None

            await conn.execute(
                """INSERT INTO books
                   (title, author, type, file_path, file_size, encoding, total_chapters, cover_path, category, file_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    book_data.get("file_fingerprint", ""),
                ),
            )
            book_id = (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]

            if chapters:
                await conn.executemany(
                    """INSERT OR IGNORE INTO chapters
                       (book_id, chapter_number, title, start_line, start_byte, end_byte, source_file, audio_file, duration)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            book_id,
                            chapter["chapter_number"],
                            chapter["title"],
                            chapter.get("start_line"),
                            chapter.get("start_byte"),
                            chapter.get("end_byte"),
                            chapter.get("source_file"),
                            chapter.get("audio_file"),
                            chapter.get("duration"),
                        )
                        for chapter in chapters
                    ],
                )

            # The only commit of the book: book row + all chapters land together.
            await conn.commit()
            self.stats["books_written"] += 1
            self.stats["chapters_written"] += len(chapters)
            self.stats["commits"] += 1
            logger.info(
                "Stored book id=%s %r: %s chapter(s) in 1 commit",
                book_id, book_data.get("title"), len(chapters),
            )
            return book_id
        except Exception as e:
            try:
                await conn.rollback()
            except Exception:
                pass
            logger.error(
                "Storing book failed and was rolled back (file_path=%s): %s",
                book_data.get("file_path"), e, exc_info=True,
            )
            raise

    async def _process_file(self, file_path: str, category: str = None):
        try:
            encoding = self._detect_encoding(file_path)
            ai_config = await self._get_ai_config()
            can_ai = self.ai_corrector and self.ai_corrector.api_key
            regex_config = await self._get_regex_config()

            file_size = os.path.getsize(file_path)
            content = None
            if file_size <= 10 * 1024 * 1024:
                try:
                    with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    return

                if ai_config["fix_ocr"] and can_ai:
                    try:
                        fixed = await self.ai_corrector.fix_ocr_errors(content[:1000], "")
                        if fixed and len(fixed) > 100:
                            content = fixed + content[3000:]
                    except Exception:
                        pass

            if ai_config["book_name"] and can_ai:
                try:
                    sample = content[:500] if content else await self._read_content_sample(file_path, encoding)
                    filename = os.path.basename(file_path)
                    ai_result = await self.ai_corrector.extract_book_name(filename, sample)
                    if ai_result and not ai_result.get("error"):
                        title = ai_result.get("title", "").strip()
                        author = ai_result.get("author", "").strip()
                        if not title:
                            title, author = self._extract_metadata(file_path, encoding, regex_config)
                    else:
                        title, author = self._extract_metadata(file_path, encoding, regex_config)
                except Exception:
                    title, author = self._extract_metadata(file_path, encoding, regex_config)
            else:
                title, author = self._extract_metadata(file_path, encoding, regex_config)

            if file_size > 10 * 1024 * 1024:
                chapters = await self._process_large_file(file_path, encoding, regex_config)
            else:
                chapters = self._detect_chapters(content, encoding, regex_config)

                if ai_config["detect_chapters"] and can_ai and content:
                    try:
                        sample = content[:800]
                        ai_ch = await self.ai_corrector.detect_chapters(sample)
                        if ai_ch and not ai_ch.get("error") and "chapters" in ai_ch:
                            ai_list = ai_ch["chapters"]
                            if ai_list:
                                existing_titles = {ch["title"] for ch in chapters}
                                for ach in ai_list:
                                    if ach.get("title") not in existing_titles:
                                        chapters.append({
                                            "title": ach["title"],
                                            "line": ach.get("line", 0),
                                            "start_byte": 0,
                                            "end_byte": None
                                        })
                                chapters.sort(key=lambda x: x.get("line", 0))
                    except Exception:
                        pass

            if ai_config["merge_duplicates"] and can_ai and len(chapters) > 1:
                try:
                    merged = await self.ai_corrector.merge_duplicates(chapters)
                    if merged and len(merged) > 0:
                        chapters = merged
                except Exception:
                    pass

            # Metadata hygiene: body text must never end up in the books table
            # as title/author (this also covers AI-provided values).
            title = clean_metadata_text(title, MAX_TITLE_LENGTH)
            author = clean_metadata_text(author, MAX_AUTHOR_LENGTH)

            _fp1 = f"{os.path.basename(file_path)}|{file_size}"
            book_data = {
                "title": title,
                "author": author,
                "type": "txt",
                "file_path": file_path,
                "file_size": file_size,
                "encoding": encoding,
                "total_chapters": len(chapters),
                "category": category or "默认",
                "file_fingerprint": _fp1
            }

            chapter_rows = [
                {
                    "chapter_number": i,
                    "title": clean_metadata_text(chapter.get("title") or "", MAX_CHAPTER_TITLE_LENGTH),
                    "start_line": chapter.get("line"),
                    "start_byte": chapter.get("start_byte"),
                    "end_byte": chapter.get("end_byte")
                }
                for i, chapter in enumerate(chapters, 1)
            ]

            # One transaction per book: 1 commit instead of 1 + len(chapters).
            book_id = await self._store_book_with_chapters(book_data, chapter_rows)
            if not book_id:
                return

            await self._ai_extract_metadata(book_id, title, author, file_path, encoding)
            print(f"Scanned: {title} ({len(chapters)} chapters)")

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    async def _ai_extract_metadata(self, book_id: int, title: str, author: str, file_path: str, encoding: str):
        """Batch extract category + tags in one AI call instead of two."""
        if not self.ai_corrector or not self.ai_corrector.api_key:
            return
        # Respect user's AI feature toggles — skip if nothing enabled
        try:
            features = await self.db.get_config("ai_enabled_features", [])
            if isinstance(features, str):
                import json
                features = json.loads(features)
            if not features:
                return
        except Exception:
            return
        content_sample = await self._read_content_sample(file_path, encoding)
        try:
            # Use combined analyze_book for batch category+tags
            result = await self.ai_corrector.analyze_book(
                title or os.path.basename(file_path), content_sample)
            if result and not result.get("error"):
                # Category
                cat = result.get("category", "").strip()
                if cat:
                    await self.db.update_book_category(book_id, cat)
                # Tags
                tags = result.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        tag = str(tag).strip()
                        if tag:
                            await self.db.add_book_tag(book_id, tag)
        except Exception:
            # Fallback: individual calls
            try:
                cat_result = await self.ai_corrector.extract_category(
                    title, author, content_sample)
                if cat_result and not cat_result.get("error"):
                    cat = cat_result.get("category", "").strip()
                    if cat:
                        await self.db.update_book_category(book_id, cat)
            except Exception:
                pass
            try:
                tag_result = await self.ai_corrector.extract_tags(
                    title, author, content_sample)
                if tag_result and not tag_result.get("error"):
                    tags = tag_result.get("tags", [])
                    if isinstance(tags, list):
                        for tag in tags:
                            tag = str(tag).strip()
                            if tag:
                                await self.db.add_book_tag(book_id, tag)
            except Exception:
                pass

    def _detect_encoding(self, file_path: str) -> str:
        """Detect file encoding with BOM handling and fallback chain."""
        try:
            with open(file_path, 'rb') as f:
                raw = f.read(65536)

            # 1) BOM detection (highest priority)
            if raw.startswith(b'\xef\xbb\xbf'):
                return 'utf-8-sig'
            if raw.startswith(b'\xff\xfe'):
                return 'utf-16-le'
            if raw.startswith(b'\xfe\xff'):
                return 'utf-16-be'

            # 2) Try UTF-8 first (most common modern encoding)
            try:
                raw.decode('utf-8')
                return 'utf-8'
            except UnicodeDecodeError:
                pass

            # 3) chardet detection
            result = chardet.detect(raw)
            detected = (result.get('encoding') or '').lower()
            confidence = result.get('confidence', 0)

            # Map aliases to proper names
            encoding_aliases = {
                'gb2312': 'gb18030',  # gb18030 is the proper superset
                'gbk': 'gb18030',     # use gb18030 for maximum compatibility
                'ascii': 'utf-8',
                'iso-8859-1': 'utf-8',  # often a false positive
            }
            enc = encoding_aliases.get(detected, detected)

            # 4) Verify the detected encoding can actually decode the content
            if enc and confidence >= 0.5:
                try:
                    raw.decode(enc)
                    return enc
                except (UnicodeDecodeError, LookupError):
                    pass

            # 5) Fallback: try common Chinese encodings
            for fallback in ['gb18030', 'big5', 'utf-8']:
                try:
                    raw.decode(fallback)
                    return fallback
                except (UnicodeDecodeError, LookupError):
                    continue

            return 'utf-8'
        except Exception:
            return 'utf-8'

    def _extract_metadata(self, file_path: str, encoding: str = 'utf-8', regex_config: Dict = None) -> Tuple[str, str]:
        """Extract and sanitise (title, author) for a TXT file.

        The raw extraction is regex based on file lines and can capture a whole
        chunk of body text (verified: a 13 179-character "title"), so the result
        is always normalised and length-capped before it leaves the scanner.
        """
        title, author = self._extract_metadata_raw(file_path, encoding, regex_config)
        return (
            clean_metadata_text(title, MAX_TITLE_LENGTH),
            clean_metadata_text(author, MAX_AUTHOR_LENGTH),
        )

    def _extract_metadata_raw(self, file_path: str, encoding: str = 'utf-8', regex_config: Dict = None) -> Tuple[str, str]:
        filename = os.path.basename(file_path)
        name = os.path.splitext(filename)[0]
        title_from_content, author_from_content = self._extract_from_content(file_path, encoding, regex_config)
        if title_from_content:
            return title_from_content, author_from_content
        if name.strip().lower() in GENERIC_NAMES or len(name.strip()) <= 2:
            parent_dir = os.path.basename(os.path.dirname(file_path))
            if parent_dir and parent_dir not in GENERIC_NAMES:
                clean_name = self._clean_dir_name(parent_dir)
                if clean_name:
                    return clean_name, ""
        # Use configurable book name patterns on filename
        if regex_config and regex_config.get("book_name_patterns"):
            for pattern_str in regex_config["book_name_patterns"]:
                try:
                    match = re.match(pattern_str, name)
                    if match:
                        if match.lastindex and match.lastindex >= 2:
                            return match.group(1).strip(), match.group(2).strip()
                        elif match.lastindex and match.lastindex >= 1:
                            return match.group(1).strip(), ""
                except re.error:
                    continue
        return name, ""

    def _extract_from_content(self, file_path: str, encoding: str, regex_config: Dict = None) -> Tuple[str, str]:
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    # Cap the line length: a file without line breaks hands us
                    # the whole book as "line 0", and the patterns below would
                    # happily use it as the book name.
                    lines.append(line.strip()[:MAX_METADATA_SCAN_LINE])

            # Get configurable patterns
            book_patterns = []
            author_patterns = []
            if regex_config:
                book_patterns = regex_config.get("book_name_patterns", [])
                author_patterns = regex_config.get("author_patterns", [])

            for line in lines:
                if not line:
                    continue
                # Try configurable book name patterns first
                for pattern_str in book_patterns:
                    try:
                        m = re.match(pattern_str, line)
                        if m:
                            # For patterns with 2+ groups, treat group1=title, group2=author
                            if m.lastindex and m.lastindex >= 2:
                                title = m.group(1).strip()
                                author = m.group(2).strip()
                                if title:
                                    return title, author
                            elif m.lastindex and m.lastindex >= 1:
                                title = m.group(1).strip()
                                if title:
                                    # Check if any author pattern matches this line too
                                    author = ""
                                    for ap in author_patterns:
                                        try:
                                            am = re.match(ap, line)
                                            if am and am.lastindex and am.lastindex >= 1:
                                                author = am.group(1).strip()
                                                break
                                        except re.error:
                                            pass
                                    return title, author
                    except re.error:
                        continue
                # Try configurable author patterns (standalone author lines)
                for pattern_str in author_patterns:
                    try:
                        m = re.match(pattern_str, line)
                        if m and m.lastindex and m.lastindex >= 1:
                            return "", m.group(1).strip()
                    except re.error:
                        continue
            return "", ""
        except Exception:
            return "", ""

    def _clean_dir_name(self, name: str) -> str:
        name = re.sub(r'^\d+[\.\s、]+', '', name)
        name = re.sub(r'[\[\]【】\(\)（）]', '', name)
        name = re.sub(r'^(?:作者|作者[：:])\s*', '', name)
        name = name.strip(' \t\n\r')
        if len(name) < 2:
            return ""
        return name

    def _detect_chapters(self, content: str, encoding: str = 'utf-8', regex_config: Dict = None) -> List[Dict]:
        if regex_config:
            patterns = regex_config.get("chapter_patterns", DEFAULT_CHAPTER_PATTERNS)
            min_score = regex_config.get("min_chapter_score", 2)
        else:
            patterns = DEFAULT_CHAPTER_PATTERNS
            min_score = 2

        lines = content.split('\n')
        chapters = []
        byte_pos = 0
        line_byte_positions = []
        for line in lines:
            line_byte_positions.append(byte_pos)
            byte_pos += len(line.encode(encoding)) + 1
        potential_chapters = []
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            for pattern in patterns:
                try:
                    if re.match(pattern, line_stripped):
                        score = self._calculate_chapter_score(line_stripped, i, lines)
                        if score < min_score:
                            score = min_score   # pattern-match alone is sufficient
                        if score >= min_score:
                            potential_chapters.append({
                                "title": line_stripped,
                                "line": i,
                                "score": score,
                                "start_byte": line_byte_positions[i]
                            })
                        break
                except re.error:
                    continue
        # ── Pass 2: standalone short lines (no pattern match needed) ──
        _SKIP_CHARS = set('"\u201c\u201d\uff08(\u300a\u3010')
        _SKIP_KW = ('作者', '来源', '转载', 'http', 'www', '.com', '.txt', 'TXT', '论坛', '章节', '公告', '声明')
        already_found = {ch["line"] for ch in potential_chapters}
        for i, line in enumerate(lines):
            if i in already_found:
                continue
            ls = line.strip()
            n = len(ls)
            if n < 2 or n > 20:
                continue
            prev_blank = i > 0 and lines[i - 1].strip() == ''
            next_blank = i < len(lines) - 1 and lines[i + 1].strip() == ''
            if not (prev_blank or next_blank):
                continue
            if ls[0] in _SKIP_CHARS:
                continue
            if any(kw in ls for kw in _SKIP_KW):
                continue
            potential_chapters.append({
                "title": ls, "line": i, "score": 3,
                "start_byte": line_byte_positions[i]
            })
        # dedup consecutive identical titles
        deduped = []
        for ch in potential_chapters:
            if deduped and ch["title"] == deduped[-1]["title"] and ch["line"] - deduped[-1]["line"] < 5:
                continue
            deduped.append(ch)
        potential_chapters = deduped
        potential_chapters.sort(key=lambda x: x["line"])
        if potential_chapters:
            for i, ch in enumerate(potential_chapters):
                end_byte = potential_chapters[i + 1]["start_byte"] if i + 1 < len(potential_chapters) else None
                chapters.append({
                    "title": ch["title"],
                    "line": ch["line"],
                    "start_byte": ch["start_byte"],
                    "end_byte": end_byte
                })
        # Adaptive fallback: if very few chapters were found relative to
        # file length, supplement with length-based splitting so that
        # long single-chapter files are still navigable.
        total_lines = len(lines)
        if total_lines > 200:
            min_expected = max(2, total_lines // 200)
            if len(chapters) < min_expected:
                extra = self._split_by_length(content, encoding)
                if extra:
                    # Keep only the split points that fall *between* detected
                    # chapters (don't duplicate existing chapter boundaries).
                    existing_starts = {ch["line"] for ch in chapters}
                    for sp in extra:
                        if sp["line"] not in existing_starts:
                            chapters.append(sp)
                    chapters.sort(key=lambda x: x.get("line", 0))

        if not chapters:
            chapters = self._split_by_length(content, encoding)
        return chapters

    async def _process_large_file(self, file_path: str, encoding: str, regex_config: Dict = None) -> List[Dict]:
        if regex_config:
            patterns = regex_config.get("chapter_patterns", DEFAULT_CHAPTER_PATTERNS)
            min_score = regex_config.get("min_chapter_score", 2)
        else:
            patterns = DEFAULT_CHAPTER_PATTERNS
            min_score = 2

        chapters = []
        byte_pos = 0
        line_num = 0
        potential_chapters = []
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                for line in f:
                    line_stripped = line.strip()
                    if line_stripped:
                        for pattern in patterns:
                            try:
                                if re.match(pattern, line_stripped):
                                    score = self._calculate_chapter_score(line_stripped, line_num, [])
                                    if score >= min_score:
                                        potential_chapters.append({
                                            "title": line_stripped,
                                            "line": line_num,
                                            "score": score,
                                            "start_byte": byte_pos
                                        })
                                    break
                            except re.error:
                                continue
                    byte_pos += len(line.encode(encoding))
                    line_num += 1
        except Exception as e:
            print(f"Error processing large file {file_path}: {e}")
        potential_chapters.sort(key=lambda x: x["line"])
        if potential_chapters:
            for i, ch in enumerate(potential_chapters):
                end_byte = potential_chapters[i + 1]["start_byte"] if i + 1 < len(potential_chapters) else None
                chapters.append({
                    "title": ch["title"],
                    "line": ch["line"],
                    "start_byte": ch["start_byte"],
                    "end_byte": end_byte
                })
        return chapters

    def _calculate_chapter_score(self, line: str, line_num: int, all_lines: List[str]) -> int:
        score = 0
        line_s = line.strip()
        n = len(line_s)

        # ── 1. Short standalone line (most common chapter-heading form) ──
        #    2-20 chars + at least one blank-line neighbour = likely heading.
        if 2 <= n <= 20 and line_num > 0:
            prev_blank = line_num > 0 and line_num - 1 < len(all_lines) and all_lines[line_num - 1].strip() == ''
            next_blank = line_num < len(all_lines) - 1 and all_lines[line_num + 1].strip() == ''
            if prev_blank or next_blank:
                score += 3

        # ── 2. Length band ──
        if 5 <= n <= 30:
            score += 1

        # ── 3. Chapter-keyword bonus ──
        if any(c in line_s for c in ['章', '节', '卷', '篇', 'Chapter', 'CHAPTER']):
            score += 2

        # ── 4. Numeric prefix ──
        if re.match(r'^\d+[\.、]', line_s):
            score += 1

        # ── 5. Indentation (sometimes used for headings) ──
        if line.startswith('    ') or line.startswith('\t'):
            score += 1

        return score

    def _split_by_length(self, content: str, encoding: str = 'utf-8') -> List[Dict]:
        chapters = []
        chunk_size = 10000
        lines = content.split('\n')
        total_lines = len(lines)
        lines_per_chunk = max(1, total_lines // max(1, len(content) // chunk_size))
        line_offset = 0
        while line_offset < total_lines:
            end_offset = min(line_offset + lines_per_chunk, total_lines)
            chapters.append({
                "title": f"第{len(chapters) + 1}节",
                "line": line_offset,
                "start_byte": 0,
                "end_byte": 0
            })
            line_offset = end_offset
        return chapters
