"""答题路径计算（纯函数，不访问数据库）。对应设计文档 6.3。

compute_path(题目列表, 答案, 模式) 从第一题开始，按答案和跳转规则计算应经过的路径：
- 路径上的答案按 validation 校验并规范化（app/logic/validation.py）
- 选填题未作答：不匹配任何规则，走 defaultNext（为 null 时顺序下一题）
- 被跳过的题不校验、不保存；路径外的答案、问卷中不存在的题目 id 直接丢弃
- 遇到第一个错误（含必答题未答）就停下，只返回这一个错误

两种模式只在“答案中没有这道题”时不同：
- PREVIEW（填写中预览）：视为还没答到，停在这里，作为下一题返回
- SUBMIT（提交）：视为未作答
"""
from dataclasses import dataclass, field
from typing import Any

from app.logic import operators as ops
from app.logic.validation import check_answer

PREVIEW = "preview"
SUBMIT = "submit"


class PathError(Exception):
    """题目数据本身不合法（如往前跳）。保存时已检查，出现说明数据被绕过接口修改。"""


@dataclass
class PathResult:
    path: list[str] = field(default_factory=list)       # 经过的题目 id（含停下时所在的题）
    answers: list[dict] = field(default_factory=list)   # 路径上已作答的题 [{questionId, value}]（已规范化）
    errors: list[dict] = field(default_factory=list)    # 最多一个
    next_question_id: str | None = None                 # 预览模式：下一道要答的题
    finished: bool = False                              # 是否已走到结尾（END 或最后一题之后）且没有错误


def index_answers(items: list[dict]) -> tuple[dict[str, Any], list[str]]:
    """把 [{questionId, value}] 转为 {questionId: value}，同时返回重复出现的题目 id。"""
    answers, duplicates = {}, []
    for item in items:
        qid = item["questionId"]
        if qid in answers and qid not in duplicates:
            duplicates.append(qid)
        answers[qid] = item["value"]
    return answers, duplicates


def _next_index(question: dict, index: int, answered: bool, value, position: dict) -> int | None:
    """答完第 index 题后去哪：返回下一题的下标，None 表示结束。"""
    logic = question.get("logic") or {}
    target = None
    if answered:
        for rule in logic.get("rules") or []:
            when = rule["when"]
            if ops.evaluate(question["type"], when["op"], when["value"], value):
                target = rule["goto"]
                break
    if target is None:
        target = logic.get("defaultNext")
    if target is None:
        return index + 1
    if target == ops.END:
        return None
    if target not in position or position[target] <= index:
        raise PathError(f"第 {index + 1} 题的跳转目标 {target} 不存在或不在本题之后")
    return position[target]


def compute_path(questions: list[dict], answers: dict[str, Any], mode: str = SUBMIT) -> PathResult:
    result = PathResult()
    position = {q["id"]: i for i, q in enumerate(questions)}
    i = 0
    while i is not None and i < len(questions):
        q = questions[i]
        result.path.append(q["id"])
        if q["id"] not in answers and mode == PREVIEW:
            result.next_question_id = q["id"]
            return result

        check = check_answer(q, answers.get(q["id"]))
        if check.error:
            result.errors.append({"questionId": q["id"], "field": "value",
                                  "message": f"第 {i + 1} 题：{check.error}"})
            return result
        if check.answered:
            result.answers.append({"questionId": q["id"], "value": check.value})
        i = _next_index(q, i, check.answered, check.value, position)

    result.finished = True
    return result
