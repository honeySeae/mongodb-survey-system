"""单道题答案的校验与规范化（纯函数，不访问数据库）。对应设计文档 3.2、6.6。

check_answer(题目, 原始答案) 返回 AnswerCheck：
- answered=False：未作答（null、空白文本、空数组）；必答题此时带错误
- answered=True：value 为规范化后的答案（去首尾空白的文本、按选项顺序排列的多选、3.0 -> 3）
- error 不为空：答案不合法，message 不含“第 N 题”前缀（由调用方加上）
"""
from dataclasses import dataclass
from typing import Any

from app.logic.operators import is_number

# MongoDB 能存储的最大整数类型是 64 位有符号整数（设计文档 6.6）
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


@dataclass(frozen=True)
class AnswerCheck:
    answered: bool
    value: Any = None
    error: str | None = None


def _fmt(n) -> str:
    """数字在提示中的写法：3.0 显示为 3。"""
    return str(int(n)) if isinstance(n, float) and n.is_integer() else str(n)


def _is_blank(question_type: str, raw) -> bool:
    if raw is None:
        return True
    if question_type == "text" and isinstance(raw, str) and not raw.strip():
        return True
    if question_type == "multiple_choice" and isinstance(raw, list) and not raw:
        return True
    return False


def check_answer(question: dict, raw) -> AnswerCheck:
    qtype = question["type"]
    v = question.get("validation") or {}
    if _is_blank(qtype, raw):
        return AnswerCheck(False, error="此题为必答题" if v.get("required") else None)

    checker = {
        "single_choice": _check_single,
        "multiple_choice": _check_multiple,
        "text": _check_text,
        "number": _check_number,
    }[qtype]
    value, error = checker(question, v, raw)
    if error:
        return AnswerCheck(True, error=error)
    return AnswerCheck(True, value=value)


def _check_single(question: dict, v: dict, raw):
    if not isinstance(raw, str):
        return None, "应选择一个选项"
    if raw not in {o["id"] for o in question["options"]}:
        return None, "选择的不是本题的选项"
    return raw, None


def _check_multiple(question: dict, v: dict, raw):
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        return None, "应为选项 id 组成的数组"
    if len(set(raw)) != len(raw):
        return None, "选项不能重复"
    order = [o["id"] for o in question["options"]]
    if any(x not in order for x in raw):
        return None, "包含不是本题的选项"
    n = len(raw)
    lo = v.get("minSelect", 1 if v.get("required") else None)
    hi = v.get("maxSelect")
    if lo is not None and hi is not None and lo == hi and n != lo:
        return None, f"必须选择 {lo} 项（当前选了 {n} 项）"
    if lo is not None and n < lo:
        return None, f"至少选择 {lo} 项（当前选了 {n} 项）"
    if hi is not None and n > hi:
        return None, f"最多选择 {hi} 项（当前选了 {n} 项）"
    chosen = set(raw)
    return [oid for oid in order if oid in chosen], None  # 按题目中选项的顺序保存


def _check_text(question: dict, v: dict, raw):
    if not isinstance(raw, str):
        return None, "应填写文字"
    text = raw.strip()
    n = len(text)  # Unicode 码点数：汉字、字母各算 1 个
    if "minLength" in v and n < v["minLength"]:
        return None, f"至少 {v['minLength']} 个字（当前 {n} 个）"
    if "maxLength" in v and n > v["maxLength"]:
        return None, f"最多 {v['maxLength']} 个字（当前 {n} 个）"
    return text, None


def _check_number(question: dict, v: dict, raw):
    if not is_number(raw):  # 拒绝字符串、布尔值、NaN、Infinity
        return None, "应填写数字"
    value = raw
    if v.get("integerOnly"):
        if isinstance(value, float):
            if not value.is_integer():
                return None, "必须为整数"
            value = int(value)  # 3.0 -> 3
    if isinstance(value, int) and not INT64_MIN <= value <= INT64_MAX:
        return None, f"数值超出允许范围（整数必须在 {INT64_MIN} ~ {INT64_MAX} 之间）"
    if "min" in v and value < v["min"]:
        return None, f"不能小于 {_fmt(v['min'])}"
    if "max" in v and value > v["max"]:
        return None, f"不能大于 {_fmt(v['max'])}"
    return value, None

