"""API tokens for the HTTP API and the MCP server; managed from the panel only (not with a token)."""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ApiToken, iso, utcnow
from app.security import hash_api_token, new_api_token, require_session

router = APIRouter(prefix="/settings/tokens", tags=["api tokens"], dependencies=[Depends(require_session)])


def token_out(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "scope": t.scope, "created_at": iso(t.created_at),
            "last_used_at": iso(t.last_used_at), "expires_at": iso(t.expires_at)}


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: Literal["read", "full"] = "read"
    expires_days: int | None = Field(None, ge=1, le=3650, description="Пусто — бессрочный")


@router.get("")
async def list_tokens(db: AsyncSession = Depends(get_db)):
    return [token_out(t) for t in (await db.execute(select(ApiToken).order_by(ApiToken.id.desc()))).scalars()]


@router.post("")
async def create_token(body: TokenIn, db: AsyncSession = Depends(get_db)):
    """The token itself is returned only here, once; the panel keeps just its hash."""
    raw = new_api_token()
    t = ApiToken(name=body.name.strip(), prefix=raw[:10], token_hash=hash_api_token(raw), scope=body.scope,
                 expires_at=utcnow() + timedelta(days=body.expires_days) if body.expires_days else None)
    db.add(t)
    await db.commit()
    return token_out(t) | {"token": raw}


@router.delete("/{token_id}")
async def revoke_token(token_id: int, db: AsyncSession = Depends(get_db)):
    if not (await db.execute(delete(ApiToken).where(ApiToken.id == token_id))).rowcount:
        raise HTTPException(404, "Токен не найден")
    await db.commit()
    return {"ok": True}
