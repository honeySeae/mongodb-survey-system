"""第五步：题目编辑接口（添加、修改、删除、调整顺序）。"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from app.db import SURVEYS
from app.errors import AppError
from app.services import questions as question_service


# ---------- 工具 ----------
def new_survey(client, headers) -> dict:
    resp = client.post("/api/surveys", json={"title": "测试问卷"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()


def add(client, headers, sid, **body):
    return client.post(f"/api/surveys/{sid}/questions", json=body, headers=headers)


def add_ok(client, headers, sid, **body) -> dict:
    resp = add(client, headers, sid, **body)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def put(client, headers, sid, qid, **body):
    return client.put(f"/api/surveys/{sid}/questions/{qid}", json=body, headers=headers)


def put_ok(client, headers, sid, qid, **body) -> dict:
    resp = put(client, headers, sid, qid, **body)
    assert resp.status_code == 200, resp.json()
    return resp.json()


SINGLE = dict(type="single_choice", title="你喜欢吃水果吗？",
              options=[{"text": "喜欢"}, {"text": "不喜欢"}], validation={"required": True})
TEXT = dict(type="text", title="其他建议", validation={"required": False, "maxLength": 500})


def question(survey: dict, index: int) -> dict:
    return survey["questions"][index]


def as_update(q: dict, **changes) -> dict:
    """把返回的题目转成修改请求体（保留选项 id）。"""
    body = {"type": q["type"], "title": q["title"], "validation": q["validation"]}
    if "options" in q:
        body["options"] = [{"id": o["id"], "text": o["text"]} for o in q["options"]]
    if "logic" in q:
        body["logic"] = q["logic"]
    body.update(changes)
    return body


# ---------- 添加 ----------
def test_add_question(client, alice):
    s = new_survey(client, alice)
    resp = add(client, alice, s["id"], **SINGLE)
    assert resp.status_code == 201
    q = question(resp.json(), 0)
    assert re.fullmatch(r"q_[a-z0-9]{6}", q["id"])
    assert all(re.fullmatch(r"o_[a-z0-9]{6}", o["id"]) for o in q["options"])
    assert [o["text"] for o in q["options"]] == ["喜欢", "不喜欢"]
    assert q["validation"] == {"required": True}
    assert "logic" not in q


def test_add_defaults_required_false_and_trims(client, alice):
    s = new_survey(client, alice)
    q = question(add_ok(client, alice, s["id"], type="text", title="  建议  "), 0)
    assert q["title"] == "建议"
    assert q["validation"] == {"required": False}
    assert "options" not in q


def test_ids_unique_across_survey(client, alice):
    s = new_survey(client, alice)
    for _ in range(5):
        s = add_ok(client, alice, s["id"], **SINGLE)
    ids = [q["id"] for q in s["questions"]] + [o["id"] for q in s["questions"] for o in q["options"]]
    assert len(ids) == len(set(ids)) == 15


def test_add_appends_by_default_and_supports_position(client, alice):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], type="text", title="A")
    add_ok(client, alice, s["id"], type="text", title="B")
    s = add_ok(client, alice, s["id"], type="text", title="开头", position=1)
    s = add_ok(client, alice, s["id"], type="text", title="第三", position=3)
    s = add_ok(client, alice, s["id"], type="text", title="末尾", position=5)
    assert [q["title"] for q in s["questions"]] == ["开头", "A", "第三", "B", "末尾"]


@pytest.mark.parametrize("position", [0, 3, -1])
def test_add_invalid_position(client, alice, position):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **TEXT)
    resp = add(client, alice, s["id"], **TEXT, position=position)
    assert resp.status_code == 422
    assert resp.json()["errors"] == [{"field": "position", "message": "position 应为 1~2"}]


def test_add_with_logic_rejected(client, alice):
    s = new_survey(client, alice)
    resp = add(client, alice, s["id"], **SINGLE, logic={"rules": [], "defaultNext": None})
    assert resp.status_code == 422
    assert resp.json()["errors"] == [
        {"field": "logic", "message": "添加题目时不能设置跳转规则，请添加后通过修改题目设置"}]


def test_add_invalid_settings(client, alice, db):
    s = new_survey(client, alice)
    resp = add(client, alice, s["id"], type="multiple_choice", title="水果",
               options=[{"text": "苹果"}, {"text": "香蕉"}],
               validation={"required": True, "minSelect": 3})
    assert resp.status_code == 422
    body = resp.json()
    assert body["message"] == "题目设置不合法"
    err = body["errors"][0]
    assert err["field"] == "validation.minSelect"
    assert err["message"] == "第 1 题：最少选择数（3）不能大于选项数（2）"
    assert re.fullmatch(r"q_[a-z0-9]{6}", err["questionId"])
    assert db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["questions"] == []  # 未保存


@pytest.mark.parametrize("body, field", [
    ({**TEXT, "required": True}, "required"),                         # 写错位置的字段
    ({**SINGLE, "options": [{"text": "A", "id": "o_abc"}]}, "options.0.id"),  # 添加时选项不能带 id
    ({**TEXT, "position": "1"}, "position"),
    ({**TEXT, "title": 123}, "title"),
])
def test_add_request_format_errors(client, alice, body, field):
    s = new_survey(client, alice)
    resp = add(client, alice, s["id"], **body)
    assert resp.status_code == 422
    assert field in [e["field"] for e in resp.json()["errors"]]


def test_unknown_field_message(client, alice):
    s = new_survey(client, alice)
    resp = add(client, alice, s["id"], **TEXT, required=True)
    assert {"field": "required", "message": "不支持该字段"} in resp.json()["errors"]


# ---------- 修改与跳转规则 ----------
def test_set_logic_after_adding(client, alice):
    """两步保存：先添加题目，再修改题目设置跳转。"""
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **SINGLE)
    s = add_ok(client, alice, s["id"], **TEXT)
    q1, q2 = s["questions"]
    dislike = q1["options"][1]["id"]
    logic = {"rules": [{"when": {"op": "eq", "value": dislike}, "goto": "END"}], "defaultNext": q2["id"]}
    s = put_ok(client, alice, s["id"], q1["id"], **as_update(q1, logic=logic))
    assert question(s, 0)["logic"] == logic
    assert question(s, 0)["id"] == q1["id"]


def test_logic_defaults_filled(client, alice):
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    s = put_ok(client, alice, s["id"], q["id"], **as_update(q, logic={}))
    assert question(s, 0)["logic"] == {"rules": [], "defaultNext": None}


def test_update_without_logic_removes_it(client, alice):
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    s = put_ok(client, alice, s["id"], q["id"], **as_update(q, logic={"rules": [], "defaultNext": "END"}))
    body = as_update(question(s, 0))
    del body["logic"]
    assert "logic" not in question(put_ok(client, alice, s["id"], q["id"], **body), 0)


def test_option_ids_stable_when_renaming(client, alice):
    """修改选项文字时 id 不变，引用它的跳转规则仍然有效。"""
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    o1, o2 = q["options"]
    logic = {"rules": [{"when": {"op": "eq", "value": o2["id"]}, "goto": "END"}], "defaultNext": None}
    s = put_ok(client, alice, s["id"], q["id"], **as_update(q, logic=logic))
    renamed = [{"id": o1["id"], "text": "非常喜欢"}, {"id": o2["id"], "text": "一点也不喜欢"}]
    s = put_ok(client, alice, s["id"], q["id"], **as_update(question(s, 0), options=renamed))
    assert question(s, 0)["options"] == [{"id": o1["id"], "text": "非常喜欢"},
                                         {"id": o2["id"], "text": "一点也不喜欢"}]
    assert question(s, 0)["logic"] == logic


def test_add_option_in_update_gets_new_id(client, alice):
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    options = [{"id": o["id"], "text": o["text"]} for o in q["options"]] + [{"text": "一般"}]
    new_q = question(put_ok(client, alice, s["id"], q["id"], **as_update(q, options=options)), 0)
    assert [o["id"] for o in new_q["options"][:2]] == [o["id"] for o in q["options"]]
    assert re.fullmatch(r"o_[a-z0-9]{6}", new_q["options"][2]["id"])
    assert new_q["options"][2]["id"] not in {o["id"] for o in q["options"]}


@pytest.mark.parametrize("bad_id", ["o_zzzzzz", "FROM_OTHER_QUESTION", "DUPLICATE"])
def test_update_option_id_must_belong_to_question(client, alice, bad_id):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **SINGLE)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q1, q2 = s["questions"]
    if bad_id == "FROM_OTHER_QUESTION":
        bad_id = q2["options"][0]["id"]
    if bad_id == "DUPLICATE":
        bad_id = q1["options"][0]["id"]
    options = [{"id": q1["options"][0]["id"], "text": "A"}, {"id": bad_id, "text": "B"}]
    resp = put(client, alice, s["id"], q1["id"], **as_update(q1, options=options))
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "options[1].id"


def test_delete_option_referenced_by_rule_rejected(client, alice, db):
    """删除被本题跳转规则引用的选项 → 拒绝，并指出是哪条规则（设计文档 6.3 第 9 条）。"""
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    o1, o2 = q["options"]
    logic = {"rules": [{"when": {"op": "eq", "value": o2["id"]}, "goto": "END"}], "defaultNext": None}
    s = put_ok(client, alice, s["id"], q["id"], **as_update(q, logic=logic))
    resp = put(client, alice, s["id"], q["id"],
               **as_update(question(s, 0), options=[{"id": o1["id"], "text": "喜欢"}]))
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert err["field"] == "logic.rules[0].when.value"
    assert err["message"] == (f"第 1 题第 1 条规则：引用的选项 {o2['id']} 不是本题的选项"
                              f"（可能已被删除），请先修改该规则")
    assert len(db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["questions"][0]["options"]) == 2


def test_backward_jump_rejected_on_update(client, alice):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **TEXT)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q1, q2 = s["questions"]
    logic = {"rules": [{"when": {"op": "eq", "value": q2["options"][0]["id"]}, "goto": q1["id"]}]}
    resp = put(client, alice, s["id"], q2["id"], **as_update(q2, logic=logic))
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["message"] == \
        "第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）"


def test_change_question_type(client, alice):
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q = question(s, 0)
    s = put_ok(client, alice, s["id"], q["id"], type="number", title="年龄",
               validation={"required": True, "min": 0, "max": 120, "integerOnly": True})
    assert question(s, 0) == {"id": q["id"], "type": "number", "title": "年龄",
                              "validation": {"required": True, "min": 0, "max": 120, "integerOnly": True}}


def test_update_unknown_question(client, alice):
    s = new_survey(client, alice)
    resp = put(client, alice, s["id"], "q_nope00", **TEXT)
    assert resp.status_code == 404
    assert resp.json() == {"code": "QUESTION_NOT_FOUND", "message": "题目不存在"}


# ---------- 删除 ----------
def test_delete_question(client, alice):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **TEXT)
    s = add_ok(client, alice, s["id"], **SINGLE)
    q1 = question(s, 0)
    resp = client.delete(f"/api/surveys/{s['id']}/questions/{q1['id']}", headers=alice)
    assert resp.status_code == 200
    assert [q["type"] for q in resp.json()["questions"]] == ["single_choice"]


def test_delete_referenced_question_rejected(client, alice, db):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **SINGLE)
    s = add_ok(client, alice, s["id"], **TEXT)
    q1, q2 = s["questions"]
    logic = {"rules": [{"when": {"op": "eq", "value": q1["options"][0]["id"]}, "goto": q2["id"]}]}
    put_ok(client, alice, s["id"], q1["id"], **as_update(q1, logic=logic))
    resp = client.delete(f"/api/surveys/{s['id']}/questions/{q2['id']}", headers=alice)
    assert resp.status_code == 409
    assert resp.json()["code"] == "QUESTION_REFERENCED"
    assert resp.json()["message"] == "第 1 题「你喜欢吃水果吗？」的第 1 条规则跳转到这道题，请先修改该规则"
    assert len(db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["questions"]) == 2


def test_delete_unknown_question(client, alice):
    s = new_survey(client, alice)
    resp = client.delete(f"/api/surveys/{s['id']}/questions/q_nope00", headers=alice)
    assert resp.status_code == 404


# ---------- 调整顺序 ----------
def reorder(client, headers, sid, ids):
    return client.put(f"/api/surveys/{sid}/questions/order", json={"questionIds": ids}, headers=headers)


def test_reorder(client, alice):
    s = new_survey(client, alice)
    for t in ("A", "B", "C"):
        s = add_ok(client, alice, s["id"], type="text", title=t)
    ids = [q["id"] for q in s["questions"]]
    resp = reorder(client, alice, s["id"], [ids[2], ids[0], ids[1]])
    assert resp.status_code == 200
    assert [q["title"] for q in resp.json()["questions"]] == ["C", "A", "B"]


@pytest.mark.parametrize("make_ids", [
    lambda ids: ids[:2],                    # 缺少
    lambda ids: ids + ["q_extra0"],         # 多余
    lambda ids: [ids[0], ids[0], ids[1]],   # 重复
    lambda ids: [],
])
def test_reorder_must_be_permutation(client, alice, make_ids):
    s = new_survey(client, alice)
    for t in ("A", "B", "C"):
        s = add_ok(client, alice, s["id"], type="text", title=t)
    resp = reorder(client, alice, s["id"], make_ids([q["id"] for q in s["questions"]]))
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "questionIds"


def test_reorder_causing_backward_jump_rejected(client, alice, db):
    """调整顺序后原本往后跳的规则变成往前跳 → 拒绝（设计文档 6.3 第 2 条）。"""
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **SINGLE)
    add_ok(client, alice, s["id"], **TEXT)
    s = add_ok(client, alice, s["id"], type="text", title="第三题")
    q1, q2, q3 = s["questions"]
    logic = {"rules": [{"when": {"op": "eq", "value": q1["options"][0]["id"]}, "goto": q3["id"]}]}
    put_ok(client, alice, s["id"], q1["id"], **as_update(q1, logic=logic))
    resp = reorder(client, alice, s["id"], [q3["id"], q1["id"], q2["id"]])
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["message"] == \
        "第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）"
    stored = db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["questions"]
    assert [q["id"] for q in stored] == [q1["id"], q2["id"], q3["id"]]  # 顺序未变


def test_order_route_not_treated_as_question_id(client, alice):
    s = new_survey(client, alice)
    resp = reorder(client, alice, s["id"], [])
    assert resp.status_code == 200  # 空问卷，空列表正好是全部题目


# ---------- 警告 ----------
def test_warnings_returned(client, alice):
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], type="number", title="年龄",
               validation={"required": True, "min": 0, "max": 120, "integerOnly": True})
    q = question(s, 0)
    logic = {"rules": [{"when": {"op": "gte", "value": 18}, "goto": "END"},
                       {"when": {"op": "between", "value": [16, 20]}, "goto": "END"},
                       {"when": {"op": "gt", "value": 200}, "goto": "END"}]}
    resp = put(client, alice, s["id"], q["id"], **as_update(q, logic=logic))
    assert resp.status_code == 200  # 警告不影响保存
    messages = [w["message"] for w in resp.json()["warnings"]]
    assert "第 1 题第 2 条规则在题目允许的取值范围内（且为整数）永远不会成立" not in messages
    assert "第 1 题第 3 条规则在题目允许的取值范围内（且为整数）永远不会成立" in messages
    assert "第 1 题第 1 条和第 2 条规则的取值范围有重叠，重叠部分按第 1 条跳转" in messages
    # 详情接口也返回当前的警告
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).json()["warnings"] == resp.json()["warnings"]


def test_no_warnings_field_is_empty_list(client, alice):
    assert new_survey(client, alice)["warnings"] == []


# ---------- 权限与状态 ----------
def test_cannot_edit_others_survey(client, alice, bob):
    s = new_survey(client, alice)
    resp = add(client, bob, s["id"], **TEXT)
    assert resp.status_code == 404
    assert resp.json()["code"] == "SURVEY_NOT_FOUND"


@pytest.mark.parametrize("action", ["add", "update", "delete", "reorder"])
@pytest.mark.parametrize("final_status", ["published", "closed"])
def test_cannot_edit_after_publish(client, alice, action, final_status):
    """发布后不能修改题目（设计文档 6.5），已关闭同理。"""
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **TEXT)
    q = question(s, 0)
    client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    if final_status == "closed":
        client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    resp = {
        "add": lambda: add(client, alice, s["id"], **TEXT),
        "update": lambda: put(client, alice, s["id"], q["id"], **TEXT),
        "delete": lambda: client.delete(f"/api/surveys/{s['id']}/questions/{q['id']}", headers=alice),
        "reorder": lambda: reorder(client, alice, s["id"], [q["id"]]),
    }[action]()
    assert resp.status_code == 409
    name = "已发布" if final_status == "published" else "已关闭"
    assert resp.json() == {"code": "INVALID_STATUS", "message": f"问卷{name}，不能修改题目"}


def test_publish_rejects_invalid_questions_written_directly(client, alice, db):
    """数据被绕过接口写入不合法的跳转时，发布前的检查能拦住。"""
    s = new_survey(client, alice)
    s = add_ok(client, alice, s["id"], **SINGLE)
    db[SURVEYS].update_one({"_id": ObjectId(s["id"])},
                           {"$set": {"questions.0.logic": {"rules": [], "defaultNext": "q_gone00"}}})
    resp = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert resp.status_code == 422
    assert resp.json()["message"] == "题目设置不合法，无法发布"


# ---------- 编辑冲突 ----------
def test_expected_updated_at_matching(client, alice):
    s = new_survey(client, alice)
    resp = client.post(f"/api/surveys/{s['id']}/questions",
                       params={"expectedUpdatedAt": s["updatedAt"]}, json=TEXT, headers=alice)
    assert resp.status_code == 201


def test_expected_updated_at_stale(client, alice):
    s = new_survey(client, alice)
    add_ok(client, alice, s["id"], **TEXT)  # 另一个标签页先保存了
    resp = client.post(f"/api/surveys/{s['id']}/questions",
                       params={"expectedUpdatedAt": s["updatedAt"]}, json=TEXT, headers=alice)
    assert resp.status_code == 409
    assert resp.json() == {"code": "EDIT_CONFLICT", "message": "问卷已被修改，请刷新后重试"}


def test_expected_updated_at_requires_timezone(client, alice):
    s = new_survey(client, alice)
    resp = client.post(f"/api/surveys/{s['id']}/questions",
                       params={"expectedUpdatedAt": "2026-10-19T12:00:00"}, json=TEXT, headers=alice)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "expectedUpdatedAt"


def test_expected_updated_at_also_checks_survey_patch(client, alice):
    """修改问卷基本信息也会更新 updatedAt，之后用旧值编辑题目会被拒绝。"""
    s = new_survey(client, alice)
    client.patch(f"/api/surveys/{s['id']}", json={"title": "改了标题"}, headers=alice)
    resp = client.post(f"/api/surveys/{s['id']}/questions",
                       params={"expectedUpdatedAt": s["updatedAt"]}, json=TEXT, headers=alice)
    assert resp.status_code == 409


def test_concurrent_edits_do_not_lose_updates(client, alice, db):
    """多个请求同时添加题目：不带 expectedUpdatedAt 时，内部的条件更新仍保证不会互相覆盖。"""
    s = new_survey(client, alice)
    owner_id = db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["ownerId"]

    def try_add(n):
        try:
            question_service.add_question(db, owner_id, s["id"], qtype="text", title=f"题{n}",
                                          options=None, validation=None, position=None,
                                          logic_given=False)
            return "ok"
        except AppError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(try_add, range(8)))
    stored = db[SURVEYS].find_one({"_id": ObjectId(s["id"])})["questions"]
    assert results.count("ok") == len(stored) >= 1
    assert set(results) <= {"ok", "EDIT_CONFLICT"}


def test_updated_at_strictly_increases(client, alice, db, monkeypatch):
    """同一毫秒内的连续修改，updatedAt 仍然严格递增。"""
    frozen = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    s = new_survey(client, alice)
    db[SURVEYS].update_one({"_id": ObjectId(s["id"])}, {"$set": {"updatedAt": frozen}})
    monkeypatch.setattr(question_service, "now_utc", lambda: frozen)
    a = datetime.fromisoformat(add_ok(client, alice, s["id"], **TEXT)["updatedAt"])
    b = datetime.fromisoformat(add_ok(client, alice, s["id"], **TEXT)["updatedAt"])
    assert frozen < a < b  # 解析成时间再比较（字符串比较时 "00Z" 会大于 "00.001Z"）


# ---------- 完整流程：用接口搭建设计文档 3.4 的示例问卷并发布 ----------
def test_build_design_example_and_publish(client, alice):
    s = new_survey(client, alice)
    sid = s["id"]
    add_ok(client, alice, sid, type="single_choice", title="你喜欢吃水果吗？",
           options=[{"text": "喜欢"}, {"text": "不喜欢"}], validation={"required": True})
    add_ok(client, alice, sid, type="multiple_choice", title="你喜欢哪些水果？",
           options=[{"text": t} for t in ("苹果", "香蕉", "西瓜", "榴莲")],
           validation={"required": True, "minSelect": 1, "maxSelect": 3})
    add_ok(client, alice, sid, type="text", title="为什么喜欢榴莲？",
           validation={"required": False, "minLength": 5, "maxLength": 200})
    add_ok(client, alice, sid, type="number", title="你每周吃几次水果？",
           validation={"required": True, "min": 0, "max": 50, "integerOnly": True})
    s = add_ok(client, alice, sid, type="text", title="其他建议",
               validation={"required": False, "maxLength": 500})
    q1, q2, q3, q4, q5 = s["questions"]

    put_ok(client, alice, sid, q1["id"], **as_update(q1, logic={
        "rules": [{"when": {"op": "eq", "value": q1["options"][1]["id"]}, "goto": q5["id"]}],
        "defaultNext": None}))
    put_ok(client, alice, sid, q2["id"], **as_update(q2, logic={
        "rules": [{"when": {"op": "contains", "value": q2["options"][3]["id"]}, "goto": q3["id"]}],
        "defaultNext": q4["id"]}))
    s = put_ok(client, alice, sid, q4["id"], **as_update(q4, logic={
        "rules": [{"when": {"op": "eq", "value": 0}, "goto": "END"}], "defaultNext": None}))
    assert s["warnings"] == []

    resp = client.post(f"/api/surveys/{sid}/publish", headers=alice)
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    assert resp.json()["questions"] == s["questions"]
