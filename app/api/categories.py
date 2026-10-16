"""Category API endpoints with validation and error handling."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Any

from ..deps import get_db

router = APIRouter()


class CategoryCreate(BaseModel):
    """Create a new category."""
    name: str = Field(..., min_length=1, max_length=100, description="Category name")


class CategoryRename(BaseModel):
    """Rename a category."""
    old: str = Field(..., min_length=1, max_length=100)
    new: str = Field(..., min_length=1, max_length=100)


@router.get("/categories")
async def get_categories():
    """Get all categories with book counts."""
    try:
        database = await get_db()
        categories = await database.get_categories()
        return {"success": True, "data": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类列表失败: {str(e)}")


@router.post("/categories")
async def create_category(config: CategoryCreate):
    """Create a new empty category."""
    name = config.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    try:
        database = await get_db()
        # Check if already exists
        existing = await database.categories.exists(name)
        if existing:
            raise HTTPException(status_code=409, detail=f"分类 '{name}' 已存在")
        await database.categories.create(name)
        return {"success": True, "message": f"分类 '{name}' 已添加"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建分类失败: {str(e)}")


@router.post("/categories/rename")
async def rename_category(config: CategoryRename):
    """Rename a category and update all books in it."""
    old_name = config.old.strip()
    new_name = config.new.strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="old 和 new 参数不能为空")
    try:
        database = await get_db()
        # Update books
        count = await database.batch_update_category(old_name, new_name)
        # Update categories table
        await database.db.execute(
            "UPDATE categories SET name = ? WHERE name = ?", (new_name, old_name)
        )
        await database.db.commit()
        return {"success": True, "message": f"已重命名 {count} 本书的分类"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重命名分类失败: {str(e)}")


@router.delete("/categories/{category}")
async def delete_category(category: str):
    """Delete a category, moving its books to '默认'."""
    try:
        database = await get_db()
        count = await database.batch_update_category(category, "默认")
        await database.db.execute(
            "DELETE FROM categories WHERE name = ?", (category,)
        )
        await database.db.commit()
        return {"success": True, "message": f"已将 {count} 本书移至默认分类"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除分类失败: {str(e)}")


@router.get("/books/by-category/{category}")
async def get_books_by_category(
    category: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """Get books filtered by category."""
    try:
        database = await get_db()
        books = await database.get_books_by_category(category, page=page, per_page=per_page)
        total = await database.get_book_count_by_category(category)
        return {"success": True, "data": books, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类书籍失败: {str(e)}")
