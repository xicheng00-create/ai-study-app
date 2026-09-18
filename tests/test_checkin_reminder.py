"""19:00 未打卡提醒（NOTIF-005）：收件人口径 + 文案/萌图 + 端到端幂等。"""
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


def _prefs(client, user_id, push_enabled, remind_1900):
    from data.db import get_db

    con = get_db()
    con.execute(
        "INSERT INTO notification_prefs (user_id, push_enabled, remind_1900, updated_at)"
        " VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET"
        " push_enabled=excluded.push_enabled, remind_1900=excluded.remind_1900",
        (user_id, push_enabled, remind_1900, models.utcnow()),
    )
    con.commit()


def _count_reminders(client, user_id):
    from data.db import get_db

    con = get_db()
    row = con.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND type='streak_reminder'",
        (user_id,),
    ).fetchone()
    return row["n"]


def test_eligible_recipients_default_on(client, teacher_headers):
    """无 prefs 记录的学生也算收件人（默认开）；关掉的排除；教师不发。"""
    alice = make_student(client, teacher_headers, "alice")
    bob = make_student(client, teacher_headers, "bob")
    mod = _load_script()
    with client.application.app_context():
        _prefs(client, bob, push_enabled=1, remind_1900=0)
        ids = [r["id"] for r in mod.eligible_students(_con())]
    assert alice in ids, "没 prefs 记录的学生默认应收到提醒"
    assert bob not in ids, "关掉 remind_1900 的学生不该收到"


def test_eligible_excludes_teacher(client, teacher_headers):
    """教师不进 19:00 提醒名单。"""
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


def test_reminder_end_to_end_dedup(client, teacher_headers):
    """真跑 main()：未达标学生收到 1 条 streak_reminder，同日再跑不重复。"""
    alice = make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")   # bob 没动手，也应收到
    mod = _load_script()

    assert mod.main() == 0
    with client.application.app_context():
        assert _count_reminders(client, alice) == 1
    # 幂等：同一天再跑一次不新增
    assert mod.main() == 0
    with client.application.app_context():
        assert _count_reminders(client, alice) == 1


def _con():
    from data.db import get_db

    return get_db()
