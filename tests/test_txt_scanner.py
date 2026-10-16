"""Characterization tests for TxtScanner pure internals.

These pin the CURRENT behavior of the scanner's pure helpers. None of them
touches the database or the network -- ``TxtScanner(None)`` is constructible
precisely because these helpers never use ``self.db`` -- so the tests run
without any I/O beyond tiny temp files for encoding detection.

They exist as a safety net for further modularization: if a refactor changes
any assertion below, that is a deliberate behavior change and must be
reviewed, not an accident. Quirks (e.g. the ``作者`` prefix alternation order
in ``_clean_dir_name``) are pinned on purpose.
"""
import pytest

from app.scanners.metadata_utils import METADATA_ELLIPSIS
from app.scanners.txt_scanner import TxtScanner


@pytest.fixture()
def scanner():
    return TxtScanner(None)


def _write(tmp_path, name, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# ── construction ──────────────────────────────────────────────────────────

def test_scanner_constructible_without_db(scanner):
    assert scanner.db is None
    assert scanner.ai_corrector is None
    assert scanner.stats == {"books_written": 0, "chapters_written": 0, "commits": 0}
    scanner.stats["books_written"] = 5
    assert scanner.reset_stats() == {"books_written": 0, "chapters_written": 0, "commits": 0}


# ── _detect_encoding ──────────────────────────────────────────────────────

def test_detect_encoding_bom_variants(scanner, tmp_path):
    body = "章节内容".encode("utf-8")
    assert scanner._detect_encoding(_write(tmp_path, "sig.txt", b"\xef\xbb\xbf" + body)) == "utf-8-sig"
    assert scanner._detect_encoding(_write(tmp_path, "le.txt", b"\xff\xfe" + body)) == "utf-16-le"
    assert scanner._detect_encoding(_write(tmp_path, "be.txt", b"\xfe\xff" + body)) == "utf-16-be"


def test_detect_encoding_utf8_and_ascii(scanner, tmp_path):
    assert scanner._detect_encoding(_write(tmp_path, "u8.txt", "第一章 测试".encode("utf-8"))) == "utf-8"
    assert scanner._detect_encoding(_write(tmp_path, "ascii.txt", b"plain ascii text")) == "utf-8"


def test_detect_encoding_gbk_maps_to_gb18030(scanner, tmp_path):
    text = "这是一段用来测试编码检测的中文内容，包含常用汉字与标点符号。" * 200
    assert scanner._detect_encoding(_write(tmp_path, "gbk.txt", text.encode("gbk"))) == "gb18030"


def test_detect_encoding_big5(scanner, tmp_path):
    text = "這是一段用來測試編碼偵測的中文內容，包含常用字與標點符號。" * 200
    assert scanner._detect_encoding(_write(tmp_path, "big5.txt", text.encode("big5"))) == "big5"


def test_detect_encoding_empty_file_is_utf8(scanner, tmp_path):
    assert scanner._detect_encoding(_write(tmp_path, "empty.txt", b"")) == "utf-8"


def test_detect_encoding_missing_file_falls_back_to_utf8(scanner, tmp_path):
    assert scanner._detect_encoding(str(tmp_path / "does-not-exist.txt")) == "utf-8"


# ── _clean_dir_name ───────────────────────────────────────────────────────

def test_clean_dir_name_strips_numeric_prefix(scanner):
    assert scanner._clean_dir_name("12.三体") == "三体"
    assert scanner._clean_dir_name("001、斗破苍穹") == "斗破苍穹"
    assert scanner._clean_dir_name("3 body") == "body"


def test_clean_dir_name_strips_author_prefix_and_brackets(scanner):
    # Quirk: the alternation tries the bare ``作者`` branch first, so a
    # following full-width colon is NOT consumed. Pinned deliberately.
    assert scanner._clean_dir_name("作者天蚕土豆") == "天蚕土豆"
    assert scanner._clean_dir_name("作者：天蚕土豆") == "：天蚕土豆"
    assert scanner._clean_dir_name("【精校】凡人修仙传") == "精校凡人修仙传"
    assert scanner._clean_dir_name("12.(作者)鲁迅全集") == "鲁迅全集"


def test_clean_dir_name_short_names_rejected(scanner):
    assert scanner._clean_dir_name("a") == ""
    assert scanner._clean_dir_name("") == ""
    assert scanner._clean_dir_name("作者传") == ""  # strips to 1 char -> rejected


def test_clean_dir_name_keeps_normal_names(scanner):
    assert scanner._clean_dir_name("凡人修仙传") == "凡人修仙传"


# ── _clean_merged_title ───────────────────────────────────────────────────

def test_clean_merged_title_strips_trailing_separators(scanner):
    assert scanner._clean_merged_title("三体.") == "三体"
    assert scanner._clean_merged_title("三体 _- ") == "三体"


def test_clean_merged_title_strips_leading_numbers(scanner):
    assert scanner._clean_merged_title("12. 三体") == "三体"
    assert scanner._clean_merged_title("12、三体") == "三体"


def test_clean_merged_title_collapses_whitespace(scanner):
    assert scanner._clean_merged_title("三  体") == "三 体"


def test_clean_merged_title_caps_length(scanner):
    out = scanner._clean_merged_title("书" * 500)
    assert len(out) == 200
    assert out.endswith(METADATA_ELLIPSIS)


def test_clean_merged_title_falls_back_to_raw_name(scanner):
    # "..." is fully consumed by the trailing-separator strip; the empty
    # result makes the function fall back to the raw name, so the dots come
    # back. Pinned deliberately.
    assert scanner._clean_merged_title("...") == "..."


def test_clean_merged_title_none_is_empty(scanner):
    assert scanner._clean_merged_title(None) == ""


# ── _calculate_chapter_score ──────────────────────────────────────────────

def test_chapter_score_short_standalone_with_blank_neighbor(scanner):
    lines = ["", "第一章 大结局", "正文内容"]
    # +3 standalone (blank above), +1 length band (7 chars), +2 keyword 章
    assert scanner._calculate_chapter_score("第一章 大结局", 1, lines) == 6


def test_chapter_score_first_line_never_gets_standalone_bonus(scanner):
    lines = ["第一章", ""]
    # line_num == 0 excludes the +3; only the keyword bonus applies.
    assert scanner._calculate_chapter_score("第一章", 0, lines) == 2


def test_chapter_score_no_blank_neighbor_no_standalone_bonus(scanner):
    lines = ["第一章", "上下文", "更多"]
    assert scanner._calculate_chapter_score("第一章", 1, lines) == 2


def test_chapter_score_length_band(scanner):
    assert scanner._calculate_chapter_score("a" * 10, 0, ["a" * 10]) == 1
    assert scanner._calculate_chapter_score("a" * 4, 0, ["a" * 4]) == 0
    assert scanner._calculate_chapter_score("a" * 31, 0, ["a" * 31]) == 0


def test_chapter_score_keywords(scanner):
    assert scanner._calculate_chapter_score("卷", 0, ["卷"]) == 2
    lines = ["Chapter 1", ""]
    # length band (9 chars) + keyword, but no standalone bonus on line 0
    assert scanner._calculate_chapter_score("Chapter 1", 0, lines) == 3


def test_chapter_score_numeric_prefix(scanner):
    # len band (5) + numeric prefix
    assert scanner._calculate_chapter_score("12.标题", 0, ["12.标题"]) == 2
    assert scanner._calculate_chapter_score("12、标题", 0, ["12、标题"]) == 2
    # a plain space after the digits does not match ^\d+[.、]
    assert scanner._calculate_chapter_score("12 标题", 0, ["12 标题"]) == 1


def test_chapter_score_indentation_uses_raw_line(scanner):
    lines = ["", "\t第一节", ""]
    # +3 standalone, +2 keyword, +1 tab indent (checked on the raw line)
    assert scanner._calculate_chapter_score("\t第一节", 1, lines) == 6
    lines = ["    第五章", ""]
    # line 0: no standalone bonus; +2 keyword, +1 four-space indent
    assert scanner._calculate_chapter_score("    第五章", 0, lines) == 3


# ── _split_by_length ──────────────────────────────────────────────────────

def test_split_by_length_small_content_single_chunk(scanner):
    chapters = scanner._split_by_length("只有一行内容")
    assert chapters == [{"title": "第1节", "line": 0, "start_byte": 0, "end_byte": 0}]


def test_split_by_length_chunks_long_multiline_content(scanner):
    # 10 lines x ~5001 chars -> len(content) // 10000 == 5 chunks over 10
    # lines -> 2 lines per chunk, 第N节 numbering starting at 1.
    content = "\n".join("line%d %s" % (i, "x" * 4995) for i in range(10))
    chapters = scanner._split_by_length(content)
    assert [c["title"] for c in chapters] == ["第1节", "第2节", "第3节", "第4节", "第5节"]
    assert [c["line"] for c in chapters] == [0, 2, 4, 6, 8]
    assert all(c["start_byte"] == 0 and c["end_byte"] == 0 for c in chapters)


def test_split_by_length_single_long_line_is_one_chunk(scanner):
    # len(content) // 10000 == 2, but total_lines == 1 and lines_per_chunk
    # floors to 0 -> max(1, 0) keeps one line per chunk.
    chapters = scanner._split_by_length("x" * 25000)
    assert len(chapters) == 1
    assert chapters[0]["title"] == "第1节"
