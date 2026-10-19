"""第六步：答题路径计算（纯函数，不访问数据库）。对应设计文档 6.3。"""
import pytest

from app.logic import operators as ops
from app.logic.jump import PREVIEW, SUBMIT, PathError, compute_path, index_answers
from app.logic.survey_check import check_survey


# ---------- 构造题目 ----------
def single(qid, opts=("a", "b", "c"), rules=(), default=None, required=True):
    return {"id": qid, "type": "single_choice", "title": qid,
            "options": [{"id": f"{qid}_{o}", "text": o} for o in opts],
            "validation": {"required": required},
            "logic": {"rules": list(rules), "defaultNext": default}}


def multi(qid, opts=("a", "b", "c", "d"), rules=(), default=None, required=True, **v):
    return {"id": qid, "type": "multiple_choice", "title": qid,
            "options": [{"id": f"{qid}_{o}", "text": o} for o in opts],
            "validation": {"required": required, **v},
            "logic": {"rules": list(rules), "defaultNext": default}}


def number(qid, rules=(), default=None, required=True, **v):
    return {"id": qid, "type": "number", "title": qid,
            "validation": {"required": required, **v},
            "logic": {"rules": list(rules), "defaultNext": default}}


def text(qid, required=False, **v):
    return {"id": qid, "type": "text", "title": qid, "validation": {"required": required, **v}}


def rule(op, value, goto):
    return {"when": {"op": op, "value": value}, "goto": goto}


def path_of(questions, answers, mode=SUBMIT):
    r = compute_path(questions, answers, mode)
    assert r.errors == [], r.errors
    return r.path


# ---------- 运算符表一致性 ----------
def test_evaluators_cover_every_operator():
    """判断函数与运算符表完全对应：新增运算符时两处必须同时修改。"""
    assert {t: set(o) for t, o in ops.EVALUATORS.items()} == {t: set(o) for t, o in ops.OPERATORS.items()}


# ---------- 每个运算符：成立 / 不成立 ----------
@pytest.mark.parametrize("qtype, op, value, answer, expected", [
    ("single_choice", "eq", "o1", "o1", True),
    ("single_choice", "eq", "o1", "o2", False),
    ("single_choice", "in", ["o1", "o2"], "o2", True),
    ("single_choice", "in", ["o1", "o2"], "o3", False),
    ("multiple_choice", "contains", "o1", ["o1", "o2"], True),
    ("multiple_choice", "contains", "o1", ["o2"], False),
    ("multiple_choice", "containsAny", ["o1", "o3"], ["o2", "o3"], True),
    ("multiple_choice", "containsAny", ["o1", "o3"], ["o2", "o4"], False),
    ("multiple_choice", "containsAll", ["o1", "o2"], ["o1", "o2", "o3"], True),
    ("multiple_choice", "containsAll", ["o1", "o2"], ["o1", "o3"], False),
    ("multiple_choice", "equals", ["o1", "o2"], ["o2", "o1"], True),       # 不看顺序
    ("multiple_choice", "equals", ["o1", "o2"], ["o1", "o2", "o3"], False),
    ("multiple_choice", "equals", ["o1", "o2"], ["o1"], False),
    ("number", "eq", 3, 3.0, True),                                        # 3 与 3.0 相等
    ("number", "eq", 3, 4, False),
    ("number", "ne", 3, 4, True),
    ("number", "ne", 3, 3, False),
    ("number", "gt", 18, 19, True),
    ("number", "gt", 18, 18, False),
    ("number", "gte", 18, 18, True),
    ("number", "gte", 18, 17.9, False),
    ("number", "lt", 0, -1, True),
    ("number", "lt", 0, 0, False),
    ("number", "lte", 0, 0, True),
    ("number", "lte", 0, 0.1, False),
    ("number", "between", [10, 20], 10, True),                             # 包含两端
    ("number", "between", [10, 20], 20, True),
    ("number", "between", [10, 20], 15.5, True),
    ("number", "between", [10, 20], 9.99, False),
    ("number", "between", [10, 20], 21, False),
])
def test_operator_semantics(qtype, op, value, answer, expected):
    assert ops.evaluate(qtype, op, value, answer) is expected


# ---------- 规则命中与默认去向 ----------
def three_after(q):
    return [q, text("q2"), text("q3"), text("q4")]


def test_no_logic_goes_sequentially():
    qs = [text("q1"), text("q2"), text("q3")]
    r = compute_path(qs, {"q1": "x", "q3": "z"})
    assert r.path == ["q1", "q2", "q3"] and r.finished


def test_rule_hit_jumps():
    qs = three_after(single("q1", rules=[rule("eq", "q1_b", "q4")]))
    assert path_of(qs, {"q1": "q1_b"}) == ["q1", "q4"]


def test_no_rule_hit_without_default_goes_next():
    qs = three_after(single("q1", rules=[rule("eq", "q1_b", "q4")]))
    assert path_of(qs, {"q1": "q1_a"}) == ["q1", "q2", "q3", "q4"]


def test_no_rule_hit_with_default_next():
    qs = three_after(single("q1", rules=[rule("eq", "q1_b", "q4")], default="q3"))
    assert path_of(qs, {"q1": "q1_a"}) == ["q1", "q3", "q4"]


def test_first_matching_rule_wins():
    """多条规则同时成立时按顺序取第一条（设计文档 6.3 第 1 条）。"""
    rules = [rule("containsAll", ["q1_a", "q1_b"], "q4"), rule("contains", "q1_a", "q3")]
    qs = three_after(multi("q1", rules=rules))
    assert path_of(qs, {"q1": ["q1_a", "q1_b"]}) == ["q1", "q4"]   # 两条都成立，取第一条
    assert path_of(qs, {"q1": ["q1_a"]}) == ["q1", "q3", "q4"]      # 只有第二条成立


def test_first_matching_rule_wins_number_overlap():
    rules = [rule("gte", 18, "q3"), rule("between", [16, 20], "q4")]
    qs = three_after(number("q1", rules=rules))
    assert path_of(qs, {"q1": 19}) == ["q1", "q3", "q4"]
    assert path_of(qs, {"q1": 17}) == ["q1", "q4"]


@pytest.mark.parametrize("where", ["rule", "default"])
def test_goto_end(where):
    q = single("q1", rules=[rule("eq", "q1_a", "END")] if where == "rule" else [], default=None if where == "rule" else "END")
    r = compute_path(three_after(q), {"q1": "q1_a", "q2": "多余"})
    assert r.path == ["q1"] and r.finished
    assert r.answers == [{"questionId": "q1", "value": "q1_a"}]   # q2 的答案在路径外，被丢弃


def test_finishes_after_last_question():
    r = compute_path([text("q1")], {"q1": "完"})
    assert r.finished and r.path == ["q1"]


def test_empty_survey_finishes_immediately():
    r = compute_path([], {})
    assert r.finished and r.path == [] and r.answers == []


# ---------- 选填题未作答（6.3 第 4 条） ----------
@pytest.mark.parametrize("default, expected", [(None, ["q1", "q2", "q3", "q4"]), ("q3", ["q1", "q3", "q4"])])
def test_optional_unanswered_skips_rules(default, expected):
    """未作答时不判断任何规则（即使是 ne 这种“不等于”也不会成立），直接走默认去向。"""
    qs = three_after(number("q1", rules=[rule("ne", 5, "q4")], default=default, required=False))
    r = compute_path(qs, {"q1": None})
    assert r.path == expected and r.finished
    assert all(a["questionId"] != "q1" for a in r.answers)


def test_optional_multi_empty_array_unanswered():
    qs = three_after(multi("q1", rules=[rule("containsAny", ["q1_a"], "q4")], required=False))
    assert path_of(qs, {"q1": []}) == ["q1", "q2", "q3", "q4"]


# ---------- 被跳过的题、多余答案（6.3 第 5、6 条） ----------
def test_skipped_required_question_not_checked():
    """被跳过的必答题不报错，即使提交了不合法的答案也不校验、不保存。"""
    qs = [single("q1", rules=[rule("eq", "q1_b", "q3")]), number("q2", required=True, max=10), text("q3")]
    r = compute_path(qs, {"q1": "q1_b", "q2": 999})
    assert r.errors == [] and r.finished
    assert r.path == ["q1", "q3"]
    assert [a["questionId"] for a in r.answers] == ["q1"]


def test_unknown_question_ids_discarded():
    r = compute_path([text("q1")], {"q1": "答", "q_not_exist": "多余", "END": "x"})
    assert r.errors == []
    assert r.answers == [{"questionId": "q1", "value": "答"}]


def test_answers_normalized_and_in_path_order():
    qs = [multi("q1"), text("q2"), number("q3", integerOnly=True)]
    r = compute_path(qs, {"q3": 7.0, "q2": "  好  ", "q1": ["q1_c", "q1_a"]})
    assert r.answers == [
        {"questionId": "q1", "value": ["q1_a", "q1_c"]},
        {"questionId": "q2", "value": "好"},
        {"questionId": "q3", "value": 7},
    ]


# ---------- 错误：遇到第一个就停下 ----------
def test_required_missing_on_path():
    qs = [text("q1"), single("q2"), text("q3")]
    r = compute_path(qs, {"q1": "x", "q3": "z"})
    assert not r.finished
    assert r.errors == [{"questionId": "q2", "field": "value", "message": "第 2 题：此题为必答题"}]
    assert r.path == ["q1", "q2"]


def test_stops_at_first_error():
    """第 1 题答案不合法时停下，不再检查后面的题（后面同样不合法也只报第一个）。"""
    qs = [number("q1", max=10), number("q2", max=10)]
    r = compute_path(qs, {"q1": 11, "q2": 12})
    assert [e["questionId"] for e in r.errors] == ["q1"]
    assert r.path == ["q1"] and r.answers == []


def test_error_message_uses_position_in_survey_not_in_path():
    """“第 N 题”是题目在问卷中的位置，不是在路径上的序号。"""
    qs = [single("q1", rules=[rule("eq", "q1_a", "q3")]), text("q2"), number("q3", max=1)]
    r = compute_path(qs, {"q1": "q1_a", "q3": 5})
    assert r.errors[0]["message"] == "第 3 题：不能大于 1"


# ---------- 预览模式与提交模式 ----------
def test_preview_stops_at_first_unreached_question():
    qs = [single("q1", rules=[rule("eq", "q1_b", "q3")]), text("q2"), text("q3")]
    r = compute_path(qs, {"q1": "q1_b"}, PREVIEW)
    assert r.next_question_id == "q3"
    assert r.path == ["q1", "q3"]
    assert not r.finished and r.errors == []


def test_preview_with_no_answers_returns_first_question():
    r = compute_path([text("q1"), text("q2")], {}, PREVIEW)
    assert r.next_question_id == "q1" and r.path == ["q1"]


def test_preview_explicit_blank_means_skipped():
    """预览时传了空值表示“看过但不答”：选填题继续往下，必答题报错。"""
    qs = [text("q1", required=False), single("q2")]
    r = compute_path(qs, {"q1": ""}, PREVIEW)
    assert r.next_question_id == "q2"
    r = compute_path(qs, {"q1": "", "q2": None}, PREVIEW)
    assert r.errors[0]["message"] == "第 2 题：此题为必答题"


def test_submit_treats_missing_as_unanswered():
    qs = [text("q1", required=False), single("q2")]
    r = compute_path(qs, {}, SUBMIT)
    assert r.next_question_id is None
    assert r.errors[0]["message"] == "第 2 题：此题为必答题"


def test_preview_finished_when_all_answered():
    qs = [text("q1"), text("q2")]
    r = compute_path(qs, {"q1": "a", "q2": "b"}, PREVIEW)
    assert r.finished and r.next_question_id is None


def test_preview_and_submit_agree_on_complete_answers():
    qs = [single("q1", rules=[rule("eq", "q1_c", "END")]), multi("q2"), number("q3")]
    answers = {"q1": "q1_a", "q2": ["q2_b"], "q3": 3}
    a, b = compute_path(qs, answers, PREVIEW), compute_path(qs, answers, SUBMIT)
    assert (a.path, a.answers, a.finished) == (b.path, b.answers, b.finished)


# ---------- 往前跳的保护 ----------
@pytest.mark.parametrize("target", ["q1", "q2", "q_gone"])
def test_backward_or_missing_target_raises(target):
    """保存时已禁止；数据被绕过接口修改时，路径计算报内部错误而不是死循环。"""
    qs = [text("q1"), single("q2", rules=[rule("eq", "q2_a", target)]), text("q3")]
    with pytest.raises(PathError):
        compute_path(qs, {"q1": "x", "q2": "q2_a"})


# ---------- 重复题目 ----------
def test_index_answers_detects_duplicates():
    items = [{"questionId": "q1", "value": 1}, {"questionId": "q2", "value": 2},
             {"questionId": "q1", "value": 3}, {"questionId": "q1", "value": 4}]
    answers, duplicates = index_answers(items)
    assert duplicates == ["q1"]
    assert answers == {"q1": 4, "q2": 2}


def test_index_answers_no_duplicates():
    assert index_answers([{"questionId": "q1", "value": 1}]) == ({"q1": 1}, [])


# ---------- 设计文档 3.4 示例问卷：所有路径 ----------
@pytest.fixture
def fruit_survey():
    qs = [
        {"id": "q1", "type": "single_choice", "title": "你喜欢吃水果吗？",
         "options": [{"id": "o1", "text": "喜欢"}, {"id": "o2", "text": "不喜欢"}],
         "validation": {"required": True},
         "logic": {"rules": [rule("eq", "o2", "q5")], "defaultNext": None}},
        {"id": "q2", "type": "multiple_choice", "title": "你喜欢哪些水果？",
         "options": [{"id": "o3", "text": "苹果"}, {"id": "o4", "text": "香蕉"},
                     {"id": "o5", "text": "西瓜"}, {"id": "o6", "text": "榴莲"}],
         "validation": {"required": True, "minSelect": 1, "maxSelect": 3},
         "logic": {"rules": [rule("contains", "o6", "q3")], "defaultNext": "q4"}},
        {"id": "q3", "type": "text", "title": "为什么喜欢榴莲？",
         "validation": {"required": False, "minLength": 5, "maxLength": 200}},
        {"id": "q4", "type": "number", "title": "你每周吃几次水果？",
         "validation": {"required": True, "min": 0, "max": 50, "integerOnly": True},
         "logic": {"rules": [rule("eq", 0, "END")], "defaultNext": None}},
        {"id": "q5", "type": "text", "title": "其他建议", "validation": {"required": False, "maxLength": 500}},
    ]
    assert check_survey(qs).ok
    return qs


@pytest.mark.parametrize("answers, expected_path", [
    ({"q1": "o2", "q5": "无"}, ["q1", "q5"]),                                         # 不喜欢 → 第 5 题
    ({"q1": "o1", "q2": ["o3", "o6"], "q3": "闻着臭吃着香", "q4": 7, "q5": "无"},
     ["q1", "q2", "q3", "q4", "q5"]),                                                 # 选了榴莲 → 第 3 题
    ({"q1": "o1", "q2": ["o3", "o6"], "q4": 7}, ["q1", "q2", "q3", "q4", "q5"]),       # 第 3、5 题选填不答
    ({"q1": "o1", "q2": ["o3", "o4"], "q4": 7, "q5": "无"}, ["q1", "q2", "q4", "q5"]),  # 没选榴莲 → 第 4 题
    ({"q1": "o1", "q2": ["o4"], "q4": 0}, ["q1", "q2", "q4"]),                         # 每周 0 次 → 结束
])
def test_fruit_survey_paths(fruit_survey, answers, expected_path):
    r = compute_path(fruit_survey, answers)
    assert r.errors == [] and r.finished
    assert r.path == expected_path
    assert [a["questionId"] for a in r.answers] == [q for q in expected_path if q in answers]


def test_fruit_survey_skipped_answers_discarded(fruit_survey):
    """选“不喜欢”后第 2~4 题被跳过：即使提交了这些题的答案（甚至不合法）也被丢弃。"""
    r = compute_path(fruit_survey, {"q1": "o2", "q2": ["o3", "o4", "o5", "o6"], "q3": "短", "q4": -1})
    assert r.errors == [] and r.path == ["q1", "q5"]
    assert r.answers == [{"questionId": "q1", "value": "o2"}]


@pytest.mark.parametrize("answers, message", [
    ({}, "第 1 题：此题为必答题"),
    ({"q1": "o1"}, "第 2 题：此题为必答题"),
    ({"q1": "o1", "q2": ["o3", "o4", "o5", "o6"]}, "第 2 题：最多选择 3 项（当前选了 4 项）"),
    ({"q1": "o1", "q2": ["o6"], "q3": "好吃"}, "第 3 题：至少 5 个字（当前 2 个）"),
    ({"q1": "o1", "q2": ["o3"], "q4": 2.5}, "第 4 题：必须为整数"),
    ({"q1": "o1", "q2": ["o3"], "q4": 51}, "第 4 题：不能大于 50"),
])
def test_fruit_survey_errors(fruit_survey, answers, message):
    r = compute_path(fruit_survey, answers)
    assert [e["message"] for e in r.errors] == [message]


def test_fruit_survey_preview_step_by_step(fruit_survey):
    """模拟前端一题一题地预览。"""
    steps = [({}, "q1"), ({"q1": "o1"}, "q2"), ({"q1": "o1", "q2": ["o6"]}, "q3"),
             ({"q1": "o1", "q2": ["o6"], "q3": None}, "q4"),
             ({"q1": "o1", "q2": ["o6"], "q3": None, "q4": 3}, "q5")]
    for answers, expected_next in steps:
        assert compute_path(fruit_survey, answers, PREVIEW).next_question_id == expected_next
    done = compute_path(fruit_survey, {"q1": "o1", "q2": ["o6"], "q3": None, "q4": 3, "q5": None}, PREVIEW)
    assert done.finished and done.next_question_id is None
