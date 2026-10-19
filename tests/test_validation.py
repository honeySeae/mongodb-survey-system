"""第六步：单道题答案的校验与规范化（纯函数，不访问数据库）。对应设计文档 3.2、6.6。"""
import json

import pytest

from app.logic.validation import INT64_MAX, INT64_MIN, check_answer


def single(required=True):
    return {"id": "q1", "type": "single_choice", "title": "t",
            "options": [{"id": "o_a", "text": "A"}, {"id": "o_b", "text": "B"}],
            "validation": {"required": required}}


def multi(required=True, **v):
    return {"id": "q1", "type": "multiple_choice", "title": "t",
            "options": [{"id": f"o_{c}", "text": c} for c in "abcd"],
            "validation": {"required": required, **v}}


def text(required=True, **v):
    return {"id": "q1", "type": "text", "title": "t", "validation": {"required": required, **v}}


def number(required=True, **v):
    return {"id": "q1", "type": "number", "title": "t", "validation": {"required": required, **v}}


def ok(question, raw):
    r = check_answer(question, raw)
    assert r.error is None, r.error
    assert r.answered
    return r.value


def err(question, raw):
    r = check_answer(question, raw)
    assert r.error is not None
    return r.error


# ---------- 未作答（设计文档 6.6） ----------
@pytest.mark.parametrize("question, raw", [
    (single(), None),
    (multi(), None), (multi(), []),
    (text(), None), (text(), ""), (text(), "   \n\t "),
    (number(), None),
])
def test_blank_is_unanswered(question, raw):
    required = check_answer(question, raw)
    assert not required.answered and required.error == "此题为必答题"
    question["validation"]["required"] = False
    optional = check_answer(question, raw)
    assert not optional.answered and optional.error is None


def test_single_empty_string_is_not_unanswered():
    """单选的空字符串不算未作答，按“不是本题的选项”报错。"""
    assert err(single(required=False), "") == "选择的不是本题的选项"


# ---------- 选填题：一旦作答就必须合法 ----------
def test_optional_but_answered_must_be_valid():
    assert err(text(required=False, minLength=5), "太短") == "至少 5 个字（当前 2 个）"
    assert err(number(required=False, max=10), 11) == "不能大于 10"
    assert err(multi(required=False, minSelect=2), ["o_a"]) == "至少选择 2 项（当前选了 1 项）"


# ---------- 单选 ----------
def test_single_valid():
    assert ok(single(), "o_b") == "o_b"


@pytest.mark.parametrize("raw, message", [
    ("o_x", "选择的不是本题的选项"),
    (["o_a"], "应选择一个选项"),
    (1, "应选择一个选项"),
    (True, "应选择一个选项"),
])
def test_single_invalid(raw, message):
    assert err(single(), raw) == message


# ---------- 多选 ----------
def test_multi_saved_in_option_order():
    """按题目中选项的顺序保存，不按点选先后。"""
    assert ok(multi(), ["o_c", "o_a"]) == ["o_a", "o_c"]


@pytest.mark.parametrize("raw, message", [
    (["o_a", "o_a"], "选项不能重复"),
    (["o_a", "o_x"], "包含不是本题的选项"),
    ("o_a", "应为选项 id 组成的数组"),
    (["o_a", 1], "应为选项 id 组成的数组"),
])
def test_multi_invalid(raw, message):
    assert err(multi(), raw) == message


@pytest.mark.parametrize("v, raw, message", [
    ({"minSelect": 2}, ["o_a"], "至少选择 2 项（当前选了 1 项）"),
    ({"maxSelect": 3}, ["o_a", "o_b", "o_c", "o_d"], "最多选择 3 项（当前选了 4 项）"),
    ({"minSelect": 2, "maxSelect": 2}, ["o_a"], "必须选择 2 项（当前选了 1 项）"),
    ({"minSelect": 2, "maxSelect": 2}, ["o_a", "o_b", "o_c"], "必须选择 2 项（当前选了 3 项）"),
])
def test_multi_count_limits(v, raw, message):
    assert err(multi(**v), raw) == message


@pytest.mark.parametrize("v, raw", [
    ({"minSelect": 2}, ["o_a", "o_b"]),
    ({"maxSelect": 3}, ["o_a", "o_b", "o_c"]),
    ({"minSelect": 2, "maxSelect": 2}, ["o_a", "o_b"]),
    ({}, ["o_a"]),                       # 必答且未设 minSelect：至少 1 个即可
    ({}, ["o_a", "o_b", "o_c", "o_d"]),  # 未设 maxSelect：全选也可以
])
def test_multi_count_boundaries_ok(v, raw):
    ok(multi(**v), raw)


# ---------- 文本 ----------
def test_text_trimmed_and_inner_whitespace_kept():
    assert ok(text(), "  第一行\n第二行  ") == "第一行\n第二行"


@pytest.mark.parametrize("raw, expected", [
    ("你好", None),                          # 汉字按 1 个字计
    ("ab", None),
    (" ab ", None),                           # 去首尾空白后 2 个字
    ("a", "至少 2 个字（当前 1 个）"),
    ("abcd", None),
    ("abcde", "最多 4 个字（当前 5 个）"),
    ("闻着臭吃着", "最多 4 个字（当前 5 个）"),
])
def test_text_length_boundaries(raw, expected):
    r = check_answer(text(minLength=2, maxLength=4), raw)
    assert r.error == expected


def test_text_length_counts_unicode_code_points():
    """按 Unicode 码点计数：带肤色的 emoji 由 2 个码点组成，算 2 个字（设计文档 6.6，已确认）。"""
    assert err(text(maxLength=1), "👍🏻") == "最多 1 个字（当前 2 个）"
    assert ok(text(maxLength=1), "👍") == "👍"


@pytest.mark.parametrize("raw", [123, 1.5, True, ["文字"], {"a": 1}])
def test_text_must_be_string(raw):
    assert err(text(), raw) == "应填写文字"


# ---------- 数字 ----------
@pytest.mark.parametrize("raw", ["7", "", True, False, [7], {"v": 7}])
def test_number_must_be_json_number(raw):
    assert err(number(), raw) == "应填写数字"


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_number_rejects_nan_and_infinity(raw):
    """Python 解析 JSON 时会接受 NaN / Infinity，必须单独拒绝。"""
    value = json.loads(raw)
    assert err(number(required=False), value) == "应填写数字"


@pytest.mark.parametrize("raw, expected", [
    (0, None), (120, None),
    (-1, "不能小于 0"), (121, "不能大于 120"),
    (0.0, None), (119.5, "必须为整数"),
])
def test_number_age_example(raw, expected):
    """需求原文的例子：年龄必须为整数，且在 0~120 之间。"""
    r = check_answer(number(min=0, max=120, integerOnly=True), raw)
    assert r.error == expected


def test_integer_only_converts_float():
    value = ok(number(integerOnly=True), 3.0)
    assert value == 3 and isinstance(value, int)


def test_float_kept_without_integer_only():
    value = ok(number(), 3.0)
    assert value == 3.0 and isinstance(value, float)
    assert ok(number(min=0.5, max=1.5), 1.25) == 1.25


def test_phone_number_example():
    """需求原文的例子：手机号必须为整数（11 位在 64 位范围内）。"""
    assert ok(number(integerOnly=True), 13812345678) == 13812345678


# ---------- 64 位整数范围（设计文档 6.6，第三步约定，此处补充校验引擎的测试） ----------
@pytest.mark.parametrize("integer_only", [True, False])
@pytest.mark.parametrize("raw, valid", [
    (INT64_MAX, True),
    (INT64_MIN, True),
    (INT64_MAX + 1, False),
    (INT64_MIN - 1, False),
    (10 ** 20, False),
])
def test_int64_range(raw, valid, integer_only):
    """对所有整数值生效，不论是否设置 integerOnly。"""
    r = check_answer(number(integerOnly=integer_only), raw)
    if valid:
        assert r.error is None and r.value == raw
    else:
        assert r.error.startswith("数值超出允许范围")


def test_large_float_converted_by_integer_only_then_range_checked():
    """1e20 是小数：不设 integerOnly 时可以存储；设了则转为整数后超出范围。"""
    assert ok(number(), 1e20) == 1e20
    assert err(number(integerOnly=True), 1e20).startswith("数值超出允许范围")


def test_min_max_message_formats_whole_floats():
    assert err(number(min=1.0), 0) == "不能小于 1"
    assert err(number(max=2.5), 3) == "不能大于 2.5"
