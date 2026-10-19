// 前端纯函数的测试（不需要浏览器）。由 tests/test_frontend_js.py 调用；没有 Node.js 时跳过。
import assert from "node:assert/strict";
import { safeNext, withQuery } from "../../static/js/api.js";
import { fromLocalInput, toLocalInput } from "../../static/js/layout.js";

// safeNext：只接受站内地址，防止开放重定向
assert.equal(safeNext("/survey/a8Kx2p"), "/survey/a8Kx2p");
assert.equal(safeNext("/surveys/1/edit?x=1"), "/surveys/1/edit?x=1");
for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "evil", "", null, undefined, "javascript:alert(1)"]) {
  assert.equal(safeNext(bad), "/surveys", `应拒绝 ${bad}`);
}

// withQuery：跳过空值
assert.equal(withQuery("/api/x", { offset: 0, limit: 20, empty: null }), "/api/x?offset=0&limit=20");
assert.equal(withQuery("/api/x", {}), "/api/x");

// 截止时间：本地时间输入框的值与带时区的 ISO 互转
assert.equal(fromLocalInput(""), null);
const iso = fromLocalInput("2026-11-30T23:59");
assert.match(iso, /Z$/);
assert.equal(toLocalInput(iso), "2026-11-30T23:59");

console.log("ok");
