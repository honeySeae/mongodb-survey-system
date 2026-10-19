"""配置：从环境变量和 .env 文件读取。

优先级：环境变量 > .env 文件 > 下面的默认值。
测试时通过环境变量把 MONGO_DB_NAME 改成独立的测试库，不影响开发数据。
与部署环境相关的项（连接串、密钥、对外地址）没有默认值，必须在 .env 或环境变量中提供，
避免在代码中写死本机地址。
"""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录下的 .env（与启动时所在目录无关）
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # MongoDB
    mongo_uri: str
    mongo_db_name: str = "survey_dev"

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # 对外访问地址，用于生成问卷链接：<PUBLIC_BASE_URL>/survey/<shortCode>
    public_base_url: str

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """全局唯一的配置对象（首次调用时读取，之后缓存）。"""
    return Settings()
