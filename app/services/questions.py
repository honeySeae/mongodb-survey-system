"""题目编辑的业务逻辑：添加、修改、删除、调整顺序。

约定（2026-10-19 开发者确认，见 AI_LOG 第 16 条、设计文档 6.3 第 9~11 条）：
- 只有草稿可以修改题目
- 每次修改后对整份问卷做一次检查（app/logic/survey_check.py），不合法则拒绝本次修改
- 添加题目时不接受跳转规则；修改题目时整体替换，保留的选项带原 id
- 写回时带上读取时的 updatedAt 做条件更新，防止并发修改互相覆盖；
  请求可选带 expectedUpdatedAt，带了就与当前值比较
"""
import secrets
import string
from datetime import datetime, timedelta

from bson import ObjectId
from pymongo.database import Database

from app.errors import Conflict, NotFound, ValidationFailed
from app.logic import survey_state as state
from app.logic.survey_check import check_survey, find_references
from app.repositories import surveys as surveys_repo
from app.services.surveys import get_owned
from app.utils import now_utc, to_mongo_time

ID_ALPHABET = string.ascii_lowercase + string.digits
ID_LENGTH = 6


def new_id(prefix: str, used: set[str]) -> str:
    """生成问卷内唯一的 id（如 q_k3x9ab、o_a1b2c3），并加入 used。"""
    while True:
        candidate = prefix + "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if candidate not in used:
            used.add(candidate)
            return candidate


def _used_ids(questions: list[dict]) -> set[str]:
    used = set()
    for q in questions:
        used.add(q["id"])
        used.update(o["id"] for o in q.get("options") or [])
    return used


def _edit_conflict() -> Conflict:
    return Conflict("EDIT_CONFLICT", "问卷已被修改，请刷新后重试")


def _load_editable(db: Database, owner_id: ObjectId, survey_id: str,
                   expected_updated_at: datetime | None) -> dict:
    survey = get_owned(db, owner_id, survey_id)
    if not state.can(survey["status"], "edit_questions"):
        raise Conflict("INVALID_STATUS",
                       f"问卷{state.STATUS_NAMES[survey['status']]}，不能修改题目")
    if expected_updated_at is not None and to_mongo_time(expected_updated_at) != survey["updatedAt"]:
        raise _edit_conflict()
    return survey


def _save(db: Database, owner_id: ObjectId, survey: dict, questions: list[dict]) -> dict:
    """整体检查后写回题目数组。"""
    result = check_survey(questions)
    if not result.ok:
        raise ValidationFailed(result.errors, "题目设置不合法")
    # 新的 updatedAt 必须严格大于旧值，否则同一毫秒内的两次修改无法区分
    now = max(now_utc(), survey["updatedAt"] + timedelta(milliseconds=1))
    updated = surveys_repo.update_if_status(
        db, survey["_id"], owner_id, state.DRAFT,
        {"questions": questions, "updatedAt": now},
        extra_filter={"updatedAt": survey["updatedAt"]},
    )
    if updated is None:
        raise _edit_conflict()
    return updated


def _find_index(survey: dict, question_id: str) -> int:
    for i, q in enumerate(survey["questions"]):
        if q["id"] == question_id:
            return i
    raise NotFound("QUESTION_NOT_FOUND", "题目不存在")


def _normalize_validation(validation: dict | None) -> dict:
    v = dict(validation or {})
    v.setdefault("required", False)
    return v


# ---------- 添加 ----------
def add_question(db: Database, owner_id: ObjectId, survey_id: str, *, qtype: str, title: str,
                 options: list[dict] | None, validation: dict | None, position: int | None,
                 logic_given: bool, expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    if logic_given:
        raise ValidationFailed([{"field": "logic",
                                 "message": "添加题目时不能设置跳转规则，请添加后通过修改题目设置"}])
    questions = list(survey["questions"])
    if position is not None and not 1 <= position <= len(questions) + 1:
        raise ValidationFailed([{"field": "position",
                                 "message": f"position 应为 1~{len(questions) + 1}"}])

    used = _used_ids(questions)
    question = {"id": new_id("q_", used), "type": qtype, "title": title.strip()}
    if options is not None:
        question["options"] = [{"id": new_id("o_", used), "text": o["text"].strip()} for o in options]
    question["validation"] = _normalize_validation(validation)

    index = len(questions) if position is None else position - 1
    questions.insert(index, question)
    return _save(db, owner_id, survey, questions)


# ---------- 修改 ----------
def update_question(db: Database, owner_id: ObjectId, survey_id: str, question_id: str, *,
                    qtype: str, title: str, options: list[dict] | None, validation: dict | None,
                    logic: dict | None, expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    questions = list(survey["questions"])
    i = _find_index(survey, question_id)
    old_option_ids = {o["id"] for o in questions[i].get("options") or []}

    used = _used_ids(questions)
    question = {"id": question_id, "type": qtype, "title": title.strip()}
    if options is not None:
        new_options, errors, kept = [], [], set()
        for k, o in enumerate(options):
            oid = o.get("id")
            if oid is None:
                oid = new_id("o_", used)
            elif oid not in old_option_ids or oid in kept:
                errors.append({"field": f"options[{k}].id", "questionId": question_id,
                               "message": f"第 {k + 1} 个选项的 id {oid} 不是本题已有的选项（新增选项不要带 id）"})
                continue
            kept.add(oid)
            new_options.append({"id": oid, "text": o["text"].strip()})
        if errors:
            raise ValidationFailed(errors, "题目设置不合法")
        question["options"] = new_options
    question["validation"] = _normalize_validation(validation)
    if logic is not None:
        question["logic"] = {"rules": logic.get("rules", []),
                             "defaultNext": logic.get("defaultNext"),
                             **{k: v for k, v in logic.items() if k not in ("rules", "defaultNext")}}

    questions[i] = question
    return _save(db, owner_id, survey, questions)


# ---------- 删除 ----------
def delete_question(db: Database, owner_id: ObjectId, survey_id: str, question_id: str,
                    expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    i = _find_index(survey, question_id)
    refs = find_references(survey["questions"], question_id)
    if refs:
        errors = [{"field": "id", "questionId": question_id, "message": f"{r}跳转到这道题"} for r in refs]
        raise Conflict("QUESTION_REFERENCED", f"{refs[0]}跳转到这道题，请先修改该规则", errors)
    questions = survey["questions"][:i] + survey["questions"][i + 1:]
    return _save(db, owner_id, survey, questions)


# ---------- 调整顺序 ----------
def reorder_questions(db: Database, owner_id: ObjectId, survey_id: str, question_ids: list[str],
                      expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    by_id = {q["id"]: q for q in survey["questions"]}
    if len(question_ids) != len(by_id) or set(question_ids) != set(by_id):
        raise ValidationFailed([{"field": "questionIds",
                                 "message": "必须恰好包含问卷的全部题目 id，且不能重复"}])
    return _save(db, owner_id, survey, [by_id[qid] for qid in question_ids])
