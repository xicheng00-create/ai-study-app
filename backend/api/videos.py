"""共享卡片视频：学生查询、入队及状态。"""
import json
import logging

from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from data.video_queue import enqueue
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok

videos_bp = Blueprint("videos_bp", __name__, url_prefix="/api/videos")


def _log_link_anomalies(con):
    # Do not silently mask missing/incorrect core links or orphan associations.
    rows = con.execute("""SELECT v.id FROM card_videos v
        WHERE NOT EXISTS (SELECT 1 FROM card_video_links l
          WHERE l.video_id=v.id AND l.card_id=v.core_card_id AND l.is_core=1)
        UNION SELECT l.video_id FROM card_video_links l
        LEFT JOIN card_videos v ON v.id=l.video_id
        LEFT JOIN knowledge_cards kc ON kc.id=l.card_id
        WHERE v.id IS NULL OR kc.id IS NULL OR
          (l.is_core=1 AND l.card_id!=v.core_card_id)""").fetchall()
    for row in rows:
        logging.getLogger(__name__).warning("video_link_anomaly video_id=%s", row[0])


def _visible_card(con, card_id):
    return con.execute("SELECT kc.id FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id WHERE kc.id=? AND ch.status='published'", (card_id,)).fetchone()


def _video(con, card_id):
    # core_card_id 是旧库的兼容回退；新库同时维护 card_video_links。
    return con.execute("SELECT v.* FROM card_videos v LEFT JOIN card_video_links l ON l.video_id=v.id WHERE (v.core_card_id=? OR l.card_id=?) ORDER BY CASE WHEN v.status='ready' THEN 0 ELSE 1 END LIMIT 1", (card_id, card_id)).fetchone()


def _video_links(con, video_id):
    """反向链接兼容旧视频：缺核心 link 时仍用 core_card_id 暴露核心卡。"""
    return con.execute("""SELECT * FROM (SELECT kc.id,kc.front,kc.sub_concept,kc.chapter_id,
        COALESCE(ct.topic,'全部卡片') topic,COALESCE(l.is_core,1) is_core
        FROM card_videos v JOIN knowledge_cards kc ON kc.id=v.core_card_id
        LEFT JOIN card_video_links l ON l.video_id=v.id AND l.card_id=kc.id
        LEFT JOIN card_topics ct ON ct.card_id=kc.id
        JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published'
        WHERE v.id=? AND v.status='ready'
        UNION ALL
        SELECT kc.id,kc.front,kc.sub_concept,kc.chapter_id,
        COALESCE(ct.topic,'全部卡片') topic,l.is_core
        FROM card_video_links l JOIN knowledge_cards kc ON kc.id=l.card_id
        LEFT JOIN card_topics ct ON ct.card_id=kc.id
        JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published'
        WHERE l.video_id=? AND l.card_id != (SELECT core_card_id FROM card_videos WHERE id=?)
        ) ORDER BY is_core DESC,id""", (video_id, video_id, video_id)).fetchall()



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
    canonical = json.dumps(sorted(ids), ensure_ascii=False)
    existing = con.execute("SELECT id FROM card_video_batches WHERE user_id=? AND card_ids_json=? AND status='active' ORDER BY created_at DESC LIMIT 1", (g.user_id, canonical)).fetchone()
    if existing:
        bid = existing["id"]
        con.commit()
        return ok(_batch_state(con, bid))
    bid = models.new_id()
    now = models.utcnow()
    con.execute("INSERT INTO card_video_batches(id,user_id,card_ids_json,total,created_at,status) VALUES(?,?,?,?,?,'pending')", (bid, g.user_id, canonical, len(ids), now))
    skipped = queued = invalid = 0
    for cid in ids:
        if not _visible_card(con, cid):
            invalid += 1
            continue
        row = _video(con, cid)
        if row and row["status"] == "ready":
            skipped += 1
            continue
        if row and row["status"] in ("queued", "generating"):
            pass
        else:
            row = enqueue(con, cid, g.user_id)
            queued += 1
        row = _video(con, cid)
        if row:
            con.execute("INSERT OR IGNORE INTO card_video_batch_items(batch_id,card_id,video_id) VALUES(?,?,?)", (bid, cid, row["id"]))
            if not con.execute("SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='batch' AND batch_id=?", (g.user_id, cid, bid)).fetchone():
                con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,batch_id,created_at) VALUES(?,?,?,?, 'batch',1,?,?)", (models.new_id(), row["id"], cid, g.user_id, bid, now))
    con.execute("UPDATE card_video_batches SET status='active' WHERE id=?", (bid,))
    con.commit()
    state = _batch_state(con, bid)
    return ok(state)


def _batch_state(con, batch_id):
    batch = con.execute("SELECT * FROM card_video_batches WHERE id=?", (batch_id,)).fetchone()
    ids = json.loads(batch["card_ids_json"])
    ready = pending = failed = skipped = invalid = queued = 0
    for cid in ids:
        if not _visible_card(con, cid):
            invalid += 1
            continue
        video = _video(con, cid)
        if video is None:
            invalid += 1
        elif video["status"] == "ready":
            ready += 1
            skipped += 1
        elif video["status"] == "failed":
            failed += 1
        else:
            pending += 1
            if con.execute("SELECT 1 FROM card_video_requests WHERE batch_id=? AND card_id=? AND source='batch'", (batch_id, cid)).fetchone():
                queued += 1
    if not pending:
        con.execute("UPDATE card_video_batches SET status='complete' WHERE id=? AND status='active'", (batch_id,))
        con.commit()
    queued = sum(1 for cid in ids if con.execute("SELECT 1 FROM card_video_requests r JOIN card_videos v ON v.id=r.video_id WHERE r.batch_id=? AND r.card_id=? AND r.source='batch' AND v.requested_by=?", (batch_id, cid, batch["user_id"])).fetchone())
    return {"batch_id": batch_id, "total": batch["total"], "ready": ready, "pending": pending,
            "failed": failed, "skipped": skipped, "queued": queued, "invalid": invalid,
            "status": "pending" if pending else "complete"}



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
    enqueue(con, card_id, g.user_id)
    con.commit()
    queued_row = _video(con, card_id)
    if queued_row and queued_row["status"] in ("queued", "generating"):
        if not con.execute("SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='manual'", (g.user_id, card_id)).fetchone():
            con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,created_at) VALUES(?,?,?,?, 'manual',1,?)", (models.new_id(), queued_row["id"], card_id, g.user_id, models.utcnow()))
        con.commit()
    return ok(_state(queued_row))


@videos_bp.get("/index")
@jwt_required
@role_required("student")
def video_index():
    con = get_db()
    _log_link_anomalies(con)
    cards = {}
    topics = {}
    chapters = {}
    topic_meta = {}
    rows = con.execute("""SELECT kc.id card_id,kc.chapter_id,v.id video_id,v.status,v.duration_s,v.core_card_id,
        COALESCE(link_count.n_cards,0) n_cards,
        COALESCE(ct.topic,'全部卡片') topic,MIN(ct.ord) OVER (PARTITION BY kc.chapter_id,COALESCE(ct.topic,'全部卡片')) topic_ord
        FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published'
        LEFT JOIN card_topics ct ON ct.card_id=kc.id
        LEFT JOIN card_videos v ON v.id=(SELECT cv.id FROM card_videos cv LEFT JOIN card_video_links l ON l.video_id=cv.id
          WHERE cv.core_card_id=kc.id OR l.card_id=kc.id ORDER BY CASE cv.status WHEN 'ready' THEN 0 WHEN 'queued' THEN 1 WHEN 'generating' THEN 2 ELSE 3 END LIMIT 1)
        LEFT JOIN (SELECT video_id,COUNT(DISTINCT card_id) n_cards FROM (
            SELECT video_id,card_id FROM card_video_links
            UNION SELECT id video_id,core_card_id card_id FROM card_videos) GROUP BY video_id) link_count ON link_count.video_id=v.id""").fetchall()
    for r in rows:
        cards[r["card_id"]] = {"video_id": r["video_id"], "status": r["status"] or "none", "duration_s": r["duration_s"],
                                "n_cards": r["n_cards"] or 0, "core_card_id": r["core_card_id"], "is_core": bool(r["video_id"] and r["card_id"] == r["core_card_id"])}
        meta = topic_meta.setdefault((r["chapter_id"], r["topic"]), {"ord": 2147483647, "cards_total": 0})
        meta["cards_total"] += 1
        meta["ord"] = min(meta["ord"], r["topic_ord"] if r["topic_ord"] is not None else 2147483647)
    groups = con.execute("""SELECT ch.id chapter_id,COALESCE(ct.topic,'全部卡片') topic,COUNT(DISTINCT kc.id) cards_total,
        COUNT(DISTINCT CASE WHEN v.status='ready' THEN kc.id END) cards_with_video,
        COUNT(DISTINCT CASE WHEN v.status='ready' AND v.core_card_id=kc.id THEN v.id END) videos
        FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published'
        LEFT JOIN card_topics ct ON ct.card_id=kc.id
        LEFT JOIN card_videos v ON v.id=(SELECT cv.id FROM card_videos cv LEFT JOIN card_video_links l ON l.video_id=cv.id
          WHERE cv.core_card_id=kc.id OR l.card_id=kc.id ORDER BY CASE cv.status WHEN 'ready' THEN 0 WHEN 'queued' THEN 1 WHEN 'generating' THEN 2 ELSE 3 END LIMIT 1)
        GROUP BY ch.id,COALESCE(ct.topic,'全部卡片')
        ORDER BY ch.order_no,ch.name,MIN(ct.ord),topic""").fetchall()
    for r in groups:
        topics[f"{r['chapter_id']}|{r['topic']}"] = {"videos": r["videos"], "cards_with_video": r["cards_with_video"], "cards_total": r["cards_total"],
                                                        "ord": topic_meta[(r["chapter_id"], r["topic"])]["ord"]}
        agg = chapters.setdefault(r["chapter_id"], {"videos": 0, "cards_with_video": 0, "cards_total": 0})
        agg["videos"] += r["videos"]
        agg["cards_with_video"] += r["cards_with_video"]
        agg["cards_total"] += r["cards_total"]
    linked_ids = {r[0] for r in con.execute("""SELECT DISTINCT card_id FROM (
        SELECT l.card_id FROM card_video_links l JOIN knowledge_cards kc ON kc.id=l.card_id
        JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published'
        UNION SELECT v.core_card_id FROM card_videos v JOIN knowledge_cards kc ON kc.id=v.core_card_id
        JOIN chapters ch ON ch.id=kc.chapter_id AND ch.status='published')""").fetchall()}
    linked_cards = {cid: cards[cid] for cid in linked_ids if cid in cards}
    return ok({"cards": linked_cards, "all_cards": cards, "topics": topics, "chapters": chapters})


@videos_bp.get("/<video_id>/cards")
@jwt_required
@role_required("student")
def video_cards(video_id):
    con = get_db()
    rows = _video_links(con, video_id)
    if not rows:
        return e_not_found()
    return ok([{"id": r["id"], "front": r["front"], "sub_concept": r["sub_concept"], "chapter_id": r["chapter_id"], "topic": r["topic"], "is_core": bool(r["is_core"])} for r in rows])


@videos_bp.get("")
@jwt_required
@role_required("student")
def list_videos():
    con = get_db()
    _log_link_anomalies(con)
    rows = con.execute("""SELECT v.*,ch.name AS chapter_name,kc.front,kc.id core_card_id,
        COALESCE(ct.topic,'全部卡片') AS topic,
        (SELECT COUNT(DISTINCT card_id) FROM (SELECT card_id FROM card_video_links WHERE video_id=v.id UNION SELECT v.core_card_id AS card_id)) n_cards,
        (SELECT COUNT(DISTINCT COALESCE(t2.topic,'全部卡片')) FROM card_video_links l2 JOIN knowledge_cards k2 ON k2.id=l2.card_id
         LEFT JOIN card_topics t2 ON t2.card_id=k2.id
         WHERE l2.video_id=v.id) adjacent_topics,
        (SELECT COUNT(*) FROM card_video_links l2 JOIN knowledge_cards k2 ON k2.id=l2.card_id
         LEFT JOIN card_topics t2 ON t2.card_id=k2.id
         WHERE l2.video_id=v.id AND COALESCE(t2.topic,'全部卡片')!=COALESCE(ct.topic,'全部卡片')) adjacent_cards
        FROM card_videos v JOIN chapters ch ON ch.id=v.chapter_id AND ch.status='published'
        JOIN knowledge_cards kc ON kc.id=v.core_card_id LEFT JOIN card_topics ct ON ct.card_id=kc.id
        WHERE v.status='ready' ORDER BY ch.order_no,ch.name,ct.ord,kc.rowid""").fetchall()
    return ok([{**_state(r), "chapter_id": r["chapter_id"], "chapter_name": r["chapter_name"], "front": r["front"],
                "topic": r["topic"], "core_card_id": r["core_card_id"], "n_cards": r["n_cards"],
                "adjacent_cards": r["adjacent_cards"], "adjacent_topics": r["adjacent_topics"]} for r in rows])


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
