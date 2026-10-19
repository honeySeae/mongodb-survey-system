// 请求封装：自动携带登录令牌；401 时跳转登录页并带上 next；错误统一为 ApiError。
// 后端错误格式：{ code, message, errors?: [{ field, questionId?, message }] }

const TOKEN_KEY = "survey.token";
const USER_KEY = "survey.user";

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* 隐私模式等情况下忽略 */ }
}
function storageRemove(key) {
  try { localStorage.removeItem(key); } catch { /* 忽略 */ }
}

export function getToken() { return storageGet(TOKEN_KEY); }

export function getUser() {
  try { return JSON.parse(storageGet(USER_KEY) || "null"); } catch { return null; }
}

export function setAuth(token, user) {
  storageSet(TOKEN_KEY, token);
  storageSet(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  storageRemove(TOKEN_KEY);
  storageRemove(USER_KEY);
}

/** 只接受站内地址，防止 /login?next=https://恶意网站 这样的“开放重定向”。 */
export function safeNext(next) {
  if (typeof next === "string" && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) {
    return next;
  }
  return "/surveys";
}

export function redirectToLogin() {
  const next = location.pathname + location.search;
  location.href = "/login?next=" + encodeURIComponent(next);
}

/** 页面开头调用：未登录则跳转登录页，返回是否已登录。 */
export function requireLogin() {
  if (!getToken()) {
    redirectToLogin();
    return false;
  }
  return true;
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body && body.message ? body.message : `请求失败（${status}）`);
    this.status = status;
    this.code = body && body.code;
    this.errors = (body && body.errors) || [];
    this.body = body;
  }
}

/**
 * 调用后端接口。
 * @param {string} method  GET / POST / PUT / PATCH / DELETE
 * @param {string} path    以 /api 开头的路径
 * @param {object} [body]  JSON 请求体
 * @param {object} [opts]  { redirectOn401: 默认 true；登录接口本身传 false }
 */
export async function api(method, path, body, opts = {}) {
  const { redirectOn401 = true } = opts;
  const headers = { "Accept": "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp;
  try {
    resp = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "无法连接服务器，请检查网络后重试" });
  }

  let data = null;
  if (resp.status !== 204) {
    try { data = await resp.json(); } catch { data = null; }
  }
  if (resp.status === 401 && redirectOn401) {
    clearAuth();
    redirectToLogin();
  }
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data;
}

/** 把查询参数对象拼到路径上。 */
export function withQuery(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}
