"""users 集合的读写（只负责数据库操作，不含业务规则）。"""
from bson import ObjectId
from pymongo.database import Database

from app.db import USERS
from app.utils import now_utc


def create(db: Database, username: str, password_hash: str) -> dict:
    """插入新用户并返回完整文档。用户名重复时抛出 pymongo.errors.DuplicateKeyError。"""
    doc = {"username": username, "passwordHash": password_hash, "createdAt": now_utc()}
    doc["_id"] = db[USERS].insert_one(doc).inserted_id
    return doc


def find_by_username(db: Database, username: str) -> dict | None:
    return db[USERS].find_one({"username": username})


def find_by_id(db: Database, user_id: ObjectId) -> dict | None:
    return db[USERS].find_one({"_id": user_id})


def find_usernames(db: Database, user_ids: list[ObjectId]) -> dict[ObjectId, str]:
    """批量查询用户名（之后答卷列表、统计中显示填写人时使用）。"""
    cursor = db[USERS].find({"_id": {"$in": list(user_ids)}}, {"username": 1})
    return {u["_id"]: u["username"] for u in cursor}
