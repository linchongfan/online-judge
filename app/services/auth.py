from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    utc_datetime,
    verify_password,
)
from app.models import AuthSession, User, UserRole, UserStatus, new_uuid, utcnow
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.mailer import mailer
from app.services.rate_limit import rate_limiter
from app.services.verification import verification_codes


def _new_session(
    db: Session, user: User, remember: bool, ip: str | None, user_agent: str | None
) -> tuple[AuthSession, str]:
    refresh_token = generate_refresh_token()
    days = get_settings().refresh_token_expire_days if remember else 1
    session = AuthSession(
        id=new_uuid(),
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=utcnow() + timedelta(days=days),
        remember=remember,
        ip_address=ip,
        user_agent=user_agent[:255] if user_agent else None,
    )
    db.add(session)
    return session, refresh_token


def token_response(user: User, session: AuthSession) -> dict:
    token, expires_in = create_access_token(user.id, session.id, user.role.value)
    return {"access_token": token, "expires_in": expires_in, "user": user}


def register(db: Session, data: RegisterRequest, ip: str | None, user_agent: str | None) -> tuple[dict, str, bool]:
    user = User(
        username=data.username,
        nickname=data.nickname,
        email=str(data.email).lower(),
        password_hash=hash_password(data.password),
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "ACCOUNT_EXISTS", "用户名或邮箱已被使用") from exc
    session, refresh_token = _new_session(db, user, True, ip, user_agent)
    db.commit()
    return token_response(user, session), refresh_token, True


def login(db: Session, data: LoginRequest, ip: str | None, user_agent: str | None) -> tuple[dict, str, bool]:
    if not rate_limiter.allow(f"login:{ip}", 15, 300):
        raise AppError(429, "TOO_MANY_ATTEMPTS", "尝试过于频繁，请稍后再试")
    account = data.account.strip().lower()
    user = db.scalar(select(User).where(or_(User.email == account, User.username == data.account.strip())))
    if user is None or not verify_password(user.password_hash, data.password):
        raise AppError(401, "INVALID_CREDENTIALS", "账号或密码错误")
    if user.status != UserStatus.ACTIVE:
        raise AppError(403, "ACCOUNT_DISABLED", "账号已被禁用")
    user.last_active_at = utcnow()
    session, refresh_token = _new_session(db, user, data.remember, ip, user_agent)
    db.commit()
    return token_response(user, session), refresh_token, data.remember


def refresh(db: Session, raw_token: str | None) -> tuple[dict, str, bool]:
    if not raw_token:
        raise AppError(401, "REFRESH_REQUIRED", "刷新凭证不存在")
    presented_hash = hash_token(raw_token)
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == presented_hash))
    if session is None:
        reused = db.scalar(select(AuthSession).where(AuthSession.previous_token_hash == presented_hash))
        if reused is not None:
            reused.revoked_at = utcnow()
            db.commit()
        raise AppError(401, "REFRESH_REUSE_DETECTED", "登录凭证已失效，请重新登录")
    if session.revoked_at is not None or utc_datetime(session.expires_at) <= utcnow():
        raise AppError(401, "SESSION_EXPIRED", "登录已过期，请重新登录")
    user = db.get(User, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise AppError(401, "ACCOUNT_UNAVAILABLE", "账号不可用")
    new_token = generate_refresh_token()
    session.previous_token_hash = session.token_hash
    session.token_hash = hash_token(new_token)
    session.rotated_at = utcnow()
    if session.remember:
        session.expires_at = utcnow() + timedelta(days=get_settings().refresh_token_expire_days)
    else:
        # "Stay logged in" was not chosen: keep the fixed short lifetime so an
        # automatic token refresh never turns it into a long-lived session.
        session.expires_at = min(utc_datetime(session.expires_at), utcnow() + timedelta(days=1))
    db.commit()
    return token_response(user, session), new_token, session.remember


def logout(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)))
    if session is not None:
        session.revoked_at = utcnow()
        db.commit()


def send_reset_code(email: str, ip: str | None) -> None:
    if not rate_limiter.allow(f"forgot:{ip}", 5, 600) or not rate_limiter.allow(f"reset-email:{email.lower()}", 1, 60):
        raise AppError(429, "RESET_RATE_LIMITED", "发送过于频繁，请稍后再试")
    # Always perform equivalent work and return a generic response to avoid account enumeration.
    code = verification_codes.issue(email)
    try:
        mailer.send_reset_code(email, code)
    except Exception as exc:
        raise AppError(503, "MAIL_UNAVAILABLE", "邮件服务暂时不可用") from exc


def reset_password(db: Session, email: str, code: str, new_password: str) -> None:
    if not verification_codes.verify(email, code):
        raise AppError(400, "INVALID_RESET_CODE", "验证码无效或已过期")
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is not None:
        user.password_hash = hash_password(new_password)
        user.last_active_at = utcnow()
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        db.commit()


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
