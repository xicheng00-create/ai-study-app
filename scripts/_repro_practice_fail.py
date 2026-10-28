"""在临时副本库里复现「练习生成失败」：不碰生产库。"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
SRC = BASE / "instance" / "aistudy.sqlite3"
TMP = Path("/tmp/wq_repro.sqlite3")
for suf in ("", "-wal", "-shm"):
    src = Path(str(SRC) + suf)
    if src.exists():
        shutil.copy2(src, str(TMP) + suf)
os.environ["DATABASE_URL"] = "sqlite://" + str(TMP)

sys.path.insert(0, str(BASE / "backend"))
from app import create_app  # noqa: E402

UID = "b331c048-789f-4c4b-ad7a-d84ef9789bf9"
app = create_app()
with app.app_context():
    from api.practice import _generate_for, _history_contents, _history_sub_concepts
    from data.db import get_db
    from ai import quizzer
    con = get_db()
    chs = [r["id"] for r in con.execute(
        "SELECT id FROM chapters WHERE status='published' ORDER BY folder, order_no, name")]
    print("已发布章节", len(chs))
    excl = _history_contents(con, UID)
    excl_sub = _history_sub_concepts(con, UID, chs)
    print("已答去重：题目", len(excl), "子概念", len(excl_sub))
    qs, cnt = _generate_for(con, UID, chs, 5)
    print("出题结果 count=", cnt, "拿到", len(qs), "题")
    for q in qs[:3]:
        print("  -", q.get("type"), str(q.get("content", ""))[:40])
    # 再看：每章卡片数 / quizzer 是否认为有卡
    no_cards = [c for c in chs if not quizzer.has_cards([c])]
    print("无卡章节", len(no_cards), "示例", no_cards[:3])
    # 今日练习统计（学习页 0/5）
    row = con.execute(
        "SELECT COUNT(*) n FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=? AND date(pq.created_at)=date('now','+8 hours')", (UID,)).fetchone()
    print("今日已生成题目", row["n"])
