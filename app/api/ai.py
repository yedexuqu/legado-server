"""AI API endpoints with validation and error handling."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()


class AIDetectRequest(BaseModel):
    """AI detection request."""
    text_sample: str = Field(..., min_length=10, max_length=50000, description="Text sample for AI analysis")
    book_id: Optional[int] = Field(None, gt=0)


@router.post("/ai/detect")
async def api_ai_detect(request: AIDetectRequest):
    """Detect chapters using AI."""
    try:
        from ..deps import get_ai_service
        ai = get_ai_service()
        if not ai.api_key:
            raise HTTPException(status_code=400, detail="AI 未配置，请先设置 API Key")
        result = await ai.detect_chapters(request.text_sample)
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 章节检测失败: {str(e)}")


@router.post("/ai/fix-ocr")
async def api_ai_fix_ocr(request: AIDetectRequest):
    """Fix OCR errors using AI."""
    try:
        from ..deps import get_ai_service
        ai = get_ai_service()
        if not ai.api_key:
            raise HTTPException(status_code=400, detail="AI 未配置，请先设置 API Key")
        result = await ai.fix_ocr_errors(request.text_sample)
        return {"success": True, "data": {"fixed_text": result}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI OCR 修复失败: {str(e)}")


@router.post("/ai/test")
async def test_ai_connection():
    """Test AI connection and API key validity."""
    try:
        from ..deps import get_db
        import httpx

        database = await get_db()
        api_base = await database.config.get("ai_api_base", "https://api.openai.com/v1")
        api_key = await database.config.get("ai_api_key", "")

        if not api_key:
            return {"success": False, "message": "API Key 未配置"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{api_base}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if response.status_code == 200:
                return {"success": True, "message": "连接成功"}
            elif response.status_code == 401:
                return {"success": False, "message": "API Key 无效"}
            else:
                return {"success": False, "message": f"连接失败，状态码: {response.status_code}"}
    except httpx.TimeoutException:
        return {"success": False, "message": "连接超时，请检查网络或 API 地址"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}
