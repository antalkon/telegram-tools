import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet
from fastapi import Cookie, HTTPException, status

from app.config import get_settings

COOKIE_NAME = "tgt_token"


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


async def require_admin(tgt_token: str | None = Cookie(default=None)) -> None:
    if not verify_token(tgt_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
