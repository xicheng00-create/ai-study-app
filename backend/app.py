"""AI 学习小组 App — Flask 入口

单体 Flask + waitress（单进程/4 线程），端口 5001。
静态托管 frontend/ + /api/* Blueprint + /health。
"""
import os

from config import config_map
from flask import Flask, g, jsonify, request, send_from_directory
from middleware.errors import e_internal

# 版本号诚实规则：任何入 CHANGELOG 的改动必须同步 bump 此常量
version = "2.14.1"


def create_app(env=None):
    app = Flask(__name__, static_folder=None)
    cfg = config_map.get(env or os.environ.get("FLASK_ENV", "development"))
    app.config.from_object(cfg)

    # 数据层：连接 teardown + 建表 + 种子教师
    from data.db import init_app as db_init_app
    from data.db import init_db
    from data.seed import seed_teacher

    db_init_app(app)
    with app.app_context():
        init_db(app)
        seed_teacher()

    # 蓝图注册（REQ 追溯：AUTH/MAT/CHAT/QUIZ/PROG/RPT/ADMIN/CURR/VIDEO/DEP/CLASS）
    from api.attempts import attempts_bp, attempts_review_bp
    from api.auth import auth_bp
    from api.chapters import chapters_bp
    from api.checkin import checkin_bp
    from api.class_bp import class_bp
    from api.conversations import conversations_bp
    from api.curriculum import curriculum_bp
    from api.health import health_bp
    from api.knowledge import knowledge_bp
    from api.materials import materials_bp
    from api.notifications import notify_bp
    from api.practice import practice_bp
    from api.progress import progress_bp
    from api.quizzes import quizzes_bp
    from api.reports import reports_bp
    from api.teacher import teacher_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chapters_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(notify_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(curriculum_bp)
    app.register_blueprint(quizzes_bp)
    app.register_blueprint(attempts_bp)
    app.register_blueprint(attempts_review_bp)
    app.register_blueprint(practice_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(class_bp)

    # 统一兜底异常 → JSON（不泄露堆栈）
    @app.errorhandler(Exception)
    def handle_exception(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify({"code": f"E_HTTP_{exc.code}", "msg": exc.description}), exc.code
        return e_internal()

    # ---- REQ-OBS-014（v2.14.1）：/api/* 缓存口径 + 逐次访问日志 ----
    # 为什么存在：出现「学生说打卡了 / 服务端查不到」时，必须能回答两件事——
    #   ① 客户端有没有把请求发到服务端（此前无任何访问日志，只能靠内容表反推）；
    #   ② 客户端会不会把上一次的旧状态当成今天（此前 API 响应无 Cache-Control，
    #      浏览器/边缘缓存理论上可重放「已打卡」态）。
    # 成本纪律：每请求 1 行、按上海日期分文件、失败静默（绝不影响业务响应）。
    import time as _time
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    _sh_tz = _tz(_td(hours=8))
    _log_dir = os.path.join(os.path.dirname(__file__), "..", "instance", "logs")

    @app.before_request
    def _api_timer():
        if request.path.startswith("/api/"):
            g._api_t0 = _time.perf_counter()

    @app.after_request
    def _api_observability(resp):
        if not request.path.startswith("/api/"):
            return resp
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        try:
            t0 = getattr(g, "_api_t0", None)
            dur = f"{int((_time.perf_counter() - t0) * 1000)}ms" if t0 else "-"
            now = _dt.now(_tz.utc)
            # 真实客户端 IP：隧道部署下 remote_addr/XFF 恒为 127.0.0.1，真 IP 在 CF-Connecting-IP
            ip = (request.headers.get("CF-Connecting-IP")
                  or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                  or request.remote_addr or "-")
            line = "\t".join([
                now.astimezone(_sh_tz).strftime("%Y-%m-%d %H:%M:%S"),
                request.method,
                request.full_path.rstrip("?"),
                str(resp.status_code),
                dur,
                str(getattr(g, "user_id", "-") or "-"),
                ip,
                (request.headers.get("User-Agent") or "")[:48].replace("\t", " "),
            ])
            os.makedirs(_log_dir, exist_ok=True)
            log_dir = os.environ.get("API_LOG_DIR") or _log_dir
            os.makedirs(log_dir, exist_ok=True)
            fname = "api_access_" + now.astimezone(_sh_tz).strftime("%Y-%m-%d") + ".log"
            with open(os.path.join(log_dir, fname), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001, S110 - 观测失败必须静默，绝不影响业务响应
            pass
        return resp

    # 静态托管 frontend/（同源，避免 CORS）
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")

    @app.route("/")
    def index():
        return send_from_directory(frontend_dir, "index.html")

    @app.route("/<path:path>")
    def static_files(path):
        full = os.path.join(frontend_dir, path)
        if os.path.isfile(full):
            return send_from_directory(frontend_dir, path)
        # PWA 路由回退：非 API 路径且无对应静态文件 → index.html
        return send_from_directory(frontend_dir, "index.html")

    return app


if __name__ == "__main__":
    from waitress import serve
    app = create_app()
    port = int(os.environ.get("PORT", "5001"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"[boot] AI Study Group {version} serving on {host}:{port}")
    serve(app, host=host, port=port, threads=4)
