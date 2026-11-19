"""Alembic migration chain test against a real throwaway database.

``alembic/env.py`` prefers ``ALEMBIC_DATABASE_URL``, so this exercises the
actual revision chain instead of whatever database the app settings point at.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def _alembic_config(database_url: str) -> Config:
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_chain_creates_outbox_delivery_fields(tmp_path, monkeypatch) -> None:
    database = tmp_path / "migrations.db"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    command.upgrade(_alembic_config(url), "head")

    connection = sqlite3.connect(database)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(outbox_message)")}
    connection.close()
    assert "nonce" in columns, "outbox nonce column missing after upgrade"
    assert "next_attempt_at" in columns, "outbox backoff column missing after upgrade"

    command.downgrade(_alembic_config(url), "base")
