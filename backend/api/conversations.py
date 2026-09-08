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


def _summary_title(content: str) -> str:
    """取首条用户消息前 18 字符作摘要标题（去多余空白，避免一排「新对话」）。"""
    text = " ".join(content.split())
    if len(text) <= 18:
        return text
    return text[:18] + "…"


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
    concept_tags = data.get("concept_tags") or []
    chapter_ids = data.get("chapter_ids") or []
    wrong_ctx = data.get("wrong_ctx") or []
    # 知识卡片「去问 TUTOR」上下文（v2.1.0）：仅接受白名单字段的字符串
    kc_ctx = data.get("kc_ctx") or None
    if kc_ctx is not None:
        if not isinstance(kc_ctx, dict):
            return e_input("kc_ctx 需为对象")
        kc_ctx = {k: str(kc_ctx.get(k) or "")[:2000] for k in ("front", "back", "sub_concept", "chapter_id")}
        if not kc_ctx.get("front"):
            kc_ctx = None
    # 辅导模式开关：仅接受 guide/direct，非法或缺失默认 direct（直接讲解）
    tutor_mode = data.get("tutor_mode") if data.get("tutor_mode") in ("guide", "direct") else "direct"
    if (not isinstance(concept_tags, list) or not isinstance(chapter_ids, list)
            or not isinstance(wrong_ctx, list)):
        return e_input("concept_tags / chapter_ids / wrong_ctx 需为数组")
    if len(wrong_ctx) > 20:
        return e_input("wrong_ctx 最多 20 题")
    for item in wrong_ctx:
        if not isinstance(item, dict):
            return e_input("wrong_ctx 每项需为对象")

    con = get_db()
    conv = _own_conversation(con, conversation_id)
    if conv is None:
        return e_forbidden("只能操作本人对话")
    user_row = con.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()

    # 首条用户消息 → 用内容摘要生成对话标题（CHAT-008：不再一排「新对话」）
    is_first = con.execute(
        "SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1", (conversation_id,)
    ).fetchone() is None
    new_title = _summary_title(content) if is_first else conv["title"]
    if is_first:
        con.execute("UPDATE conversations SET title=? WHERE id=?", (new_title, conversation_id))

    now = models.utcnow()
    # 写用户消息
    con.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cite, turn, created_at)"
        " VALUES (?, ?, 'user', ?, '', 0, ?)",
        (models.new_id(), conversation_id, content, now),
    )

    result = tutor.tutor_orchestrate(
        con, user_row, conv, content, chapter_id, concept_tags=concept_tags,
        chapter_ids=chapter_ids, wrong_ctx=wrong_ctx, tutor_mode=tutor_mode, kc_ctx=kc_ctx
    )
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
        "related_videos": result.get("related_videos", []),
        "title": new_title,
    })
