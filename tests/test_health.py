"""Smoke tests for the FastAPI app.

These exercise the app through its ASGI interface with the lifespan disabled
(httpx.ASGITransport + AsyncClient), so no database file is created and no
background scan task is started.  They guard the most basic "the server boots
and /health answers" contract without polluting runtime dependencies.

Note: httpx ASGITransport is async-only, so an AsyncClient is required.
"""
import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_200():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
