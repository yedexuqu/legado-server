"""Book API endpoints with input validation and error handling."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from ..deps import get_db

router = APIRouter()


class BookSearchParams(BaseModel):
    """Query parameters for book search/list."""
    search: Optional[str] = Field(None, max_length=200, description="Search keyword")
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(50, ge=1, le=200, description="Items per page")


@router.get("/books")
async def api_search_books(
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """List or search books with pagination.

    Args:
        search: Optional search keyword (matches title/author)
        page: Page number (1-based)
        per_page: Items per page (1-200, default 50)
    """
    database = await get_db()
    try:
        if search:
            results = await database.books.search(search, page=page, per_page=per_page)
            total = await database.books.search_count(search)
        else:
            results = await database.books.get_all(page=page, per_page=per_page)
            total = await database.books.count()
        return {"success": True, "data": results, "total": total, "page": page, "per_page": per_page}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取书籍列表失败: {str(e)}")


@router.get("/books/{book_id}")
async def api_get_book(book_id: int):
    """Get a single book with its chapters.

    Args:
        book_id: Book database ID
    """
    if book_id < 1:
        raise HTTPException(status_code=400, detail="无效的书籍 ID")
    database = await get_db()
    try:
        book = await database.books.get(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")
        chapters = await database.chapters.get_all(book_id)
        return {"success": True, "data": {"book": book, "chapters": chapters}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取书籍详情失败: {str(e)}")


@router.get("/books/{book_id}/chapters")
async def api_get_chapters(book_id: int):
    """Get chapter list for a book.

    Args:
        book_id: Book database ID
    """
    if book_id < 1:
        raise HTTPException(status_code=400, detail="无效的书籍 ID")
    database = await get_db()
    try:
        chapters = await database.chapters.get_all(book_id)
        return {"success": True, "data": chapters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取章节列表失败: {str(e)}")


@router.get("/books/{book_id}/chapter/{chapter_num}")
async def api_get_chapter_content(book_id: int, chapter_num: int):
    """Get chapter content by book ID and chapter number.

    Args:
        book_id: Book database ID
        chapter_num: Chapter number (1-based)
    """
    if book_id < 1:
        raise HTTPException(status_code=400, detail="无效的书籍 ID")
    if chapter_num < 1:
        raise HTTPException(status_code=400, detail="无效的章节号")
    database = await get_db()
    try:
        chapter = await database.chapters.get(book_id, chapter_num)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        content = await database.chapters.get_content(chapter["id"])
        return {"success": True, "data": {"chapter": chapter, "content": content}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取章节内容失败: {str(e)}")


class BookTagsUpdate(BaseModel):
    """Payload for replacing a book's tags."""
    tags: list = Field(default_factory=list, description="Full tag list for the book")


@router.post("/books/{book_id}/tags/batch")
async def set_book_tags(book_id: int, payload: BookTagsUpdate):
    """Replace all tags of a book (used by the book detail tag editor)."""
    try:
        database = await get_db()
        if book_id < 1:
            raise HTTPException(status_code=400, detail="无效的书籍 ID")
        book = await database.books.get(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")

        target = {str(t).strip() for t in payload.tags if str(t).strip()}
        current = set(await database.tags.get_by_book(book_id))

        for t in current - target:
            await database.tags.remove(book_id, t)
        for t in target - current:
            await database.tags.add(book_id, t)
        return {"success": True, "data": sorted(target), "message": f"已更新 {len(target)} 个标签"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存标签失败: {str(e)}")
