#!/usr/bin/env python3
"""每日学习建议生成脚本（REQ-RPT-003 改每日）。

遍历全部 active 学生，按当天（UTC+8）对话/练习/测评数据生成建议（复用 agents.tutor_reply，
失败给模板兜底），写入 daily_advice（UNIQUE(user_id, advice_date) 幂等 upsert）。

由 launchd `com.aistudy.daily-advice` 每天本地 22:00 触发（只写脚本与 plist，不安装）。
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # backend/scripts -> backend -> repo 根
sys.path.insert(0, str(BASE / "backend"))


def _load_env(path: Path) -> None:
    """加载 .env 到环境（DeepSeek key 等），已存在的环境变量不覆盖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def _advice_text(con, stats: dict, weak_names: list[str]) -> str:
    """AI 建议：走 TUTOR；不可用则模板兜底（参考原 reports._advice）。"""
    from ai import agents

    sys_prompt = (
        "你是「AI 学习小组」的学习教练。请根据学生今天的数据给出 3 条简短学习建议"
        "（每条一句，用「• 」开头）。数据："
        f"对话 {stats.get('conversations', 0)} 次，练习 {stats.get('practice', 0)} 次，"
        f"测评 {stats.get('quizzes', 0)} 次，薄弱章节：{'、'.join(weak_names) if weak_names else '无'}。"
    )
    out = agents.tutor_reply(sys_prompt, [])
    if out:
        return out
    if weak_names:
        return (
            f"• 优先巩固薄弱章节：{'、'.join(weak_names)}，可到「进度」页一键生成巩固练习。\n"
            "• 保持当前对话提问节奏，卡住的概念开新对话继续引导。\n"
            "• 每天完成一点对应章节练习，用错题检验掌握情况。"
        )
    return "• 今天状态良好，可推进新章节学习，并保持间隔复习节奏。"


def main() -> int:
    _load_env(BASE / ".env")
    from app import create_app
    from data import models, timeutil
    from data.db import get_db

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    today = timeutil.today_str()
    written = 0

    with app.app_context():
        con = get_db()
        students = con.execute(
            "SELECT id FROM users WHERE role='student' AND is_active=1"
        ).fetchall()
        for s in students:
            uid = s["id"]
            # 当天（UTC+8）活动统计
            convs = con.execute(
                "SELECT created_at FROM conversations WHERE user_id=?", (uid,)
            ).fetchall()
            today_convs = sum(1 for r in convs if timeutil.shanghai_date(r["created_at"]) == today)
            msgs = con.execute(
                "SELECT m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id"
                " WHERE c.user_id=? AND m.role='user'", (uid,)
            ).fetchall()
            today_turns = sum(1 for r in msgs if timeutil.shanghai_date(r["created_at"]) == today)
            practices = con.execute(
                "SELECT created_at FROM practice_sessions WHERE user_id=?", (uid,)
            ).fetchall()
            today_practice = sum(1 for r in practices if timeutil.shanghai_date(r["created_at"]) == today)
            quiz_subs = con.execute(
                "SELECT DISTINCT quiz_id, quiz_version, created_at FROM attempts WHERE user_id=?", (uid,)
            ).fetchall()
            today_quizzes = sum(1 for r in quiz_subs if timeutil.shanghai_date(r["created_at"]) == today)

            from ai import mastery
            chapters = con.execute("SELECT * FROM chapters WHERE status='published'").fetchall()
            weak_names = []
            for ch in chapters:
                m = mastery.compute_mastery(con, uid, ch["id"])
                if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
                    weak_names.append(ch["name"])

            stats = {
                "conversations": today_convs,
                "turns": today_turns,
                "practice": today_practice,
                "quizzes": today_quizzes,
            }
            advice = _advice_text(con, stats, weak_names)
            # upsert：同一天重复跑不产生重复行
            con.execute(
                "INSERT INTO daily_advice (id, user_id, advice_date, stats, advice, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id, advice_date) DO UPDATE SET"
                " stats=excluded.stats, advice=excluded.advice, created_at=excluded.created_at",
                (models.new_id(), uid, today, json.dumps(stats, ensure_ascii=False), advice, models.utcnow()),
            )
            written += 1
        con.commit()

    print(f"[daily_advice_gen] {today} written={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
