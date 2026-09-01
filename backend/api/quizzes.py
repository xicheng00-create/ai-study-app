"""测评 Blueprint（REQ-QUIZ-001/007/008）：教师草稿→确认发布，全班同题。"""
import json

from ai import quizzer
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, e_role, ok
from middleware.input_validation import check_len
from middleware.rate_limit import rate_limit

quizzes_bp = Blueprint("quizzes_bp", __name__, url_prefix="/api/quizzes")


def _quiz_dict(row, with_status=False) -> dict:
    d = {
        "id": row["id"],
        "title": row["title"],
        "chapter_ids": _parse_ids(row["chapter_ids"]),
        "version": row["version"],
        "status": row["status"],
        "published_at": row["published_at"],
    }
    if with_status:
        d["created_at"] = row["created_at"]
    return d


def _parse_ids(raw: str) -> list[str]:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _get_quiz_or_404(con, quiz_id: str):
    row = con.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if row is None:
        return None
    return row


@quizzes_bp.route("", methods=["GET"])
@jwt_required
def list_quizzes():
    con = get_db()
    if g.role == "teacher":
        rows = con.execute("SELECT * FROM quizzes ORDER BY created_at DESC").fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM quizzes WHERE status='published' ORDER BY published_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = _quiz_dict(r, with_status=True)
        if g.role == "student":
            # 学生视角：标记最近一次成绩（可重做取最近，QUIZ-002）
            latest = con.execute(
                "SELECT MAX(created_at) AS t FROM attempts"
                " WHERE user_id=? AND quiz_id=? AND quiz_version=?",
                (g.user_id, r["id"], r["version"]),
            ).fetchone()
            if latest["t"]:
                agg = con.execute(
                    "SELECT AVG(score) AS s, COUNT(*) AS c FROM attempts"
                    " WHERE user_id=? AND quiz_id=? AND quiz_version=? AND created_at=?",
                    (g.user_id, r["id"], r["version"], latest["t"]),
                ).fetchone()
                d["taken"] = True
                d["score"] = round(agg["s"] * 100, 1) if agg["c"] else None
            else:
                d["taken"] = False
                d["score"] = None
        out.append(d)
    return ok({"quizzes": out})


@quizzes_bp.route("/draft", methods=["POST"])
@jwt_required
@role_required("teacher")
@rate_limit(limit=60)
def create_draft():
    """生成草稿（QUIZ-001）：选章 → QUIZZER 出题 → status=draft。"""
    data = request.get_json(silent=True) or {}
    chapter_ids = data.get("chapter_ids") or []
    if not isinstance(chapter_ids, list) or not chapter_ids:
        return e_input("请至少选择一章")
    title = (data.get("title") or f"草稿 · {len(chapter_ids)} 章").strip()
    err = check_len("title", title)
    if err:
        return err
    con = get_db()
    for cid in chapter_ids:
        if con.execute("SELECT 1 FROM chapters WHERE id=?", (cid,)).fetchone() is None:
            return e_not_found(f"章节不存在：{cid}")

    raw_qs = quizzer.generate_questions(
        chapter_ids,
        sub_concepts=data.get("sub_concepts", ""),
        spec=data.get("spec", ""),
    )
    quiz_id = models.new_id()
    now = models.utcnow()
    con.execute(
        "INSERT INTO quizzes (id, title, chapter_ids, version, teacher_id, status, created_at)"
        " VALUES (?, ?, ?, 1, ?, 'draft', ?)",
        (quiz_id, title, json.dumps(chapter_ids, ensure_ascii=False), g.user_id, now),
    )
    # 每个章节至少一题：按顺序把题目轮转分配到所选章节
    for i, raw in enumerate(raw_qs):
        cid = chapter_ids[i % len(chapter_ids)]
        q = quizzer.norm_question(raw, cid)
        con.execute(
            "INSERT INTO questions (id, quiz_id, chapter_id, sub_concept, type, content, options, answer_key, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), quiz_id, cid, q["sub_concept"], q["type"], q["content"],
             q["options"], q["answer_key"], now),
        )
    con.commit()
    return ok({"id": quiz_id, "question_count": len(raw_qs)})


@quizzes_bp.route("/<quiz_id>/publish", methods=["POST"])
@jwt_required
@role_required("teacher")
def publish_quiz(quiz_id):
    """确认发布（QUIZ-001/008）：draft → published。"""
    con = get_db()
    row = _get_quiz_or_404(con, quiz_id)
    if row is None:
        return e_not_found("测评不存在")
    if row["status"] != "draft":
        return e_input("仅草稿可发布")
    count = con.execute("SELECT COUNT(*) AS c FROM questions WHERE quiz_id=?", (quiz_id,)).fetchone()
    if count["c"] == 0:
        return e_input("草稿无题目，无法发布")
    now = models.utcnow()
    con.execute(
        "UPDATE quizzes SET status='published', published_at=?, confirmed_at=? WHERE id=?",
        (now, now, quiz_id),
    )
    con.commit()
    return ok({"id": quiz_id, "status": "published"})


@quizzes_bp.route("/<quiz_id>/revision", methods=["POST"])
@jwt_required
@role_required("teacher")
@rate_limit(limit=60)
def revision_quiz(quiz_id):
    """重出生成新 version（QUIZ-007，F3：旧版保留 superseded）。"""
    con = get_db()
    old = _get_quiz_or_404(con, quiz_id)
    if old is None:
        return e_not_found("测评不存在")
    if old["status"] not in ("published", "superseded"):
        return e_input("仅已发布测评可重出")
    new_version = old["version"] + 1
    chapter_ids = _parse_ids(old["chapter_ids"])
    raw_qs = quizzer.generate_questions(chapter_ids)
    new_id = models.new_id()
    now = models.utcnow()
    con.execute(
        "INSERT INTO quizzes (id, title, chapter_ids, version, teacher_id, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'draft', ?)",
        (new_id, f"{old['title']} · v{new_version}", json.dumps(chapter_ids, ensure_ascii=False),
         new_version, g.user_id, now),
    )
    for i, raw in enumerate(raw_qs):
        cid = chapter_ids[i % len(chapter_ids)]
        q = quizzer.norm_question(raw, cid)
        con.execute(
            "INSERT INTO questions (id, quiz_id, chapter_id, sub_concept, type, content, options, answer_key, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), new_id, cid, q["sub_concept"], q["type"], q["content"],
             q["options"], q["answer_key"], now),
        )
    con.execute("UPDATE quizzes SET status='superseded' WHERE id=?", (quiz_id,))
    con.commit()
    return ok({"id": new_id, "version": new_version})


@quizzes_bp.route("/<quiz_id>", methods=["GET"])
@jwt_required
def get_quiz(quiz_id):
    con = get_db()
    row = _get_quiz_or_404(con, quiz_id)
    if row is None:
        return e_not_found("测评不存在")
    if g.role == "student" and row["status"] != "published":
        return e_role("该测评尚未发布")
    questions = con.execute(
        "SELECT id, chapter_id, sub_concept, type, content, options FROM questions"
        " WHERE quiz_id=? ORDER BY rowid", (quiz_id,)
    ).fetchall()
    # 学生不可见 answer_key（作答前）；教师可见
    qs = []
    for q in questions:
        d = dict(q)
        d["options"] = json.loads(q["options"] or "[]")
        if g.role == "student":
            d.pop("answer_key", None)
        qs.append(d)
    return ok({"quiz": _quiz_dict(row, with_status=True), "questions": qs})


@quizzes_bp.route("/<quiz_id>", methods=["DELETE"])
@jwt_required
@role_required("teacher")
def delete_quiz(quiz_id):
    """仅草稿可删除；已发布走 supersede（防误删）。"""
    con = get_db()
    row = _get_quiz_or_404(con, quiz_id)
    if row is None:
        return e_not_found("测评不存在")
    if row["status"] != "draft":
        return e_input("已发布测评不可删除，请用「重出」替换")
    con.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
    con.commit()
    return ok({"deleted": 1})
