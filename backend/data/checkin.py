"""每日打卡与连胜判定（CHECKIN-001~008）。

服务端唯一判定，幂等：daily_checkins UNIQUE(user_id, checkin_date)。
时区统一走 timeutil.shanghai_date()（UTC+8），与班级榜 today_* 口径一致。
"""
from datetime import timedelta

from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED

from data import models, timeutil


def today_str() -> str:
    return timeutil.today_str()


def _yesterday_str() -> str:
    return (timeutil.shanghai_now() - timedelta(days=1)).strftime("%Y-%m-%d")


def counts_today(con, user_id) -> dict:
    """今日（UTC+8）distinct 复习卡片数 + distinct 已作答练习题数。"""
    today = timeutil.today_str()
    cards = set()
    for r in con.execute(
        "SELECT card_id, last_review_at FROM knowledge_reviews"
        " WHERE user_id=? AND last_review_at IS NOT NULL",
        (user_id,),
    ).fetchall():
        if timeutil.shanghai_date(r["last_review_at"]) == today:
            cards.add(r["card_id"])

    questions = set()
    for r in con.execute(
        "SELECT pq.id AS qid, pq.answered_at FROM practice_questions pq"
        " JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=? AND pq.answered_at IS NOT NULL AND COALESCE(pq.user_answer,'') != ''",
        (user_id,),
    ).fetchall():
        if timeutil.shanghai_date(r["answered_at"]) == today:
            questions.add(r["qid"])

    return {"cards": len(cards), "questions": len(questions)}


def streak_info(con, user_id) -> dict:
    """连胜存活模型：done（今日达标）/ pending（昨日达标待续）/ broken（断连归零）。"""
    today = timeutil.today_str()
    longest_row = con.execute(
        "SELECT MAX(streak_after) AS m FROM daily_checkins WHERE user_id=?", (user_id,)
    ).fetchone()
    longest = int(longest_row["m"] or 0)

    row_today = con.execute(
        "SELECT * FROM daily_checkins WHERE user_id=? AND checkin_date=?", (user_id, today)
    ).fetchone()
    if row_today:
        return {
            "done": True, "state": "done", "streak": int(row_today["streak_after"]),
            "longest": longest, "alive": True, "today": today,
        }

    row_yesterday = con.execute(
        "SELECT * FROM daily_checkins WHERE user_id=? AND checkin_date=?",
        (user_id, _yesterday_str()),
    ).fetchone()
    if row_yesterday:
        return {
            "done": False, "state": "pending", "streak": int(row_yesterday["streak_after"]),
            "longest": longest, "alive": True, "today": today,
        }
    return {
        "done": False, "state": "broken", "streak": 0,
        "longest": longest, "alive": False, "today": today,
    }


def evaluate_and_maybe_complete(con, user_id) -> dict:
    """惰性幂等评估：达到阈值则写入当日打卡行（单日只记一次）并触发 streak_done 通知。"""
    today = timeutil.today_str()
    existing = con.execute(
        "SELECT id FROM daily_checkins WHERE user_id=? AND checkin_date=?", (user_id, today)
    ).fetchone()
    if existing:
        return streak_info(con, user_id)

    c = counts_today(con, user_id)
    if c["cards"] < TASK_CARDS_REQUIRED or c["questions"] < TASK_QUESTIONS_REQUIRED:
        return streak_info(con, user_id)

    prev = con.execute(
        "SELECT streak_after FROM daily_checkins WHERE user_id=? AND checkin_date=?",
        (user_id, _yesterday_str()),
    ).fetchone()
    streak_after = (int(prev["streak_after"]) + 1) if prev else 1
    con.execute(
        "INSERT INTO daily_checkins (id, user_id, checkin_date, cards_done, questions_done,"
        " streak_after, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (models.new_id(), user_id, today, c["cards"], c["questions"], streak_after, models.utcnow()),
    )
    con.commit()

    # 首次达标 → 本人即时通知（NOTIF-007）
    from services.notify import notify_users

    notify_users(
        con, [user_id], "streak_done",
        "🔥 连胜 +1", f"已连续打卡 {streak_after} 天",
        image="", ref_kind="checkin", ref_id=today,
    )
    return streak_info(con, user_id)


def build_today_deck(con, user_id, limit=None) -> dict:
    """今日卡组：到期复习卡优先 → 未学新卡按章节补齐（跨章，上限 limit）。"""
    limit = limit or TASK_CARDS_REQUIRED
    today = timeutil.today_str()

    # 1) 到期复习卡（next_review_at ≤ 今天，UTC+8，非 mastered 优先）
    due = []
    for r in con.execute(
        "SELECT kc.id, kc.chapter_id, kc.sub_concept, kc.front, kc.back,"
        " kr.learn_count, kr.interval_days, kr.next_review_at, kr.status, kr.last_review_at"
        " FROM knowledge_cards kc JOIN knowledge_reviews kr ON kr.card_id=kc.id"
        " WHERE kr.user_id=? AND kr.status != 'mastered'",
        (user_id,),
    ).fetchall():
        if r["next_review_at"] and timeutil.shanghai_date(r["next_review_at"]) <= today:
            due.append(r)

    # 2) 未学过的新卡（无 knowledge_reviews 行），按章节顺序补齐
    new = con.execute(
        "SELECT kc.id, kc.chapter_id, kc.sub_concept, kc.front, kc.back,"
        " NULL AS learn_count, NULL AS interval_days, NULL AS next_review_at,"
        " 'new' AS status, NULL AS last_review_at"
        " FROM knowledge_cards kc"
        " WHERE NOT EXISTS (SELECT 1 FROM knowledge_reviews kr WHERE kr.card_id=kc.id AND kr.user_id=?)"
        " AND kc.chapter_id IN (SELECT id FROM chapters WHERE status='published')"
        " ORDER BY kc.chapter_id, kc.rowid",
        (user_id,),
    ).fetchall()

    seen = set()
    picked = []
    for r in due + new:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        picked.append(r)
        if len(picked) >= limit:
            break

    def _fmt(r):
        ch = con.execute("SELECT name FROM chapters WHERE id=?", (r["chapter_id"],)).fetchone()
        return {
            "id": r["id"],
            "chapter_id": r["chapter_id"],
            "chapter_name": ch["name"] if ch else "",
            "sub_concept": r["sub_concept"],
            "front": r["front"],
            "back": r["back"],
            "status": r["status"],
            "overdue": bool(
                r["next_review_at"] and r["status"] not in ("new", "mastered")
                and timeutil.shanghai_date(r["next_review_at"]) <= today
            ),
        }

    return {"cards": [_fmt(r) for r in picked], "required": limit, "short": len(picked) < limit}


def _student_map(con):
    from api.class_bp import EXCLUDED_USERNAMES

    rows = con.execute(
        "SELECT id, username, display_name, avatar FROM users"
        " WHERE role='student' AND is_active=1 ORDER BY display_name, created_at"
    ).fetchall()
    return {r["id"]: r for r in rows if r["username"] not in EXCLUDED_USERNAMES}


def class_today(con, me_uid) -> dict:
    """班级「今日打卡」投影：每人打卡状态 / 连胜 / 今日进度 / 是否可提醒。"""
    today = timeutil.today_str()
    students = _student_map(con)

    out = []
    for uid, stu in students.items():
        c = counts_today(con, uid)
        info = streak_info(con, uid)
        checked_in = info["done"]
        out.append({
            "user_id": uid,
            "name": stu["display_name"] or stu["username"],
            "avatar": stu["avatar"] or "",
            "checked_in": checked_in,
            "cards": min(c["cards"], TASK_CARDS_REQUIRED),
            "questions": min(c["questions"], TASK_QUESTIONS_REQUIRED),
            "streak": info["streak"],
            "state": info["state"],
            "can_nudge": (not checked_in) and uid != me_uid,
        })

    out.sort(key=lambda r: (not r["checked_in"], -r["streak"], r["name"]))
    me = next((r for r in out if r["user_id"] == me_uid), None)
    return {"date": today, "students": out, "me": me}
