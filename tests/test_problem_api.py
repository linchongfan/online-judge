import io
import zipfile


def problem_payload(title="A+B"):
    return {
        "title": title,
        "difficulty": "简单",
        "description": ["读入两个整数并输出它们的和。"],
        "inputDescription": "一行两个整数 a b。",
        "outputDescription": "输出 a+b。",
        "constraints": ["-1000 <= a,b <= 1000"],
        "tags": ["入门", "模拟"],
        "timeLimitMs": 1000,
        "memoryLimitMb": 256,
        "solution": {
            "title": "直接求和",
            "summary": "读入后相加。",
            "steps": ["读入两个整数", "输出它们的和"],
            "timeComplexity": "O(1)",
            "spaceComplexity": "O(1)",
            "codes": [{"language": "python", "code": "a,b=map(int,input().split())\nprint(a+b)"}],
        },
    }


def archive_bytes():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample/1.in", "1 2\n")
        archive.writestr("sample/1.out", "3\n")
        archive.writestr("hidden/1.in", "10 20\n")
        archive.writestr("hidden/1.out", "30\n")
    return content.getvalue()


def create_published_problem(client, admin_headers):
    created = client.post("/api/v1/admin/problems", json=problem_payload(), headers=admin_headers)
    assert created.status_code == 201, created.text
    problem_id = created.json()["id"]
    blocked = client.post(f"/api/v1/admin/problems/{problem_id}/publish", headers=admin_headers)
    assert blocked.status_code == 409
    uploaded = client.post(
        f"/api/v1/admin/problems/{problem_id}/test-data",
        files={"upload": ("data.zip", archive_bytes(), "application/zip")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["testCaseCount"] == 2
    published = client.post(f"/api/v1/admin/problems/{problem_id}/publish", headers=admin_headers)
    assert published.status_code == 200, published.text
    return problem_id


def test_problem_publish_and_hidden_data_boundary(client, admin_headers):
    problem_id = create_published_problem(client, admin_headers)
    listed = client.get("/api/v1/problems")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    detail = client.get(f"/api/v1/problems/{problem_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["samples"] == [{"input": "1 2\n", "output": "3\n", "explanation": None}]
    text = detail.text
    assert "10 20" not in text and "30\n" not in text
    solution = client.get(f"/api/v1/problems/{problem_id}/solution")
    assert solution.status_code == 200, solution.text
    assert solution.json()["time"] == "O(1)"


def test_submission_idempotency_and_owner_access(client, admin_headers, user_headers):
    problem_id = create_published_problem(client, admin_headers)
    payload = {
        "problemId": problem_id,
        "language": "python",
        "source": "a,b=map(int,input().split())\nprint(a+b)",
        "idempotencyKey": "submission-key-1",
    }
    first = client.post("/api/v1/submissions", json=payload, headers=user_headers)
    assert first.status_code == 202, first.text
    second = client.post("/api/v1/submissions", json=payload, headers=user_headers)
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    conflict = client.post("/api/v1/submissions", json={**payload, "source": "print(0)"}, headers=user_headers)
    assert conflict.status_code == 409
    submission_id = first.json()["id"]
    detail = client.get(f"/api/v1/submissions/{submission_id}", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "PENDING"
    assert client.get(f"/api/v1/submissions/{submission_id}").status_code == 401
    records = client.get("/api/v1/submissions", headers=user_headers)
    assert records.status_code == 200
    assert records.json()["total"] == 1
