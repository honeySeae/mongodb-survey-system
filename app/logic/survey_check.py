"""整份问卷的合法性检查（纯函数，不访问数据库）。对应设计文档 3.3、6.3、6.5。

每次添加、修改、删除、调整顺序题目后都对整份问卷检查一次：
- errors：不合法，拒绝保存（题目设置、跳转规则格式、引用、只能往后跳）
- warnings：可以保存但需要提醒（规则重叠、永远不会命中的规则、永远不会显示的题目）

每一项为 {"questionId", "field", "message"}，message 中用“第 N 题”指明位置。
"""
from dataclasses import dataclass, field

from app.logic import operators as ops
from app.logic.question_rules import check_question_settings

MAX_QUESTIONS = 100
MAX_RULES = 50

_RULE_KEYS = {"when", "goto"}
_WHEN_KEYS = {"op", "value"}
_LOGIC_KEYS = {"rules", "defaultNext"}


@dataclass
class CheckResult:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _label(index: int) -> str:
    return f"第 {index + 1} 题"


def check_survey(questions: list[dict]) -> CheckResult:
    result = CheckResult()
    if len(questions) > MAX_QUESTIONS:
        result.errors.append({"questionId": None, "field": "questions",
                              "message": f"每份问卷最多 {MAX_QUESTIONS} 道题"})

    position = {}  # 题目 id -> 下标
    seen_ids: set[str] = set()
    for i, q in enumerate(questions):
        qid = q.get("id")
        for oid in [qid] + [o.get("id") for o in q.get("options") or [] if isinstance(o, dict)]:
            if oid in seen_ids:
                result.errors.append({"questionId": qid, "field": "id",
                                      "message": f"{_label(i)}：id {oid} 在问卷中重复"})
            seen_ids.add(oid)
        position[qid] = i

    for i, q in enumerate(questions):
        for p in check_question_settings(q):
            result.errors.append({"questionId": q.get("id"), "field": p["field"],
                                  "message": f"{_label(i)}：{p['message']}"})
        if "logic" in q:
            _check_logic(questions, i, position, result)

    # 有错误时警告意义不大（例如目标不存在时无法分析可达性），只在合法时计算
    if result.ok:
        for i, q in enumerate(questions):
            _warn_rules(q, i, result)
        _warn_unreachable(questions, result)
    return result


# ---------- 跳转规则 ----------
def _check_target(target, questions, i, position, prefix: str, field_name: str,
                  qid: str, result: CheckResult, allow_null: bool) -> None:
    if target is None and allow_null:
        return
    if target == ops.END:
        return
    if not isinstance(target, str) or target not in position:
        result.errors.append({"questionId": qid, "field": field_name,
                              "message": f"{prefix}：跳转目标 {target!r} 不存在"})
        return
    j = position[target]
    if j <= i:
        what = "本题自己" if j == i else _label(j)
        result.errors.append({"questionId": qid, "field": field_name,
                              "message": f"{prefix}：只能跳转到后面的题目或 END（目标是{what}）"})


def _check_logic(questions: list[dict], i: int, position: dict, result: CheckResult) -> None:
    q = questions[i]
    qid, qtype = q.get("id"), q.get("type")
    label = _label(i)

    def err(field_name: str, message: str):
        result.errors.append({"questionId": qid, "field": field_name, "message": message})

    if not ops.supports_logic(qtype):
        err("logic", f"{label}：该题型不支持跳转")
        return
    logic = q["logic"]
    if not isinstance(logic, dict):
        err("logic", f"{label}：跳转规则应为对象")
        return
    for key in logic:
        if key not in _LOGIC_KEYS:
            err(f"logic.{key}", f"{label}：跳转规则不支持字段 {key}")

    _check_target(logic.get("defaultNext"), questions, i, position, f"{label}默认去向",
                  "logic.defaultNext", qid, result, allow_null=True)

    rules = logic.get("rules", [])
    if not isinstance(rules, list):
        err("logic.rules", f"{label}：rules 应为数组")
        return
    if len(rules) > MAX_RULES:
        err("logic.rules", f"{label}：每道题最多 {MAX_RULES} 条跳转规则")

    option_ids = {o.get("id") for o in q.get("options") or [] if isinstance(o, dict)}
    allowed_ops = ops.OPERATORS[qtype]
    for k, rule in enumerate(rules):
        prefix = f"{label}第 {k + 1} 条规则"
        base = f"logic.rules[{k}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("when"), dict) or "goto" not in rule:
            err(base, f"{prefix}：格式应为 {{when: {{op, value}}, goto}}")
            continue
        extra = (set(rule) - _RULE_KEYS) | (set(rule["when"]) - _WHEN_KEYS)
        if extra:
            err(base, f"{prefix}：不支持字段 {', '.join(sorted(extra))}")
        op = rule["when"].get("op")
        if op not in allowed_ops:
            err(f"{base}.when.op",
                f"{prefix}：该题型的运算符只能是 {' / '.join(allowed_ops)}（收到 {op!r}）")
        else:
            msg = _check_value(allowed_ops[op], rule["when"].get("value"), option_ids)
            if msg:
                err(f"{base}.when.value", f"{prefix}：{msg}")
        _check_target(rule.get("goto"), questions, i, position, prefix, f"{base}.goto",
                      qid, result, allow_null=False)


def _check_value(fmt: str, value, option_ids: set) -> str | None:
    """检查条件值的格式；合法返回 None，否则返回问题说明。"""
    expected = f"值应为{ops.VALUE_FORMAT_NAMES[fmt]}"
    if fmt == ops.OPTION:
        if not isinstance(value, str):
            return expected
        if value not in option_ids:
            return f"引用的选项 {value} 不是本题的选项（可能已被删除），请先修改该规则"
    elif fmt == ops.OPTION_LIST:
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            return expected + "，且不能为空"
        if len(set(value)) != len(value):
            return "选项 id 不能重复"
        missing = [v for v in value if v not in option_ids]
        if missing:
            return f"引用的选项 {', '.join(missing)} 不是本题的选项（可能已被删除），请先修改该规则"
    elif fmt == ops.NUMBER:
        if not ops.is_number(value):
            return expected
    elif fmt == ops.NUMBER_RANGE:
        if not isinstance(value, list) or len(value) != 2 or not all(ops.is_number(v) for v in value):
            return expected
        if value[0] > value[1]:
            return f"between 的最小值（{value[0]}）不能大于最大值（{value[1]}）"
    return None


# ---------- 警告 ----------
def _warn_rules(q: dict, i: int, result: CheckResult) -> None:
    rules = (q.get("logic") or {}).get("rules") or []
    if not rules:
        return
    qid, qtype, label = q["id"], q["type"], _label(i)
    v = q.get("validation") or {}

    def warn(k: int, message: str):
        result.warnings.append({"questionId": qid, "field": f"logic.rules[{k}]", "message": message})

    if qtype == "single_choice":
        texts = {o["id"]: o["text"] for o in q["options"]}
        sets = [{r["when"]["value"]} if r["when"]["op"] == "eq" else set(r["when"]["value"])
                for r in rules]
        for b in range(len(rules)):
            for a in range(b):
                common = sets[a] & sets[b]
                if common:
                    names = "、".join(f"「{texts[o]}」" for o in sorted(common, key=list(texts).index))
                    warn(b, f"{label}第 {a + 1} 条和第 {b + 1} 条规则都包含选项{names}，"
                            f"选中时按第 {a + 1} 条跳转，第 {b + 1} 条对这些选项不会生效")

    elif qtype == "number":
        integer_only = v.get("integerOnly") is True
        domain = [ops.Interval(v.get("min", -ops.INF), "min" in v, v.get("max", ops.INF), "max" in v)]
        ranges = [ops.number_condition_intervals(r["when"]["op"], r["when"]["value"]) for r in rules]
        for k, rng in enumerate(ranges):
            if not ops.intervals_overlap(rng, domain, integer_only):
                why = "在题目允许的取值范围内" + ("（且为整数）" if integer_only else "")
                warn(k, f"{label}第 {k + 1} 条规则{why}永远不会成立")
        for b in range(len(ranges)):
            for a in range(b):
                if ops.intervals_overlap(ranges[a], ranges[b], integer_only):
                    warn(b, f"{label}第 {a + 1} 条和第 {b + 1} 条规则的取值范围有重叠，"
                            f"重叠部分按第 {a + 1} 条跳转")

    elif qtype == "multiple_choice":
        lo = v.get("minSelect", 1 if v.get("required") else 0)
        hi = v.get("maxSelect", len(q["options"]))
        for k, r in enumerate(rules):
            op, value = r["when"]["op"], r["when"]["value"]
            if op == "equals" and not lo <= len(value) <= hi:
                warn(k, f"{label}第 {k + 1} 条规则要求恰好选 {len(value)} 项，"
                        f"但本题只能选 {lo}~{hi} 项，永远不会成立")
            elif op == "containsAll" and len(value) > hi:
                warn(k, f"{label}第 {k + 1} 条规则要求同时选中 {len(value)} 项，"
                        f"但本题最多选 {hi} 项，永远不会成立")


def _successors(questions: list[dict], i: int) -> set:
    """第 i 题之后可能到达的下一个位置（题目下标或 END），包括每条规则的目标和默认去向。"""
    index = {q["id"]: k for k, q in enumerate(questions)}

    def resolve(target):
        return ops.END if target == ops.END else index[target]

    logic = questions[i].get("logic") or {}
    nexts = {resolve(r["goto"]) for r in logic.get("rules") or []}
    default = logic.get("defaultNext")
    if default is not None:
        nexts.add(resolve(default))
    else:
        nexts.add(i + 1 if i + 1 < len(questions) else ops.END)
    return nexts


def _warn_unreachable(questions: list[dict], result: CheckResult) -> None:
    if not questions:
        return
    reached, stack = {0}, [0]
    while stack:
        for nxt in _successors(questions, stack.pop()):
            if nxt != ops.END and nxt not in reached:
                reached.add(nxt)
                stack.append(nxt)
    for i, q in enumerate(questions):
        if i not in reached:
            result.warnings.append({"questionId": q["id"], "field": "id",
                                    "message": f"{_label(i)}在任何情况下都不会被显示（前面的跳转都绕过了它）"})


# ---------- 引用查询 ----------
def find_references(questions: list[dict], target_id: str) -> list[str]:
    """哪些跳转规则指向 target_id（删除题目前检查用），返回说明文字列表。"""
    refs = []
    for i, q in enumerate(questions):
        logic = q.get("logic") or {}
        for k, r in enumerate(logic.get("rules") or []):
            if r.get("goto") == target_id:
                refs.append(f"{_label(i)}「{q['title']}」的第 {k + 1} 条规则")
        if logic.get("defaultNext") == target_id:
            refs.append(f"{_label(i)}「{q['title']}」的默认去向")
    return refs
