"""发布 Session（教师端「发布」动作的命令行等价物），并回读联动结果。

背景：`backend/api/curriculum.py::publish_session()` 会把该 Session 下的
`chapters` / `materials` / `video_resources` 状态一并随动为 published（`_sync_content_status`）。
学生端只能看到 published 的章节资料与卡片（`GET /api/knowledge/<chapter_id>` 对 draft 章 404）。

用法：
    python scripts/publish_sessions.py --week 2 --dry-run     # 先看要发什么
    python scripts/publish_sessions.py --week 2               # 实际发布
    python scripts/publish_sessions.py --session <id前缀>     # 单发
    python scripts/publish_sessions.py --check                # 只回读当前状态与可见性
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "instance" / "aistudy.sqlite3"
API = "http://127.0.0.1:5003"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def mint(secret: str, role: str) -> str:
    import jwt  # 项目 .venv 已带
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    uid = con.execute("SELECT id FROM users WHERE role=?", (role,)).fetchone()["id"]
    con.close()
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + dt.timedelta(hours=1)},
                      secret, algorithm="HS256")


def call(method: str, path: str, token: str, api: str = API):
    req = urllib.request.Request(api + path, method=method, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def state(con: sqlite3.Connection) -> None:
    print("\n=== 当前状态 ===")
    for s in con.execute("SELECT id, week_no, session_no, title, chapter_ids, status FROM sessions ORDER BY week_no, session_no"):
        cids = json.loads(s["chapter_ids"] or "[]")
        q = ",".join("?" * len(cids)) or "''"
        ch = con.execute(f"SELECT COUNT(*) n, SUM(status='published') p FROM chapters WHERE id IN ({q})", cids).fetchone()
        mt = con.execute(f"""SELECT COUNT(*) n, SUM(status='published') p FROM materials
                             WHERE chapter_id IN ({q})""", cids).fetchone()
        vd = con.execute("""SELECT COUNT(*) n, SUM(status='published') p FROM video_resources
                            WHERE week_no=? AND session_no=?""", (s["week_no"], s["session_no"])).fetchone()
        print(f"  W{s['week_no']}S{s['session_no']} [{s['status']:9s}] {s['title'][:26]:28s}"
              f" 章节 {ch['p'] or 0}/{ch['n']} · 资料 {mt['p'] or 0}/{mt['n']} · 视频 {vd['p'] or 0}/{vd['n']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--session", default=None, help="session_id 前缀")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="只回读状态与学生可见性")
    ap.add_argument("--api", default=API)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    state(con)

    if not args.check:
        rows = con.execute("SELECT id, week_no, session_no, title, status FROM sessions ORDER BY week_no, session_no").fetchall()
        if args.week is not None:
            rows = [r for r in rows if r["week_no"] == args.week]
        if args.session:
            rows = [r for r in rows if r["id"].startswith(args.session)]
        todo = [r for r in rows if r["status"] != "published"]
        if not todo:
            print("\n没有待发布的 Session")
        else:
            print(f"\n待发布 {len(todo)} 个：" + ", ".join(f"W{r['week_no']}S{r['session_no']}" for r in todo))
            if args.dry_run:
                print("（dry-run，未执行）")
            else:
                tok = mint(load_env()["JWT_SECRET"], "teacher")
                for r in todo:
                    st, body = call("POST", f"/api/curriculum/sessions/{r['id']}/publish", tok, args.api)
                    ok = st == 200 and body.get("code") == 0
                    print(f"  发布 W{r['week_no']}S{r['session_no']} → HTTP {st} {'✓' if ok else json.dumps(body, ensure_ascii=False)[:160]}")
    con.close()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    state(con)

    # 学生可见性回读（卡片接口对 draft 章 404）
    print("\n=== 学生可见性 ===")
    env = load_env()
    stok = mint(env["JWT_SECRET"], "student")
    for c in con.execute("SELECT id, name, status FROM chapters ORDER BY folder, order_no"):
        st, body = call("GET", f"/api/knowledge/{c['id']}", stok, args.api)
        n = len(body.get("data", {}).get("cards", [])) if st == 200 else 0
        print(f"  [{c['status']:9s}] {c['name'][:26]:28s} 学生取卡 HTTP {st} 卡片 {n}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
