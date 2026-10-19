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
