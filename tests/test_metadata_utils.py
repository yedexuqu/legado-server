"""Characterization tests for the extracted pure metadata helpers.

These pin the behaviour of app.scanners.metadata_utils as originally defined
inside txt_scanner.py, so the refactor that moved the code keeps producing
identical output.  They are the regression net for phase-1.
"""
from app.scanners.metadata_utils import (
    clean_metadata_text,
    chinese_to_int,
    extract_sort_key,
)


def test_clean_metadata_text_none_returns_empty_string():
    assert clean_metadata_text(None, 10) == ""


def test_clean_metadata_text_collapses_full_width_space():
    # U+3000 full-width space and runs of whitespace collapse to a single space.
    assert clean_metadata_text("我的　小说", 100) == "我的 小说"


def test_clean_metadata_text_truncates_with_ellipsis():
    # max_length=5, ellipsis='…' (len 1) -> head takes 5-1=4 chars, then '…'.
    # clean_metadata_text rstrip()s the head, so a clean 4-char head stays.
    value = clean_metadata_text("一二三四五六七八九十", 5)
    assert value.endswith("…")
    assert len(value) == 5  # 4 head chars + 1 ellipsis
    assert value == "一二三四…"


def test_chinese_to_int():
    assert chinese_to_int("三十五") == 35
    assert chinese_to_int("一百二十三") == 123
    assert chinese_to_int("") == 0


def test_extract_sort_key():
    assert extract_sort_key("我的小说 12.txt") == ("我的小说", 12)
    # Chinese numeral in the trailing number
    assert extract_sort_key("我的小说 十二.txt") == ("我的小说", 12)
    # No number -> (name, 0)
    assert extract_sort_key("我的小说.txt") == ("我的小说", 0)
