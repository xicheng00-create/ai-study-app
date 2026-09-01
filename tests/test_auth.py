"""鉴权测试（AUTH-001~008）：登录/注册/me/角色门禁/改密。"""
from conftest import login, make_student


def test_teacher_seeded_login(client):
    token = login(client, "teacher", "teacher123")
    assert token


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "teacher", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "E_AUTH"


def test_register_student_requires_teacher(client, teacher_headers):
    resp = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alice123", "role": "student"},
    )
    assert resp.status_code == 401  # 无 token
    resp = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alice123", "role": "student"},
        headers=teacher_headers,
    )
    assert resp.status_code == 200


def test_student_cannot_register(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice_token = login(client, "alice", "student123")
    resp = client.post(
        "/api/auth/register",
        json={"username": "mallory", "password": "x", "role": "student"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "E_ROLE"


def test_me_and_refresh(client, teacher_headers):
    token = login(client, "teacher", "teacher123")
    h = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/auth/me", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["role"] == "teacher"
    resp = client.post("/api/auth/refresh", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["token"]


def test_change_password(client, teacher_headers):
    make_student(client, teacher_headers, "bob")
    token = login(client, "bob", "student123")
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/auth/change-password",
                       json={"old_password": "student123", "new_password": "newpass1"}, headers=h)
    assert resp.status_code == 200
    # 旧密码失效，新密码可登录
    assert login(client, "bob", "newpass1")
