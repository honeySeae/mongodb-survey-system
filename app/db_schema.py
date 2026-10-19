"""集合的 $jsonSchema 校验和索引定义（对应 docs/DATABASE_DESIGN.md 第 2~5 节）。

ensure_schema() 是幂等的：集合不存在则创建，已存在则用 collMod 更新校验规则；
索引已存在则跳过。应用启动和 scripts/init_db.py 都会调用它。

校验策略（设计文档 5.1）：
- 只约束核心字段的必填、类型和枚举取值，更细的业务校验在应用层完成；
- 不设置 additionalProperties: false，第二阶段新增字段不会被数据库拒绝；
- validationLevel 为 moderate：已存在的不合规旧文档仍可更新，不会因规则变化而“卡死”。
"""
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database

from app.db import RESPONSES, SURVEYS, USERS

# ---------- 取值枚举（与设计文档一致，供应用层复用） ----------
SURVEY_STATUSES = ["draft", "published", "closed"]
SUBMISSION_POLICIES = ["once", "latest", "all"]
QUESTION_TYPES = ["single_choice", "multiple_choice", "text", "number"]

# MongoDB 中整数可能是 int（32 位）或 long（64 位），统一接受
_INT = ["int", "long"]

# ---------- $jsonSchema ----------
USERS_SCHEMA = {
    "bsonType": "object",
    "required": ["username", "passwordHash", "createdAt"],
    "properties": {
        "username": {"bsonType": "string", "minLength": 1},
        "passwordHash": {"bsonType": "string", "minLength": 1},
        "createdAt": {"bsonType": "date"},
    },
}

_OPTION_SCHEMA = {
    "bsonType": "object",
    "required": ["id", "text"],
    "properties": {
        "id": {"bsonType": "string"},
        "text": {"bsonType": "string"},
    },
}

_QUESTION_SCHEMA = {
    "bsonType": "object",
    "required": ["id", "type", "title", "validation"],
    "properties": {
        "id": {"bsonType": "string"},
        "type": {"enum": QUESTION_TYPES},
        "title": {"bsonType": "string"},
        "options": {"bsonType": "array", "items": _OPTION_SCHEMA},
        "validation": {"bsonType": "object"},
        "logic": {"bsonType": "object"},
    },
}

SURVEYS_SCHEMA = {
    "bsonType": "object",
    "required": [
        "ownerId", "shortCode", "title", "status", "settings",
        "version", "questions", "createdAt", "updatedAt",
    ],
    "properties": {
        "ownerId": {"bsonType": "objectId"},
        "shortCode": {"bsonType": "string", "minLength": 1},
        "title": {"bsonType": "string", "minLength": 1},
        "description": {"bsonType": "string"},
        "status": {"enum": SURVEY_STATUSES},
        "settings": {
            "bsonType": "object",
            "required": ["allowAnonymous", "submissionPolicy"],
            "properties": {
                "allowAnonymous": {"bsonType": "bool"},
                "submissionPolicy": {"enum": SUBMISSION_POLICIES},
                "deadline": {"bsonType": ["date", "null"]},
            },
        },
        "version": {"bsonType": _INT, "minimum": 1},
        "questions": {"bsonType": "array", "items": _QUESTION_SCHEMA},
        "createdAt": {"bsonType": "date"},
        "updatedAt": {"bsonType": "date"},
        "publishedAt": {"bsonType": ["date", "null"]},
        "closedAt": {"bsonType": ["date", "null"]},
    },
}

RESPONSES_SCHEMA = {
    "bsonType": "object",
    "required": [
        "surveyId", "surveyVersion", "respondentId", "isLatest", "submittedAt", "answers",
    ],
    "properties": {
        "surveyId": {"bsonType": "objectId"},
        "surveyVersion": {"bsonType": _INT, "minimum": 1},
        "respondentId": {"bsonType": "objectId"},
        "isLatest": {"bsonType": "bool"},
        "submittedAt": {"bsonType": "date"},
        "answers": {
            "bsonType": "array",
            "items": {
                # value 的类型随题型变化（字符串 / 数组 / 数值），由应用层校验
                "bsonType": "object",
                "required": ["questionId", "value"],
                "properties": {"questionId": {"bsonType": "string"}},
            },
        },
    },
}

SCHEMAS = {
    USERS: USERS_SCHEMA,
    SURVEYS: SURVEYS_SCHEMA,
    RESPONSES: RESPONSES_SCHEMA,
}

# ---------- 索引（设计文档第 5 节），统一显式命名 ----------
INDEXES = {
    USERS: [
        IndexModel([("username", ASCENDING)], name="username_unique", unique=True),
    ],
    SURVEYS: [
        IndexModel([("shortCode", ASCENDING)], name="shortCode_unique", unique=True),
        IndexModel([("ownerId", ASCENDING), ("createdAt", DESCENDING)], name="ownerId_createdAt"),
    ],
    RESPONSES: [
        IndexModel([("surveyId", ASCENDING), ("submittedAt", DESCENDING)], name="surveyId_submittedAt"),
        # 每人每份问卷最多一份“最新”答卷；也用于判断是否填写过（查询带 isLatest: true）
        IndexModel(
            [("surveyId", ASCENDING), ("respondentId", ASCENDING)],
            name="surveyId_respondentId_latest_unique",
            unique=True,
            partialFilterExpression={"isLatest": True},
        ),
        IndexModel([("answers.questionId", ASCENDING)], name="answers_questionId"),
    ],
}


def ensure_schema(db: Database) -> None:
    """创建/更新所有集合的校验规则和索引（幂等）。"""
    existing = set(db.list_collection_names())
    for name, schema in SCHEMAS.items():
        validator = {"$jsonSchema": schema}
        if name in existing:
            db.command("collMod", name, validator=validator,
                       validationLevel="moderate", validationAction="error")
        else:
            db.create_collection(name, validator=validator,
                                 validationLevel="moderate", validationAction="error")
    for name, indexes in INDEXES.items():
        db[name].create_indexes(indexes)
