"""共享卡片视频：学生查询、入队及状态。"""
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g
from middleware.errors import e_not_found, ok

videos_bp = Blueprint("videos_bp", __name__, url_prefix="/api/videos")


def _visible_card(con, card_id):
    return con.execute("SELECT kc.id FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id WHERE kc.id=? AND ch.status='published'", (card_id,)).fetchone()


def _video(con, card_id):
    return con.execute("SELECT v.* FROM card_videos v LEFT JOIN card_video_links l ON l.video_id=v.id WHERE (v.core_card_id=? OR l.card_id=?) ORDER BY CASE WHEN v.status='ready' THEN 0 ELSE 1 END LIMIT 1", (card_id, card_id)).fetchone()


def _state(row):
    if row is None:
        return {"status": "none", "video_id": None, "url": None, "duration_s": None, "title": None, "core_card_id": None}
    return {"status": row["status"], "video_id": row["id"],
            "url": "/media/videos/" + row["file_name"] if row["status"] == "ready" and row["file_name"] else None,
            "duration_s": row["duration_s"], "title": row["title"], "core_card_id": row["core_card_id"]}


@videos_bp.get("/card/<card_id>")
@jwt_required
@role_required("student")
def card_status(card_id):
    con = get_db()
    if len(card_id) > 128 or not _visible_card(con, card_id):
        return e_not_found("卡片不存在或章节未发布")
    return ok(_state(_video(con, card_id)))


@videos_bp.post("/card/<card_id>/request")
@jwt_required
@role_required("student")
def request_video(card_id):
    con = get_db()
    if len(card_id) > 128 or not _visible_card(con, card_id):
        return e_not_found("卡片不存在或章节未发布")
    row = _video(con, card_id)
    if row and row["status"] != "failed":
        return ok(_state(row))
    if row:
        con.execute("UPDATE card_videos SET status='queued', error=NULL, requested_by=?, requested_at=? WHERE id=? AND status='failed'", (g.user_id, models.utcnow(), row["id"]))
    else:
        con.execute("INSERT OR IGNORE INTO card_videos(id,core_card_id,chapter_id,status,title,requested_by,requested_at) SELECT ?,id,chapter_id,'queued',front,?,? FROM knowledge_cards WHERE id=?", (models.new_id(), g.user_id, models.utcnow(), card_id))
    con.commit()
    return ok(_state(_video(con, card_id)))


@videos_bp.get("")
@jwt_required
@role_required("student")
def list_videos():
    rows = get_db().execute("SELECT v.*,ch.name AS chapter_name,kc.front,COALESCE(ct.topic,'') AS topic FROM card_videos v JOIN chapters ch ON ch.id=v.chapter_id AND ch.status='published' JOIN knowledge_cards kc ON kc.id=v.core_card_id LEFT JOIN card_topics ct ON ct.card_id=kc.id WHERE v.status='ready' ORDER BY ch.name,v.ready_at DESC").fetchall()
    return ok([{**_state(r), "chapter_id": r["chapter_id"], "chapter_name": r["chapter_name"], "front": r["front"], "topic": r["topic"]} for r in rows])


@videos_bp.get("/<video_id>/status")
@jwt_required
@role_required("student")
def video_status(video_id):
    if len(video_id) > 128:
        return e_not_found()
    row = get_db().execute("SELECT v.* FROM card_videos v JOIN chapters ch ON ch.id=v.chapter_id AND ch.status='published' WHERE v.id=?", (video_id,)).fetchone()
    if not row:
        return e_not_found()
    return ok(_state(row))
