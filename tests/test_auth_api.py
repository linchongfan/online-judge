def test_register_login_and_profile(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "new_user", "nickname": "新用户", "email": "new@example.com", "password": "Password1"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "user"
    assert body["tokenType"] == "bearer"
    assert body["user"]["joinedAt"]
    headers = {"Authorization": f"Bearer {body['accessToken']}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    updated = client.patch(
        "/api/v1/me", headers=headers, json={"nickname": "新昵称", "school": "测试大学", "bio": "你好"}
    )
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "新昵称"
    assert client.post("/api/v1/auth/login", json={"account": "new_user", "password": "wrong"}).status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_registration_rejects_weak_and_duplicate_accounts(client):
    weak = client.post(
        "/api/v1/auth/register",
        json={"username": "weak", "nickname": "弱密码", "email": "weak@example.com", "password": "12345678"},
    )
    assert weak.status_code == 422
    payload = {"username": "duplicate", "nickname": "用户", "email": "dup@example.com", "password": "Password1"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409


def test_refresh_requires_csrf_and_rotates_token(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "refresh", "nickname": "刷新", "email": "refresh@example.com", "password": "Password1"},
    )
    assert registered.status_code == 201
    old_cookie = client.cookies.get("oj_refresh")
    csrf = client.cookies.get("oj_csrf")
    assert old_cookie and csrf
    assert client.post("/api/v1/auth/refresh").status_code == 403
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200, refreshed.text
    assert client.cookies.get("oj_refresh") != old_cookie


def test_password_reset_revokes_existing_session(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "username": "reset_user",
            "nickname": "重置用户",
            "email": "reset@example.com",
            "password": "Password1",
        },
    )
    assert registered.status_code == 201
    old_headers = {"Authorization": f"Bearer {registered.json()['accessToken']}"}
    sent = client.post("/api/v1/auth/forgot/code", json={"email": "reset@example.com"})
    assert sent.status_code == 202, sent.text
    from app.core.config import get_settings

    mail_file = get_settings().storage_root / "mail_outbox" / "reset@example.com.txt"
    content = mail_file.read_text(encoding="utf-8")
    code = content.split("验证码：", 1)[1][:6]
    reset = client.post(
        "/api/v1/auth/forgot/reset",
        json={"email": "reset@example.com", "code": code, "newPassword": "NewPassword2"},
    )
    assert reset.status_code == 200, reset.text
    assert client.get("/api/v1/me", headers=old_headers).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"account": "reset_user", "password": "NewPassword2"}).status_code == 200
    )


def test_admin_routes_require_real_server_role(client, user_headers, admin_headers):
    payload = {
        "title": "A+B",
        "difficulty": "简单",
        "description": ["计算两个整数之和。"],
        "inputDescription": "两个整数",
        "outputDescription": "一个整数",
        "constraints": [],
        "tags": ["入门"],
        "timeLimitMs": 1000,
        "memoryLimitMb": 256,
    }
    assert client.post("/api/v1/admin/problems", json=payload).status_code == 401
    assert client.post("/api/v1/admin/problems", json=payload, headers=user_headers).status_code == 403
    created = client.post("/api/v1/admin/problems", json=payload, headers=admin_headers)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
