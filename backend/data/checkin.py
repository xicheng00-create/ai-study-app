"""每日打卡与连胜判定（CHECKIN-001~008）。

服务端唯一判定，幂等：daily_checkins UNIQUE(user_id, checkin_date)。
时区统一走 timeutil.shanghai_date()（UTC+8），与班级榜 today_* 口径一致。
"""
import random
from datetime import timedelta

from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED

from data import models, timeutil

# 档③低掌握度排序权重：越小越不熟（无 review 行的卡归一为 new）
_STATUS_WEIGHT = {"new": 0, "learning": 1, "reviewing": 2, "mastered": 3}


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


def build_today_deck(con, user_id, limit=None, mode="task", rng=None) -> dict:
    """今日卡组（CHECKIN-005/009/010/011）三档装配：①未学习 → ②到期复习 → ③低掌握度随机补足。

    只要库中存在「已发布章节的卡」，cards 必非空（永不返回空 → 前端不卡死）。
    mode="extra" 排除今日已复习过的卡（额外组不承诺凑满 limit）。
    """
    limit = limit or TASK_CARDS_REQUIRED
    if mode not in ("task", "extra"):
        mode = "task"  # 白名单回落，不报错
    rng = rng or random.Random()
    today = timeutil.today_str()

    rows = con.execute(
        "SELECT kc.id, kc.chapter_id, kc.sub_concept, kc.front, kc.back,"
        " kr.learn_count, kr.interval_days, kr.next_review_at, kr.status, kr.last_review_at"
        " FROM knowledge_cards kc"
        " LEFT JOIN knowledge_reviews kr ON kr.card_id = kc.id AND kr.user_id = ?"
        " WHERE kc.chapter_id IN (SELECT id FROM chapters WHERE status='published')"
        " ORDER BY kc.chapter_id, kc.rowid",
        (user_id,),
    ).fetchall()
    has_published = len(rows) > 0

    # 无 review 行归一：视为未学（status='new'、learn_count=0、interval_days=0、next_review_at=None）
    cards = []
    for r in rows:
        cards.append({
            "id": r["id"],
            "chapter_id": r["chapter_id"],
            "sub_concept": r["sub_concept"],
            "front": r["front"],
            "back": r["back"],
            "learn_count": int(r["learn_count"] or 0),
            "interval_days": int(r["interval_days"] or 0),
            "next_review_at": r["next_review_at"],
            "status": r["status"] or "new",
            "last_review_at": r["last_review_at"],
        })

    # extra：先排除今日已复习过的卡（避免重复劳动刷进度）
    if mode == "extra":
        cards = [c for c in cards if not (c["last_review_at"] and timeutil.shanghai_date(c["last_review_at"]) == today)]

    seen = set()
    picked = []

    # ① 未学习（learn_count=0，含无 review 行），按课程顺序（chapter_id, rowid）
    for c in cards:
        if c["learn_count"] == 0:
            seen.add(c["id"])
            picked.append(c)
            if len(picked) >= limit:
                break

    # ② 到期复习（已学过且非 mastered 且 next_review_at 已到），按到期时间升序
    if len(picked) < limit:
        due = [c for c in cards if c["id"] not in seen and c["learn_count"] > 0
               and c["status"] != "mastered" and c["next_review_at"]
               and timeutil.shanghai_date(c["next_review_at"]) <= today]
        due.sort(key=lambda c: c["next_review_at"])
        for c in due:
            seen.add(c["id"])
            picked.append(c)
            if len(picked) >= limit:
                break

    # ③ 低掌握度随机补足：候选按「不熟 → 熟」排序，取最差 POOL 池后洗牌补齐（CHECKIN-010）
    if len(picked) < limit:
        rest = [c for c in cards if c["id"] not in seen]
        rest.sort(key=lambda c: (_STATUS_WEIGHT.get(c["status"], 3), c["learn_count"], c["interval_days"]))
        pool = rest[:max(3 * limit, 20)]
        rng.shuffle(pool)
        for c in pool:
            seen.add(c["id"])
            picked.append(c)
            if len(picked) >= limit:
                break

    def _fmt(c):
        ch = con.execute("SELECT name FROM chapters WHERE id=?", (c["chapter_id"],)).fetchone()
        return {
            "id": c["id"],
            "chapter_id": c["chapter_id"],
            "chapter_name": ch["name"] if ch else "",
            "sub_concept": c["sub_concept"],
            "front": c["front"],
            "back": c["back"],
            "status": c["status"],
            "learn_count": c["learn_count"],
            "overdue": bool(
                c["next_review_at"] and c["status"] not in ("new", "mastered")
                and timeutil.shanghai_date(c["next_review_at"]) <= today
            ),
        }

    result = {
        "cards": [_fmt(c) for c in picked],
        "required": limit,
        "short": len(picked) < limit,
    }
    if mode == "extra":
        result["extra"] = True
        result["short"] = False  # 额外组不承诺凑满 limit
    # 真真空（库中无已发布章节的卡）才给明确引导；额外组学完属正常，不给 reason
    result["empty_reason"] = "" if (picked or has_published) else "no_published_cards"
    return result


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
