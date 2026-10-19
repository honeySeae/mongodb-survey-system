"""第三步：用户注册、登录、身份认证与统一错误格式。"""
from datetime import timedelta

import jwt
import pytest
from bson import ObjectId

from app.config import get_settings
from app.db import USERS
from app.security import create_access_token
from tests.conftest import DEFAULT_PASSWORD, login, register


def error_fields(resp) -> set[str]:
    return {e["field"] for e in resp.json().get("errors", [])}


# ---------- 注册 ----------
def test_register_success(client, db):
    resp = register(client, "alice")
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert ObjectId.is_valid(body["id"])
    assert "createdAt" in body
    assert "password" not in body and "passwordHash" not in body

    doc = db[USERS].find_one({"username": "alice"})
    assert doc is not None
    assert doc["createdAt"] is not None


def test_production_bcrypt_rounds_default_is_12():
    """正式运行的 bcrypt 强度默认为 12（测试中通过环境变量调低）。"""
    from app.config import Settings
    assert Settings.model_fields["bcrypt_rounds"].default == 12


def test_password_stored_as_bcrypt_hash(client, db):
    """数据库中只存 bcrypt 哈希，不存明文。"""
    register(client, "alice", "my-secret-pw")
    doc = db[USERS].find_one({"username": "alice"})
    assert doc["passwordHash"] != "my-secret-pw"
    assert doc["passwordHash"].startswith("$2b$")
    assert "my-secret-pw" not in str(doc)


def test_register_does_not_return_token(client):
    """注册成功后不自动登录。"""
    assert "accessToken" not in register(client, "alice").json()


@pytest.mark.parametrize("username", ["abc", "a" * 20, "User_01", "  carol  ", "___", "alice\n"])
def test_register_valid_usernames(client, username):
    assert register(client, username).status_code == 201


def test_username_stored_lowercase_and_trimmed(client):
    resp = register(client, "  Alice_01 ")
    assert resp.status_code == 201
    assert resp.json()["username"] == "alice_01"


@pytest.mark.parametrize(
    "username, expected_message",
    [
        ("ab", "用户名长度应为 3~20 个字符"),
        ("a" * 21, "用户名长度应为 3~20 个字符"),
        ("", "用户名长度应为 3~20 个字符"),
        ("   ", "用户名长度应为 3~20 个字符"),
        ("al ice", "用户名只能包含字母、数字和下划线"),
        ("alice!", "用户名只能包含字母、数字和下划线"),
        ("张三丰", "用户名只能包含字母、数字和下划线"),
        ("ａｌｉｃｅ", "用户名只能包含字母、数字和下划线"),  # 全角字母
    ],
)
def test_register_invalid_usernames(client, username, expected_message):
    resp = register(client, username)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {"field": "username", "message": expected_message} in body["errors"]


@pytest.mark.parametrize(
    "password, ok",
    [
        ("1234567", False),         # 7 个字符
        ("12345678", True),         # 8 个字符（下限）
        ("密码密码密码密码", True),   # 8 个汉字 = 24 字节
        ("密码密码密", False),        # 5 个汉字：字节数够 8，但字符数不够
        ("a" * 72, True),           # 72 字节（上限）
        ("a" * 73, False),          # 73 字节
        ("密" * 24, True),           # 24 个汉字 = 72 字节
        ("密" * 25, False),          # 25 个汉字 = 75 字节
        ("        ", True),         # 8 个空格：不去除空格，也不要求字符种类
    ],
)
def test_register_password_length(client, password, ok):
    resp = register(client, "alice", password)
    if ok:
        assert resp.status_code == 201
        assert login(client, "alice", password).status_code == 200
    else:
        assert resp.status_code == 422
        assert error_fields(resp) == {"password"}


def test_register_reports_all_field_errors_at_once(client):
    resp = register(client, "a!", "short")
    assert resp.status_code == 422
    assert error_fields(resp) == {"username", "password"}


def test_register_duplicate_username(client):
    assert register(client, "alice").status_code == 201
    resp = register(client, "alice", "another-password")
    assert resp.status_code == 409
    assert resp.json() == {"code": "USERNAME_TAKEN", "message": "用户名已被注册"}


def test_register_duplicate_username_case_insensitive(client):
    assert register(client, "alice").status_code == 201
    assert register(client, "ALICE").status_code == 409
    assert register(client, " Alice ").status_code == 409


# ---------- 登录 ----------
def test_login_success(client):
    register(client, "alice")
    resp = login(client, "alice")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == get_settings().jwt_expire_minutes * 60
    assert body["user"]["username"] == "alice"
    payload = jwt.decode(body["accessToken"], get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == body["user"]["id"]
    assert payload["username"] == "alice"


def test_login_username_case_insensitive(client):
    register(client, "alice")
    assert login(client, "ALICE").status_code == 200
    assert login(client, " Alice ").status_code == 200


def test_login_password_case_sensitive(client):
    register(client, "alice", "Password123")
    assert login(client, "alice", "password123").status_code == 401


def test_login_wrong_password_and_unknown_user_same_response(client):
    """密码错误和用户不存在返回完全相同的提示，不泄露用户名是否已注册。"""
    register(client, "alice")
    wrong_pw = login(client, "alice", "wrong-password")
    no_user = login(client, "nobody", DEFAULT_PASSWORD)
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json() == {
        "code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}


def test_login_overlong_password_is_invalid_credentials(client):
    """登录时超过 72 字节的密码不会让 bcrypt 报错，而是按密码错误处理。"""
    register(client, "alice")
    resp = login(client, "alice", "a" * 100)
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


# ---------- 当前用户与令牌 ----------
def test_me_with_valid_token(client, alice):
    resp = client.get("/api/auth/me", headers=alice)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_me_without_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json() == {"code": "NOT_AUTHENTICATED", "message": "请先登录"}
    assert resp.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("header", [
    "Bearer not-a-jwt",
    "Bearer ",
    "Basic YWxpY2U6cGFzcw==",
])
def test_me_with_malformed_token(client, header):
    resp = client.get("/api/auth/me", headers={"Authorization": header})
    assert resp.status_code == 401
    assert resp.json()["code"] in ("INVALID_TOKEN", "NOT_AUTHENTICATED")


def test_me_with_token_signed_by_other_secret(client, alice):
    """被篡改（用其他密钥签名）的令牌无效。"""
    me = client.get("/api/auth/me", headers=alice).json()
    forged = jwt.encode({"sub": me["id"], "username": "alice", "exp": 9999999999},
                        "attacker-secret-attacker-secret-attacker", algorithm="HS256")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


def test_me_with_expired_token(client, alice):
    me = client.get("/api/auth/me", headers=alice).json()
    token, _ = create_access_token(ObjectId(me["id"]), "alice", expires_delta=timedelta(minutes=-1))
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json() == {"code": "TOKEN_EXPIRED", "message": "登录已过期，请重新登录"}


def test_me_with_token_for_nonexistent_user(client):
    token, _ = create_access_token(ObjectId(), "ghost")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


def test_me_with_token_missing_subject(client):
    settings = get_settings()
    token = jwt.encode({"username": "alice", "exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


# ---------- 统一错误格式 ----------
def test_missing_fields_use_unified_error_format(client):
    resp = client.post("/api/auth/register", json={"username": "alice"})
    assert resp.status_code == 422
    assert resp.json() == {
        "code": "VALIDATION_ERROR", "message": "提交内容不合法",
        "errors": [{"field": "password", "message": "缺少必填字段"}],
    }


def test_wrong_field_type_uses_unified_error_format(client):
    resp = client.post("/api/auth/register", json={"username": 123, "password": "password123"})
    assert resp.status_code == 422
    assert resp.json()["errors"] == [{"field": "username", "message": "应为字符串"}]


def test_invalid_json_uses_unified_error_format(client):
    resp = client.post("/api/auth/register", content="{not json",
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert resp.json() == {
        "code": "VALIDATION_ERROR", "message": "提交内容不合法",
        # 出错位置是第 2 个字符 n；field 不是字符下标，避免被误解为字段名
        "errors": [{"field": "body", "message": "请求体不是合法的 JSON（第 2 个字符附近）"}],
    }


def test_invalid_json_position_on_later_line(client):
    body = '{"username": "alice",\n "password": }'
    resp = client.post("/api/auth/register", content=body,
                       headers={"Content-Type": "application/json"})
    pos = body.index("}") + 1  # 第 36 个字符：缺少值的位置
    assert resp.json()["errors"] == [
        {"field": "body", "message": f"请求体不是合法的 JSON（第 {pos} 个字符附近）"}]


def test_non_utf8_body_uses_unified_error_format(client):
    """非 UTF-8 编码的请求体（如 GBK 编码的中文）返回统一格式的中文提示。"""
    body = '{"username": "张三", "password": "password123"}'.encode("gbk")
    resp = client.post("/api/auth/register", content=body,
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json() == {"code": "BAD_REQUEST",
                           "message": "请求体无法解析，请使用 UTF-8 编码的 JSON"}


def test_unknown_route_uses_unified_error_format(client):
    resp = client.get("/api/no-such-route")
    assert resp.status_code == 404
    assert resp.json() == {"code": "NOT_FOUND", "message": "请求的资源不存在"}


def test_wrong_method_uses_unified_error_format(client):
    resp = client.get("/api/auth/login")
    assert resp.status_code == 405
    assert resp.json()["code"] == "METHOD_NOT_ALLOWED"
