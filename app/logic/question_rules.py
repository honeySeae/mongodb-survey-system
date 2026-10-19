"""单道题设置本身的检查（纯函数，不访问数据库）。对应设计文档 3.1、3.2。

只检查题目自身：题型、题目文字、选项、validation。
跳转规则涉及题目之间的位置关系，在 survey_check 中检查。
返回值为问题列表 [{"field": ..., "message": ...}]，合法时为空列表。
"""
from app.logic.operators import is_number

QUESTION_TYPES = ("single_choice", "multiple_choice", "text", "number")
CHOICE_TYPES = ("single_choice", "multiple_choice")
TYPE_NAMES = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "text": "文本填空题",
    "number": "数字填空题",
}

TITLE_MAX = 200
OPTIONS_MAX = 50
OPTION_TEXT_MAX = 100
MAX_LENGTH_LIMIT = 10000

# 各题型允许的 validation 字段
VALIDATION_FIELDS = {
    "single_choice": {"required"},
    "multiple_choice": {"required", "minSelect", "maxSelect"},
    "text": {"required", "minLength", "maxLength"},
    "number": {"required", "min", "max", "integerOnly"},
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_question_settings(q: dict) -> list[dict]:
    qtype = q.get("type")
    if qtype not in QUESTION_TYPES:
        return [{"field": "type", "message": f"题型只能是 {' / '.join(QUESTION_TYPES)}"}]

    problems: list[dict] = []

    def add(field: str, message: str):
        problems.append({"field": field, "message": message})

    # 题目文字
    title = q.get("title")
    if not isinstance(title, str) or not title.strip():
        add("title", "题目文字不能为空")
    elif len(title.strip()) > TITLE_MAX:
        add("title", f"题目文字最多 {TITLE_MAX} 个字符")

    # 选项
    options = q.get("options")
    if qtype in CHOICE_TYPES:
        if not isinstance(options, list) or not options:
            add("options", f"{TYPE_NAMES[qtype]}至少需要 1 个选项")
            options = []
        elif len(options) > OPTIONS_MAX:
            add("options", f"选项最多 {OPTIONS_MAX} 个")
        seen_texts = set()
        for i, opt in enumerate(options):
            text = opt.get("text") if isinstance(opt, dict) else None
            if not isinstance(text, str) or not text.strip():
                add(f"options[{i}].text", f"第 {i + 1} 个选项的文字不能为空")
                continue
            text = text.strip()
            if len(text) > OPTION_TEXT_MAX:
                add(f"options[{i}].text", f"第 {i + 1} 个选项的文字最多 {OPTION_TEXT_MAX} 个字符")
            if text in seen_texts:
                add(f"options[{i}].text", f"第 {i + 1} 个选项「{text}」与前面的选项重复")
            seen_texts.add(text)
    elif options is not None:
        add("options", f"{TYPE_NAMES[qtype]}没有选项")

    # validation
    v = q.get("validation")
    if not isinstance(v, dict):
        add("validation", "校验规则应为对象")
        return problems
    for key in v:
        if key not in VALIDATION_FIELDS[qtype]:
            add(f"validation.{key}", f"{TYPE_NAMES[qtype]}不支持校验字段 {key}")
    if "required" in v and not isinstance(v["required"], bool):
        add("validation.required", "required 应为 true 或 false")

    if qtype == "multiple_choice":
        _check_select_counts(v, len(options), add)
    elif qtype == "text":
        _check_lengths(v, add)
    elif qtype == "number":
        _check_number_range(v, add)
    return problems


def _check_select_counts(v: dict, option_count: int, add) -> None:
    lo, hi = v.get("minSelect"), v.get("maxSelect")
    for name, val in (("minSelect", lo), ("maxSelect", hi)):
        if val is not None and (not _is_int(val) or val < 1):
            add(f"validation.{name}", f"{name} 应为正整数")
    lo = lo if _is_int(lo) and lo >= 1 else None
    hi = hi if _is_int(hi) and hi >= 1 else None
    if lo is not None and hi is not None and lo > hi:
        add("validation.minSelect", f"最少选择数（{lo}）不能大于最多选择数（{hi}）")
    if option_count:
        if hi is not None and hi > option_count:
            add("validation.maxSelect", f"最多选择数（{hi}）不能大于选项数（{option_count}）")
        if lo is not None and lo > option_count:
            add("validation.minSelect", f"最少选择数（{lo}）不能大于选项数（{option_count}）")


def _check_lengths(v: dict, add) -> None:
    lo, hi = v.get("minLength"), v.get("maxLength")
    if lo is not None and (not _is_int(lo) or lo < 0):
        add("validation.minLength", "minLength 应为非负整数")
        lo = None
    if hi is not None and (not _is_int(hi) or not 1 <= hi <= MAX_LENGTH_LIMIT):
        add("validation.maxLength", f"maxLength 应为 1~{MAX_LENGTH_LIMIT} 的整数")
        hi = None
    if lo is not None and hi is not None and lo > hi:
        add("validation.minLength", f"最少字数（{lo}）不能大于最多字数（{hi}）")


def _check_number_range(v: dict, add) -> None:
    lo, hi = v.get("min"), v.get("max")
    if lo is not None and not is_number(lo):
        add("validation.min", "min 应为数字")
        lo = None
    if hi is not None and not is_number(hi):
        add("validation.max", "max 应为数字")
        hi = None
    if lo is not None and hi is not None and lo > hi:
        add("validation.min", f"最小值（{lo}）不能大于最大值（{hi}）")
    if "integerOnly" in v and not isinstance(v["integerOnly"], bool):
        add("validation.integerOnly", "integerOnly 应为 true 或 false")
