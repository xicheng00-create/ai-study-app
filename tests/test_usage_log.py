"""LLM 逐次用量记账（JSONL）单元测试。

覆盖：成功调用记一行且字段齐全、四个 Agent 的 feature 标签正确、失败/异常路径不记一行、
写盘失败不影响主流程。
"""
import json

from ai import agents, usage_log


class _FakeResp:
    """模拟 requests 响应（仅用到的接口）。"""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _mock_success(monkeypatch, payload):
    """让 _chat 走一次成功的 HTTP 分支。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setattr(agents.requests, "post", lambda *a, **k: _FakeResp(payload))


def _usage(**overrides):
    u = {
        "prompt_tokens": 120,
        "prompt_cache_hit_tokens": 30,
        "completion_tokens": 45,
        "total_tokens": 165,
    }
    u.update(overrides)
    return u


def _read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_log_usage_writes_one_line_with_all_fields(tmp_path, monkeypatch):
    """log_usage 追加一行 JSONL，字段齐全。"""
    log_path = tmp_path / "app-usage" / "aistudy.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log_path))
    usage_log.log_usage("deepseek-chat", _usage(), "quizzer")
    recs = _read_records(log_path)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["model"] == "deepseek-chat"
    assert rec["feature"] == "quizzer"
    assert rec["prompt_tokens"] == 120
    assert rec["prompt_cache_hit_tokens"] == 30
    assert rec["completion_tokens"] == 45
    assert rec["total_tokens"] == 165
    assert rec["timestamp"]


def test_chat_success_records_usage(tmp_path, monkeypatch):
    """成功拿到 JSON → 记一行（feature=tutor，model 取自请求实发值）。"""
    log_path = tmp_path / "aistudy.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log_path))
    _mock_success(monkeypatch, {
        "choices": [{"message": {"content": "你好"}}],
        "usage": _usage(),
    })
    out = agents.tutor_reply("系统提示", [{"role": "user", "content": "hi"}])
    assert out == "你好"
    recs = _read_records(log_path)
    assert len(recs) == 1
    assert recs[0]["feature"] == "tutor"
    assert recs[0]["model"] == "deepseek-chat"
    assert recs[0]["total_tokens"] == 165


def test_each_wrapper_feature_tag(tmp_path, monkeypatch):
    """四个 Agent 包装函数各自写入对应 feature 标签。"""
    log_path = tmp_path / "aistudy.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log_path))

    _mock_success(monkeypatch, {
        "choices": [{"message": {"content": "{\"questions\": []}"}}], "usage": _usage(),
    })
    agents.quizzer_generate("出题")

    _mock_success(monkeypatch, {
        "choices": [{"message": {"content": "{\"cards\": []}"}}], "usage": _usage(),
    })
    agents.knowledge_generate("卡片")

    _mock_success(monkeypatch, {
        "choices": [{"message": {"content": "{\"correct\": 1}"}}], "usage": _usage(),
    })
    agents.grader_grade("批改")

    _mock_success(monkeypatch, {
        "choices": [{"message": {"content": "回复"}}], "usage": _usage(),
    })
    agents.tutor_reply("s", [])

    features = [r["feature"] for r in _read_records(log_path)]
    assert features == ["quizzer", "knowledge", "grader", "tutor"]


def test_failure_path_does_not_record(tmp_path, monkeypatch):
    """未配置 key（返回 None）路径不写日志。"""
    log_path = tmp_path / "aistudy.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    assert agents.tutor_reply("s", []) is None
    assert not log_path.exists()


def test_server_error_does_not_record(tmp_path, monkeypatch):
    """HTTP 5xx 返回 None，且不记录。"""
    log_path = tmp_path / "aistudy.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(agents.requests, "post", lambda *a, **k: _FakeResp({}, status_code=503))
    assert agents.tutor_reply("s", []) is None
    assert not log_path.exists()


def test_log_usage_write_failure_never_raises(tmp_path, monkeypatch):
    """写盘失败（父路径是文件）被吞掉，主流程不受影响。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv("LLM_USAGE_LOG", str(blocker / "nested" / "aistudy.jsonl"))
    usage_log.log_usage("m", _usage(), "unknown")  # 不抛异常即通过
