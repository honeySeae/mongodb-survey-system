"""第十步：示例数据脚本 scripts/seed_demo.py（在测试库上运行）。"""
from bson import ObjectId

from app.db import RESPONSES, SURVEYS, USERS
from app.logic.survey_check import check_survey
from scripts import seed_demo


def test_seed_creates_published_demo_survey(db):
    result = seed_demo.seed(db)
    assert result["created"] is True
    survey = db[SURVEYS].find_one({"_id": ObjectId(result["survey_id"])})
    assert survey["title"] == "大学生饮食习惯调查"
    assert survey["status"] == "published"
    assert survey["settings"] == {"allowAnonymous": False, "submissionPolicy": "latest", "deadline": None}
    assert len(survey["questions"]) == 12
    check = check_survey(survey["questions"])
    assert check.errors == [] and check.warnings == []        # 没有错误，也没有永远不会显示的题等警告
    assert result["url"].endswith(f"/survey/{survey['shortCode']}")


def test_seed_covers_types_jumps_and_validations(db):
    seed_demo.seed(db)
    qs = db[SURVEYS].find_one({"title": "大学生饮食习惯调查"})["questions"]
    assert {q["type"] for q in qs} == {"single_choice", "multiple_choice", "text", "number"}
    ops = {(q["type"], r["when"]["op"]) for q in qs for r in (q.get("logic") or {}).get("rules", [])}
    assert {("single_choice", "eq"), ("multiple_choice", "contains"), ("number", "gte")} <= ops
    assert any(r["goto"] == "END" for q in qs for r in (q.get("logic") or {}).get("rules", []))
    assert qs[1]["validation"] == {"required": True, "min": 0, "max": 120, "integerOnly": True}   # 年龄 0–120 整数
    assert qs[10]["validation"]["minSelect"] == qs[10]["validation"]["maxSelect"] == 2           # 必须选 2 项
    assert qs[8]["validation"]["minLength"] == 5                                                 # 文本字数


def test_seed_responses_follow_different_paths(db):
    result = seed_demo.seed(db)
    sid = ObjectId(result["survey_id"])
    assert result["responses"] == 13 and result["respondents"] == 12
    qs = db[SURVEYS].find_one({"_id": sid})["questions"]
    qn = {q["id"]: n for n, q in enumerate(qs, start=1)}

    def latest_path(username):
        uid = db[USERS].find_one({"username": username})["_id"]
        doc = db[RESPONSES].find_one({"surveyId": sid, "respondentId": uid, "isLatest": True})
        return [qn[a["questionId"]] for a in doc["answers"]]

    assert latest_path("demo_s03") == [1]                                        # 选“否” → 结束问卷
    assert latest_path("demo_s12") == [1, 2, 3, 4, 6, 7, 10, 11, 12]            # 不吃早餐 → 第 6 题；没选外卖 → 第 10 题
    assert latest_path("demo_s09") == [1, 2, 3, 4, 5, 7, 8, 9, 10, 11]          # 外卖每周 7 次 → 第 9 题
    assert latest_path("demo_s04") == [1, 2, 3, 4, 5, 7, 8, 10, 11]             # 外卖每周 3 次 → 跳过第 9 题
    assert latest_path("demo_s02") == [1, 2, 3, 4, 6, 7, 8, 10, 11, 12]         # 重新提交后以最新一份为准
    assert db[RESPONSES].count_documents({"surveyId": sid, "isLatest": True}) == 12


def test_seed_is_idempotent(db):
    first = seed_demo.seed(db)
    second = seed_demo.seed(db)
    assert second["created"] is False
    assert second["survey_id"] == first["survey_id"]
    assert db[SURVEYS].count_documents({"title": "大学生饮食习惯调查"}) == 1
    assert db[RESPONSES].count_documents({}) == 13
    assert db[USERS].count_documents({"username": {"$regex": "^demo_"}}) == 13


def test_seed_reset_recreates(db):
    first = seed_demo.seed(db)
    other = db[SURVEYS].insert_one({**db[SURVEYS].find_one({"_id": ObjectId(first["survey_id"])}),
                                    "_id": ObjectId(), "title": "别的问卷", "shortCode": "keepMe"}).inserted_id
    again = seed_demo.seed(db, reset=True)
    assert again["created"] is True and again["survey_id"] != first["survey_id"]
    assert db[SURVEYS].count_documents({"title": "大学生饮食习惯调查"}) == 1
    assert db[RESPONSES].count_documents({}) == 13
    assert db[SURVEYS].count_documents({"_id": other}) == 1                     # 只删示例问卷，不碰其他数据


def test_seed_owner_password_option(db):
    from app.security import verify_password
    seed_demo.seed(db, owner_password="another-secret-pw")
    owner = db[USERS].find_one({"username": "demo_owner"})
    assert verify_password("another-secret-pw", owner["passwordHash"])
    assert not verify_password("demo123456", owner["passwordHash"])
