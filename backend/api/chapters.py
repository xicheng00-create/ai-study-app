"""章节 Blueprint（REQ-MAT-001/004/007）：教师写、全班读。"""
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from middleware.input_validation import check_len, require_fields

chapters_bp = Blueprint("chapters_bp", __name__, url_prefix="/api/chapters")


def _chapter_row(row) -> dict:
    return {
        "id": row["id"],
        "folder": row["folder"],
        "name": row["name"],
        "order_no": row["order_no"],
        "created_by": row["created_by"],
    }


@chapters_bp.route("", methods=["GET"])
@jwt_required
def list_chapters():
    """全班共享只读（MAT-004）。按 folder + order_no 排序。"""
    con = get_db()
    rows = con.execute(
        "SELECT * FROM chapters ORDER BY folder, order_no, name"
    ).fetchall()
    return ok({"chapters": [_chapter_row(r) for r in rows]})


@chapters_bp.route("", methods=["POST"])
@jwt_required
@role_required("teacher")
def create_chapter():
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("name",))
    if bad:
        return bad
    name = data["name"].strip()
    folder = (data.get("folder") or "").strip()
    for field, val in (("name", name), ("folder", folder)):
        err = check_len(field, val)
        if err:
            return err
    order_no = int(data.get("order_no") or 0)
    uid = models.new_id()
    con = get_db()
    con.execute(
        "INSERT INTO chapters (id, folder, name, order_no, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (uid, folder, name, order_no, g.user_id, models.utcnow()),
    )
    con.commit()
    return ok({"id": uid})


@chapters_bp.route("/<chapter_id>", methods=["PUT"])
@jwt_required
@role_required("teacher")
def update_chapter(chapter_id):
    data = request.get_json(silent=True) or {}
    con = get_db()
    row = con.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if row is None:
        return e_not_found("章节不存在")
    name = (data.get("name") or row["name"]).strip()
    folder = (data.get("folder") if data.get("folder") is not None else row["folder"]).strip()
    order_no = int(data.get("order_no", row["order_no"]))
    for field, val in (("name", name), ("folder", folder)):
        err = check_len(field, val)
        if err:
            return err
    con.execute(
        "UPDATE chapters SET name=?, folder=?, order_no=? WHERE id=?",
        (name, folder, order_no, chapter_id),
    )
    con.commit()
    return ok({"id": chapter_id})


@chapters_bp.route("/<chapter_id>", methods=["DELETE"])
@jwt_required
@role_required("teacher")
def delete_chapter(chapter_id):
    con = get_db()
    row = con.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if row is None:
        return e_not_found("章节不存在")
    # 章节下有资料时禁止删除（防孤儿；资料先软删）
    mat = con.execute("SELECT COUNT(*) AS c FROM materials WHERE chapter_id=? AND is_deleted=0",
                      (chapter_id,)).fetchone()
    if mat["c"] > 0:
        return e_input("该章节下仍有资料，请先删除资料")
    con.execute("DELETE FROM chapters WHERE id = ?", (chapter_id,))
    con.commit()
    return ok({"deleted": 1})
