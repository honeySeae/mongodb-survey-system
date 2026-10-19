"""测试共用：通过接口搭建问卷（第七步填写、第八步统计的测试都会用到）。"""


def as_update(q: dict, **changes) -> dict:
    """把返回的题目转成修改请求体（保留选项 id）。"""
    body = {"type": q["type"], "title": q["title"], "validation": q["validation"]}
    if "options" in q:
        body["options"] = [{"id": o["id"], "text": o["text"]} for o in q["options"]]
    if "logic" in q:
        body["logic"] = q["logic"]
    body.update(changes)
    return body


def _ok(resp, status=200):
    assert resp.status_code == status, resp.json()
    return resp.json()


def build_fruit_survey(client, headers, publish=True, **settings) -> dict:
    """搭建设计文档 3.4 的示例问卷，返回 {"survey": 问卷, "q": [5 道题], "o": {选项文字: 选项 id}}。

    q1 单选（不喜欢 → q5）；q2 多选 1~3 项（含榴莲 → q3，否则 → q4）；q3 文本 5~200 字选填；
    q4 数字 0~50 整数（0 → END）；q5 文本选填。
    """
    body = {"title": "水果偏好调查", "description": "了解大家吃水果的习惯", **settings}
    sid = _ok(client.post("/api/surveys", json=body, headers=headers), 201)["id"]

    def add(**q):
        return _ok(client.post(f"/api/surveys/{sid}/questions", json=q, headers=headers), 201)

    add(type="single_choice", title="你喜欢吃水果吗？",
        options=[{"text": "喜欢"}, {"text": "不喜欢"}], validation={"required": True})
    add(type="multiple_choice", title="你喜欢哪些水果？",
        options=[{"text": t} for t in ("苹果", "香蕉", "西瓜", "榴莲")],
        validation={"required": True, "minSelect": 1, "maxSelect": 3})
    add(type="text", title="为什么喜欢榴莲？",
        validation={"required": False, "minLength": 5, "maxLength": 200})
    add(type="number", title="你每周吃几次水果？",
        validation={"required": True, "min": 0, "max": 50, "integerOnly": True})
    s = add(type="text", title="其他建议", validation={"required": False, "maxLength": 500})
    q1, q2, q3, q4, q5 = s["questions"]
    o = {opt["text"]: opt["id"] for q in (q1, q2) for opt in q["options"]}

    def set_logic(q, rules, default=None):
        logic = {"rules": [{"when": w, "goto": g} for w, g in rules], "defaultNext": default}
        return _ok(client.put(f"/api/surveys/{sid}/questions/{q['id']}",
                              json=as_update(q, logic=logic), headers=headers))

    set_logic(q1, [({"op": "eq", "value": o["不喜欢"]}, q5["id"])])
    set_logic(q2, [({"op": "contains", "value": o["榴莲"]}, q3["id"])], default=q4["id"])
    s = set_logic(q4, [({"op": "eq", "value": 0}, "END")])
    if publish:
        s = _ok(client.post(f"/api/surveys/{sid}/publish", headers=headers))
    return {"survey": s, "q": s["questions"], "o": o}
