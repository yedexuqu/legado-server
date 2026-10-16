"""Configuration API endpoints with validation and error handling."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Any

from ..deps import get_db

router = APIRouter()


class ConfigUpdate(BaseModel):
    """Configuration update request."""
    key: str = Field(..., min_length=1, max_length=100, description="Config key")
    value: Any = Field(..., description="Config value")
    description: Optional[str] = Field(None, max_length=500)
    category: Optional[str] = Field("general", max_length=50)


class BulkConfigUpdate(BaseModel):
    """Bulk configuration update request."""
    configs: list[ConfigUpdate] = Field(..., min_length=1, max_length=50)


@router.get("/config")
async def get_all_config():
    """Get all configuration values."""
    try:
        database = await get_db()
        config = await database.config.get_all()
        return {"success": True, "data": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/config/{category}")
async def get_config_by_category(category: str):
    """Get configuration for a specific category."""
    try:
        database = await get_db()
        config = await database.config.get_by_category(category)
        if not config:
            raise HTTPException(status_code=404, detail=f"配置分类 '{category}' 不存在")
        return {"success": True, "data": config}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类配置失败: {str(e)}")


@router.get("/config/key/{key}")
async def get_config_value(key: str):
    """Get a single config value by key. Masks sensitive values."""
    try:
        database = await get_db()
        value = await database.config.get(key)
        if value is None:
            raise HTTPException(status_code=404, detail="配置项不存在")
        # Mask AI API key for security
        if key == "ai_api_key" and value:
            value = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
        return {"success": True, "data": {"key": key, "value": value}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置值失败: {str(e)}")


@router.post("/config")
async def update_config(config: ConfigUpdate):
    """Update a single configuration value."""
    try:
        database = await get_db()
        success = await database.config.set(config.key, config.value, config.description, config.category)
        if success:
            return {"success": True, "message": f"配置 '{config.key}' 已更新"}
        else:
            raise HTTPException(status_code=500, detail=f"配置 '{config.key}' 更新失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.post("/config/bulk")
async def bulk_update_config(bulk: BulkConfigUpdate):
    """Update multiple configuration values at once."""
    try:
        database = await get_db()
        results = []
        for c in bulk.configs:
            try:
                success = await database.config.set(c.key, c.value, c.description, c.category)
                results.append({"key": c.key, "success": success})
            except Exception as e:
                results.append({"key": c.key, "success": False, "error": str(e)})
        success_count = sum(1 for r in results if r["success"])
        return {
            "success": True,
            "data": results,
            "message": f"成功更新 {success_count}/{len(results)} 个配置项"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量更新配置失败: {str(e)}")


@router.delete("/config/{key}")
async def delete_config(key: str):
    """Delete a configuration value."""
    try:
        database = await get_db()
        await database.config.delete(key)
        return {"success": True, "message": f"配置 '{key}' 已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.post("/config/scan")
async def trigger_scan():
    """Trigger a manual scan of book directories."""
    try:
        from ..deps import get_scanner_service
        scanner = get_scanner_service()
        scanned_count = await scanner.scan_all()
        return {"success": True, "message": f"扫描完成，处理了 {scanned_count} 个目录"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.get("/stats")
async def get_stats():
    """Get system statistics (book count, chapters, total size)."""
    try:
        database = await get_db()
        book_count = await database.books.count()

        async with database.get_connection() as conn:
            cursor = await conn.execute("SELECT type, COUNT(*) as count FROM books GROUP BY type")
            type_stats = {row[0]: row[1] for row in await cursor.fetchall()}

            cursor = await conn.execute("SELECT COUNT(*) FROM chapters")
            total_chapters = (await cursor.fetchone())[0]

            cursor = await conn.execute("SELECT SUM(file_size) FROM books")
            total_size = (await cursor.fetchone())[0] or 0

        return {
            "success": True,
            "data": {
                "book_count": book_count,
                "total_chapters": total_chapters,
                "total_size": total_size,
                "type_distribution": type_stats
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.post("/config/delete-dir")
async def delete_dir_with_books(config: ConfigUpdate):
    """Delete a directory from book_dirs and remove its books from DB."""
    try:
        database = await get_db()
        dir_path = str(config.value).strip()
        if not dir_path:
            raise HTTPException(status_code=400, detail="目录路径不能为空")

        if len(dir_path) < 2 or dir_path == "/":
            raise HTTPException(status_code=400, detail="目录路径非法，拒绝删除")

        book_dirs = await database.config.get("book_dirs", [])
        if not isinstance(book_dirs, list):
            book_dirs = []
        registered = [(d.get("path") if isinstance(d, dict) else str(d)) for d in book_dirs]
        if dir_path not in registered:
            raise HTTPException(status_code=400, detail=f"目录 '{dir_path}' 不在已配置的书籍目录中，拒绝删除")

        book_dirs = [d for d in book_dirs if (d.get("path") if isinstance(d, dict) else str(d)) != dir_path]

        # Delete books first: if deletion fails, the directory stays configured and the
        # next scan re-imports it (self-healing). The reverse order would leave books
        # in the library that no longer have any configured source directory.
        count = await database.books.delete_by_dir(dir_path)
        await database.config.set("book_dirs", book_dirs, description="书籍目录（JSON数组）", category="general")
        return {"success": True, "message": f"已从 {dir_path} 删除 {count} 本书籍"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除目录失败: {str(e)}")
