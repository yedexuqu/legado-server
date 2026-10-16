"""Tests for the dependency-injection module (``app.deps``).

Pins the bootstrap contract (getters return None before init), the setter
injection round-trip, the ``make_state`` test factory (real DatabaseManager +
fakes), and the real ``init_deps`` -> ``get_db`` -> ``close_deps`` lifecycle.
"""
import pytest

import app.deps as deps
from app.deps import (
    FakeAIService,
    FakeScannerService,
    FakeTemplates,
    close_deps,
    get_ai_service,
    get_db,
    get_scanner_service,
    get_templates,
    init_deps,
    install_state,
    make_state,
    set_ai_service,
    set_db_manager,
    set_scanner_service,
    set_templates,
)


class _FakeDbManager:
    """Minimal DatabaseManager double: only what close_deps() touches."""

    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.fixture()
def clean_state(monkeypatch):
    """Run each test against a pristine, isolated _AppState."""
    state = deps._AppState()
    monkeypatch.setattr(deps, "_state", state)
    return state


@pytest.mark.asyncio
async def test_getters_return_none_before_init(clean_state):
    assert await get_db() is None
    assert get_templates() is None
    assert get_scanner_service() is None
    assert get_ai_service() is None


@pytest.mark.asyncio
async def test_setter_injection_roundtrip(clean_state):
    db = _FakeDbManager()
    templates = FakeTemplates()
    scanner = FakeScannerService()
    ai = FakeAIService()

    set_db_manager(db)
    set_templates(templates)
    set_scanner_service(scanner)
    set_ai_service(ai)

    assert await get_db() is db
    assert get_templates() is templates
    assert get_scanner_service() is scanner
    assert get_ai_service() is ai

    # close_deps closes the installed db manager and clears the reference.
    await close_deps()
    assert db.closed is True
    assert await get_db() is None


@pytest.mark.asyncio
async def test_close_deps_is_idempotent(tmp_path, clean_state):
    await close_deps()  # nothing installed yet: must not raise
    set_db_manager(_FakeDbManager())
    await close_deps()
    await close_deps()  # already cleared: must not raise
    assert await get_db() is None


@pytest.mark.asyncio
async def test_make_state_provides_working_database(tmp_path, clean_state):
    state = make_state(str(tmp_path / "books.db"))
    install_state(state)

    assert isinstance(get_templates(), FakeTemplates)
    assert isinstance(get_scanner_service(), FakeScannerService)
    assert isinstance(get_ai_service(), FakeAIService)

    db = await get_db()
    await db.init()
    try:
        # Real SQLite under the hood: the books table exists and is empty.
        assert await db.books.count() == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_init_deps_full_cycle(tmp_path, clean_state):
    await init_deps(str(tmp_path / "books.db"))
    try:
        db = await get_db()
        assert db is not None
        # init_deps wires the real template directory and services.
        assert get_templates() is not None
        assert get_ai_service() is not None
        assert get_scanner_service() is not None
        # The AI service was initialized against the same db manager.
        assert get_ai_service().corrector is not None
    finally:
        await close_deps()
    assert await get_db() is None


@pytest.mark.asyncio
async def test_install_state_replaces_singleton(tmp_path, clean_state):
    state = make_state(str(tmp_path / "books.db"))
    install_state(state)
    assert await get_db() is state.db_manager
    assert get_scanner_service() is state.scanner_service


@pytest.mark.asyncio
async def test_fakes_satisfy_their_contracts():
    templates = FakeTemplates()
    out = templates.TemplateResponse(request=None, name="login.html", context={"a": 1})
    assert templates.rendered == [("login.html", {"a": 1})]
    assert out == {"template": "login.html"}

    scanner = FakeScannerService()
    assert await scanner.scan_all() == 0
    assert scanner.scan_calls == 1

    ai = FakeAIService()
    assert ai.corrector is None
    await ai.init("db-marker")
    assert ai.init_called_with == "db-marker"
