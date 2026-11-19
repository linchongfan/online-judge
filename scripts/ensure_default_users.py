"""Idempotently create initial accounts after deployment (explicit opt-in).

There are intentionally NO built-in default credentials. A fresh production
deploy creates no accounts at all; use the interactive ``scripts/create_admin.py``
instead, or opt in here by providing every credential via environment variables:

* ``CREATE_DEFAULT_USERS=1`` plus ``DEFAULT_ADMIN_USERNAME`` /
  ``DEFAULT_ADMIN_PASSWORD`` / ``DEFAULT_ADMIN_EMAIL`` creates the admin.
* ``CREATE_DEFAULT_TEST_USER=1`` plus ``DEFAULT_TEST_USERNAME`` /
  ``DEFAULT_TEST_PASSWORD`` / ``DEFAULT_TEST_EMAIL`` additionally creates the
  test user. Never enable this on a public deployment.

The script is idempotent: existing accounts are reported and left untouched.
Passwords are never printed.
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


SPECS: dict[str, _AccountSpec] = {
    "admin": _AccountSpec(nickname="管理员", role=UserRole.ADMIN),
    "test": _AccountSpec(nickname="测试用户", role=UserRole.USER),
}

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


def _resolve_accounts() -> list[tuple[str, str, str, str]]:
    """Return (kind, username, password, email) tuples for explicitly configured accounts."""
    if os.environ.get("CREATE_DEFAULT_USERS") != "1":
        # Default: create nothing. Accounts are provisioned interactively via
        # scripts/create_admin.py unless the operator explicitly opts in here.
        return []
    accounts: list[tuple[str, str, str, str]] = []
    for kind, keys in ENV_KEYS.items():
        username, password, email = (os.environ.get(key, "").strip() for key in keys)
        if kind == "test" and os.environ.get("CREATE_DEFAULT_TEST_USER") != "1":
            if username or password or email:
                raise SystemExit("Test user requested without CREATE_DEFAULT_TEST_USER=1; refusing to create it.")
            continue
        missing = [key for key, value in zip(keys, (username, password, email), strict=True) if not value]
        if missing:
            raise SystemExit(
                f"Cannot create the default {kind!r} account: missing environment variables {', '.join(missing)}. "
                "Provide all of them, or use scripts/create_admin.py for an interactive admin setup."
            )
        accounts.append((kind, username, password, email))
    return accounts


def ensure_default_users(db: Session) -> list[str]:
    """Create the configured default accounts; return one status message each."""
    accounts = _resolve_accounts()
    for _kind, username, password, _email in accounts:
        _validate_username(username)
        _validate_password(password)

    messages: list[str] = []
    for kind, username, password, email in accounts:
        if db.scalar(select(User).where(User.username == username)) is not None:
            messages.append(f"{kind}: account {username!r} already exists, skipped")
            continue
        spec = SPECS[kind]
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
    db = SessionLocal()
    try:
        for message in ensure_default_users(db):
            print(message)
    finally:
        db.close()


if __name__ == "__main__":
    main()
