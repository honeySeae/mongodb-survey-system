"""统计与答卷列表的业务逻辑。对应设计文档 6.1（匿名展示）、6.7（统计口径）。

约定（2026-10-19 开发者确认，见 AI_LOG 第 19 条）：
- 统计用聚合管道实时计算（app/stats/pipelines.py），口径由 scope_filter 统一定义
- 整份统计：一题一个查询；填空题只列最新 20 条并给出总数。单题统计可分页查看全部内容
- 答卷列表口径与统计一致（不含历史版本）
- 匿名问卷的管道不取用户名、不输出 respondentId
"""
from bson import ObjectId
from pymongo.database import Database

from app.db import RESPONSES
from app.errors import NotFound
from app.repositories.responses import scope_filter
from app.services.surveys import get_owned
from app.stats import pipelines as p

WHOLE_SURVEY_ITEMS = 20  # 整份统计中每道填空题列出的条数

SCOPE_NAMES = {
    "once": "全部答卷（每人一份）",
    "latest": "每人最新一份答卷",
    "all": "全部答卷（含同一人的多次提交）",
}


def _aggregate_one(db: Database, pipeline: list[dict]) -> dict:
    rows = list(db[RESPONSES].aggregate(pipeline))
    return rows[0] if rows else {}


def _totals(facet: dict) -> dict:
    totals = facet.get("totals") or [{}]
    return {"answer_count": totals[0].get("answerCount", 0),
            "respondent_count": totals[0].get("respondentCount", 0)}


def _question_stats(db: Database, survey: dict, q: dict, skip: int, limit: int) -> dict:
    sid, scope = survey["_id"], scope_filter(survey["settings"]["submissionPolicy"])
    anonymous = survey["settings"]["allowAnonymous"]
    base = {"question_id": q["id"], "type": q["type"], "title": q["title"]}
    qtype = q["type"]

    if qtype in ("single_choice", "multiple_choice"):
        facet = _aggregate_one(db, p.choice_question_pipeline(
            sid, scope, q["id"], multiple=qtype == "multiple_choice"))
        counts = {row["_id"]: row["count"] for row in facet.get("byOption", [])}
        # 按题目中的选项顺序列出全部选项，没人选的为 0
        options = [{"id": o["id"], "text": o["text"], "count": counts.get(o["id"], 0)}
                   for o in q["options"]]
        return {**base, **_totals(facet), "options": options}

    if qtype == "text":
        facet = _aggregate_one(db, p.text_question_pipeline(sid, scope, q["id"], anonymous, skip, limit))
    else:
        facet = _aggregate_one(db, p.number_question_pipeline(sid, scope, q["id"], anonymous, skip, limit))
    totals = _totals(facet)
    result = {**base, **totals, "items": facet.get("items", []), "items_total": totals["answer_count"]}
    if qtype == "number":
        average = facet.get("average") or [{}]
        result["average"] = average[0].get("value")  # 没人作答时为 None
    return result


def _survey_header(db: Database, survey: dict) -> dict:
    scope = scope_filter(survey["settings"]["submissionPolicy"])
    totals = _aggregate_one(db, p.survey_totals_pipeline(survey["_id"], scope))
    return {
        "survey_id": str(survey["_id"]),
        "title": survey["title"],
        "status": survey["status"],
        "allow_anonymous": survey["settings"]["allowAnonymous"],
        "submission_policy": survey["settings"]["submissionPolicy"],
        "scope": SCOPE_NAMES[survey["settings"]["submissionPolicy"]],
        "total_responses": totals.get("responses", 0),
        "total_respondents": totals.get("respondents", 0),
    }


def survey_stats(db: Database, owner_id: ObjectId, survey_id: str) -> dict:
    """整份问卷统计：一题一个查询，填空题只列最新的若干条。"""
    survey = get_owned(db, owner_id, survey_id)
    questions = [_question_stats(db, survey, q, 0, WHOLE_SURVEY_ITEMS) for q in survey["questions"]]
    return {**_survey_header(db, survey), "questions": questions}


def question_stats(db: Database, owner_id: ObjectId, survey_id: str, question_id: str,
                   offset: int, limit: int) -> dict:
    """单题统计；填空题可分页查看全部内容。"""
    survey = get_owned(db, owner_id, survey_id)
    q = next((q for q in survey["questions"] if q["id"] == question_id), None)
    if q is None:
        raise NotFound("QUESTION_NOT_FOUND", "题目不存在")
    return {**_survey_header(db, survey), "question": _question_stats(db, survey, q, offset, limit),
            "offset": offset, "limit": limit}


def list_responses(db: Database, owner_id: ObjectId, survey_id: str, offset: int, limit: int) -> dict:
    """答卷列表（口径与统计一致、不含历史版本）。匿名问卷不含填写人。"""
    survey = get_owned(db, owner_id, survey_id)
    scope = scope_filter(survey["settings"]["submissionPolicy"])
    total = db[RESPONSES].count_documents({"surveyId": survey["_id"], **scope})
    items = list(db[RESPONSES].aggregate(p.responses_list_pipeline(
        survey["_id"], scope, survey["settings"]["allowAnonymous"], offset, limit)))
    return {"survey_id": str(survey["_id"]), "scope": SCOPE_NAMES[survey["settings"]["submissionPolicy"]],
            "total": total, "offset": offset, "limit": limit, "items": items}
