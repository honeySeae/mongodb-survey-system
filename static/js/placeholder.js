// 占位页面（统计页 9d 实现前使用）：检查登录、显示导航。
import { requireLogin } from "./api.js";
import { renderTopbar } from "./layout.js";

if (requireLogin()) renderTopbar();
