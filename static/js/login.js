// 登录 / 注册。登录成功后回到 next 指定的站内地址（未登录访问问卷链接时会带上）。
import { api, getToken, safeNext, setAuth } from "./api.js";
import { errorNotice, queryParam } from "./layout.js";

const next = safeNext(queryParam("next"));
const $ = (id) => document.getElementById(id);
let mode = "login";

if (queryParam("next") && next.startsWith("/survey/")) {
  $("next-hint").hidden = false;
  $("next-hint").textContent = "登录后将自动打开你要填写的问卷";
}

// 已登录（令牌仍有效）时直接前往目标页面
if (getToken()) {
  api("GET", "/api/auth/me", undefined, { redirectOn401: false })
    .then(() => location.replace(next))
    .catch(() => { /* 令牌无效：留在登录页 */ });
}

function setMode(m) {
  mode = m;
  $("tab-login").classList.toggle("active", m === "login");
  $("tab-register").classList.toggle("active", m === "register");
  $("submit").textContent = m === "login" ? "登录" : "注册并登录";
  $("username-help").hidden = m === "login";
  $("password-help").hidden = m === "login";
  $("password").autocomplete = m === "login" ? "current-password" : "new-password";
  clearErrors();
}
$("tab-login").addEventListener("click", () => setMode("login"));
$("tab-register").addEventListener("click", () => setMode("register"));

function clearErrors() {
  $("message").replaceChildren();
  for (const f of ["username", "password"]) {
    $(`${f}-error`).textContent = "";
    $(f).classList.remove("invalid");
  }
}

function showError(err) {
  // 字段错误显示在对应输入框下方，其余显示在表单上方
  const fieldErrors = (err.errors || []).filter((e) => e.field === "username" || e.field === "password");
  for (const e of fieldErrors) {
    $(`${e.field}-error`).textContent = e.message;
    $(e.field).classList.add("invalid");
  }
  if (!fieldErrors.length) $("message").replaceChildren(errorNotice(err));
}

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();
  const body = { username: $("username").value, password: $("password").value };
  const button = $("submit");
  button.disabled = true;
  try {
    if (mode === "register") {
      await api("POST", "/api/auth/register", body, { redirectOn401: false });
    }
    // 注册成功后自动登录（后端注册接口本身不返回令牌）
    const result = await api("POST", "/api/auth/login", body, { redirectOn401: false });
    setAuth(result.accessToken, result.user);
    location.replace(next);
  } catch (err) {
    showError(err);
  } finally {
    button.disabled = false;
  }
});
