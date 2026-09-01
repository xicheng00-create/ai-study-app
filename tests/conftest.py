"""pytest 公共 fixture：临时库 + 测试客户端（隔离真实 instance 库）。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 测试专用临时库 + 禁用 LLM（走兜底，确定性）
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("TEACHER_USERNAME", "teacher")
    monkeypatch.setenv("TEACHER_PASSWORD", "teacher123")

    from app import create_app

    app = create_app("development")
    app.config["TESTING"] = True
    return app.test_client()


def login(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["token"]


@pytest.fixture
def teacher_token(client):
    return login(client, "teacher", "teacher123")


@pytest.fixture
def teacher_headers(client, teacher_token):
    return {"Authorization": f"Bearer {teacher_token}"}


def make_student(client, teacher_headers, username, password="student123", display_name=None):
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "role": "student",
            "display_name": display_name or username.title(),
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]
