"""掌握度 M 与四态（Design Spec §3.5，PROG-007/008，F3 数据正确性）。

M = Σ(wᵢ·correctᵢ)/Σ(wᵢ)，wᵢ=0.5^间隔周数；
仅聚合该章「最新已发布 version」的 attempts（F3，避免重出题污染）。
"""
import json
from datetime import datetime, timezone

# 四态阈值（PROG-008）
THRESHOLD_MASTER = 80
THRESHOLD_PROGRESS = 50
MIN_ATTEMPTS_MASTER = 2


def _weeks_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / (7 * 86400))


def _weight(iso: str) -> float:
    return 0.5 ** _weeks_since(iso)


def latest_version_for_chapter(con, chapter_id: str) -> int:
    """该章已发布测评的最新 version（无则 0）。"""
    rows = con.execute(
        "SELECT version FROM quizzes WHERE status='published' AND chapter_ids LIKE ?",
        (f'%"{chapter_id}"%',),
    ).fetchall()
    return max([r["version"] for r in rows], default=0)


def _chapter_ids_of(quiz_chapter_ids: str) -> list[str]:
    try:
        return json.loads(quiz_chapter_ids)
    except (json.JSONDecodeError, TypeError):
        return []


def compute_mastery(con, user_id: str, chapter_id: str) -> dict:
    """返回 {m, attempts, latest_version}；m=None 表示未评估。"""
    latest = latest_version_for_chapter(con, chapter_id)
    if latest <= 0:
        return {"m": None, "attempts": 0, "latest_version": 0}
    rows = con.execute(
        "SELECT score, correct, created_at FROM attempts"
        " WHERE user_id=? AND chapter_id=? AND quiz_version=?",
        (user_id, chapter_id, latest),
    ).fetchall()
    if not rows:
        return {"m": None, "attempts": 0, "latest_version": latest}
    total_w = 0.0
    total = 0.0
    for r in rows:
        w = _weight(r["created_at"])
        correct = float(r["score"]) if r["score"] is not None else float(r["correct"])
        total += w * correct
        total_w += w
    m = round(total / total_w * 100, 1) if total_w > 0 else None
    return {"m": m, "attempts": len(rows), "latest_version": latest}


def mastery_state(m, attempts: int) -> str:
    """四态映射：master / progress / weak / na（PROG-008）。"""
    if m is None:
        return "na"
    if m >= THRESHOLD_MASTER and attempts >= MIN_ATTEMPTS_MASTER:
        return "master"
    if m >= THRESHOLD_PROGRESS:
        return "progress"
    return "weak"


def state_label(state: str) -> str:
    return {"master": "已掌握", "progress": "进行中", "weak": "薄弱", "na": "未评估"}.get(state, state)
