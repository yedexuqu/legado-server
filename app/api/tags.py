"""Tag API endpoints with validation and error handling."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from ..deps import get_db

router = APIRouter()


class TagCreate(BaseModel):
    """Create a new tag."""
    name: str = Field(..., min_length=1, max_length=100, description="Tag name")


class TagRename(BaseModel):
    """Rename a tag."""
    old: str = Field(..., min_length=1, max_length=100)
    new: str = Field(..., min_length=1, max_length=100)


class TagMerge(BaseModel):
    """Merge two tags."""
    source: str = Field(..., min_length=1, max_length=100)
    target: str = Field(..., min_length=1, max_length=100)


@router.get("/tags")
async def get_tags():
    """Get all tags with usage counts."""
    try:
        database = await get_db()
        tags = await database.get_popular_tags(limit=100)
        return {"success": True, "data": tags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取标签列表失败: {str(e)}")


@router.get("/tags/popular")
async def get_popular_tags(limit: int = Query(20, ge=1, le=100)):
    """Get popular tags (consumed by the book detail tag editor)."""
    try:
        database = await get_db()
        rows = await database.get_popular_tags(limit=limit)
        data = [{"name": (r.get("tag") or r.get("name")), "count": r.get("count", 0)} for r in rows]
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取热门标签失败: {str(e)}")


@router.post("/tags")
async def create_tag(config: TagCreate):
    """Create a new empty tag."""
    name = config.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名称不能为空")
    try:
        database = await get_db()
        # Check if already exists
        existing = await database.tags.exists_in_tags_table(name)
        if existing:
            raise HTTPException(status_code=409, detail=f"标签 '{name}' 已存在")
        await database.tags.create(name)
        return {"success": True, "message": f"标签 '{name}' 已添加"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建标签失败: {str(e)}")


@router.delete("/tags/{tag}")
async def delete_tag(tag: str):
    """Delete a tag from all books and the tags table."""
    try:
        database = await get_db()
        count = await database.delete_tag(tag)
        await database.db.execute("DELETE FROM tags WHERE name = ?", (tag,))
        await database.db.commit()
        return {"success": True, "message": f"已从 {count} 本书中移除标签"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除标签失败: {str(e)}")


@router.post("/tags/rename")
async def rename_tag(config: TagRename):
    """Rename a tag across all books."""
    old_tag = config.old.strip()
    new_tag = config.new.strip()
    if not old_tag or not new_tag:
        raise HTTPException(status_code=400, detail="old 和 new 参数不能为空")
    try:
        database = await get_db()
        count = await database.rename_tag(old_tag, new_tag)
        return {"success": True, "message": f"已重命名 {count} 条标签记录"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重命名标签失败: {str(e)}")


@router.post("/tags/merge")
async def merge_tags(config: TagMerge):
    """Merge source tag into target tag."""
    source = config.source.strip()
    target = config.target.strip()
    if not source or not target:
        raise HTTPException(status_code=400, detail="source 和 target 参数不能为空")
    if source == target:
        raise HTTPException(status_code=400, detail="源标签和目标标签不能相同")
    try:
        database = await get_db()
        count = await database.merge_tags(source, target)
        return {"success": True, "message": f"已合并 {count} 条标签记录"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"合并标签失败: {str(e)}")


@router.get("/books/by-tag/{tag}")
async def get_books_by_tag(
    tag: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """Get books filtered by tag."""
    try:
        database = await get_db()
        books = await database.get_books_by_tag(tag, page=page, per_page=per_page)
        total = await database.get_book_tag_count(tag)
        return {"success": True, "data": books, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取标签书籍失败: {str(e)}")
