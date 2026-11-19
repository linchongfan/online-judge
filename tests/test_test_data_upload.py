"""Test-data upload regressions: off-loop worker, versions, orphan cleanup."""

from __future__ import annotations

import io
import zipfile

from app.core.config import get_settings
from tests.test_problem_api import archive_bytes, problem_payload


def _create_draft(client, admin_headers, title: str) -> int:
    created = client.post("/api/v1/admin/problems", json=problem_payload(title=title), headers=admin_headers)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _upload(client, admin_headers, problem_id: int, content: bytes):
    return client.post(
        f"/api/v1/admin/problems/{problem_id}/test-data",
        files={"upload": ("data.zip", content, "application/zip")},
        headers=admin_headers,
    )


def test_sequential_uploads_allocate_increasing_versions(client, admin_headers):
    problem_id = _create_draft(client, admin_headers, "版本号测试")
    first = _upload(client, admin_headers, problem_id, archive_bytes())
    second = _upload(client, admin_headers, problem_id, archive_bytes())
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    versions = client.get(f"/api/v1/admin/problems/{problem_id}/test-data", headers=admin_headers)
    assert versions.status_code == 200
    numbers = sorted(item["version"] for item in versions.json())
    assert numbers == [1, 2]


def test_invalid_archive_creates_no_storage_directory(client, admin_headers):
    problem_id = _create_draft(client, admin_headers, "损坏压缩包")
    response = _upload(client, admin_headers, problem_id, b"not-a-zip")
    assert response.status_code == 422, response.text

    problem_dir = get_settings().storage_root / "test-data" / f"problem-{problem_id}"
    assert not problem_dir.exists() or not any(problem_dir.iterdir())


def test_invalid_archive_is_recorded_as_invalid_version(client, admin_headers):
    problem_id = _create_draft(client, admin_headers, "无效版本记录")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # Missing the paired .out file: validation must fail and be recorded.
        archive.writestr("sample/1.in", "1 2\n")
    response = _upload(client, admin_headers, problem_id, buffer.getvalue())
    assert response.status_code == 422, response.text
    version_id = response.json()["error"]["details"]["versionId"]

    versions = client.get(f"/api/v1/admin/problems/{problem_id}/test-data", headers=admin_headers)
    recorded = {item["id"]: item for item in versions.json()}
    assert recorded[version_id]["status"] == "invalid"
