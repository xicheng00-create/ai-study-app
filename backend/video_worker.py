"""单进程 FIFO 视频队列。运行：.venv/bin/python backend/video_worker.py。"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ai.agents import _chat
from app import create_app
from data import checkin, models, timeutil
from data.db import get_db
from data.video_queue import enqueue
from services.notify import notify_users

ROOT = Path(__file__).resolve().parent.parent
VIDEO = Path(__file__).resolve().parent / "video"
MEDIA = ROOT / "instance/media/videos"
LOG = ROOT / "instance/logs/video_worker.log"
logger = logging.getLogger("video_worker")


def recover(con):
    con.execute("UPDATE card_videos SET status='queued' WHERE status='generating'")
    con.commit()


def claim(con):
    row = con.execute("SELECT id FROM card_videos WHERE status='queued' ORDER BY requested_at,id LIMIT 1").fetchone()
    if not row:
        return None
    cur = con.execute("UPDATE card_videos SET status='generating' WHERE id=? AND status='queued'", (row["id"],))
    con.commit()
    if cur.rowcount != 1:
        return None
    return con.execute("SELECT * FROM card_videos WHERE id=?", (row["id"],)).fetchone()


def neighbours(con, card):
    rows = con.execute("SELECT kc.id,kc.front FROM knowledge_cards kc LEFT JOIN card_topics ct ON ct.card_id=kc.id WHERE kc.chapter_id=? AND kc.id!=? ORDER BY (ct.topic=? AND ct.topic!='') DESC,ct.ord LIMIT 40", (card["chapter_id"], card["id"], card["topic"])).fetchall()
    if not rows:
        return []
    prompt = "从同章候选里挑与核心卡知识点最接近的5到10个；不够就少挑，不许硬凑。只输出JSON数组，元素为候选id。核心：" + card["front"][:500] + "\n候选：" + json.dumps([{"id": r["id"], "front": r["front"][:160]} for r in rows], ensure_ascii=False)
    raw = _chat([{"role": "user", "content": prompt}], feature="video_neighbours")
    try:
        ids = json.loads(raw or "[]")
        allowed = {r["id"] for r in rows}
        return list(dict.fromkeys(i for i in ids if isinstance(i, str) and i in allowed))[:10]
    except (ValueError, TypeError):
        return []


def _run(cmd, timeout, label):
    """跑子进程；失败时把 stdout/stderr 带进异常（失败必须留痕，不许只报 exit code）。"""
    r = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()[-600:]
        raise ValueError(f"{label} 失败(exit {r.returncode})：{detail}")
    return r


def render(con, row):
    card = con.execute("SELECT kc.*,ch.name AS chapter_name,COALESCE(ct.topic,'') AS topic FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id LEFT JOIN card_topics ct ON ct.card_id=kc.id WHERE kc.id=?", (row["core_card_id"],)).fetchone()
    if not card:
        raise ValueError("核心卡已删除")
    linked = neighbours(con, card)
    excerpts = con.execute("SELECT text FROM chunks WHERE chapter_id=? ORDER BY chunk_idx LIMIT 6", (card["chapter_id"],)).fetchall()
    if not excerpts:
        raise ValueError("该章没有可引用资料 chunks，拒绝无依据出片")
    with tempfile.TemporaryDirectory(prefix="aistudy-video-") as temp:
        work = Path(temp)
        note = work / "note.md"
        note.write_text(f"# {card['front']}\n\n子概念：{card['sub_concept']}\n答案：{card['back']}\n\n资料证据（仅以下内容可作为依据；不确定不要编造）：\n" + "\n".join(r["text"][:900] for r in excerpts), encoding="utf-8")
        script = work / "card.json"
        _run([str(ROOT / ".venv/bin/python"), str(VIDEO / "director.py"), "--page", str(note), "--out", str(script), "--title", card["front"][:120], "--source", card["chapter_name"], "--neighbours", ",".join(linked), "--tries", "3"], timeout=600, label="导演")
        _run([str(ROOT / ".venv/bin/python"), str(VIDEO / "daily_video.py"), str(script), "--project", str(work / "project"), "--out-dir", str(work / "out"), "--name-prefix", row["id"]], timeout=1200, label="渲染")
        files = list((work / "out").glob("*.mp4"))
        if len(files) != 1:
            raise ValueError("渲染器未产出唯一 mp4")
        MEDIA.mkdir(parents=True, exist_ok=True)
        target = MEDIA / (row["id"] + ".mp4")
        shutil.move(str(files[0]), target)
        try:
            duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(target)], text=True).strip())
            if not 60 <= duration <= 120:
                raise ValueError(f"成片时长 {duration:.1f}s 不在 60–120s")
            return linked, script.read_text(encoding="utf-8"), duration, target.stat().st_size
        except Exception:
            target.unlink(missing_ok=True)
            raise


def _batch_card_state(con, card_id):
    """批次结算与学生卡片查询使用同一覆盖判据，支持复用他人生成的视频。"""
    return con.execute("""SELECT v.status FROM card_videos v
        LEFT JOIN card_video_links l ON l.video_id=v.id
        WHERE v.core_card_id=? OR l.card_id=?
        ORDER BY CASE WHEN v.status='ready' THEN 0 ELSE 1 END LIMIT 1""", (card_id, card_id)).fetchone()


def _notify_video_requests(con, video_id):
    # manual 单卡请求仍单独通知请求者。
    rows = con.execute("SELECT * FROM card_video_requests WHERE video_id=? AND notify=1 ORDER BY created_at", (video_id,)).fetchall()
    for req in rows:
        if req["source"] == "manual":
            notify_users(con, [req["user_id"]], "card_video_ready", "AI 视频讲解已完成", "点击观看", ref_kind="card_video", ref_id=video_id)
            con.execute("UPDATE card_video_requests SET notify=2 WHERE id=?", (req["id"],))
            con.commit()

    # 按每个未通知批次的完整原始卡集结算；触发者不必是最后一张卡的请求来源。
    batches = con.execute("SELECT * FROM card_video_batches WHERE status='active' AND notified_at IS NULL").fetchall()
    for batch in batches:
        card_ids = json.loads(batch["card_ids_json"])
        ready = failed = pending = 0
        for card_id in card_ids:
            card = _batch_card_state(con, card_id)
            if card is None:
                pending += 1
            elif card["status"] == "ready":
                ready += 1
            elif card["status"] == "failed":
                failed += 1
            else:
                pending += 1
        if pending:
            continue
        # 全 ready 的批次是纯 skip，不发通知；存在失败也属于批次完成，发一次总结。
        if ready + failed:
            notify_users(con, [batch["user_id"]], "card_video_batch_ready", "今日卡组 AI 视频已就绪",
                         f"{ready} 张已就绪 · {failed} 张失败，点开即可观看",
                         ref_kind="card_videos", ref_id=batch["id"])
        con.execute("UPDATE card_video_batches SET notified_at=?,status='complete' WHERE id=? AND notified_at IS NULL",
                    (models.utcnow(), batch["id"]))
        con.execute("UPDATE card_video_requests SET notify=2 WHERE batch_id=? AND source='batch'", (batch["id"],))
        con.commit()


def process(con, row):
    try:
        linked, script, duration, size = render(con, row)
        con.execute("UPDATE card_videos SET status='ready',file_name=?,duration_s=?,size_bytes=?,script_json=?,ready_at=?,error=NULL WHERE id=?", (row["id"] + ".mp4", duration, size, script, models.utcnow(), row["id"]))
        con.execute("INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,1)", (row["id"], row["core_card_id"]))
        for cid in linked:
            con.execute("INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,0)", (row["id"], cid))
        con.commit()
        _notify_video_requests(con, row["id"])
    except Exception as exc:
        con.rollback()
        logger.exception("生成失败 %s", row["id"])
        con.execute("UPDATE card_videos SET status='failed',error=? WHERE id=?", (str(exc)[:1000], row["id"]))
        con.commit()
        _notify_video_requests(con, row["id"])


def warm_today_decks(con):
    """按上海日历日为每位活跃学生静默预热当日任务卡组，主键保证每日幂等。"""
    from config import TASK_CARDS_REQUIRED
    day = timeutil.today_str()
    students = con.execute("SELECT id FROM users WHERE role='student' AND is_active=1").fetchall()
    for student in students:
        uid = student["id"]
        if con.execute("SELECT 1 FROM card_video_daily_runs WHERE date=? AND user_id=?", (day, uid)).fetchone():
            continue
        started = time.monotonic()
        deck = checkin.build_today_deck(con, uid, limit=TASK_CARDS_REQUIRED, mode="task")
        ids = [card["id"] for card in deck["cards"]]
        queued = skipped = 0
        con.execute("SAVEPOINT daily_video_warmup")
        try:
            for cid in ids:
                row = con.execute("SELECT v.* FROM card_videos v LEFT JOIN card_video_links l ON l.video_id=v.id WHERE (v.core_card_id=? OR l.card_id=?) ORDER BY CASE WHEN v.status='ready' THEN 0 ELSE 1 END LIMIT 1", (cid, cid)).fetchone()
                if row and row["status"] in ("ready", "queued", "generating"):
                    skipped += 1
                card = con.execute("SELECT kc.id,kc.chapter_id,kc.front FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id WHERE kc.id=? AND ch.status='published'", (cid,)).fetchone()
                if not card:
                    skipped += 1
                    continue
                current = enqueue(con, cid)
                queued += int(current['status'] == 'queued')
                if current:
                    con.execute("INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,created_at) SELECT ?,?,?,?,'prewarm',0,? WHERE NOT EXISTS (SELECT 1 FROM card_video_requests WHERE user_id=? AND card_id=? AND source='prewarm')", (models.new_id(), current["id"], cid, uid, models.utcnow(), uid, cid))
            con.execute("INSERT INTO card_video_daily_runs(date,user_id,total,queued,skipped,ran_at) VALUES(?,?,?,?,?,?)", (day, uid, len(ids), queued, skipped, models.utcnow()))
            con.execute("RELEASE SAVEPOINT daily_video_warmup")
            con.commit()
            logger.info("daily_warmup date=%s user_id=%s queued=%s skipped=%s elapsed_s=%.3f", day, uid, queued, skipped, time.monotonic() - started)
        except Exception:
            con.execute("ROLLBACK TO SAVEPOINT daily_video_warmup")
            con.execute("RELEASE SAVEPOINT daily_video_warmup")
            con.commit()
            logger.exception("daily_warmup failed date=%s user_id=%s queued=%s skipped=%s elapsed_s=%.3f", day, uid, queued, skipped, time.monotonic() - started)


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app(os.getenv("FLASK_ENV", "production"))
    with app.app_context():
        con = get_db()
        models.migrate(con)
        con.commit()
        con.execute("""CREATE TABLE IF NOT EXISTS card_video_requests (
          id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES card_videos(id) ON DELETE CASCADE,
          card_id TEXT NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          source TEXT NOT NULL CHECK(source IN ('manual','batch','prewarm')),
          notify INTEGER NOT NULL DEFAULT 0, batch_id TEXT REFERENCES card_video_batches(id),
          created_at TEXT NOT NULL
        )""")
        con.commit()
        recover(get_db())
        warmed_day = None
        while True:
            day = timeutil.today_str()
            if day != warmed_day:
                warm_today_decks(get_db())
                warmed_day = day
            row = claim(get_db())
            if row:
                process(get_db(), row)
            else:
                time.sleep(5)


if __name__ == "__main__":
    main()
