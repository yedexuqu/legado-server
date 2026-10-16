"""Admin authentication module for Legado Server.

Provides session-based authentication with cookie management.
Default credentials: admin / admin123 (change in settings after first login).
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import logging
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

# Default admin credentials
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

SESSION_EXPIRY = 86400  # 24 hours
SECRET_KEY = None  # Generated on first run


class _SessionStore:
    """SQLite-backed session storage (pluggable).

    Previously sessions lived in a plain module-level dict. They now live in
    a single small SQLite table, which gives sessions one well-defined home:
    the backend is swappable via :func:`set_session_store` (tests can inject
    their own store; a future shared/multi-worker store only has to implement
    the same four methods), and expired rows are actually purged instead of
    leaking until process restart.

    The default backend is an in-memory database, so the observable behavior
    is unchanged: sessions last for the process lifetime only.
    """

    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "token TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        self._conn.commit()

    def create(self, token: str, username: str, expires_at: float) -> None:
        self._conn.execute(
            "INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
            (token, username, expires_at),
        )
        self._conn.commit()

    def get(self, token: str) -> Optional[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT username, expires_at FROM sessions WHERE token = ?", (token,)
        )
        return cursor.fetchone()

    def delete(self, token: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self._conn.commit()

    def purge_expired(self, now: float) -> int:
        """Delete sessions whose expires_at is in the past; return the count."""
        cursor = self._conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (now,)
        )
        self._conn.commit()
        return cursor.rowcount


_store = _SessionStore()


def set_session_store(store: "_SessionStore") -> None:
    """Replace the process-wide session store (tests / alternative backends)."""
    global _store
    _store = store


def _get_secret_key() -> str:
    """Get or generate secret key for session signing."""
    global SECRET_KEY
    if SECRET_KEY is None:
        SECRET_KEY = secrets.token_hex(32)
    return SECRET_KEY


def hash_password(password: str) -> str:
    """Hash password using PBKDF2 with random salt."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}:{pwd_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt, hash_hex = stored_hash.split(':', 1)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return hmac.compare_digest(pwd_hash.hex(), hash_hex)
    except Exception:
        return False


def create_session(username: str) -> str:
    """Create a new session and return the token."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    _store.create(token, username, now + SESSION_EXPIRY)
    # Opportunistic cleanup: drop rows that expired earlier, so the table
    # does not grow without bound across many logins.
    _store.purge_expired(now)
    return token


def validate_session(token: Optional[str]) -> bool:
    """Validate session token."""
    if not token:
        return False
    session = _store.get(token)
    if session is None:
        return False
    if time.time() > session["expires_at"]:
        _store.delete(token)
        return False
    return True


def destroy_session(token: Optional[str]):
    """Destroy a session."""
    if token:
        _store.delete(token)


def get_session_user(token: Optional[str]) -> Optional[str]:
    """Get username from session token."""
    if not token:
        return None
    session = _store.get(token)
    if session is not None and time.time() <= session["expires_at"]:
        return session["username"]
    return None


async def get_current_user(request: Request) -> Optional[str]:
    """Get current user from request cookie."""
    token = request.cookies.get("session_token")
    return get_session_user(token)


async def require_admin(request: Request):
    """Dependency: require admin authentication."""
    user = await get_current_user(request)
    if not user:
        # For API endpoints, return 401
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="未登录或登录已过期")
        # For page routes, redirect to login
        raise HTTPException(
            status_code=307,
            headers={"Location": f"/login?next={request.url.path}"}
        )
    return user
