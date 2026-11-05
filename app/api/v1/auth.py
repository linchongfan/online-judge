from fastapi import APIRouter, Request, Response, status

from app.api.deps import Db
from app.core.config import get_settings
from app.core.security import request_ip
from app.schemas.auth import (
    ForgotCodeRequest,
    ForgotResetRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.services import auth
from app.services.cookies import clear_auth_cookies, set_auth_cookies, verify_refresh_csrf

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, response: Response, db: Db):
    result, refresh_token, remember = auth.register(db, data, request_ip(request), request.headers.get("User-Agent"))
    set_auth_cookies(response, refresh_token, remember)
    return result


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, response: Response, db: Db):
    result, refresh_token, remember = auth.login(db, data, request_ip(request), request.headers.get("User-Agent"))
    set_auth_cookies(response, refresh_token, remember)
    return result


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Db):
    verify_refresh_csrf(request)
    result, refresh_token, remember = auth.refresh(db, request.cookies.get(get_settings().refresh_cookie_name))
    set_auth_cookies(response, refresh_token, remember)
    return result


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response, db: Db):
    if request.cookies.get(get_settings().refresh_cookie_name):
        verify_refresh_csrf(request)
    auth.logout(db, request.cookies.get(get_settings().refresh_cookie_name))
    clear_auth_cookies(response)
    return {"message": "已退出登录"}


@router.post("/forgot/code", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def forgot_code(data: ForgotCodeRequest, request: Request):
    auth.send_reset_code(str(data.email), request_ip(request))
    return {"message": "如果账号存在，验证码将发送至对应邮箱"}


@router.post("/forgot/reset", response_model=MessageResponse)
def forgot_reset(data: ForgotResetRequest, db: Db):
    auth.reset_password(db, str(data.email), data.code, data.new_password)
    return {"message": "密码已重置，请使用新密码登录"}
