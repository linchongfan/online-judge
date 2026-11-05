from fastapi import APIRouter

from app.api.deps import CurrentUser, Db
from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.schemas.auth import PasswordChangeRequest, ProfileUpdateRequest, UserResponse
from app.schemas.common import MessageResponse
from app.services.auth import revoke_user_sessions
from app.services.stats import user_contest_records, user_stats

router = APIRouter()


@router.get("", response_model=UserResponse)
def get_profile(user: CurrentUser):
    return user


@router.patch("", response_model=UserResponse)
def update_profile(data: ProfileUpdateRequest, user: CurrentUser, db: Db):
    user.nickname = data.nickname.strip()
    user.school = data.school.strip()
    user.bio = data.bio.strip()
    db.commit()
    return user


@router.put("/password", response_model=MessageResponse)
def change_password(data: PasswordChangeRequest, user: CurrentUser, db: Db):
    if not verify_password(user.password_hash, data.old_password):
        raise AppError(400, "INVALID_OLD_PASSWORD", "当前密码不正确")
    if data.old_password == data.new_password:
        raise AppError(400, "PASSWORD_UNCHANGED", "新密码不能与当前密码相同")
    user.password_hash = hash_password(data.new_password)
    revoke_user_sessions(db, user.id)
    db.commit()
    return {"message": "密码已修改，请重新登录"}


@router.get("/stats")
def get_stats(user: CurrentUser, db: Db):
    return user_stats(db, user)


@router.get("/contests")
def get_contest_records(user: CurrentUser, db: Db):
    return user_contest_records(db, user.id)
