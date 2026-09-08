"""学生个人知识卡片：生成、浏览和间隔复习。"""
from ai import knowledge
from ai.review_sched import next_interval, next_review_at_iso
from auth.jwt_utils import jwt_required, role_required
from data import models, timeutil
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, e_not_found, ok
from middleware.rate_limit import rate_limit

knowledge_bp = Blueprint("knowledge_bp", __name__, url_prefix="/api/knowledge")


def _card(row):
    return {k: row[k] for k in ("id", "chapter_id", "sub_concept", "front", "back",
        "learn_count", "interval_days", "next_review_at", "status", "last_review_at", "created_at")}


def _published(con, chapter_id):
    return con.execute("SELECT id FROM chapters WHERE id=? AND status='published'", (chapter_id,)).fetchone()


@knowledge_bp.route("/generate", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def generate():
    data = request.get_json(silent=True) or {}
    ids = data.get("chapter_ids") or []
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
        return e_input("请至少选择一章")
    con = get_db()
    for cid in ids:
        if not _published(con, cid):
            return e_not_found("章节不存在或未发布")
    # 卡片按章保存，已有卡直接复用，避免重复调用 Agent。
    cid = ids[0]
    rows = con.execute("SELECT * FROM knowledge_cards WHERE user_id=? AND chapter_id=?", (g.user_id, cid)).fetchall()
    if rows:
        return ok({"chapter_id": cid, "cards": [_card(r) for r in rows]})
    cards = knowledge.generate_knowledge_cards([cid])
    if not cards:
        return e_input("生成失败请重试")
    now = models.utcnow()
    seen_fronts = set()
    for card in cards:
        if card["front"] in seen_fronts:
            continue
        seen_fronts.add(card["front"])
        con.execute("INSERT INTO knowledge_cards (id,user_id,chapter_id,sub_concept,front,back,next_review_at,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (models.new_id(), g.user_id, cid, card["sub_concept"], card["front"], card["back"], now, "new", now))
    con.commit()
    rows = con.execute("SELECT * FROM knowledge_cards WHERE user_id=? AND chapter_id=?", (g.user_id, cid)).fetchall()
    return ok({"chapter_id": cid, "cards": [_card(r) for r in rows]})


@knowledge_bp.route("/overview", methods=["GET"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def overview():
    con = get_db(); today = timeutil.today_str()
    rows = con.execute("SELECT chapter_id,status,next_review_at FROM knowledge_cards WHERE user_id=?", (g.user_id,)).fetchall()
    groups = {}
    for row in rows:
        d = groups.setdefault(row["chapter_id"], {"new": 0, "learning": 0, "reviewing": 0, "mastered": 0, "total": 0, "today_due": 0})
        d[row["status"]] += 1; d["total"] += 1
        if row["status"] != "mastered" and timeutil.shanghai_date(row["next_review_at"]) == today: d["today_due"] += 1
    return ok({"chapters": [{"chapter_id": cid, "counts": counts} for cid, counts in groups.items()]})


@knowledge_bp.route("/<chapter_id>", methods=["GET"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def cards(chapter_id):
    con = get_db()
    if not _published(con, chapter_id): return e_not_found("章节不存在或未发布")
    rows = con.execute("SELECT * FROM knowledge_cards WHERE user_id=? AND chapter_id=? ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'learning' THEN 1 WHEN 'reviewing' THEN 2 ELSE 3 END, next_review_at", (g.user_id, chapter_id)).fetchall()
    return ok({"chapter_id": chapter_id, "cards": [_card(r) for r in rows]})


@knowledge_bp.route("/<card_id>/review", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def review(card_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("remembered"), bool): return e_input("remembered 必须为布尔值")
    con = get_db(); row = con.execute("SELECT * FROM knowledge_cards WHERE id=? AND user_id=?", (card_id, g.user_id)).fetchone()
    if row is None: return e_forbidden("只能复习本人卡片")
    remembered = data["remembered"]
    if remembered:
        status = {"new":"learning", "learning":"reviewing", "reviewing":"mastered", "mastered":"mastered"}[row["status"]]
    else:
        status = "new" if row["status"] == "new" else "learning"
    interval = next_interval(remembered, row["interval_days"])
    now = models.utcnow()
    con.execute("UPDATE knowledge_cards SET learn_count=learn_count+1,interval_days=?,status=?,next_review_at=?,last_review_at=? WHERE id=?", (interval, status, next_review_at_iso(interval), now, card_id)); con.commit()
    return ok({"card": _card(con.execute("SELECT * FROM knowledge_cards WHERE id=?", (card_id,)).fetchone())})
