"""健康检查 Blueprint（DEP-001 / NFR-007）。

GET /health -> {"status","db","version"}；公开端点，不泄露敏感信息。
RAG 已降维为 SQLite chunks（不再依赖 ChromaDB）。
"""
from app import version
from data.db import get_db
from flask import Blueprint, jsonify

health_bp = Blueprint("health_bp", __name__)


@health_bp.route("/health")
def health():
    db_status = "ok"
    try:
        con = get_db()
        con.execute("SELECT 1").fetchone()
    # 探活需兜底任意库异常，避免 /health 自身抛错
    except Exception:  # noqa: BLE001
        db_status = "down"
    return jsonify(
        {
            "code": 0,
            "data": {
                "status": "up" if db_status == "ok" else "degraded",
                "db": db_status,
                "rag": "keyword",
                "version": version,
            },
        }
    )
