"""UNI-MASTER：卡级主题证据与章/书/学科统一 rollup（PROG-007~012）。"""
import math
from datetime import datetime, timezone

STATE_SCORES = {"new": 0, "learning": 40, "reviewing": 70, "mastered": 100}
LABELS = {"master": "已掌握", "progress": "进行中", "weak": "薄弱", "na": "未评估"}


def _weight(iso):
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except (TypeError, ValueError):
        days = 0
    return 0.5 ** (days / 7)


def effective_score(row):
    if row["is_reviewed"] and row["reviewed_score"] is not None:
        return float(row["reviewed_score"])
    return float(row["score"] or 0)


def latest_version_for_chapter(con, chapter_id):
    rows = con.execute(
        "SELECT version FROM quizzes WHERE status='published' AND chapter_ids LIKE ?",
        (f'%"{chapter_id}"%',),
    ).fetchall()
    return max((r["version"] for r in rows), default=0)


def _evidence(con, user_id, chapter_ids):
    """仅按 (章, 原值主题) 聚合；历史空主题事件绝不回填。"""
    if not chapter_ids:
        return {}
    ph = ",".join("?" for _ in chapter_ids)
    events = {}
    versions = {cid: latest_version_for_chapter(con, cid) for cid in chapter_ids}
    rows = con.execute(
        "SELECT a.chapter_id, q.topic, a.score, a.is_reviewed, a.reviewed_score,"
        " a.created_at, q.points, a.quiz_version FROM attempts a"
        " JOIN questions q ON q.id=a.question_id WHERE a.user_id=?"
        f" AND a.chapter_id IN ({ph}) AND q.topic IS NOT NULL AND q.topic!=''",
        (user_id, *chapter_ids),
    ).fetchall()
    for r in rows:
        if r["quiz_version"] == versions[r["chapter_id"]] and versions[r["chapter_id"]] > 0:
            events.setdefault((r["chapter_id"], r["topic"]), []).append(
                (effective_score(r), r["points"], r["created_at"]))
    rows = con.execute(
        "SELECT pq.chapter_id, pq.topic, pq.score, pq.points, pq.answered_at"
        " FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        f" WHERE ps.user_id=? AND pq.chapter_id IN ({ph})"
        " AND pq.answered_at IS NOT NULL AND pq.topic IS NOT NULL AND pq.topic!=''",
        (user_id, *chapter_ids),
    ).fetchall()
    for r in rows:
        events.setdefault((r["chapter_id"], r["topic"]), []).append(
            (float(r["score"] or 0), r["points"], r["answered_at"]))
    result = {}
    for key, values in events.items():
        possible = sum(_weight(t) * float(p or 0) for _, p, t in values)
        earned = sum(_weight(t) * e for e, _, t in values)
        result[key] = (round(100 * earned / possible) if possible else None, len(values))
    return result


def _cards(con, user_id, chapter_ids):
    if not chapter_ids:
        return []
    ph = ",".join("?" for _ in chapter_ids)
    rows = con.execute(
        "SELECT kc.id, kc.chapter_id, ct.topic, COALESCE(kr.status,'new') AS status"
        " FROM knowledge_cards kc LEFT JOIN card_topics ct ON ct.card_id=kc.id"
        " LEFT JOIN knowledge_reviews kr ON kr.card_id=kc.id AND kr.user_id=?"
        f" WHERE kc.chapter_id IN ({ph})", (user_id, *chapter_ids),
    ).fetchall()
    evidence = _evidence(con, user_id, chapter_ids)
    out = []
    for r in rows:
        acc, count = evidence.get((r["chapter_id"], r["topic"]), (None, 0))
        score = STATE_SCORES[r["status"]]
        out.append({"id": r["id"], "chapter_id": r["chapter_id"],
                    "state": r["status"], "m": round((score + acc) / 2) if acc is not None else score,
                    "acc": acc, "evidence": count > 0, "events": count})
    return out


def card_mastery(con, user_id, chapter_id):
    return _cards(con, user_id, [chapter_id])


def can_master_card(card):
    """调度条件之外的证据门槛。"""
    return card["events"] >= 2 and card["acc"] is not None and card["acc"] >= 80


def mastery_state(m, evidence_cards=0, cards_total=0, learned=None):
    if m is None or learned == 0:
        return "na"
    if m >= 80 and evidence_cards >= max(2, math.ceil(cards_total * 0.2)):
        return "master"
    if m >= 50:
        return "progress"
    return "weak"


def state_label(state):
    return LABELS.get(state, state)


def rollup(cards):
    """废除旧口径：已掌握卡按 5 分仅奖不罚；测评/练习分数直接对层级 M 计分。"""
    learned_cards = [c for c in cards if c["state"] != "new"]
    learned, total = len(learned_cards), len(cards)
    m = round(sum(c["m"] for c in learned_cards) / learned) if learned else None
    evidence_cards = sum(bool(c["evidence"]) for c in cards)
    state = mastery_state(m, evidence_cards, total, learned)
    return {"m": m, "learned": learned, "cards_total": total,
            "coverage": round(100 * learned / total) if total else 0,
            "evidence_cards": evidence_cards, "state": state, "state_label": state_label(state)}


def compute_mastery(con, user_id, chapter_id):
    return rollup(card_mastery(con, user_id, chapter_id))


def compute_book_mastery(con, user_id, folder):
    ids = [r["id"] for r in con.execute("SELECT id FROM chapters WHERE folder=?", (folder,))]
    return rollup(_cards(con, user_id, ids))


def compute_subject_mastery(con, user_id):
    ids = [r["id"] for r in con.execute("SELECT id FROM chapters")]
    return rollup(_cards(con, user_id, ids))


def class_mastery(student_masteries):
    students = list(student_masteries)
    assessed = [s["m"] for s in students if s["state"] != "na" and s["m"] is not None]
    return {"m": round(sum(assessed) / len(assessed)) if assessed else None,
            "coverage": round(sum(s["coverage"] for s in students) / len(students)) if students else 0,
            "assessed": len(assessed), "total": len(students)}
