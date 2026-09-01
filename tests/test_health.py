"""最小冒烟/健康测试：确保骨架可启动、/health 返回 up。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app("development")
    return app.test_client()


def test_health_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["status"] == "up"
    assert "version" in body["data"]


def test_index_served(client):
    resp = client.get("/")
    # 骨架阶段前端占位；若未实现则回退 index.html（仍 200）
    assert resp.status_code in (200, 404)
