// 占位页面（9b~9d 实现前使用）：检查登录；填写页显示问卷标题，用于验证“未登录访问链接 → 登录 → 自动回到问卷”。
import { api, requireLogin } from "./api.js";
import { pathSegment, renderTopbar } from "./layout.js";

// 模块脚本中 document.currentScript 为 null，因此用 data-page 属性查找
const page = document.querySelector("script[data-page]").dataset.page;

if (requireLogin()) {
  renderTopbar();
  if (page === "fill") {
    api("GET", `/api/s/${encodeURIComponent(pathSegment(1))}`)
      .then((s) => { document.getElementById("title").textContent = s.title; })
      .catch((err) => { document.getElementById("info").textContent = err.message; });
  }
}
