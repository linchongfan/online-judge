"""Idempotently create the default admin and test accounts after deployment.

Runs automatically at the end of ``deploy/linux/deploy.sh`` (disable with
``CREATE_DEFAULT_USERS=0``). Credentials can be overridden via environment
variables before first deploy; afterwards the script only reports that the
accounts already exist. Passwords are never printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import USERNAME_PATTERN, hash_password
from app.db import SessionLocal
from app.models import User, UserRole, UserStatus


@dataclass(frozen=True)
class _AccountSpec:
    nickname: str
    role: UserRole


DEFAULTS: dict[str, _AccountSpec] = {
    "admin": _AccountSpec(nickname="管理员", role=UserRole.ADMIN),
    "test": _AccountSpec(nickname="测试用户", role=UserRole.USER),
}

DEFAULT_USERNAMES = {"admin": "admin@123321", "test": "test@123456"}
DEFAULT_PASSWORDS = {"admin": "admin@123321", "test": "test@123456"}
DEFAULT_EMAILS = {"admin": "admin@xinbaoyan.local", "test": "test@xinbaoyan.local"}

ENV_KEYS = {
    "admin": ("DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD", "DEFAULT_ADMIN_EMAIL"),
    "test": ("DEFAULT_TEST_USERNAME", "DEFAULT_TEST_PASSWORD", "DEFAULT_TEST_EMAIL"),
}


def _validate_username(username: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise SystemExit(f"Default username does not match the required pattern: {username!r}")


def _validate_password(password: str) -> None:
    if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise SystemExit("Default passwords must contain letters and digits, min 8 characters")


def ensure_default_users(
    db: Session,
    *,
    admin_username: str = DEFAULT_USERNAMES["admin"],
    admin_password: str = DEFAULT_PASSWORDS["admin"],
    admin_email: str = DEFAULT_EMAILS["admin"],
    test_username: str = DEFAULT_USERNAMES["test"],
    test_password: str = DEFAULT_PASSWORDS["test"],
    test_email: str = DEFAULT_EMAILS["test"],
) -> list[str]:
    """Create missing default accounts; return one human-readable status per account."""

    accounts = (
        ("admin", admin_username, admin_password, admin_email),
        ("test", test_username, test_password, test_email),
    )
    for _kind, username, password, _email in accounts:
        _validate_username(username)
        _validate_password(password)

    messages: list[str] = []
    for kind, username, password, email in accounts:
        if db.scalar(select(User).where(User.username == username)) is not None:
            messages.append(f"{kind}: account {username!r} already exists, skipped")
            continue
        spec = DEFAULTS[kind]
        db.add(
            User(
                username=username,
                nickname=spec.nickname,
                email=email.lower(),
                password_hash=hash_password(password),
                role=spec.role,
                status=UserStatus.ACTIVE,
            )
        )
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise SystemExit(
                f"Cannot create default {kind} account {username!r}: username or email already used"
            ) from exc
        messages.append(f"{kind}: account {username!r} created")
    db.commit()
    return messages


def main() -> None:
    overrides = {}
    for kind, keys in ENV_KEYS.items():
        username = os.environ.get(keys[0])
        password = os.environ.get(keys[1])
        email = os.environ.get(keys[2])
        if username:
            overrides[f"{kind}_username"] = username
        if password:
            overrides[f"{kind}_password"] = password
        if email:
            overrides[f"{kind}_email"] = email
    db = SessionLocal()
    try:
        for message in ensure_default_users(db, **overrides):
            print(message)
    finally:
        db.close()


if __name__ == "__main__":
    main()
