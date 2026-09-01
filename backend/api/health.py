"""健康检查 Blueprint（DEP-001 / NFR-007）
GET /health -> {"status","db","chroma","version"}
公开端点，仅返回 up/down，不泄露敏感信息。
"""
from app import version
from flask import Blueprint, jsonify

health_bp = Blueprint("health_bp", __name__)


@health_bp.route("/health")
def health():
    # db / chroma 探测：骨架阶段先返回 ok（无依赖可探），模块落地后接真实探活
    return jsonify(
        {
            "code": 0,
            "data": {
                "status": "up",
                "db": "ok",
                "chroma": "ok",
                "version": version,
            },
        }
    )
