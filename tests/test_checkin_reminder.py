"""每晚阶梯式未达标提醒（NOTIF-005/009）：收件人口径 + 文案/萌图 + 端到端幂等。"""
import importlib.util
from pathlib import Path

from conftest import make_student
from data import models

SCRIPT = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "checkin_reminder.py"


def _load_script():
    """按文件路径加载 launchd 用的脚本（不是包，只能这样导入；main() 有 __main__ 守卫）。"""
    spec = importlib.util.spec_from_file_location("checkin_reminder_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prefs(client, user_id, push_enabled, remind_daily):
    from data.db import get_db

    con = get_db()
    con.execute(
        "INSERT INTO notification_prefs (user_id, push_enabled, remind_daily, updated_at)"
        " VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET"
        " push_enabled=excluded.push_enabled, remind_daily=excluded.remind_daily",
        (user_id, push_enabled, remind_daily, models.utcnow()),
    )
    con.commit()


def _count(client, user_id, ntype="streak_reminder", ref_id=None):
    from data.db import get_db

    con = get_db()
    sql = "SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND type=?"
    args = [user_id, ntype]
    if ref_id is not None:
        sql += " AND ref_id=?"
        args.append(ref_id)
    return con.execute(sql, args).fetchone()["n"]


def test_eligible_recipients_default_on(client, teacher_headers):
    """无 prefs 记录的学生也算收件人（默认开）；关掉的排除；教师不发。"""
    alice = make_student(client, teacher_headers, "alice")
    bob = make_student(client, teacher_headers, "bob")
    mod = _load_script()
    with client.application.app_context():
        _prefs(client, bob, push_enabled=1, remind_daily=0)
        ids = [r["id"] for r in mod.eligible_students(_con())]
    assert alice in ids, "没 prefs 记录的学生默认应收到提醒"
    assert bob not in ids, "关掉 remind_daily 的学生不该收到"


def test_eligible_excludes_teacher(client, teacher_headers):
    """教师不进提醒名单。"""
    make_student(client, teacher_headers, "alice")
    mod = _load_script()
    with client.application.app_context():
        rows = mod.eligible_students(_con())
    assert rows and all(r["username"] != "teacher" for r in rows)


def test_copy_three_branches_and_images():
    """三条文案分支 + 萌图选择（纯函数，不调 LLM）。"""
    from ai.reminder_copy import IMG_HOT, IMG_LOW, IMG_OK, reminder_copy

    hot = reminder_copy("然然", 3, 0, 0)          # 连胜 ≥3 + 今日 0 进度 → 快灭
    assert "3 天连胜要熄火了" in hot["body"] and hot["image"] == IMG_LOW
    mid = reminder_copy("然然", 5, 4, 1)          # 连胜中 + 有部分进度
    assert "保住 5 天连胜" in mid["body"] and mid["image"] == IMG_OK
    new = reminder_copy("然然", 0, 0, 0)          # 无连胜
    assert "火焰还没点起来" in new["body"]
    assert reminder_copy("然然", 7, 0, 0)["image"] == IMG_HOT   # 连胜 ≥7 → 暖黄
    for c in (hot, mid, new):
        assert c["title"].startswith("🔥") and c["body"].strip()


def test_copy_five_slots_tone_progression():
    """五档文案存在且逐档语气升级（L2 卖萌 / L3 急切 / L5 最后通牒）。"""
    from ai.reminder_copy import reminder_copy

    l2 = reminder_copy("然然", 3, 0, 0, "L2")
    assert "小火焰" in l2["body"]
    l3 = reminder_copy("然然", 3, 0, 0, "L3")
    assert "连胜今晚就要归零" in l3["body"]
    l5 = reminder_copy("然然", 3, 0, 0, "L5")
    assert "不到 1 小时" in l5["body"]


def test_slot_for_hour_boundaries():
    """slot_for_hour 边界：19→L1、23→L5、18/0→None。"""
    from ai.reminder_copy import slot_for_hour

    assert slot_for_hour(19) == "L1"
    assert slot_for_hour(23) == "L5"
    assert slot_for_hour(18) is None
    assert slot_for_hour(0) is None


def test_reminder_end_to_end_dedup(client, teacher_headers):
    """真跑 main()：未达标学生收到 1 条 streak_reminder，同日再跑不重复。"""
    alice = make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")   # bob 没动手，也应收到
    mod = _load_script()

    assert mod.main(["--slot", "L1"]) == 0
    with client.application.app_context():
        assert _count(client, alice) == 1
    # 幂等：同一天同一档再跑一次不新增
    assert mod.main(["--slot", "L1"]) == 0
    with client.application.app_context():
        assert _count(client, alice) == 1


def test_reminder_same_day_five_slots_each_once(client, teacher_headers):
    """同一天 5 个档位各落 1 条；同一档重跑只落 1 条。"""
    alice = make_student(client, teacher_headers, "alice")
    mod = _load_script()

    assert mod.main(["--slot", "L1"]) == 0
    assert mod.main(["--slot", "L1"]) == 0
    for slot in ("L2", "L3", "L4", "L5"):
        assert mod.main(["--slot", slot]) == 0
    with client.application.app_context():
        assert _count(client, alice) == 5


def test_qualified_student_skips_all_slots(client, teacher_headers, monkeypatch):
    """达标学生后续档位不再发（达标即停）。"""
    alice = make_student(client, teacher_headers, "alice")
    bob = make_student(client, teacher_headers, "bob")
    mod = _load_script()

    from data import checkin as ck

    real = ck.counts_today

    def fake(con, uid):
        return {"cards": 30, "questions": 5} if uid == alice else real(con, uid)

    monkeypatch.setattr(ck, "counts_today", fake)
    assert mod.main(["--slot", "L1"]) == 0
    with client.application.app_context():
        assert _count(client, alice) == 0, "达标学生不该收到提醒"
        assert _count(client, bob) == 1


def test_lapse_prefix():
    """lapse_days>=2 时正文带「已经 N 天没见到你了…」前缀。"""
    from ai.reminder_copy import reminder_copy

    assert reminder_copy("然然", 0, 0, 0, "L1", 1)["body"].startswith("🔥")
    assert reminder_copy("然然", 0, 0, 0, "L1", 3)["body"].startswith("已经 3 天没见到你了…")


def test_l3_absent_digest(client, teacher_headers):
    """L3 有未达标学生时给教师发 absent_digest。"""
    make_student(client, teacher_headers, "alice")
    mod = _load_script()
    assert mod.main(["--slot", "L3"]) == 0
    with client.application.app_context():
        con = _con()
        teacher = con.execute("SELECT id FROM users WHERE role='teacher' AND is_active=1").fetchone()
        assert teacher is not None
        assert _count(client, teacher["id"], "absent_digest") == 1


def test_l3_no_absent_no_digest(client, teacher_headers, monkeypatch):
    """L3 无未达标学生时不发教师名单。"""
    make_student(client, teacher_headers, "alice")
    mod = _load_script()

    from data import checkin as ck

    monkeypatch.setattr(ck, "counts_today", lambda con, uid: {"cards": 30, "questions": 5})
    assert mod.main(["--slot", "L3"]) == 0
    with client.application.app_context():
        con = _con()
        teacher = con.execute("SELECT id FROM users WHERE role='teacher' AND is_active=1").fetchone()
        assert _count(client, teacher["id"], "absent_digest") == 0


def _con():
    from data.db import get_db

    return get_db()
