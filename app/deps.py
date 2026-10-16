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


class _AppState:
    """Module-level mutable singleton.

    Wraps the previously module-scoped ``None`` globals so they live on a single
    private instance instead of as module attributes.  The public dependency
    functions (``get_db`` / ``get_templates`` / ``get_scanner_service`` /
    ``get_ai_service`` / ``init_deps`` / ``close_deps``) keep their names,
    signatures and return semantics unchanged, so every ``Depends(...)`` binding
    in the route handlers stays valid.
    """

    db_manager: DatabaseManager = None
    templates: Jinja2Templates = None
    scanner_service: ScannerService = None
    ai_service: AIService = None


_state = _AppState()


def set_db_manager(value: DatabaseManager) -> None:
    _state.db_manager = value


def set_templates(value: Jinja2Templates) -> None:
    _state.templates = value


def set_scanner_service(value: ScannerService) -> None:
    _state.scanner_service = value


def set_ai_service(value: AIService) -> None:
    _state.ai_service = value


async def init_deps(db_path: str = "data/books.db"):
    """Initialize all shared dependencies. Call once in lifespan."""
    _state.db_manager = DatabaseManager(db_path)
    await _state.db_manager.init()

    _state.templates = Jinja2Templates(directory="app/templates")

    _state.ai_service = AIService()
    await _state.ai_service.init(_state.db_manager)

    _state.scanner_service = ScannerService(_state.db_manager, _state.ai_service.corrector)


async def close_deps():
    """Cleanup. Call at end of lifespan."""
    if _state.db_manager:
        await _state.db_manager.close()
        _state.db_manager = None


async def get_db() -> DatabaseManager:
    """FastAPI dependency: returns the DatabaseManager."""
    return _state.db_manager


def get_templates() -> Jinja2Templates:
    """Returns the Jinja2 templates instance."""
    return _state.templates


def get_scanner_service() -> ScannerService:
    """Returns the ScannerService instance."""
    return _state.scanner_service


def get_ai_service() -> AIService:
    """Returns the AIService instance."""
    return _state.ai_service


# ── Test support ─────────────────────────────────────────────────────────────
# Lightweight stand-ins and a state factory so tests can boot the dependency
# graph without touching app/templates, the AI network client, or the
# production data directory.  They are part of the module's supported surface
# (imported by tests/test_deps.py), but production code never uses them.


class FakeTemplates:
    """Stand-in for Jinja2Templates: records TemplateResponse calls."""

    def __init__(self):
        self.rendered = []

    def TemplateResponse(self, request, name, context=None):
        self.rendered.append((name, context))
        return {"template": name}


class FakeScannerService:
    """Stand-in for ScannerService: scan_all() is a counted no-op."""

    def __init__(self):
        self.scan_calls = 0

    async def scan_all(self):
        self.scan_calls += 1
        return 0


class FakeAIService:
    """Stand-in for AIService: no network client; records init() calls."""

    def __init__(self):
        self.corrector = None
        self.init_called_with = None

    async def init(self, db_manager):
        self.init_called_with = db_manager


def make_state(
    db_path: str,
    *,
    templates=None,
    scanner_service=None,
    ai_service=None,
) -> _AppState:
    """Build a ready-to-install ``_AppState`` (test factory).

    The DatabaseManager is real and pointed at ``db_path`` because routes and
    services exercise it deeply (use a tmp_path file in tests).  Templates,
    scanner service and AI service default to fakes that satisfy the
    dependency contract without IO; pass explicit instances to override.
    """
    state = _AppState()
    state.db_manager = DatabaseManager(db_path)
    state.templates = templates if templates is not None else FakeTemplates()
    state.scanner_service = (
        scanner_service if scanner_service is not None else FakeScannerService()
    )
    state.ai_service = ai_service if ai_service is not None else FakeAIService()
    return state


def install_state(state: _AppState) -> None:
    """Replace the module-level singleton state (tests)."""
    global _state
    _state = state
