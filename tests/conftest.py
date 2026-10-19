"""pytest 公共配置。

测试一律使用独立的测试数据库（默认 survey_test）：
在导入 app 之前设置环境变量，环境变量优先于 .env，因此不会读写开发库。
"""
import os

os.environ.setdefault("MONGO_DB_NAME", "survey_test")

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

# 安全检查：防止误连开发库后被测试清空
assert get_settings().mongo_db_name.endswith("_test"), "测试必须使用以 _test 结尾的数据库"


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as c:
        yield c
