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
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quiz_id      TEXT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    question_id  TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    chapter_id   TEXT NOT NULL,
    quiz_version INTEGER NOT NULL,
    correct      INTEGER NOT NULL DEFAULT 0,
    score        REAL NOT NULL DEFAULT 0,
    answer       TEXT DEFAULT '',
    created_at   TEXT NOT NULL
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


def migrate(con) -> None:
    """幂等迁移：老库补 status 列（默认 published，不破坏现状，REQ-CURR）。"""
    for table in ("chapters", "materials"):
        cols = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if "status" not in cols:
            con.execute(
                f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'published'"
            )
    con.commit()
