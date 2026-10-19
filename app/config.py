"""配置：从环境变量和 .env 文件读取。

优先级：环境变量 > .env 文件 > 下面的默认值。
测试时通过环境变量把 MONGO_DB_NAME 改成独立的测试库，不影响开发数据。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "survey_dev"

    # JWT
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24


@lru_cache
def get_settings() -> Settings:
    """全局唯一的配置对象（首次调用时读取，之后缓存）。"""
    return Settings()
