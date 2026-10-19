"""第一步：项目骨架与配置。"""
from app.config import Settings, get_settings


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
    s = Settings(mongo_uri="mongodb://db:27017", jwt_secret="x",
                 public_base_url="https://survey.example.com/")
    assert s.public_base_url == "https://survey.example.com"
