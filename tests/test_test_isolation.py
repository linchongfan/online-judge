"""Tests must never flush the application's Redis database."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from tests.redis_testing import TEST_REDIS_DB, redis_db_index, resolve_test_redis_url


def test_configured_application_redis_is_not_used_by_tests():
    configured = get_settings().redis_url
    resolved = resolve_test_redis_url()
    assert redis_db_index(resolved) != 0
    if redis_db_index(configured) == 0:
        # The default configuration uses db 0; the test resolver must move off it.
        assert resolved != configured


def test_explicit_test_url_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/9")
    assert resolve_test_redis_url() == "redis://127.0.0.1:6379/9"


def test_missing_database_path_defaults_to_test_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TEST_REDIS_URL", raising=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6379", raising=False)
    assert resolve_test_redis_url() == f"redis://127.0.0.1:6379/{TEST_REDIS_DB}"
