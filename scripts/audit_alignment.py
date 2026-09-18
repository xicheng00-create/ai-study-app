#!/usr/bin/env python3
"""上架成果审计：章节 ↔ 资料 ↔ 切片 ↔ 卡片 的一一对应，以及考点覆盖度。

用法：
    python3 scripts/audit_alignment.py            # 仅结构对齐（确定性，不花钱）
    python3 scripts/audit_alignment.py --llm      # 追加考点覆盖度审视（调模型）
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
DB = BASE / "instance" / "aistudy.sqlite3"
sys.path.insert(0, str(BASE / "scripts"))

HEAD_RE = re.compile(r"^\s{0,3}#{1,4}\s+(.+?)\s*$")

# 教案里的「流程性/容器型」小节不含具体考点，不该被算作应被卡片覆盖的考点（否则审计误报）：
#   流程性 → 学习目标 / 动手任务 / 备课参考材料…
#   容器型 → 「3.4 行业核心判断（来源：xxx.pptx）」这类**指向整节/整份素材的指针标题**，
#           本节内容由若干细粒度卡片共同覆盖，无法由单张卡「覆盖」，故不计入
META_HEAD = re.compile(
    r"学习目标|前置与衔接|与视频课|视频课对应|动手任务|课后任务|本 Session 产出|备课参考材料|"
    r"知识点讲解|课程结构|板书|时间分配|教学流程|作业|导语|目录|常见误区|答疑|"
    r"来源：|了解即可|Session\s*\d")


def structural(con) -> tuple[list[str], dict]:
    problems: list[str] = []
    info: dict = {}

    sessions = con.execute("SELECT * FROM sessions ORDER BY week_no, session_no").fetchall()
    for s in sessions:
        cids = json.loads(s["chapter_ids"] or "[]")
        if len(cids) != 1:
            problems.append(f"session {s['week_no']}-{s['session_no']} 关联章节数 = {len(cids)}（应为 1）")
        for cid in cids:
            ch = con.execute("SELECT * FROM chapters WHERE id=?", (cid,)).fetchone()
            if ch is None:
                problems.append(f"session {s['week_no']}-{s['session_no']} 指向不存在的章节 {cid[:8]}")
            elif ch["status"] != s["status"]:
                problems.append(
                    f"章节 {ch['name']} 状态({ch['status']}) 与 session 状态({s['status']}) 不一致")
    # 反向：孤儿章节
    linked = {cid for s in sessions for cid in json.loads(s["chapter_ids"] or "[]")}
    for ch in con.execute("SELECT id, name FROM chapters"):
        if ch["id"] not in linked:
            problems.append(f"章节 {ch['name']} 未挂到任何 session")

    rows = []
    for ch in con.execute("SELECT id, name, status FROM chapters ORDER BY folder, order_no"):
        cid = ch["id"]
        mats = con.execute(
            "SELECT id, original_name, chunk_count, parse_status, status, is_deleted, source_path"
            " FROM materials WHERE chapter_id=? AND is_deleted=0", (cid,)).fetchall()
        if not mats:
            problems.append(f"章节 {ch['name']} 没有任何资料")
        total_chunks = 0
        chunk_ids = set()
        for m in mats:
            real = con.execute("SELECT COUNT(*) c FROM chunks WHERE material_id=?", (m["id"],)).fetchone()["c"]
            total_chunks += real
            if real != m["chunk_count"]:
                problems.append(f"资料 {m['original_name']} chunk_count={m['chunk_count']} 与实际 {real} 不符")
            if real == 0:
                problems.append(f"资料 {m['original_name']} 未解析出任何切片")
            if m["status"] != ch["status"]:
                problems.append(f"资料 {m['original_name']} 状态({m['status']}) 与章节({ch['status']}) 不一致")
            if not m["source_path"] or not Path(m["source_path"]).is_file():
                problems.append(f"资料 {m['original_name']} 源文件缺失，无法下载")
            for c in con.execute("SELECT id, chapter_id FROM chunks WHERE material_id=?", (m["id"],)):
                chunk_ids.add(c["id"])
                if c["chapter_id"] != cid:
                    problems.append(f"切片 {c['id'][:8]} 的 chapter_id 与所属资料章节不一致（错配）")
        # 切片跨章节错配
        stray = con.execute(
            "SELECT COUNT(*) c FROM chunks WHERE chapter_id=? AND material_id NOT IN"
            " (SELECT id FROM materials WHERE chapter_id=?)", (cid, cid)).fetchone()["c"]
        if stray:
            problems.append(f"章节 {ch['name']} 有 {stray} 个切片不属于本章任何资料")

        cards = con.execute(
            "SELECT id, front, sub_concept, source_chunk_id FROM knowledge_cards WHERE chapter_id=?",
            (cid,)).fetchall()
        if not cards:
            problems.append(f"章节 {ch['name']} 没有知识卡片")
        no_src = [c for c in cards if not c["source_chunk_id"]]
        bad_src = [c for c in cards if c["source_chunk_id"] and c["source_chunk_id"] not in chunk_ids]
        if no_src:
            problems.append(f"章节 {ch['name']} 有 {len(no_src)} 张卡片未绑定切片")
        if bad_src:
            problems.append(f"章节 {ch['name']} 有 {len(bad_src)} 张卡片绑定的切片不属于本章（错配）")
        no_sub = [c for c in cards if not (c["sub_concept"] or "").strip()]
        if no_sub:
            problems.append(f"章节 {ch['name']} 有 {len(no_sub)} 张卡片缺 sub_concept")

        lessons = [m for m in mats if "课件（教案）" in m["original_name"]]
        if not lessons:
            problems.append(f"章节 {ch['name']} 未挂课件（教案），切片将缺少「课上有讲」的原文")

        # 课件小节 → 卡片 sub_concept 覆盖
        subs = {c["sub_concept"] for c in cards if c["sub_concept"]}
        heads: list[str] = []
        for m in lessons:
            for c in con.execute("SELECT text FROM chunks WHERE material_id=? ORDER BY chunk_idx", (m["id"],)):
                # 标题常落在切片中部，必须逐行扫描（切片是定长窗口）
                for line in (c["text"] or "").splitlines():
                    mt = HEAD_RE.match(line)
                    if mt:
                        h = mt.group(0).lstrip("# ").strip()
                        if 3 <= len(h) <= 40:
                            heads.append(h)
        rows.append({
            "chapter": ch["name"], "status": ch["status"],
            "materials": len(mats), "chunks": total_chunks, "cards": len(cards),
            "sub_concepts": len(subs), "lesson_heads": len(heads), "sections": heads,
            "bound": len(cards) - len(no_src),
        })
    info["chapters"] = rows
    return problems, info


def _cv_tokens(s: str) -> set:
    return set(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", s or ""))


def llm_coverage(con, info: dict) -> list[dict]:
    """用模型逐条判：课件小节 / 随堂测试题 是否被卡片覆盖。

    每个考点只附带**关键词预筛出的候选卡片**（而不是全章几百张）：实测把 276 张卡全量丢给模型时，
    它会漏看明明匹配的卡片（「政府工作报告」考点被人形机器人卡片覆盖却判未覆盖）；预筛后判得准得多。
    """
    import rebuild_cards as rc

    out = []
    for row in info["chapters"]:
        ch = con.execute("SELECT id FROM chapters WHERE name=?", (row["chapter"],)).fetchone()
        cid = ch["id"]
        cards = con.execute(
            "SELECT front, back, sub_concept FROM knowledge_cards WHERE chapter_id=?", (cid,)).fetchall()
        # 候选匹配必须**正反两面都算**：大量考点的答案落在卡片背面
        # （如「插件」出现在「智能体」卡的答案里），只看正面会大面积假阴性。
        toks_list = [(c["front"], c["back"] or "",
                      _cv_tokens(f"{c['front']} {c['back'] or ''}")) for c in cards]
        quizzes = con.execute(
            "SELECT id FROM quizzes WHERE chapter_ids LIKE ?", (f"%{cid}%",)).fetchall()
        questions: list[str] = []
        for q in quizzes:
            for r in con.execute("SELECT content FROM questions WHERE quiz_id=? LIMIT 40", (q["id"],)):
                questions.append(r["content"])

        targets = [f"【课件小节】{h}" for h in row["sections"] if not META_HEAD.search(h)] + \
                  [f"【随堂测试题】{q}" for q in questions]
        if not targets:
            continue
        blocks = []
        for t in targets:
            want = _cv_tokens(t)
            scored = sorted(((len(want & tk), f, b) for f, b, tk in toks_list),
                            key=lambda x: -x[0])
            cand = [(f, b) for n, f, b in scored[:40] if n > 0]
            body = "\n".join(f"    - 卡面：{f}｜答案要点：{(b or '')[:90]}" for f, b in cand) \
                or "    （无关键词相近的卡片）"
            blocks.append(f"【待核对考点】{t}\n  候选卡片：\n{body}")
        sys_prompt = (
            "下面是若干个「待核对考点」，每个考点后面跟着本章中**关键词相近的候选卡片**\n"
            "（含卡片正面与答案要点摘录）。请逐条判断该考点是否被候选卡片覆盖：\n"
            "同义表述、更细粒度、答案里确实包含了该考点问的细节 → 都算覆盖；\n"
            "只答大框架而缺少该细节 → 算未覆盖。严格输出 JSON，不要多余文字。\n\n"
            + "\n\n".join(blocks) + "\n\n"
            '输出格式：{"items":[{"target":"考点原文","covered":true/false,"card":"覆盖它的卡片正面或空"}]}'
        )
        try:
            data = rc.call_llm_json(sys_prompt)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 覆盖度审视失败 {row['chapter']}: {e}")
            continue
        items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
        covered = sum(1 for i in items if i.get("covered"))
        row["coverage_targets"] = len(targets)
        row["coverage_items"] = len(items)
        row["coverage_covered"] = covered
        row["missed"] = [i.get("target") for i in items if not i.get("covered")]
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--save-report", default=None, help="把未覆盖考点写成 JSON（供 rebuild_cards.py --fill-gaps 用）")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    con = sqlite3.connect(args.db, timeout=30)
    con.row_factory = sqlite3.Row

    problems, info = structural(con)
    print("=== 结构对齐 ===")
    for r in info["chapters"]:
        print(f"  {r['chapter']}")
        print(f"    资料 {r['materials']} 份 / 切片 {r['chunks']} 条 / 卡片 {r['cards']} 张"
              f"（绑定切片 {r['bound']} 张）/ sub_concept {r['sub_concepts']} 个"
              f" / 课件小节 {r['lesson_heads']} 个 / 状态 {r['status']}")
    print("\n=== 结构问题 ===")
    if problems:
        for p in problems:
            print("  ✗ " + p)
    else:
        print("  ✓ 未发现结构性问题（章节↔资料↔切片↔卡片一一对应）")

    if args.llm:
        print("\n=== 考点覆盖度（模型审视）===")
        rows = llm_coverage(con, info)
        for r in rows:
            print(f"  {r['chapter']}: {r['coverage_covered']}/{r['coverage_targets']} 条考点被覆盖")
            for m in (r.get("missed") or [])[:15]:
                print(f"      ✗ 疑似未覆盖：{m}")
        if args.save_report:
            Path(args.save_report).write_text(json.dumps(
                {"chapters": [{"chapter": r["chapter"], "missed": r.get("missed") or [],
                               "covered": r.get("coverage_covered", 0),
                               "targets": r.get("coverage_targets", 0)} for r in rows]},
                ensure_ascii=False, indent=1))
            print(f"\n报告已写入 {args.save_report}")
    con.close()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
