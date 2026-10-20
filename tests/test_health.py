"""第一步：项目骨架与配置。"""
import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import EXAMPLE_JWT_SECRETS, Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_health(client):
    """服务能启动，健康检查接口返回 ok（数据库状态的检查见 test_db.py）。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_settings_use_test_database():
    """测试环境使用独立的测试库，而不是 .env 中的开发库。"""
    settings = get_settings()
    assert settings.mongo_db_name == "survey_test"
    assert settings.mongo_uri.startswith("mongodb")


def test_public_base_url_strips_trailing_slash():
    """问卷链接前缀来自配置，结尾的 / 会被去掉，避免拼出 //survey/xxx。"""
    s = Settings(mongo_uri="mongodb://db:27017", jwt_secret="x" * 32,
                 public_base_url="https://survey.example.com/")
    assert s.public_base_url == "https://survey.example.com"


def make_settings(secret: str) -> Settings:
    return Settings(mongo_uri="mongodb://db:27017", jwt_secret=secret, public_base_url="http://localhost:8000")


def test_short_jwt_secret_rejected():
    """JWT_SECRET 少于 32 个字符时拒绝启动，并提示生成方法。"""
    with pytest.raises(ValidationError) as exc:
        make_settings("too-short")
    assert "至少 32 个字符" in str(exc.value)
    assert "secrets.token_urlsafe" in str(exc.value)


def test_config_errors_do_not_echo_secret():
    """配置报错时不回显输入值：真实但过短的密钥不会出现在启动报错（控制台、日志）中。"""
    real_but_short = "my-real-server-key-20"
    with pytest.raises(ValidationError) as exc:
        make_settings(real_but_short)
    assert real_but_short not in str(exc.value)


def _example_secret() -> str:
    """读取 .env.example 中实际写的示例密钥。"""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("JWT_SECRET="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(".env.example 中没有 JWT_SECRET")


def test_example_jwt_secret_rejected():
    """.env.example 中的示例密钥虽然够 32 个字符，但是公开的，部署时忘记修改也必须拒绝启动。"""
    secret = _example_secret()
    assert len(secret) >= 32                     # 长度检查本身拦不住它，所以需要单独拒绝
    for value in (secret, f"  {secret}  "):
        with pytest.raises(ValidationError) as exc:
            make_settings(value)
        assert "仍是 .env.example 中的示例值" in str(exc.value)
        assert "secrets.token_urlsafe" in str(exc.value)


def test_example_secret_list_matches_env_example():
    """修改 .env.example 的示例值时，必须同步修改 app/config.py 中被拒绝的示例值列表。"""
    assert _example_secret() in EXAMPLE_JWT_SECRETS


def test_generated_secret_accepted():
    """按提示生成的随机密钥可以正常使用。"""
    assert make_settings(secrets.token_urlsafe(48)).jwt_secret
