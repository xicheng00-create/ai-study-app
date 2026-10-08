#!/usr/bin/env python3
"""连胜冰冻（REQ-CHECKIN-013 / v2.14.0）HTTP 级独立验收脚本（PM 侧，不是 CC 的自测）。

用法：
  ./.venv/bin/python scripts/verify_streak_freeze.py --base http://127.0.0.1:5004 --db /tmp/freeze-db/test.sqlite3 [--student Winnie]

判据（任一失败 → 退出 1，打印 FAIL 明细）：
  A 静态：前端三处标记存在（#freezeChip / #freezeCount / #freezeAnim）+ index.html 的 ?v= 与 backend/app.py version 一致
  B 接口：GET /api/checkin/today 的 streak.freezes{available,granted,used} 必须等于「按库推导值」
          （granted = 2 + COUNT(daily_checkins WHERE streak_after % 5 = 0)；used = COUNT(streak_freezes)）
  C 幂等：连打两次 today，streak_freezes 行数不得增加（缺口已结算过一次），第二次 just_frozen 必须为空
  D 状态一致：streak.state ∈ {done,pending,broken}；broken ⇒ streak == 0；
          非 broken 且存在缺口 ⇒ streak 必须等于 MAX(streak_after)（被冰冻保住的数字，不是 0）
  E 缺卡口径：若 gap > available，streak 必须为 0 且该用户 streak_freezes 行数不得因本次调用增加

只读：脚本自身不写库（结算副作用来自被测接口，按 runbook 一律在「库副本 + 本地实例」上跑）。
"""
import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def env_secret(repo: Path) -> str:
    """从 .env 读 JWT_SECRET（不打印、不外传）。"""
    env = repo / ".env"
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("JWT_SECRET="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("找不到 .env 的 JWT_SECRET")


def mint(secret: str, user_id: str, role: str = "student") -> str:
    import jwt  # 项目 venv 已装

    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": now, "exp": now + 3600}, secret, algorithm="HS256"
    )


def get(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(base.rstrip("/") + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode("utf-8", "replace")


def jget(base: str, path: str, token: str):
    st, body = get(base, path, token)
    data = json.loads(body)
    return data.get("data", data)


def db_row(db: str, sql: str, args=()):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def db_all(db: str, sql: str, args=()):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5004")
    ap.add_argument("--db", required=True)
    ap.add_argument("--student", default="Winnie", help="username")
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args()
    repo = Path(a.repo)
    db = a.db

    print(f"[verify] base={a.base} db={db} student={a.student}")

    # ---------- A 静态 ----------
    print("A 前端标记与版本三件套")
    ver = None
    m = re.search(r'version\s*=\s*"([0-9.]+)"', (repo / "backend/app.py").read_text(encoding="utf-8"))
    if m:
        ver = m.group(1)
        ok(f"app.py version={ver}")
    else:
        fail("backend/app.py 未找到 version 常量")
    idx = (repo / "backend/frontend/index.html").read_text(encoding="utf-8")
    if ver and f"?v={ver}" in idx:
        ok(f"index.html 静态资源 ?v={ver} 一致")
    else:
        fail(f"index.html 未使用 ?v={ver}（CF 4h 强缓存会滞留旧 JS）")
    js = (repo / "backend/frontend/js/app.js").read_text(encoding="utf-8")
    st_js = (repo / "backend/frontend/js/student.js").read_text(encoding="utf-8")
    css = (repo / "backend/frontend/css/style.css").read_text(encoding="utf-8")
    for mark in ("freezeChip", "freezeCount"):
        if mark in js or mark in st_js:
            ok(f"前端含 {mark}")
        else:
            fail(f"前端缺少 {mark}")
    if "freezeAnim" in css or "freezeAnim" in st_js or "freezeAnim" in js:
        ok("前端含 freezeAnim（冰封动画）")
    else:
        fail("前端缺少 freezeAnim 动画层")

    # ---------- 造 token ----------
    secret = env_secret(repo)
    row = db_row(db, "SELECT id, username FROM users WHERE username=?", (a.student,))
    if not row:
        raise SystemExit(f"库 {db} 找不到用户 {a.student}")
    uid = row["id"]
    tk = mint(secret, uid)

    # ---------- B 接口 vs 库 ----------
    print("B /api/checkin/today 的 freezes 与库推导值一致")
    data = jget(a.base, "/api/checkin/today", tk)
    streak = data.get("streak") or {}
    fz = data.get("freezes") or (streak.get("freezes") if isinstance(streak, dict) else None)
    if not isinstance(fz, dict):
        fail("streak.freezes 缺失（接口未按 REQ-CHECKIN-013 下发）")
        return 1
    g_row = db_row(
        db,
        "SELECT COUNT(*) n FROM daily_checkins WHERE user_id=? AND streak_after % 5 = 0",
        (uid,),
    )
    granted = 2 + int(g_row["n"])
    used_row = db_row(db, "SELECT COUNT(*) n FROM streak_freezes WHERE user_id=?", (uid,))
    used = int(used_row["n"])
    want_avail = max(0, granted - used)
    for k, want in (("granted", granted), ("used", used), ("available", want_avail)):
        got = fz.get(k)
        if got == want:
            ok(f"freezes.{k}={got}（与库一致）")
        else:
            fail(f"freezes.{k}={got} 但库推导={want}")
    recs = db_all(db, "SELECT freeze_date, streak_kept FROM streak_freezes WHERE user_id=?"
                      " ORDER BY freeze_date DESC LIMIT 3", (uid,))
    if fz.get("records") == recs:
        ok(f"freezes.records 与库一致（{len(recs)} 条）")
    else:
        fail(f"freezes.records={fz.get('records')} 但库={recs}")

    # ---------- C 幂等 ----------
    print("C 结算幂等（连打两次不重复扣）")
    before = int(db_row(db, "SELECT COUNT(*) n FROM streak_freezes WHERE user_id=?", (uid,))["n"])
    time.sleep(0.4)
    data2 = jget(a.base, "/api/checkin/today", tk)
    after = int(db_row(db, "SELECT COUNT(*) n FROM streak_freezes WHERE user_id=?", (uid,))["n"])
    if after == before:
        ok(f"第二次调用未新增冰冻行（{before} → {after}）")
    else:
        fail(f"重复调用重复扣冰冻：{before} → {after}")
    fz2 = data2.get("freezes")
    if not isinstance(fz2, dict):
        _s2 = data2.get("streak")
        fz2 = _s2 if isinstance(_s2, dict) else {}
    jf2 = fz2.get("just_frozen") or []
    if not jf2:
        ok("第二次 just_frozen 为空（幂等，前端不会重复播动画）")
    else:
        fail(f"第二次 just_frozen 非空：{jf2}")

    # ---------- D / E 状态一致性 ----------
    print("D/E 状态与缺口口径")
    st = data.get("state")
    if st in ("done", "pending", "broken"):
        ok(f"streak.state={st}")
    else:
        fail(f"streak.state 非法：{st!r}")
    last = db_row(db, "SELECT checkin_date d, streak_after s FROM daily_checkins WHERE user_id=?"
                      " ORDER BY checkin_date DESC LIMIT 1", (uid,))
    started = data.get("today") or data.get("date")
    gap = 0
    if last and last["d"]:
        import datetime

        today = datetime.date.fromisoformat(str(data.get("today") or datetime.date.today().isoformat()))
        gap = max(0, (today - datetime.date.fromisoformat(last["d"])).days - 1)
    avail = int(fz.get("available") or 0)
    shown = int(data.get("streak") or 0)
    if data.get("state") == "broken":
        if shown == 0:
            ok("broken ⇒ streak=0")
        else:
            fail(f"broken 但 streak={shown}")
    if gap >= 1 and avail >= gap and last and last["s"]:
        if shown == int(last["s"]):
            ok(f"缺口 {gap} 天被冰冻保住，streak={shown}（= 最后一次打卡行的 streak_after）")
        else:
            fail(f"缺口已可覆盖（avail={avail} ≥ gap={gap}）但 streak={shown} ≠ {last['s']}")
    if gap > avail:
        if shown == 0:
            ok(f"gap={gap} > available={avail} ⇒ streak=0（且不得消耗）")
        else:
            fail(f"gap={gap} > available={avail} 却仍显示 streak={shown}")
        if after > before:
            fail("未覆盖的缺口仍被扣了冰冻")

    print(f"\n[verify] 结果：{'PASS' if not FAILS else 'FAIL'}（{len(FAILS)} 项失败）")
    for f in FAILS:
        print(f"  - {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
