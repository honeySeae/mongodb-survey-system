// 界面测试（9b 编辑页）：跳转规则编辑器、校验错误标注、调整顺序被拒、添加题目、发布后只读、手机尺寸。
import { scenario } from "./helpers.mjs";

await scenario("编辑页", async (t) => {
  const { browser: b, assert } = t;
  const token = await t.login("ui_editor");
  const created = await t.api("POST", "/api/surveys", { title: "水果偏好调查", description: "了解大家吃水果的习惯" }, token);
  const sid = created.body.id;
  const add = (q) => t.api("POST", `/api/surveys/${sid}/questions`, q, token);
  await add({ type: "single_choice", title: "你喜欢吃水果吗？", options: [{ text: "喜欢" }, { text: "不喜欢" }], validation: { required: true } });
  await add({ type: "multiple_choice", title: "你喜欢哪些水果？", options: [{ text: "苹果" }, { text: "香蕉" }, { text: "榴莲" }], validation: { required: true, minSelect: 1, maxSelect: 2 } });
  await add({ type: "number", title: "你每周吃几次水果？", validation: { required: true, min: 0, max: 50, integerOnly: true } });

  await b.goto(`${t.base}/surveys`);
  await t.shot("我的问卷列表");

  await b.goto(`${t.base}/surveys/${sid}/edit`);
  await b.waitFor(`document.querySelectorAll("#questions > .question").length === 3`, "显示 3 道题");
  assert.deepEqual(await t.texts(".q-hint"), ["单选", "多选，至少选 1 项，最多选 2 项", "请输入 0–50 之间的整数"]);
  t.step("编辑页显示 3 道题，作答说明由校验规则自动生成");
  await t.shot("编辑页");

  // 第 1 题加跳转规则：选了“不喜欢”就跳到第 3 题
  await t.click(".q-tools button", "编辑");
  await t.click(".question.editing button", "＋ 添加跳转规则");
  const options = await b.eval(`[...document.querySelectorAll(".editor-rule select")].map((s) => [...s.options].map((o) => o.textContent))`);
  assert.deepEqual(options[0], ["选择了", "选择了其中之一"]);
  assert.deepEqual(options[1], ["喜欢", "不喜欢"]);
  assert.deepEqual(options[2], ["第 2 题：你喜欢哪些水果？", "第 3 题：你每周吃几次水果？", "结束问卷"]);
  t.step("跳转规则用下拉框设置；目标只列出后面的题和“结束问卷”");
  await b.eval(`(() => { const s = document.querySelectorAll(".editor-rule select");
    s[1].value = s[1].options[1].value; s[1].dispatchEvent(new Event("change"));
    s[2].value = s[2].options[1].value; s[2].dispatchEvent(new Event("change")); return true; })()`);
  await t.shot("设置跳转规则");
  await t.click(".question.editing button", "保存");
  await b.waitFor(`!document.querySelector(".question.editing")`, "保存后关闭编辑器");
  const saved = (await t.api("GET", `/api/surveys/${sid}`, undefined, token)).body;
  const [q1, , q3] = saved.questions;
  assert.deepEqual(q1.logic, { rules: [{ when: { op: "eq", value: q1.options[1].id }, goto: q3.id }], defaultNext: null });
  t.step("保存后数据库中的跳转规则正确（不喜欢 → 第 3 题）");

  // 校验错误：多选“至少选 5 项”
  await b.eval(`document.querySelectorAll(".q-tools")[1].querySelector("button").click()`);
  await t.type('.question.editing [data-field="validation.minSelect"]', "5");
  await t.click(".question.editing button", "保存");
  await b.waitFor(`document.querySelector(".question.editing .notice.error")`, "显示错误");
  const errors = await t.texts(".question.editing .notice.error li");
  assert.ok(errors.includes("第 2 题：最少选择数（5）不能大于选项数（3）"), errors.join(" | "));
  assert.deepEqual(await b.eval(`[...document.querySelectorAll(".question.editing .invalid")].map((n) => n.dataset.field)`), ["validation.minSelect"]);
  t.step("校验错误显示在题目上方，对应输入框标红");
  await t.shot("校验错误");
  await t.click(".question.editing button", "取消");

  // 第 3 题上移两次：第 1 题的规则会变成往前跳，第二次被拒绝
  await b.eval(`document.querySelectorAll(".q-tools")[2].querySelectorAll("button")[1].click()`);
  await b.waitFor(`document.querySelectorAll(".q-tools")[1].closest(".question").textContent.includes("每周")`, "第一次上移成功");
  await b.eval(`document.querySelectorAll(".q-tools")[1].querySelectorAll("button")[1].click()`);
  await b.waitFor(`document.querySelector("#questions-message .notice.error")`, "显示排序错误");
  assert.deepEqual(await t.texts(".q-error:not([hidden])"), ["第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）"]);
  t.step("调整顺序导致往前跳时被拒绝，错误标在对应题目上");
  await t.shot("调整顺序被拒");

  // 添加文本题
  await t.click("#add-bar button", "＋ 文本填空");
  await t.type('.question.editing [data-field="title"]', "其他建议");
  await t.click(".question.editing button", "添加");
  // 只数 #questions 的直接子元素：编辑器里的“预览”也是 .question，不能算进去
  await b.waitFor(`!document.querySelector(".question.editing") && document.querySelectorAll("#questions > .question").length === 4`,
    "添加第 4 题（编辑器关闭、列表中有 4 道题）");
  t.step("添加文本填空题");

  // 发布后只读
  const published = await t.api("POST", `/api/surveys/${sid}/publish`, undefined, token);
  assert.equal(published.status, 200, JSON.stringify(published.body));
  await b.goto(`${t.base}/surveys/${sid}/edit`);
  await b.waitFor(`document.querySelectorAll("#questions > .question").length === 4`, "发布后显示题目");
  assert.equal(await b.eval(`document.querySelectorAll(".q-tools").length`), 0);
  assert.equal(await b.eval(`document.getElementById("add-bar").hidden`), true);
  assert.equal(await b.eval(`document.querySelector('input[name="s-policy"]').disabled`), true);
  t.step("发布后题目只读，提交策略和匿名设置锁定");
  await t.shot("发布后");

  await b.size(390, 800);
  await b.goto(`${t.base}/surveys/${sid}/edit`);
  await t.shot("编辑页-手机");
  t.step("手机尺寸显示正常");
});
