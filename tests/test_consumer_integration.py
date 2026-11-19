"""Real-Redis integration tests for the judge result consumer.

These tests exercise the actual BRPOPLPUSH transport against a live Redis
server (no mocking of the queue client). They FLUSH the judge result queues,
so they must never run against a shared or production instance:

* set ``TEST_REDIS_URL`` to a dedicated throwaway Redis server, or
* run with ``APP_ENV=test`` and a ``REDIS_URL`` that points at a test server.

If neither condition holds, the whole module is skipped.
"""

import json
import os

import pytest
import redis as redis_lib

from app.core.config import get_settings
from app.core.signing import sign_result
from app.models import Submission
from app.tasks import consumer
from app.tasks.consumer import (
    DEAD_LETTER_QUEUE,
    PROCESSING_QUEUE,
    QUEUE,
    _consume_once,
    _recover_stale_processing,
)
from tests.test_contest_api import result_for
from tests.test_problem_api import create_published_problem


def _test_redis_url() -> str | None:
    """Resolve a Redis URL that is safe to flush, or None to skip the module."""
    explicit = os.environ.get("TEST_REDIS_URL", "").strip()
    if explicit:
        return explicit
    if get_settings().app_env == "test":
        return get_settings().redis_url
    return None


@pytest.fixture(scope="module")
def redis_url():
    url = _test_redis_url()
    if url is None:
        pytest.skip(
            "Consumer integration tests need a dedicated test Redis: "
            "set TEST_REDIS_URL, or run with APP_ENV=test and a test REDIS_URL"
        )
    return url


@pytest.fixture()
def queue_client(redis_url):
    client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=5)
    try:
        client.ping()
    except redis_lib.RedisError:
        pytest.skip("Test Redis server not reachable")
    for key in (QUEUE, PROCESSING_QUEUE, DEAD_LETTER_QUEUE):
        client.delete(key)
    yield client
    for key in (QUEUE, PROCESSING_QUEUE, DEAD_LETTER_QUEUE):
        client.delete(key)


def _envelope(payload: dict) -> str:
    return json.dumps({"payload": payload, "signature": sign_result(payload)}, ensure_ascii=False)


def _create_submission(client, user_headers, problem_id: int, key: str) -> str:
    accepted = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={"problemId": problem_id, "language": "python", "source": "print(1)", "idempotencyKey": key},
    )
    assert accepted.status_code == 202, accepted.text
    return accepted.json()["id"]


def test_signed_result_is_consumed_and_acknowledged(client, admin_headers, user_headers, db_session, queue_client):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "consumer-key-1")

    queue_client.rpush(QUEUE, _envelope(result_for(db_session, submission_id, "AC")))
    # BRPOPLPUSH returns a single bytes value (redis-py, no decode_responses).
    assert _consume_once(queue_client, block_ms=1000) is True

    db_session.expire_all()
    assert db_session.get(Submission, submission_id).status == "AC"
    assert queue_client.llen(QUEUE) == 0
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    assert queue_client.llen(DEAD_LETTER_QUEUE) == 0


def test_invalid_json_is_dead_lettered_and_acked(queue_client):
    queue_client.rpush(QUEUE, b"not-json{")

    assert _consume_once(queue_client, block_ms=1000) is True

    assert queue_client.llen(QUEUE) == 0
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    dead = queue_client.lrange(DEAD_LETTER_QUEUE, 0, -1)
    assert len(dead) == 1
    assert b"invalid JSON" in dead[0]


def test_non_object_json_envelope_is_dead_lettered_not_poison_loop(queue_client):
    # A JSON array/string used to crash _handle_message with AttributeError
    # (message.get on a list) and was returned to the queue forever.
    queue_client.rpush(QUEUE, json.dumps([1, 2, 3]))

    assert _consume_once(queue_client, block_ms=1000) is True

    assert queue_client.llen(QUEUE) == 0
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    dead = queue_client.lrange(DEAD_LETTER_QUEUE, 0, -1)
    assert len(dead) == 1
    assert b"invalid envelope" in dead[0]


def test_bad_signature_is_dead_lettered_and_acked(queue_client):
    payload = {"event": "started", "task_id": "x"}
    queue_client.rpush(QUEUE, json.dumps({"payload": payload, "signature": "bad-signature"}))

    assert _consume_once(queue_client, block_ms=1000) is True

    assert queue_client.llen(QUEUE) == 0
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    assert queue_client.llen(DEAD_LETTER_QUEUE) == 1


def test_transient_failure_requeues_with_attempt_counter(
    client, admin_headers, user_headers, db_session, queue_client, monkeypatch
):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "consumer-key-2")

    calls = {"count": 0}
    real_handler = consumer.process_judge_result

    def flaky(data):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("database hiccup")
        return real_handler(data)

    monkeypatch.setattr(consumer, "process_judge_result", flaky)
    queue_client.rpush(QUEUE, _envelope(result_for(db_session, submission_id, "AC")))

    assert _consume_once(queue_client, block_ms=1000) is True
    # Message returned to the main queue with attempts=1, processing list empty.
    assert queue_client.llen(QUEUE) == 1
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    requeued = json.loads(queue_client.lindex(QUEUE, 0))
    assert requeued["attempts"] == 1

    assert _consume_once(queue_client, block_ms=1000) is True
    db_session.expire_all()
    assert db_session.get(Submission, submission_id).status == "AC"
    assert queue_client.llen(QUEUE) == 0
    assert queue_client.llen(PROCESSING_QUEUE) == 0


def test_orphaned_processing_item_is_recovered_to_main_queue(queue_client):
    queue_client.rpush(PROCESSING_QUEUE, b"orphaned-message")

    assert _recover_stale_processing(queue_client) == 1
    assert queue_client.llen(PROCESSING_QUEUE) == 0
    assert queue_client.lrange(QUEUE, 0, -1) == [b"orphaned-message"]
