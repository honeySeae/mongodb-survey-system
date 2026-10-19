// 填写问卷（滚动式）：所有题在同一页从上往下排列。开始只显示第一题；每答完一题，由后端路径预览接口
// 算出下一题并显示在下方、平滑滚动过去。前端不实现跳转逻辑（规则对填写者不可见）。
//
// 约定（开发者 2026-10-19 确认，见 AI_LOG 第 21、25 条）：
// - 被跳过的题不显示，但题号保持问卷中的原编号；
// - 修改前面的答案后重新预览：不再需要的题收起（内容保留在页面上，改回去时恢复），新需要的题出现；
// - 单选点击后立即计算；多选、填空在失去焦点或停止输入片刻后计算；
// - 只采用最后一次预览请求的结果，较早发出的请求返回后直接丢弃，避免旧结果覆盖新结果；
// - 走到结尾出现“提交”；提交时只发送路径上的题；
// - latest 策略：用上次的答案依次计算路径，直接展开到上次答过的位置。
import { api, requireLogin } from "./api.js";
import { el, errorNotice, formatTime, pathSegment, POLICY_LABELS, renderTopbar } from "./layout.js";
import { createQuestionView } from "./render.js";

const $ = (id) => document.getElementById(id);
const shortCode = pathSegment(1);
const DEBOUNCE_MS = 700;

let survey = null;
const views = new Map();        // 题目 id -> 渲染出的题目（全部预先创建，不在路径上的隐藏）
const committed = new Set();    // 已确认的题（作答过，或点了“跳过此题”）——预览时只发送这些题
let path = [];                  // 最近一次采用的预览结果中的路径
let finished = false;
let previewSeq = 0;             // 预览请求编号：只采用最后一次请求的结果
let pending = false;            // 有尚未返回、或尚未发出的预览（此时禁用提交）
let debounceTimer = null;

if (requireLogin()) {
  renderTopbar();
  init();
}

async function init() {
  try {
    survey = await api("GET", `/api/s/${encodeURIComponent(shortCode)}`);
  } catch (err) {
    $("title").textContent = err.code === "SURVEY_NOT_PUBLISHED" ? "问卷尚未发布" : "无法打开问卷";
    $("notices").replaceChildren(errorNotice(err));
    return;
  }
  document.title = `${survey.title} · 填写问卷`;
  $("title").textContent = survey.title;
  $("description").textContent = survey.description;
  $("description").hidden = !survey.description;
  const meta = [POLICY_LABELS[survey.settings.submissionPolicy]];
  if (survey.settings.deadline) meta.push(`截止于 ${formatTime(survey.settings.deadline)}`);
  $("meta").textContent = meta.join(" · ");

  const notices = [];
  if (survey.preview) notices.push(el("div", { class: "notice warn", text: survey.notice }));
  if (survey.settings.allowAnonymous) {
    notices.push(el("div", { class: "notice info", text: "本问卷为匿名问卷，创建者看不到你的身份" }));
  }

  const me = survey.mySubmission;
  // 不能填写：已关闭、已截止，或 once 策略下已经填过
  if (!survey.questions || (!survey.preview && !me.canSubmit)) {
    notices.push(el("div", { class: "notice warn", text: me.reason || survey.notice || "问卷当前不接受填写" }));
    if (me.count) notices.push(el("div", { class: "muted", text: `你已于 ${formatTime(me.lastSubmittedAt)} 提交过这份问卷` }));
    $("notices").replaceChildren(...notices);
    return;
  }

  const prefill = new Map((me.latestAnswers || []).map((a) => [a.questionId, a.value]));
  if (prefill.size) {
    notices.push(el("div", { class: "notice info", text: "已为你填入上次提交的答案，修改后重新提交即可（以最后一次为准）" }));
  }
  $("notices").replaceChildren(...notices);

  survey.questions.forEach((q, i) => {
    const view = createQuestionView(q, i + 1, {
      value: prefill.has(q.id) ? prefill.get(q.id) : undefined,
      onChange: (value, source) => onAnswer(q, source),
    });
    view.element.hidden = true;
    // 选填题：当前最下面一道题可以“跳过”
    const skip = el("button", { class: "btn link muted skip-btn", type: "button", text: "跳过此题", hidden: true,
                                onclick: () => { view.setValue(null); commit(q.id, true); } });
    view.element.append(skip);
    view.skipButton = skip;
    // 单行填空按回车即确认
    view.element.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); commit(q.id, true); }
    });
    views.set(q.id, view);
    $("questions").append(view.element);
    if (prefill.has(q.id)) committed.add(q.id);
  });

  $("progress").hidden = false;
  $("submit-btn").addEventListener("click", submit);
  if (survey.preview) {
    $("submit-btn").disabled = true;
    $("submit-hint").textContent = "预览模式不能提交";
  }
  // 有预填时直接展开到上次答过的位置；否则只显示第一题
  await preview({ scroll: false });
}

// ---------- 作答 ----------
function onAnswer(q, source) {
  if (q.type === "single_choice") {
    commit(q.id, true);                          // 单选：点击后立即计算
  } else if (source === "blur") {
    if (committed.has(q.id) || views.get(q.id).getValue() !== null) commit(q.id, true);
  } else {
    commit(q.id, false);                         // 多选、填空：停止输入片刻后计算
  }
}

function commit(qid, immediately) {
  committed.add(qid);
  pending = true;
  updateSubmitState();
  clearTimeout(debounceTimer);
  if (immediately) preview({ scroll: true });
  else debounceTimer = setTimeout(() => preview({ scroll: true }), DEBOUNCE_MS);
}

/** 预览请求的答案：已确认的题（值为空表示“看过但不答”）。没有确认的题视为“还没答到”。 */
function confirmedAnswers() {
  return [...committed].map((qid) => ({ questionId: qid, value: views.get(qid).getValue() }));
}

async function preview({ scroll }) {
  clearTimeout(debounceTimer);
  const seq = ++previewSeq;
  pending = true;
  updateSubmitState();
  let result;
  try {
    result = await api("POST", `/api/s/${encodeURIComponent(shortCode)}/path`, { answers: confirmedAnswers() });
  } catch (err) {
    if (seq !== previewSeq) return;
    pending = false;
    $("submit-message").replaceChildren(errorNotice(err));
    $("submit-bar").hidden = false;
    $("submit-btn").hidden = true;
    return;
  }
  if (seq !== previewSeq) return;               // 已有更新的请求：丢弃这次（较早的）结果
  pending = false;
  applyPath(result, scroll);
}

function applyPath(result, scroll) {
  const before = new Set(path);
  const wasFinished = finished;
  path = result.path;
  finished = result.finished;
  const onPath = new Set(path);

  // 路径上的题显示，其他题收起（内容保留，改回去时恢复）
  for (const [qid, view] of views) {
    view.element.hidden = !onPath.has(qid);
    view.setError(null);
    view.skipButton.hidden = true;
  }
  for (const e of result.errors) {
    const view = views.get(e.questionId);
    if (view) view.setError(e.message.replace(/^第 \d+ 题：/, ""));
  }

  const frontier = result.nextQuestionId;
  if (frontier) {
    const q = survey.questions.find((x) => x.id === frontier);
    views.get(frontier).skipButton.hidden = Boolean(q.validation && q.validation.required);
  }

  updateProgress(frontier || (result.errors[0] && result.errors[0].questionId));
  updateSubmitState();

  // 新出现的下一题：平滑滚动过去
  const target = frontier || (result.errors[0] && result.errors[0].questionId);
  if (scroll && target && (!before.has(target) || result.errors.length)) {
    views.get(target).element.scrollIntoView({ behavior: "smooth", block: "center" });
  } else if (scroll && finished && !wasFinished) {
    $("submit-bar").scrollIntoView({ behavior: "smooth", block: "center" });   // 刚走到结尾：滚动到“提交”
  }
}

function updateProgress(currentId) {
  const total = survey.questions.length || 1;
  let percent = 100;
  if (!finished) {
    const index = survey.questions.findIndex((q) => q.id === currentId);
    percent = Math.max(0, Math.round((index / total) * 100));
  }
  $("progress-bar").style.width = `${percent}%`;
  $("progress").setAttribute("aria-valuenow", String(percent));
}

function updateSubmitState() {
  $("submit-bar").hidden = !finished;
  $("submit-btn").hidden = false;
  $("submit-btn").disabled = pending || survey.preview;
  if (!survey.preview) $("submit-hint").textContent = pending && finished ? "正在检查答案…" : "";
}

// ---------- 提交 ----------
async function submit() {
  if (pending || !finished) return;
  $("submit-message").replaceChildren();
  $("submit-btn").disabled = true;
  const answers = path.map((qid) => ({ questionId: qid, value: views.get(qid).getValue() }));
  try {
    const result = await api("POST", `/api/s/${encodeURIComponent(shortCode)}/responses`, { answers });
    showThanks(result);
  } catch (err) {
    $("submit-btn").disabled = false;
    const first = (err.errors || []).find((e) => e.questionId && views.has(e.questionId));
    if (first) {
      const view = views.get(first.questionId);
      view.setError(first.message.replace(/^第 \d+ 题：/, ""));
      view.element.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      $("submit-message").replaceChildren(errorNotice(err));
    }
  }
}

function showThanks(result) {
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("progress-bar").style.width = "100%";
  const policy = survey.settings.submissionPolicy;
  const again = {
    latest: el("button", { class: "btn ghost", type: "button", text: "修改答案", onclick: () => location.reload() }),
    all: el("button", { class: "btn ghost", type: "button", text: "再填一次", onclick: () => location.reload() }),
  }[policy];
  $("paper").replaceChildren(
    el("div", { class: "paper-head" }, el("h1", { text: survey.title })),
    el("div", { class: "thanks" },
      el("div", { class: "thanks-mark", text: "✓" }),
      el("h2", { text: "感谢填写！" }),
      el("p", { class: "muted", text: `你的答卷已于 ${formatTime(result.submittedAt)} 提交` }),
      policy === "latest" ? el("p", { class: "muted", text: "如需修改，可以重新填写，以最后一次提交为准" }) : null,
      el("div", { class: "actions center-actions" }, again || null, el("a", { class: "btn link", href: "/surveys", text: "我的问卷" }))),
  );
}
