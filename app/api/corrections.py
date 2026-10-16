"""Correction API endpoints with validation and error handling."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ..deps import get_db

router = APIRouter()


class CorrectionCreate(BaseModel):
    """Create a new AI correction record."""
    book_id: int = Field(..., gt=0, description="Book database ID")
    type: str = Field(..., min_length=1, max_length=50, description="Correction type")
    line_number: Optional[int] = Field(None, ge=0)
    original_text: Optional[str] = Field(None, max_length=10000)
    new_text: Optional[str] = Field(None, max_length=10000)


@router.post("/corrections")
async def api_create_correction(correction: CorrectionCreate):
    """Create a new correction record."""
    try:
        database = await get_db()
        cursor = await database.db.execute(
            """INSERT INTO corrections
               (book_id, type, line_number, original_text, new_text)
               VALUES (?, ?, ?, ?, ?)""",
            (correction.book_id, correction.type, correction.line_number,
             correction.original_text, correction.new_text)
        )
        await database.db.commit()
        return {"success": True, "data": {"id": cursor.lastrowid}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建纠错记录失败: {str(e)}")


@router.get("/corrections/{book_id}")
async def api_get_corrections(book_id: int):
    """Get all corrections for a book."""
    if book_id < 1:
        raise HTTPException(status_code=400, detail="无效的书籍 ID")
    try:
        database = await get_db()
        cursor = await database.db.execute(
            "SELECT * FROM corrections WHERE book_id = ? ORDER BY created_at DESC",
            (book_id,)
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        corrections = [dict(zip(columns, row)) for row in rows]
        return {"success": True, "data": corrections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取纠错记录失败: {str(e)}")
