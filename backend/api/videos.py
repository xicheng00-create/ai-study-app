"""共享卡片视频：学生查询、入队及状态。"""
import json

from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok

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


@videos_bp.post("/batch")
@jwt_required
@role_required("student")
def batch_videos():
    data = request.get_json(silent=True) or {}
    ids = data.get("card_ids")
    if not isinstance(ids, list) or any(not isinstance(cid, str) or len(cid) > 128 for cid in ids) or len(ids) > 100:
        return e_input("card_ids 必须是最多 100 个卡片 ID 的数组")
    ids = list(dict.fromkeys(ids))
    con = get_db()
    existing = con.execute("SELECT id FROM card_video_batches WHERE user_id=? AND card_ids_json=? AND status='active' ORDER BY created_at DESC LIMIT 1", (g.user_id, json.dumps(sorted(ids), ensure_ascii=False))).fetchone()
    if existing:
        bid = existing["id"]
        con.commit()
        return ok(_batch_state(con, bid))
    bid = models.new_id()
    now = models.utcnow()
    con.execute("INSERT INTO card_video_batches(id,user_id,card_ids_json,total,created_at,status) VALUES(?,?,?,?,?,'pending')", (bid, g.user_id, json.dumps(sorted(ids), ensure_ascii=False), len(ids), now))
    skipped = queued = invalid = 0
    for cid in ids:
        if not _visible_card(con, cid):
            invalid += 1
            continue
        row = _video(con, cid)
        if row and row["status"] == "ready":
            skipped += 1
        elif row and row["status"] in ("queued", "generating"):
            pass
        else:
            card = con.execute("SELECT id,chapter_id,front FROM knowledge_cards WHERE id=?", (cid,)).fetchone()
            if row:
                con.execute("UPDATE card_videos SET status='queued',error=NULL,requested_by=?,requested_at=? WHERE id=? AND status='failed'", (g.user_id, now, row["id"]))
            else:
                vid = models.new_id()
                con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_by,requested_at) VALUES(?,?,?,'queued',?,?,?)", (vid, cid, card["chapter_id"], card["front"], g.user_id, now))
                row = con.execute("SELECT * FROM card_videos WHERE id=?", (vid,)).fetchone()
            queued += 1
        row = _video(con, cid)
        if row:
            con.execute("INSERT OR IGNORE INTO card_video_batch_items(batch_id,card_id,video_id) VALUES(?,?,?)", (bid, cid, row["id"]))
            if row["status"] != "ready" and not con.execute("SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='batch'", (g.user_id, cid)).fetchone():
                con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,batch_id,created_at) VALUES(?,?,?,?, 'batch',1,?,?)", (models.new_id(), row["id"], cid, g.user_id, bid, now))
    con.execute("UPDATE card_video_batches SET status='active' WHERE id=?", (bid,))
    con.commit()
    state = _batch_state(con, bid)
    if state["pending"] == 0:
        con.execute("UPDATE card_video_batches SET status='complete' WHERE id=?", (bid,))
        con.commit()
    return ok({**state, "skipped": skipped, "queued": queued, "invalid": invalid})


def _batch_state(con, batch_id):
    counts = con.execute("SELECT SUM(CASE WHEN v.status='ready' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN v.status IN ('queued','generating') THEN 1 ELSE 0 END) pending,SUM(CASE WHEN v.status='failed' THEN 1 ELSE 0 END) failed FROM card_video_batch_items i JOIN card_videos v ON v.id=i.video_id WHERE i.batch_id=?", (batch_id,)).fetchone()
    batch = con.execute("SELECT total FROM card_video_batches WHERE id=?", (batch_id,)).fetchone()
    ready, pending, failed = (int(counts[k] or 0) for k in ("ready", "pending", "failed"))
    if not pending:
        con.execute("UPDATE card_video_batches SET status='complete' WHERE id=? AND status='active'", (batch_id,))
        con.commit()
    return {"batch_id": batch_id, "total": batch["total"], "ready": ready, "pending": pending, "failed": failed, "status": "pending" if pending else "complete"}


@videos_bp.get("/batch/<batch_id>")
@jwt_required
@role_required("student")
def batch_status(batch_id):
    con = get_db()
    row = con.execute("SELECT id FROM card_video_batches WHERE id=? AND user_id=?", (batch_id, g.user_id)).fetchone()
    if not row:
        return e_not_found()
    return ok(_batch_state(con, batch_id))


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
        if row["status"] in ("queued", "generating"):
            if not con.execute("SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='manual'", (g.user_id, card_id)).fetchone():
                con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,created_at) VALUES(?,?,?,?, 'manual',1,?)", (models.new_id(), row["id"], card_id, g.user_id, models.utcnow()))
            con.commit()
        return ok(_state(row))
    if row:
        con.execute("UPDATE card_videos SET status='queued', error=NULL, requested_by=?, requested_at=? WHERE id=? AND status='failed'", (g.user_id, models.utcnow(), row["id"]))
    else:
        con.execute("INSERT OR IGNORE INTO card_videos(id,core_card_id,chapter_id,status,title,requested_by,requested_at) SELECT ?,id,chapter_id,'queued',front,?,? FROM knowledge_cards WHERE id=?", (models.new_id(), g.user_id, models.utcnow(), card_id))
    con.commit()
    queued_row = _video(con, card_id)
    if queued_row and queued_row["status"] in ("queued", "generating"):
        if not con.execute("SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='manual'", (g.user_id, card_id)).fetchone():
            con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,created_at) VALUES(?,?,?,?, 'manual',1,?)", (models.new_id(), queued_row["id"], card_id, g.user_id, models.utcnow()))
        con.commit()
    return ok(_state(queued_row))


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
