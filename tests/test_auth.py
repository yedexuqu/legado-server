"""Tests for the SQLite-backed session store in ``app.auth``.

The public session API (create_session / validate_session / destroy_session /
get_session_user) kept its signatures and semantics when storage moved from a
plain dict to a pluggable SQLite store (``_SessionStore``).  These tests pin
that contract, including expiry handling and backend swappability.
"""
import sqlite3
import time

import pytest

import app.auth
from app.auth import (
    SESSION_EXPIRY,
    _SessionStore,
    create_session,
    destroy_session,
    get_session_user,
    set_session_store,
    validate_session,
)


@pytest.fixture()
def fresh_store(monkeypatch):
    """Isolate every test with its own in-memory session store."""
    store = _SessionStore()
    monkeypatch.setattr(app.auth, "_store", store)
    return store


def _backdate(store, token, delta_seconds):
    """Force a session to expire ``delta_seconds`` ago."""
    store._conn.execute(
        "UPDATE sessions SET expires_at = ? WHERE token = ?",
        (time.time() - delta_seconds, token),
    )
    store._conn.commit()


def test_session_lifecycle(fresh_store):
    token = create_session("admin")
    assert token
    assert validate_session(token) is True
    assert get_session_user(token) == "admin"

    destroy_session(token)
    assert validate_session(token) is False
    assert get_session_user(token) is None
    destroy_session(token)  # idempotent, must not raise


def test_invalid_tokens_are_rejected(fresh_store):
    assert validate_session(None) is False
    assert validate_session("") is False
    assert validate_session("bogus-token") is False
    assert get_session_user(None) is None
    assert get_session_user("bogus-token") is None


def test_expired_session_is_rejected_and_purged(fresh_store):
    token = create_session("admin")
    _backdate(fresh_store, token, 1)

    assert validate_session(token) is False
    # validate_session deletes the expired row (parity with the dict impl).
    assert fresh_store.get(token) is None
    assert get_session_user(token) is None


def test_expired_session_not_deleted_by_get(fresh_store):
    # get_session_user never deletes (parity with the old dict behavior);
    # purging happens on the next create_session / purge_expired call.
    token = create_session("admin")
    _backdate(fresh_store, token, 1)

    assert get_session_user(token) is None
    assert fresh_store.get(token) is not None


def test_purge_expired_removes_only_stale_rows(fresh_store):
    stale = create_session("old")
    live = create_session("admin")
    _backdate(fresh_store, stale, 10)

    removed = fresh_store.purge_expired(time.time())
    assert removed == 1
    assert fresh_store.get(stale) is None
    assert fresh_store.get(live) is not None
    assert get_session_user(live) == "admin"


def test_set_session_store_swaps_backend(monkeypatch):
    first = _SessionStore()
    monkeypatch.setattr(app.auth, "_store", first)
    token = create_session("admin")
    assert validate_session(token) is True

    replacement = _SessionStore()
    set_session_store(replacement)
    # The new store knows nothing about the old token.
    assert validate_session(token) is False
    new_token = create_session("ops")
    assert get_session_user(new_token) == "ops"
    # monkeypatch teardown restores the original module store.


def test_sessions_are_stored_in_sqlite_on_disk(tmp_path, monkeypatch):
    """A file-backed store proves the backend really is SQLite: two store
    instances over the same file share sessions."""
    path = str(tmp_path / "sessions.db")
    store_a = _SessionStore(path)
    monkeypatch.setattr(app.auth, "_store", store_a)

    token = create_session("admin")

    store_b = _SessionStore(path)
    row = store_b.get(token)
    assert row is not None
    assert row["username"] == "admin"

    # And it really is a SQLite database with the expected table.
    raw = sqlite3.connect(path)
    try:
        tables = {
            r[0]
            for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "sessions" in tables
    finally:
        raw.close()


def test_session_expiry_constant():
    """Pin the documented 24-hour expiry contract."""
    assert SESSION_EXPIRY == 86400
