"""批量 LLM 成本纪律：统一入口 `_chat` 的机械断言（2026-10-01）。

覆盖四条铁律里本入口负责的 ①②：
  ① 转换型任务默认关思考（`thinking:{"type":"disabled"}`），可用配置提档；
  ② 每次成功调用落账本并带 `reasoning_tokens` / `thinking`（护栏的前提）。
以及一条硬要求：上游不认 `thinking` 参数时必须自动去掉重发（换 base_url/服务商不因此 400）。

LLM 一律用 stub（不真调）。
"""
import json

import pytest

from ai import agents


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    """无 Flask 上下文时 `_config` 读环境变量；没有凭据 `_chat` 会直接返回 None（测试要拦住这点）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {"choices": [{"message": {"content": '{"ok":true}'}}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                              "total_tokens": 15}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("stub: 不该对 400 调用 raise_for_status")

    def json(self):
        return self._payload


def _capture(monkeypatch, responses):
    """把 requests.post 换成记录 payload 的桩；responses 是待返回的 FakeResp 序列。"""
    sent = []
    queue = list(responses)

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(dict(json or {}))       # 复制：`_chat` 会在 400 时原地 pop("thinking")
        return queue.pop(0) if queue else FakeResp()

    monkeypatch.setattr(agents.requests, "post", fake_post)
    return sent


def test_default_disables_thinking(monkeypatch):
    sent = _capture(monkeypatch, [FakeResp()])
    monkeypatch.delenv("LLM_THINKING", raising=False)
    monkeypatch.delenv("LLM_THINKING_FEATURES", raising=False)
    out = agents._chat([{"role": "user", "content": "hi"}], feature="quizzer")
    assert out == '{"ok":true}'
    assert sent[0]["thinking"] == {"type": "disabled"}, "转换型任务必须默认关思考"


def test_env_raises_thinking_globally(monkeypatch):
    sent = _capture(monkeypatch, [FakeResp()])
    monkeypatch.setenv("LLM_THINKING", "on")
    agents._chat([{"role": "user", "content": "hi"}], feature="quizzer")
    assert "thinking" not in sent[0], "LLM_THINKING=on 应全局提档"


def test_feature_allowlist(monkeypatch):
    sent = _capture(monkeypatch, [FakeResp(), FakeResp()])
    monkeypatch.delenv("LLM_THINKING", raising=False)
    monkeypatch.setenv("LLM_THINKING_FEATURES", "tutor")
    agents._chat([{"role": "user", "content": "hi"}], feature="tutor")
    agents._chat([{"role": "user", "content": "hi"}], feature="knowledge_dup_check")
    assert "thinking" not in sent[0], "白名单里的 feature 应保留思考"
    assert sent[1]["thinking"] == {"type": "disabled"}, "白名单外的 feature 仍须关思考"


def test_400_drops_thinking_and_retries_once(monkeypatch):
    sent = _capture(monkeypatch, [FakeResp(status=400, payload={}), FakeResp()])
    out = agents._chat([{"role": "user", "content": "hi"}], feature="grader")
    assert out == '{"ok":true}'
    assert len(sent) == 2, "上游不认 thinking 时应去掉后重发一次（且只一次）"
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert "thinking" not in sent[1]


def test_ledger_records_reasoning_and_thinking(monkeypatch, tmp_path):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("LLM_USAGE_LOG", str(log))
    monkeypatch.delenv("LLM_THINKING", raising=False)
    monkeypatch.delenv("LLM_THINKING_FEATURES", raising=False)
    resp = FakeResp(payload={
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 60, "total_tokens": 160,
                  "completion_tokens_details": {"reasoning_tokens": 42}},
    })
    _capture(monkeypatch, [resp])
    agents._chat([{"role": "user", "content": "hi"}], feature="knowledge")
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert rec["reasoning_tokens"] == 42, "账本必须记推理 token（护栏据此查绕过）"
    assert rec["thinking"] == "off"
    assert rec["feature"] == "knowledge"
