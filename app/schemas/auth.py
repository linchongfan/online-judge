from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.security import USERNAME_PATTERN
from app.models import UserRole
from app.schemas.common import ApiSchema


class PasswordStrengthMixin:
    @field_validator("password", "new_password", check_fields=False)
    @classmethod
    def password_has_character_variety(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("密码必须同时包含字母和数字")
        return value


class UserResponse(ApiSchema):
    id: int
    username: str
    nickname: str
    email: EmailStr
    school: str
    bio: str
    role: UserRole
    joined_at: datetime


class RegisterRequest(PasswordStrengthMixin, ApiSchema):
    username: str = Field(min_length=3, max_length=32)
    nickname: str = Field(min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("用户名只能包含字母、数字、下划线和 @ 符号")
        return value

    @field_validator("nickname")
    @classmethod
    def strip_nickname(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("昵称不能为空")
        return value


class LoginRequest(ApiSchema):
    account: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class TokenResponse(ApiSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class ForgotCodeRequest(ApiSchema):
    email: EmailStr


class ForgotResetRequest(PasswordStrengthMixin, ApiSchema):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(ApiSchema):
    nickname: str = Field(min_length=1, max_length=50)
    school: str = Field(default="", max_length=100)
    bio: str = Field(default="", max_length=500)


class PasswordChangeRequest(PasswordStrengthMixin, ApiSchema):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
