#!/usr/bin/env python3
"""每日学习建议生成脚本（REQ-RPT-003 改每日）。

遍历全部 active 学生，按当天（UTC+8）对话/练习/测评数据生成建议（复用 agents.tutor_reply，
失败给模板兜底），写入 daily_advice（UNIQUE(user_id, advice_date) 幂等 upsert）。

由 launchd `com.aistudy.daily-advice` 每天本地 22:00 触发（只写脚本与 plist，不安装）。
统计与文案生成逻辑已收敛到 ai/advice_gen.py（与进度页「生成今日建议」共用）。
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


def main() -> int:
    from ai.advice_gen import build_advice_text, today_stats

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
            # 当天（UTC+8）活动统计 + 薄弱章名（与进度页「生成今日建议」同一口径）
            stats, weak_names = today_stats(con, uid)
            advice = build_advice_text(con, stats, weak_names)
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
