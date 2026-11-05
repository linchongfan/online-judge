import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Request

from app.core.config import get_settings

_password_hasher = PasswordHasher()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    return token_urlsafe(48)


def create_access_token(user_id: int, session_id: str, role: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": session_id,
        "role": role,
        "typ": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": token_urlsafe(12),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256"), expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["sub", "sid", "exp"]})
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def request_ip(request: Request) -> str:
    # Only trust proxy headers after Nginx has replaced them with a validated client address.
    return request.client.host if request.client else "unknown"


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
