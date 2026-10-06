"""LLM 成本纪律护栏 `scripts/llm_cost_guard.py` 的机械断言（2026-10-01）。

规格条款 = Design-Spec §7.4（REQ-NFR-LLMCOST-001）。这里断言护栏**能失败也能通过**：
  · 重复率 >1.5（调用数 ÷ 唯一 input_sha256）→ 退出 1
  · 推理占比 >15%（reasoning_tokens ÷ completion_tokens）→ 退出 1
  · 存在未清 .fail → 退出 1
  · 干净账本 → 退出 0（含「缺 input_sha256 / 缺 thinking 的历史记录不参与判据」，否则永远红）

一律用 subprocess 真跑脚本（退出码是契约的一部分，不能在进程内 import 掉）。

⚠️ 账本时间戳必须**动态取当前时间**（2026-10-06 修）：护栏按 `--days N` 滚动窗口过滤账本，
写死 `2026-10-01` 的记录在窗口滑走后会被整批跳过 → 判据全部不触发、本该红的用例变绿
（`test_fail_repeat_ratio` / `test_fail_reasoning_ratio` 就是这么在 10-02 起静默烂掉的）。
「窗口外记录不参与判据」由 `test_pass_record_outside_window_not_judged` 显式断言，不再靠时间碰运气。
"""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "llm_cost_guard.py"
TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def _now_ts():
    """当前时间（+08:00，秒级）——永远落在护栏的 --days 1 窗口内。"""
    return datetime.datetime.now(TZ8).replace(microsecond=0).isoformat()


def _old_ts(days=30):
    """窗口外的旧时间戳（用于断言「窗口外记录不参与判据」）。"""
    return (datetime.datetime.now(TZ8) - datetime.timedelta(days=days)).replace(
        microsecond=0).isoformat()


def _rec(feature="rebuild_cards.py", *, sha=None, thinking: "str | None" = "off",
         comp=100, reason=0, ts=None):
    r = {"timestamp": ts or _now_ts(), "model": "deepseek-chat", "feature": feature,
         "prompt_tokens": 10, "completion_tokens": comp, "total_tokens": 10 + comp,
         "reasoning_tokens": reason}
    if thinking is not None:
        r["thinking"] = thinking
    if sha is not None:
        r["input_sha256"] = sha
    return r


def _run(tmp_path, records, fails=0):
    """真跑护栏：账本与 .fail 目录都指向 tmp_path（不碰生产账本）。"""
    ledger = tmp_path / "aistudy.jsonl"
    ledger.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                      encoding="utf-8")
    fail_dir = tmp_path / "llm-fails"
    for i in range(fails):
        fail_dir.mkdir(exist_ok=True)
        (fail_dir / f"extract-{i:016d}.fail").write_text("{}", encoding="utf-8")
    env = dict(os.environ, LLM_USAGE_LOG=str(ledger), LLM_FAIL_DIR=str(fail_dir))
    p = subprocess.run([sys.executable, str(SCRIPT), "--days", "1"],
                       capture_output=True, text=True, env=env, timeout=60, check=False)
    return p.returncode, p.stdout + p.stderr


def test_pass_clean_ledger(tmp_path):
    """干净账本（唯一输入、无推理、无 .fail）→ 0。"""
    rc, out = _run(tmp_path, [_rec(sha=f"sha{i:016d}") for i in range(5)])
    assert rc == 0, out
    assert out == ""            # 正常静默


def test_pass_dirty_legacy_records_not_judged(tmp_path):
    """缺 input_sha256 / 缺 thinking 的历史记录只统计条数，不参与判据 → 仍 0。"""
    rc, out = _run(tmp_path, [_rec(sha=None, thinking=None, comp=5000, reason=4000)
                              for _ in range(20)])
    assert rc == 0, out


def test_fail_repeat_ratio(tmp_path):
    """同一输入 4 次调用 / 1 个唯一 sha = 4.00 > 1.5 → 1，且明细出现。"""
    rc, out = _run(tmp_path, [_rec(sha="e9a51d58896ce7de") for _ in range(4)])
    assert rc == 1, out
    assert "重复率 4.00" in out and "rebuild_cards.py" in out


def test_fail_reasoning_ratio(tmp_path):
    """推理 token 60/100 = 60% > 15% → 1（防「有人绕过关思考入口」）。"""
    rc, out = _run(tmp_path, [_rec(sha="a" * 16, thinking="on", comp=100, reason=60)])
    assert rc == 1, out
    assert "推理占比 60.0%" in out


def test_fail_marker(tmp_path):
    """存在未清 .fail → 1（不设时间窗，未清即红）。"""
    rc, out = _run(tmp_path, [_rec(sha="b" * 16)], fails=1)
    assert rc == 1, out
    assert "未清 .fail" in out


def test_repeat_ratio_boundary_not_flagged(tmp_path):
    """正好 1.5 不算违规（判据是「>1.5」）：3 次调用 / 2 个唯一输入 = 1.50 → 0。"""
    rc, out = _run(tmp_path, [_rec(sha="c" * 16), _rec(sha="c" * 16),
                              _rec(sha="d" * 16)])
    assert rc == 0, out


def test_pass_record_outside_window_not_judged(tmp_path):
    """窗口外（30 天前）的违规记录不参与判据 → 0：窗口语义显式断言，避免又变成「时间碰运气」。"""
    rc, out = _run(tmp_path, [_rec(sha="e" * 16, thinking="on", comp=100, reason=60,
                                   ts=_old_ts(30))
                              for _ in range(4)])
    assert rc == 0, out


def test_fail_repeat_ratio_inside_window_not_stale(tmp_path):
    """同一输入 4 次（**当前时间戳**）→ 1：时间戳动态化后不会再随窗口滑走而静默变绿。"""
    rc, out = _run(tmp_path, [_rec(sha="f" * 16) for _ in range(4)])
    assert rc == 1, out
    assert "重复率 4.00" in out
