"""HTML page routes: /, /search, /book/{id}, /book/{id}/chapter/{num}, /cover/{id}, /settings — optimized."""

import logging
import os
from html import escape as _html_escape
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, Response
from typing import Optional

from ..deps import get_db, get_templates
from ..utils import is_legado_client, validate_file_path
from ..auth import get_current_user
from ..legado.source import get_book_source_url

router = APIRouter()
logger = logging.getLogger(__name__)

# Allowed per_page values
VALID_PAGE_SIZES = {10, 20, 50, 100}
DEFAULT_PAGE_SIZE = 50


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    view: str = Query("grid")
):
    """Home page with category/tag filtering and view modes."""
    db = await get_db()
    templates = get_templates()

    # Resolve page size
    if per_page and per_page in VALID_PAGE_SIZES:
        page_size = per_page
    else:
        try:
            page_size = int(await db.config.get("page_size", str(DEFAULT_PAGE_SIZE)))
            if page_size not in VALID_PAGE_SIZES:
                page_size = DEFAULT_PAGE_SIZE
        except (ValueError, TypeError):
            page_size = DEFAULT_PAGE_SIZE

    # Fetch books based on filter
    if category:
        books = await db.categories.get_books(category, page=page, per_page=page_size)
        total = await db.categories.get_count(category)
    elif tag:
        books = await db.tags.get_books_by_tag(tag, page=page, per_page=page_size)
        total = await db.tags.get_book_tag_count(tag)
    else:
        books = await db.books.get_all(page=page, per_page=page_size)
        total = await db.books.count()

    categories = await db.categories.get_all()
    tags = await db.tags.get_popular(limit=30)

    valid_views = {"grid", "list", "category", "detail", "timeline", "bigicon"}
    view_mode = view if view in valid_views else "grid"

    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "books": books,
        "page": page,
        "total": total,
        "per_page": page_size,
        "categories": categories,
        "tags": tags,
        "current_category": category,
        "current_tag": tag,
        "view_mode": view_mode
    })


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    key: str = Query(..., min_length=1, max_length=200),
    page: int = Query(1, ge=1)
):
    """Search results page."""
    db = await get_db()
    templates = get_templates()
    try:
        page_size = int(await db.config.get("page_size", str(DEFAULT_PAGE_SIZE)))
        if page_size not in VALID_PAGE_SIZES:
            page_size = DEFAULT_PAGE_SIZE
    except (ValueError, TypeError):
        page_size = DEFAULT_PAGE_SIZE

    results = await db.books.search(key, page=page, per_page=page_size)
    total = await db.books.search_count(key)

    template = "search_legado.html" if is_legado_client(request) else "search.html"
    return templates.TemplateResponse(request, template, {
        "request": request,
        "results": results,
        "books": results,
        "key": key,
        "page": page,
        "total": total,
        "per_page": page_size,
        "base_url": await get_book_source_url(request) if is_legado_client(request) else ""
    })


@router.get("/book/{book_id}", response_class=HTMLResponse)
async def book_detail(request: Request, book_id: int):
    """Book detail page with chapter list."""
    if book_id < 1:
        raise HTTPException(status_code=400, detail="无效的书籍 ID")
    db = await get_db()
    templates = get_templates()
    book = await db.books.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    chapters = await db.chapters.get_all(book_id)
    book_tags = await db.tags.get_by_book(book_id)
    template = "book_legado.html" if is_legado_client(request) else "book.html"

    return templates.TemplateResponse(request, template, {
        "request": request,
        "book": book,
        "chapters": chapters,
        "tags": book_tags,
        "base_url": await get_book_source_url(request) if is_legado_client(request) else ""
    })


@router.get("/book/{book_id}/chapter/{chapter_num}", response_class=HTMLResponse)
async def chapter(request: Request, book_id: int, chapter_num: int):
    """Chapter reading page."""
    if book_id < 1 or chapter_num < 1:
        raise HTTPException(status_code=400, detail="无效的参数")
    db = await get_db()
    templates = get_templates()
    book = await db.books.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    ch = await db.chapters.get(book_id, chapter_num)
    if not ch:
        raise HTTPException(status_code=404, detail="章节不存在")

    content = await db.chapters.get_content(ch["id"])
    template = "chapter_legado.html" if is_legado_client(request) else "chapter.html"

    return templates.TemplateResponse(request, template, {
        "request": request,
        "book": book,
        "chapter": ch,
        "content": content,
        "chapter_num": chapter_num,
        "base_url": await get_book_source_url(request) if is_legado_client(request) else ""
    })


def _placeholder_cover(book: Optional[dict] = None, label: str = "暂无封面") -> Response:
    """Build an inline SVG placeholder cover (always HTTP 200, image/svg+xml).

    Used instead of a JSON error body so that <img src="/cover/{id}"> never
    renders a broken image.
    """
    book = book or {}
    title = (book.get("title") or "").strip()
    is_audio = book.get("type") == "audio"
    glyph = _html_escape(title[0]) if title else ("♪" if is_audio else "书")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400" '
        'role="img" aria-label="' + _html_escape(label) + '">'
        '<defs><linearGradient id="cbg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#2b2f3a"/><stop offset="100%" stop-color="#1b1e26"/>'
        '</linearGradient></defs>'
        '<rect width="300" height="400" fill="url(#cbg)"/>'
        '<rect x="70" y="110" width="160" height="150" rx="12" fill="none" '
        'stroke="#4f6ef7" stroke-width="4" opacity="0.5"/>'
        '<text x="150" y="228" font-family="sans-serif" font-size="76" fill="#4f6ef7" '
        'text-anchor="middle" opacity="0.9">' + glyph + '</text>'
        '<text x="150" y="320" font-family="sans-serif" font-size="20" fill="#8b93a7" '
        'text-anchor="middle">' + _html_escape(label) + '</text>'
        '</svg>'
    )
    return Response(
        content=svg.encode("utf-8"),
        media_type="image/svg+xml",
        status_code=200,
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/cover/{book_id}")
async def cover(book_id: int):
    """Serve book cover image; always returns an image, never a JSON error body."""
    db = await get_db()
    book = None
    if book_id >= 1:
        try:
            book = await db.books.get(book_id)
        except Exception as exc:  # never let a lookup error break the <img>
            logger.warning(f"cover: 查询书籍 {book_id} 失败: {exc}")

    cover_path = (book or {}).get("cover_path")
    if cover_path:
        raw_dirs = await db.config.get("book_dirs", ["/books"]) or []
        # book_dirs may hold plain strings or {"path": ..., "category": ...} dicts
        allowed_dirs = []
        for entry in raw_dirs:
            if isinstance(entry, dict):
                path = entry.get("path")
            elif isinstance(entry, str):
                path = entry
            else:
                path = None
            if path:
                allowed_dirs.append(path)

        if allowed_dirs and validate_file_path(cover_path, allowed_dirs) and os.path.isfile(cover_path):
            return FileResponse(cover_path)

        logger.warning(
            "cover: 书籍 %s 的封面不可用（校验失败或文件不存在），返回占位图: %s",
            book_id, cover_path,
        )

    return _placeholder_cover(book)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page (requires admin login)."""
    from fastapi.responses import RedirectResponse
    
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/settings", status_code=302)
    
    db = await get_db()
    templates = get_templates()
    config = await db.config.get_all()

    return templates.TemplateResponse(request, "settings.html", {
        "request": request,
        "config": config,
        "admin_user": user
    })
