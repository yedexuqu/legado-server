"""Legado book source routes: /sources/*, /discover — optimized."""

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Optional

from ..deps import get_db, get_templates
from ..utils import is_legado_client

router = APIRouter()


async def get_book_source_url(request: Request) -> str:
    """Get book source URL, using configured URL if available."""
    db = await get_db()
    configured_url = await db.get_config("book_source_url", "")
    if configured_url:
        return configured_url.rstrip("/")

    host = request.headers.get("Host", "localhost:8086")
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    scheme = "https" if forwarded_proto == "https" or "443" in host else "http"
    return f"{scheme}://{host}"


# Shared rule definitions to avoid duplication
_TEXT_RULES = {
    "ruleExplore": {
        "bookList": "@css:.book-item",
        "name": "@css:.book-title@text",
        "author": "@css:.book-author@text",
        "coverUrl": "@css:img@src",
        "bookUrl": "@css:a@href"
    },
    "ruleSearch": {
        "bookList": "@css:.book-item",
        "name": "@css:.book-title@text",
        "author": "@css:.book-author@text",
        "coverUrl": "@css:img@src",
        "bookUrl": "@css:a@href"
    },
    "ruleBookInfo": {
        "name": "@css:.book-title@text",
        "author": "@css:.book-author@text",
        "coverUrl": "@css:.book-cover@src",
        "intro": "@css:.book-intro@text",
        "lastChapter": "@css:.chapter-item:first-child a@text"
    },
    "ruleToc": {
        "chapterList": "@css:.chapter-item",
        "chapterName": "@css:a@text",
        "chapterUrl": "@css:a@href"
    },
    "ruleContent": {
        "content": "@css:.chapter-text@text"
    }
}


@router.get("/sources/text.json")
async def text_source(request: Request):
    """Generate Legado-compatible text book source JSON."""
    base_url = await get_book_source_url(request)
    source = {
        "bookSourceUrl": base_url,
        "bookSourceName": "本地书库",
        "bookSourceType": 0,
        "bookSourceGroup": "自建",
        "enabled": True,
        "enabledExplore": True,
        "header": '{"User-Agent": "Legado/3.0"}',
        "searchUrl": "{{baseUrl}}/search?key={{key}}&page={{page}}",
        "exploreUrl": "{{baseUrl}}/discover?page={{page}}",
        **_TEXT_RULES
    }
    return JSONResponse(content=[source])


@router.get("/sources/audio.json")
async def audio_source(request: Request):
    """Generate Legado-compatible audio book source JSON.

    Selectors are aligned with the real Legado-facing DOM:
      search  -> templates/search_legado.html (div.book-list > div.book-item)
      bookInfo/toc -> templates/book_legado.html (div.chapter-list > div.chapter-item)
      content -> templates/chapter_legado.html (audio.chapter-audio[src])
    """
    host = request.headers.get("Host", "localhost:8086")
    scheme = "https" if "443" in host else "http"

    source = {
        "bookSourceUrl": f"{scheme}://{host}",
        "bookSourceName": "本地有声书",
        "bookSourceType": 1,
        "searchUrl": "{{baseUrl}}/search?key={{key}}&page={{page}}",
        "ruleSearch": {
            "bookList": "@css:.book-list .book-item",
            "name": "@css:.book-title@text",
            "author": "@css:.book-author@text",
            "bookUrl": "@css:a@href",
            "coverUrl": "@css:img@src"
        },
        "ruleBookInfo": {
            "name": "@css:h1.book-title@text",
            "author": "@css:p.book-author@text",
            "coverUrl": "@css:img.book-cover@src"
        },
        "ruleToc": {
            "chapterList": "@css:.chapter-list .chapter-item",
            "chapterName": "@css:a@text",
            "chapterUrl": "@css:a@href"
        },
        "ruleContent": {
            "content": "@css:audio.chapter-audio@src"
        }
    }
    return JSONResponse(content=[source])


@router.get("/sources/qr")
async def source_qr(request: Request):
    """Generate QR code for book source URL.

    Returns HTTP 503 when the optional qrcode dependency is missing so that
    clients cannot mistake a failure for a successful response.
    """
    try:
        import qrcode
    except ImportError:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "qrcode_missing",
                "message": "qrcode 库未安装，无法生成二维码；请先安装（pip install 'qrcode[pil]'）后重试",
            },
        )

    try:
        from io import BytesIO
        import base64

        base_url = await get_book_source_url(request)
        url = f"{base_url}/sources/text.json"

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return {"success": True, "url": url, "qr": f"data:image/png;base64,{img_base64}"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "qr_generation_failed", "message": str(e)},
        )


@router.get("/sources/export")
async def source_export(request: Request):
    """Export book source as downloadable JSON file."""
    from fastapi.responses import Response
    import json

    base_url = await get_book_source_url(request)
    source = {
        "bookSourceUrl": base_url,
        "bookSourceName": "本地书库",
        "bookSourceType": 0,
        "searchUrl": "{{baseUrl}}/search?key={{key}}&page={{page}}",
        "enabled": True,
        "exploreUrl": "{{baseUrl}}/discover?page={{page}}",
        **_TEXT_RULES
    }

    content = json.dumps([source], ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="legado_source.json"'}
    )


@router.get("/discover")
async def discover(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100)
):
    """Discovery page for Legado — uses repository pattern instead of raw SQL."""
    db = await get_db()
    templates = get_templates()
    offset = (page - 1) * per_page

    books = await db.get_books(page=page, per_page=per_page)

    if is_legado_client(request):
        return templates.TemplateResponse(request, "discover_legado.html",
                                          {"request": request, "books": books, "base_url": await get_book_source_url(request)})

    # Browser: index.html needs the full context, otherwise rendering breaks (500).
    categories = await db.get_categories()
    tags = await db.get_popular_tags(limit=30)
    total = await db.get_book_count()
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "books": books,
        "page": page,
        "total": total,
        "per_page": per_page,
        "categories": categories,
        "tags": tags,
        "current_category": None,
        "current_tag": None,
        "view_mode": "grid",
    })
