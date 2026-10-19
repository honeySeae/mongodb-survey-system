"""统计用的聚合管道（只构造管道，不执行）。对应设计文档 6.1、6.7 及“统计聚合管道”一节。

所有按题统计的管道共用前三步（question_answers_stages）：
    $match 问卷 + 统计口径 + 答了这道题  ->  $unwind answers  ->  $match 这道题的答案
之后按题型接不同的阶段。这得益于答卷的 answers 采用 {questionId, value} 数组（属性模式）。

匿名问卷（anonymous=True）的管道不包含 $lookup，也不输出 respondentId：
“不展示填写人”在数据库查询这一层就得到保证。
"""
from bson import ObjectId

from app.db import USERS


def scoped_match(survey_id: ObjectId, scope: dict) -> dict:
    """问卷 + 统计口径（scope 来自 repositories.responses.scope_filter）。"""
    return {"$match": {"surveyId": survey_id, **scope}}


def question_answers_stages(survey_id: ObjectId, scope: dict, question_id: str) -> list[dict]:
    """按题统计的公共前三步：每条输出是“一份答卷中这道题的答案”。"""
    return [
        # ① 只取这份问卷、口径内、答了这道题的答卷（可使用 answers.questionId 等索引）
        {"$match": {"surveyId": survey_id, **scope, "answers.questionId": question_id}},
        # ② 把答案数组拆开，每个答案成为一条
        {"$unwind": "$answers"},
        # ③ 只保留这道题的答案
        {"$match": {"answers.questionId": question_id}},
    ]


def totals_stages() -> list[dict]:
    """答卷数和作答人数：先按填写人分组，再数有几组、各组相加。

    不用 $addToSet 收集所有填写人再求数组长度：人数很多时该数组可能超过单个文档 16MB 上限。
    """
    return [
        {"$group": {"_id": "$respondentId", "n": {"$sum": 1}}},
        {"$group": {"_id": None, "respondentCount": {"$sum": 1}, "answerCount": {"$sum": "$n"}}},
        {"$project": {"_id": 0, "respondentCount": 1, "answerCount": 1}},
    ]


def items_stages(anonymous: bool, skip: int, limit: int) -> list[dict]:
    """填空题内容列表（新的在前、分页）。非匿名时用 $lookup 取用户名，匿名时不包含这一步。"""
    stages = [
        {"$sort": {"submittedAt": -1, "_id": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    project = {"_id": 0, "value": "$answers.value", "submittedAt": 1}
    if not anonymous:
        stages.append({"$lookup": {
            "from": USERS, "localField": "respondentId", "foreignField": "_id",
            # 只取用户名：密码哈希等字段不会进入管道
            "pipeline": [{"$project": {"_id": 0, "username": 1}}],
            "as": "respondent",
        }})
        project["username"] = {"$first": "$respondent.username"}
    stages.append({"$project": project})
    return stages


# ---------- 各题型 ----------
def choice_question_pipeline(survey_id: ObjectId, scope: dict, question_id: str,
                             multiple: bool) -> list[dict]:
    """单选：各选项人数；多选：各选项被选次数（先把选项数组再 $unwind 一次）。"""
    by_option = [{"$unwind": "$answers.value"}] if multiple else []
    by_option.append({"$group": {"_id": "$answers.value", "count": {"$sum": 1}}})
    return question_answers_stages(survey_id, scope, question_id) + [
        {"$facet": {"byOption": by_option, "totals": totals_stages()}},
    ]


def text_question_pipeline(survey_id: ObjectId, scope: dict, question_id: str,
                           anonymous: bool, skip: int, limit: int) -> list[dict]:
    """文本：内容列表 + 答卷数、作答人数。"""
    return question_answers_stages(survey_id, scope, question_id) + [
        {"$facet": {"items": items_stages(anonymous, skip, limit), "totals": totals_stages()}},
    ]


def number_question_pipeline(survey_id: ObjectId, scope: dict, question_id: str,
                             anonymous: bool, skip: int, limit: int) -> list[dict]:
    """数字：内容列表 + 平均值（数值类型存储，$avg 直接计算）+ 答卷数、作答人数。"""
    return question_answers_stages(survey_id, scope, question_id) + [
        {"$facet": {
            "items": items_stages(anonymous, skip, limit),
            "totals": totals_stages(),
            "average": [{"$group": {"_id": None, "value": {"$avg": "$answers.value"}}}],
        }},
    ]


# ---------- 问卷层面 ----------
def survey_totals_pipeline(survey_id: ObjectId, scope: dict) -> list[dict]:
    """口径内的总答卷数和总填写人数。"""
    return [
        scoped_match(survey_id, scope),
        {"$group": {"_id": "$respondentId", "n": {"$sum": 1}}},
        {"$group": {"_id": None, "respondents": {"$sum": 1}, "responses": {"$sum": "$n"}}},
    ]


def responses_list_pipeline(survey_id: ObjectId, scope: dict, anonymous: bool,
                            skip: int, limit: int) -> list[dict]:
    """答卷列表（口径与统计一致，新的在前、分页）。匿名时不含填写人。"""
    stages = [
        scoped_match(survey_id, scope),
        {"$sort": {"submittedAt": -1, "_id": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    project = {"_id": 0, "id": {"$toString": "$_id"}, "submittedAt": 1, "answers": 1}
    if not anonymous:
        stages.append({"$lookup": {
            "from": USERS, "localField": "respondentId", "foreignField": "_id",
            "pipeline": [{"$project": {"_id": 0, "username": 1}}],
            "as": "respondent",
        }})
        project["username"] = {"$first": "$respondent.username"}
    stages.append({"$project": project})
    return stages
