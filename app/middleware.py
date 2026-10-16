"""Unified error handling middleware for FastAPI."""

import logging
import traceback
from datetime import datetime
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger('legado-server.middleware')


class ErrorHandlerMiddleware:
    """Catches unhandled exceptions and returns standardized JSON errors."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        try:
            response = await self.app(scope, receive, send)
            return response
        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(f"Validation error: {e}", extra={"path": scope.get("path")})
            return JSONResponse(
                status_code=422,
                content={"success": False, "message": f"参数错误: {str(e)}"}
            )
        except Exception as e:
            logger.error(
                f"Unhandled exception: {e}",
                extra={"path": scope.get("path"), "method": scope.get("method")},
                exc_info=True
            )
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "服务器内部错误，请稍后重试"}
            )


class RequestLoggingMiddleware:
    """Logs request method, path, status code, and duration."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = datetime.utcnow()
        path = scope.get("path", "")
        method = scope.get("method", "")

        status_code = 0

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (datetime.utcnow() - start).total_seconds() * 1000
            if status_code >= 500:
                logger.error(f"{method} {path} -> {status_code} ({duration_ms:.0f}ms)")
            elif status_code >= 400:
                logger.warning(f"{method} {path} -> {status_code} ({duration_ms:.0f}ms)")
            elif path != "/health":
                logger.info(f"{method} {path} -> {status_code} ({duration_ms:.0f}ms)")
