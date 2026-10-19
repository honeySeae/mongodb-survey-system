"""填写问卷接口的请求/响应模型。答案内容的校验在 app/logic/validation.py 中完成。"""
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import CamelModel
from app.schemas.questions import StrictCamelModel
from app.schemas.surveys import SettingsOut

MAX_ANSWERS = 200


class AnswerIn(StrictCamelModel):
    question_id: str
    value: Any  # 必须提交，null 表示未作答；类型随题型不同


class AnswersRequest(StrictCamelModel):
    answers: list[AnswerIn] = Field(max_length=MAX_ANSWERS)


class MySubmission(CamelModel):
    count: int                                   # 本人在该问卷上的提交次数
    last_submitted_at: datetime | None
    can_submit: bool
    reason: str | None                           # 不能提交的原因
    latest_answers: list[dict[str, Any]] | None  # latest 策略下本人最新一份答案，用于预填


class RespondentSurveyOut(CamelModel):
    """填写者看到的问卷：不含 ownerId 等内部字段，题目不含跳转规则。"""
    short_code: str
    title: str
    description: str
    settings: SettingsOut
    status: str
    is_expired: bool
    accepting: bool                              # 是否正在接受填写
    notice: str | None                           # 给填写者的提示（已关闭、已截止、预览模式）
    is_owner: bool
    preview: bool                                # 创建者预览草稿
    questions: list[dict[str, Any]] | None       # 已关闭、已过期时为 null
    my_submission: MySubmission


class PathOut(CamelModel):
    path: list[str]
    next_question_id: str | None
    finished: bool
    errors: list[dict[str, Any]]


class SubmitOut(CamelModel):
    id: str
    submitted_at: datetime
    is_latest: bool
    answers: list[dict[str, Any]]                # 实际保存的（规范化后、仅路径上的）答案
