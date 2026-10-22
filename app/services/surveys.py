"""问卷管理的业务逻辑：创建、列表、详情、修改、删除、发布、关闭。

规则（2026-10-19 开发者确认，见 AI_LOG 第 14 条、设计文档 6.4）：
- 只能操作自己的问卷；别人的问卷与不存在的问卷一样返回 404
- 标题 1~100 字符，说明 0~1000 字符；截止时间必须带时区，设置时必须晚于当前时间
- 状态 draft -> published -> closed 单向流转；各状态可改的字段见 app/logic/survey_state.py
- 状态相关的写操作都使用条件更新，并发操作时只有一个成功
"""
import secrets
import string
from datetime import datetime

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.errors import AppError, Conflict, NotFound, ValidationFailed
from app.logic import survey_state as state
from app.logic.survey_check import check_survey
from app.repositories import responses as responses_repo
from app.repositories import surveys as surveys_repo
from app.utils import now_utc, parse_object_id, to_mongo_time

TITLE_MAX = 100
DESCRIPTION_MAX = 1000
SHORT_CODE_LENGTH = 6
SHORT_CODE_ALPHABET = string.ascii_letters + string.digits
SHORT_CODE_RETRIES = 5


def generate_short_code() -> str:
    return "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


def is_valid_short_code(code: str) -> bool:
    return len(code) == SHORT_CODE_LENGTH and all(c in SHORT_CODE_ALPHABET for c in code)


# ---------- 字段检查 ----------
def _check_title(title: str) -> list[dict]:
    t = title.strip()
    if not t:
        return [{"field": "title", "message": "标题不能为空"}]
    if len(t) > TITLE_MAX:
        return [{"field": "title", "message": f"标题最多 {TITLE_MAX} 个字符"}]
    return []


def _check_description(description: str) -> list[dict]:
    if len(description.strip()) > DESCRIPTION_MAX:
        return [{"field": "description", "message": f"说明最多 {DESCRIPTION_MAX} 个字符"}]
    return []


def _check_deadline(deadline: datetime | None, now: datetime) -> list[dict]:
    if deadline is not None and to_mongo_time(deadline) <= now:
        return [{"field": "deadline", "message": "截止时间必须晚于当前时间"}]
    return []


def _status_error(action_desc: str, required: str, current: str) -> Conflict:
    return Conflict("INVALID_STATUS",
                    f"只有{state.STATUS_NAMES[required]}的问卷可以{action_desc}"
                    f"（当前状态：{state.STATUS_NAMES[current]}）")


# ---------- 查询 ----------
def get_owned(db: Database, owner_id: ObjectId, survey_id: str) -> dict:
    """取自己的问卷；id 格式不对、不存在、不是自己的，都返回 404。"""
    oid = parse_object_id(survey_id)
    survey = surveys_repo.find_owned(db, oid, owner_id) if oid else None
    if survey is None:
        raise NotFound("SURVEY_NOT_FOUND", "问卷不存在")
    return survey


def list_surveys(db: Database, owner_id: ObjectId) -> list[dict]:
    """我的问卷列表，每项附带按统计口径计算的答卷数 responseCount。"""
    surveys = surveys_repo.list_by_owner(db, owner_id)
    counts = responses_repo.count_by_surveys(db, surveys)
    for s in surveys:
        s["responseCount"] = counts.get(s["_id"], 0)
    return surveys


# ---------- 创建 ----------
def create_survey(db: Database, owner_id: ObjectId, *, title: str, description: str | None,
                  allow_anonymous: bool, submission_policy: str,
                  deadline: datetime | None, short_code: str | None = None) -> dict:
    """创建问卷（草稿）。

    short_code 通常不传，由系统随机生成；只有脚本（如示例数据 scripts/seed_demo.py）会指定固定值，
    网页和接口不接受这个参数。指定的值已被其他问卷使用时返回 409，不会覆盖。
    """
    now = now_utc()
    description = description or ""
    errors = _check_title(title) + _check_description(description) + _check_deadline(deadline, now)
    if errors:
        raise ValidationFailed(errors)

    doc_base = {
        "ownerId": owner_id,
        "title": title.strip(),
        "description": description.strip(),
        "status": state.DRAFT,
        "settings": {
            "allowAnonymous": allow_anonymous,
            "submissionPolicy": submission_policy,
            "deadline": to_mongo_time(deadline) if deadline else None,
        },
        "version": 1,
        "questions": [],
        "createdAt": now,
        "updatedAt": now,
        "publishedAt": None,
        "closedAt": None,
    }
    if short_code is not None:
        if not is_valid_short_code(short_code):
            raise ValidationFailed([{"field": "shortCode",
                                     "message": f"链接代码应为 {SHORT_CODE_LENGTH} 位字母或数字"}])
        try:
            return surveys_repo.insert(db, {**doc_base, "shortCode": short_code})
        except DuplicateKeyError:
            raise Conflict("SHORT_CODE_TAKEN", f"链接代码 {short_code} 已被其他问卷使用")

    # shortCode 随机生成，极少数情况下与已有的重复，由唯一索引发现后重试
    for _ in range(SHORT_CODE_RETRIES):
        try:
            return surveys_repo.insert(db, {**doc_base, "shortCode": generate_short_code()})
        except DuplicateKeyError:
            continue
    raise AppError(500, "SHORT_CODE_EXHAUSTED", "生成问卷链接失败，请重试")


# ---------- 修改 ----------
# 接口字段名 -> 数据库中的路径
_FIELD_PATHS = {
    "title": "title",
    "description": "description",
    "allowAnonymous": "settings.allowAnonymous",
    "submissionPolicy": "settings.submissionPolicy",
    "deadline": "settings.deadline",
}


def _current_value(survey: dict, field: str):
    if field in ("title", "description"):
        return survey.get(field, "")
    return survey["settings"].get(field)


def update_survey(db: Database, owner_id: ObjectId, survey_id: str, changes: dict) -> dict:
    """修改问卷。changes 只包含请求中实际提交的字段（键为接口字段名）。

    与当前值相同的字段视为未修改，不受状态限制，便于前端整份提交设置。
    """
    survey = get_owned(db, owner_id, survey_id)
    now = now_utc()

    # 规范化提交的值，并检查格式
    normalized, errors = {}, []
    for field, value in changes.items():
        if field in ("title", "description", "allowAnonymous", "submissionPolicy") and value is None:
            errors.append({"field": field, "message": "不能为空"})
            continue
        if field == "title":
            errors += _check_title(value)
            value = value.strip()
        elif field == "description":
            errors += _check_description(value)
            value = value.strip()
        elif field == "deadline" and value is not None:
            value = to_mongo_time(value)
        normalized[field] = value
    if errors:
        raise ValidationFailed(errors)

    changed = {f: v for f, v in normalized.items() if v != _current_value(survey, f)}
    if not changed:
        return survey

    status = survey["status"]
    locked = state.locked_fields(status, set(changed))
    if locked:
        errors = [{"field": f, "message": state.lock_message(status, f)} for f in locked]
        raise Conflict("FIELD_LOCKED", errors[0]["message"], errors)

    # 只有真正修改截止时间时才要求晚于当前时间（未改动的旧截止时间即使已过也不报错）
    if "deadline" in changed:
        errors = _check_deadline(changed["deadline"], now)
        if errors:
            raise ValidationFailed(errors)

    set_fields = {_FIELD_PATHS[f]: v for f, v in changed.items()}
    set_fields["updatedAt"] = now
    updated = surveys_repo.update_if_status(db, survey["_id"], owner_id, status, set_fields)
    if updated is None:
        # 读取之后状态被其他请求改变（例如同时发布）
        raise Conflict("INVALID_STATUS", "问卷状态已变化，请刷新后重试")
    return updated


# ---------- 删除 ----------
def delete_survey(db: Database, owner_id: ObjectId, survey_id: str) -> None:
    survey = get_owned(db, owner_id, survey_id)
    if not state.can(survey["status"], "delete"):
        raise _status_error("删除", state.DRAFT, survey["status"])
    if not surveys_repo.delete_if_status(db, survey["_id"], owner_id, state.DRAFT):
        raise Conflict("INVALID_STATUS", "问卷状态已变化，请刷新后重试")


# ---------- 发布 / 关闭 ----------
def publish_survey(db: Database, owner_id: ObjectId, survey_id: str) -> dict:
    survey = get_owned(db, owner_id, survey_id)
    required, target = state.TRANSITIONS["publish"]
    if not state.can(survey["status"], "publish"):
        raise _status_error("发布", required, survey["status"])
    if not survey["questions"]:
        raise AppError(422, "NO_QUESTIONS", "问卷至少需要 1 道题才能发布")
    # 正常情况下题目每次保存都已检查过；这里再检查一次，防止数据被绕过接口写入
    check = check_survey(survey["questions"])
    if not check.ok:
        raise ValidationFailed(check.errors, "题目设置不合法，无法发布")
    now = now_utc()
    if state.is_expired(survey["settings"].get("deadline"), now):
        raise ValidationFailed([{"field": "deadline", "message": "截止时间已过，请先修改截止时间再发布"}])

    updated = surveys_repo.update_if_status(
        db, survey["_id"], owner_id, required,
        {"status": target, "publishedAt": now, "updatedAt": now},
        extra_filter={"questions.0": {"$exists": True}},
    )
    if updated is None:
        raise Conflict("INVALID_STATUS", "问卷状态已变化，请刷新后重试")
    return updated


def close_survey(db: Database, owner_id: ObjectId, survey_id: str) -> dict:
    survey = get_owned(db, owner_id, survey_id)
    required, target = state.TRANSITIONS["close"]
    if not state.can(survey["status"], "close"):
        raise _status_error("关闭", required, survey["status"])
    now = now_utc()
    updated = surveys_repo.update_if_status(
        db, survey["_id"], owner_id, required,
        {"status": target, "closedAt": now, "updatedAt": now},
    )
    if updated is None:
        raise Conflict("INVALID_STATUS", "问卷状态已变化，请刷新后重试")
    return updated
