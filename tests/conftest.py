"""pytest 公共配置。

测试一律使用独立的测试数据库（默认 survey_test）：
在导入 app 之前设置环境变量，环境变量优先于 .env，因此不会读写开发库。
整轮测试开始时删除并重建测试库；每个测试结束后清空各集合（保留校验规则和索引）。
"""
import os

os.environ.setdefault("MONGO_DB_NAME", "survey_test")
# 测试中降低 bcrypt 强度以加快速度（4 是 bcrypt 允许的最小值）；正式运行仍为默认的 12
os.environ.setdefault("BCRYPT_ROUNDS", "4")

import pytest
from fastapi.testclient import TestClient

from app import db as app_db
from app.config import get_settings
from app.db_schema import SCHEMAS, ensure_schema
from app.main import create_app

# 安全检查：防止误连开发库后被测试清空
assert get_settings().mongo_db_name.endswith("_test"), "测试必须使用以 _test 结尾的数据库"


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """整轮测试前重建测试库，结束后删除。"""
    assert app_db.ping(), "连接不上 MongoDB，请先启动（Windows：scripts/start_mongo.bat）"
    client = app_db.get_client()
    name = get_settings().mongo_db_name
    client.drop_database(name)
    ensure_schema(client[name])
    yield
    # 应用关闭时会释放客户端，这里重新获取
    app_db.get_client().drop_database(name)
    app_db.close_client()


@pytest.fixture
def db():
    """测试数据库；测试结束后清空所有集合。"""
    yield app_db.get_db()
    database = app_db.get_db()  # 测试中应用可能已关闭并重建客户端，重新获取
    for name in SCHEMAS:
        database[name].delete_many({})


@pytest.fixture
def client(db) -> TestClient:
    with TestClient(create_app()) as c:
        yield c


# ---------- 账号相关的公共工具（后续步骤的测试也会用到） ----------
DEFAULT_PASSWORD = "password123"


def register(client, username: str, password: str = DEFAULT_PASSWORD):
    return client.post("/api/auth/register", json={"username": username, "password": password})


def login(client, username: str, password: str = DEFAULT_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def auth_headers_for(client, username: str, password: str = DEFAULT_PASSWORD) -> dict:
    """注册并登录一个用户，返回带令牌的请求头。"""
    assert register(client, username, password).status_code == 201
    token = login(client, username, password).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice(client) -> dict:
    """已登录用户 alice 的请求头。"""
    return auth_headers_for(client, "alice")


@pytest.fixture
def bob(client) -> dict:
    """已登录用户 bob 的请求头。"""
    return auth_headers_for(client, "bob")
