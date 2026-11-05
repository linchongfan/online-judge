from secrets import token_urlsafe

from fastapi import Request, Response

from app.core.config import get_settings
from app.core.exceptions import AppError


def set_auth_cookies(response: Response, refresh_token: str, remember: bool = True) -> None:
    settings = get_settings()
    # Non-remembered sessions use a browser-session cookie and a fixed
    # one-day server-side expiry (see app/services/auth.py).
    max_age = settings.refresh_token_expire_days * 86400 if remember else None
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=f"{settings.api_v1_prefix}/auth",
    )
    response.set_cookie(
        "oj_csrf",
        token_urlsafe(24),
        max_age=max_age,
        httponly=False,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path=f"{settings.api_v1_prefix}/auth")
    response.delete_cookie("oj_csrf", path="/")


def verify_refresh_csrf(request: Request) -> None:
    cookie = request.cookies.get("oj_csrf")
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or cookie != header:
        raise AppError(403, "CSRF_FAILED", "安全校验失败，请刷新页面后重试")
