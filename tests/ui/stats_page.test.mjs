// 界面测试（9d 统计页）：答卷数与填写人数、柱状条人数和百分比、平均值、填写人用户名、
// 填空题“加载更多”、答卷列表（选项显示为文字、加载更多）、匿名问卷不显示填写人、手机尺寸。
//
// 固定数据（all 策略，每个数字都可以手工算出）：
//   u_zhang : 喜欢 → [苹果, 榴莲] → "闻着臭吃着香" → 7 → "多吃水果"
//   u_li    : 喜欢 → [苹果, 香蕉] → 3
//   u_wang  : 不喜欢 → "不爱吃"；之后又提交 22 次 不喜欢 → "意见1"…"意见22"（用于测试加载更多）
//   u_zhao  : 喜欢 → [香蕉] → 0
//   合计 26 份答卷、4 位填写人；第 1 题 喜欢 3 / 不喜欢 23；第 4 题平均 (7+3+0)/3 = 3.33；第 5 题 24 条
import { buildFruitSurvey, scenario } from "./helpers.mjs";

await scenario("统计页", async (t) => {
  const { browser: b, assert } = t;
  const register = async (name) => {
    await t.api("POST", "/api/auth/register", { username: name, password: "uitest123" });
    return (await t.api("POST", "/api/auth/login", { username: name, password: "uitest123" })).body.accessToken;
  };
  const submit = async (s, token, answers) => {
    const items = Object.entries(answers).map(([questionId, value]) => ({ questionId, value }));
    const r = await t.api("POST", `/api/s/${s.shortCode}/responses`, { answers: items }, token);
    assert.equal(r.status, 201, JSON.stringify(r.body));
  };
  const card = (n) => `#question-stats .stat-q:nth-child(${n})`;

  const owner = await register("ui_stats_owner");
  const s = await buildFruitSurvey(t, owner, { submissionPolicy: "all" });
  const [q1, q2, q3, q4, q5] = s.q;
  const o = s.o;
  const users = {};
  for (const name of ["u_zhang", "u_li", "u_wang", "u_zhao"]) users[name] = await register(name);
  await submit(s, users.u_zhang, { [q1]: o["喜欢"], [q2]: [o["苹果"], o["榴莲"]], [q3]: "闻着臭吃着香", [q4]: 7, [q5]: "多吃水果" });
  await submit(s, users.u_li, { [q1]: o["喜欢"], [q2]: [o["苹果"], o["香蕉"]], [q4]: 3 });
  await submit(s, users.u_wang, { [q1]: o["不喜欢"], [q5]: "不爱吃" });
  await submit(s, users.u_zhao, { [q1]: o["喜欢"], [q2]: [o["香蕉"]], [q4]: 0 });
  for (let i = 1; i <= 22; i++) await submit(s, users.u_wang, { [q1]: o["不喜欢"], [q5]: `意见${i}` });

  // 以创建者身份打开统计页
  await t.login("ui_stats_owner");
  await b.goto(`${t.base}/surveys/${s.id}/stats`);
  await b.waitFor(`document.querySelectorAll("#question-stats .stat-q").length === 5`, "显示 5 道题的统计");
  assert.deepEqual(await t.texts("#totals .stat-number"), ["26答卷数", "4填写人数"]);
  assert.ok((await t.text("#scope")).startsWith("统计口径：全部答卷（含同一人的多次提交）"));
  t.step("顶部显示答卷数 26、填写人数 4 和统计口径");

  assert.deepEqual(await t.texts(`${card(1)} .bar-value`), ["3 人（11.5%）", "23 人（88.5%）"]);
  assert.equal(await t.text(`${card(1)} .q-hint`), "单选题 · 答卷数 26 · 作答人数 4");
  assert.deepEqual(await t.texts(`${card(2)} .bar-value`), ["2 次（66.7%）", "2 次（66.7%）", "0 次（0%）", "1 次（33.3%）"]);
  assert.equal(await b.eval(`document.querySelector("${card(1)} .bar-fill").style.width`), "11.5%");
  // 同一道题各选项的底槽一样长，柱子才能直接比较
  const trackWidths = await b.eval(`[...document.querySelectorAll("${card(2)} .bar-track")].map((n) => n.getBoundingClientRect().width)`);
  assert.equal(new Set(trackWidths).size, 1, `底槽宽度不一致：${trackWidths}`);
  t.step("单选、多选用横向柱状条显示人数（次数）和百分比，没人选的选项显示 0");

  assert.equal(await t.text(`${card(4)} .stat-average b`), "3.33");
  assert.deepEqual(await t.texts(`${card(4)} .stat-value`), ["0", "3", "7"]);
  assert.deepEqual(await t.texts(`${card(3)} .stat-user`), ["u_zhang"]);
  t.step("数字题显示平均值 3.33 和全部填写内容；实名问卷显示填写人用户名");
  await t.shot("统计页");

  // 第 5 题共 24 条：先显示 20 条，加载更多后显示全部
  assert.equal(await b.eval(`document.querySelectorAll("${card(5)} .stat-item").length`), 20);
  assert.equal(await t.text(`${card(5)} .btn.link`), "加载更多（已显示 20 / 24）");
  await t.click(`${card(5)} .btn.link`);
  await b.waitFor(`document.querySelectorAll("${card(5)} .stat-item").length === 24`, "加载更多后显示 24 条");
  assert.equal(await b.eval(`document.querySelector("${card(5)} .btn.link").hidden`), true);
  t.step("填空题先显示 20 条，点“加载更多”后显示全部 24 条");
  await t.shot("加载更多");

  // 答卷列表
  await t.click("#tab-responses");
  await b.waitFor(`document.querySelectorAll("#responses .resp-card").length === 20`, "答卷列表显示 20 份");
  assert.ok((await t.text("#responses-summary")).startsWith("共 26 份答卷"));
  const last = await b.eval(`[...document.querySelectorAll("#responses .resp-card")].at(-1).textContent`);
  assert.ok(!last.includes("o_"), "选项应显示为文字而不是 id");
  await t.click("#responses-more");
  await b.waitFor(`document.querySelectorAll("#responses .resp-card").length === 26`, "加载更多后显示 26 份");
  const oldest = await b.eval(`[...document.querySelectorAll("#responses .resp-card")].at(-1).innerText`);
  assert.ok(oldest.includes("第 1 份") && oldest.includes("u_zhang") && oldest.includes("苹果、榴莲") && oldest.includes("闻着臭吃着香"), oldest);
  t.step("答卷列表按时间从新到旧显示，选项显示为文字，可加载更多，实名问卷显示填写人");
  await t.shot("答卷列表");

  // 匿名问卷：统计和答卷列表中都不出现填写人
  const anon = await buildFruitSurvey(t, owner, { allowAnonymous: true });
  await submit(anon, users.u_zhang, { [anon.q[0]]: anon.o["不喜欢"], [anon.q[4]]: "匿名的意见" });
  await b.goto(`${t.base}/surveys/${anon.id}/stats`);
  await b.waitFor(`document.querySelectorAll("#question-stats .stat-q").length === 5`, "匿名问卷统计");
  await t.click("#tab-responses");
  await b.waitFor(`document.querySelectorAll("#responses .resp-card").length === 1`, "匿名问卷答卷列表");
  const pageText = await b.eval("document.body.innerText");
  assert.ok(!pageText.includes("u_zhang"), "匿名问卷不应出现填写人用户名");
  assert.equal(await b.eval(`document.querySelectorAll(".stat-user").length`), 0);
  assert.ok(pageText.includes("匿名的意见"));
  t.step("匿名问卷的统计和答卷列表都不显示填写人");
  await t.shot("匿名问卷答卷列表");

  await b.size(390, 800);
  await b.goto(`${t.base}/surveys/${s.id}/stats`);
  await b.waitFor(`document.querySelectorAll("#question-stats .stat-q").length === 5`, "手机尺寸统计页");
  await t.shot("统计页-手机");
  t.step("手机尺寸显示正常");
});
