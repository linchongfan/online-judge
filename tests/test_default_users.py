from __future__ import annotations

from sqlalchemy import select

from app.core.security import verify_password
from app.models import User, UserRole
from scripts.ensure_default_users import ensure_default_users


def test_default_accounts_are_created_with_expected_roles(db_session):
    messages = ensure_default_users(db_session)

    assert "created" in messages[0]
    assert "created" in messages[1]
    admin = db_session.scalar(select(User).where(User.username == "admin@123321"))
    test = db_session.scalar(select(User).where(User.username == "test@123456"))
    assert admin is not None and admin.role is UserRole.ADMIN
    assert test is not None and test.role is UserRole.USER
    assert verify_password(admin.password_hash, "admin@123321")
    assert verify_password(test.password_hash, "test@123456")


def test_default_account_creation_is_idempotent(db_session):
    ensure_default_users(db_session)
    second_run = ensure_default_users(db_session)

    assert second_run == [
        "admin: account 'admin@123321' already exists, skipped",
        "test: account 'test@123456' already exists, skipped",
    ]
    assert len(db_session.scalars(select(User)).all()) == 2
