"""Admin authentication module for Legado Server.

Provides session-based authentication with cookie management.
Default credentials: admin / admin123 (change in settings after first login).
"""
import hashlib
import hmac
import os
import secrets
import time
import logging
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

# Session storage (in-memory)
_sessions = {}  # token -> {user, created_at, expires_at}
SESSION_EXPIRY = 86400  # 24 hours
SECRET_KEY = None  # Generated on first run

# Default admin credentials
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"


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
    _sessions[token] = {
        "user": username,
        "created_at": time.time(),
        "expires_at": time.time() + SESSION_EXPIRY
    }
    return token


def validate_session(token: Optional[str]) -> bool:
    """Validate session token."""
    if not token or token not in _sessions:
        return False
    session = _sessions[token]
    if time.time() > session["expires_at"]:
        del _sessions[token]
        return False
    return True


def destroy_session(token: Optional[str]):
    """Destroy a session."""
    if token and token in _sessions:
        del _sessions[token]


def get_session_user(token: Optional[str]) -> Optional[str]:
    """Get username from session token."""
    if token and token in _sessions:
        session = _sessions[token]
        if time.time() <= session["expires_at"]:
            return session["user"]
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
