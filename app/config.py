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

# .env.example 中的示例密钥：公开在仓库里，用它签名的令牌任何人都能伪造，因此拒绝使用。
# 修改 .env.example 中的示例值时须同步修改这里（tests/test_health.py 会检查两者一致）。
EXAMPLE_JWT_SECRETS = frozenset({"change-me-to-a-long-random-string"})
GENERATE_SECRET_HINT = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'


class Settings(BaseSettings):
    # hide_input_in_errors：配置有误时报错信息不回显输入值，避免把（真实的）密钥打进控制台和日志
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)

    # MongoDB
    mongo_uri: str
    mongo_db_name: str = "survey_dev"

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # bcrypt 计算强度（2 的幂次轮数）。默认 12；测试中调低以加快速度
    bcrypt_rounds: int = 12

    # 对外访问地址，用于生成问卷链接：<PUBLIC_BASE_URL>/survey/<shortCode>
    public_base_url: str

    @field_validator("jwt_secret")
    @classmethod
    def _secret_usable(cls, v: str) -> str:
        # 示例值长度够 32 个字符，但它是公开的，必须单独拒绝（部署时忘记修改也无法启动）
        if v.strip() in EXAMPLE_JWT_SECRETS:
            raise ValueError(f"JWT_SECRET 仍是 .env.example 中的示例值，请重新生成：{GENERATE_SECRET_HINT}")
        # HS256 建议密钥至少 32 字节，过短的密钥容易被暴力破解
        if len(v.encode("utf-8")) < 32:
            raise ValueError(f"JWT_SECRET 至少 32 个字符，请重新生成：{GENERATE_SECRET_HINT}")
        return v

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """全局唯一的配置对象（首次调用时读取，之后缓存）。"""
    return Settings()
