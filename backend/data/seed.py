"""初始种子：确保至少存在一个教师账号（首次启动自举）。"""
import os

from werkzeug.security import generate_password_hash

from data import models
from data.db import get_db


def seed_teacher() -> str:
    """若无任何用户，则用环境变量（或开发默认值）建教师账号。"""
    con = get_db()
    row = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if row["c"] > 0:
        return ""
    username = os.environ.get("TEACHER_USERNAME", "teacher")
    password = os.environ.get("TEACHER_PASSWORD", "teacher123")
    display = os.environ.get("TEACHER_DISPLAY", "西城老师")
    uid = models.new_id()
    con.execute(
        "INSERT INTO users (id, username, password_hash, role, display_name, grade, is_active, created_at)"
        " VALUES (?, ?, ?, 'teacher', ?, '', 1, ?)",
        (uid, username, generate_password_hash(password), display, models.utcnow()),
    )
    con.commit()
    return username


def seed_curriculum() -> int:
    """学习路径（8 周）种子壳：等用户课件数据就绪后由 Hermes 注入。

    本函数只留接口与空结构演示，**绝不灌真实课件/真实视频 URL**。
    真实数据注入时：
      - 创建对应 sessions（week_no/session_no/title/goal/chapter_ids/concept_tags）
      - 创建 video_resources（title/url/platform/week_no/session_no/concept_tags）
      - 预置 chapters/materials 默认 status='draft'，待教师发布 session 后学生可见。
    """
    # TODO(Hermes)：数据就绪后在此写入 8 周 × 2 Session 结构。
    return 0
