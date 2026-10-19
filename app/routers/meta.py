"""前端用的元数据：题型、运算符表、各项长度上限。

直接返回后端代码中的定义（运算符表来自 app/logic/operators.py），前端不再维护一份副本；
第二阶段新增题型或运算符时，前端的跳转规则编辑器自动就能看到。中文名称属于显示层，放在前端。
不含敏感信息，不需要登录。
"""
from fastapi import APIRouter

from app.logic import operators as ops
from app.logic import question_rules as qr
from app.logic import survey_check as sc
from app.schemas.fill import MAX_ANSWERS
from app.services import surveys as survey_service

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta")
def meta() -> dict:
    return {
        "questionTypes": list(qr.QUESTION_TYPES),
        "validationFields": {t: sorted(fields) for t, fields in qr.VALIDATION_FIELDS.items()},
        "operators": ops.OPERATORS,          # 题型 -> {运算符: 值的格式}；文本题不在其中（不支持跳转）
        "end": ops.END,
        "limits": {
            "surveyTitleMax": survey_service.TITLE_MAX,
            "descriptionMax": survey_service.DESCRIPTION_MAX,
            "questionTitleMax": qr.TITLE_MAX,
            "optionsMax": qr.OPTIONS_MAX,
            "optionTextMax": qr.OPTION_TEXT_MAX,
            "maxLengthLimit": qr.MAX_LENGTH_LIMIT,
            "questionsMax": sc.MAX_QUESTIONS,
            "rulesMax": sc.MAX_RULES,
            "answersMax": MAX_ANSWERS,
        },
    }
