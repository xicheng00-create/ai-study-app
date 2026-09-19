"""配置：开发/生产（对齐 Design Spec DEP-003）
DEBUG 仅在 FLASK_ENV != production 时开启；生产走 waitress 无 Werkzeug debugger。
"""
import os

# 模块级常量：供业务模块 `from config import X` 直接引用（与 BaseConfig 同源，保持单一真相）。
# 每日打卡阈值（CHECKIN-002，服务端唯一判定；本期不做前端可配置 UI）
TASK_CARDS_REQUIRED = 30
TASK_QUESTIONS_REQUIRED = 5
# 单次「开始复习」卡组上限（KNOW-004）：每次学习最多 100 张（阈值单点，随响应下发）。
# 学习记录（knowledge_reviews）长期累计、绝不按天清空；本次没复习完的卡次日自动进入下一批。
SESSION_DECK_MAX = 100

# Web Push（VAPID）：私钥只存 .env，不进 git / 不进 API 响应 / 不写日志
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@aistudygroup.shuiyanhaha.org")

# 通知萌图/角标的公网前缀（站内通知卡片用相对路径 /img/notify/*，push 用完整 URL）
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://aistudygroup.shuiyanhaha.org")


class BaseConfig:
    SECRET_KEY = os.environ.get("APP_SECRET", "dev-secret-change-me-0123456789abcdef0123456789abcdef")
    JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY)
    ACCESS_TOKEN_TTL_HOURS = int(os.environ.get("ACCESS_TOKEN_TTL_HOURS", "12"))
    RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "60"))
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 上传上限（MAT-002 ≤30MB，留余量）
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.path.dirname(__file__), "..", "uploads"),
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "..", "instance", "aistudy.sqlite3")
    )

    # 打卡阈值 / VAPID / 公网前缀：引用模块级常量，保证 current_app.config 与 `from config import X` 同源
    TASK_CARDS_REQUIRED = TASK_CARDS_REQUIRED
    TASK_QUESTIONS_REQUIRED = TASK_QUESTIONS_REQUIRED
    SESSION_DECK_MAX = SESSION_DECK_MAX
    VAPID_PUBLIC_KEY = VAPID_PUBLIC_KEY
    VAPID_PRIVATE_KEY = VAPID_PRIVATE_KEY
    VAPID_SUBJECT = VAPID_SUBJECT
    PUBLIC_BASE_URL = PUBLIC_BASE_URL


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    # 生产强制无 Werkzeug debugger；生产默认关闭测试端点
    TESTING = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
