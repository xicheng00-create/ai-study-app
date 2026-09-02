"""建表 / 迁移（对齐 Design Spec §5.2，REQ-DM-001~010）。

时间一律 UTC ISO 8601 字符串。字段与 PRD §7 对齐；
RAG 降维：ChromaDB → SQLite chunks 表（REQ-DM-010 替代）。
"""
import uuid
from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('teacher','student')),
    display_name  TEXT NOT NULL DEFAULT '',
    grade         TEXT DEFAULT '',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    id         TEXT PRIMARY KEY,
    folder     TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL,
    order_no   INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft','published')),
    created_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id           TEXT PRIMARY KEY,
    chapter_id   TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_type    TEXT NOT NULL DEFAULT '',
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    uploaded_by  TEXT,
    is_deleted   INTEGER NOT NULL DEFAULT 0,
    deleted_at   TEXT,
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    status       TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft','published')),
    created_at   TEXT NOT NULL
);

-- RAG 降维替代 ChromaDB：material_id/chapter_id/chunk_idx/text
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    chapter_id  TEXT NOT NULL,
    chunk_idx   INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chapter_id TEXT,
    title      TEXT NOT NULL DEFAULT '新对话',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,
    cite            TEXT DEFAULT '',
    turn            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quizzes (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    chapter_ids  TEXT NOT NULL DEFAULT '[]',
    version      INTEGER NOT NULL DEFAULT 1,
    teacher_id   TEXT,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','superseded')),
    published_at TEXT,
    confirmed_at TEXT,
    total_points REAL NOT NULL DEFAULT 100,
    config_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id          TEXT PRIMARY KEY,
    quiz_id     TEXT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    chapter_id  TEXT NOT NULL,
    sub_concept TEXT DEFAULT '',
    type        TEXT NOT NULL DEFAULT 'choice' CHECK (type IN ('choice','bool','essay')),
    content     TEXT NOT NULL,
    options     TEXT NOT NULL DEFAULT '[]',
    answer_key  TEXT NOT NULL DEFAULT '',
    points      REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quiz_id        TEXT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    question_id    TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    chapter_id     TEXT NOT NULL,
    quiz_version   INTEGER NOT NULL,
    correct        INTEGER NOT NULL DEFAULT 0,
    score          REAL NOT NULL DEFAULT 0,
    graded_by      TEXT NOT NULL DEFAULT 'ai' CHECK (graded_by IN ('ai','teacher')),
    is_reviewed    INTEGER NOT NULL DEFAULT 0,
    reviewed_score REAL,
    answer         TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_items (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chapter_id     TEXT NOT NULL,
    question_id    TEXT,
    payload        TEXT NOT NULL DEFAULT '',
    next_review_at TEXT NOT NULL,
    interval_days  INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done')),
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start TEXT NOT NULL,
    stats      TEXT NOT NULL DEFAULT '{}',
    advice     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- 学习路径节点：周/节 → 目标 → 关联章节 → 概念标签（REQ-CURR / DM-011）
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    week_no      INTEGER NOT NULL,
    session_no   INTEGER NOT NULL,
    title        TEXT NOT NULL,
    goal         TEXT NOT NULL DEFAULT '',
    chapter_ids  TEXT NOT NULL DEFAULT '[]',   -- JSON 数组，引用 chapters.id
    concept_tags TEXT NOT NULL DEFAULT '[]',   -- JSON 数组
    milestone    TEXT DEFAULT '',
    order_no     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

-- 视频课 = 结构化元数据（不进 RAG/chunks/embedding，RAG 纯度红线）
CREATE TABLE IF NOT EXISTS video_resources (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    platform     TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    week_no      INTEGER,
    session_no   INTEGER,                       -- NULL = 整周
    concept_tags TEXT NOT NULL DEFAULT '[]',
    order_no     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_material ON chunks(material_id);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user_chapter ON attempts(user_id, chapter_id);
CREATE INDEX IF NOT EXISTS idx_review_user ON review_items(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_week ON sessions(week_no, session_no);
CREATE INDEX IF NOT EXISTS idx_videos_ws ON video_resources(week_no, session_no);
"""


def _add_column(con, table: str, column: str, ddl: str) -> bool:
    """补列并返回是否新增（True=首次迁移，供一次性数据回填判断）。"""
    cols = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in cols:
        return False
    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


def migrate(con) -> None:
    """幂等迁移：老库补 status / 百分制评分模型列（DM-004/005/006）。"""
    for table in ("chapters", "materials"):
        _add_column(con, table, "status", "TEXT NOT NULL DEFAULT 'published'")

    # 方案B（v1.4.0）：材料源文件绝对路径（serve 课件/ 源文件供下载）
    _add_column(con, "materials", "source_path", "TEXT")

    # 百分制评分模型（v1.3.0）：quizzes/questions/attempts 增量列
    _add_column(con, "quizzes", "total_points", "REAL NOT NULL DEFAULT 100")
    _add_column(con, "quizzes", "config_json", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(con, "questions", "points", "REAL NOT NULL DEFAULT 0")
    added_graded_by = _add_column(con, "attempts", "graded_by", "TEXT NOT NULL DEFAULT 'ai'")
    _add_column(con, "attempts", "is_reviewed", "INTEGER NOT NULL DEFAULT 0")
    _add_column(con, "attempts", "reviewed_score", "REAL")

    # 存量题按题型补默认分（选择/是非 5、问答 10）
    con.execute(
        "UPDATE questions SET points = CASE type WHEN 'essay' THEN 10 ELSE 5 END"
        " WHERE points = 0"
    )

    # 存量二元 score(0/1) → 实际得分点（仅首次新增 graded_by 时执行一次）
    if added_graded_by:
        con.execute(
            "UPDATE attempts SET score = CASE WHEN score > 0 THEN"
            " COALESCE((SELECT points FROM questions WHERE questions.id = attempts.question_id), 0)"
            " ELSE 0 END"
            " WHERE graded_by = 'ai'"
        )
    con.commit()
