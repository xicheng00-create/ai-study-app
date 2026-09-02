"""鉴权 Blueprint（REQ-AUTH-001~008）。"""
from auth.jwt_utils import jwt_required, make_token, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_auth, e_input, ok
from middleware.input_validation import check_len, require_fields
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth_bp", __name__, url_prefix="/api/auth")


def _user_dict(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "is_active": bool(row["is_active"]),
    }


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("username", "password"))
    if bad:
        return bad
    con = get_db()
    row = con.execute(
        "SELECT * FROM users WHERE username = ?", (data["username"].strip(),)
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], data["password"]):
        return e_auth("账号或密码错误")
    if not row["is_active"]:
        return e_auth("账号已停用")
    token = make_token(row["id"], row["role"])
    return ok({"token": token, "role": row["role"], "display_name": row["display_name"], "user_id": row["id"]})


@auth_bp.route("/register", methods=["POST"])
@jwt_required
@role_required("teacher")
def register():
    """教师创建学生账号（AUTH-002）。"""
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("username", "password"))
    if bad:
        return bad
    username = data["username"].strip()
    display_name = (data.get("display_name") or username).strip()
    # 年级维度已移除（v1.5.0）：不再收集/存储 grade
    grade = ""
    for field, val in (("username", username), ("display_name", display_name)):
        err = check_len(field, val)
        if err:
            return err
    # 仅允许教师创建 student 账号（角色白名单）
    role = data.get("role", "student")
    if role not in ("student", "teacher"):
        return e_input("角色仅支持 student/teacher")
    con = get_db()
    if con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return e_input("用户名已存在")
    uid = models.new_id()
    con.execute(
        "INSERT INTO users (id, username, password_hash, role, display_name, grade, is_active, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (uid, username, generate_password_hash(data["password"]), role, display_name, grade, models.utcnow()),
    )
    con.commit()
    return ok({"id": uid})


@auth_bp.route("/me", methods=["GET"])
@jwt_required
def me():
    con = get_db()
    row = con.execute("SELECT * FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if row is None:
        return e_auth("账号不存在")
    return ok(_user_dict(row))


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required
def refresh():
    """临近过期换发新 token（AUTH-005，无 refresh token，直接重签）。"""
    token = make_token(g.user_id, g.role)
    return ok({"token": token})


@auth_bp.route("/change-password", methods=["POST"])
@jwt_required
def change_password():
    """各自改密（AUTH-003）。"""
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("old_password", "new_password"))
    if bad:
        return bad
    if len(data["new_password"]) < 6:
        return e_input("新密码至少 6 位")
    if len(data["new_password"]) > 128:
        return e_input("新密码过长")
    con = get_db()
    row = con.execute("SELECT * FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not check_password_hash(row["password_hash"], data["old_password"]):
        return e_input("旧密码不正确")
    con.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(data["new_password"]), g.user_id),
    )
    con.commit()
    return ok({"updated": 1})
