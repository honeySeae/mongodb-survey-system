"""填写问卷的业务逻辑：获取问卷、路径预览、提交。对应设计文档 6.1、6.2、6.3、6.4。

约定（2026-10-19 开发者确认，见 AI_LOG 第 18 条）：
- 草稿只有创建者能预览（含路径预览），不能提交；已关闭、已过期时获取问卷返回提示但不含题目
- 填写者看不到跳转规则和内部字段（题目字段白名单）
- 提交时后端完整重算路径并校验（app/logic/jump.py），保存规范化后的答案
- 三种提交策略的写入顺序见设计文档 6.2；第 ③ 步冲突时先撤销刚插入的答卷再返回 409
"""
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.errors import AppError, Conflict, NotFound, ValidationFailed
from app.logic import survey_state as state
from app.logic.jump import PREVIEW, SUBMIT, PathError, PathResult, compute_path, index_answers
from app.repositories import responses as responses_repo
from app.repositories import surveys as surveys_repo
from app.utils import now_utc

# 填写者能看到的题目字段（白名单）：不含跳转规则 logic
RESPONDENT_QUESTION_FIELDS = ("id", "type", "title", "options", "validation")

NOT_PUBLISHED = "问卷尚未发布"
CLOSED = "问卷已关闭，不再接受填写"
EXPIRED = "问卷已截止，不再接受填写"
ONCE_SUBMITTED = "你已经填写过这份问卷（每人只能填写一次）"


def _load(db: Database, short_code: str, user_id: ObjectId) -> tuple[dict, bool]:
    """按 shortCode 取问卷，返回 (问卷, 是否创建者)。草稿对非创建者不可见。"""
    survey = surveys_repo.find_by_short_code(db, short_code)
    if survey is None:
        raise NotFound("SURVEY_NOT_FOUND", "问卷不存在")
    is_owner = survey["ownerId"] == user_id
    if survey["status"] == state.DRAFT and not is_owner:
        raise NotFound("SURVEY_NOT_PUBLISHED", NOT_PUBLISHED)
    return survey, is_owner


def _closed_reason(survey: dict) -> tuple[str, str] | None:
    """不接受填写的原因 (错误码, 提示)；正在收集时返回 None。"""
    status, deadline = survey["status"], survey["settings"].get("deadline")
    if status == state.DRAFT:
        return "SURVEY_NOT_PUBLISHED", NOT_PUBLISHED
    if status == state.CLOSED:
        return "SURVEY_CLOSED", CLOSED
    if state.is_expired(deadline, now_utc()):
        return "SURVEY_EXPIRED", EXPIRED
    return None


def _respondent_questions(survey: dict) -> list[dict]:
    return [{k: q[k] for k in RESPONDENT_QUESTION_FIELDS if k in q} for q in survey["questions"]]


def _index_or_reject(survey: dict, items: list[dict]) -> dict:
    answers, duplicates = index_answers(items)
    if duplicates:
        position = {q["id"]: i for i, q in enumerate(survey["questions"])}
        raise ValidationFailed([
            {"field": "answers", "questionId": qid,
             "message": (f"第 {position[qid] + 1} 题" if qid in position else f"题目 {qid} ")
                        + "的答案出现了多次"}
            for qid in duplicates])
    return answers


def _compute(survey: dict, answers: dict, mode: str) -> PathResult:
    try:
        return compute_path(survey["questions"], answers, mode)
    except PathError:
        raise AppError(500, "SURVEY_DATA_INVALID", "问卷数据异常，请联系问卷创建者")


# ---------- 获取问卷 ----------
def get_for_respondent(db: Database, short_code: str, user_id: ObjectId) -> dict:
    survey, is_owner = _load(db, short_code, user_id)
    reason = _closed_reason(survey)
    preview = survey["status"] == state.DRAFT  # 能走到这里说明是创建者
    accepting = reason is None
    policy = survey["settings"]["submissionPolicy"]

    summary = responses_repo.submission_summary(db, survey["_id"], user_id)
    can_submit, why_not = accepting, (reason[1] if reason else None)
    if accepting and policy == "once" and summary["count"] > 0:
        can_submit, why_not = False, ONCE_SUBMITTED

    latest_answers = None
    if policy == "latest":
        latest = responses_repo.find_latest_of(db, survey["_id"], user_id)
        latest_answers = latest["answers"] if latest else None

    notice = None
    if preview:
        notice = "预览模式：问卷尚未发布，不能提交"
    elif reason:
        notice = reason[1]

    return {
        "survey": survey,
        "is_owner": is_owner,
        "preview": preview,
        "accepting": accepting,
        "notice": notice,
        # 已关闭、已过期时不返回题目；草稿预览和正在收集时返回
        "questions": _respondent_questions(survey) if (accepting or preview) else None,
        "my_submission": {
            "count": summary["count"],
            "last_submitted_at": summary["last"],
            "can_submit": can_submit,
            "reason": why_not,
            "latest_answers": latest_answers,
        },
    }


# ---------- 路径预览 ----------
def preview_path(db: Database, short_code: str, user_id: ObjectId, items: list[dict]) -> PathResult:
    survey, _ = _load(db, short_code, user_id)
    reason = _closed_reason(survey)
    if reason and survey["status"] != state.DRAFT:  # 草稿（创建者）允许预览以测试跳转
        raise Conflict(*reason)
    return _compute(survey, _index_or_reject(survey, items), PREVIEW)


# ---------- 提交 ----------
def submit(db: Database, short_code: str, user_id: ObjectId, items: list[dict]) -> dict:
    survey, _ = _load(db, short_code, user_id)
    reason = _closed_reason(survey)
    if reason:
        raise Conflict(*reason)

    result = _compute(survey, _index_or_reject(survey, items), SUBMIT)
    if result.errors:
        raise ValidationFailed(result.errors, "答案不合法")

    doc = {
        "surveyId": survey["_id"],
        "surveyVersion": survey["version"],
        "respondentId": user_id,
        "isLatest": False,
        "submittedAt": now_utc(),
        "answers": result.answers,
    }
    if survey["settings"]["submissionPolicy"] == "once":
        _submit_once(db, survey, user_id, doc)
    else:
        _submit_with_latest_switch(db, survey, user_id, doc)
    return doc


def _submit_once(db: Database, survey: dict, user_id: ObjectId, doc: dict) -> None:
    """once：直接插入 isLatest: true；已填写过则拒绝（先查询给出友好提示，索引是最终保证）。"""
    if responses_repo.find_latest_of(db, survey["_id"], user_id) is not None:
        raise Conflict("ALREADY_SUBMITTED", ONCE_SUBMITTED)
    doc["isLatest"] = True
    try:
        doc["_id"] = responses_repo.insert(db, doc)
    except DuplicateKeyError:
        doc.pop("_id", None)
        raise Conflict("ALREADY_SUBMITTED", ONCE_SUBMITTED)


def _submit_with_latest_switch(db: Database, survey: dict, user_id: ObjectId, doc: dict) -> None:
    """latest / all：三步写入（设计文档 6.2）。"""
    doc["_id"] = responses_repo.insert(db, doc)                                # ① isLatest: false
    responses_repo.unset_other_latest(db, survey["_id"], user_id, doc["_id"])  # ② 旧的置为 false
    try:
        responses_repo.mark_latest(db, doc["_id"])                             # ③ 新的置为 true
    except DuplicateKeyError:
        # 同一用户的另一份提交抢先成为最新：撤销本次插入，使 409 表示“没有保存”（设计文档 6.2 修正）
        responses_repo.delete(db, doc["_id"])
        raise Conflict("SUBMIT_CONFLICT", "检测到同时提交，本次提交未保存，请稍后重试")
    doc["isLatest"] = True
