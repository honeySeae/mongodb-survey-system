"""问卷相关的请求/响应模型。

这里只约束类型；标题长度、截止时间是否在未来等规则在 app/services/surveys.py 中检查。
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, StrictBool

from app.schemas.common import CamelModel

SubmissionPolicy = Literal["once", "latest", "all"]


class SurveyCreate(CamelModel):
    title: str
    description: str | None = None
    allow_anonymous: StrictBool = False
    submission_policy: SubmissionPolicy = "once"
    deadline: AwareDatetime | None = None  # 必须带时区；null 表示不限


class SurveyUpdate(CamelModel):
    """只提交要修改的字段；deadline 显式传 null 表示改为不限。"""
    title: str | None = None
    description: str | None = None
    allow_anonymous: StrictBool | None = None
    submission_policy: SubmissionPolicy | None = None
    deadline: AwareDatetime | None = None


class SettingsOut(CamelModel):
    allow_anonymous: bool
    submission_policy: str
    deadline: datetime | None


class SurveySummary(CamelModel):
    """列表中的一项（不含题目）。"""
    id: str
    short_code: str
    url: str
    title: str
    status: str
    is_expired: bool
    settings: SettingsOut
    question_count: int
    response_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    closed_at: datetime | None


class SurveyOut(CamelModel):
    """问卷详情（创建者视角，含题目）。"""
    id: str
    short_code: str
    url: str
    title: str
    description: str
    status: str
    is_expired: bool
    settings: SettingsOut
    version: int
    questions: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    closed_at: datetime | None
