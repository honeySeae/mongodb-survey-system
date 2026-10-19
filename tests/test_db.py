"""第二步：数据库连接、$jsonSchema 校验与索引。

验证 docs/DATABASE_DESIGN.md 第 5 节的索引和 5.1 节的校验策略在数据库中真实生效。
"""
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from app.db import RESPONSES, SURVEYS, USERS
from app.db_schema import ensure_schema


def now():
    return datetime.now(timezone.utc)


# ---------- 构造合法文档 ----------
def make_user(**overrides):
    doc = {"username": "alice", "passwordHash": "$2b$12$hash", "createdAt": now()}
    doc.update(overrides)
    return doc


def make_survey(**overrides):
    doc = {
        "ownerId": ObjectId(),
        "shortCode": "a8Kx2p",
        "title": "水果偏好调查",
        "status": "draft",
        "settings": {"allowAnonymous": False, "submissionPolicy": "once", "deadline": None},
        "version": 1,
        "questions": [
            {
                "id": "q_abc123", "type": "single_choice", "title": "你喜欢吃水果吗？",
                "options": [{"id": "o_aaa111", "text": "喜欢"}, {"id": "o_bbb222", "text": "不喜欢"}],
                "validation": {"required": True},
            }
        ],
        "createdAt": now(),
        "updatedAt": now(),
    }
    doc.update(overrides)
    return doc


def make_response(**overrides):
    doc = {
        "surveyId": ObjectId(),
        "surveyVersion": 1,
        "respondentId": ObjectId(),
        "isLatest": True,
        "submittedAt": now(),
        "answers": [{"questionId": "q_abc123", "value": "o_aaa111"}],
    }
    doc.update(overrides)
    return doc


# ---------- 连接与健康检查 ----------
def test_health_reports_database_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


# ---------- 集合与校验规则 ----------
def test_collections_created_with_validator(db):
    infos = {c["name"]: c for c in db.list_collections()}
    for name in (USERS, SURVEYS, RESPONSES):
        assert name in infos
        options = infos[name]["options"]
        assert "$jsonSchema" in options["validator"]
        assert options["validationLevel"] == "moderate"
        assert options["validationAction"] == "error"


def test_ensure_schema_is_idempotent(db):
    """重复执行初始化不报错，索引不重复。"""
    before = {n: sorted(db[n].index_information()) for n in (USERS, SURVEYS, RESPONSES)}
    ensure_schema(db)
    ensure_schema(db)
    after = {n: sorted(db[n].index_information()) for n in (USERS, SURVEYS, RESPONSES)}
    assert before == after


def test_valid_documents_accepted(db):
    db[USERS].insert_one(make_user())
    db[SURVEYS].insert_one(make_survey())
    db[RESPONSES].insert_one(make_response())


@pytest.mark.parametrize(
    "collection, doc",
    [
        (USERS, {"username": "bob", "createdAt": now()}),                          # 缺 passwordHash
        (USERS, make_user(createdAt="2026-10-19")),                                  # 时间存成字符串
        (SURVEYS, make_survey(status="open")),                                       # 非法状态
        (SURVEYS, make_survey(ownerId="not-an-objectid")),                           # ownerId 类型错误
        (SURVEYS, make_survey(settings={"allowAnonymous": True, "submissionPolicy": "daily"})),  # 非法提交策略
        (SURVEYS, make_survey(settings={"submissionPolicy": "once"})),               # 缺 allowAnonymous
        (SURVEYS, make_survey(questions=[{"id": "q_x", "type": "rating", "title": "t", "validation": {}}])),  # 非法题型
        (SURVEYS, make_survey(version=0)),                                           # 版本号从 1 开始
        (RESPONSES, make_response(isLatest="yes")),                                  # isLatest 类型错误
        (RESPONSES, make_response(answers=[{"value": "o_aaa111"}])),                 # 答案缺 questionId
    ],
)
def test_invalid_documents_rejected(db, collection, doc):
    with pytest.raises(WriteError) as exc:
        db[collection].insert_one(doc)
    assert exc.value.code == 121  # DocumentValidationFailure


def test_extra_fields_allowed_for_future_extension(db):
    """第二阶段新增字段不会被数据库校验拒绝（不设 additionalProperties: false）。"""
    survey = make_survey(settings={
        "allowAnonymous": False, "submissionPolicy": "once", "deadline": None, "maxResponses": 100,
    })
    survey["questions"][0]["options"][0]["media"] = {"url": "https://example.com/a.png"}
    db[SURVEYS].insert_one(survey)
    db[RESPONSES].insert_one(make_response(answers=[
        {"questionId": "q_abc123", "value": "o_aaa111", "durationMs": 1200},
    ]))


# ---------- 索引 ----------
def test_indexes_match_design(db):
    """索引的字段、唯一性、部分过滤条件与设计文档第 5 节一致。"""
    users = db[USERS].index_information()
    assert users["username_unique"]["key"] == [("username", 1)]
    assert users["username_unique"]["unique"] is True

    surveys = db[SURVEYS].index_information()
    assert surveys["shortCode_unique"]["key"] == [("shortCode", 1)]
    assert surveys["shortCode_unique"]["unique"] is True
    assert surveys["ownerId_createdAt"]["key"] == [("ownerId", 1), ("createdAt", -1)]

    responses = db[RESPONSES].index_information()
    assert responses["surveyId_submittedAt"]["key"] == [("surveyId", 1), ("submittedAt", -1)]
    latest = responses["surveyId_respondentId_latest_unique"]
    assert latest["key"] == [("surveyId", 1), ("respondentId", 1)]
    assert latest["unique"] is True
    assert latest["partialFilterExpression"] == {"isLatest": True}
    assert responses["answers_questionId"]["key"] == [("answers.questionId", 1)]

    # 已删除的普通索引 {surveyId, respondentId} 不应存在
    plain = [n for n, i in responses.items()
             if i["key"] == [("surveyId", 1), ("respondentId", 1)] and not i.get("unique")]
    assert plain == []


def test_username_unique(db):
    db[USERS].insert_one(make_user(username="alice"))
    with pytest.raises(DuplicateKeyError):
        db[USERS].insert_one(make_user(username="alice"))


def test_short_code_unique(db):
    db[SURVEYS].insert_one(make_survey(shortCode="abc123"))
    with pytest.raises(DuplicateKeyError):
        db[SURVEYS].insert_one(make_survey(shortCode="abc123"))


def test_only_one_latest_response_per_user(db):
    """部分唯一索引：同一人同一问卷最多一份 isLatest: true（设计文档 6.2 依赖此索引）。"""
    survey_id, user_id = ObjectId(), ObjectId()
    db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id, isLatest=True))
    with pytest.raises(DuplicateKeyError):
        db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id, isLatest=True))


def test_multiple_non_latest_responses_allowed(db):
    """isLatest: false 的历史答卷不受唯一约束，可以有多份。"""
    survey_id, user_id = ObjectId(), ObjectId()
    db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id, isLatest=True))
    db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id, isLatest=False))
    db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id, isLatest=False))
    assert db[RESPONSES].count_documents({"surveyId": survey_id, "respondentId": user_id}) == 3


def test_latest_unique_is_per_user_and_per_survey(db):
    """不同的人、不同的问卷各自可以有自己的最新答卷。"""
    survey_a, survey_b, user_1, user_2 = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    db[RESPONSES].insert_one(make_response(surveyId=survey_a, respondentId=user_1))
    db[RESPONSES].insert_one(make_response(surveyId=survey_a, respondentId=user_2))
    db[RESPONSES].insert_one(make_response(surveyId=survey_b, respondentId=user_1))
    assert db[RESPONSES].count_documents({"isLatest": True}) == 3


def test_three_step_latest_switch(db):
    """设计文档 6.2 的三步写入顺序在索引约束下可以完成。"""
    survey_id, user_id = ObjectId(), ObjectId()
    old_id = db[RESPONSES].insert_one(
        make_response(surveyId=survey_id, respondentId=user_id, isLatest=True)).inserted_id
    # ① 插入新答卷 isLatest: false
    new_id = db[RESPONSES].insert_one(
        make_response(surveyId=survey_id, respondentId=user_id, isLatest=False)).inserted_id
    # ② 旧的最新答卷置为 false
    db[RESPONSES].update_many(
        {"surveyId": survey_id, "respondentId": user_id, "isLatest": True, "_id": {"$ne": new_id}},
        {"$set": {"isLatest": False}})
    # ③ 新答卷置为 true
    db[RESPONSES].update_one({"_id": new_id}, {"$set": {"isLatest": True}})

    latest = list(db[RESPONSES].find({"surveyId": survey_id, "respondentId": user_id, "isLatest": True}))
    assert [d["_id"] for d in latest] == [new_id]
    assert db[RESPONSES].find_one({"_id": old_id})["isLatest"] is False


def test_has_answered_query_uses_partial_index(db):
    """“是否填写过”查询带 isLatest: true 时命中部分唯一索引（设计文档第 5 节）。"""
    survey_id, user_id = ObjectId(), ObjectId()
    db[RESPONSES].insert_one(make_response(surveyId=survey_id, respondentId=user_id))
    plan = db[RESPONSES].find(
        {"surveyId": survey_id, "respondentId": user_id, "isLatest": True}).explain()
    assert "surveyId_respondentId_latest_unique" in str(plan["queryPlanner"]["winningPlan"])


# ---------- 整数范围（设计文档 6.6） ----------
INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1


@pytest.mark.parametrize("value", [INT64_MIN, INT64_MAX, 13812345678])
def test_int64_boundary_values_can_be_stored(db, value):
    """64 位整数范围内的值（含两端边界、11 位手机号）能正常存储并原样读回。"""
    rid = db[RESPONSES].insert_one(
        make_response(answers=[{"questionId": "q_num001", "value": value}])).inserted_id
    assert db[RESPONSES].find_one({"_id": rid})["answers"][0]["value"] == value


@pytest.mark.parametrize("value", [INT64_MAX + 1, INT64_MIN - 1, 10 ** 20])
def test_int_beyond_int64_cannot_be_stored(db, value):
    """超出 64 位范围的整数无法写入 MongoDB——这就是 6.6 要求应用层提前按校验错误拒绝的原因。
    （应用层校验的测试在第六步“校验引擎”中补充。）"""
    with pytest.raises(OverflowError):
        db[RESPONSES].insert_one(make_response(answers=[{"questionId": "q_num001", "value": value}]))
