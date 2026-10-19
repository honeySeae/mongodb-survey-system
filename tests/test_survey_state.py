"""第四步：问卷状态规则（纯函数，不访问数据库）。对应设计文档 6.4。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.logic import survey_state as state

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("status, action, expected", [
    ("draft", "publish", True),
    ("published", "publish", False),
    ("closed", "publish", False),
    ("draft", "close", False),       # 草稿不能关闭，只能删除
    ("published", "close", True),
    ("closed", "close", False),
    ("draft", "delete", True),
    ("published", "delete", False),
    ("closed", "delete", False),
    ("draft", "edit_questions", True),
    ("published", "edit_questions", False),  # 发布后不能改题目
    ("closed", "edit_questions", False),
    ("unknown", "publish", False),
])
def test_can(status, action, expected):
    assert state.can(status, action) is expected


# 设计文档 6.4 表格的每一格
ALL_FIELDS = {"title", "description", "deadline", "allowAnonymous", "submissionPolicy"}


@pytest.mark.parametrize("status, expected_locked", [
    ("draft", []),
    ("published", ["allowAnonymous", "submissionPolicy"]),
    ("closed", ["title", "description", "deadline", "allowAnonymous", "submissionPolicy"]),
])
def test_locked_fields(status, expected_locked):
    assert state.locked_fields(status, ALL_FIELDS) == expected_locked


def test_locked_fields_only_reports_changed_ones():
    assert state.locked_fields("published", {"title", "submissionPolicy"}) == ["submissionPolicy"]
    assert state.locked_fields("published", {"title", "deadline"}) == []


def test_lock_message_includes_reason():
    assert state.lock_message("published", "submissionPolicy") == \
        "问卷已发布，不能修改提交策略（会影响已收集答卷的统计口径）"
    assert state.lock_message("published", "allowAnonymous") == \
        "问卷已发布，不能修改匿名设置（会影响对填写者的隐私承诺）"
    assert state.lock_message("closed", "title") == "问卷已关闭，不能修改标题"


@pytest.mark.parametrize("deadline, expected", [
    (None, False),                          # 不限
    (NOW + timedelta(seconds=1), False),
    (NOW, True),                            # 恰好到截止时间即视为过期
    (NOW - timedelta(days=1), True),
])
def test_is_expired(deadline, expected):
    assert state.is_expired(deadline, NOW) is expected


@pytest.mark.parametrize("status, deadline, expected", [
    ("draft", None, False),
    ("published", None, True),
    ("published", NOW + timedelta(days=1), True),
    ("published", NOW - timedelta(days=1), False),  # 过期视同关闭
    ("closed", NOW + timedelta(days=1), False),
])
def test_accepting_responses(status, deadline, expected):
    assert state.accepting_responses(status, deadline, NOW) is expected
