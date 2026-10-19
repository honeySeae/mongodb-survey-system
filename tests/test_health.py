"""第一步：项目骨架与配置。"""
from app.config import get_settings


def test_health(client):
    """服务能启动，健康检查接口返回 ok。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_settings_use_test_database():
    """测试环境使用独立的测试库，而不是 .env 中的开发库。"""
    settings = get_settings()
    assert settings.mongo_db_name == "survey_test"
    assert settings.mongo_uri.startswith("mongodb://")
