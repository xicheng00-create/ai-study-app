"""卡片 ↔ 切片绑定精度审计（纯本地、零 LLM 成本）。

背景（必读）：卡片绑定切片有两条路径——
    ① 按构造绑定（逐片生成时 source_chunk_id 直接写入）→ 精确；
    ② 按内容重合度回绑（fill_gaps / rebind_recent 事后找片）→ 会错。
另外「教案片组」路径生成的卡片默认绑到片组的首片，组内跨多片时也会错。
2026-09-19 实测：全库 2384 张卡精确率仅 61.1%，回绑后 84.9%。所以：

**每次生成/补卡之后，必须跑一次 `--rebind`。**

用法：
    python scripts/audit_binding.py                 # 只看统计
    python scripts/audit_binding.py --top 20        # 打印最差的 N 张
    python scripts/audit_binding.py --rebind        # 弱匹配卡片回绑到同资料内更吻合的切片
    python scripts/audit_binding.py --report x.json # 明细落盘
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "instance" / "aistudy.sqlite3"

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\.\-_]{1,}")
_NUM = re.compile(r"\d+")
STOP = {"什么", "什么?", "哪些", "以下", "关于", "描述", "是否", "如何", "为什么", "的是", "指的是"}


def tokens(text: str) -> list[str]:
    """中英混排粗分词：英文词 + 数字 + 中文 2-gram。"""
    out = [w.lower() for w in _WORD.findall(text)]
    out += ["num:" + n for n in _NUM.findall(text)]
    han = re.sub(r"[^\u4e00-\u9fff]", "", text)
    out += [han[i : i + 2] for i in range(len(han) - 1) if han[i : i + 2] not in STOP]
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b, self.docs = k1, b, docs
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(1, self.N)
        self.tf = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.df = df

    def score(self, q: list[str], i: int) -> float:
        tf, dl = self.tf[i], len(self.docs[i])
        s = 0.0
        for t in set(q):
            f = tf.get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (self.N - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5))
            s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s


def scan(db: Path = DB, ratio: float = 1.35, rank_cut: int = 3) -> dict:
    """在「同一份资料」的切片池里给绑定切片排 BM25 名次。返回统计 + 弱匹配明细 + 可回绑清单。"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    chunks = {r["id"]: {"id": r["id"], "material_id": r["material_id"], "idx": r["chunk_idx"], "text": r["text"]}
              for r in con.execute("SELECT id, material_id, chunk_idx, text FROM chunks")}
    by_mat: dict[str, list[dict]] = {}
    for c in chunks.values():
        by_mat.setdefault(c["material_id"], []).append(c)
    for v in by_mat.values():
        v.sort(key=lambda x: x["idx"])
    names = {r["id"]: r["original_name"] for r in con.execute("SELECT id, original_name FROM materials")}
    cards = list(con.execute("SELECT id, sub_concept, front, back, source_chunk_id FROM knowledge_cards"))
    con.close()

    total = len(cards)
    unbound = sum(1 for c in cards if not c["source_chunk_id"])
    ranked = {"rank1": 0, "rank2-3": 0, "rank4+": 0}
    weak: list[dict] = []
    for c in cards:
        scid = c["source_chunk_id"]
        if not scid or scid not in chunks:
            continue
        mat = chunks[scid]["material_id"]
        pool = by_mat.get(mat) or []
        if len(pool) < 2:
            ranked["rank1"] += 1
            continue
        bm = BM25([tokens(p["text"]) for p in pool])
        q = tokens(f"{c['front']} {c['back']}")
        scores = sorted(((bm.score(q, i), p) for i, p in enumerate(pool)), key=lambda x: -x[0])
        order = [p["id"] for _, p in scores]
        r = order.index(scid) + 1
        ranked["rank1" if r == 1 else ("rank2-3" if r <= 3 else "rank4+")] += 1
        if r > 1:
            bound_s = next(s for s, p in scores if p["id"] == scid)
            weak.append({
                "card_id": c["id"], "front": c["front"][:60], "rank": r, "pool": len(pool),
                "bound_idx": chunks[scid]["idx"], "best_idx": scores[0][1]["idx"],
                "best_ratio": round(scores[0][0] / max(bound_s, 1e-6), 2),
                "material": names.get(mat, "?"), "material_id": mat,
                "best_chunk_id": scores[0][1]["id"], "bound_chunk_id": scid,
                "bound_snippet": chunks[scid]["text"][:110].replace("\n", " "),
                "best_snippet": scores[0][1]["text"][:110].replace("\n", " "),
            })
    weak.sort(key=lambda x: -x["rank"])
    rebindable = [w for w in weak if w["rank"] > rank_cut and w["best_ratio"] >= ratio]
    denom = max(1, total - unbound)
    return {"total": total, "unbound": unbound, "ranked": ranked, "weak": weak,
            "rebindable": rebindable, "precision": round(ranked["rank1"] / denom * 100, 1)}


def rebind_weak(db: Path | str = DB, ratio: float = 1.35, rank_cut: int = 3, verbose: bool = True) -> int:
    """把弱匹配卡片改绑到同资料内更吻合的切片。返回改绑数量。供 rebuild_cards.py 生成后自动调用。"""
    db = Path(db)
    res = scan(db, ratio=ratio, rank_cut=rank_cut)
    todo = res["rebindable"]
    if todo:
        w = sqlite3.connect(db)
        w.executemany("UPDATE knowledge_cards SET source_chunk_id=? WHERE id=?",
                      [(x["best_chunk_id"], x["card_id"]) for x in todo])
        w.commit()
        w.close()
    if verbose:
        print(f"[rebind] 精确率 {res['precision']}% | 弱匹配 {len(res['weak'])} 张 | 回绑 {len(todo)} 张"
              f"（排名>{rank_cut} 且倍数≥{ratio}）")
    return len(todo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="打印最差 N 张卡")
    ap.add_argument("--rebind", action="store_true", help="对弱匹配卡片回绑到同资料最佳切片")
    ap.add_argument("--ratio", type=float, default=1.35, help="最佳切片须比绑定切片高多少倍才回绑")
    ap.add_argument("--rank-cut", type=int, default=3, help="绑定切片排名差于此值才考虑回绑")
    ap.add_argument("--report", default="", help="把明细写入 JSON 文件")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    res = scan(Path(args.db), ratio=args.ratio, rank_cut=args.rank_cut)
    r = res["ranked"]
    print(f"卡片总数 {res['total']} | 未绑切片 {res['unbound']}")
    print(f"绑定切片排名：第1名 {r['rank1']} | 第2-3名 {r['rank2-3']} | 第4名及以后 {r['rank4+']}")
    print(f"精确率（绑定切片即同资料内最佳）= {r['rank1']}/{res['total'] - res['unbound']} = {res['precision']}%")
    if args.top:
        print(f"\n--- 最差 {args.top} 张 ---")
        for w in res["weak"][: args.top]:
            print(f"  排名{w['rank']:3d}/{w['pool']:<3d} 倍数{w['best_ratio']:<9} {w['front'][:44]}")
            print(f"      现绑[#{w['bound_idx']}] {w['bound_snippet'][:80]}")
            print(f"      更佳[#{w['best_idx']}] {w['best_snippet'][:80]}")
    print(f"\n符合回绑条件（排名>{args.rank_cut} 且倍数≥{args.ratio}）：{len(res['rebindable'])} 张")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"明细已写 {args.report}")
    if args.rebind:
        n = rebind_weak(Path(args.db), args.ratio, args.rank_cut)
        print(f"已回绑 {n} 张")


if __name__ == "__main__":
    main()
