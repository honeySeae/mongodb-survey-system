"""跳转条件的运算符表（设计文档 3.3），以及数字条件的区间运算。

运算符表只在这里定义一处：保存问卷时的合法性检查（survey_check）和
填写时的路径计算（第六步 jump）共用。第二阶段新增运算符或题型只需修改这里。
"""
import math
from dataclasses import dataclass

END = "END"

# 条件值的格式
OPTION = "option"              # 本题的一个选项 id
OPTION_LIST = "option_list"    # 本题的选项 id 数组（非空、不重复）
NUMBER = "number"              # 一个数字
NUMBER_RANGE = "number_range"  # [最小, 最大]，包含两端

# 题型 -> {运算符: 值的格式}；不在表中的题型（文本题）不支持跳转
OPERATORS: dict[str, dict[str, str]] = {
    "single_choice": {"eq": OPTION, "in": OPTION_LIST},
    "multiple_choice": {
        "contains": OPTION,
        "containsAny": OPTION_LIST,
        "containsAll": OPTION_LIST,
        "equals": OPTION_LIST,
    },
    "number": {
        "eq": NUMBER, "ne": NUMBER,
        "gt": NUMBER, "gte": NUMBER,
        "lt": NUMBER, "lte": NUMBER,
        "between": NUMBER_RANGE,
    },
}

VALUE_FORMAT_NAMES = {
    OPTION: "本题的一个选项 id",
    OPTION_LIST: "本题选项 id 组成的数组",
    NUMBER: "一个数字",
    NUMBER_RANGE: "[最小值, 最大值]",
}


def supports_logic(question_type: str) -> bool:
    return question_type in OPERATORS


def is_number(value) -> bool:
    """JSON 数字（int / float），不含布尔值，且为有限数。"""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


# ---------- 数字区间 ----------
@dataclass(frozen=True)
class Interval:
    """数轴上的一个区间；lo / hi 可以是 ±inf（此时对应端点视为开）。"""
    lo: float
    lo_closed: bool
    hi: float
    hi_closed: bool

    def is_empty(self) -> bool:
        return self.lo > self.hi or (self.lo == self.hi and not (self.lo_closed and self.hi_closed))

    def intersect(self, other: "Interval") -> "Interval":
        if self.lo > other.lo or (self.lo == other.lo and not self.lo_closed):
            lo, lo_closed = self.lo, self.lo_closed
        else:
            lo, lo_closed = other.lo, other.lo_closed
        if self.hi < other.hi or (self.hi == other.hi and not self.hi_closed):
            hi, hi_closed = self.hi, self.hi_closed
        else:
            hi, hi_closed = other.hi, other.hi_closed
        return Interval(lo, lo_closed, hi, hi_closed)

    def has_integer(self) -> bool:
        if self.is_empty():
            return False
        if math.isinf(self.lo) or math.isinf(self.hi):
            return True
        first = math.ceil(self.lo)
        if first == self.lo and not self.lo_closed:
            first += 1
        last = math.floor(self.hi)
        if last == self.hi and not self.hi_closed:
            last -= 1
        return first <= last


INF = math.inf
EVERYTHING = Interval(-INF, False, INF, False)


def number_condition_intervals(op: str, value) -> list[Interval]:
    """数字条件成立的取值范围（若干个不相交区间之并）。调用前 value 已通过格式检查。"""
    if op == "eq":
        return [Interval(value, True, value, True)]
    if op == "ne":
        return [Interval(-INF, False, value, False), Interval(value, False, INF, False)]
    if op == "gt":
        return [Interval(value, False, INF, False)]
    if op == "gte":
        return [Interval(value, True, INF, False)]
    if op == "lt":
        return [Interval(-INF, False, value, False)]
    if op == "lte":
        return [Interval(-INF, False, value, True)]
    if op == "between":
        return [Interval(value[0], True, value[1], True)]
    raise ValueError(f"不是数字运算符：{op}")


def intervals_overlap(a: list[Interval], b: list[Interval], integer_only: bool) -> bool:
    """两组区间是否有交集；integer_only 时要求交集中有整数。"""
    for x in a:
        for y in b:
            z = x.intersect(y)
            if (z.has_integer() if integer_only else not z.is_empty()):
                return True
    return False
