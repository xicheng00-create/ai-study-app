"""学习路径与视频课 Blueprint（REQ-CURR / REQ-VIDEO）。

发布状态机：session 是发布源，其下章节/资料/视频可见性随 session 同步。
视频/路径为共享资源，读操作仅 @jwt_required（不经 @user_scope）。
"""
import json

from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from middleware.input_validation import check_len, require_fields

curriculum_bp = Blueprint("curriculum_bp", __name__, url_prefix="/api/curriculum")


def _parse_list(value):
    """校验入参是字符串列表（chapter_ids / concept_tags），返回 JSON 字符串或 None。"""
    if value is None:
        return "[]"
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        return None
    if len(json.dumps(value, ensure_ascii=False)) > 2000:
        return None
    return json.dumps([x.strip() for x in value if x.strip()], ensure_ascii=False)


def _json_list(raw):
    try:
        val = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def _int_field(data, key, default=0):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _session_row(row):
    return {
        "id": row["id"],
        "week_no": row["week_no"],
        "session_no": row["session_no"],
        "title": row["title"],
        "goal": row["goal"],
        "chapter_ids": _json_list(row["chapter_ids"]),
        "concept_tags": _json_list(row["concept_tags"]),
        "milestone": row["milestone"] or "",
        "order_no": row["order_no"],
        "status": row["status"],
    }


def _video_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "platform": row["platform"],
        "description": row["description"],
        "week_no": row["week_no"],
        "session_no": row["session_no"],
        "concept_tags": _json_list(row["concept_tags"]),
        "order_no": row["order_no"],
        "status": row["status"],
    }


def _find_session(con, week_no, session_no):
    return con.execute(
        "SELECT * FROM sessions WHERE week_no=? AND session_no=?",
        (week_no, session_no),
    ).fetchone()


def _sync_content_status(con, session, new_status):
    """session 发布/取消发布时，其下章节/资料/视频 status 随动。"""
    chapter_ids = _json_list(session["chapter_ids"])
    if chapter_ids:
        ph = ",".join("?" * len(chapter_ids))
        con.execute(
            f"UPDATE chapters SET status=? WHERE id IN ({ph})", (new_status, *chapter_ids)
        )
        con.execute(
            f"UPDATE materials SET status=? WHERE chapter_id IN ({ph}) AND is_deleted=0",
            (new_status, *chapter_ids),
        )
    con.execute(
        "UPDATE video_resources SET status=? WHERE week_no=? AND (session_no=? OR session_no IS NULL)",
        (new_status, session["week_no"], session["session_no"]),
    )


def _session_detail(con, row):
    """session 概览：关联章节 + 资料 + 视频列表。"""
    detail = _session_row(row)
    chapter_ids = detail["chapter_ids"]
    chapters, materials, videos = [], [], []
    if chapter_ids:
        ph = ",".join("?" * len(chapter_ids))
        ch_rows = con.execute(
            f"SELECT id, folder, name, order_no FROM chapters WHERE id IN ({ph}) ORDER BY order_no, name",
            (*chapter_ids,),
        ).fetchall()
        chapters = [{"id": r["id"], "name": r["name"], "folder": r["folder"]} for r in ch_rows]
        mat_rows = con.execute(
            f"SELECT id, filename, original_name, file_type FROM materials"
            f" WHERE chapter_id IN ({ph}) AND is_deleted=0 ORDER BY created_at",
            (*chapter_ids,),
        ).fetchall()
        materials = [dict(r) for r in mat_rows]
    v_rows = con.execute(
        "SELECT * FROM video_resources WHERE week_no=? AND (session_no=? OR session_no IS NULL)"
        " ORDER BY order_no, created_at",
        (row["week_no"], row["session_no"]),
    ).fetchall()
    videos = [_video_row(r) for r in v_rows]
    detail["chapters"] = chapters
    detail["materials"] = materials
    detail["videos"] = videos
    return detail


@curriculum_bp.route("", methods=["GET"])
@jwt_required
def overview():
    """学习路径总览：weeks→sessions。

    学生仅返回 status='published'；教师返回全部（含 draft，供课程管理）。
    """
    con = get_db()
    if g.role == "teacher":
        rows = con.execute(
            "SELECT * FROM sessions ORDER BY week_no, session_no, order_no"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM sessions WHERE status='published' ORDER BY week_no, session_no, order_no"
        ).fetchall()
    weeks = {}
    for r in rows:
        detail = _session_detail(con, r)
        weeks.setdefault(r["week_no"], []).append(detail)
    return ok({"weeks": [{"week_no": w, "sessions": weeks[w]} for w in sorted(weeks)]})


@curriculum_bp.route("/sessions", methods=["POST"])
@jwt_required
@role_required("teacher")
def create_session():
    """建 Session（CURR-001），默认 draft。"""
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("title",))
    if bad:
        return bad
    week_no = _int_field(data, "week_no")
    session_no = _int_field(data, "session_no")
    title = data["title"].strip()
    goal = (data.get("goal") or "").strip()
    milestone = (data.get("milestone") or "").strip()
    chapter_ids = _parse_list(data.get("chapter_ids"))
    concept_tags = _parse_list(data.get("concept_tags"))
    if chapter_ids is None or concept_tags is None:
        return e_input("chapter_ids / concept_tags 需为字符串数组")
    for field, val in (("title", title), ("goal", goal), ("milestone", milestone)):
        err = check_len(field, val)
        if err:
            return err
    order_no = _int_field(data, "order_no")
    uid = models.new_id()
    con = get_db()
    con.execute(
        "INSERT INTO sessions (id, week_no, session_no, title, goal, chapter_ids,"
        " concept_tags, milestone, order_no, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
        (uid, week_no, session_no, title, goal, chapter_ids, concept_tags,
         milestone, order_no, g.user_id, models.utcnow()),
    )
    con.commit()
    return ok({"id": uid, "status": "draft"})


@curriculum_bp.route("/sessions/<session_id>", methods=["PUT"])
@jwt_required
@role_required("teacher")
def update_session(session_id):
    """改 Session（CURR-001）。"""
    con = get_db()
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return e_not_found("Session 不存在")
    data = request.get_json(silent=True) or {}
    week_no = _int_field(data, "week_no", row["week_no"])
    session_no = _int_field(data, "session_no", row["session_no"])
    title = (data.get("title") or row["title"]).strip()
    goal = (data.get("goal") if data.get("goal") is not None else row["goal"]).strip()
    milestone = (data.get("milestone") if data.get("milestone") is not None else row["milestone"] or "").strip()
    chapter_ids = _parse_list(data.get("chapter_ids"))
    concept_tags = _parse_list(data.get("concept_tags"))
    if chapter_ids is None or concept_tags is None:
        return e_input("chapter_ids / concept_tags 需为字符串数组")
    order_no = _int_field(data, "order_no", row["order_no"])
    for field, val in (("title", title), ("goal", goal), ("milestone", milestone)):
        err = check_len(field, val)
        if err:
            return err
    con.execute(
        "UPDATE sessions SET week_no=?, session_no=?, title=?, goal=?, chapter_ids=?,"
        " concept_tags=?, milestone=?, order_no=? WHERE id=?",
        (week_no, session_no, title, goal, chapter_ids, concept_tags, milestone, order_no, session_id),
    )
    con.commit()
    return ok({"id": session_id})


@curriculum_bp.route("/sessions/<session_id>", methods=["DELETE"])
@jwt_required
@role_required("teacher")
def delete_session(session_id):
    """删 Session（CURR-001）：级联删其视频；章节/资料保留（避免误删全班数据）。"""
    con = get_db()
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return e_not_found("Session 不存在")
    con.execute(
        "DELETE FROM video_resources WHERE week_no=? AND (session_no=? OR session_no IS NULL)",
        (row["week_no"], row["session_no"]),
    )
    con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    con.commit()
    return ok({"deleted": 1, "note": "章节/资料已保留，可另行处理"})


@curriculum_bp.route("/sessions/<session_id>/publish", methods=["POST"])
@jwt_required
@role_required("teacher")
def publish_session(session_id):
    """发布（CURR-003）：session 与其下内容 status → published，学生立即可见。"""
    con = get_db()
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return e_not_found("Session 不存在")
    con.execute("UPDATE sessions SET status='published' WHERE id=?", (session_id,))
    _sync_content_status(con, row, "published")
    con.commit()
    return ok({"id": session_id, "status": "published"})


@curriculum_bp.route("/sessions/<session_id>/unpublish", methods=["POST"])
@jwt_required
@role_required("teacher")
def unpublish_session(session_id):
    """取消发布（CURR-003）：回 draft，内容随动隐藏。"""
    con = get_db()
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return e_not_found("Session 不存在")
    con.execute("UPDATE sessions SET status='draft' WHERE id=?", (session_id,))
    _sync_content_status(con, row, "draft")
    con.commit()
    return ok({"id": session_id, "status": "draft"})


@curriculum_bp.route("/videos", methods=["GET"])
@jwt_required
def list_videos():
    """视频列表（VIDEO-002）：学生只见 published，教师全部。"""
    con = get_db()
    if g.role == "teacher":
        rows = con.execute("SELECT * FROM video_resources ORDER BY week_no, session_no, order_no").fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM video_resources WHERE status='published' ORDER BY week_no, session_no, order_no"
        ).fetchall()
    return ok({"videos": [_video_row(r) for r in rows]})


@curriculum_bp.route("/videos", methods=["POST"])
@jwt_required
@role_required("teacher")
def create_video():
    """建视频（VIDEO-001）：status 随所属 session（无 session 或 session 为 draft 则 draft）。"""
    data = request.get_json(silent=True) or {}
    bad = require_fields(data, ("title", "url"))
    if bad:
        return bad
    title = data["title"].strip()
    url = data["url"].strip()
    platform = (data.get("platform") or "").strip()
    description = (data.get("description") or "").strip()
    concept_tags = _parse_list(data.get("concept_tags"))
    if concept_tags is None:
        return e_input("concept_tags 需为字符串数组")
    for field, val in (("title", title), ("url", url), ("platform", platform),
                       ("description", description)):
        err = check_len(field, val)
        if err:
            return err
    week_no = data.get("week_no")
    session_no = data.get("session_no")
    week_no = int(week_no) if week_no not in (None, "") else None
    session_no = int(session_no) if session_no not in (None, "") else None
    order_no = _int_field(data, "order_no")

    con = get_db()
    status = "draft"
    if week_no is not None and session_no is not None:
        s = _find_session(con, week_no, session_no)
        if s is not None:
            status = s["status"]
    uid = models.new_id()
    con.execute(
        "INSERT INTO video_resources (id, title, url, platform, description, week_no,"
        " session_no, concept_tags, order_no, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uid, title, url, platform, description, week_no, session_no, concept_tags,
         order_no, status, g.user_id, models.utcnow()),
    )
    con.commit()
    return ok({"id": uid, "status": status})


@curriculum_bp.route("/videos/<video_id>", methods=["PUT"])
@jwt_required
@role_required("teacher")
def update_video(video_id):
    """改视频（VIDEO-001）。"""
    con = get_db()
    row = con.execute("SELECT * FROM video_resources WHERE id=?", (video_id,)).fetchone()
    if row is None:
        return e_not_found("视频不存在")
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or row["title"]).strip()
    url = (data.get("url") or row["url"]).strip()
    platform = (data.get("platform") if data.get("platform") is not None else row["platform"]).strip()
    description = (data.get("description") if data.get("description") is not None else row["description"]).strip()
    concept_tags = _parse_list(data.get("concept_tags"))
    if concept_tags is None:
        return e_input("concept_tags 需为字符串数组")
    for field, val in (("title", title), ("url", url), ("platform", platform),
                       ("description", description)):
        err = check_len(field, val)
        if err:
            return err
    week_no = data.get("week_no", row["week_no"])
    session_no = data.get("session_no", row["session_no"])
    week_no = int(week_no) if week_no not in (None, "") else None
    session_no = int(session_no) if session_no not in (None, "") else None
    order_no = _int_field(data, "order_no", row["order_no"])
    con.execute(
        "UPDATE video_resources SET title=?, url=?, platform=?, description=?, week_no=?,"
        " session_no=?, concept_tags=?, order_no=? WHERE id=?",
        (title, url, platform, description, week_no, session_no, concept_tags, order_no, video_id),
    )
    con.commit()
    return ok({"id": video_id})


@curriculum_bp.route("/videos/<video_id>", methods=["DELETE"])
@jwt_required
@role_required("teacher")
def delete_video(video_id):
    """删视频（VIDEO-001）。"""
    con = get_db()
    row = con.execute("SELECT * FROM video_resources WHERE id=?", (video_id,)).fetchone()
    if row is None:
        return e_not_found("视频不存在")
    con.execute("DELETE FROM video_resources WHERE id=?", (video_id,))
    con.commit()
    return ok({"deleted": 1})
