from datetime import timedelta

from app.models import Contest, JudgeTask, Submission, utcnow
from app.tasks.results import process_judge_result
from tests.test_problem_api import create_published_problem


def contest_payload(problem_id):
    now = utcnow()
    return {
        "title": "新生程序设计赛",
        "subtitle": "ACM 测试赛",
        "description": "测试竞赛流程",
        "organizer": "新保研",
        "startTime": (now + timedelta(days=1)).isoformat(),
        "endTime": (now + timedelta(days=1, hours=2)).isoformat(),
        "accent": "blue",
        "problems": [{"problemId": problem_id, "label": "A", "position": 1}],
    }


def result_for(db, submission_id, status):
    submission = db.get(Submission, submission_id)
    task = db.scalar(__import__("sqlalchemy").select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    return {
        "task_id": task.id,
        "submission_id": submission.id,
        "status": status,
        "runtime_ms": 12,
        "memory_kb": 1024,
        "diagnostic": "",
        "attempt": task.attempt,
        "test_data_version_id": submission.test_data_version_id,
        "nonce": "test-nonce-123",
    }


def test_contest_registration_time_and_acm_ranking(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    created = client.post("/api/v1/admin/contests", json=contest_payload(problem_id), headers=admin_headers)
    assert created.status_code == 201, created.text
    contest_id = created.json()["id"]
    assert client.post(f"/api/v1/admin/contests/{contest_id}/publish", headers=admin_headers).status_code == 200
    upcoming = client.get(f"/api/v1/contests/{contest_id}", headers=user_headers)
    assert upcoming.status_code == 200
    assert upcoming.json()["problems"] == []
    assert client.get(f"/api/v1/problems/{problem_id}?contest_id={contest_id}", headers=user_headers).status_code == 403
    registered = client.put(f"/api/v1/contests/{contest_id}/registration", headers=user_headers)
    assert registered.status_code == 200, registered.text

    contest = db_session.get(Contest, contest_id)
    contest.start_time = utcnow() - timedelta(minutes=10)
    contest.end_time = utcnow() + timedelta(hours=2)
    db_session.commit()

    wrong = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={
            "problemId": problem_id,
            "contestId": contest_id,
            "language": "python",
            "source": "print(0)",
            "idempotencyKey": "contest-wrong-1",
        },
    )
    assert wrong.status_code == 202, wrong.text
    db_session.expire_all()
    assert process_judge_result(result_for(db_session, wrong.json()["id"], "WA")) is True
    db_session.expire_all()
    accepted = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={
            "problemId": problem_id,
            "contestId": contest_id,
            "language": "python",
            "source": "a,b=map(int,input().split());print(a+b)",
            "idempotencyKey": "contest-accepted-1",
        },
    )
    assert accepted.status_code == 202, accepted.text
    db_session.expire_all()
    payload = result_for(db_session, accepted.json()["id"], "AC")
    assert process_judge_result(payload) is True
    assert process_judge_result(payload) is False

    detail = client.get(f"/api/v1/submissions/{accepted.json()['id']}", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "AC"
    board = client.get(f"/api/v1/contests/{contest_id}/ranking")
    assert board.status_code == 200, board.text
    entry = board.json()["entries"][0]
    assert entry["solved"] == 1
    assert entry["penaltySeconds"] >= 1200
    assert entry["results"]["A"]["status"] == "AC"
    mine = client.get(f"/api/v1/contests/{contest_id}/my-result", headers=user_headers)
    assert mine.status_code == 200
    assert mine.json()["rank"] == 1


def test_contest_submission_requires_registration_and_server_time(client, admin_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    created = client.post("/api/v1/admin/contests", json=contest_payload(problem_id), headers=admin_headers)
    contest_id = created.json()["id"]
    client.post(f"/api/v1/admin/contests/{contest_id}/publish", headers=admin_headers)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "contestant", "nickname": "选手", "email": "contestant@example.com", "password": "Password1"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['accessToken']}"}
    contest = db_session.get(Contest, contest_id)
    contest.start_time = utcnow() - timedelta(minutes=1)
    db_session.commit()
    response = client.post(
        "/api/v1/submissions",
        headers=headers,
        json={
            "problemId": problem_id,
            "contestId": contest_id,
            "language": "python",
            "source": "print(3)",
            "idempotencyKey": "not-registered-1",
        },
    )
    assert response.status_code == 403
