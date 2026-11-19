"""Queue capacity reservation regressions."""

from __future__ import annotations

import pytest
import redis as redis_lib
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import Language, User
from app.services import submissions as submissions_service
from app.services.queue_capacity import QueueCapacity, UserQueueFull, reserve_or_raise
from tests.test_problem_api import create_published_problem

PYTHON = Language("python")


def _redis_available() -> bool:
    try:
        return bool(
            redis_lib.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
        )
    except redis_lib.RedisError:
        return False


@pytest.fixture()
def capacity():
    queue = QueueCapacity()
    client = queue._client()
    for key in client.keys("judge:slot*"):
        client.delete(key)
    yield queue
    for key in client.keys("judge:slot*"):
        client.delete(key)


def test_global_queue_limit_is_enforced(db_session):
    with pytest.raises(AppError) as caught:
        reserve_or_raise(db_session, "sub-g-1", 1, global_limit=0, user_limit=3)
    assert caught.value.code == "GLOBAL_QUEUE_FULL"


def test_user_queue_limit_is_enforced(db_session):
    with pytest.raises(AppError) as caught:
        reserve_or_raise(db_session, "sub-u-1", 1, global_limit=10, user_limit=0)
    assert caught.value.code == "USER_QUEUE_FULL"


@pytest.mark.skipif(not _redis_available(), reason="Redis not reachable")
def test_rejected_user_reservation_does_not_steal_live_slots(capacity):
    capacity.reserve("sub-a", 999001, global_limit=10, user_limit=1)
    with pytest.raises(UserQueueFull):
        capacity.reserve("sub-b", 999001, global_limit=10, user_limit=1)
    client = capacity._client()
    assert int(client.get("judge:slots:user:999001")) == 1
    assert int(client.get("judge:slots:global")) == 1
    with pytest.raises(UserQueueFull):
        capacity.reserve("sub-c", 999001, global_limit=10, user_limit=1)
    assert int(client.get("judge:slots:user:999001")) == 1


@pytest.mark.skipif(not _redis_available(), reason="Redis not reachable")
def test_release_is_idempotent_per_submission(capacity):
    capacity.reserve("sub-x", 999002, global_limit=10, user_limit=5)
    capacity.reserve("sub-y", 999002, global_limit=10, user_limit=5)
    capacity.release("sub-x")
    capacity.release("sub-x")
    client = capacity._client()
    assert int(client.get("judge:slots:global")) == 1
    assert int(client.get("judge:slots:user:999002")) == 1
    assert client.get("judge:slot:sub:sub-x") is None
    assert client.get("judge:slot:sub:sub-y") is not None


def test_idempotency_conflict_returns_existing_submission(
    client, admin_headers, user_headers, db_session, monkeypatch
):
    TestingSession = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.tasks.results.SessionLocal", TestingSession)
    problem_id = create_published_problem(client, admin_headers)
    user = db_session.scalar(select(User).where(User.username == "student"))
    problem = submissions_service.get_problem(db_session, problem_id, user)

    first = submissions_service._create_record(db_session, user, problem, PYTHON, "print(1)", "service-dup-key")
    second = submissions_service._create_record(db_session, user, problem, PYTHON, "print(1)", "service-dup-key")
    assert second.id == first.id

    with pytest.raises(AppError) as caught:
        submissions_service._create_record(db_session, user, problem, PYTHON, "print(2)", "service-dup-key")
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
