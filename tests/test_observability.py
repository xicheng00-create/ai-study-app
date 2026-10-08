"""REQ-OBS-014（v2.14.1）机械断言：/api/* 缓存口径 + 逐次访问日志。

背景：出现「学生称已打卡、服务端各表零记录」的争议时，必须能区分
「客户端没发请求」与「发了但服务端没落库」；此前两个都查不了。
"""
import pathlib


def test_api_no_store_header(client):
    """未鉴权也必须有 no-store（缓存头在 after_request 统一加，与鉴权无关）。"""
    r = client.get("/api/checkin/today")
    cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc, cc
    assert "no-cache" in cc, cc
    assert r.headers.get("Pragma") == "no-cache"


def test_api_access_log_written(client, tmp_path, monkeypatch):
    """一次 /api/ 请求 → 日志新增 1 行，且固定 8 列（Tab 分隔）。"""
    monkeypatch.setenv("API_LOG_DIR", str(tmp_path))
    client.post("/api/auth/login", json={"username": "___nobody___", "password": "x"})
    files = list(pathlib.Path(tmp_path).glob("api_access_*.log"))
    assert len(files) == 1, files
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    cols = lines[-1].split("\t")
    assert len(cols) == 8, cols
    assert cols[1] == "POST" and cols[2].startswith("/api/auth/login"), cols
    assert cols[3].isdigit(), cols          # status
    assert cols[4].endswith("ms"), cols      # 耗时
    assert "-" in cols[6] or cols[6], cols   # XFF 首跳（测试客户端无 XFF 时为 -）


def test_non_api_path_not_logged(client, tmp_path, monkeypatch):
    """非 /api/ 路径不写该日志（避免把静态请求也灌进来）。"""
    monkeypatch.setenv("API_LOG_DIR", str(tmp_path))
    client.get("/health")
    assert list(pathlib.Path(tmp_path).glob("api_access_*.log")) == []
