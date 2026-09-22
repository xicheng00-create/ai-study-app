#!/usr/bin/env python3
"""通用课件注入：把 课件/WxSy/（课件.md 教案 + 材料/ 源文件）上架到老师端后台。

方案 B：不复制原件进 uploads/，仅解析文本块 + 写元数据；源文件留在 课件/ 目录（source_path 绝对路径）。
新建 session/chapter/material/chunk 一律 status='draft'（学生不可见），教师后台发布后可见。
视频链接（video_resources）默认 draft，随 session 发布。

幂等：先删该周旧数据，再注入（可重复运行）。

用法：
    python3 scripts/inject_curriculum.py W2S1 W2S2        # 只注入指定 session
    python3 scripts/inject_curriculum.py --week 2        # 注入某周全部 session
    python3 scripts/inject_curriculum.py --backfill-courseware   # 给已有章节补挂 课件.md
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))
from ai import parser  # noqa: E402  pdfplumber/pptx 解析

DB = BASE / "instance" / "aistudy.sqlite3"
COURSE = BASE / "课件"

# 预抽取文本副本（与同名 PDF 内容重复），不参与切片，避免 RAG 重复召回
SKIP_SUFFIXES = ("_extracted.txt",)


def new_id():
    return str(uuid.uuid4())


def utcnow(offset_sec=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def chapter_no(s: dict) -> int:
    """章节全局序号（v2.7.0 解耦「周/节」展示口径）：每周 2 讲 → W1S1=1、W1S2=2、W2S1=3…"""
    return (int(s["week"]) - 1) * 2 + int(s["no"])


SPECS = {
    "W2S1": {
        "week": 2, "no": 1, "dir": "W2S1",
        "title": "AIPM vs 传统 PM",
        "goal": (
            "用 3 个以上维度（定位/底层逻辑/价值核心）说清传统 PM 与 AIPM 的差异；"
            "理解确定性逻辑 vs 概率性逻辑 + 泛化能力；"
            "掌握 9 步工作流、场景化落地、Copilot/Autopilot、Evals 意识；"
            "建立「AI 产品经理要不要学技术」的下限与上限认知，避免两个极端误区；"
            "产出一张「传统 PM vs AIPM」对比表（差异行数 ≥ 5 行）。"
        ),
        "concept_tags": [
            "传统PM", "AIPM", "确定性逻辑", "概率性逻辑", "泛化能力", "管控不确定性",
            "9步工作流", "场景化落地", "Copilot", "Autopilot", "Evals",
            "GUI", "CUI", "结构性困境", "信息差护城河", "toB", "信任链", "Vibe Coding",
        ],
        "milestone": "一张「传统 PM vs AIPM」对比表（差异行数 ≥ 5 行）",
        "videos": [
            {
                "title": "AI 产品经理入门教程",
                "url": "https://www.bilibili.com/video/BV1XNd3YeEbf/",
                "platform": "bilibili",
                "description": "重点看：AIPM 到底是什么、与传统 PM 的核心区别、AI 产品经理的日常工作内容。对应课件 3.1–3.5 的定位与逻辑差异。",
            },
            {
                "title": "零基础转行 AI 产品经理",
                "url": "https://www.bilibili.com/video/BV1qo26BbE4x/",
                "platform": "bilibili",
                "description": "重点看：从岗位视角看 AI 产品的实际工作流、能力要求与转型路径。对应课件 3.6–3.8 的方法论与学技术讨论。",
            },
        ],
    },
    "W2S2": {
        "week": 2, "no": 2, "dir": "W2S2",
        "title": "真实落地案例",
        "goal": (
            "掌握「四问拆读法」（痛点 / AI 解法 / 数据知识来源 / 边界与兜底）拆解任意 AI 落地案例；"
            "分清三类高频 AI 产品形态：RAG 知识问答、Agent 自动化、MCP 协议连接；"
            "讲清智能客服三种技术路线 PairQA / DocQA / KBQA 的差异与适用边界；"
            "掌握 KBQA 四大流程（Query 理解 / 关系识别 / 子图召回 / 答案排序）与三大落地挑战；"
            "掌握电商智能客服三大核心能力（多轮对话管理 / 意图识别 / 知识推荐）；"
            "了解知识图谱增强 RAG；MCP 概念预览；产出 3 个「我的 AI 改造场景」清单。"
        ),
        "concept_tags": [
            "四问拆读法", "PairQA", "DocQA", "KBQA", "知识图谱", "RAG", "Agent", "MCP",
            "槽位填充", "Slot Filling", "意图识别", "知识推荐", "多跳查询", "实体链接",
            "依存分析", "子图召回", "答案排序", "交互型BERT", "层次剪枝", "微服务架构",
        ],
        "milestone": "3 个「我的 AI 改造场景」清单",
        "videos": [
            {
                "title": "AI 产品经理真实落地案例解析",
                "url": "https://www.woshipm.com/?p=6252150",
                "platform": "woshipm",
                "description": "从行业落地视角讲 AI 产品经理如何拆解真实案例、提炼需求模板与方法论，与本节「四问拆读法 + 三篇技术型案例精读」互补。",
            },
        ],
    },
}


def iter_source_files(sdir: Path) -> list[Path]:
    """课件.md（教案）优先，其余 材料/ 支持类型按文件名排序；跳过预抽取重复副本。"""
    files: list[Path] = []
    lesson = sdir / "课件.md"
    if lesson.is_file():
        files.append(lesson)
    mdir = sdir / "材料"
    if mdir.is_dir():
        for f in sorted(mdir.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue
            if f.name.endswith(SKIP_SUFFIXES):
                continue
            if f.suffix.lower().lstrip(".") not in parser.SUPPORTED:
                continue
            if f.name == "课件.md":
                continue
            files.append(f)
    return files


def cleanup_week(cur, week: int) -> None:
    sids = [r[0] for r in cur.execute("SELECT id FROM sessions WHERE week_no=?", (week,)).fetchall()]
    cids: list[str] = []
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
    cur.execute("DELETE FROM video_resources WHERE week_no=?", (week,))
    cur.execute("DELETE FROM sessions WHERE week_no=?", (week,))


def insert_material(cur, cid: str, f: Path, order: int, status: str, counts: dict) -> None:
    try:
        blob = f.read_bytes()
        text = parser.extract_text(f.name, blob)
        chunks = parser.chunk_text_list(text)
        parse_status = "parsed" if text.strip() else "failed"
    except Exception as e:  # noqa: BLE001
        chunks, text, parse_status = [], "", "failed"
        print(f"  [warn] 解析失败 {f.name}: {e}")
    ext = f.suffix.lower().lstrip(".")
    mid = new_id()
    display = f.name
    if f.name == "课件.md":
        display = f"{f.parent.name} 课件（教案）.md"
    cur.execute(
        "INSERT INTO materials (id, chapter_id, filename, original_name, file_type, size_bytes,"
        " uploaded_by, is_deleted, chunk_count, parse_status, created_at, status, source_path)"
        " VALUES (?,?,?,?,?,?, 'seed', 0, ?, ?, ?, ?, ?)",
        (mid, cid, mid + "." + ext, display, ext, f.stat().st_size,
         len(chunks), parse_status, utcnow(order), status, str(f)),
    )
    counts["materials"] += 1
    for c in chunks:
        cur.execute(
            "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (new_id(), mid, cid, c["chunk_idx"], c["text"], utcnow(order)),
        )
        counts["chunks"] += 1
    print(f"  [ok] {display} -> {len(chunks)} chunks ({parse_status})")


def inject_session(cur, key: str, status: str, counts: dict) -> str:
    s = SPECS[key]
    sid, cid = new_id(), new_id()
    cur.execute(
        "INSERT INTO sessions (id, week_no, session_no, title, goal, chapter_ids, concept_tags,"
        " milestone, order_no, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'seed', ?)",
        (sid, s["week"], s["no"], s["title"], s["goal"], json.dumps([cid], ensure_ascii=False),
         json.dumps(s["concept_tags"], ensure_ascii=False), s["milestone"], s["no"], status, utcnow()),
    )
    counts["sessions"] += 1
    cname = f"第 {chapter_no(s)} 章 · {s['title']}"
    cur.execute(
        "INSERT INTO chapters (id, folder, name, order_no, created_by, created_at, status)"
        " VALUES (?,?,?,?, 'seed', ?, ?)",
        (cid, "", cname, chapter_no(s), utcnow(), status),
    )
    counts["chapters"] += 1
    print(f"\n[{key}] {cname}  (session={sid[:8]} chapter={cid[:8]} status={status})")

    sdir = COURSE / s["dir"]
    for i, f in enumerate(iter_source_files(sdir)):
        insert_material(cur, cid, f, i, status, counts)

    for i, v in enumerate(s["videos"]):
        cur.execute(
            "INSERT INTO video_resources (id, title, url, platform, description, week_no, session_no,"
            " concept_tags, order_no, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?, 'seed', ?)",
            (new_id(), v["title"], v["url"], v["platform"], v["description"], s["week"], s["no"],
             json.dumps(s["concept_tags"], ensure_ascii=False), i, status, utcnow(i)),
        )
        counts["videos"] += 1
    return cid


def backfill_courseware(cur, counts: dict) -> None:
    """给已有章节补挂 课件.md（历史章节从未把教案入库，导致 RAG 检索不到课上原文）。"""
    rows = cur.execute(
        "SELECT c.id, c.name, c.status, c.folder, c.order_no FROM chapters c ORDER BY c.folder, c.order_no"
    ).fetchall()
    for cid, name, status, folder, order_no in rows:
        # v2.7.0：章节名解耦为「第 N 章」（folder 置空），由全局章号反推 W{week}S{session}
        # （课程每周 2 讲：章 1→W1S1、章 2→W1S2、章 3→W2S1、章 4→W2S2）。
        # 课件源目录仍按 WxSx 命名，本函数只是把它换算成目录名，不改任何展示口径。
        try:
            chno = int(order_no)
            if chno < 1:
                raise ValueError(order_no)
            key = f"W{(chno - 1) // 2 + 1}S{(chno - 1) % 2 + 1}"
        except (ValueError, TypeError):
            print(f"  [skip] 无法解析章节序号：{name}")
            continue
        lesson = COURSE / key / "课件.md"
        if not lesson.is_file():
            print(f"  [skip] 缺文件 {lesson}")
            continue
        exists = cur.execute(
            "SELECT COUNT(*) FROM materials WHERE chapter_id=? AND original_name LIKE '%课件（教案）%'",
            (cid,),
        ).fetchone()[0]
        if exists:
            print(f"  [have] {key} 已挂课件.md")
            continue
        n = cur.execute("SELECT COUNT(*) FROM materials WHERE chapter_id=?", (cid,)).fetchone()[0]
        first = cur.execute(
            "SELECT MIN(created_at) FROM materials WHERE chapter_id=?", (cid,)
        ).fetchone()[0]
        base = datetime.fromisoformat(first) if first else datetime.now(timezone.utc)
        cur.execute(
            "UPDATE materials SET created_at=? WHERE chapter_id=?", ((base - timedelta(seconds=1)).isoformat(), cid)
        )
        insert_material(cur, cid, lesson, -1, status, counts)
        print(f"  [add] {key} 补挂课件.md（该章原有 {n} 份资料，教案排首位）")


def rechunk_all(cur, counts: dict) -> None:
    """按 best_text（原生解析 + 图片型 PDF/PPTX 的 OCR 文本）重算全部资料的切片。

    图片型幻灯片的原生文本极少，只靠原生解析会让「AI 对话切片」看不到课件原内容。
    """
    import ocr_materials

    rows = cur.execute(
        "SELECT id, chapter_id, original_name, source_path FROM materials"
        " WHERE is_deleted=0 ORDER BY chapter_id, created_at"
    ).fetchall()
    for mid, cid, name, src in rows:
        p = Path(src) if src else None
        if not p or not p.is_file():
            print(f"  [skip] 源文件缺失：{name}")
            continue
        text = ocr_materials.best_text(p, quiet=True)
        chunks = parser.chunk_text_list(text)
        cur.execute("DELETE FROM chunks WHERE material_id=?", (mid,))
        for c in chunks:
            cur.execute(
                "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (new_id(), mid, cid, c["chunk_idx"], c["text"], utcnow()),
            )
            counts["chunks"] += 1
        cur.execute(
            "UPDATE materials SET chunk_count=?, parse_status=? WHERE id=?",
            (len(chunks), "parsed" if text.strip() else "failed", mid),
        )
        counts["rechunked"] += 1
        print(f"  [ok] {name[:40]:<42} -> {len(chunks):3d} 切片 / {len(text):6d} 字")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="*", help="如 W2S1 W2S2")
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--status", default="draft", choices=["draft", "published"])
    ap.add_argument("--backfill-courseware", action="store_true")
    ap.add_argument("--rechunk", action="store_true",
                    help="按 best_text（含 OCR）重算全部资料切片")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    keys = list(args.sessions)
    if args.week is not None:
        keys += [k for k, s in SPECS.items() if s["week"] == args.week and k not in keys]
    if not keys and not args.backfill_courseware and not args.rechunk:
        ap.error("请指定 session（如 W2S1）或 --week N 或 --backfill-courseware 或 --rechunk")

    con = sqlite3.connect(args.db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    cur = con.cursor()
    counts = {"sessions": 0, "chapters": 0, "materials": 0, "chunks": 0, "videos": 0,
              "rechunked": 0}

    weeks = sorted({SPECS[k]["week"] for k in keys})
    for w in weeks:
        cleanup_week(cur, w)
    for k in keys:
        inject_session(cur, k, args.status, counts)
    if args.backfill_courseware:
        print("\n[backfill-courseware]")
        backfill_courseware(cur, counts)
    if args.rechunk:
        print("\n[rechunk] 按 OCR 增强文本重算切片")
        rechunk_all(cur, counts)

    con.commit()
    print("\n=== 注入完成 ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
