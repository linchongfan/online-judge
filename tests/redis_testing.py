"""Resolve a Redis URL that is safe for tests to flush.

Tests must never clear keys in the application's own Redis database. The
resolved URL is either an explicit ``TEST_REDIS_URL`` (CI / dedicated service)
or a derived logical database (15) of the configured server, so local runs
cannot touch the application's db 0.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings

TEST_REDIS_DB = 15


def redis_db_index(url: str) -> int | None:
    path = urlsplit(url).path.strip("/")
    if not path:
        return None
    try:
        return int(path)
    except ValueError:
        return None


def resolve_test_redis_url() -> str:
    explicit = os.environ.get("TEST_REDIS_URL", "").strip()
    if explicit:
        return explicit
    configured = get_settings().redis_url
    if redis_db_index(configured) == TEST_REDIS_DB:
        # Already pointed at the test database (e.g. APP_ENV=test in CI).
        return configured
    parts = urlsplit(configured)
    return urlunsplit((parts.scheme, parts.netloc, f"/{TEST_REDIS_DB}", "", ""))
