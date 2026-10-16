"""Centralized dependency injection for the application.

Usage in main.py lifespan:
    from .deps import init_deps
    await init_deps()

Usage in route handlers:
    from .deps import get_db, get_templates, get_scanner_service, get_ai_service
"""

from fastapi.templating import Jinja2Templates

from .database import DatabaseManager
from .services.scanner import ScannerService
from .services.ai import AIService

# ── Singleton instances ──
_db_manager: DatabaseManager = None
_templates: Jinja2Templates = None
_scanner_service: ScannerService = None
_ai_service: AIService = None


async def init_deps(db_path: str = "data/books.db"):
    """Initialize all shared dependencies. Call once in lifespan."""
    global _db_manager, _templates, _ai_service, _scanner_service

    _db_manager = DatabaseManager(db_path)
    await _db_manager.init()

    _templates = Jinja2Templates(directory="app/templates")

    _ai_service = AIService()
    await _ai_service.init(_db_manager)

    _scanner_service = ScannerService(_db_manager, _ai_service.corrector)


async def close_deps():
    """Cleanup. Call at end of lifespan."""
    global _db_manager
    if _db_manager:
        await _db_manager.close()
        _db_manager = None


async def get_db() -> DatabaseManager:
    """FastAPI dependency: returns the DatabaseManager."""
    return _db_manager


def get_templates() -> Jinja2Templates:
    """Returns the Jinja2 templates instance."""
    return _templates


def get_scanner_service() -> ScannerService:
    """Returns the ScannerService instance."""
    return _scanner_service


def get_ai_service() -> AIService:
    """Returns the AIService instance."""
    return _ai_service
