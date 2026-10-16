import os
import re
import logging
from typing import Tuple

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
    r'^(.+?)[-_](.+)',
    r'^(.+?)[（(](.+?)[）)]$',
]

DEFAULT_AUTHOR_PATTERNS = [
    r'作者[：:]\s*(.+)',
    r'^(?:作者|作者名)[：:]\s*(.+)',
]
