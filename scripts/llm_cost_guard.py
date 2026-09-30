#!/usr/bin/env python3
"""llm_cost_guard.py — LLM 成本纪律护栏（Design-Spec §7.4 / REQ-NFR-LLMCOST-001 的机械断言）。

三条判据（任一命中 → 打印明细并退出 1）：
  ① 推理占比 > 15%   reasoning_tokens ÷ completion_tokens（按 feature）
  ② 重复率   > 1.5   调用数 ÷ 唯一 input_sha256（按 feature）
  ③ 存在未清 .fail   $LLM_FAIL_DIR/*.fail（不设时间窗：未清即红，重跑成功后删标记）

窗口内**缺 `input_sha256`**（算不出重复率）或**缺 `thinking`**（看不出是否绕过关思考入口）
的历史记录只统计条数、不参与判据 —— 否则 2026-10-01 之前的历史记录会让护栏永远红。

账本：`$LLM_USAGE_LOG` 或 `~/.hermes/app-usage/aistudy.jsonl`（与 backend/ai/usage_log.py 同一份）。
失败标记目录：`$LLM_FAIL_DIR` 或 `~/.hermes/app-usage/llm-fails/`
（写入方 = `scripts/rebuild_cards.py`、`scripts/group_cards.py`）。

用法：
    python3 scripts/llm_cost_guard.py                # 近 1 天（默认），正常静默
    python3 scripts/llm_cost_guard.py --days 7 -v    # 近 7 天 + 打印统计
退出码：0 = 通过；1 = 命中判据；2 = 账本不可读 / 参数错。
"""
import argparse
import collections
import datetime
import json
import os
import sys
from pathlib import Path

LEDGER = Path(os.environ.get("LLM_USAGE_LOG")
              or os.path.expanduser("~/.hermes/app-usage/aistudy.jsonl"))
FAIL_DIR = Path(os.path.expanduser(os.environ.get("LLM_FAIL_DIR")
                                   or "~/.hermes/app-usage/llm-fails"))
REASONING_MAX = 0.15      # 推理 token ÷ 输出 token 的上限（§7.4）
REPEAT_MAX = 1.5          # 调用数 ÷ 唯一输入 sha256 的上限（§7.4）
TZ8 = datetime.timezone(datetime.timedelta(hours=8))

Stats = collections.namedtuple(
    "Stats",
    "calls shas comp reason total judged_reasoning no_sha no_thinking bad_lines cut")


def _load(ledger: Path, days: int) -> Stats:
    """扫账本窗口：每 feature 的调用数 / 唯一输入 sha256 / 输出与推理 token。"""
    cut = datetime.datetime.now(TZ8) - datetime.timedelta(days=days)
    calls = collections.Counter()       # 参与重复率判据的调用（有 input_sha256 的）
    shas = collections.defaultdict(collections.Counter)   # feature -> {sha: 次数}
    comp = collections.Counter()        # feature -> 输出 token（有 thinking 字段的）
    reason = collections.Counter()      # feature -> 推理 token（有 thinking 字段的）
    total = judged_reasoning = 0
    no_sha = collections.Counter()      # feature -> 缺 input_sha256 的条数
    no_thinking = collections.Counter()  # feature -> 缺 thinking 的条数
    bad_lines = 0
    with ledger.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
                ts = datetime.datetime.fromisoformat(str(r.get("timestamp", "")))
            except Exception:   # noqa: BLE001 —— 账本里任何一行坏了都只跳过该行，不中断护栏
                bad_lines += 1
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ8)
            if ts < cut:
                continue
            total += 1
            feat = r.get("feature") or "?"
            if r.get("input_sha256"):
                calls[feat] += 1
                shas[feat][str(r["input_sha256"])] += 1
            else:
                no_sha[feat] += 1
            if r.get("thinking"):
                judged_reasoning += 1
                comp[feat] += int(r.get("completion_tokens") or 0)
                reason[feat] += int(r.get("reasoning_tokens") or 0)
            else:
                no_thinking[feat] += 1
    return Stats(calls=calls, shas=shas, comp=comp, reason=reason, total=total,
                 judged_reasoning=judged_reasoning, no_sha=no_sha,
                 no_thinking=no_thinking, bad_lines=bad_lines, cut=cut)


def _fails():
    """未清 .fail 标记（不设时间窗：存在即红）。"""
    out = []
    if FAIL_DIR.is_dir():
        for p in sorted(FAIL_DIR.glob("*.fail")):
            try:
                mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime, TZ8)
            except OSError:
                mtime = None
            out.append((p.name, mtime))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 成本纪律护栏（Design-Spec §7.4）")
    ap.add_argument("--days", type=int, default=1, help="回看天数（默认 1）")
    ap.add_argument("-v", "--verbose", action="store_true", help="通过时也打印统计")
    a = ap.parse_args()
    if a.days < 0:
        print("[llm-cost-guard] --days 必须 >= 0", file=sys.stderr)
        return 2
    if not LEDGER.is_file():
        print(f"[llm-cost-guard] 账本不存在：{LEDGER}"
              "（确认 LLM_USAGE_LOG，或让服务/脚本先跑一次 LLM）", file=sys.stderr)
        return 2

    d = _load(LEDGER, a.days)
    problems = []

    # ① 推理占比（只看有 thinking 字段的记录）
    for feat, c in sorted(d.comp.items(), key=lambda kv: -kv[1]):
        if c <= 0:
            continue
        ratio = d.reason[feat] / c
        if ratio > REASONING_MAX:
            problems.append(
                f"推理占比 {ratio:.1%}（{d.reason[feat]}/{c} tok，{feat}）"
                f"> {REASONING_MAX:.0%}：有人绕过了默认关思考入口？")

    # ② 重复率（只看有 input_sha256 的记录）
    for feat, n in sorted(d.calls.items(), key=lambda kv: -kv[1]):
        uniq = len(d.shas[feat])
        if uniq <= 0:
            continue
        ratio = n / uniq
        if ratio > REPEAT_MAX:
            top_sha, top_n = d.shas[feat].most_common(1)[0]
            problems.append(
                f"重复率 {ratio:.2f}（{n} 次调用 / {uniq} 个唯一输入，{feat}）"
                f"> {REPEAT_MAX}：同一输入最多重复 {top_n} 次（sha {str(top_sha)[:16]}…）")

    # ③ 未清 .fail
    fails = _fails()
    if fails:
        shown = "、".join(f"{n}（{m:%Y-%m-%d %H:%M}）" if m else n for n, m in fails[:5])
        problems.append(f"存在未清 .fail 标记 {len(fails)} 个：{shown}"
                        f"（目录 {FAIL_DIR}；重跑成功并确认后删标记）")

    no_sha = sum(d.no_sha.values())
    no_thinking = sum(d.no_thinking.values())
    note = []
    if no_sha:
        note.append(f"{no_sha} 条缺 input_sha256（算不出重复率）")
    if no_thinking:
        note.append(f"{no_thinking} 条缺 thinking（看不出是否绕过关思考入口）")
    if d.bad_lines:
        note.append(f"{d.bad_lines} 行不可解析")

    if problems:
        print(f"[llm-cost-guard] 近 {a.days} 天 {d.total} 次调用，命中 {len(problems)} 条判据：")
        for p in problems:
            print("  - " + p)
        if note:
            print("  （未参与判据的脏记录：" + "；".join(note) + "）")
        return 1

    if a.verbose:
        print(f"[llm-cost-guard] 近 {a.days} 天 {d.total} 次调用，无违规"
              f"（判据样本：重复率 {len(d.calls)} 个 feature / 推理占比 {len(d.comp)} 个 feature）")
        for feat, n in sorted(d.calls.items(), key=lambda kv: -kv[1]):
            uniq = len(d.shas[feat])
            print(f"  · 重复率 {feat}: {n}/{uniq} = {n / uniq:.2f}")
        for feat, c in sorted(d.comp.items(), key=lambda kv: -kv[1]):
            r = d.reason[feat] / c if c else 0.0
            print(f"  · 推理占比 {feat}: {d.reason[feat]}/{c} = {r:.1%}")
        print(f"  · .fail 标记 0 个（{FAIL_DIR}）")
        if note:
            print("  · 未参与判据的脏记录：" + "；".join(note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
