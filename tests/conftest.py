"""pytest 公共 fixture：临时库 + 测试客户端（隔离真实 instance 库）。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """全局屏蔽真实 LLM：单测一律走兜底/桩，保证确定性、不产生真实 API 花费。

    config.py 的 DEEPSEEK_API_KEY 是「模块首次 import 时」绑定的类属性；验收/CI 会
    `set -a; source .env` 后再跑 pytest，此时 config 被 import 就已拿到真 key，
    于是批改（essay 三档）、每日建议等断言会随模型措辞随机失败。
    需要假 key 的测试自己 monkeypatch.setenv 覆盖即可（测试级覆盖在此之后生效）。
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")


@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path, monkeypatch):
    """全局隔离 LLM 用量日志，避免测试写入真实 ~/.hermes/app-usage/aistudy.jsonl。"""
    monkeypatch.setenv("LLM_USAGE_LOG", str(tmp_path / "app-usage" / "aistudy.jsonl"))


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
    # 单测确定性：config.py 的类属性在「首次 import 时」就绑定了当时的 .env key，
    # 只在 os.environ 上 setenv 覆盖不到 current_app.config，而 agents._config 在应用上下文里
    # 优先读 current_app.config → 测试会真去打 DeepSeek，断言随模型措辞随机失败。
    # （其它测试文件在收集阶段 import ai/* 就会触发 config 导入，故必须在这里再兜一层）
    app.config["DEEPSEEK_API_KEY"] = ""
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
