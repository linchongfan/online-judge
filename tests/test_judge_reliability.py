"""Reliability regressions for the judge pipeline, auth sessions and stats."""

from datetime import timedelta

from sqlalchemy import select

from app.models import AuthSession, JudgeStatus, JudgeTask, Submission, utcnow
from app.tasks.results import SUPERSEDED_ERROR, process_judge_result, process_judge_started
from tests.test_contest_api import contest_payload, result_for
from tests.test_problem_api import create_published_problem


def _create_submission(client, user_headers, problem_id: int, key: str) -> str:
    accepted = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={"problemId": problem_id, "language": "python", "source": "print(1)", "idempotencyKey": key},
    )
    assert accepted.status_code == 202, accepted.text
    return accepted.json()["id"]


def _started_payload(submission: Submission, task: JudgeTask, worker: str = "w-1") -> dict:
    return {
        "event": "started",
        "task_id": task.id,
        "submission_id": submission.id,
        "attempt": task.attempt,
        "test_data_version_id": submission.test_data_version_id,
        "nonce": "nonce-123456",
        "worker_id": worker,
        "lease_seconds": 600,
    }


def test_started_event_opens_execution_lease_and_result_finalizes(
    client, admin_headers, user_headers, db_session
):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "lease-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    assert task.status == JudgeStatus.PENDING
    assert task.lease_expires_at is None

    submission = db_session.get(Submission, submission_id)
    assert process_judge_started(_started_payload(submission, task)) is True

    db_session.expire_all()
    task = db_session.get(JudgeTask, task.id)
    submission = db_session.get(Submission, submission_id)
    assert task.status == JudgeStatus.JUDGING
    assert task.lease_owner == "w-1"
    assert task.lease_expires_at is not None
    assert submission.status == JudgeStatus.JUDGING

    result = result_for(db_session, submission_id, "AC")
    assert process_judge_result(result) is True
    db_session.expire_all()
    assert db_session.get(Submission, submission_id).status == JudgeStatus.AC


def test_late_result_for_superseded_attempt_terminates_old_task(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "supersede-key-1")
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))

    newer = JudgeTask(submission_id=submission_id, attempt=2)
    db_session.add(newer)
    db_session.commit()

    late = result_for(db_session, submission_id, "WA")
    assert process_judge_result(late) is False

    db_session.expire_all()
    old_task = db_session.get(JudgeTask, task.id)
    assert old_task.status == JudgeStatus.SE
    assert old_task.last_error == SUPERSEDED_ERROR
    assert old_task.finished_at is not None
    # The newer attempt owns the submission state.
    assert db_session.get(Submission, submission_id).status == JudgeStatus.PENDING


def test_rejudge_rejects_when_latest_attempt_is_active(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "rejudge-key-1")
    first = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    assert process_judge_result(result_for(db_session, submission_id, "WA")) is True

    active = JudgeTask(submission_id=submission_id, attempt=2, status=JudgeStatus.JUDGING)
    db_session.add(active)
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/judge/tasks/{first.id}/rejudge",
        json={"reason": "重测旧任务"},
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUBMISSION_STILL_ACTIVE"


def test_batch_rejudge_deduplicates_by_submission(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    submission_id = _create_submission(client, user_headers, problem_id, "batch-key-1")
    first = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    assert process_judge_result(result_for(db_session, submission_id, "WA")) is True
    second = JudgeTask(submission_id=submission_id, attempt=2, status=JudgeStatus.SE, last_error="lost")
    db_session.add(second)
    db_session.commit()

    response = client.post(
        "/api/v1/admin/judge/tasks/batch-rejudge",
        json={"taskIds": [first.id, second.id], "reason": "批量重测"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    latest = db_session.scalar(
        select(JudgeTask)
        .where(JudgeTask.submission_id == submission_id)
        .order_by(JudgeTask.attempt.desc())
        .limit(1)
    )
    assert latest.attempt == 3


def test_refresh_keeps_short_session_when_remember_is_false(client, admin_user, db_session):
    response = client.post(
        "/api/v1/auth/login",
        json={"account": "admin", "password": "Admin12345", "remember": False},
    )
    assert response.status_code == 200, response.text
    # Non-remembered sessions must not get a long-lived cookie.
    assert "max-age" not in response.headers["set-cookie"].lower()

    session = db_session.scalar(
        select(AuthSession).where(AuthSession.user_id == admin_user.id).order_by(AuthSession.created_at.desc())
    )
    assert session is not None and session.remember is False
    before = session.expires_at

    csrf = response.cookies.get("oj_csrf")
    # The TestClient cookie jar already persisted the login cookies.
    refresh = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert refresh.status_code == 200, refresh.text
    db_session.expire_all()
    assert abs((session.expires_at - before).total_seconds()) < 2


def test_contest_edit_replaces_problem_rows_without_duplicate_key(client, admin_headers):
    problem_id = create_published_problem(client, admin_headers)
    created = client.post("/api/v1/admin/contests", json=contest_payload(problem_id), headers=admin_headers)
    assert created.status_code == 201, created.text
    contest_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/admin/contests/{contest_id}", json=contest_payload(problem_id), headers=admin_headers
    )
    assert updated.status_code == 200, updated.text
    assert [(item["problemId"], item["label"]) for item in updated.json()["problems"]] == [(problem_id, "A")]


def test_contest_accepted_submission_is_excluded_from_practice_stats(
    client, admin_headers, user_headers, db_session
):
    problem_id = create_published_problem(client, admin_headers)
    created = client.post("/api/v1/admin/contests", json=contest_payload(problem_id), headers=admin_headers)
    assert created.status_code == 201, created.text
    contest_id = created.json()["id"]
    assert client.post(f"/api/v1/admin/contests/{contest_id}/publish", headers=admin_headers).status_code == 200
    assert client.put(f"/api/v1/contests/{contest_id}/registration", headers=user_headers).status_code == 200

    from app.models import Contest

    contest = db_session.get(Contest, contest_id)
    contest.start_time = utcnow() - timedelta(minutes=10)
    contest.end_time = utcnow() + timedelta(hours=2)
    db_session.commit()

    accepted = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={
            "problemId": problem_id,
            "contestId": contest_id,
            "language": "python",
            "source": "print(3)",
            "idempotencyKey": "contest-ac-key-1",
        },
    )
    assert accepted.status_code == 202, accepted.text
    submission_id = accepted.json()["id"]
    assert process_judge_result(result_for(db_session, submission_id, "AC")) is True

    stats = client.get("/api/v1/me/stats", headers=user_headers)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["solvedCount"] == 0
    for group in body["difficultyProgress"]:
        assert group["solved"] == 0
