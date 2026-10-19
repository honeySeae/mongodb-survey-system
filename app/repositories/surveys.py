"""surveys 集合的读写（只负责数据库操作，不含业务规则）。

查询一律带 ownerId 条件：别人的问卷与不存在的问卷对调用方来说没有区别。
"""
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.db import SURVEYS


def insert(db: Database, doc: dict) -> dict:
    """插入问卷并返回完整文档。shortCode 重复时抛出 DuplicateKeyError。"""
    doc["_id"] = db[SURVEYS].insert_one(doc).inserted_id
    return doc


def find_by_short_code(db: Database, short_code: str) -> dict | None:
    """填写者通过链接访问问卷（命中 shortCode_unique 索引）。不带 ownerId 条件，由调用方判断状态。"""
    return db[SURVEYS].find_one({"shortCode": short_code})


def find_owned(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict | None:
    return db[SURVEYS].find_one({"_id": survey_id, "ownerId": owner_id})


def list_by_owner(db: Database, owner_id: ObjectId) -> list[dict]:
    """我的问卷列表（新的在前，命中 ownerId_createdAt 索引）；不返回题目，只返回题目数。"""
    pipeline = [
        {"$match": {"ownerId": owner_id}},
        {"$sort": {"createdAt": -1}},
        {"$addFields": {"questionCount": {"$size": "$questions"}}},
        {"$project": {"questions": 0}},
    ]
    return list(db[SURVEYS].aggregate(pipeline))


def update_if_status(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                     status: str | list[str], set_fields: dict,
                     extra_filter: dict | None = None) -> dict | None:
    """仅当问卷当前状态符合要求时才更新（条件更新，防止并发操作互相覆盖）。

    返回更新后的文档；条件不满足（不存在、不是自己的、状态不对）时返回 None。
    """
    statuses = [status] if isinstance(status, str) else status
    query = {"_id": survey_id, "ownerId": owner_id, "status": {"$in": statuses}}
    if extra_filter:
        query.update(extra_filter)
    return db[SURVEYS].find_one_and_update(
        query, {"$set": set_fields}, return_document=ReturnDocument.AFTER)


def delete_if_status(db: Database, survey_id: ObjectId, owner_id: ObjectId, status: str) -> bool:
    result = db[SURVEYS].delete_one({"_id": survey_id, "ownerId": owner_id, "status": status})
    return result.deleted_count == 1
