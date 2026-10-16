"""API router registry — includes all sub-routers under /api prefix."""

from fastapi import APIRouter

from .books import router as books_router
from .categories import router as categories_router
from .tags import router as tags_router
from .config import router as config_router
from .corrections import router as corrections_router
from .ai import router as ai_router

api_router = APIRouter()

api_router.include_router(books_router)
api_router.include_router(categories_router)
api_router.include_router(tags_router)
api_router.include_router(config_router)
api_router.include_router(corrections_router)
api_router.include_router(ai_router)
