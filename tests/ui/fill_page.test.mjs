// 界面测试（9c 填写页，滚动式）：未登录跳转与回到问卷、逐题展开与跳转、收起与恢复、请求先后顺序、
// 错误提示、跳过选填题、提交与感谢页、latest 预填、已关闭提示、创建者预览草稿、手机尺寸。
import { buildFruitSurvey, scenario } from "./helpers.mjs";

await scenario("填写页", async (t) => {
  const { browser: b, assert } = t;
  const nth = (k) => `#questions .question:nth-child(${k})`;
  const visible = () => b.eval(`[...document.querySelectorAll("#questions .question")].filter((n) => !n.hidden)
    .map((n) => n.querySelector(".q-number").textContent.replace(".", ""))`);
  const waitVisible = (nums, what) =>
    b.waitFor(`JSON.stringify([...document.querySelectorAll("#questions .question")].filter((n) => !n.hidden)
      .map((n) => n.querySelector(".q-number").textContent.replace(".", ""))) === ${JSON.stringify(JSON.stringify(nums))}`,
      `${what}（期望显示第 ${nums.join("、")} 题）`);
  const submitShown = () => b.eval(`!document.getElementById("submit-bar").hidden`);
  const progress = () => b.eval(`document.getElementById("progress-bar").style.width`);

  // 创建者：示例问卷（latest 策略、匿名）
  const owner = await t.login("ui_owner");
  const s = await buildFruitSurvey(t, owner, { submissionPolicy: "latest", allowAnonymous: true });
  await t.logout();
  await t.api("POST", "/api/auth/register", { username: "ui_filler", password: "uitest123" });

  // 1. 未登录打开问卷链接 → 登录页 → 登录后回到问卷
  await b.goto(`${t.base}/survey/${s.shortCode}`);
  await b.waitFor(`location.pathname === "/login"`, "跳转到登录页");
  assert.equal(await t.location(), `/login?next=${encodeURIComponent(`/survey/${s.shortCode}`)}`);
  assert.equal(await t.text("#next-hint"), "登录后将自动打开你要填写的问卷");
  await t.shot("未登录跳转登录页");
  await t.type("#username", "ui_filler");
  await t.type("#password", "uitest123");
  await t.click("#submit");
  await b.waitFor(`location.pathname === "/survey/${s.shortCode}"`, "登录后回到问卷");
  t.step("未登录访问问卷链接跳转登录页，登录后自动回到原问卷");

  // 2. 开始只显示第一题；匿名提示；进度 0%
  await waitVisible(["1"], "初始只显示第一题");
  assert.equal(await progress(), "0%");
  assert.ok((await t.texts("#notices .notice")).includes("本问卷为匿名问卷，创建者看不到你的身份"));
  t.step("开始只显示第 1 题，显示匿名提示，进度 0%");
  await t.shot("初始只显示第一题");

  // 3. 选“不喜欢” → 第 5 题出现（第 2~4 题被跳过，题号保持原编号）；选填题显示“跳过此题”
  await t.click(`${nth(1)} .option`, "不喜欢");
  await waitVisible(["1", "5"], "选“不喜欢”跳到第 5 题");
  assert.equal(await b.eval(`!document.querySelector("${nth(5)} .skip-btn").hidden`), true);
  t.step("单选点击后立即计算：选“不喜欢”跳到第 5 题，第 2～4 题不显示，题号保持原编号");
  await t.shot("选不喜欢跳到第5题");

  // 4. 改回“喜欢” → 第 5 题收起，第 2 题出现
  await t.click(`${nth(1)} .option`, "喜欢");
  await waitVisible(["1", "2"], "改选“喜欢”");
  t.step("修改前面的答案后，不再需要的题收起，新需要的题出现");

  // 5. 多选（停止操作片刻后计算）：选了榴莲 → 第 3 题
  await t.click(`${nth(2)} .option`, "苹果");
  await t.click(`${nth(2)} .option`, "榴莲");
  assert.deepEqual(await visible(), ["1", "2"], "多选不应立即计算");
  await waitVisible(["1", "2", "3"], "多选停顿后计算，选了榴莲进入第 3 题");
  t.step("多选在停止操作片刻后才计算：选了榴莲进入第 3 题");

  // 6. 文本太短 → 错误提示在题目旁、题目边框变红
  await t.type(`${nth(3)} textarea`, "好吃", true);
  await b.waitFor(`document.querySelector("${nth(3)}").classList.contains("has-error")`, "第 3 题显示错误");
  assert.equal(await t.text(`${nth(3)} .q-error`), "至少 5 个字（当前 2 个）");
  t.step("填写不合法时，错误提示显示在对应题目下方，题目边框变红");
  await t.shot("文本太短的错误提示");

  // 7. 改正 → 第 4 题出现；填 0 → 结束问卷，出现“提交”，进度 100%
  await t.type(`${nth(3)} textarea`, "闻着臭吃着香", true);
  await waitVisible(["1", "2", "3", "4"], "改正后出现第 4 题");
  assert.equal(await b.eval(`document.querySelector("${nth(3)}").classList.contains("has-error")`), false);
  await t.type(`${nth(4)} input`, "0", true);
  await b.waitFor(`!document.getElementById("submit-bar").hidden`, "每周 0 次 → 结束，出现提交按钮");
  assert.deepEqual(await visible(), ["1", "2", "3", "4"]);
  assert.equal(await progress(), "100%");
  t.step("数字题填 0 → 结束问卷，第 5 题不显示，底部出现“提交”，进度 100%");
  await t.shot("走到结尾出现提交");

  // 8. 改成 7 → 第 5 题出现、提交按钮消失；点“跳过此题”→ 结束
  await t.type(`${nth(4)} input`, "7", true);
  await waitVisible(["1", "2", "3", "4", "5"], "改成 7 后出现第 5 题");
  assert.equal(await submitShown(), false);
  await t.click(`${nth(5)} .skip-btn`);
  await b.waitFor(`!document.getElementById("submit-bar").hidden`, "跳过选填题后出现提交");
  t.step("选填题可以“跳过此题”，之后出现“提交”");

  // 9. 收起的题内容保留：取消榴莲 → 第 3 题收起；再选回 → 第 3 题恢复原来的内容
  await t.click(`${nth(2)} .option`, "榴莲");
  await waitVisible(["1", "2", "4", "5"], "取消榴莲后第 3 题收起");
  await t.click(`${nth(2)} .option`, "榴莲");
  await waitVisible(["1", "2", "3", "4", "5"], "选回榴莲后第 3 题恢复");
  assert.equal(await b.eval(`document.querySelector("${nth(3)} textarea").value`), "闻着臭吃着香");
  t.step("收起的题内容暂存在页面上，改回去时恢复");

  // 10. 请求先后顺序：先发出的预览请求故意延迟返回，只采用最后一次请求的结果
  await b.eval(`(() => {
    const original = window.fetch; const delays = [1200, 0]; let n = 0;
    window.__restoreFetch = () => { window.fetch = original; };
    window.fetch = (url, init) => String(url).endsWith("/path")
      ? new Promise((r) => setTimeout(r, delays[n++] ?? 0)).then(() => original(url, init))
      : original(url, init);
    return true; })()`);
  await t.click(`${nth(1)} .option`, "不喜欢");   // 第一次请求：延迟 1.2 秒才发出、最后返回
  await t.click(`${nth(1)} .option`, "喜欢");     // 第二次请求：立即返回
  await b.sleep(1800);
  assert.deepEqual(await visible(), ["1", "2", "3", "4", "5"], "较早发出的“不喜欢”结果返回更晚，不能覆盖最后一次的结果");
  await b.eval(`window.__restoreFetch(); true`);
  t.step("快速连续修改时只采用最后一次预览请求的结果，较早的请求返回后被丢弃");

  // 11. 提交 → 感谢页；只保存路径上的题
  await b.waitFor(`!document.getElementById("submit-btn").disabled`, "提交按钮可用");
  await t.click("#submit-btn");
  await b.waitFor(`document.querySelector(".thanks")`, "显示感谢页");
  assert.ok((await t.text(".thanks")).includes("感谢填写！"));
  const list = (await t.api("GET", `/api/surveys/${s.id}/responses`, undefined, owner)).body;
  assert.equal(list.total, 1);
  assert.deepEqual(list.items[0].answers.map((a) => a.questionId), [s.q[0], s.q[1], s.q[2], s.q[3]]);  // 第 5 题跳过未答
  assert.ok(!("username" in list.items[0]), "匿名问卷的答卷列表不含填写人");
  t.step("提交成功显示感谢页；保存的答案只含路径上作答的题");
  await t.shot("感谢页");

  // 12. latest 策略：再次打开时预填上次答案，并直接展开到上次答过的位置
  // 上次第 5 题是跳过的（没有存答案），所以展开到第 5 题停下，等待作答或跳过
  await b.goto(`${t.base}/survey/${s.shortCode}`);
  await waitVisible(["1", "2", "3", "4", "5"], "预填后直接展开到上次答过的位置");
  assert.equal(await submitShown(), false);
  assert.equal(await b.eval(`!document.querySelector("${nth(5)} .skip-btn").hidden`), true);
  assert.equal(await b.eval(`document.querySelector("${nth(3)} textarea").value`), "闻着臭吃着香");
  assert.equal(await b.eval(`document.querySelector("${nth(4)} input").value`), "7");
  assert.ok((await t.texts("#notices .notice")).some((x) => x.startsWith("已为你填入上次提交的答案")));
  t.step("latest 策略再次打开时预填上次的答案，并直接展开到上次答过的位置");
  await t.shot("latest预填");

  // 13. 已关闭：只显示提示，不显示题目
  await t.api("POST", `/api/surveys/${s.id}/close`, undefined, owner);
  await b.goto(`${t.base}/survey/${s.shortCode}`);
  await b.waitFor(`document.querySelector("#notices .notice.warn")`, "显示关闭提示");
  assert.ok((await t.texts("#notices .notice.warn")).includes("问卷已关闭，不再接受填写"));
  assert.equal(await b.eval(`document.querySelectorAll("#questions .question").length`), 0);
  t.step("问卷已关闭时显示提示，不显示题目");
  await t.shot("已关闭提示");

  // 14. 创建者预览草稿：可以逐题预览跳转，不能提交
  const draft = await buildFruitSurvey(t, owner, {}, { publish: false });
  await t.logout();
  await t.login("ui_owner");
  await b.goto(`${t.base}/survey/${draft.shortCode}`);
  await waitVisible(["1"], "预览模式显示第一题");
  assert.ok((await t.texts("#notices .notice.warn")).includes("预览模式：问卷尚未发布，不能提交"));
  await t.click(`${nth(1)} .option`, "不喜欢");
  await waitVisible(["1", "5"], "预览模式也能计算跳转");
  await t.click(`${nth(5)} .skip-btn`);
  await b.waitFor(`!document.getElementById("submit-bar").hidden`, "预览走到结尾");
  assert.equal(await b.eval(`document.getElementById("submit-btn").disabled`), true);
  t.step("创建者预览草稿：可以逐题预览跳转，提交按钮禁用");
  await t.shot("创建者预览草稿");

  await b.size(390, 800);
  await b.goto(`${t.base}/survey/${draft.shortCode}`);
  await t.click(`${nth(1)} .option`, "喜欢");
  await waitVisible(["1", "2"], "手机尺寸下逐题展开");
  await t.shot("填写页-手机");
  t.step("手机尺寸显示正常");
});
