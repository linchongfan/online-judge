from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import decode_access_token, utc_datetime
from app.db import get_db
from app.models import AuthSession, User, UserRole, UserStatus, utcnow

bearer_scheme = HTTPBearer(auto_error=False)
Db = Annotated[Session, Depends(get_db)]


def _user_from_credentials(credentials: HTTPAuthorizationCredentials | None, db: Session) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "AUTH_REQUIRED", "请先登录", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        session_id = str(payload["sid"])
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise AppError(401, "INVALID_TOKEN", "登录凭证无效或已过期", headers={"WWW-Authenticate": "Bearer"}) from exc
    auth_session = db.get(AuthSession, session_id)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or utc_datetime(auth_session.expires_at) <= utcnow()
        or auth_session.user_id != user_id
    ):
        raise AppError(401, "SESSION_REVOKED", "登录状态已失效，请重新登录")
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise AppError(401, "ACCOUNT_UNAVAILABLE", "账号不可用")
    return user


def get_current_user(
    db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User:
    return _user_from_credentials(credentials, db)


def get_optional_user(
    db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User | None:
    if credentials is None:
        return None
    return _user_from_credentials(credentials, db)


def get_admin_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN:
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
