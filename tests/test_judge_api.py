from sqlalchemy import select

from app.core.signing import sign_result
from app.models import JudgeTask, Submission
from app.tasks.results import process_judge_result
from tests.test_problem_api import create_published_problem


def test_signed_worker_heartbeat_and_admin_visibility(client, admin_headers):
    payload = {
        "worker_id": "windows-judge-1",
        "host": "judge-host",
        "active_tasks": 1,
        "completed": 20,
        "cpu": 25.0,
        "memory": 40.0,
    }
    invalid = client.post("/api/v1/internal/judge/heartbeat", json=payload, headers={"X-Judge-Signature": "bad"})
    assert invalid.status_code == 401
    valid = client.post(
        "/api/v1/internal/judge/heartbeat",
        json=payload,
        headers={"X-Judge-Signature": sign_result(payload)},
    )
    assert valid.status_code == 200, valid.text
    workers = client.get("/api/v1/admin/judge/workers", headers=admin_headers)
    assert workers.status_code == 200
    assert workers.json()[0]["status"] == "busy"
    stopped = client.patch(
        "/api/v1/admin/judge/workers/windows-judge-1", json={"accepting": False}, headers=admin_headers
    )
    assert stopped.status_code == 200
    assert stopped.json()["accepting"] is False


def test_sample_run_does_not_pollute_practice_statistics(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    response = client.post(
        f"/api/v1/problems/{problem_id}/sample-runs",
        headers=user_headers,
        json={
            "language": "python",
            "source": "a,b=map(int,input().split());print(a+b)",
            "idempotencyKey": "sample-run-key-1",
        },
    )
    assert response.status_code == 202, response.text
    submission_id = response.json()["id"]
    db_session.expire_all()
    submission = db_session.get(Submission, submission_id)
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    payload = {
        "task_id": task.id,
        "submission_id": submission_id,
        "status": "AC",
        "runtime_ms": 10,
        "memory_kb": 1000,
        "diagnostic": "",
        "attempt": task.attempt,
        "test_data_version_id": submission.test_data_version_id,
        "nonce": "sample-result-nonce",
    }
    assert process_judge_result(payload) is True
    stats = client.get("/api/v1/me/stats", headers=user_headers)
    assert stats.status_code == 200
    assert stats.json()["submissionCount"] == 0
    records = client.get("/api/v1/submissions", headers=user_headers)
    assert records.json()["total"] == 0
    detail = client.get(f"/api/v1/problems/{problem_id}", headers=user_headers)
    assert detail.json()["submissionCount"] == 0
    assert detail.json()["progress"] == "untouched"


def test_global_submission_switch_preserves_browsing(client, admin_headers, user_headers):
    problem_id = create_published_problem(client, admin_headers)
    settings = client.put(
        "/api/v1/admin/judge/settings",
        headers=admin_headers,
        json={"submissionsEnabled": False, "globalQueueLimit": 1000},
    )
    assert settings.status_code == 200, settings.text
    response = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={
            "problemId": problem_id,
            "language": "python",
            "source": "print(3)",
            "idempotencyKey": "paused-submit-1",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUBMISSIONS_PAUSED"
    assert client.get("/api/v1/problems").status_code == 200
