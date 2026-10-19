"""问卷状态规则（纯函数，不访问数据库，可单独测试）。

对应 docs/DATABASE_DESIGN.md 6.4 节。规则写成数据表：
第二阶段若要新增状态、放开某些修改，只需修改下面的表。
"""
from datetime import datetime

DRAFT, PUBLISHED, CLOSED = "draft", "published", "closed"

STATUS_NAMES = {DRAFT: "草稿", PUBLISHED: "已发布", CLOSED: "已关闭"}

# 状态变更：操作 -> (要求的当前状态, 变更后的状态)
TRANSITIONS = {
    "publish": (DRAFT, PUBLISHED),
    "close": (PUBLISHED, CLOSED),
}

# 各状态允许的其他操作
ALLOWED_ACTIONS = {
    DRAFT: {"publish", "delete", "edit_questions"},
    PUBLISHED: {"close"},
    CLOSED: set(),
}

# 各状态下可以修改的字段（字段名与接口中的名称一致）
EDITABLE_FIELDS = {
    DRAFT: {"title", "description", "deadline", "allowAnonymous", "submissionPolicy"},
    PUBLISHED: {"title", "description", "deadline"},
    CLOSED: set(),
}

# 字段被锁定时的原因说明
LOCK_REASONS = {
    "allowAnonymous": "会影响对填写者的隐私承诺",
    "submissionPolicy": "会影响已收集答卷的统计口径",
}

FIELD_NAMES = {
    "title": "标题",
    "description": "说明",
    "deadline": "截止时间",
    "allowAnonymous": "匿名设置",
    "submissionPolicy": "提交策略",
}


def can(status: str, action: str) -> bool:
    """当前状态下能否执行某个操作。"""
    if action in TRANSITIONS:
        return TRANSITIONS[action][0] == status
    return action in ALLOWED_ACTIONS.get(status, set())


def locked_fields(status: str, changed: set[str]) -> list[str]:
    """在当前状态下，changed 中不允许修改的字段（按固定顺序返回）。"""
    editable = EDITABLE_FIELDS.get(status, set())
    return [f for f in FIELD_NAMES if f in changed and f not in editable]


def lock_message(status: str, field: str) -> str:
    msg = f"问卷{STATUS_NAMES[status]}，不能修改{FIELD_NAMES[field]}"
    if status != CLOSED and field in LOCK_REASONS:
        msg += f"（{LOCK_REASONS[field]}）"
    return msg


def is_expired(deadline: datetime | None, now: datetime) -> bool:
    """是否已过截止时间（截止时间为空表示不限）。"""
    return deadline is not None and now >= deadline


def accepting_responses(status: str, deadline: datetime | None, now: datetime) -> bool:
    """是否正在收集答卷：已发布且未过截止时间。过期视同关闭，延长截止时间后恢复。"""
    return status == PUBLISHED and not is_expired(deadline, now)
