#!/usr/bin/env python3
"""注入 W1 两个 Session（W1S1 概念扫盲 / W1S2 AI产品地图）到 app 数据库。

方案 B：不复制原件进 uploads/，仅解析文本块 + 写元数据；源文件留在 课件/ 目录。
所有内容默认 status='draft'（学生不可见），教师后台发布后可见。

幂等：先删 W1 相关旧数据，再注入（可重复运行）。
"""
import sys, json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))
from ai import parser  # pdfplumber/pptx/docx 解析

DB = BASE / "instance" / "aistudy.sqlite3"
COURSE = BASE / "课件"


def new_id():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc).isoformat()


SESSIONS = [
    {
        "week": 1, "no": 1, "title": "大模型是什么：概念扫盲",
        "goal": "概念扫盲：讲清 AI/LLM/AIGC 是什么，记住 Token/上下文窗口/Transformer/幻觉/微调 五个术语，破除对 AI 的神秘感。",
        "concept_tags": ["LLM", "Token", "上下文窗口", "Transformer", "幻觉", "微调"],
        "milestone": "本周产出「我眼中的 AI」概念卡片",
        "videos": [
            {"title": "智泊AI《AI大模型零基础全套教程》(前30分钟)", "url": "https://www.bilibili.com/video/BV1KUwazoEXH/", "platform": "bilibili"},
            {"title": "吴恩达《Generative AI for Everyone》中文版", "url": "https://www.bilibili.com/video/BV11G411X7nZ/", "platform": "bilibili"},
            {"title": "李宏毅《生成式AI导论 2024》", "url": "https://www.bilibili.com/video/av1251133686/", "platform": "bilibili"},
            {"title": "大模型零基础全套教程", "url": "https://www.bilibili.com/video/BV1D5QRYkEmg/", "platform": "bilibili"},
        ],
        "materials_dir": "W1S1",
    },
    {
        "week": 1, "no": 2, "title": "AI 产品地图",
        "goal": "从产品经理/行业观察者视角看 AI：产业三层结构、市场阻抗四类、讲清幻觉边界、岗位全景与转型路径、AI 时代机会。",
        "concept_tags": ["AI产品", "产业三层结构", "市场阻抗", "幻觉", "岗位全景", "Agent"],
        "milestone": "「我眼中的 AI」概念卡片（终稿）",
        "videos": [
            {"title": "卡帕西《ChatGPT 与大语言模型》讲解", "url": "https://www.bilibili.com/video/BV16cNEeXEer/", "platform": "bilibili"},
        ],
        "materials_dir": "W1S2",
    },
]

con = sqlite3.connect(str(DB))
cur = con.cursor()


def cleanup_w1():
    sids = [r[0] for r in cur.execute("SELECT id FROM sessions WHERE week_no=1").fetchall()]
    cids = []
    if sids:
        ph = ",".join("?" * len(sids))
        for (cj,) in cur.execute(f"SELECT chapter_ids FROM sessions WHERE id IN ({ph})", sids).fetchall():
            try:
                cids += json.loads(cj or "[]")
            except json.JSONDecodeError:
                pass
    if cids:
        cph = ",".join("?" * len(cids))
        mids = [r[0] for r in cur.execute(f"SELECT id FROM materials WHERE chapter_id IN ({cph})", cids).fetchall()]
        if mids:
            mph = ",".join("?" * len(mids))
            cur.execute(f"DELETE FROM chunks WHERE material_id IN ({mph})", mids)
        cur.execute(f"DELETE FROM materials WHERE chapter_id IN ({cph})", cids)
        cur.execute(f"DELETE FROM chapters WHERE id IN ({cph})", cids)
    if sids:
        ph = ",".join("?" * len(sids))
        cur.execute(f"DELETE FROM video_resources WHERE week_no=1 AND session_no IN (SELECT session_no FROM sessions WHERE id IN ({ph}))", sids)
    cur.execute("DELETE FROM sessions WHERE week_no=1")


cleanup_w1()

counts = {"sessions": 0, "chapters": 0, "materials": 0, "chunks": 0, "videos": 0}

for s in SESSIONS:
    # 1. Session
    sid = new_id()
    cur.execute(
        "INSERT INTO sessions (id, week_no, session_no, title, goal, chapter_ids, concept_tags, milestone, order_no, status, created_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?, 'draft', 'seed', ?)",
        (sid, s["week"], s["no"], s["title"], s["goal"], "[]",
         json.dumps(s["concept_tags"], ensure_ascii=False), s["milestone"], s["no"], utcnow()),
    )
    counts["sessions"] += 1

    # 2. Chapter 一对一
    cname = "第" + str(s["week"]) + "周·第" + str(s["no"]) + "节 · " + s["title"]
    cid = new_id()
    cur.execute(
        "INSERT INTO chapters (id, folder, name, order_no, created_by, created_at, status)"
        " VALUES (?,?,?,?, 'seed', ?, 'draft')",
        (cid, "第" + str(s["week"]) + "周", cname, s["no"], utcnow()),
    )
    cur.execute("UPDATE sessions SET chapter_ids=? WHERE id=?", (json.dumps([cid], ensure_ascii=False), sid))
    counts["chapters"] += 1

    # 3. 材料 + chunks
    mdir = COURSE / s["materials_dir"] / "材料"
    if mdir.is_dir():
        for f in sorted(mdir.iterdir()):
            if not f.is_file() or f.suffix.lower().lstrip(".") not in parser.SUPPORTED:
                continue
            try:
                blob = f.read_bytes()
                text = parser.extract_text(f.name, blob)
                chunks = parser.chunk_text_list(text)
                parse_status = "parsed" if text.strip() else "failed"
            except Exception as e:  # noqa: BLE001
                chunks = []
                parse_status = "failed"
                print("  [warn] 解析失败 " + f.name + ": " + str(e))
            ext = f.suffix.lower().lstrip(".")
            mid = new_id()
            cur.execute(
                "INSERT INTO materials (id, chapter_id, filename, original_name, file_type, size_bytes, uploaded_by, is_deleted, chunk_count, parse_status, created_at, status)"
                " VALUES (?,?,?,?,?,?, 'seed', 0, ?, ?, ?, 'draft')",
                (mid, cid, mid + "." + ext, f.name, ext, f.stat().st_size, len(chunks), parse_status, utcnow()),
            )
            counts["materials"] += 1
            for c in chunks:
                cur.execute(
                    "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (new_id(), mid, cid, c["chunk_idx"], c["text"], utcnow()),
                )
                counts["chunks"] += 1
            print("  [ok] " + s["materials_dir"] + "/" + f.name + " -> " + str(len(chunks)) + " chunks")

    # 4. 视频链接
    for v in s["videos"]:
        vid = new_id()
        cur.execute(
            "INSERT INTO video_resources (id, title, url, platform, description, week_no, session_no, concept_tags, order_no, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?, 'draft', 'seed', ?)",
            (vid, v["title"], v["url"], v["platform"], "", s["week"], s["no"],
             json.dumps(s["concept_tags"], ensure_ascii=False), s["no"], utcnow()),
        )
        counts["videos"] += 1

con.commit()
print("\n=== 注入完成 ===")
for k, v in counts.items():
    print("  " + k + ": " + str(v))

rows = cur.execute("SELECT week_no, session_no, title FROM sessions WHERE week_no=1").fetchall()
print("\nW1 sessions: " + repr(rows))
con.close()
