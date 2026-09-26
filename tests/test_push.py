"""Web Push 发送封装（NOTIF-002）：payload 序列化契约 + 降级 + last_ok_at 语义 + 失效订阅留痕。

回归背景（v2.9.1）：`_webpush()` 曾把 dict 原样交给 pywebpush，而 pywebpush 的 `data`
契约是**已序列化的 str/bytes** → 本地加密阶段抛 `KeyError: slice(0, 4079, None)`，
被 `except Exception` 吞掉 → 自 v2.4.0 起推送 100% 静默失败（`make lint test smoke`
与 CI 全绿也发现不了：旧测试只打桩到 `send_push` 层，全仓无 `_webpush()` 级用例）。

回归背景（v2.9.6）：404/410 删订阅行时曾**不留任何日志**，于是「曾经开过后来失效」
与「从未开过」在库里不可区分（2026-09-26 两名学生排查时无法归因）。
"""
import json
import logging
from types import SimpleNamespace

import pytest
from conftest import make_student

import pywebpush

from data import models


@pytest.fixture
def push_mod(monkeypatch):
    """打上假 VAPID 密钥，避免 send_push 因「无密钥」提前 return。"""
    from services import push

    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "test-public-key")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "test-private-key")
    return push


def _add_sub(con, user_id, endpoint="https://web.push.apple.com/FAKE"):
    sid = models.new_id()
    con.execute(
        "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (sid, user_id, endpoint, "p256dh", "auth", models.utcnow()),
    )
    con.commit()
    return sid


def _sub_row(con, sid):
    return con.execute("SELECT * FROM push_subscriptions WHERE id=?", (sid,)).fetchone()


# ---- 序列化契约（本事故的回归哨兵） ----


def test_webpush_serializes_dict_payload(push_mod, monkeypatch):
    captured = {}

    def recorder(subscription_info, data, **kwargs):
        captured["data"] = data
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(pywebpush, "webpush", recorder)

    payload = {"title": "该学习了", "body": "今晚还有 5 档", "data": {"url": "/"}}
    ok = push_mod._webpush({"endpoint": "https://e", "p256dh": "p", "auth": "a"}, payload)

    assert ok is True
    data = captured["data"]
    # dict 直传会让 pywebpush 加密层抛 KeyError: slice(0, 4079, None)
    assert isinstance(data, (str, bytes))
    assert json.loads(data) == payload


def test_webpush_keeps_str_payload_as_is(push_mod, monkeypatch):
    captured = {}

    monkeypatch.setattr(
        pywebpush, "webpush", lambda subscription_info, data, **kw: captured.update(d=data)
    )
    assert push_mod._webpush({"endpoint": "https://e", "p256dh": "p", "auth": "a"}, '{"a": 1}') is True
    assert captured["d"] == '{"a": 1}'


# ---- 降级 / 失效订阅 / last_ok_at ----


def test_send_push_deletes_subscription_on_410(client, teacher_headers, push_mod, monkeypatch):
    uid = make_student(client, teacher_headers, "push_410")

    def gone(subscription_info, data, **kwargs):
        raise pywebpush.WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(pywebpush, "webpush", gone)

    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid = _add_sub(con, uid)

        push_mod.send_push(con, [uid], {"title": "t"})  # 不抛

        assert _sub_row(con, sid) is None  # 失效订阅已删除


def test_send_push_failure_does_not_write_last_ok_at(
    client, teacher_headers, push_mod, monkeypatch
):
    uid = make_student(client, teacher_headers, "push_boom")

    def boom(subscription_info, data, **kwargs):
        raise RuntimeError("push exploded")

    monkeypatch.setattr(pywebpush, "webpush", boom)

    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid = _add_sub(con, uid)

        push_mod.send_push(con, [uid], {"title": "t"})  # 不抛

        row = _sub_row(con, sid)
        assert row is not None and row["last_ok_at"] is None  # 失败不记「最近成功」


def test_send_push_success_writes_last_ok_at(client, teacher_headers, push_mod, monkeypatch):
    uid = make_student(client, teacher_headers, "push_ok")

    monkeypatch.setattr(
        pywebpush, "webpush", lambda subscription_info, data, **kw: SimpleNamespace(status_code=201)
    )

    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid = _add_sub(con, uid)

        push_mod.send_push(con, [uid], {"title": "t"})

        assert _sub_row(con, sid)["last_ok_at"] is not None


def test_send_push_no_vapid_key_is_silent_noop(client, teacher_headers, monkeypatch):
    """无 VAPID 密钥 → 静默跳过，不触碰任何数据。"""
    from services import push

    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "")
    uid = make_student(client, teacher_headers, "push_nokey")
    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid = _add_sub(con, uid)
        push.send_push(con, [uid], {"title": "t"})
        assert _sub_row(con, sid)["last_ok_at"] is None


def test_send_push_logs_subscription_gone(client, teacher_headers, push_mod, monkeypatch, caplog):
    """404/410 删订阅行必须留 warning（sub/user/endpoint），否则不可归因（v2.9.6）。

    2026-09-26 排查依据：分不清「曾开过后来失效」与「从未开过」→ 每个失效都不能静默。
    """
    uid = make_student(client, teacher_headers, "push_410_log")
    endpoint = "https://web.push.apple.com/GONE-410-FIXTURE"

    def gone(subscription_info, data, **kwargs):
        raise pywebpush.WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(pywebpush, "webpush", gone)

    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid = _add_sub(con, uid, endpoint=endpoint)

        with caplog.at_level(logging.WARNING, logger="aistudy.push"):
            push_mod.send_push(con, [uid], {"title": "t"})  # 不抛

        assert _sub_row(con, sid) is None  # 行仍被删
        hits = [
            r.getMessage()
            for r in caplog.records
            if r.name == "aistudy.push" and "404/410" in r.getMessage()
        ]
        assert hits, "失效订阅被删除时必须留 warning 日志"
        assert sid in hits[0] and uid in hits[0] and "GONE-410-FIXTURE" in hits[0]

    # 对照：HTTP 500 类失败（非失效）不得删行、也不该命中本告警
    uid2 = make_student(client, teacher_headers, "push_500_log")

    def err500(subscription_info, data, **kwargs):
        raise pywebpush.WebPushException("boom", response=SimpleNamespace(status_code=500))

    monkeypatch.setattr(pywebpush, "webpush", err500)
    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        sid2 = _add_sub(con, uid2, endpoint="https://web.push.apple.com/ERR-500-FIXTURE")
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="aistudy.push"):
            push_mod.send_push(con, [uid2], {"title": "t"})
        assert _sub_row(con, sid2) is not None  # 500 不删行
        assert not [r for r in caplog.records if "404/410" in r.getMessage()]
