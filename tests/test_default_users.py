from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models import User, UserRole
from scripts.ensure_default_users import ensure_default_users

ADMIN_ENV = {
    "DEFAULT_ADMIN_USERNAME": "ops_admin",
    "DEFAULT_ADMIN_PASSWORD": "Sup3rSecret",
    "DEFAULT_ADMIN_EMAIL": "ops@example.com",
}
TEST_ENV = {
    "DEFAULT_TEST_USERNAME": "ops_tester",
    "DEFAULT_TEST_PASSWORD": "Test3rPass",
    "DEFAULT_TEST_EMAIL": "test@example.com",
}
# Every environment variable that can influence account creation. An autouse
# fixture clears all of them so tests are immune to the invoking environment
# (e.g. a shell that exports CREATE_DEFAULT_USERS=1 for deployment).
ENV_KEYS = (*ADMIN_ENV, *TEST_ENV, "CREATE_DEFAULT_USERS", "CREATE_DEFAULT_TEST_USER")


@pytest.fixture(autouse=True)
def _isolate_default_user_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_no_accounts_created_without_explicit_credentials(db_session):
    assert ensure_default_users(db_session) == []
    assert db_session.scalars(select(User)).all() == []


def test_admin_account_requires_complete_explicit_credentials(db_session, monkeypatch):
    monkeypatch.setenv("CREATE_DEFAULT_USERS", "1")
    monkeypatch.setenv("DEFAULT_ADMIN_USERNAME", "ops_admin")

    with pytest.raises(SystemExit):
        ensure_default_users(db_session)
    assert db_session.scalars(select(User)).all() == []


def test_admin_account_is_created_with_explicit_credentials(db_session, monkeypatch):
    monkeypatch.setenv("CREATE_DEFAULT_USERS", "1")
    for key, value in ADMIN_ENV.items():
        monkeypatch.setenv(key, value)

    messages = ensure_default_users(db_session)

    assert "created" in messages[0]
    admin = db_session.scalar(select(User).where(User.username == "ops_admin"))
    assert admin is not None and admin.role is UserRole.ADMIN
    assert verify_password(admin.password_hash, "Sup3rSecret")
    # The test user is opt-in only.
    assert db_session.scalar(select(User).where(User.username == "ops_tester")) is None


def test_test_user_requires_explicit_opt_in(db_session, monkeypatch):
    monkeypatch.setenv("CREATE_DEFAULT_USERS", "1")
    for key, value in {**ADMIN_ENV, **TEST_ENV}.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit):
        ensure_default_users(db_session)


def test_test_user_is_created_only_with_opt_in(db_session, monkeypatch):
    monkeypatch.setenv("CREATE_DEFAULT_USERS", "1")
    for key, value in {**ADMIN_ENV, **TEST_ENV}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CREATE_DEFAULT_TEST_USER", "1")

    messages = ensure_default_users(db_session)

    assert len(messages) == 2
    test = db_session.scalar(select(User).where(User.username == "ops_tester"))
    assert test is not None and test.role is UserRole.USER
    assert verify_password(test.password_hash, "Test3rPass")


def test_account_creation_is_idempotent(db_session, monkeypatch):
    monkeypatch.setenv("CREATE_DEFAULT_USERS", "1")
    for key, value in ADMIN_ENV.items():
        monkeypatch.setenv(key, value)

    ensure_default_users(db_session)
    second_run = ensure_default_users(db_session)

    assert second_run == ["admin: account 'ops_admin' already exists, skipped"]
    assert len(db_session.scalars(select(User)).all()) == 1
