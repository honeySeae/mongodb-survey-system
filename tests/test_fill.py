"""第七步：填写与提交（获取问卷、路径预览、提交）。对应设计文档 6.1、6.2、6.3、6.4。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from app.db import RESPONSES, SURVEYS, USERS
from app.errors import AppError
from app.services import fill as fill_service
from tests.builders import build_fruit_survey
from tests.conftest import auth_headers_for


# ---------- 工具 ----------
def get(client, headers, code):
    return client.get(f"/api/s/{code}", headers=headers)


def path(client, headers, code, answers: dict):
    return client.post(f"/api/s/{code}/path", headers=headers,
                       json={"answers": [{"questionId": k, "value": v} for k, v in answers.items()]})


def submit(client, headers, code, answers: dict):
    return client.post(f"/api/s/{code}/responses", headers=headers,
                       json={"answers": [{"questionId": k, "value": v} for k, v in answers.items()]})


@pytest.fixture
def fruit(client, alice):
    """alice 创建并发布的示例问卷（默认 once、非匿名）。"""
    return build_fruit_survey(client, alice)


def ids(built):
    return [q["id"] for q in built["q"]]


def full_answers(built, durian=True):
    """一份完整合法的答案：喜欢 → 苹果(+榴莲) → (理由) → 每周 7 次 → 建议。"""
    q1, q2, q3, q4, q5 = ids(built)
    o = built["o"]
    a = {q1: o["喜欢"], q2: [o["苹果"]] + ([o["榴莲"]] if durian else []), q4: 7, q5: "多吃水果"}
    if durian:
        a[q3] = "闻着臭吃着香"
    return a


def user_id(db, username):
    return db[USERS].find_one({"username": username})["_id"]


def set_status(db, built, **fields):
    db[SURVEYS].update_one({"_id": ObjectId(built["survey"]["id"])}, {"$set": fields})


PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)


# ---------- 获取问卷（填写者视角） ----------
def test_get_survey_as_respondent(client, bob, fruit):
    resp = get(client, bob, fruit["survey"]["shortCode"])
    assert resp.status_code == 200
    s = resp.json()
    assert s["title"] == "水果偏好调查"
    assert s["accepting"] is True and s["notice"] is None
    assert s["isOwner"] is False and s["preview"] is False
    assert len(s["questions"]) == 5
    assert s["mySubmission"] == {"count": 0, "lastSubmittedAt": None, "canSubmit": True,
                                 "reason": None, "latestAnswers": None}


def test_respondent_cannot_see_logic_or_owner(client, bob, fruit):
    """填写者看不到跳转规则和内部字段（设计文档 6.1）。"""
    s = get(client, bob, fruit["survey"]["shortCode"]).json()
    assert all(set(q) <= {"id", "type", "title", "options", "validation"} for q in s["questions"])
    assert all("logic" not in q for q in s["questions"])
    assert "ownerId" not in s and "id" not in s and "warnings" not in s


def test_get_requires_login(client, fruit):
    assert get(client, {}, fruit["survey"]["shortCode"]).status_code == 401


def test_get_unknown_code(client, bob):
    resp = get(client, bob, "nope00")
    assert resp.status_code == 404
    assert resp.json() == {"code": "SURVEY_NOT_FOUND", "message": "问卷不存在"}


def test_short_code_is_case_sensitive(client, bob, fruit):
    code = fruit["survey"]["shortCode"]
    other = code.swapcase()
    if other != code:
        assert get(client, bob, other).status_code == 404


# ---------- 问卷状态（设计文档 6.4） ----------
def test_draft_hidden_from_others(client, alice, bob):
    built = build_fruit_survey(client, alice, publish=False)
    code = built["survey"]["shortCode"]
    for resp in (get(client, bob, code), path(client, bob, code, {}), submit(client, bob, code, {})):
        assert resp.status_code == 404
        assert resp.json() == {"code": "SURVEY_NOT_PUBLISHED", "message": "问卷尚未发布"}


def test_owner_can_preview_draft_but_not_submit(client, alice):
    built = build_fruit_survey(client, alice, publish=False)
    code = built["survey"]["shortCode"]
    s = get(client, alice, code).json()
    assert s["preview"] is True and s["isOwner"] is True and s["accepting"] is False
    assert s["notice"] == "预览模式：问卷尚未发布，不能提交"
    assert len(s["questions"]) == 5
    assert s["mySubmission"]["canSubmit"] is False
    # 路径预览允许（便于测试跳转）
    q1, *_ , q5 = ids(built)
    assert path(client, alice, code, {q1: built["o"]["不喜欢"]}).json()["nextQuestionId"] == q5
    # 提交不允许
    resp = submit(client, alice, code, full_answers(built))
    assert resp.status_code == 409
    assert resp.json()["code"] == "SURVEY_NOT_PUBLISHED"


@pytest.mark.parametrize("fields, code, notice", [
    ({"status": "closed"}, "SURVEY_CLOSED", "问卷已关闭，不再接受填写"),
    ({"settings.deadline": PAST}, "SURVEY_EXPIRED", "问卷已截止，不再接受填写"),
])
def test_closed_or_expired(client, bob, db, fruit, fields, code, notice):
    """已关闭/已过期：获取问卷返回 200 和提示但不含题目；预览和提交返回 409。"""
    set_status(db, fruit, **fields)
    sc = fruit["survey"]["shortCode"]
    s = get(client, bob, sc)
    assert s.status_code == 200
    body = s.json()
    assert body["accepting"] is False and body["notice"] == notice and body["questions"] is None
    assert body["mySubmission"]["canSubmit"] is False and body["mySubmission"]["reason"] == notice
    for resp in (path(client, bob, sc, {}), submit(client, bob, sc, full_answers(fruit))):
        assert resp.status_code == 409
        assert resp.json() == {"code": code, "message": notice}
    assert db[RESPONSES].count_documents({}) == 0


def test_close_via_api_then_submit_rejected(client, alice, bob, fruit):
    client.post(f"/api/surveys/{fruit['survey']['id']}/close", headers=alice)
    resp = submit(client, bob, fruit["survey"]["shortCode"], full_answers(fruit))
    assert resp.status_code == 409 and resp.json()["code"] == "SURVEY_CLOSED"


def test_extended_deadline_resumes_submission(client, alice, bob, db, fruit):
    set_status(db, fruit, **{"settings.deadline": PAST})
    sc = fruit["survey"]["shortCode"]
    assert submit(client, bob, sc, full_answers(fruit)).status_code == 409
    client.patch(f"/api/surveys/{fruit['survey']['id']}", json={"deadline": "2099-01-01T00:00:00Z"},
                 headers=alice)
    assert submit(client, bob, sc, full_answers(fruit)).status_code == 201


def test_owner_can_fill_own_published_survey(client, alice, fruit):
    s = get(client, alice, fruit["survey"]["shortCode"]).json()
    assert s["isOwner"] is True and s["preview"] is False and s["accepting"] is True
    assert submit(client, alice, fruit["survey"]["shortCode"], full_answers(fruit)).status_code == 201


# ---------- 路径预览 ----------
def test_preview_step_by_step(client, bob, fruit):
    q1, q2, q3, q4, q5 = ids(fruit)
    o, sc = fruit["o"], fruit["survey"]["shortCode"]
    steps = [({}, q1), ({q1: o["喜欢"]}, q2), ({q1: o["喜欢"], q2: [o["榴莲"]]}, q3),
             ({q1: o["喜欢"], q2: [o["榴莲"]], q3: None}, q4),
             ({q1: o["喜欢"], q2: [o["苹果"]], q4: 3}, q5)]
    for answers, expected in steps:
        body = path(client, bob, sc, answers).json()
        assert body["nextQuestionId"] == expected and body["errors"] == []
    done = path(client, bob, sc, {q1: o["不喜欢"], q5: None}).json()
    assert done == {"path": [q1, q5], "nextQuestionId": None, "finished": True, "errors": []}


def test_preview_returns_errors_with_200(client, bob, fruit):
    q1, q2, *_ = ids(fruit)
    o = fruit["o"]
    resp = path(client, bob, fruit["survey"]["shortCode"],
                {q1: o["喜欢"], q2: [o["苹果"], o["香蕉"], o["西瓜"], o["榴莲"]]})
    assert resp.status_code == 200
    assert resp.json()["errors"] == [{"questionId": q2, "field": "value",
                                      "message": "第 2 题：最多选择 3 项（当前选了 4 项）"}]


def test_preview_does_not_save(client, bob, db, fruit):
    path(client, bob, fruit["survey"]["shortCode"], full_answers(fruit))
    assert db[RESPONSES].count_documents({}) == 0


# ---------- 请求格式 ----------
@pytest.mark.parametrize("endpoint", ["path", "responses"])
def test_duplicate_question_rejected(client, bob, db, fruit, endpoint):
    q1 = ids(fruit)[0]
    o = fruit["o"]
    body = {"answers": [{"questionId": q1, "value": o["喜欢"]}, {"questionId": q1, "value": o["不喜欢"]}]}
    resp = client.post(f"/api/s/{fruit['survey']['shortCode']}/{endpoint}", json=body, headers=bob)
    assert resp.status_code == 422
    assert resp.json()["errors"] == [{"field": "answers", "questionId": q1, "message": "第 1 题的答案出现了多次"}]
    assert db[RESPONSES].count_documents({}) == 0


@pytest.mark.parametrize("body, field", [
    ({}, "answers"),
    ({"answers": [{"questionId": "q_x"}]}, "answers.0.value"),        # value 必须提交（可为 null）
    ({"answers": [{"value": 1}]}, "answers.0.questionId"),
    ({"answers": [{"questionId": "q_x", "value": 1, "extra": 2}]}, "answers.0.extra"),
    ({"answers": "nope"}, "answers"),
])
def test_request_format(client, bob, fruit, body, field):
    resp = client.post(f"/api/s/{fruit['survey']['shortCode']}/responses", json=body, headers=bob)
    assert resp.status_code == 422
    assert field in [e["field"] for e in resp.json()["errors"]]


def test_answers_limit_200(client, bob, fruit):
    sc = fruit["survey"]["shortCode"]
    many = {"answers": [{"questionId": f"q_x{i}", "value": None} for i in range(201)]}
    resp = client.post(f"/api/s/{sc}/path", json=many, headers=bob)
    assert resp.status_code == 422
    assert {"field": "answers", "message": "数量超出上限"} in resp.json()["errors"]
    many["answers"] = many["answers"][:200]
    assert client.post(f"/api/s/{sc}/path", json=many, headers=bob).status_code == 200


# ---------- 提交：后端重算路径并校验（设计文档 6.3 第 6 条） ----------
def test_submit_success(client, bob, db, fruit):
    resp = submit(client, bob, fruit["survey"]["shortCode"], full_answers(fruit))
    assert resp.status_code == 201
    body = resp.json()
    assert body["isLatest"] is True
    doc = db[RESPONSES].find_one({"_id": ObjectId(body["id"])})
    assert doc["surveyId"] == ObjectId(fruit["survey"]["id"])
    assert doc["surveyVersion"] == 1
    assert doc["respondentId"] == user_id(db, "bob")
    assert doc["isLatest"] is True
    assert doc["answers"] == body["answers"]
    assert [a["questionId"] for a in doc["answers"]] == ids(fruit)


def test_submit_saves_normalized_answers(client, bob, db, fruit):
    q1, q2, q3, q4, q5 = ids(fruit)
    o = fruit["o"]
    resp = submit(client, bob, fruit["survey"]["shortCode"],
                  {q1: o["喜欢"], q2: [o["榴莲"], o["苹果"]], q3: "  闻着臭吃着香  ", q4: 7.0, q5: "  "})
    assert resp.status_code == 201
    assert resp.json()["answers"] == [
        {"questionId": q1, "value": o["喜欢"]},
        {"questionId": q2, "value": [o["苹果"], o["榴莲"]]},  # 按选项顺序
        {"questionId": q3, "value": "闻着臭吃着香"},          # 去首尾空白
        {"questionId": q4, "value": 7},                       # 7.0 -> 7
    ]                                                          # q5 空白视为未作答，不保存
    stored = db[RESPONSES].find_one({})["answers"]
    assert isinstance(stored[3]["value"], int)                # 数字存为数值类型


def test_submit_discards_off_path_answers(client, bob, db, fruit):
    """选“不喜欢”跳到第 5 题：第 2~4 题被跳过，即使提交了（甚至不合法）也不校验、不保存。"""
    q1, q2, q3, q4, q5 = ids(fruit)
    o = fruit["o"]
    resp = submit(client, bob, fruit["survey"]["shortCode"],
                  {q1: o["不喜欢"], q2: [o["苹果"], o["香蕉"], o["西瓜"], o["榴莲"]], q3: "短",
                   q4: -1, q5: "无", "q_unknown": "多余"})
    assert resp.status_code == 201
    assert [a["questionId"] for a in resp.json()["answers"]] == [q1, q5]
    assert [a["questionId"] for a in db[RESPONSES].find_one({})["answers"]] == [q1, q5]


def test_skipped_required_not_needed(client, bob, fruit):
    """第 4 题必答，但选“不喜欢”后被跳过，不答也能提交。"""
    q1, *_ = ids(fruit)
    assert submit(client, bob, fruit["survey"]["shortCode"], {q1: fruit["o"]["不喜欢"]}).status_code == 201


@pytest.mark.parametrize("make, message", [
    (lambda q, o: {}, "第 1 题：此题为必答题"),
    (lambda q, o: {q[0]: o["喜欢"], q[1]: [o["苹果"]]}, "第 4 题：此题为必答题"),
    (lambda q, o: {q[0]: o["喜欢"], q[1]: [o["榴莲"]], q[2]: "好吃", q[3]: 1}, "第 3 题：至少 5 个字（当前 2 个）"),
    (lambda q, o: {q[0]: o["喜欢"], q[1]: [o["苹果"]], q[3]: "7"}, "第 4 题：应填写数字"),
    (lambda q, o: {q[0]: o["喜欢"], q[1]: [o["苹果"]], q[3]: 2 ** 63}, "第 4 题：数值超出允许范围"),
])
def test_submit_invalid_rejected_and_not_saved(client, bob, db, fruit, make, message):
    resp = submit(client, bob, fruit["survey"]["shortCode"], make(ids(fruit), fruit["o"]))
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR" and body["message"] == "答案不合法"
    assert len(body["errors"]) == 1 and body["errors"][0]["message"].startswith(message)
    assert db[RESPONSES].count_documents({}) == 0


# ---------- 三种提交策略（设计文档 6.2） ----------
def test_policy_once(client, bob, db):
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="once")
    sc = built["survey"]["shortCode"]
    assert submit(client, bob, sc, full_answers(built)).status_code == 201
    resp = submit(client, bob, sc, full_answers(built, durian=False))
    assert resp.status_code == 409
    assert resp.json() == {"code": "ALREADY_SUBMITTED", "message": "你已经填写过这份问卷（每人只能填写一次）"}
    assert db[RESPONSES].count_documents({}) == 1
    me = get(client, bob, sc).json()["mySubmission"]
    assert me["count"] == 1 and me["canSubmit"] is False and me["reason"].startswith("你已经填写过")
    assert me["latestAnswers"] is None  # once 不返回预填


def test_policy_latest(client, bob, db):
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="latest")
    sc = built["survey"]["shortCode"]
    first = submit(client, bob, sc, full_answers(built)).json()
    second = submit(client, bob, sc, full_answers(built, durian=False)).json()
    third = submit(client, bob, sc, full_answers(built)).json()
    docs = {str(d["_id"]): d for d in db[RESPONSES].find({})}
    assert len(docs) == 3                                     # 所有提交都保留
    assert [docs[r["id"]]["isLatest"] for r in (first, second, third)] == [False, False, True]
    me = get(client, bob, sc).json()["mySubmission"]
    assert me["count"] == 3 and me["canSubmit"] is True
    assert me["latestAnswers"] == third["answers"]            # 预填本人最新一份


def test_policy_all(client, bob, db):
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="all")
    sc = built["survey"]["shortCode"]
    for _ in range(3):
        assert submit(client, bob, sc, full_answers(built)).status_code == 201
    assert db[RESPONSES].count_documents({}) == 3
    assert db[RESPONSES].count_documents({"isLatest": True}) == 1   # isLatest 在所有策略下都维护
    me = get(client, bob, sc).json()["mySubmission"]
    assert me["count"] == 3 and me["canSubmit"] is True and me["latestAnswers"] is None


def test_latest_answers_only_own(client, bob, db):
    owner = auth_headers_for(client, "owner1")
    built = build_fruit_survey(client, owner, submissionPolicy="latest")
    sc = built["survey"]["shortCode"]
    submit(client, bob, sc, full_answers(built))
    carol = auth_headers_for(client, "carol")
    assert get(client, carol, sc).json()["mySubmission"]["latestAnswers"] is None


def test_policies_independent_per_survey(client, bob):
    """同一用户在不同问卷上的提交互不影响。"""
    owner = auth_headers_for(client, "owner1")
    a = build_fruit_survey(client, owner)
    b = build_fruit_survey(client, owner)
    assert submit(client, bob, a["survey"]["shortCode"], full_answers(a)).status_code == 201
    assert submit(client, bob, b["survey"]["shortCode"], full_answers(b)).status_code == 201


# ---------- 匿名（设计文档 6.1） ----------
def test_anonymous_still_records_respondent(client, bob, db):
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), allowAnonymous=True)
    sc = built["survey"]["shortCode"]
    assert get(client, bob, sc).json()["settings"]["allowAnonymous"] is True
    submit(client, bob, sc, full_answers(built))
    assert db[RESPONSES].find_one({})["respondentId"] == user_id(db, "bob")
    # 匿名问卷同样能防止重复填写（once）
    assert submit(client, bob, sc, full_answers(built)).status_code == 409


# ---------- 并发 ----------
def test_many_users_submit_concurrently(client, db, fruit):
    """多人同时填写，全部保存。"""
    headers = [auth_headers_for(client, f"user{i}") for i in range(10)]
    sc = fruit["survey"]["shortCode"]
    answers = full_answers(fruit)
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(lambda h: submit(client, h, sc, answers).status_code, headers))
    assert codes == [201] * 10
    assert db[RESPONSES].count_documents({"isLatest": True}) == 10


def _concurrent_same_user(db, built, uid, n=8):
    survey = db[SURVEYS].find_one({"_id": ObjectId(built["survey"]["id"])})
    items = [{"questionId": k, "value": v} for k, v in full_answers(built).items()]

    def try_submit(_):
        try:
            fill_service.submit(db, survey["shortCode"], uid, items)
            return "ok"
        except AppError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(try_submit, range(n)))


def test_concurrent_once_only_one_saved(client, bob, db):
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="once")
    results = _concurrent_same_user(db, built, user_id(db, "bob"))
    assert results.count("ok") == 1
    assert set(results) == {"ok", "ALREADY_SUBMITTED"}
    assert db[RESPONSES].count_documents({}) == 1


@pytest.mark.parametrize("policy", ["latest", "all"])
def test_concurrent_same_user_latest_switch(client, bob, db, policy):
    """同一用户并发提交：最终恰好一份 isLatest；返回 409 的提交没有留下答卷（设计文档 6.2 修正）。"""
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy=policy)
    results = _concurrent_same_user(db, built, user_id(db, "bob"))
    assert set(results) <= {"ok", "SUBMIT_CONFLICT"}
    assert db[RESPONSES].count_documents({"isLatest": True}) == 1
    assert db[RESPONSES].count_documents({}) == results.count("ok")


def test_step3_conflict_deletes_inserted_response(client, bob, db, monkeypatch):
    """确定性地模拟第 ③ 步冲突：撤销刚插入的答卷并返回 409（设计文档 6.2 修正）。"""
    from pymongo.errors import DuplicateKeyError
    from app.repositories import responses as repo

    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="all")
    sc = built["survey"]["shortCode"]
    assert submit(client, bob, sc, full_answers(built)).status_code == 201

    def conflict(db_, rid):
        raise DuplicateKeyError("模拟：另一份提交抢先成为最新")
    monkeypatch.setattr(repo, "mark_latest", conflict)
    resp = submit(client, bob, sc, full_answers(built))
    assert resp.status_code == 409
    assert resp.json() == {"code": "SUBMIT_CONFLICT", "message": "检测到同时提交，本次提交未保存，请稍后重试"}
    assert db[RESPONSES].count_documents({}) == 1   # 只剩第一次的答卷


# ---------- 数据异常保护 ----------
def test_corrupted_logic_returns_500_not_loop(client, bob, db, fruit):
    """跳转规则被绕过接口改成往前跳时，返回 500 而不是死循环。"""
    q1 = ids(fruit)[0]
    db[SURVEYS].update_one({"_id": ObjectId(fruit["survey"]["id"])},
                           {"$set": {"questions.1.logic.defaultNext": q1}})
    resp = submit(client, bob, fruit["survey"]["shortCode"], full_answers(fruit, durian=False))
    assert resp.status_code == 500
    assert resp.json()["code"] == "SURVEY_DATA_INVALID"


# ---------- 完整流程 ----------
def test_full_flow_preview_then_submit(client, bob, db, fruit):
    """获取问卷 → 逐题预览 → 提交 → 再次获取问卷看到自己的提交记录。"""
    sc = fruit["survey"]["shortCode"]
    q1, q2, q3, q4, q5 = ids(fruit)
    o = fruit["o"]
    assert get(client, bob, sc).json()["questions"][0]["id"] == q1
    answers = {}
    for qid, value in [(q1, o["喜欢"]), (q2, [o["香蕉"]]), (q4, 0)]:
        assert path(client, bob, sc, answers).json()["nextQuestionId"] == qid
        answers[qid] = value
    assert path(client, bob, sc, answers).json()["finished"] is True   # 每周 0 次 → END
    resp = submit(client, bob, sc, answers)
    assert resp.status_code == 201
    assert [a["questionId"] for a in resp.json()["answers"]] == [q1, q2, q4]
    me = get(client, bob, sc).json()["mySubmission"]
    assert me["count"] == 1 and me["lastSubmittedAt"] == resp.json()["submittedAt"]


def test_duplicate_unknown_question_message(client, bob, fruit):
    body = {"answers": [{"questionId": "q_ghost0", "value": 1}, {"questionId": "q_ghost0", "value": 2}]}
    resp = client.post(f"/api/s/{fruit['survey']['shortCode']}/path", json=body, headers=bob)
    assert resp.json()["errors"][0]["message"] == "题目 q_ghost0 的答案出现了多次"
