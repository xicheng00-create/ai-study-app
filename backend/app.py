"""AI 学习小组 App — Flask 入口

单体 Flask + waitress（单进程/4 线程），端口 5001。
静态托管 frontend/ + /api/* Blueprint + /health。
"""
import os

from config import config_map
from flask import Flask, jsonify, send_from_directory
from middleware.errors import e_internal

# 版本号诚实规则：任何入 CHANGELOG 的改动必须同步 bump 此常量
version = "1.5.0"


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

    # 蓝图注册（REQ 追溯：AUTH/MAT/CHAT/QUIZ/PROG/RPT/ADMIN/CURR/VIDEO/DEP）
    from api.attempts import attempts_bp, attempts_review_bp
    from api.auth import auth_bp
    from api.chapters import chapters_bp
    from api.conversations import conversations_bp
    from api.curriculum import curriculum_bp
    from api.health import health_bp
    from api.materials import materials_bp
    from api.progress import progress_bp
    from api.quizzes import quizzes_bp
    from api.reports import reports_bp
    from api.teacher import teacher_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chapters_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(curriculum_bp)
    app.register_blueprint(quizzes_bp)
    app.register_blueprint(attempts_bp)
    app.register_blueprint(attempts_review_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(teacher_bp)

    # 统一兜底异常 → JSON（不泄露堆栈）
    @app.errorhandler(Exception)
    def handle_exception(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify({"code": f"E_HTTP_{exc.code}", "msg": exc.description}), exc.code
        return e_internal()

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
