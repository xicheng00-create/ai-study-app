"""健康检查 / 首页静态托管冒烟测试。"""
import pytest


def test_health_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["status"] == "up"
    assert body["data"]["db"] == "ok"
    assert "version" in body["data"]


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200


@pytest.mark.parametrize("path", ["/manifest.webmanifest", "/sw.js", "/js/app.js"])
def test_static_assets(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
