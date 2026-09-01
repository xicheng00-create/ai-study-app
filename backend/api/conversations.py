"""对话 Blueprint（REQ-CHAT-001~009）：学生本人对话，TUTOR 引导式。"""
from ai import tutor
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, e_not_found, ok
from middleware.input_validation import check_len
from middleware.rate_limit import rate_limit

conversations_bp = Blueprint("conversations_bp", __name__, url_prefix="/api/conversations")


def _conv_dict(row) -> dict:
    return {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "title": row["title"],
        "created_at": row["created_at"],
    }


def _own_conversation(con, conversation_id: str):
    """归属校验：非本人对话返回 403（F9）。"""
    row = con.execute(
        "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, g.user_id)
    ).fetchone()
    return row


@conversations_bp.route("", methods=["GET"])
@jwt_required
@role_required("student")
def list_conversations():
    """仅本人对话（CHAT-006）。"""
    con = get_db()
    rows = con.execute(
        "SELECT * FROM conversations WHERE user_id=? ORDER BY created_at DESC", (g.user_id,)
    ).fetchall()
    return ok({"conversations": [_conv_dict(r) for r in rows]})


@conversations_bp.route("", methods=["POST"])
@jwt_required
@role_required("student")
def create_conversation():
    data = request.get_json(silent=True) or {}
    chapter_id = (data.get("chapter_id") or "").strip() or None
    title = (data.get("title") or "新对话").strip()
    err = check_len("title", title)
    if err:
        return err
    if chapter_id:
        con = get_db()
        if con.execute("SELECT 1 FROM chapters WHERE id=?", (chapter_id,)).fetchone() is None:
            return e_not_found("章节不存在")
    uid = models.new_id()
    con = get_db()
    con.execute(
        "INSERT INTO conversations (id, user_id, chapter_id, title, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (uid, g.user_id, chapter_id, title, models.utcnow()),
    )
    con.commit()
    return ok({"id": uid})


@conversations_bp.route("/<conversation_id>", methods=["GET"])
@jwt_required
@role_required("student")
def get_conversation(conversation_id):
    con = get_db()
    conv = _own_conversation(con, conversation_id)
    if conv is None:
        # 不区分 403/404，统一 403 防探测（F9）
        return e_forbidden("只能访问本人对话")
    rows = con.execute(
        "SELECT id, role, content, cite, turn, created_at FROM messages"
        " WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
        (conversation_id,),
    ).fetchall()
    msgs = [dict(r) for r in rows]
    return ok({"conversation": _conv_dict(conv), "messages": msgs})


@conversations_bp.route("/<conversation_id>", methods=["DELETE"])
@jwt_required
@role_required("student")
def delete_conversation(conversation_id):
    con = get_db()
    conv = _own_conversation(con, conversation_id)
    if conv is None:
        return e_forbidden("只能操作本人对话")
    con.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    con.commit()
    return ok({"deleted": 1})


@conversations_bp.route("/<conversation_id>/message", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def post_message(conversation_id):
    """发送消息并返回 TUTOR 引导式回复（CHAT-002/004/005）。"""
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return e_input("消息不能为空")
    err = check_len("content", content)
    if err:
        return err
    chapter_id = (data.get("chapter_id") or "").strip() or None

    con = get_db()
    conv = _own_conversation(con, conversation_id)
    if conv is None:
        return e_forbidden("只能操作本人对话")
    user_row = con.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()

    now = models.utcnow()
    # 写用户消息
    con.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cite, turn, created_at)"
        " VALUES (?, ?, 'user', ?, '', 0, ?)",
        (models.new_id(), conversation_id, content, now),
    )

    result = tutor.tutor_orchestrate(con, user_row, conv, content, chapter_id)
    con.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cite, turn, created_at)"
        " VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
        (models.new_id(), conversation_id, result["content"], result["cite"], result["turn"] + 1, models.utcnow()),
    )
    con.commit()
    return ok({
        "reply": result["content"],
        "turn": result["turn"] + 1,
        "max_turn": tutor.MAX_TURN,
        "fallback": result["fallback"],
    })
