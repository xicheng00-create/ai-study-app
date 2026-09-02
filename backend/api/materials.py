"""资料 Blueprint（REQ-MAT-002/003/004/005/007）。

上传同步解析分块写 SQLite chunks（RAG 降维）；删除走软删（F7）。
"""
import os

from ai import parser
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, current_app, g, request, send_file
from middleware.errors import e_input, e_not_found, e_role, ok
from middleware.rate_limit import rate_limit

materials_bp = Blueprint("materials_bp", __name__, url_prefix="/api/materials")

MAX_SIZE = 30 * 1024 * 1024  # 30MB（MAT-002）


def _material_dict(row) -> dict:
    return {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "filename": row["filename"],
        "original_name": row["original_name"],
        "file_type": row["file_type"],
        "size_bytes": row["size_bytes"],
        "chunk_count": row["chunk_count"],
        "parse_status": row["parse_status"],
        "is_deleted": bool(row["is_deleted"]),
        "created_at": row["created_at"],
    }


def _save_original(uid: str, ext: str, blob: bytes) -> str:
    folder = current_app.config.get("UPLOAD_FOLDER")
    if not folder:
        folder = os.path.join(current_app.root_path, "..", "uploads")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uid}.{ext}")
    with open(path, "wb") as fh:
        fh.write(blob)
    return path


@materials_bp.route("", methods=["GET"])
@jwt_required
def list_materials():
    """全班共享只读（MAT-004）：学生仅 published 且未软删，教师全部。"""
    chapter_id = request.args.get("chapter_id")
    con = get_db()
    if g.role == "teacher":
        if chapter_id:
            rows = con.execute(
                "SELECT * FROM materials WHERE chapter_id=? AND is_deleted=0 ORDER BY created_at",
                (chapter_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM materials WHERE is_deleted=0 ORDER BY created_at"
            ).fetchall()
    else:
        if chapter_id:
            rows = con.execute(
                "SELECT * FROM materials WHERE chapter_id=? AND is_deleted=0 AND status='published' ORDER BY created_at",
                (chapter_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM materials WHERE is_deleted=0 AND status='published' ORDER BY created_at"
            ).fetchall()
    return ok({"materials": [_material_dict(r) for r in rows]})


@materials_bp.route("/upload", methods=["POST"])
@jwt_required
@role_required("teacher")
@rate_limit(limit=120)
def upload():
    """教师上传资料并归入章节，同步解析分块（MAT-002/003）。"""
    chapter_id = request.form.get("chapter_id", "")
    if not chapter_id:
        return e_input("缺少 chapter_id")
    f = request.files.get("file")
    if f is None or f.filename == "":
        return e_input("缺少文件")
    blob = f.read()
    if len(blob) > MAX_SIZE:
        return e_input("文件超过 30MB 上限")
    original_name = f.filename
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in parser.SUPPORTED:
        return e_input(f"不支持的文件类型：{ext or '无扩展名'}")

    con = get_db()
    ch = con.execute("SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if ch is None:
        return e_not_found("章节不存在")

    uid = models.new_id()
    # 解析（失败不阻断上传，标记 parse_status=failed 供教师查看）
    text = ""
    parse_status = "pending"
    try:
        text = parser.extract_text(original_name, blob)
        parse_status = "parsed" if text.strip() else "failed"
    # 解析失败不阻断上传，标记 failed 供教师重试
    except Exception:  # noqa: BLE001
        parse_status = "failed"

    _save_original(uid, ext or "bin", blob)
    chunk_list = parser.chunk_text_list(text) if parse_status == "parsed" else []
    now = models.utcnow()
    con.execute(
        "INSERT INTO materials (id, chapter_id, filename, original_name, file_type, size_bytes,"
        " uploaded_by, is_deleted, deleted_at, chunk_count, parse_status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)",
        (uid, chapter_id, f"{uid}.{ext}", original_name, ext, len(blob), g.user_id,
         len(chunk_list), parse_status, now),
    )
    for c in chunk_list:
        con.execute(
            "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (models.new_id(), uid, chapter_id, c["chunk_idx"], c["text"], now),
        )
    con.commit()
    return ok({"id": uid, "parse_status": parse_status, "chunk_count": len(chunk_list)})


@materials_bp.route("/<material_id>", methods=["DELETE"])
@jwt_required
@role_required("teacher")
def delete_material(material_id):
    """软删除（F7）：is_deleted=1，保留 7 天硬删窗口。"""
    con = get_db()
    row = con.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    if row is None:
        return e_not_found("资料不存在")
    con.execute(
        "UPDATE materials SET is_deleted=1, deleted_at=? WHERE id=?",
        (models.utcnow(), material_id),
    )
    con.commit()
    return ok({"deleted": 1, "soft": True})


@materials_bp.route("/<material_id>/download", methods=["GET"])
@jwt_required
def download_material(material_id):
    """方案B下载：serve 课件/ 源文件。学生仅已发布可下，教师全下。"""
    con = get_db()
    row = con.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if row is None:
        return e_not_found("资料不存在")
    if g.role != "teacher" and row["status"] != "published":
        return e_role("该资料尚未发布，不可下载")
    src = row["source_path"]
    if not src or not os.path.isfile(src):
        return e_not_found("源文件不存在")
    return send_file(src, as_attachment=True, download_name=row["original_name"])
