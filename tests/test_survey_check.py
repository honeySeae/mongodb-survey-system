"""第五步：整份问卷的跳转规则合法性检查与警告（纯函数，不访问数据库）。
对应设计文档 3.3、6.3（第 2、3、9 条）、6.5。
"""
import pytest

from app.logic import operators as ops
from app.logic.survey_check import check_survey, find_references


# ---------- 构造题目 ----------
def single(qid, options=("o_a", "o_b", "o_c"), rules=None, default=None, logic=True, **v):
    q = {"id": qid, "type": "single_choice", "title": f"题{qid}",
         "options": [{"id": o, "text": f"选项{o}"} for o in options],
         "validation": {"required": True, **v}}
    if logic:
        q["logic"] = {"rules": rules or [], "defaultNext": default}
    return q


def multi(qid, options=("o_m1", "o_m2", "o_m3", "o_m4"), rules=None, default=None, **v):
    return {"id": qid, "type": "multiple_choice", "title": f"题{qid}",
            "options": [{"id": o, "text": f"选项{o}"} for o in options],
            "validation": {"required": True, **v},
            "logic": {"rules": rules or [], "defaultNext": default}}


def number(qid, rules=None, default=None, **v):
    return {"id": qid, "type": "number", "title": f"题{qid}",
            "validation": {"required": True, **v},
            "logic": {"rules": rules or [], "defaultNext": default}}


def text(qid, **v):
    return {"id": qid, "type": "text", "title": f"题{qid}", "validation": {"required": False, **v}}


def rule(op, value, goto):
    return {"when": {"op": op, "value": value}, "goto": goto}


def errors_of(questions):
    return check_survey(questions).errors


def warnings_of(questions):
    return check_survey(questions).warnings


# ---------- 设计文档 3.4 的示例问卷 ----------
def design_example():
    return [
        single("q1", options=("o1", "o2"), rules=[rule("eq", "o2", "q5")]),
        multi("q2", options=("o3", "o4", "o5", "o6"), rules=[rule("contains", "o6", "q3")],
              default="q4", minSelect=1, maxSelect=3),
        text("q3", minLength=5, maxLength=200),
        number("q4", rules=[rule("eq", 0, "END")], min=0, max=50, integerOnly=True),
        text("q5", maxLength=500),
    ]


def test_design_example_passes_without_warnings():
    result = check_survey(design_example())
    assert result.errors == []
    assert result.warnings == []


def test_empty_survey_is_valid():
    assert check_survey([]).ok


# ---------- 每种运算符的合法值 ----------
@pytest.mark.parametrize("question", [
    single("q1", rules=[rule("eq", "o_a", "END")]),
    single("q1", rules=[rule("in", ["o_a", "o_b"], "END")]),
    multi("q1", rules=[rule("contains", "o_m1", "END")]),
    multi("q1", rules=[rule("containsAny", ["o_m1", "o_m2"], "END")]),
    multi("q1", rules=[rule("containsAll", ["o_m1", "o_m2"], "END")]),
    multi("q1", rules=[rule("equals", ["o_m1"], "END")]),
    number("q1", rules=[rule("eq", 3, "END")]),
    number("q1", rules=[rule("ne", 3, "END")]),
    number("q1", rules=[rule("gt", 3, "END")]),
    number("q1", rules=[rule("gte", 3.5, "END")]),
    number("q1", rules=[rule("lt", -2, "END")]),
    number("q1", rules=[rule("lte", 0, "END")]),
    number("q1", rules=[rule("between", [1, 5], "END")]),
    number("q1", rules=[rule("between", [5, 5], "END")]),
])
def test_valid_operator_values(question):
    assert errors_of([question]) == []


# ---------- 运算符与题型 ----------
@pytest.mark.parametrize("question, op", [
    (single("q1", rules=[rule("contains", "o_a", "END")]), "contains"),   # 多选的运算符
    (single("q1", rules=[rule("gt", 1, "END")]), "gt"),                    # 数字的运算符
    (multi("q1", rules=[rule("eq", "o_m1", "END")]), "eq"),                # 单选的运算符
    (multi("q1", rules=[rule("in", ["o_m1"], "END")]), "in"),
    (number("q1", rules=[rule("contains", 1, "END")]), "contains"),
    (number("q1", rules=[rule("like", 1, "END")]), "like"),
])
def test_operator_must_match_type(question, op):
    errs = errors_of([question])
    assert [e["field"] for e in errs] == ["logic.rules[0].when.op"]
    assert repr(op) in errs[0]["message"]


def test_text_question_cannot_have_logic():
    q = text("q1") | {"logic": {"rules": [], "defaultNext": None}}
    errs = errors_of([q])
    assert errs[0]["field"] == "logic"
    assert "不支持跳转" in errs[0]["message"]


# ---------- 条件值的格式 ----------
@pytest.mark.parametrize("question", [
    single("q1", rules=[rule("eq", "o_x", "END")]),                     # 不是本题的选项
    single("q1", rules=[rule("eq", ["o_a"], "END")]),                   # 应为单个 id
    single("q1", rules=[rule("in", [], "END")]),                        # 不能为空
    single("q1", rules=[rule("in", "o_a", "END")]),                     # 应为数组
    single("q1", rules=[rule("in", ["o_a", "o_a"], "END")]),            # 不能重复
    single("q1", rules=[rule("in", ["o_a", "o_zz"], "END")]),           # 包含不存在的选项
    multi("q1", rules=[rule("contains", "o_a", "END")]),                # 别的题的选项
    multi("q1", rules=[rule("containsAll", [], "END")]),
    multi("q1", rules=[rule("equals", ["o_m1", 2], "END")]),
    number("q1", rules=[rule("eq", "3", "END")]),                       # 字符串不当数字
    number("q1", rules=[rule("gt", True, "END")]),                      # 布尔值不当数字
    number("q1", rules=[rule("lt", None, "END")]),
    number("q1", rules=[rule("between", [5, 1], "END")]),               # 最小 > 最大
    number("q1", rules=[rule("between", [1], "END")]),
    number("q1", rules=[rule("between", [1, 2, 3], "END")]),
    number("q1", rules=[rule("between", 3, "END")]),
    number("q1", rules=[rule("between", [1, "5"], "END")]),
])
def test_invalid_values(question):
    errs = errors_of([question])
    assert [e["field"] for e in errs] == ["logic.rules[0].when.value"]


def test_option_from_other_question_rejected():
    """规则只能引用本题的选项，即使 id 在问卷中存在。"""
    qs = [single("q1", rules=[rule("eq", "o_other", "END")]),
          single("q2", options=("o_other",))]
    errs = errors_of(qs)
    assert errs[0]["questionId"] == "q1"
    assert "不是本题的选项" in errs[0]["message"]


# ---------- 规则结构 ----------
@pytest.mark.parametrize("bad_rule, field", [
    ({"when": {"op": "eq", "value": "o_a"}}, "logic.rules[0]"),                      # 缺 goto
    ({"goto": "END"}, "logic.rules[0]"),                                              # 缺 when
    ("eq o_a", "logic.rules[0]"),
    ({"when": {"op": "eq", "value": "o_a"}, "goto": "END", "note": 1}, "logic.rules[0]"),        # 多余字段
    ({"when": {"op": "eq", "value": "o_a", "x": 1}, "goto": "END"}, "logic.rules[0]"),
])
def test_rule_structure(bad_rule, field):
    q = single("q1")
    q["logic"]["rules"] = [bad_rule]
    assert field in [e["field"] for e in errors_of([q])]


def test_logic_extra_field_and_rules_type():
    q = single("q1")
    q["logic"] = {"rules": "nope", "defaultNext": None, "showIf": 1}
    assert {e["field"] for e in errors_of([q])} == {"logic.showIf", "logic.rules"}


def test_rule_count_limit():
    ok = single("q1", rules=[rule("eq", "o_a", "END")] * 50)
    too_many = single("q1", rules=[rule("eq", "o_a", "END")] * 51)
    assert errors_of([ok]) == []
    assert [e["field"] for e in errors_of([too_many])] == ["logic.rules"]


# ---------- 只能往后跳（6.3 第 2、3 条） ----------
def test_jump_forward_and_end_ok():
    qs = [single("q1", rules=[rule("eq", "o_a", "q3"), rule("eq", "o_b", "END")], default="q2"),
          text("q2"), text("q3")]
    assert errors_of(qs) == []


@pytest.mark.parametrize("target, expected", [
    ("q1", "目标是第 1 题"),
    ("q2", "目标是本题自己"),
])
def test_backward_or_self_jump_rejected(target, expected):
    qs = [text("q1"), single("q2", rules=[rule("eq", "o_a", target)]), text("q3")]
    errs = errors_of(qs)
    assert len(errs) == 1
    assert errs[0]["field"] == "logic.rules[0].goto"
    assert errs[0]["message"] == f"第 2 题第 1 条规则：只能跳转到后面的题目或 END（{expected}）"


def test_default_next_backward_rejected():
    qs = [text("q1"), single("q2", default="q1")]
    errs = errors_of(qs)
    assert [e["field"] for e in errs] == ["logic.defaultNext"]
    assert "第 2 题默认去向" in errs[0]["message"]


@pytest.mark.parametrize("target", ["q_missing", "end", None, 3])
def test_goto_target_must_exist(target):
    errs = errors_of([single("q1", rules=[rule("eq", "o_a", target)]), text("q2")])
    assert [e["field"] for e in errs] == ["logic.rules[0].goto"]
    assert "不存在" in errs[0]["message"]


def test_default_next_must_exist():
    assert [e["field"] for e in errors_of([single("q1", default="q_nope")])] == ["logic.defaultNext"]


def test_reorder_turns_forward_jump_into_backward():
    """调整顺序后，原本往后跳的规则变成往前跳，整体检查能发现。"""
    q1 = single("q1", rules=[rule("eq", "o_a", "q3")])
    assert errors_of([q1, text("q2"), text("q3")]) == []
    errs = errors_of([text("q3"), q1, text("q2")])
    assert errs[0]["message"] == "第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）"


def test_end_does_not_conflict_with_ids():
    """END 是保留字；系统生成的 id 以 q_ 开头，不会与之冲突。"""
    assert ops.END == "END"
    assert errors_of([single("q_aaaaaa", rules=[rule("eq", "o_a", "END")])]) == []


# ---------- id 唯一 ----------
def test_duplicate_ids_rejected():
    qs = [single("q1", options=("o_a", "o_b")), single("q2", options=("o_a", "o_c"))]
    assert any("重复" in e["message"] for e in errors_of(qs))
    assert any("重复" in e["message"] for e in errors_of([text("q1"), text("q1")]))


def test_question_count_limit():
    assert errors_of([text(f"q{i}") for i in range(100)]) == []
    assert errors_of([text(f"q{i}") for i in range(101)])[0]["field"] == "questions"


# ---------- 警告：规则重叠（6.5） ----------
def test_single_choice_overlap_warning():
    q = single("q1", rules=[rule("in", ["o_a", "o_b"], "q2"), rule("eq", "o_b", "END")])
    result = check_survey([q, text("q2")])
    assert result.ok
    assert len(result.warnings) == 1
    w = result.warnings[0]
    assert w["field"] == "logic.rules[1]"
    assert "第 1 条和第 2 条规则都包含选项「选项o_b」" in w["message"]


def test_single_choice_no_overlap_no_warning():
    q = single("q1", rules=[rule("eq", "o_a", "q2"), rule("in", ["o_b", "o_c"], "END")])
    assert warnings_of([q, text("q2")]) == []


@pytest.mark.parametrize("rules, overlap", [
    ([rule("gt", 10, "END"), rule("gte", 18, "q2")], True),
    ([rule("lt", 18, "END"), rule("gte", 18, "q2")], False),                  # 18 恰好分开
    ([rule("lte", 18, "END"), rule("gte", 18, "q2")], True),                  # 都含 18
    ([rule("between", [0, 10], "END"), rule("between", [10, 20], "q2")], True),
    ([rule("between", [0, 10], "END"), rule("between", [11, 20], "q2")], False),
    ([rule("eq", 5, "END"), rule("ne", 5, "q2")], False),
    ([rule("eq", 5, "END"), rule("ne", 6, "q2")], True),
    ([rule("ne", 5, "END"), rule("ne", 6, "q2")], True),
])
def test_number_overlap_warning(rules, overlap):
    result = check_survey([number("q1", rules=rules), text("q2")])
    assert result.ok
    assert any("有重叠" in w["message"] for w in result.warnings) is overlap


def test_number_overlap_ignored_when_no_integer_in_common():
    """只允许整数时，(10, 11) 之间没有整数，不算重叠。"""
    rules = [rule("gt", 10, "END"), rule("lt", 11, "q2")]
    assert any("有重叠" in w["message"] for w in warnings_of([number("q1", rules=rules), text("q2")]))
    assert not warnings_of([number("q1", rules=rules, integerOnly=True), text("q2")])


def test_multiple_choice_overlap_not_warned():
    """多选题的重叠无法避免（设计文档 6.3 第 1 条），不警告。"""
    q = multi("q1", rules=[rule("containsAll", ["o_m1", "o_m2"], "q2"), rule("contains", "o_m1", "END")])
    assert warnings_of([q, text("q2")]) == []


# ---------- 警告：永远不会命中的规则 ----------
@pytest.mark.parametrize("rules, v, never", [
    ([rule("gt", 120, "END")], {"min": 0, "max": 120}, True),
    ([rule("gte", 120, "END")], {"min": 0, "max": 120}, False),
    ([rule("lt", 0, "END")], {"min": 0}, True),
    ([rule("between", [200, 300], "END")], {"max": 150}, True),
    ([rule("eq", 2.5, "END")], {"integerOnly": True}, True),
    ([rule("between", [2.1, 2.9], "END")], {"integerOnly": True}, True),
    ([rule("eq", 2.5, "END")], {}, False),
    ([rule("ne", 5, "END")], {"min": 5, "max": 5}, True),
])
def test_number_rule_never_matches(rules, v, never):
    result = check_survey([number("q1", rules=rules, **v)])
    assert result.ok
    assert any("永远不会成立" in w["message"] for w in result.warnings) is never


@pytest.mark.parametrize("r, v, never", [
    (rule("equals", ["o_m1"], "END"), {"minSelect": 2, "maxSelect": 3}, True),
    (rule("equals", ["o_m1", "o_m2", "o_m3", "o_m4"], "END"), {"maxSelect": 3}, True),
    (rule("equals", ["o_m1", "o_m2"], "END"), {"minSelect": 2, "maxSelect": 2}, False),
    (rule("containsAll", ["o_m1", "o_m2", "o_m3"], "END"), {"maxSelect": 2}, True),
    (rule("containsAll", ["o_m1", "o_m2"], "END"), {"maxSelect": 2}, False),
    (rule("containsAny", ["o_m1", "o_m2", "o_m3"], "END"), {"maxSelect": 1}, False),
])
def test_multiple_choice_rule_never_matches(r, v, never):
    result = check_survey([multi("q1", rules=[r], **v)])
    assert result.ok
    assert any("永远不会成立" in w["message"] for w in result.warnings) is never


# ---------- 警告：永远不会显示的题目 ----------
def test_unreachable_question_warning():
    """第 1 题所有规则和默认去向都绕过了第 2 题。"""
    qs = [single("q1", rules=[rule("eq", "o_a", "q3")], default="q3"), text("q2"), text("q3")]
    result = check_survey(qs)
    assert result.ok
    assert [(w["questionId"], w["message"]) for w in result.warnings] == [
        ("q2", "第 2 题在任何情况下都不会被显示（前面的跳转都绕过了它）")]


def test_question_after_end_unreachable():
    qs = [single("q1", default="END"), text("q2")]
    assert [w["questionId"] for w in warnings_of(qs)] == ["q2"]


def test_reachable_through_some_branch_not_warned():
    qs = [single("q1", rules=[rule("eq", "o_a", "q3")]), text("q2"), text("q3")]
    assert warnings_of(qs) == []


def test_unreachable_chain():
    """不可达的题跳转到的后续题，如果没有别的路，也不可达。"""
    qs = [single("q1", default="q4"),
          single("q2", options=("o_x", "o_y"), rules=[rule("eq", "o_x", "q3")], default="q4"),
          text("q3"), text("q4")]
    result = check_survey(qs)
    assert result.ok
    assert [w["questionId"] for w in result.warnings] == ["q2", "q3"]


# ---------- 引用查询（删除题目前） ----------
def test_find_references():
    qs = [single("q1", rules=[rule("eq", "o_a", "q3")]), single("q2", default="q3"), text("q3")]
    assert find_references(qs, "q3") == ["第 1 题「题q1」的第 1 条规则", "第 2 题「题q2」的默认去向"]
    assert find_references(qs, "q2") == []


def test_errors_suppress_warnings():
    """有错误时不计算警告（例如目标不存在时无法分析可达性）。"""
    qs = [single("q1", rules=[rule("eq", "o_a", "q_x")], default="END"), text("q2")]
    result = check_survey(qs)
    assert not result.ok and result.warnings == []
