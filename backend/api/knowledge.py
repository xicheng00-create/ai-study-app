"""共享知识卡片及学生个人间隔复习状态。"""
from ai import knowledge
from ai.review_sched import next_interval, next_review_at_iso
from auth.jwt_utils import jwt_required, role_required
from config import SESSION_DECK_MAX
from data import checkin, models, timeutil
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, e_not_found, ok
from middleware.rate_limit import rate_limit

knowledge_bp = Blueprint("knowledge_bp", __name__, url_prefix="/api/knowledge")


def _card(row):
    # 先转 dict：sqlite3.Row 没有 .get()，而 topic 只在带 card_topics 的查询里存在
    src = dict(row)
    d = {k: src[k] for k in ("id", "chapter_id", "sub_concept", "front", "back",
        "learn_count", "interval_days", "next_review_at", "status", "last_review_at")}
    # 主题分组标签（KNOW-008，v2.7.0）：仅用于浏览归类；未归类时为空串，前端回退单组
    d["topic"] = src.get("topic", "")
    return d


# 卡片查询统一带主题（card_topics 可能为空表 → LEFT JOIN 后 topic 为 NULL，COALESCE 兜 0 行）
_CARD_COLS = ("kc.id,kc.chapter_id,kc.sub_concept,kc.front,kc.back,kr.learn_count,kr.interval_days,"
              "kr.next_review_at,kr.status,kr.last_review_at,COALESCE(ct.topic,'') AS topic")
_CARD_FROM = "knowledge_cards kc JOIN knowledge_reviews kr ON kr.card_id=kc.id LEFT JOIN card_topics ct ON ct.card_id=kc.id"


def _published(con, chapter_id):
    return con.execute("SELECT id FROM chapters WHERE id=? AND status='published'", (chapter_id,)).fetchone()


def _review(con, card_id):
    row = con.execute("SELECT * FROM knowledge_reviews WHERE card_id=? AND user_id=?", (card_id, g.user_id)).fetchone()
    if row is None:
        now = models.utcnow()
        con.execute("INSERT INTO knowledge_reviews (id,card_id,user_id,next_review_at,created_at) VALUES (?,?,?,?,?)", (models.new_id(), card_id, g.user_id, now, now))
        row = con.execute("SELECT * FROM knowledge_reviews WHERE card_id=? AND user_id=?", (card_id, g.user_id)).fetchone()
    return row


@knowledge_bp.route("/generate", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def generate():
    data = request.get_json(silent=True) or {}; ids = data.get("chapter_ids") or []
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids): return e_input("请至少选择一章")
    con = get_db()
    for cid in ids:
        if not _published(con, cid): return e_not_found("章节不存在或未发布")
        knowledge.ensure_chapter_cards(cid)
    cid = ids[0]
    return cards(cid)


@knowledge_bp.route("/overview", methods=["GET"])
@jwt_required
@role_required("student")
def overview():
    """知识卡片总览（KNOW-003/004）。

    口径（v2.6.4 修正）：
    - today_due「今日待复习」= **已学过**（learn_count>0）且**已到期或逾期**且未掌握的卡；
      未学的卡单独计入 new，不再被算成「待复习」（旧口径把懒建的 new 行也算进去，
      导致刚发布章节时显示「今日待复习 = 全部卡片数」）。
    - deck_max：单次复习卡组上限（`config.SESSION_DECK_MAX`），随响应下发，前端不得硬编码。
    """
    con = get_db(); today = timeutil.today_str()
    rows = con.execute("SELECT kc.chapter_id,kr.status,kr.learn_count,kr.next_review_at FROM knowledge_reviews kr JOIN knowledge_cards kc ON kc.id=kr.card_id WHERE kr.user_id=?", (g.user_id,)).fetchall()
    groups = {}
    for row in rows:
        d = groups.setdefault(row["chapter_id"], {"new": 0, "learning": 0, "reviewing": 0, "mastered": 0, "total": 0, "today_due": 0})
        d[row["status"]] += 1; d["total"] += 1
        due_at = timeutil.shanghai_date(row["next_review_at"]) if row["next_review_at"] else today
        if row["status"] != "mastered" and (row["learn_count"] or 0) > 0 and due_at <= today:
            d["today_due"] += 1
    return ok({"chapters": [{"chapter_id": cid, "counts": counts} for cid, counts in groups.items()],
               "deck_max": SESSION_DECK_MAX})


@knowledge_bp.route("/today", methods=["GET"])
@jwt_required
@role_required("student")
def today_deck():
    """今日任务卡组（CHECKIN-005/009/010/011）：?mode=task|extra，非法值回落 task，不返回 4xx。"""
    mode = (request.args.get("mode") or "task").strip()
    if mode not in ("task", "extra"):
        mode = "task"
    raw = (request.args.get("chapter_ids") or "").strip()
    chapter_ids = [x for x in raw.split(",") if x]      # v2.6.5：范围由学生自定（CHECKIN-013）
    con = get_db()
    deck = checkin.build_today_deck(con, g.user_id, mode=mode, chapter_ids=chapter_ids)
    return ok(deck)


@knowledge_bp.route("/<chapter_id>", methods=["GET"])
@jwt_required
@role_required("student")
def cards(chapter_id):
    con = get_db()
    if not _published(con, chapter_id): return e_not_found("章节不存在或未发布")
    shared = con.execute("SELECT id FROM knowledge_cards WHERE chapter_id=?", (chapter_id,)).fetchall()
    for card in shared: _review(con, card["id"])
    con.commit()
    rows = con.execute(f"SELECT {_CARD_COLS} FROM {_CARD_FROM} WHERE kc.chapter_id=? AND kr.user_id=? ORDER BY CASE kr.status WHEN 'new' THEN 0 WHEN 'learning' THEN 1 WHEN 'reviewing' THEN 2 ELSE 3 END,kr.next_review_at", (chapter_id, g.user_id)).fetchall()
    return ok({"chapter_id": chapter_id, "cards": [_card(r) for r in rows], "deck_max": SESSION_DECK_MAX})


@knowledge_bp.route("/<card_id>/review", methods=["POST"])
@jwt_required
@role_required("student")
def review(card_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("remembered"), bool): return e_input("remembered 必须为布尔值")
    con = get_db()
    if con.execute("SELECT id FROM knowledge_cards WHERE id=?", (card_id,)).fetchone() is None: return e_forbidden("只能复习本人卡片")
    row = _review(con, card_id); remembered = data["remembered"]
    status = ({"new":"learning", "learning":"reviewing", "reviewing":"mastered", "mastered":"mastered"}[row["status"]]
              if remembered else ("new" if row["status"] == "new" else "learning"))
    interval = next_interval(remembered, row["interval_days"]); now = models.utcnow()
    con.execute("UPDATE knowledge_reviews SET learn_count=learn_count+1,interval_days=?,status=?,next_review_at=?,last_review_at=? WHERE id=?", (interval, status, next_review_at_iso(interval), now, row["id"])); con.commit()
    # 打卡判定触发点：复习提交成功后服务端惰性评估（CHECKIN-004）
    checkin.evaluate_and_maybe_complete(con, g.user_id)
    updated = con.execute(f"SELECT {_CARD_COLS} FROM {_CARD_FROM} WHERE kr.id=?", (row["id"],)).fetchone()
    return ok({"card": _card(updated)})
