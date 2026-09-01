"""配置：开发/生产（对齐 Design Spec DEP-003）
DEBUG 仅在 FLASK_ENV != production 时开启；生产走 waitress 无 Werkzeug debugger。
"""
import os


class BaseConfig:
    SECRET_KEY = os.environ.get("APP_SECRET", "dev-secret-change-me")
    JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY)
    ACCESS_TOKEN_TTL_HOURS = int(os.environ.get("ACCESS_TOKEN_TTL_HOURS", "12"))
    RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "60"))
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "..", "instance", "aistudy.sqlite3")
    )


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
