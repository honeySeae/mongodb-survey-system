"""端到端测试：为开发者在网页上手工创建的问卷“大学生运动习惯调查”模拟 15 位填写人，并逐项核对结果。

问卷由开发者（账号 hanmeimei）在网页上手工创建并发布，链接 /survey/Z2alVy；本脚本只模拟填写数据。
全部通过 HTTP 接口操作（与网页走同样的校验和路径计算），不直接读写数据库、不引用 app/ 中的代码。

检查内容：
  1. 问卷结构：题目和选项文字与预期一致（不一致则停止，避免问卷被修改后填错）
  2. 路径：提交前用路径预览接口确认服务器算出的路径与人工推出的路径一致（全部一致才开始提交）
  3. 提交：15 人提交；每份实际保存的题目与期望路径一致，被跳过的题没有保存
  4. 不合法答卷：单独账号提交 6 份不合法答卷，全部被拒绝且没有保存
  5. 统计：调用统计接口，与人工算出的期望值逐项核对（需要创建者密码，只做只读查询）

用法（先启动 MongoDB 和服务）：
    python -m scripts.sport_survey_e2e                       # 统计核对时会提示输入创建者密码（不回显）
    python -m scripts.sport_survey_e2e --skip-stats          # 不核对统计
    python -m scripts.sport_survey_e2e --report 结果.md      # 同时把结果表写入 Markdown 文件
创建者密码也可以通过环境变量 SURVEY_OWNER_PASSWORD 提供。密码不会被保存或打印。

重复运行：已提交过的账号不再提交（只做核对），不会重复提交。只操作这一份问卷，不修改创建者账号。
答案与路径设计见 AI_LOG 第 30 条（2026-10-21 开发者确认）。
"""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_CODE = "Z2alVy"
DEFAULT_OWNER = "hanmeimei"
PASSWORD = "sport12345"          # 模拟填写人账号的密码
INVALID_USER = "sport_invalid"   # 专门用来提交不合法答卷的账号

# ---------- 问卷的预期结构（读取问卷后核对；不一致则停止） ----------
EXPECTED_TITLES = {
    1: "你的年龄（周岁）？",
    2: "你平时运动的频率是？",
    3: "你经常做哪些运动？",
    4: "你每次在健身房大约待多久？",
    5: "你每次运动大约多少分钟？",
    6: "你觉得自己的运动量够吗？",
    7: "你不常运动的主要原因是？",
    8: "你对学校的体育设施有什么建议？",
}
EXPECTED_OPTIONS = {
    2: ["每周 3 次及以上", "每周 1–2 次", "每月几次", "基本不运动"],
    3: ["跑步", "篮球", "羽毛球", "健身", "游泳", "其他"],
    4: ["30 分钟以内", "30–60 分钟", "1–2 小时", "2 小时以上"],
    6: ["够", "一般", "不够"],
    7: ["没时间", "没兴趣", "没有合适场地", "太累", "其他"],
}

# ---------- 15 位填写人的答案（题号 -> 答案；选择题写选项文字）与人工推出的路径 ----------
W3, W12, MONTH, NONE = "每周 3 次及以上", "每周 1–2 次", "每月几次", "基本不运动"
RESPONDENTS = {
    "sport_u01": ({1: 20, 2: W3, 3: ["跑步", "健身"], 4: "1–2 小时", 5: 60, 6: "够", 8: "希望健身房延长开放时间"},
                  [1, 2, 3, 4, 5, 6, 8]),
    "sport_u02": ({1: 19, 2: W12, 3: ["篮球", "羽毛球"], 5: 90, 6: "一般"}, [1, 2, 3, 5, 6, 8]),
    "sport_u03": ({1: 21, 2: W12, 3: ["跑步"], 5: 40, 6: "不够", 8: "操场晚上的灯光不够亮"}, [1, 2, 3, 5, 6, 8]),
    "sport_u04": ({1: 18, 2: NONE, 7: ["没时间", "太累"]}, [1, 2, 7, 8]),
    "sport_u05": ({1: 22, 2: W3, 3: ["健身", "游泳"], 4: "30–60 分钟", 5: 75, 6: "够", 8: "游泳馆票价能不能便宜一点"},
                  [1, 2, 3, 4, 5, 6, 8]),
    "sport_u06": ({1: 20, 2: MONTH, 7: ["没兴趣"], 8: "希望多组织一些趣味运动会"}, [1, 2, 7, 8]),
    "sport_u07": ({1: 19, 2: W12, 3: ["羽毛球"], 5: 10, 8: "羽毛球场总是约不到"}, [1, 2, 3, 5, 8]),
    # 同时选了篮球、羽毛球、健身：规则按顺序检查，“同时选中篮球和羽毛球”在前，跳过第 4 题
    "sport_u08": ({1: 23, 2: W12, 3: ["篮球", "羽毛球", "健身"], 5: 120, 6: "一般"}, [1, 2, 3, 5, 6, 8]),
    "sport_u09": ({1: 17, 2: W3, 3: ["跑步", "篮球"], 5: 50, 6: "够"}, [1, 2, 3, 5, 6, 8]),
    "sport_u10": ({1: 24, 2: MONTH, 7: ["没时间", "没有合适场地"], 8: "研究生宿舍附近没有运动场"}, [1, 2, 7, 8]),
    # 第 5 题正好填 15：规则“1 到 15”包含 15，跳到第 8 题（边界）
    "sport_u11": ({1: 20, 2: W12, 3: ["健身"], 4: "30 分钟以内", 5: 15}, [1, 2, 3, 4, 5, 8]),
    "sport_u12": ({1: 21, 2: W3, 3: ["跑步", "羽毛球", "其他"], 5: 45, 6: "不够", 8: "希望增加室内运动场地"},
                  [1, 2, 3, 5, 6, 8]),
    "sport_u13": ({1: 15, 2: NONE, 7: ["没兴趣", "其他"]}, [1, 2, 7, 8]),
    "sport_u14": ({1: 22, 2: W12, 3: ["游泳"], 5: 30, 6: "一般"}, [1, 2, 3, 5, 6, 8]),
    "sport_u15": ({1: 16, 2: MONTH, 7: ["太累"]}, [1, 2, 7, 8]),
}

# ---------- 人工算出的期望统计（只含上面 15 人；推算过程见 AI_LOG 第 30 条） ----------
EXPECTED_STATS = {
    "totalResponses": 15,
    "totalRespondents": 15,
    "questions": {
        1: {"answerCount": 15, "respondentCount": 15, "sum": 297},          # 平均 19.8
        2: {"answerCount": 15, "respondentCount": 15,
            "options": {W3: 4, W12: 6, MONTH: 3, NONE: 2}},
        3: {"answerCount": 10, "respondentCount": 10,
            "options": {"跑步": 4, "篮球": 3, "羽毛球": 4, "健身": 4, "游泳": 2, "其他": 1}},
        4: {"answerCount": 3, "respondentCount": 3,
            "options": {"30 分钟以内": 1, "30–60 分钟": 1, "1–2 小时": 1, "2 小时以上": 0}},
        5: {"answerCount": 10, "respondentCount": 10, "sum": 535},          # 平均 53.5
        6: {"answerCount": 8, "respondentCount": 8, "options": {"够": 3, "一般": 3, "不够": 2}},
        7: {"answerCount": 5, "respondentCount": 5,
            "options": {"没时间": 2, "没兴趣": 2, "没有合适场地": 1, "太累": 2, "其他": 1}},
        8: {"answerCount": 7, "respondentCount": 7},
    },
}

# ---------- 不合法答卷：在合法答案基础上改一处，期望被拒绝的提示 ----------
VALID_ACTIVE = {1: 21, 2: W12, 3: ["跑步"], 5: 40, 6: "不够", 8: None}      # 1→2→3→5→6→8
VALID_INACTIVE = {1: 18, 2: NONE, 7: ["没时间"], 8: None}                    # 1→2→7→8
INVALID_CASES = [
    ("年龄 31（超出 14–30）", {**VALID_ACTIVE, 1: 31}, "第 1 题：不能大于 30"),
    ("年龄 13（超出 14–30）", {**VALID_ACTIVE, 1: 13}, "第 1 题：不能小于 14"),
    ("年龄 18.5（带小数）", {**VALID_ACTIVE, 1: 18.5}, "第 1 题：必须为整数"),
    ("第 3 题选 4 项（最多 3 项）", {**VALID_ACTIVE, 3: ["跑步", "篮球", "游泳", "其他"]},
     "第 3 题：最多选择 3 项（当前选了 4 项）"),
    ("第 7 题选 3 项（最多 2 项）", {**VALID_INACTIVE, 7: ["没时间", "没兴趣", "太累"]},
     "第 7 题：最多选择 2 项（当前选了 3 项）"),
    ("第 8 题少于 5 字", {**VALID_ACTIVE, 8: "很好"}, "第 8 题：至少 5 个字（当前 2 个）"),
]


# ---------- HTTP ----------
class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def call(self, method: str, path: str, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else None)

    def login(self, username: str, password: str, register: bool) -> None:
        if register:
            status, body = self.call("POST", "/api/auth/register", {"username": username, "password": password})
            if status not in (201, 409):   # 409：账号已存在，沿用
                raise SystemExit(f"注册 {username} 失败：{status} {body}")
        status, body = self.call("POST", "/api/auth/login", {"username": username, "password": password})
        if status != 200:
            raise SystemExit(f"登录 {username} 失败：{status} {body.get('message') if body else ''}")
        self.token = body["accessToken"]


# ---------- 结果表 ----------
class Report:
    def __init__(self):
        self.sections: list[tuple[str, list[tuple[str, str, str, bool]]]] = []

    def section(self, title: str):
        self.sections.append((title, []))

    def check(self, item: str, expected, actual) -> bool:
        ok = expected == actual
        self.sections[-1][1].append((item, str(expected), str(actual), ok))
        return ok

    @property
    def failures(self) -> int:
        return sum(1 for _, rows in self.sections for *_, ok in rows if not ok)

    @property
    def total(self) -> int:
        return sum(len(rows) for _, rows in self.sections)

    def markdown(self) -> str:
        out = []
        for title, rows in self.sections:
            out.append(f"\n### {title}\n\n| 检查项 | 期望 | 实际 | 是否一致 |\n|---|---|---|---|")
            out += [f"| {i} | {e} | {a} | {'一致' if ok else '**不一致**'} |" for i, e, a, ok in rows]
        out.append(f"\n**合计：{self.total} 项，一致 {self.total - self.failures} 项，不一致 {self.failures} 项。**")
        return "\n".join(out)


# ---------- 答案转换 ----------
def to_items(questions: list[dict], answers: dict) -> list[dict]:
    """题号 -> 答案（选择题为选项文字）转换为接口格式 [{questionId, value}]。"""
    items = []
    for n, value in answers.items():
        q = questions[n - 1]
        ids = {o["text"]: o["id"] for o in q.get("options") or []}
        if value is not None and q["type"] == "single_choice":
            value = ids[value]
        elif value is not None and q["type"] == "multiple_choice":
            value = [ids[v] for v in value]
        items.append({"questionId": q["id"], "value": value})
    return items


def with_skipped_q8(answers: dict) -> dict:
    """选填的第 8 题不填时显式提交 null（“看过但不答”），预览才会走到结尾。"""
    return answers if 8 in answers else {**answers, 8: None}


def numbers(questions: list[dict], ids: list[str]) -> list[int]:
    pos = {q["id"]: i + 1 for i, q in enumerate(questions)}
    return [pos[i] for i in ids]


def fmt_path(nums: list[int]) -> str:
    return "→".join(str(n) for n in nums)


# ---------- 各项检查 ----------
def check_structure(report: Report, questions: list[dict]) -> bool:
    report.section("1. 问卷结构（题目与选项文字）")
    ok = report.check("题目数", len(EXPECTED_TITLES), len(questions))
    for n, title in EXPECTED_TITLES.items():
        actual = questions[n - 1]["title"] if n <= len(questions) else None
        ok &= report.check(f"第 {n} 题题目", title, actual)
    for n, texts in EXPECTED_OPTIONS.items():
        actual = [o["text"] for o in questions[n - 1].get("options") or []] if n <= len(questions) else None
        ok &= report.check(f"第 {n} 题选项", "、".join(texts), "、".join(actual or []))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="大学生运动习惯调查：模拟 15 位填写人并逐项核对（端到端测试）")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"服务地址（默认 {DEFAULT_BASE}）")
    parser.add_argument("--code", default=DEFAULT_CODE, help=f"问卷 shortCode（默认 {DEFAULT_CODE}）")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help=f"问卷创建者账号（默认 {DEFAULT_OWNER}，只用于读取统计）")
    parser.add_argument("--skip-stats", action="store_true", help="不核对统计（不需要创建者密码）")
    parser.add_argument("--report", help="把结果表另存为 Markdown 文件")
    args = parser.parse_args()
    code = args.code
    report = Report()

    # 读取问卷（用第一个填写人账号）
    first = Client(args.base)
    first.login("sport_u01", PASSWORD, register=True)
    status, survey = first.call("GET", f"/api/s/{code}")
    if status != 200 or not survey.get("questions"):
        raise SystemExit(f"无法读取问卷 {code}：{status} {survey}")
    print(f"问卷：{survey['title']}（{code}），提交策略 {survey['settings']['submissionPolicy']}，"
          f"{'匿名' if survey['settings']['allowAnonymous'] else '实名'}，正在收集：{survey['accepting']}")
    questions = survey["questions"]
    if not check_structure(report, questions):
        print(report.markdown())
        raise SystemExit("问卷结构与预期不一致，已停止（没有提交任何答卷）")

    # 登录全部填写人，先用路径预览核对路径；全部一致才提交
    clients = {}
    report.section("2. 路径（提交前用路径预览接口核对，服务器计算）")
    all_paths_ok = True
    for user, (answers, expected) in RESPONDENTS.items():
        c = first if user == "sport_u01" else Client(args.base)
        if c is not first:
            c.login(user, PASSWORD, register=True)
        clients[user] = c
        status, preview = c.call("POST", f"/api/s/{code}/path",
                                 {"answers": to_items(questions, with_skipped_q8(answers))})
        actual = numbers(questions, preview["path"]) if status == 200 else f"{status} {preview}"
        finished = status == 200 and preview["finished"] and not preview["errors"]
        all_paths_ok &= report.check(f"{user} 路径", fmt_path(expected),
                                     fmt_path(actual) if finished else f"未走到结尾：{actual}")
    if not all_paths_ok:
        print(report.markdown())
        raise SystemExit("有路径与预期不一致，已停止（没有提交任何答卷）")

    # 提交（已提交过的账号跳过），并核对实际保存的题目
    report.section("3. 提交与实际保存的题目（被跳过的题不应保存）")
    submitted = skipped = 0
    for user, (answers, expected) in RESPONDENTS.items():
        c = clients[user]
        _, view = c.call("GET", f"/api/s/{code}")
        if view["mySubmission"]["count"] > 0:
            skipped += 1
        else:
            status, body = c.call("POST", f"/api/s/{code}/responses", {"answers": to_items(questions, answers)})
            if not report.check(f"{user} 提交", 201, status):
                continue
            submitted += 1
        # 用本人最新一份答卷（latest 策略下由接口返回）核对实际保存了哪些题
        _, view = c.call("GET", f"/api/s/{code}")
        saved = numbers(questions, [a["questionId"] for a in view["mySubmission"]["latestAnswers"] or []])
        should_save = [n for n in expected if n in answers and answers[n] is not None]
        report.check(f"{user} 保存的题目", fmt_path(should_save), fmt_path(saved))
    print(f"本次提交 {submitted} 份；已提交过而跳过 {skipped} 份")

    # 不合法答卷：全部被拒绝，且该账号没有任何答卷
    report.section("4. 不合法答卷（应全部被拒绝且不保存）")
    bad = Client(args.base)
    bad.login(INVALID_USER, PASSWORD, register=True)
    for name, answers, message in INVALID_CASES:
        status, body = bad.call("POST", f"/api/s/{code}/responses", {"answers": to_items(questions, answers)})
        actual_msg = (body.get("errors") or [{}])[0].get("message") if body else None
        report.check(f"{name}：状态码", 422, status)
        report.check(f"{name}：提示", message, actual_msg)
    _, view = bad.call("GET", f"/api/s/{code}")
    report.check(f"{INVALID_USER} 保存的答卷数", 0, view["mySubmission"]["count"])

    # 统计：人工期望（15 人）+ 其他已有答卷（运行时从答卷列表读取）
    if args.skip_stats:
        print("已按 --skip-stats 跳过统计核对")
    else:
        password = os.environ.get("SURVEY_OWNER_PASSWORD") or getpass.getpass(
            f"请输入创建者 {args.owner} 的密码（只用于读取统计，不会保存或打印）：")
        owner = Client(args.base)
        owner.login(args.owner, password, register=False)
        check_stats(report, owner, survey, questions)

    print(report.markdown())
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report.markdown().lstrip() + "\n")
        print(f"结果表已写入 {args.report}")
    return 1 if report.failures else 0


def check_stats(report: Report, owner: Client, survey: dict, questions: list[dict]) -> None:
    # 找到问卷 id（创建者的问卷列表），读取统计与答卷列表
    _, mine = owner.call("GET", "/api/surveys")
    survey_id = next(s["id"] for s in mine if s["shortCode"] == survey["shortCode"])
    _, stats = owner.call("GET", f"/api/surveys/{survey_id}/stats")
    responses, offset = [], 0
    while True:
        _, page = owner.call("GET", f"/api/surveys/{survey_id}/responses?offset={offset}&limit=100")
        responses += page["items"]
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            break

    # 其他答卷：不是本脚本的 15 人（也不是不合法答卷账号——它没有任何答卷）
    others = [r for r in responses if r.get("username") not in RESPONDENTS]
    pos = {q["id"]: i + 1 for i, q in enumerate(questions)}
    text = {o["id"]: o["text"] for q in questions for o in q.get("options") or []}
    extra = {n: {"answers": 0, "people": set(), "options": {}, "sum": 0} for n in range(1, 9)}
    for r in others:
        for a in r["answers"]:
            e = extra[pos[a["questionId"]]]
            e["answers"] += 1
            e["people"].add(r.get("username") or r["id"])
            values = a["value"] if isinstance(a["value"], list) else [a["value"]]
            for v in values:
                if v in text:
                    e["options"][text[v]] = e["options"].get(text[v], 0) + 1
            if isinstance(a["value"], (int, float)) and not isinstance(a["value"], bool):
                e["sum"] += a["value"]
    other_people = {r.get("username") or r["id"] for r in others}

    title = f"5. 统计（期望 = 人工计算的 15 人 + 其他已有答卷 {len(others)} 份，运行时从答卷列表读取）"
    report.section(title)
    report.check("总答卷数", EXPECTED_STATS["totalResponses"] + len(others), stats["totalResponses"])
    report.check("填写人数", EXPECTED_STATS["totalRespondents"] + len(other_people), stats["totalRespondents"])
    for n, exp in EXPECTED_STATS["questions"].items():
        q = stats["questions"][n - 1]
        e = extra[n]
        answer_count = exp["answerCount"] + e["answers"]
        report.check(f"第 {n} 题 答卷数", answer_count, q["answerCount"])
        report.check(f"第 {n} 题 作答人数", exp["respondentCount"] + len(e["people"]), q["respondentCount"])
        if "options" in exp:
            actual = {o["text"]: o["count"] for o in q["options"]}
            for opt, count in exp["options"].items():
                report.check(f"第 {n} 题「{opt}」", count + e["options"].get(opt, 0), actual.get(opt))
        if "sum" in exp:
            expected_avg = round((exp["sum"] + e["sum"]) / answer_count, 4)
            report.check(f"第 {n} 题 平均值", expected_avg, round(q["average"], 4))
        if n == 8:
            report.check("第 8 题 填写内容条数", answer_count, q["itemsTotal"])


if __name__ == "__main__":
    sys.exit(main())
