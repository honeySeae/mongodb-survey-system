// 用 Chrome 调试协议（CDP）驱动无界面 Chrome：导航、执行页面脚本、等待条件、截图、收集页面错误。
// 只用 Node.js 自带的 fetch 和 WebSocket（Node 22+），不需要安装任何依赖。
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch({ chrome, profileDir, port }) {
  const proc = spawn(chrome, [
    "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profileDir}`,
    "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--lang=zh-CN", "about:blank",
  ], { stdio: "ignore" });

  let targets = [];
  for (let i = 0; i < 75 && !targets.some((t) => t.type === "page"); i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { /* Chrome 还没启动好 */ }
    if (!targets.some((t) => t.type === "page")) await sleep(200);
  }
  const page = targets.find((t) => t.type === "page");
  if (!page) { proc.kill(); throw new Error("无法连接无界面 Chrome"); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.addEventListener("open", resolve); ws.addEventListener("error", reject); });

  let id = 0;
  const pending = new Map();
  const listeners = [];
  const errors = [];      // 页面中的 JS 异常、console.error：出现即视为测试失败
  const network = [];     // 加载失败的请求（含故意制造的 4xx），仅供参考

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const myId = ++id;
      pending.set(myId, (m) => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
      ws.send(JSON.stringify({ id: myId, method, params }));
    });
  }

  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
    const p = msg.params || {};
    if (msg.method === "Runtime.exceptionThrown") {
      errors.push("JS 异常: " + (p.exceptionDetails.exception?.description || p.exceptionDetails.text));
    }
    if (msg.method === "Runtime.consoleAPICalled" && p.type === "error") {
      errors.push("console.error: " + p.args.map((a) => a.value ?? a.description).join(" "));
    }
    if (msg.method === "Log.entryAdded" && p.entry.level === "error") network.push(`${p.entry.text} ${p.entry.url || ""}`);
    // 确认框（如“确定发布吗？”）一律点“确定”
    if (msg.method === "Page.javascriptDialogOpening") send("Page.handleJavaScriptDialog", { accept: true });
    listeners.forEach((l) => l(msg));
  });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");

  return {
    errors, network, sleep,
    async size(width, height) {
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
    },
    async goto(url, settle = 600) {
      const loaded = new Promise((resolve) => {
        const l = (m) => {
          if (m.method === "Page.loadEventFired") { listeners.splice(listeners.indexOf(l), 1); resolve(); }
        };
        listeners.push(l);
      });
      await send("Page.navigate", { url });
      await loaded;
      await sleep(settle);
    },
    /** 在页面中执行表达式（可返回 Promise），返回其值。 */
    async eval(expression) {
      const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) {
        throw new Error("页面脚本出错: " + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
      }
      return r.result.value;
    },
    /** 等待页面中的表达式为真（轮询），超时则抛错并附上说明。 */
    async waitFor(expression, description, timeout = 6000) {
      const start = Date.now();
      for (;;) {
        try { if (await this.eval(expression)) return; } catch { /* 页面跳转中 */ }
        if (Date.now() - start > timeout) throw new Error(`等待超时：${description}`);
        await sleep(100);
      }
    },
    async shot(dir, name) {
      mkdirSync(dir, { recursive: true });
      const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      writeFileSync(`${dir}/${name}.png`, Buffer.from(data, "base64"));
    },
    close() {
      try { ws.close(); } catch { /* 忽略 */ }
      proc.kill();
    },
  };
}
