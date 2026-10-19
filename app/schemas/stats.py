"""统计与答卷列表的响应模型。

按题型只返回相关字段（路由使用 response_model_exclude_unset）：
选择题有 options；填空题有 items、itemsTotal；数字题另有 average。
items 中的每一项由聚合管道直接产生：匿名问卷没有 username 字段。
"""
from typing import Any

from app.schemas.common import CamelModel


class OptionCount(CamelModel):
    id: str
    text: str
    count: int


class QuestionStats(CamelModel):
    question_id: str
    type: str
    title: str
    answer_count: int          # 答卷数（口径内答了这道题的答卷数）
    respondent_count: int      # 作答人数（按填写人去重；匿名问卷也返回数字）
    options: list[OptionCount] | None = None
    items: list[dict[str, Any]] | None = None
    items_total: int | None = None
    average: float | None = None


class SurveyStatsHeader(CamelModel):
    survey_id: str
    title: str
    status: str
    allow_anonymous: bool
    submission_policy: str
    scope: str                 # 统计口径说明
    total_responses: int
    total_respondents: int


class SurveyStatsOut(SurveyStatsHeader):
    questions: list[QuestionStats]


class QuestionStatsOut(SurveyStatsHeader):
    question: QuestionStats
    offset: int
    limit: int


class ResponsesPage(CamelModel):
    survey_id: str
    scope: str
    total: int
    offset: int
    limit: int
    items: list[dict[str, Any]]   # {id, submittedAt, answers[, username]}
