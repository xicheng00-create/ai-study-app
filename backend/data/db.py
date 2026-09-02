"""SQLite 连接与初始化（WAL + busy_timeout）。

单进程 waitress 多线程：每个请求从 Flask g 拿独立连接，
避免跨线程共享 sqlite3.Connection。
"""
import os
import sqlite3

from flask import current_app, g

from data import models


def _db_path() -> str:
    """优先读环境变量 DATABASE_PATH（测试用临时库），否则用 config 的 URI。"""
    path = current_app.config.get("DATABASE_PATH") or os.environ.get("DATABASE_PATH")
    if path:
        return path
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    # 仅支持 sqlite:/// 写法；相对路径转成基于 backend 根
    if uri.startswith("sqlite:///"):
        path = uri[len("sqlite:///"):]
        if not os.path.isabs(path):
            path = os.path.join(current_app.root_path, "..", path)
        return path
    # 兜底：instance 目录
    return os.path.join(current_app.root_path, "..", "instance", "aistudy.sqlite3")


def get_db() -> sqlite3.Connection:
    """每个请求一个连接，开启 WAL 与 busy_timeout。"""
    if "db" not in g:
        path = _db_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")
        g.db = con
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db(app=None):
    """建表 + 迁移；幂等，启动与测试均可调用。"""
    con = get_db()
    con.executescript(models.SCHEMA)
    models.migrate(con)
    con.commit()


def init_app(app):
    """注册 teardown 与 CLI 建表命令。"""
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def _init_db_cmd():
        with app.app_context():
            init_db(app)
        print("init_db done")
