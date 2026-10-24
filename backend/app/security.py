import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import get_settings

COOKIE_NAME = "tgt_token"
TOKEN_PREFIX = "tgt_"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
LAST_USED_EVERY = timedelta(minutes=1)  # don't write to the DB on every request

# Both schemes are optional on their own; require_admin accepts either. Declared as security
# dependencies so the OpenAPI schema (and Scalar) know how to authorize.
cookie_auth = APIKeyCookie(name=COOKIE_NAME, auto_error=False, scheme_name="session",
                           description="Сессия панели: cookie ставится после входа по паролю")
bearer_auth = HTTPBearer(auto_error=False, scheme_name="token", bearerFormat="tgt_…",
                         description="API-токен из «Настройки → API-токены»")


def _fernet() -> Fernet:
    digest = hashlib.sha256(("fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def check_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), get_settings().admin_password.encode())


def issue_token() -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": "admin", "iat": now, "exp": now + timedelta(hours=s.token_ttl_hours)},
        s.secret_key,
        algorithm="HS256",
    )


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


@dataclass(frozen=True)
class Principal:
    kind: Literal["session", "token"]
    scope: Literal["read", "full"]
    token_id: int | None = None


SESSION = Principal("session", "full")


def new_api_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def token_principal(raw: str | None) -> Principal | None:
    """The API token's principal, or None when it is unknown or expired."""
    from app.db import SessionLocal
    from app.models import ApiToken, utcnow

    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    async with SessionLocal() as db:
        tok = (await db.execute(select(ApiToken).where(ApiToken.token_hash == hash_api_token(raw)))).scalar()
        if tok is None:
            return None
        now = utcnow()
        aware = lambda d: d if d is None or d.tzinfo else d.replace(tzinfo=UTC)  # noqa: E731  (SQLite drops tzinfo)
        if tok.expires_at and aware(tok.expires_at) <= now:
            return None
        if tok.last_used_at is None or now - aware(tok.last_used_at) > LAST_USED_EVERY:
            tok.last_used_at = now
            await db.commit()
        return Principal("token", "full" if tok.scope == "full" else "read", tok.id)


async def require_admin(
    request: Request,
    session: str | None = Depends(cookie_auth),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
) -> Principal:
    """The panel session cookie or an API token. Read-only tokens may only make GET requests."""
    if verify_token(session):
        principal = SESSION
    elif bearer and (principal := await token_principal(bearer.credentials)):
        if principal.scope == "read" and request.method not in READ_METHODS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Токен только для чтения")
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    request.state.principal = principal
    return principal


async def require_session(session: str | None = Depends(cookie_auth)) -> Principal:
    """Panel session only: an API token can't create or revoke tokens."""
    if not verify_token(session):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход в панель по паролю")
    return SESSION
