"""第八步：统计与答卷列表。对应设计文档 6.1（匿名展示）、6.7（统计口径）。

固定数据（设计文档 3.4 示例问卷，4 位填写人按不同路径填写），每个期望数字都可以手工算出：
  zhang_san : 喜欢 → [苹果, 榴莲] → q3 "闻着臭吃着香" → q4 7 → q5 "多吃水果"
  li_si     : 喜欢 → [苹果, 香蕉] → q4 3 → q5 不答
  wang_wu   : 不喜欢 → q5 "不爱吃"（第 2~4 题被跳过）
  zhao_liu  : 喜欢 → [香蕉] → q4 0 → 结束（第 5 题被跳过）
"""
import json

import pytest
from bson import ObjectId

from app.db import RESPONSES
from app.utils import now_utc
from tests.builders import build_fruit_survey
from tests.conftest import auth_headers_for

RESPONDENTS = ["zhang_san", "li_si", "wang_wu", "zhao_liu"]


def answers_for(built, who: str) -> dict:
    q1, q2, q3, q4, q5 = [q["id"] for q in built["q"]]
    o = built["o"]
    return {
        "zhang_san": {q1: o["喜欢"], q2: [o["苹果"], o["榴莲"]], q3: "闻着臭吃着香", q4: 7, q5: "多吃水果"},
        "li_si": {q1: o["喜欢"], q2: [o["苹果"], o["香蕉"]], q4: 3},
        "wang_wu": {q1: o["不喜欢"], q5: "不爱吃"},
        "zhao_liu": {q1: o["喜欢"], q2: [o["香蕉"]], q4: 0},
        "zhang_san_changed": {q1: o["不喜欢"], q5: "改主意了"},
    }[who]


def submit(client, headers, built, answers: dict):
    resp = client.post(f"/api/s/{built['survey']['shortCode']}/responses", headers=headers,
                       json={"answers": [{"questionId": k, "value": v} for k, v in answers.items()]})
    return resp


@pytest.fixture
def owner(client):
    return auth_headers_for(client, "survey_owner")


@pytest.fixture
def people(client):
    return {name: auth_headers_for(client, name) for name in RESPONDENTS}


def scenario(client, owner, people, **settings):
    """搭建问卷并让 4 位填写人提交。"""
    built = build_fruit_survey(client, owner, **settings)
    for name in RESPONDENTS:
        assert submit(client, people[name], built, answers_for(built, name)).status_code == 201
    return built


def stats(client, owner, built):
    resp = client.get(f"/api/surveys/{built['survey']['id']}/stats", headers=owner)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def all_keys(obj) -> set:
    """递归收集 JSON 中出现的所有字段名。"""
    if isinstance(obj, dict):
        return set(obj) | set().union(*(all_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(all_keys(v) for v in obj))
    return set()


def option_counts(q: dict) -> dict:
    return {o["text"]: o["count"] for o in q["options"]}


# ---------- 各题型统计（设计文档 6.7） ----------
def test_whole_survey_stats(client, owner, people):
    built = scenario(client, owner, people)
    s = stats(client, owner, built)
    assert s["totalResponses"] == 4 and s["totalRespondents"] == 4
    assert s["submissionPolicy"] == "once" and s["scope"] == "全部答卷（每人一份）"
    q1, q2, q3, q4, q5 = s["questions"]

    # 单选：各选项人数 + 答卷数 + 作答人数
    assert option_counts(q1) == {"喜欢": 3, "不喜欢": 1}
    assert (q1["answerCount"], q1["respondentCount"]) == (4, 4)
    assert "items" not in q1 and "average" not in q1

    # 多选：各选项被选次数（没人选的西瓜为 0），按题目中的选项顺序
    assert [o["text"] for o in q2["options"]] == ["苹果", "香蕉", "西瓜", "榴莲"]
    assert option_counts(q2) == {"苹果": 2, "香蕉": 2, "西瓜": 0, "榴莲": 1}
    assert (q2["answerCount"], q2["respondentCount"]) == (3, 3)   # wang_wu 跳过了第 2 题

    # 文本：列出内容；被跳过、选填未答的不计入
    assert [i["value"] for i in q3["items"]] == ["闻着臭吃着香"]
    assert (q3["answerCount"], q3["itemsTotal"]) == (1, 1)
    assert "options" not in q3 and "average" not in q3

    # 数字：内容 + 平均值（新的在前）
    assert [i["value"] for i in q4["items"]] == [0, 3, 7]
    assert q4["average"] == pytest.approx(10 / 3)
    assert (q4["answerCount"], q4["respondentCount"]) == (3, 3)

    # 第 5 题：li_si 选填未答、zhao_liu 被跳过
    assert [i["value"] for i in q5["items"]] == ["不爱吃", "多吃水果"]
    assert q5["answerCount"] == 2


def test_single_question_stats(client, owner, people):
    built = scenario(client, owner, people)
    q2 = built["q"][1]
    resp = client.get(f"/api/surveys/{built['survey']['id']}/stats/questions/{q2['id']}", headers=owner)
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalResponses"] == 4
    assert body["question"] == stats(client, owner, built)["questions"][1]


def test_number_average_with_floats(client, owner):
    """整数与小数混合时平均值正确。"""
    sid = client.post("/api/surveys", json={"title": "身高"}, headers=owner).json()["id"]
    s = client.post(f"/api/surveys/{sid}/questions", headers=owner,
                    json={"type": "number", "title": "身高（米）", "validation": {"required": True}}).json()
    s = client.post(f"/api/surveys/{sid}/publish", headers=owner).json()
    qid = s["questions"][0]["id"]
    for i, v in enumerate([1.5, 2, 1.75]):
        h = auth_headers_for(client, f"tall{i}")
        client.post(f"/api/s/{s['shortCode']}/responses", headers=h,
                    json={"answers": [{"questionId": qid, "value": v}]})
    q = client.get(f"/api/surveys/{sid}/stats", headers=owner).json()["questions"][0]
    assert q["average"] == pytest.approx(1.75)


def test_empty_survey_stats(client, owner):
    """草稿或没有答卷：全为 0，平均值为 null，不报错。"""
    built = build_fruit_survey(client, owner, publish=False)
    s = stats(client, owner, built)
    assert s["totalResponses"] == 0 and s["totalRespondents"] == 0
    q1, q2, q3, q4, q5 = s["questions"]
    assert option_counts(q1) == {"喜欢": 0, "不喜欢": 0}
    assert q1["answerCount"] == 0 and q1["respondentCount"] == 0
    assert q3["items"] == [] and q3["itemsTotal"] == 0
    assert "average" in q4 and q4["average"] is None


# ---------- 三种提交策略的口径（设计文档 6.7） ----------
def test_policy_latest_counts_only_latest(client, owner, people):
    built = scenario(client, owner, people, submissionPolicy="latest")
    assert submit(client, people["zhang_san"], built, answers_for(built, "zhang_san_changed")).status_code == 201
    s = stats(client, owner, built)
    assert s["totalResponses"] == 4 and s["totalRespondents"] == 4
    q1, q2, q3, q4, q5 = s["questions"]
    assert option_counts(q1) == {"喜欢": 2, "不喜欢": 2}       # zhang_san 改成了不喜欢
    assert option_counts(q2) == {"苹果": 1, "香蕉": 2, "西瓜": 0, "榴莲": 0}
    assert q3["answerCount"] == 0                                # 旧答卷中的榴莲理由不再计入
    assert q4["average"] == pytest.approx(3 / 2)
    assert [i["value"] for i in q5["items"]] == ["改主意了", "不爱吃"]


def test_policy_all_counts_every_submission(client, owner, people):
    built = scenario(client, owner, people, submissionPolicy="all")
    assert submit(client, people["zhang_san"], built, answers_for(built, "zhang_san_changed")).status_code == 201
    s = stats(client, owner, built)
    assert s["totalResponses"] == 5 and s["totalRespondents"] == 4
    q1, *_, q5 = s["questions"]
    assert option_counts(q1) == {"喜欢": 3, "不喜欢": 2}
    assert (q1["answerCount"], q1["respondentCount"]) == (5, 4)  # all 下作答人数少于答卷数
    assert (q5["answerCount"], q5["respondentCount"]) == (3, 2)


def test_policy_once_second_submission_not_counted(client, owner, people):
    built = scenario(client, owner, people, submissionPolicy="once")
    assert submit(client, people["zhang_san"], built, answers_for(built, "zhang_san_changed")).status_code == 409
    assert option_counts(stats(client, owner, built)["questions"][0]) == {"喜欢": 3, "不喜欢": 1}


@pytest.mark.parametrize("policy", ["once", "latest", "all"])
def test_counts_consistent_across_endpoints(client, owner, people, policy):
    """问卷列表的答卷数、统计的总答卷数、答卷列表的总数三者一致（共用 scope_filter）。"""
    built = scenario(client, owner, people, submissionPolicy=policy)
    submit(client, people["li_si"], built, answers_for(built, "li_si"))
    sid = built["survey"]["id"]
    listed = next(s for s in client.get("/api/surveys", headers=owner).json() if s["id"] == sid)
    total = stats(client, owner, built)["totalResponses"]
    responses = client.get(f"/api/surveys/{sid}/responses", headers=owner).json()["total"]
    assert listed["responseCount"] == total == responses == {"once": 4, "latest": 4, "all": 5}[policy]


# ---------- 匿名展示（设计文档 6.1） ----------
def test_anonymous_hides_respondents_everywhere(client, owner, people, db):
    built = scenario(client, owner, people, allowAnonymous=True)
    sid = built["survey"]["id"]
    q3 = built["q"][2]["id"]
    payloads = [
        client.get(f"/api/surveys/{sid}/stats", headers=owner).json(),
        client.get(f"/api/surveys/{sid}/stats/questions/{q3}", headers=owner).json(),
        client.get(f"/api/surveys/{sid}/responses", headers=owner).json(),
    ]
    respondent_ids = [str(u["_id"]) for u in db["users"].find({"username": {"$in": RESPONDENTS}})]
    for body in payloads:
        text = json.dumps(body, ensure_ascii=False)
        for name in RESPONDENTS + respondent_ids:
            assert name not in text                       # 不出现任何用户名和用户 id
        assert all_keys(body).isdisjoint({"username", "respondentId", "respondent"})
    s = payloads[0]
    assert s["totalRespondents"] == 4                     # 作答人数（只是数字）仍然返回
    assert s["questions"][0]["respondentCount"] == 4


def test_non_anonymous_shows_usernames(client, owner, people):
    built = scenario(client, owner, people, allowAnonymous=False)
    sid = built["survey"]["id"]
    q5 = stats(client, owner, built)["questions"][4]
    assert [(i["value"], i["username"]) for i in q5["items"]] == [("不爱吃", "wang_wu"), ("多吃水果", "zhang_san")]
    items = client.get(f"/api/surveys/{sid}/responses", headers=owner).json()["items"]
    assert [i["username"] for i in items] == ["zhao_liu", "wang_wu", "li_si", "zhang_san"]
    text = json.dumps(items)
    assert "respondentId" not in text and "passwordHash" not in text   # 只取用户名


# ---------- 分页 ----------
def test_question_items_pagination(client, owner, people):
    built = scenario(client, owner, people)
    sid, q4 = built["survey"]["id"], built["q"][3]["id"]
    body = client.get(f"/api/surveys/{sid}/stats/questions/{q4}?offset=1&limit=2", headers=owner).json()
    assert [i["value"] for i in body["question"]["items"]] == [3, 7]
    assert body["question"]["itemsTotal"] == 3 and (body["offset"], body["limit"]) == (1, 2)
    assert body["question"]["average"] == pytest.approx(10 / 3)   # 平均值不受分页影响


def test_whole_survey_lists_20_items_single_question_lists_all(client, owner, db):
    """整份统计每道填空题只列最新 20 条并给出总数；单题统计可以分页查看全部。"""
    sid = client.post("/api/surveys", json={"title": "意见"}, headers=owner).json()["id"]
    s = client.post(f"/api/surveys/{sid}/questions", headers=owner,
                    json={"type": "text", "title": "意见"}).json()
    client.post(f"/api/surveys/{sid}/publish", headers=owner)
    qid = s["questions"][0]["id"]
    db[RESPONSES].insert_many([{
        "surveyId": ObjectId(sid), "surveyVersion": 1, "respondentId": ObjectId(), "isLatest": True,
        "submittedAt": now_utc(), "answers": [{"questionId": qid, "value": f"意见{i}"}]} for i in range(25)])
    whole = client.get(f"/api/surveys/{sid}/stats", headers=owner).json()["questions"][0]
    assert len(whole["items"]) == 20 and whole["itemsTotal"] == 25
    single = client.get(f"/api/surveys/{sid}/stats/questions/{qid}?limit=200", headers=owner).json()
    assert len(single["question"]["items"]) == 25


def test_responses_list_pagination(client, owner, people):
    built = scenario(client, owner, people)
    sid = built["survey"]["id"]
    page = client.get(f"/api/surveys/{sid}/responses?offset=1&limit=2", headers=owner).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert [i["username"] for i in page["items"]] == ["wang_wu", "li_si"]
    item = page["items"][0]
    assert set(item) == {"id", "submittedAt", "answers", "username"}
    assert ObjectId.is_valid(item["id"])


@pytest.mark.parametrize("path, message", [
    ("stats/questions/{q}?limit=0", "不能小于 1"),
    ("stats/questions/{q}?limit=201", "不能大于 200"),
    ("stats/questions/{q}?offset=-1", "不能小于 0"),
    ("responses?limit=101", "不能大于 100"),
    ("responses?limit=abc", "应为整数"),
])
def test_invalid_pagination(client, owner, path, message):
    built = build_fruit_survey(client, owner)
    url = f"/api/surveys/{built['survey']['id']}/" + path.format(q=built["q"][2]["id"])
    resp = client.get(url, headers=owner)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["message"] == message


def test_responses_list_excludes_history_for_latest(client, owner, people):
    """latest 策略下答卷列表只含每人最新一份（不含历史版本）。"""
    built = scenario(client, owner, people, submissionPolicy="latest")
    submit(client, people["zhang_san"], built, answers_for(built, "zhang_san_changed"))
    items = client.get(f"/api/surveys/{built['survey']['id']}/responses", headers=owner).json()["items"]
    assert [i["username"] for i in items].count("zhang_san") == 1
    assert len(items) == 4


# ---------- 权限 ----------
@pytest.mark.parametrize("suffix", ["stats", "stats/questions/{q}", "responses"])
def test_only_owner_can_view(client, owner, bob, suffix):
    built = build_fruit_survey(client, owner)
    url = f"/api/surveys/{built['survey']['id']}/" + suffix.format(q=built["q"][0]["id"])
    resp = client.get(url, headers=bob)
    assert resp.status_code == 404 and resp.json()["code"] == "SURVEY_NOT_FOUND"
    assert client.get(url).status_code == 401


def test_unknown_question(client, owner):
    built = build_fruit_survey(client, owner)
    resp = client.get(f"/api/surveys/{built['survey']['id']}/stats/questions/q_nope00", headers=owner)
    assert resp.status_code == 404 and resp.json()["code"] == "QUESTION_NOT_FOUND"


# ---------- 管道结构 ----------
def test_anonymous_pipelines_have_no_lookup():
    """匿名问卷的管道不包含 $lookup，也不输出 respondentId（在数据库层面保证不展示填写人）。"""
    from app.stats import pipelines as p
    sid = ObjectId()
    for anonymous, expect_lookup in [(True, False), (False, True)]:
        for pipeline in (p.text_question_pipeline(sid, {}, "q", anonymous, 0, 10),
                         p.number_question_pipeline(sid, {}, "q", anonymous, 0, 10),
                         p.responses_list_pipeline(sid, {}, anonymous, 0, 10)):
            text = json.dumps(pipeline, default=str)
            assert ("$lookup" in text) is expect_lookup
            projects = [s["$project"] for s in pipeline if "$project" in s]
            facet_projects = [st["$project"] for s in pipeline if "$facet" in s
                              for branch in s["$facet"].values() for st in branch if "$project" in st]
            for proj in projects + facet_projects:
                assert "respondentId" not in proj


def test_question_pipelines_share_first_three_stages():
    """四种题型共用前三步（得益于 answers 的 {questionId, value} 数组结构）。"""
    from app.stats import pipelines as p
    sid = ObjectId()
    common = p.question_answers_stages(sid, {"isLatest": True}, "q_x")
    for pipeline in (p.choice_question_pipeline(sid, {"isLatest": True}, "q_x", multiple=False),
                     p.choice_question_pipeline(sid, {"isLatest": True}, "q_x", multiple=True),
                     p.text_question_pipeline(sid, {"isLatest": True}, "q_x", True, 0, 10),
                     p.number_question_pipeline(sid, {"isLatest": True}, "q_x", True, 0, 10)):
        assert pipeline[:3] == common


def test_question_stats_uses_index(db, client, owner, people):
    """按题统计的第一步可以使用索引（不是全集合扫描）。"""
    from app.repositories.responses import scope_filter
    from app.stats import pipelines as p
    built = scenario(client, owner, people)
    match = p.question_answers_stages(ObjectId(built["survey"]["id"]), scope_filter("once"),
                                      built["q"][0]["id"])[0]["$match"]
    plan = db[RESPONSES].find(match).explain()["queryPlanner"]["winningPlan"]
    assert "IXSCAN" in json.dumps(plan, default=str)
