// 界面测试的公共工具：参数、启动浏览器、通过页面调用接口准备数据、点击与输入、断言与结果输出。
import assert from "node:assert/strict";
import { launch } from "./cdp.mjs";

/** 由 tests/test_ui.py 以命令行参数传入：服务地址、Chrome 路径、截图目录、浏览器配置目录、调试端口。 */
export function args() {
  const [, , base, chrome, shots, profile, port] = process.argv;
  return { base, chrome, shots, profile, port: Number(port) };
}

const js = (value) => JSON.stringify(value);

/**
 * 运行一个界面测试场景：启动浏览器 → 执行 steps(ctx) → 检查页面没有 JS 异常 → 关闭浏览器。
 * 每完成一步打印一行“✓ 说明”（用于整理测试用例）；失败时打印原因并以非 0 退出码结束。
 */
export async function scenario(name, steps) {
  const a = args();
  const browser = await launch({ chrome: a.chrome, profileDir: a.profile, port: a.port });
  let shotNo = 0;
  const ctx = {
    ...a,
    browser,
    assert,
    step(text) { console.log(`✓ ${text}`); },
    async shot(label) {
      shotNo += 1;
      await browser.shot(a.shots, `${String(shotNo).padStart(2, "0")}-${label}`);
    },
    /** 在页面中调用后端接口（使用页面同源的 fetch），返回 { status, body }。 */
    api(method, path, body, token) {
      const headers = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const init = { method, headers };
      if (body !== undefined) init.body = JSON.stringify(body);
      return browser.eval(`fetch(${js(path)}, ${js(init)})
        .then(async (r) => ({ status: r.status, body: r.status === 204 ? null : await r.json() }))`);
    },
    /** 注册并登录，返回令牌；同时写入浏览器 localStorage，使页面处于登录状态。 */
    async login(username, password = "uitest123") {
      await this.api("POST", "/api/auth/register", { username, password });
      const r = await this.api("POST", "/api/auth/login", { username, password });
      assert.equal(r.status, 200, `登录失败：${js(r.body)}`);
      await browser.eval(`localStorage.setItem("survey.token", ${js(r.body.accessToken)});
        localStorage.setItem("survey.user", ${js(js(r.body.user))}); true`);
      return r.body.accessToken;
    },
    async logout() { await browser.eval("localStorage.clear(); true"); },
    /** 点击第一个文字完全匹配的元素（text 省略时点击第一个匹配选择器的元素）。 */
    click(selector, text) {
      const match = text === undefined ? "true" : `x.textContent.trim() === ${js(text)}`;
      return browser.eval(`(() => {
        const n = [...document.querySelectorAll(${js(selector)})].find((x) => ${match});
        if (!n) throw new Error("找不到元素 " + ${js(`${selector} ${text ?? ""}`)});
        n.click(); return true; })()`);
    },
    /** 给输入框赋值并触发 input/change；blur 为 true 时再触发 blur（模拟离开输入框）。 */
    type(selector, value, blur = false) {
      return browser.eval(`(() => {
        const n = document.querySelector(${js(selector)});
        if (!n) throw new Error("找不到输入框 " + ${js(selector)});
        n.value = ${js(value)};
        n.dispatchEvent(new Event("input", { bubbles: true }));
        n.dispatchEvent(new Event("change", { bubbles: true }));
        if (${js(blur)}) n.dispatchEvent(new Event("blur"));
        return true; })()`);
    },
    text: (selector) => browser.eval(`(document.querySelector(${js(selector)}) || {}).textContent || ""`),
    texts: (selector) => browser.eval(`[...document.querySelectorAll(${js(selector)})].map((n) => n.textContent.trim())`),
    location: () => browser.eval("location.pathname + location.search"),
    /** 页面上不得出现文字 "null"（原生 append 误传 null 的典型症状）。 */
    async assertNoNullText() {
      const where = await browser.eval(`[...document.querySelectorAll("body *")].filter((n) =>
        [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim() === "null"))
        .map((n) => n.className || n.tagName)`);
      assert.deepEqual(where, [], `页面中出现文字 null：${where}`);
    },
  };

  let failed = null;
  try {
    await browser.size(1100, 900);
    await browser.goto(`${a.base}/login`);
    await steps(ctx);
    await ctx.assertNoNullText();
    assert.deepEqual(browser.errors, [], "页面中出现 JS 异常或 console.error");
  } catch (e) {
    failed = e;
    // 失败现场：截图、当前地址、页面文字、失败的请求，便于排查
    try {
      await ctx.shot("失败现场");
      console.log("失败时地址：", await ctx.location());
      console.log("失败时页面文字：", (await browser.eval("document.body.innerText")).slice(0, 600));
      console.log("失败的请求：", browser.network);
    } catch { /* 浏览器可能已不可用 */ }
  } finally {
    browser.close();
  }
  if (failed) {
    console.log(`✗ ${name} 失败：${failed.message}`);
    if (browser.errors.length) console.log("页面错误：", browser.errors);
    process.exit(1);
  }
  console.log(`ok ${name}`);
}

/** 通过接口搭建设计文档 3.4 的示例问卷（与 tests/builders.py 一致），返回 { id, shortCode, q: [题目 id], o: {选项文字: id} }。 */
export async function buildFruitSurvey(ctx, token, settings = {}, { publish = true } = {}) {
  const ok = (r, status = 200) => {
    assert.equal(r.status, status, js(r.body));
    return r.body;
  };
  const s = ok(await ctx.api("POST", "/api/surveys",
    { title: "水果偏好调查", description: "了解大家吃水果的习惯", ...settings }, token), 201);
  const add = async (q) => ok(await ctx.api("POST", `/api/surveys/${s.id}/questions`, q, token), 201);
  await add({ type: "single_choice", title: "你喜欢吃水果吗？", options: [{ text: "喜欢" }, { text: "不喜欢" }], validation: { required: true } });
  await add({ type: "multiple_choice", title: "你喜欢哪些水果？", options: ["苹果", "香蕉", "西瓜", "榴莲"].map((text) => ({ text })),
              validation: { required: true, minSelect: 1, maxSelect: 3 } });
  await add({ type: "text", title: "为什么喜欢榴莲？", validation: { required: false, minLength: 5, maxLength: 200 } });
  await add({ type: "number", title: "你每周吃几次水果？", validation: { required: true, min: 0, max: 50, integerOnly: true } });
  const full = await add({ type: "text", title: "其他建议", validation: { required: false, maxLength: 500 } });
  const [q1, q2, q3, q4, q5] = full.questions;
  const o = Object.fromEntries([q1, q2].flatMap((q) => q.options.map((x) => [x.text, x.id])));
  const setLogic = async (q, rules, defaultNext = null) => {
    const body = { type: q.type, title: q.title, validation: q.validation, logic: { rules, defaultNext } };
    if (q.options) body.options = q.options;
    return ok(await ctx.api("PUT", `/api/surveys/${s.id}/questions/${q.id}`, body, token));
  };
  await setLogic(q1, [{ when: { op: "eq", value: o["不喜欢"] }, goto: q5.id }]);
  await setLogic(q2, [{ when: { op: "contains", value: o["榴莲"] }, goto: q3.id }], q4.id);
  await setLogic(q4, [{ when: { op: "eq", value: 0 }, goto: "END" }]);
  if (publish) ok(await ctx.api("POST", `/api/surveys/${s.id}/publish`, undefined, token));
  return { id: s.id, shortCode: s.shortCode, q: [q1, q2, q3, q4, q5].map((q) => q.id), o };
}
