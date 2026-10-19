"""responses 集合的读写（只负责数据库操作，不含业务规则）。

第四步只用到答卷计数；提交、统计在第七、八步补充。
"""
from bson import ObjectId
from pymongo.database import Database

from app.db import RESPONSES


def scope_filter(submission_policy: str) -> dict:
    """统计口径（设计文档 6.7）：latest 只算每人最新一份，once / all 算全部答卷。

    列表中的答卷数和统计接口共用这一处定义，保证口径一致。
    """
    return {"isLatest": True} if submission_policy == "latest" else {}


def count_by_surveys(db: Database, surveys: list[dict]) -> dict[ObjectId, int]:
    """按各问卷自己的统计口径，一次聚合算出每份问卷的答卷数。"""
    if not surveys:
        return {}
    conditions = [{"surveyId": s["_id"], **scope_filter(s["settings"]["submissionPolicy"])}
                  for s in surveys]
    pipeline = [
        {"$match": {"$or": conditions}},
        {"$group": {"_id": "$surveyId", "count": {"$sum": 1}}},
    ]
    return {row["_id"]: row["count"] for row in db[RESPONSES].aggregate(pipeline)}


# ---------- 提交（设计文档 6.2 的写入顺序由 services/fill.py 编排） ----------
def insert(db: Database, doc: dict) -> ObjectId:
    """插入答卷。isLatest 为 true 且该用户已有最新答卷时抛出 DuplicateKeyError（部分唯一索引）。"""
    return db[RESPONSES].insert_one(doc).inserted_id


def unset_other_latest(db: Database, survey_id: ObjectId, respondent_id: ObjectId,
                       except_id: ObjectId) -> None:
    """把该用户在该问卷上除 except_id 以外的最新答卷置为非最新（第 ② 步）。"""
    db[RESPONSES].update_many(
        {"surveyId": survey_id, "respondentId": respondent_id, "isLatest": True,
         "_id": {"$ne": except_id}},
        {"$set": {"isLatest": False}})


def mark_latest(db: Database, response_id: ObjectId) -> None:
    """把答卷置为最新（第 ③ 步）。并发提交时可能抛出 DuplicateKeyError。"""
    db[RESPONSES].update_one({"_id": response_id}, {"$set": {"isLatest": True}})


def delete(db: Database, response_id: ObjectId) -> None:
    """撤销一次失败的提交（第 ③ 步冲突时）。"""
    db[RESPONSES].delete_one({"_id": response_id})


def find_latest_of(db: Database, survey_id: ObjectId, respondent_id: ObjectId) -> dict | None:
    """该用户在该问卷上的最新答卷（查询带 isLatest: true，命中部分唯一索引）。"""
    return db[RESPONSES].find_one(
        {"surveyId": survey_id, "respondentId": respondent_id, "isLatest": True})


def submission_summary(db: Database, survey_id: ObjectId, respondent_id: ObjectId) -> dict:
    """该用户在该问卷上的提交次数和最近一次提交时间。"""
    rows = list(db[RESPONSES].aggregate([
        {"$match": {"surveyId": survey_id, "respondentId": respondent_id}},
        {"$group": {"_id": None, "count": {"$sum": 1}, "last": {"$max": "$submittedAt"}}},
    ]))
    if not rows:
        return {"count": 0, "last": None}
    return {"count": rows[0]["count"], "last": rows[0]["last"]}
