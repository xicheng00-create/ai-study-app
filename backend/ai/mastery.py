"""掌握度 M 与四态（Design Spec §3.5，PROG-007/008，F3 数据正确性）。

百分制 M = Σ(wᵢ·score_earnedᵢ)/Σ(wᵢ·points_possibleᵢ)×100，wᵢ=0.5^间隔周数；
聚合该章「最新已发布 version」的 attempts（F3，避免重出题污染）+ 自主练习
practice_questions（已作答，同权重，任务书定义 A）。
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


def effective_score(row) -> float:
    """教师覆核后以 reviewed_score 为准，否则取 AI 实际得分（QUIZ-009）。"""
    if row["is_reviewed"] and row["reviewed_score"] is not None:
        return float(row["reviewed_score"])
    return float(row["score"]) if row["score"] is not None else 0.0


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
    """返回 {m, attempts, latest_version}；m=None 表示未评估。

    M 聚合两部分（同一条加权公式，任务书定义 A）：
    1) 该章最新 published version 的测评 attempts（F3）；
    2) 该章自主练习 practice_questions（answered_at 非空，earned=score、possible=points）。
    仅当两者皆无作答时才返回 m=None（未评估）。
    """
    latest = latest_version_for_chapter(con, chapter_id)
    total_w = 0.0
    earned_w = 0.0
    attempts = 0

    # 测评：最新已发布 version（F3，避免重出题污染）
    if latest > 0:
        rows = con.execute(
            "SELECT a.score, a.created_at, a.is_reviewed, a.reviewed_score,"
            " q.points AS points"
            " FROM attempts a JOIN questions q ON q.id=a.question_id"
            " WHERE a.user_id=? AND a.chapter_id=? AND a.quiz_version=?",
            (user_id, chapter_id, latest),
        ).fetchall()
        for r in rows:
            w = _weight(r["created_at"])
            pts = float(r["points"]) if r["points"] else 0.0
            earned_w += w * effective_score(r)
            total_w += w * pts
        attempts += len(rows)

    # 自主练习：已作答题目（按 answered_at 计时衰减，与测评同权重）
    prows = con.execute(
        "SELECT pq.score, pq.points, pq.answered_at"
        " FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=? AND pq.chapter_id=? AND pq.answered_at IS NOT NULL",
        (user_id, chapter_id),
    ).fetchall()
    for r in prows:
        w = _weight(r["answered_at"])
        pts = float(r["points"]) if r["points"] else 0.0
        earned_w += w * (float(r["score"]) if r["score"] is not None else 0.0)
        total_w += w * pts
    attempts += len(prows)

    if attempts == 0:
        return {"m": None, "attempts": 0, "latest_version": latest}
    m = round(earned_w / total_w * 100, 1) if total_w > 0 else None
    return {"m": m, "attempts": attempts, "latest_version": latest}


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
