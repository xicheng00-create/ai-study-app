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
from data import models
from data.db import get_db
from services.notify import active_student_ids, notify_users

ROOT = Path(__file__).resolve().parent.parent
VIDEO = Path(__file__).resolve().parent / "video"
MEDIA = ROOT / "instance/media/videos"
LOG = ROOT / "instance/logs/video_worker.log"
logger = logging.getLogger("video_worker")


def recover(con):
    con.execute("UPDATE card_videos SET status='queued' WHERE status='generating'")
    con.commit()


def claim(con):
    row = con.execute("SELECT * FROM card_videos WHERE status='queued' ORDER BY requested_at,id LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE card_videos SET status='generating' WHERE id=? AND status='queued'", (row["id"],))
        con.commit()
    return row


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
        subprocess.run([str(ROOT / ".venv/bin/python"), str(VIDEO / "director.py"), "--page", str(note), "--out", str(script), "--title", card["front"][:120], "--source", card["chapter_name"], "--neighbours", ",".join(linked)], check=True, timeout=180, capture_output=True, text=True)
        subprocess.run([str(ROOT / ".venv/bin/python"), str(VIDEO / "daily_video.py"), str(script), "--project", str(work / "project"), "--out-dir", str(work / "out"), "--name-prefix", row["id"]], check=True, timeout=1200, capture_output=True, text=True)
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


def process(con, row):
    try:
        linked, script, duration, size = render(con, row)
        con.execute("UPDATE card_videos SET status='ready',file_name=?,duration_s=?,size_bytes=?,script_json=?,ready_at=?,error=NULL WHERE id=?", (row["id"] + ".mp4", duration, size, script, models.utcnow(), row["id"]))
        con.execute("INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,1)", (row["id"], row["core_card_id"]))
        for cid in linked:
            con.execute("INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,0)", (row["id"], cid))
        con.commit()
        notify_users(con, active_student_ids(con), "card_video_ready", "AI 视频讲解已完成", row["title"] or "点击观看", ref_kind="card_video", ref_id=row["id"])
    except Exception as exc:
        con.rollback()
        logger.exception("生成失败 %s", row["id"])
        con.execute("UPDATE card_videos SET status='failed',error=? WHERE id=?", (str(exc)[:1000], row["id"]))
        con.commit()


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app(os.getenv("FLASK_ENV", "production"))
    with app.app_context():
        recover(get_db())
        while True:
            row = claim(get_db())
            if row:
                process(get_db(), row)
            else:
                time.sleep(5)


if __name__ == "__main__":
    main()
