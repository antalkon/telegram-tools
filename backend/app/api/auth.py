from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.security import COOKIE_NAME, Principal, check_password, issue_token, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response):
    if not check_password(body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный пароль")
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        issue_token(),
        max_age=s.token_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(principal: Principal = Depends(require_admin)):
    """Who is calling: the panel session or an API token (and its scope)."""
    return {"user": "admin", "via": principal.kind, "scope": principal.scope}
