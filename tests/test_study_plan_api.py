from sqlalchemy import select

from app.models import JudgeTask, Submission
from app.tasks.results import process_judge_result
from tests.test_problem_api import archive_bytes, problem_payload


def create_problem(client, admin_headers, title: str) -> int:
    created = client.post("/api/v1/admin/problems", json=problem_payload(title), headers=admin_headers)
    assert created.status_code == 201, created.text
    problem_id = created.json()["id"]
    uploaded = client.post(
        f"/api/v1/admin/problems/{problem_id}/test-data",
        files={"upload": ("data.zip", archive_bytes(), "application/zip")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    published = client.post(f"/api/v1/admin/problems/{problem_id}/publish", headers=admin_headers)
    assert published.status_code == 200, published.text
    return problem_id


def plan_payload(problem_ids: list[int], title: str = "C 语言入门计划") -> dict:
    return {
        "title": title,
        "subtitle": "从第一行代码开始",
        "description": "按章节顺序完成，遇到卡点回到对应知识点复习。",
        "accent": "green",
        "problems": [
            {
                "problemId": problem_id,
                "position": index + 1,
                "groupName": "基础" if index < 1 else "进阶",
            }
            for index, problem_id in enumerate(problem_ids)
        ],
    }


def create_plan(
    client, admin_headers, problem_ids: list[int], publish: bool = True, title: str = "C 语言入门计划"
) -> dict:
    created = client.post("/api/v1/admin/study-plans", json=plan_payload(problem_ids, title), headers=admin_headers)
    assert created.status_code == 201, created.text
    if not publish:
        return created.json()
    published = client.post(f"/api/v1/admin/study-plans/{created.json()['id']}/publish", headers=admin_headers)
    assert published.status_code == 200, published.text
    return published.json()


def solve_problem(client, user_headers, db_session, problem_id: int, key: str) -> None:
    response = client.post(
        "/api/v1/submissions",
        headers=user_headers,
        json={
            "problemId": problem_id,
            "language": "python",
            "source": "print(3)",
            "idempotencyKey": key,
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
        "nonce": f"{key}-nonce",
    }
    assert process_judge_result(payload) is True


def test_admin_creates_and_publishes_plan(client, admin_headers, user_headers):
    first = create_problem(client, admin_headers, "计划第一题")
    second = create_problem(client, admin_headers, "计划第二题")
    plan = create_plan(client, admin_headers, [second, first])

    assert plan["status"] == "published"
    assert [item["problemId"] for item in plan["problems"]] == [second, first]
    assert [item["groupName"] for item in plan["problems"]] == ["基础", "进阶"]

    listed = client.get("/api/v1/study-plans", headers=user_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    summary = listed.json()[0]
    assert summary["problemCount"] == 2
    assert summary["solvedCount"] == 0
    assert summary["enrolled"] is False
    assert summary["completed"] is False

    detail = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    assert [item["problemId"] for item in detail.json()["problems"]] == [second, first]
    assert all(item["progress"] == "untouched" for item in detail.json()["problems"])

    admin_list = client.get("/api/v1/admin/study-plans", headers=admin_headers)
    assert admin_list.status_code == 200, admin_list.text
    assert admin_list.json()["items"][0]["problemCount"] == 2


def test_plan_management_requires_admin(client, admin_headers, user_headers):
    payload = plan_payload([])
    assert client.post("/api/v1/admin/study-plans", json=payload).status_code == 401
    assert client.post("/api/v1/admin/study-plans", json=payload, headers=user_headers).status_code == 403
    created = client.post("/api/v1/admin/study-plans", json=payload, headers=admin_headers)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"


def test_plan_rejects_duplicate_problem_and_position(client, admin_headers):
    problem_id = create_problem(client, admin_headers, "唯一题目")
    duplicate_problem = {
        **plan_payload([problem_id, problem_id]),
    }
    response = client.post("/api/v1/admin/study-plans", json=duplicate_problem, headers=admin_headers)
    assert response.status_code == 422, response.text

    duplicate_position = plan_payload([problem_id])
    duplicate_position["problems"].append({"problemId": problem_id + 1, "position": 1, "groupName": None})
    response = client.post("/api/v1/admin/study-plans", json=duplicate_position, headers=admin_headers)
    assert response.status_code == 422, response.text


def test_editing_plan_replaces_problems_and_order(client, admin_headers):
    first = create_problem(client, admin_headers, "编辑前第一题")
    second = create_problem(client, admin_headers, "编辑前第二题")
    plan = create_plan(client, admin_headers, [first, second])

    edited = client.put(
        f"/api/v1/admin/study-plans/{plan['id']}",
        json=plan_payload([second, first]),
        headers=admin_headers,
    )
    assert edited.status_code == 200, edited.text
    assert [item["problemId"] for item in edited.json()["problems"]] == [second, first]

    detail = client.get(f"/api/v1/study-plans/{plan['id']}")
    assert [item["problemId"] for item in detail.json()["problems"]] == [second, first]


def test_publish_requires_problems_and_published_problem_rows(client, admin_headers):
    empty = client.post("/api/v1/admin/study-plans", json=plan_payload([]), headers=admin_headers)
    assert empty.status_code == 201, empty.text
    blocked = client.post(f"/api/v1/admin/study-plans/{empty.json()['id']}/publish", headers=admin_headers)
    assert blocked.status_code == 409

    draft_problem = client.post("/api/v1/admin/problems", json=problem_payload("未发布题目"), headers=admin_headers)
    assert draft_problem.status_code == 201, draft_problem.text
    plan = create_plan(client, admin_headers, [draft_problem.json()["id"]], publish=False)
    blocked = client.post(f"/api/v1/admin/study-plans/{plan['id']}/publish", headers=admin_headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "STUDY_PLAN_PROBLEM_UNPUBLISHED"


def test_draft_and_archived_plans_are_hidden_from_users(client, admin_headers):
    draft = create_plan(client, admin_headers, [], publish=False, title="草稿计划")
    assert client.get("/api/v1/study-plans").json() == []
    assert client.get(f"/api/v1/study-plans/{draft['id']}").status_code == 404

    problem_id = create_problem(client, admin_headers, "归档计划题目")
    published = create_plan(client, admin_headers, [problem_id], title="待归档计划")
    archived = client.post(f"/api/v1/admin/study-plans/{published['id']}/archive", headers=admin_headers)
    assert archived.status_code == 200, archived.text
    assert client.get("/api/v1/study-plans").json() == []
    assert client.get(f"/api/v1/study-plans/{published['id']}").status_code == 404

    admin_list = client.get("/api/v1/admin/study-plans", headers=admin_headers)
    assert {item["status"] for item in admin_list.json()["items"]} == {"draft", "archived"}


def test_join_and_leave_plan(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers, "加入计划题目")
    plan = create_plan(client, admin_headers, [problem_id])

    assert client.put(f"/api/v1/study-plans/{plan['id']}/enrollment").status_code == 401
    joined = client.put(f"/api/v1/study-plans/{plan['id']}/enrollment", headers=user_headers)
    assert joined.status_code == 200, joined.text
    joined_again = client.put(f"/api/v1/study-plans/{plan['id']}/enrollment", headers=user_headers)
    assert joined_again.status_code == 200, joined_again.text

    detail = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers)
    assert detail.json()["enrolled"] is True
    listed = client.get("/api/v1/study-plans", headers=user_headers)
    assert listed.json()[0]["enrolled"] is True

    left = client.delete(f"/api/v1/study-plans/{plan['id']}/enrollment", headers=user_headers)
    assert left.status_code == 200, left.text
    assert client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers).json()["enrolled"] is False
    assert client.delete(f"/api/v1/study-plans/{plan['id']}/enrollment", headers=user_headers).status_code == 200


def test_plan_progress_follows_accepted_submissions(client, admin_headers, user_headers, db_session):
    first = create_problem(client, admin_headers, "进度第一题")
    second = create_problem(client, admin_headers, "进度第二题")
    plan = create_plan(client, admin_headers, [first, second])

    before = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers).json()
    assert before["solvedCount"] == 0
    assert before["completed"] is False

    solve_problem(client, user_headers, db_session, first, "study-plan-ac-1")

    after = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers).json()
    assert after["solvedCount"] == 1
    assert after["completed"] is False
    assert [item["progress"] for item in after["problems"]] == ["solved", "untouched"]

    solve_problem(client, user_headers, db_session, second, "study-plan-ac-2")
    completed = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers).json()
    assert completed["solvedCount"] == 2
    assert completed["completed"] is True


def test_sample_runs_do_not_count_toward_plan_progress(client, admin_headers, user_headers, db_session):
    problem_id = create_problem(client, admin_headers, "样例运行题目")
    plan = create_plan(client, admin_headers, [problem_id])

    response = client.post(
        f"/api/v1/problems/{problem_id}/sample-runs",
        headers=user_headers,
        json={
            "language": "python",
            "source": "print(3)",
            "idempotencyKey": "study-plan-sample-1",
        },
    )
    assert response.status_code == 202, response.text
    submission_id = response.json()["id"]
    db_session.expire_all()
    submission = db_session.get(Submission, submission_id)
    task = db_session.scalar(select(JudgeTask).where(JudgeTask.submission_id == submission_id))
    assert process_judge_result(
        {
            "task_id": task.id,
            "submission_id": submission_id,
            "status": "AC",
            "runtime_ms": 10,
            "memory_kb": 1000,
            "diagnostic": "",
            "attempt": task.attempt,
            "test_data_version_id": submission.test_data_version_id,
            "nonce": "study-plan-sample-nonce",
        }
    ) is True

    detail = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers).json()
    assert detail["solvedCount"] == 0
    assert detail["problems"][0]["progress"] == "untouched"


def test_archived_problem_is_filtered_from_user_plan(client, admin_headers, user_headers):
    first = create_problem(client, admin_headers, "会被归档的题目")
    second = create_problem(client, admin_headers, "保留的题目")
    plan = create_plan(client, admin_headers, [first, second])

    archived = client.post(f"/api/v1/admin/problems/{first}/archive", headers=admin_headers)
    assert archived.status_code == 200, archived.text

    detail = client.get(f"/api/v1/study-plans/{plan['id']}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["problemCount"] == 1
    assert [item["problemId"] for item in detail.json()["problems"]] == [second]

    admin_detail = client.get(f"/api/v1/admin/study-plans/{plan['id']}", headers=admin_headers)
    assert admin_detail.status_code == 200, admin_detail.text
    assert len(admin_detail.json()["problems"]) == 2
    assert {item["problemStatus"] for item in admin_detail.json()["problems"]} == {"published", "archived"}
