// 前端纯函数的测试（不需要浏览器）。由 tests/test_frontend_js.py 调用；没有 Node.js 时跳过。
import assert from "node:assert/strict";
import { safeNext, withQuery } from "../../static/js/api.js";
import { daysLaterEndOfDay, formatDeadline, fromDateTimeInputs, toDateInput, toTimeInput } from "../../static/js/deadline.js";

// safeNext：只接受站内地址，防止开放重定向
assert.equal(safeNext("/survey/a8Kx2p"), "/survey/a8Kx2p");
assert.equal(safeNext("/surveys/1/edit?x=1"), "/surveys/1/edit?x=1");
for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "evil", "", null, undefined, "javascript:alert(1)"]) {
  assert.equal(safeNext(bad), "/surveys", `应拒绝 ${bad}`);
}

// withQuery：跳过空值
assert.equal(withQuery("/api/x", { offset: 0, limit: 20, empty: null }), "/api/x?offset=0&limit=20");
assert.equal(withQuery("/api/x", {}), "/api/x");

// 截止时间组件
const now = new Date(2026, 9, 19, 15, 30);                       // 本地时间 2026-10-19 15:30
const d7 = daysLaterEndOfDay(7, now);
assert.equal(formatDeadline(d7), "2026年10月26日 23:59");       // 7 天后当天 23:59
assert.equal(formatDeadline(daysLaterEndOfDay(30, now)), "2026年11月18日 23:59");  // 跨月
assert.equal(formatDeadline(daysLaterEndOfDay(1, new Date(2026, 11, 31, 9, 0))), "2027年1月1日 23:59");  // 跨年
assert.equal(toDateInput(d7), "2026-10-26");
assert.equal(toTimeInput(new Date(2026, 0, 5, 7, 3)), "07:03");
const picked = fromDateTimeInputs("2026-11-30", "23:59");
assert.equal(formatDeadline(picked), "2026年11月30日 23:59");
assert.match(picked.toISOString(), /Z$/);                         // 提交时带时区
assert.equal(fromDateTimeInputs("", "23:59"), null);
assert.equal(fromDateTimeInputs("2026-11-30", ""), null);

console.log("ok");
