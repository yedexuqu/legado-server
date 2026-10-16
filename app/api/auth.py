"""Authentication API endpoints."""
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional

from ..deps import get_db, get_templates
from ..auth import (
    hash_password, verify_password, create_session, destroy_session,
    get_current_user, require_admin, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=6, max_length=100)


async def _ensure_admin_credentials():
    """Ensure admin credentials exist in config table."""
    db = await get_db()
    
    # Check if admin_user exists
    admin_user = await db.get_config("admin_user")
    if not admin_user:
        await db.set_config("admin_user", DEFAULT_ADMIN_USER, "管理员用户名", "auth")
        await db.set_config("admin_pass_hash", hash_password(DEFAULT_ADMIN_PASS), "管理员密码哈希", "auth")
        return DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS
    
    admin_pass_hash = await db.get_config("admin_pass_hash")
    if not admin_pass_hash:
        # Reset if hash is missing
        await db.set_config("admin_pass_hash", hash_password(DEFAULT_ADMIN_PASS), "管理员密码哈希", "auth")
        return admin_user, DEFAULT_ADMIN_PASS
    
    return admin_user, None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/settings"):
    """Render login page."""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url=next, status_code=302)
    
    templates = get_templates()
    return templates.TemplateResponse(request, "login.html", {
        "request": request,
        "next_url": next,
        "error": None
    })


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/settings")
):
    """Handle login form submission."""
    admin_user, _ = await _ensure_admin_credentials()
    db = await get_db()
    admin_pass_hash = await db.get_config("admin_pass_hash")
    
    if username != admin_user or not verify_password(password, admin_pass_hash):
        templates = get_templates()
        return templates.TemplateResponse(request, "login.html", {
            "request": request,
            "next_url": next,
            "error": "用户名或密码错误"
        })
    
    # Create session and set cookie
    token = create_session(username)
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400  # 24 hours
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    token = request.cookies.get("session_token")
    destroy_session(token)
    
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="session_token")
    return response


@router.get("/api/auth/status")
async def auth_status(request: Request):
    """Check authentication status."""
    user = await get_current_user(request)
    return {"authenticated": bool(user), "user": user}


@router.post("/api/auth/change-password")
async def change_password(request: Request, req: ChangePasswordRequest):
    """Change admin password."""
    user = await require_admin(request)
    
    db = await get_db()
    admin_user = await db.get_config("admin_user")
    admin_pass_hash = await db.get_config("admin_pass_hash")
    
    if not verify_password(req.old_password, admin_pass_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    
    new_hash = hash_password(req.new_password)
    await db.set_config("admin_pass_hash", new_hash, "管理员密码哈希", "auth")
    
    return {"success": True, "message": "密码已更新"}
