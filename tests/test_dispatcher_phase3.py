"""Phase-3 reliability regressions for the judge outbox dispatcher."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import JudgeStatus, JudgeTask, OutboxMessage, OutboxStatus, Submission, utcnow
from app.tasks import dispatcher
from tests.test_contest_api import result_for
from tests.test_problem_api import create_published_problem

# conftest replaces dispatch_outbox with a no-op for API tests; capture the
# real implementation at import time so these tests exercise it.
REAL_DISPATCH_OUTBOX = dispatcher.dispatch_outbox


@pytest.fixture()
def dispatch_stub(monkeypatch):
    """Capture celery sends and bind the dispatcher to the test database."""
    sent: list[dict] = []

    def fake_send_task(name, kwargs=None, queue=None):
        sent.append(kwargs["payload"])
        return types.SimpleNamespace(id="fake-async-result")

    monkeypatch.setattr(dispatcher.celery_app, "send_task", fake_send_task)
    return sent


def _patch_session_local(monkeypatch, db_session):
    TestingSession = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(dispatcher, "SessionLocal", TestingSession)


def _create_submission(client, user_headers, problem_id: int, key: str) -> str:
    accepted = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={"problemId": problem_id, "language": "python", "source": "print(1)", "idempotencyKey": key},
    )
    assert accepted.status_code == 202, accepted.text
    return accepted.json()["id"]


def test_nonce_is_stable_across_duplicate_dispatch(
    client, admin_headers, user_headers, db_session, monkeypatch, dispatch_stub
):
    # conftest stubs dispatch at the service layer; exercise the real one here.
    _patch_session_local(monkeypatch, db_session)
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "nonce-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))

    assert REAL_DISPATCH_OUTBOX(task.id) is True
    assert len(dispatch_stub) == 1
    first_nonce = dispatch_stub[0]["nonce"]

    # A concurrent second dispatcher must not send again (claim is exclusive)...
    assert REAL_DISPATCH_OUTBOX(task.id) is True
    assert len(dispatch_stub) == 1
    # ...and the stored nonce must persist for the sweeper's redispatch path.
    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    assert outbox.nonce == first_nonce


def test_permanent_payload_error_fails_task_without_retry(
    client, admin_headers, user_headers, db_session, monkeypatch, dispatch_stub
):
    _patch_session_local(monkeypatch, db_session)
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "perm-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))

    def broken_build(db, task, nonce):
        raise dispatcher.PermanentDispatchError("No runnable test cases")

    monkeypatch.setattr(dispatcher, "_build_payload", broken_build)
    monkeypatch.setattr("app.services.queue_capacity.queue_capacity.release", lambda user_id: None)
    assert REAL_DISPATCH_OUTBOX(task.id) is True
    assert dispatch_stub == []

    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    stored_task = db_session.get(JudgeTask, task.id)
    submission = db_session.get(Submission, submission_id)
    assert outbox.status is OutboxStatus.FAILED
    assert stored_task.status is JudgeStatus.SE
    assert submission.status is JudgeStatus.SE
    assert submission.diagnostic == "No runnable test cases"


def test_transient_broker_error_backs_off_with_bounded_attempts(
    client, admin_headers, user_headers, db_session, monkeypatch
):
    _patch_session_local(monkeypatch, db_session)
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "transient-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))

    def failing_send(name, kwargs=None, queue=None):
        raise ConnectionError("broker down")

    monkeypatch.setattr(dispatcher.celery_app, "send_task", failing_send)
    from datetime import timedelta

    before = utcnow() - timedelta(seconds=5)
    assert REAL_DISPATCH_OUTBOX(task.id) is False

    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    assert outbox.status is OutboxStatus.PENDING
    assert outbox.attempts == 1
    assert outbox.next_attempt_at is not None and outbox.next_attempt_at >= before.replace(tzinfo=None)
    # A hot maintenance loop must not immediately redispatch: the backoff
    # keeps the row out of the claim window.
    assert REAL_DISPATCH_OUTBOX(task.id) is True
    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    assert outbox.attempts == 1

    # After the bounded attempts the task terminates instead of hot-looping:
    # every iteration but the last backs off; the last one reports the
    # terminal failure as handled.
    results = []
    for _ in range(dispatcher.MAX_TRANSIENT_ATTEMPTS - 1):
        # The dispatcher commits in its own sessions; expire first so the
        # manual backoff reset below is a real change for this session.
        db_session.expire_all()
        outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
        outbox.next_attempt_at = None
        db_session.commit()
        results.append(REAL_DISPATCH_OUTBOX(task.id))
    assert results[:-1] == [False] * (len(results) - 1)
    assert results[-1] is True
    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    stored_task = db_session.get(JudgeTask, task.id)
    assert outbox.status is OutboxStatus.FAILED
    assert stored_task.status is JudgeStatus.SE
    assert "repeatedly" in (outbox.last_error or "")


def test_duplicate_result_delivery_is_idempotent_with_stable_nonce(
    client, admin_headers, user_headers, db_session
):
    from app.tasks.results import process_judge_result

    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "dup-result-key")
    payload = result_for(db_session, submission_id, "AC")
    assert process_judge_result(payload) is True
    # Identical redelivery (at-least-once): same hash, no conflict, no change.
    assert process_judge_result(dict(payload)) is False
    db_session.expire_all()
    assert db_session.get(Submission, submission_id).status is JudgeStatus.AC


def test_stale_result_cannot_overwrite_newer_attempt(
    client, admin_headers, user_headers, db_session
):
    from app.tasks.results import SUPERSEDED_ERROR, process_judge_result

    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "stale-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    newer = JudgeTask(submission_id=submission_id, attempt=2, status=JudgeStatus.JUDGING)
    db_session.add(newer)
    db_session.commit()

    stale = result_for(db_session, submission_id, "AC")
    stale["task_id"] = task.id
    stale["attempt"] = 1
    # The late result is absorbed (old attempt superseded), never written.
    assert process_judge_result(stale) is False
    db_session.expire_all()
    assert db_session.get(JudgeTask, task.id).status is JudgeStatus.SE
    assert db_session.get(JudgeTask, task.id).last_error == SUPERSEDED_ERROR
    assert db_session.get(Submission, submission_id).status is not JudgeStatus.AC


def test_terminal_result_without_started_event_keeps_started_at(
    client, admin_headers, user_headers, db_session
):
    from app.tasks.results import process_judge_result

    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "started-at-key")
    assert process_judge_result(result_for(db_session, submission_id, "AC")) is True
    db_session.expire_all()
    assert db_session.get(Submission, submission_id).started_at is not None


def test_unreadable_test_data_is_a_permanent_error(
    client, admin_headers, user_headers, db_session, monkeypatch, dispatch_stub
):
    _patch_session_local(monkeypatch, db_session)
    monkeypatch.setattr("app.services.queue_capacity.queue_capacity.release", lambda submission_id: None)
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "corrupt-data-key")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))

    def unreadable(db, task, nonce):
        raise dispatcher.PermanentDispatchError("Test data file unreadable: OSError")

    monkeypatch.setattr(dispatcher, "_build_payload", unreadable)
    assert REAL_DISPATCH_OUTBOX(task.id) is True
    assert dispatch_stub == []
    db_session.expire_all()
    outbox = db_session.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task.id))
    assert outbox.status is OutboxStatus.FAILED
    assert db_session.get(Submission, submission_id).status is JudgeStatus.SE
