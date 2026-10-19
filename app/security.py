"""密码哈希、JWT 与“当前登录用户”依赖。"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.config import get_settings
from app.db import get_db
from app.errors import Unauthorized
from app.repositories import users as users_repo

# bcrypt 只处理密码的前 72 个字节，超出时 bcrypt 库会直接报错
BCRYPT_MAX_BYTES = 72


# ---------- 密码 ----------
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    data = password.encode("utf-8")
    if len(data) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(data, password_hash.encode("ascii"))


# 用户不存在时也做一次哈希比较，使“用户不存在”和“密码错误”的响应耗时接近，避免借此试探用户名
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def verify_password_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


# ---------- JWT ----------
def create_access_token(user_id: ObjectId, username: str,
                        expires_delta: timedelta | None = None) -> tuple[str, int]:
    """签发令牌，返回 (token, 有效期秒数)。"""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                          options={"require": ["sub", "exp"]})
    except jwt.ExpiredSignatureError:
        raise Unauthorized("TOKEN_EXPIRED", "登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise Unauthorized("INVALID_TOKEN", "登录状态无效，请重新登录")


# ---------- FastAPI 依赖 ----------
def get_database() -> Database:
    return get_db()


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Database = Depends(get_database),
) -> dict:
    """从请求头 Authorization: Bearer <token> 解析当前用户（数据库中的用户文档）。"""
    if credentials is None:
        raise Unauthorized()
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = ObjectId(payload["sub"])
    except (InvalidId, TypeError):
        raise Unauthorized("INVALID_TOKEN", "登录状态无效，请重新登录")
    user = users_repo.find_by_id(db, user_id)
    if user is None:
        raise Unauthorized("INVALID_TOKEN", "登录状态无效，请重新登录")
    return user
