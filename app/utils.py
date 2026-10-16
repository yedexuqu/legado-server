"""Shared utility functions used across the application."""

import os
import re
import logging
from typing import Optional, Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)


def is_legado_client(request) -> bool:
    """Check if request is from legado client (okhttp UA, not browser).

    Args:
        request: FastAPI Request object

    Returns:
        True if request appears to be from Legado reader app
    """
    user_agent = request.headers.get("User-Agent", "")
    ua_lower = user_agent.lower()
    # Browser UAs contain common keywords
    if any(kw in ua_lower for kw in ("mozilla", "chrome", "safari", "firefox", "edge")):
        return False
    return len(user_agent) > 0


def validate_file_path(file_path: str, allowed_dirs: list) -> bool:
    """Validate file path is within allowed directories.

    Prevents path traversal attacks by resolving symlinks and checking
    the real path starts with one of the allowed directories.

    Args:
        file_path: Path to validate
        allowed_dirs: List of allowed base directories

    Returns:
        True if path is safe
    """
    try:
        real_path = os.path.realpath(file_path)
        for allowed_dir in allowed_dirs:
            allowed_real = os.path.realpath(allowed_dir)
            if real_path.startswith(allowed_real + os.sep) or real_path == allowed_real:
                return True
        return False
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    """Remove or replace dangerous characters from a filename.

    Args:
        filename: Raw filename string

    Returns:
        Sanitized filename safe for filesystem use
    """
    # Decode URL encoding
    decoded = unquote(filename)
    # Remove path separators and null bytes
    cleaned = os.path.basename(decoded)
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', cleaned)
    # Replace filesystem-unsafe characters
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', cleaned)
    # Collapse multiple underscores
    cleaned = re.sub(r'_{2,}', '_', cleaned)
    # Strip leading/trailing underscores and spaces
    cleaned = cleaned.strip('_ ')
    return cleaned or "unnamed"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text with ellipsis suffix.

    Args:
        text: Input text
        max_length: Maximum length before truncation
        suffix: String to append when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def format_file_size(size_bytes: int) -> str:
    """Format bytes into human-readable size string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string like "1.5 MB"
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def safe_int(value: Any, default: int = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Safely convert value to int with optional bounds.

    Args:
        value: Value to convert
        default: Fallback if conversion fails
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)

    Returns:
        Integer value within bounds, or default
    """
    try:
        result = int(value)
        if min_val is not None and result < min_val:
            result = min_val
        if max_val is not None and result > max_val:
            result = max_val
        return result
    except (TypeError, ValueError):
        return default
