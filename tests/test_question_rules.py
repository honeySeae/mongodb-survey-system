"""第五步：单道题设置本身的检查（纯函数，不访问数据库）。对应设计文档 3.1、3.2。"""
import pytest

from app.logic.question_rules import check_question_settings


def opts(*texts):
    return [{"id": f"o_{i:06d}", "text": t} for i, t in enumerate(texts)]


def q(qtype, validation=None, options=None, title="题目"):
    d = {"id": "q_000001", "type": qtype, "title": title, "validation": validation or {"required": False}}
    if options is not None:
        d["options"] = options
    return d


def fields(problems):
    return [p["field"] for p in problems]


# ---------- 合法设置 ----------
@pytest.mark.parametrize("question", [
    q("single_choice", {"required": True}, opts("男", "女", "其他")),
    q("single_choice", {"required": False}, opts("唯一选项")),
    q("multiple_choice", {"required": True, "minSelect": 2, "maxSelect": 3}, opts("苹果", "香蕉", "西瓜", "葡萄")),
    q("multiple_choice", {"required": True, "minSelect": 2, "maxSelect": 2}, opts("A", "B", "C")),  # 必须选 2 个
    q("multiple_choice", {"required": False, "maxSelect": 4}, opts("A", "B", "C", "D")),           # maxSelect = 选项数
    q("text", {"required": False, "minLength": 5, "maxLength": 200}),
    q("text", {"required": True, "minLength": 0, "maxLength": 10000}),
    q("text", {"required": True, "minLength": 3, "maxLength": 3}),
    q("number", {"required": True, "min": 0, "max": 120, "integerOnly": True}),               # 年龄
    q("number", {"required": True, "integerOnly": True}),                                     # 手机号
    q("number", {"required": False, "min": -1.5, "max": 99.9}),
    q("number", {"required": False, "min": 5, "max": 5}),
    q("text", {"required": True}),
])
def test_valid_settings(question):
    assert check_question_settings(question) == []


# ---------- 题型与题目文字 ----------
def test_unknown_type():
    assert fields(check_question_settings(q("rating"))) == ["type"]


@pytest.mark.parametrize("title, ok", [("", False), ("   ", False), ("题" * 200, True), ("题" * 201, False)])
def test_title_length(title, ok):
    problems = check_question_settings(q("text", title=title))
    assert (problems == []) is ok
    if not ok:
        assert fields(problems) == ["title"]


# ---------- 选项 ----------
@pytest.mark.parametrize("qtype", ["single_choice", "multiple_choice"])
def test_choice_requires_options(qtype):
    assert fields(check_question_settings(q(qtype, options=[]))) == ["options"]
    assert fields(check_question_settings(q(qtype))) == ["options"]


@pytest.mark.parametrize("qtype", ["text", "number"])
def test_non_choice_cannot_have_options(qtype):
    problems = check_question_settings(q(qtype, options=opts("A")))
    assert fields(problems) == ["options"]
    assert "没有选项" in problems[0]["message"]


def test_option_count_limit():
    assert check_question_settings(q("single_choice", options=opts(*map(str, range(50))))) == []
    assert fields(check_question_settings(q("single_choice", options=opts(*map(str, range(51)))))) == ["options"]


def test_option_text_rules():
    problems = check_question_settings(q("single_choice", options=opts("苹果", "", "选" * 101, "苹果")))
    assert fields(problems) == ["options[1].text", "options[2].text", "options[3].text"]
    assert "重复" in problems[2]["message"]
    assert check_question_settings(q("single_choice", options=opts("选" * 100))) == []


# ---------- validation 通用 ----------
@pytest.mark.parametrize("qtype, key", [
    ("single_choice", "minSelect"),
    ("multiple_choice", "minLength"),
    ("text", "min"),
    ("text", "integerOnly"),
    ("number", "minLength"),
    ("number", "maxSelect"),
    ("number", "pattern"),
])
def test_field_not_matching_type_rejected(qtype, key):
    options = opts("A", "B") if qtype in ("single_choice", "multiple_choice") else None
    problems = check_question_settings(q(qtype, {"required": False, key: 1}, options))
    assert f"validation.{key}" in fields(problems)


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_required_must_be_bool(value):
    assert fields(check_question_settings(q("text", {"required": value}))) == ["validation.required"]


def test_validation_must_be_object():
    assert fields(check_question_settings(q("text") | {"validation": [1, 2]})) == ["validation"]


# ---------- 多选 ----------
@pytest.mark.parametrize("v, bad_field", [
    ({"minSelect": 3, "maxSelect": 2}, "validation.minSelect"),
    ({"maxSelect": 5}, "validation.maxSelect"),          # 大于选项数 4
    ({"minSelect": 5}, "validation.minSelect"),          # 大于选项数 4
    ({"minSelect": 0}, "validation.minSelect"),          # 必须为正整数
    ({"maxSelect": -1}, "validation.maxSelect"),
    ({"minSelect": 1.5}, "validation.minSelect"),
    ({"minSelect": True}, "validation.minSelect"),       # 布尔值不当数字
    ({"minSelect": "2"}, "validation.minSelect"),        # 字符串不当数字
])
def test_multiple_choice_select_counts(v, bad_field):
    problems = check_question_settings(q("multiple_choice", {"required": True, **v}, opts("A", "B", "C", "D")))
    assert bad_field in fields(problems)


# ---------- 文本 ----------
@pytest.mark.parametrize("v, bad_field", [
    ({"minLength": 10, "maxLength": 5}, "validation.minLength"),
    ({"minLength": -1}, "validation.minLength"),
    ({"maxLength": 0}, "validation.maxLength"),
    ({"maxLength": 10001}, "validation.maxLength"),
    ({"maxLength": 2.5}, "validation.maxLength"),
    ({"maxLength": True}, "validation.maxLength"),
    ({"minLength": "3"}, "validation.minLength"),
])
def test_text_lengths(v, bad_field):
    assert bad_field in fields(check_question_settings(q("text", {"required": True, **v})))


# ---------- 数字 ----------
@pytest.mark.parametrize("v, bad_field", [
    ({"min": 10, "max": 0}, "validation.min"),
    ({"min": "0"}, "validation.min"),
    ({"max": True}, "validation.max"),
    ({"integerOnly": "yes"}, "validation.integerOnly"),
    ({"integerOnly": 1}, "validation.integerOnly"),
])
def test_number_range(v, bad_field):
    assert bad_field in fields(check_question_settings(q("number", {"required": True, **v})))
