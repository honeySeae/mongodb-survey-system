"""第四步：问卷创建、列表、详情、修改、删除、发布、关闭。"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.config import get_settings
from app.db import RESPONSES, SURVEYS
from app.errors import AppError
from app.services import surveys as survey_service
from app.utils import now_utc


# ---------- 工具 ----------
def future(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def create(client, headers, **body):
    payload = {"title": "水果偏好调查", **body}
    return client.post("/api/surveys", json=payload, headers=headers)


def create_ok(client, headers, **body) -> dict:
    resp = create(client, headers, **body)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def add_question_directly(db, survey_id: str):
    """添加题目的接口在第五步实现，这里直接写数据库，以便测试发布。"""
    db[SURVEYS].update_one({"_id": ObjectId(survey_id)}, {"$push": {"questions": {
        "id": "q_abc123", "type": "single_choice", "title": "你喜欢吃水果吗？",
        "options": [{"id": "o_aaa111", "text": "喜欢"}, {"id": "o_bbb222", "text": "不喜欢"}],
        "validation": {"required": True},
    }}})


def set_deadline_directly(db, survey_id: str, deadline: datetime):
    """接口不允许设置过去的截止时间，这里直接写数据库来模拟“已经过期”。"""
    db[SURVEYS].update_one({"_id": ObjectId(survey_id)}, {"$set": {"settings.deadline": deadline}})


def published(client, headers, db, **body) -> dict:
    s = create_ok(client, headers, **body)
    add_question_directly(db, s["id"])
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=headers)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def closed(client, headers, db, **body) -> dict:
    s = published(client, headers, db, **body)
    resp = client.post(f"/api/surveys/{s['id']}/close", headers=headers)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def patch(client, headers, survey_id, **body):
    return client.patch(f"/api/surveys/{survey_id}", json=body, headers=headers)


# ---------- 创建 ----------
def test_create_survey(client, alice, db):
    resp = create(client, alice, title="水果偏好调查", description="了解大家吃水果的习惯",
                  allowAnonymous=True, submissionPolicy="latest", deadline="2099-11-30T23:59:59+08:00")
    assert resp.status_code == 201
    s = resp.json()
    assert s["title"] == "水果偏好调查"
    assert s["description"] == "了解大家吃水果的习惯"
    assert s["status"] == "draft"
    assert s["isExpired"] is False
    assert s["settings"] == {"allowAnonymous": True, "submissionPolicy": "latest",
                             "deadline": "2099-11-30T15:59:59Z"}  # 统一存为 UTC
    assert s["version"] == 1
    assert s["questions"] == []
    assert s["publishedAt"] is None and s["closedAt"] is None

    doc = db[SURVEYS].find_one({"_id": ObjectId(s["id"])})
    me = client.get("/api/auth/me", headers=alice).json()
    assert doc["ownerId"] == ObjectId(me["id"])
    assert doc["settings"]["deadline"] == datetime(2099, 11, 30, 15, 59, 59, tzinfo=timezone.utc)
    assert "url" not in doc  # 链接不存数据库


def test_create_defaults(client, alice):
    s = create_ok(client, alice, title="只有标题")
    assert s["description"] == ""
    assert s["settings"] == {"allowAnonymous": False, "submissionPolicy": "once", "deadline": None}


def test_short_code_and_url(client, alice):
    s = create_ok(client, alice)
    assert re.fullmatch(r"[A-Za-z0-9]{6}", s["shortCode"])
    assert s["url"] == f"{get_settings().public_base_url}/survey/{s['shortCode']}"


def test_short_codes_are_unique(client, alice):
    codes = {create_ok(client, alice)["shortCode"] for _ in range(20)}
    assert len(codes) == 20


def test_short_code_collision_retries(client, alice, monkeypatch):
    """生成的 shortCode 与已有的重复时自动重试。"""
    first = create_ok(client, alice)
    codes = iter([first["shortCode"], first["shortCode"], "Zz9Yy8"])
    monkeypatch.setattr(survey_service, "generate_short_code", lambda: next(codes))
    assert create_ok(client, alice)["shortCode"] == "Zz9Yy8"


def test_short_code_collision_gives_up_after_retries(client, alice, monkeypatch):
    first = create_ok(client, alice)
    monkeypatch.setattr(survey_service, "generate_short_code", lambda: first["shortCode"])
    resp = create(client, alice)
    assert resp.status_code == 500
    assert resp.json()["code"] == "SHORT_CODE_EXHAUSTED"


def test_create_trims_title(client, alice):
    assert create_ok(client, alice, title="  标题  ")["title"] == "标题"


@pytest.mark.parametrize("body, field, message", [
    ({"title": ""}, "title", "标题不能为空"),
    ({"title": "   "}, "title", "标题不能为空"),
    ({"title": "题" * 101}, "title", "标题最多 100 个字符"),
    ({"description": "说" * 1001}, "description", "说明最多 1000 个字符"),
    ({"deadline": "2020-01-01T00:00:00Z"}, "deadline", "截止时间必须晚于当前时间"),
])
def test_create_invalid_fields(client, alice, body, field, message):
    resp = create(client, alice, **body)
    assert resp.status_code == 422
    assert {"field": field, "message": message} in resp.json()["errors"]


def test_create_title_and_description_boundaries(client, alice):
    s = create_ok(client, alice, title="题" * 100, description="说" * 1000)
    assert len(s["title"]) == 100 and len(s["description"]) == 1000


@pytest.mark.parametrize("body, field", [
    ({"submissionPolicy": "daily"}, "submissionPolicy"),
    ({"allowAnonymous": "yes"}, "allowAnonymous"),
    ({"allowAnonymous": 1}, "allowAnonymous"),
    ({"deadline": "下周五"}, "deadline"),
])
def test_create_invalid_types(client, alice, body, field):
    resp = create(client, alice, **body)
    assert resp.status_code == 422
    assert field in {e["field"] for e in resp.json()["errors"]}


def test_create_deadline_without_timezone_rejected(client, alice):
    resp = create(client, alice, deadline="2099-11-30T23:59:59")
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert err["field"] == "deadline"
    assert "时区" in err["message"]


def test_create_requires_login(client):
    assert create(client, {}).status_code == 401


# ---------- 列表 ----------
def test_list_only_my_surveys_newest_first(client, alice, bob):
    a1 = create_ok(client, alice, title="A1")
    a2 = create_ok(client, alice, title="A2")
    create_ok(client, bob, title="B1")
    items = client.get("/api/surveys", headers=alice).json()
    assert [s["id"] for s in items] == [a2["id"], a1["id"]]
    assert all("questions" not in s for s in items)


def test_list_question_count(client, alice, db):
    s = create_ok(client, alice)
    add_question_directly(db, s["id"])
    item = client.get("/api/surveys", headers=alice).json()[0]
    assert item["questionCount"] == 1


def _insert_response(db, survey_id, respondent, is_latest):
    db[RESPONSES].insert_one({
        "surveyId": ObjectId(survey_id), "surveyVersion": 1, "respondentId": respondent,
        "isLatest": is_latest, "submittedAt": now_utc(), "answers": [],
    })


@pytest.mark.parametrize("policy, expected", [
    ("once", 3),     # 全部答卷（每人一份）
    ("all", 3),      # 全部答卷
    ("latest", 2),   # 只算每人最新一份
])
def test_list_response_count_follows_policy(client, alice, db, policy, expected):
    """答卷数口径与统计一致（设计文档 6.7）。"""
    s = create_ok(client, alice, submissionPolicy=policy)
    u1, u2 = ObjectId(), ObjectId()
    _insert_response(db, s["id"], u1, False)
    _insert_response(db, s["id"], u1, True)
    _insert_response(db, s["id"], u2, True)
    create_ok(client, alice, title="没有答卷的问卷")
    items = {i["id"]: i for i in client.get("/api/surveys", headers=alice).json()}
    assert items[s["id"]]["responseCount"] == expected
    assert [i["responseCount"] for i in items.values() if i["id"] != s["id"]] == [0]


def test_list_empty(client, alice):
    assert client.get("/api/surveys", headers=alice).json() == []


# ---------- 详情与权限 ----------
def test_detail(client, alice):
    s = create_ok(client, alice)
    resp = client.get(f"/api/surveys/{s['id']}", headers=alice)
    assert resp.status_code == 200
    assert resp.json() == s


@pytest.mark.parametrize("method, suffix, body", [
    ("get", "", None),
    ("patch", "", {"title": "改"}),
    ("delete", "", None),
    ("post", "/publish", None),
    ("post", "/close", None),
])
def test_cannot_access_others_survey(client, alice, bob, db, method, suffix, body):
    """别人的问卷与不存在的问卷返回完全相同的 404，且不会被修改。"""
    s = create_ok(client, alice)
    add_question_directly(db, s["id"])
    s = client.get(f"/api/surveys/{s['id']}", headers=alice).json()  # 操作前的快照
    kwargs = {"headers": bob, **({"json": body} if body else {})}
    resp = getattr(client, method)(f"/api/surveys/{s['id']}{suffix}", **kwargs)
    missing = getattr(client, method)(f"/api/surveys/{ObjectId()}{suffix}", **kwargs)
    assert resp.status_code == missing.status_code == 404
    assert resp.json() == missing.json() == {"code": "SURVEY_NOT_FOUND", "message": "问卷不存在"}
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).json() == s


def test_invalid_id_returns_404(client, alice):
    resp = client.get("/api/surveys/not-an-id", headers=alice)
    assert resp.status_code == 404
    assert resp.json()["code"] == "SURVEY_NOT_FOUND"


# ---------- 修改 ----------
def test_update_draft_all_fields(client, alice):
    s = create_ok(client, alice)
    resp = patch(client, alice, s["id"], title="新标题", description="新说明", allowAnonymous=True,
                 submissionPolicy="all", deadline="2099-01-01T00:00:00Z")
    assert resp.status_code == 200
    u = resp.json()
    assert (u["title"], u["description"]) == ("新标题", "新说明")
    assert u["settings"] == {"allowAnonymous": True, "submissionPolicy": "all",
                             "deadline": "2099-01-01T00:00:00Z"}
    assert datetime.fromisoformat(u["updatedAt"]) >= datetime.fromisoformat(s["updatedAt"])


def test_update_only_given_fields(client, alice):
    s = create_ok(client, alice, description="原说明", deadline="2099-01-01T00:00:00Z")
    u = patch(client, alice, s["id"], title="新标题").json()
    assert u["description"] == "原说明"
    assert u["settings"]["deadline"] == "2099-01-01T00:00:00Z"


def test_update_clear_deadline(client, alice):
    s = create_ok(client, alice, deadline="2099-01-01T00:00:00Z")
    assert patch(client, alice, s["id"], deadline=None).json()["settings"]["deadline"] is None


@pytest.mark.parametrize("body, field", [
    ({"title": ""}, "title"),
    ({"title": None}, "title"),
    ({"description": "说" * 1001}, "description"),
    ({"submissionPolicy": None}, "submissionPolicy"),
    ({"deadline": "2020-01-01T00:00:00Z"}, "deadline"),
    ({"deadline": "2099-01-01T00:00:00"}, "deadline"),  # 无时区
])
def test_update_invalid_values(client, alice, body, field):
    s = create_ok(client, alice)
    resp = patch(client, alice, s["id"], **body)
    assert resp.status_code == 422
    assert field in {e["field"] for e in resp.json()["errors"]}


def test_update_published_allowed_fields(client, alice, db):
    s = published(client, alice, db)
    resp = patch(client, alice, s["id"], title="新标题", description="新说明",
                 deadline="2099-01-01T00:00:00+08:00")
    assert resp.status_code == 200
    assert resp.json()["settings"]["deadline"] == "2098-12-31T16:00:00Z"


@pytest.mark.parametrize("field, value, reason", [
    ("submissionPolicy", "all", "统计口径"),
    ("allowAnonymous", True, "隐私承诺"),
])
def test_update_published_locked_fields(client, alice, db, field, value, reason):
    s = published(client, alice, db)
    resp = patch(client, alice, s["id"], **{field: value, "title": "顺便改标题"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "FIELD_LOCKED"
    assert [e["field"] for e in body["errors"]] == [field]
    assert reason in body["message"]
    # 整个请求被拒绝，标题也没有被修改
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).json()["title"] == s["title"]


def test_update_same_value_on_locked_field_is_ok(client, alice, db):
    """提交与当前值相同的锁定字段不算修改（前端整份提交设置时不会被误拒）。"""
    s = published(client, alice, db, submissionPolicy="latest", allowAnonymous=True)
    resp = patch(client, alice, s["id"], title="新标题",
                 submissionPolicy="latest", allowAnonymous=True)
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"


@pytest.mark.parametrize("body", [
    {"title": "新标题"}, {"description": "新说明"}, {"deadline": "2099-01-01T00:00:00Z"},
    {"allowAnonymous": True}, {"submissionPolicy": "all"},
])
def test_update_closed_rejected(client, alice, db, body):
    s = closed(client, alice, db)
    resp = patch(client, alice, s["id"], **body)
    assert resp.status_code == 409
    assert resp.json()["code"] == "FIELD_LOCKED"
    assert resp.json()["message"].startswith("问卷已关闭，不能修改")


def test_update_no_change_does_not_touch_updated_at(client, alice):
    s = create_ok(client, alice)
    u = patch(client, alice, s["id"], title=s["title"]).json()
    assert u["updatedAt"] == s["updatedAt"]


def test_update_unchanged_past_deadline_is_ok(client, alice, db):
    """已过期问卷的旧截止时间原样提交时不报“必须晚于当前时间”。"""
    s = published(client, alice, db)
    set_deadline_directly(db, s["id"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    resp = patch(client, alice, s["id"], title="新标题", deadline="2020-01-01T00:00:00Z")
    assert resp.status_code == 200


# ---------- 删除 ----------
def test_delete_draft(client, alice, db):
    s = create_ok(client, alice)
    resp = client.delete(f"/api/surveys/{s['id']}", headers=alice)
    assert resp.status_code == 204
    assert db[SURVEYS].count_documents({"_id": ObjectId(s["id"])}) == 0
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).status_code == 404


@pytest.mark.parametrize("make", [published, closed])
def test_delete_non_draft_rejected(client, alice, db, make):
    s = make(client, alice, db)
    resp = client.delete(f"/api/surveys/{s['id']}", headers=alice)
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS"
    assert db[SURVEYS].count_documents({"_id": ObjectId(s["id"])}) == 1


# ---------- 发布 ----------
def test_publish(client, alice, db):
    s = create_ok(client, alice)
    add_question_directly(db, s["id"])
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert resp.status_code == 200
    p = resp.json()
    assert p["status"] == "published"
    assert p["publishedAt"] is not None
    assert p["shortCode"] == s["shortCode"]


def test_publish_without_questions_rejected(client, alice):
    s = create_ok(client, alice)
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert resp.status_code == 422
    assert resp.json() == {"code": "NO_QUESTIONS", "message": "问卷至少需要 1 道题才能发布"}


def test_publish_with_past_deadline_rejected(client, alice, db):
    s = create_ok(client, alice)
    add_question_directly(db, s["id"])
    set_deadline_directly(db, s["id"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "deadline"


@pytest.mark.parametrize("make, current", [(published, "已发布"), (closed, "已关闭")])
def test_publish_twice_or_after_close_rejected(client, alice, db, make, current):
    s = make(client, alice, db)
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert resp.status_code == 409
    assert resp.json() == {"code": "INVALID_STATUS",
                           "message": f"只有草稿的问卷可以发布（当前状态：{current}）"}


def test_concurrent_publish_only_one_succeeds(client, alice, db):
    """同时发起多次发布，条件更新保证只有一次成功。"""
    s = create_ok(client, alice)
    add_question_directly(db, s["id"])
    owner_id = db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["ownerId"]

    def try_publish(_):
        try:
            survey_service.publish_survey(db, owner_id, s["id"])
            return "ok"
        except AppError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(try_publish, range(8)))
    assert results.count("ok") == 1
    assert set(results) - {"ok"} <= {"INVALID_STATUS"}


# ---------- 关闭 ----------
def test_close(client, alice, db):
    s = published(client, alice, db)
    resp = client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    assert resp.status_code == 200
    c = resp.json()
    assert c["status"] == "closed"
    assert c["closedAt"] is not None
    assert c["publishedAt"] == s["publishedAt"]


def test_close_draft_rejected(client, alice):
    s = create_ok(client, alice)
    resp = client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    assert resp.status_code == 409
    assert resp.json()["message"] == "只有已发布的问卷可以关闭（当前状态：草稿）"


def test_close_twice_rejected(client, alice, db):
    s = closed(client, alice, db)
    assert client.post(f"/api/surveys/{s['id']}/close", headers=alice).status_code == 409


# ---------- 过期 ----------
def test_expired_survey(client, alice, db):
    """过了截止时间：isExpired 为 true，状态仍是 published（视同关闭，不自动改状态）。"""
    s = published(client, alice, db)
    set_deadline_directly(db, s["id"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    d = client.get(f"/api/surveys/{s['id']}", headers=alice).json()
    assert d["status"] == "published"
    assert d["isExpired"] is True
    assert client.get("/api/surveys", headers=alice).json()[0]["isExpired"] is True


def test_expired_survey_can_be_closed(client, alice, db):
    s = published(client, alice, db)
    set_deadline_directly(db, s["id"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert client.post(f"/api/surveys/{s['id']}/close", headers=alice).json()["status"] == "closed"


@pytest.mark.parametrize("new_deadline", [future(30), None])
def test_extend_expired_survey_resumes(client, alice, db, new_deadline):
    """已发布且过期的问卷延长截止时间（或改为不限）后恢复收集。"""
    s = published(client, alice, db)
    set_deadline_directly(db, s["id"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    resp = patch(client, alice, s["id"], deadline=new_deadline)
    assert resp.status_code == 200
    assert resp.json()["isExpired"] is False
    assert resp.json()["status"] == "published"
