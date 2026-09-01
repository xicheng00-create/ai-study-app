"""AI 学习小组 App — Flask 入口

单体 Flask + waitress（单进程/4 线程），端口 5001。
静态托管 frontend/ + /api/* Blueprint + /health。
"""
import os

from config import config_map
from flask import Flask, send_from_directory

# 版本号诚实规则：任何入 CHANGELOG 的改动必须同步 bump 此常量
version = "0.1.0"


def create_app(env=None):
    app = Flask(__name__, static_folder=None)
    cfg = config_map.get(env or os.environ.get("FLASK_ENV", "development"))
    app.config.from_object(cfg)

    # 注册蓝图（模块未落地前先占位，逐步由 Claude Code 填充）
    from api.health import health_bp
    app.register_blueprint(health_bp)

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


app = create_app()


if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "5001"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"[boot] AI Study Group {version} serving on {host}:{port}")
    serve(app, host=host, port=port, threads=4)
