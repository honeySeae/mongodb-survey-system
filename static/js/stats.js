// 统计页：整份问卷统计（选择题横向柱状条、填空题内容列表与加载更多、数字题平均值）与答卷列表。
// 数字全部来自后端聚合管道（设计文档 6.7、6.8）；前端只负责显示和计算百分比。
// 非匿名问卷显示填写人用户名；匿名问卷后端根本不返回填写人，这里也就无从显示。
import { api, requireLogin, withQuery } from "./api.js";
import { el, errorNotice, formatTime, pathSegment, renderTopbar, statusBadge } from "./layout.js";
import { TYPE_LABELS } from "./render.js";

const $ = (id) => document.getElementById(id);
const surveyId = pathSegment(1);
const ITEMS_PAGE = 50;       // 填空题“加载更多”每次加载的条数
const RESPONSES_PAGE = 20;   // 答卷列表每次加载的份数

let survey = null;           // 问卷详情（用于把选项 id 显示成选项文字）
let stats = null;
let responsesLoaded = 0;

if (requireLogin()) {
  renderTopbar("surveys");
  init();
}

async function init() {
  try {
    [survey, stats] = await Promise.all([
      api("GET", `/api/surveys/${encodeURIComponent(surveyId)}`),
      api("GET", `/api/surveys/${encodeURIComponent(surveyId)}/stats`),
    ]);
  } catch (err) {
    $("title").textContent = err.status === 404 ? "问卷不存在" : "加载失败";
    $("message").replaceChildren(errorNotice(err));
    return;
  }
  document.title = `${survey.title} · 统计结果`;
  $("title").replaceChildren(survey.title, " ", statusBadge(survey));
  $("meta").textContent = survey.settings.allowAnonymous ? "匿名问卷：不显示填写人" : "实名问卷：显示填写人用户名";
  $("head-actions").replaceChildren(
    el("a", { class: "btn small ghost", href: `/surveys/${survey.id}/edit`, text: "编辑 / 设置" }),
    survey.status !== "draft"
      ? el("a", { class: "btn small ghost", href: `/survey/${survey.shortCode}`, target: "_blank", text: "打开填写页" })
      : el("span"));
  $("tabs").hidden = false;
  $("tab-stats").addEventListener("click", () => showTab("stats"));
  $("tab-responses").addEventListener("click", () => showTab("responses"));
  renderStats();
  showTab("stats");
}

function showTab(name) {
  $("tab-stats").classList.toggle("active", name === "stats");
  $("tab-responses").classList.toggle("active", name === "responses");
  $("panel-stats").hidden = name !== "stats";
  $("panel-responses").hidden = name !== "responses";
  if (name === "responses" && responsesLoaded === 0) loadResponses();
}

// ---------- 统计 ----------
function number(value, label) {
  return el("div", { class: "stat-number" }, el("b", { text: String(value) }), el("span", { text: label }));
}

function renderStats() {
  $("totals").replaceChildren(
    number(stats.totalResponses, "答卷数"),
    number(stats.totalRespondents, "填写人数"));
  $("scope").textContent = `统计口径：${stats.scope}`
    + (stats.submissionPolicy === "all" ? "。答卷数可能大于填写人数" : "");
  const list = $("question-stats");
  if (!stats.questions.length) {
    list.replaceChildren(el("div", { class: "empty", text: "这份问卷还没有题目" }));
    return;
  }
  list.replaceChildren(...stats.questions.map((q, i) => questionCard(q, i + 1)));
}

const percent = (count, total) => (total ? Math.round((count / total) * 1000) / 10 : 0);

function questionCard(q, n) {
  const card = el("div", { class: "question stat-q", dataset: { questionId: q.questionId } },
    el("div", { class: "q-title" },
      el("span", { class: "q-number", text: `${n}.` }),
      el("span", { text: q.title })),
    el("div", { class: "q-hint", text: `${TYPE_LABELS[q.type] || q.type} · 答卷数 ${q.answerCount} · 作答人数 ${q.respondentCount}` }));
  const body = el("div", { class: "q-body" });
  card.append(body);

  if (q.options) {
    // 单选、多选：横向柱状条，百分比 = 选项人数（次数）÷ 这道题的答卷数
    for (const o of q.options) {
      const p = percent(o.count, q.answerCount);
      const fill = el("div", { class: "bar-fill" });
      fill.style.width = `${p}%`;
      body.append(el("div", { class: "bar-row" },
        el("div", { class: "bar-label", text: o.text }),
        el("div", { class: "bar-track", title: `${p}%` }, fill),
        el("div", { class: "bar-value", text: `${o.count} ${q.type === "multiple_choice" ? "次" : "人"}（${p}%）` })));
    }
    if (q.type === "multiple_choice" && q.answerCount) {
      body.append(el("div", { class: "help", text: "多选题：百分比 = 选择该项的答卷 ÷ 答卷数，各项之和可能超过 100%" }));
    }
    if (!q.answerCount) body.append(el("div", { class: "muted", text: "还没有人作答" }));
    return card;
  }

  // 文本、数字：内容列表 + 加载更多；数字题显示平均值
  if (q.type === "number") {
    body.append(el("div", { class: "stat-average" },
      el("span", { class: "muted", text: "平均值 " }),
      el("b", { text: q.average === null || q.average === undefined ? "—" : formatNumber(q.average) })));
  }
  const items = el("div", { class: "stat-items" });
  body.append(items);
  appendItems(items, q.items, q.type);
  if (!q.itemsTotal) items.append(el("div", { class: "muted", text: "还没有人作答" }));

  const more = el("button", { class: "btn small link", type: "button" });
  const updateMore = () => {
    const shown = items.querySelectorAll(".stat-item").length;
    more.hidden = shown >= q.itemsTotal;
    more.textContent = `加载更多（已显示 ${shown} / ${q.itemsTotal}）`;
  };
  more.addEventListener("click", async () => {
    more.disabled = true;
    try {
      const shown = items.querySelectorAll(".stat-item").length;
      const page = await api("GET", withQuery(`/api/surveys/${survey.id}/stats/questions/${encodeURIComponent(q.questionId)}`,
                                              { offset: shown, limit: ITEMS_PAGE }));
      appendItems(items, page.question.items, q.type);
    } catch (err) {
      items.append(errorNotice(err));
    } finally {
      more.disabled = false;
      updateMore();
    }
  });
  body.append(more);
  updateMore();
  return card;
}

function formatNumber(x) {
  return Number.isInteger(x) ? String(x) : x.toFixed(2);
}

function appendItems(container, items, type) {
  for (const item of items) {
    container.append(el("div", { class: "stat-item" },
      el("div", { class: `stat-value${type === "number" ? " number" : ""}`, text: String(item.value) }),
      el("div", { class: "stat-meta" },
        item.username ? el("span", { class: "stat-user", text: item.username }) : null,
        el("span", { text: formatTime(item.submittedAt) }))));
  }
}

// ---------- 答卷列表 ----------
async function loadResponses() {
  const btn = $("responses-more");
  btn.disabled = true;
  try {
    const page = await api("GET", withQuery(`/api/surveys/${survey.id}/responses`,
                                            { offset: responsesLoaded, limit: RESPONSES_PAGE }));
    if (responsesLoaded === 0 && !page.total) {
      $("responses").replaceChildren(el("div", { class: "empty", text: "还没有答卷" }));
    }
    const startNo = responsesLoaded;
    page.items.forEach((r, k) => $("responses").append(responseCard(r, page.total - startNo - k)));
    responsesLoaded += page.items.length;
    $("responses-summary").textContent = `共 ${page.total} 份答卷（${page.scope}），按提交时间从新到旧排列，已显示 ${responsesLoaded} 份`;
    btn.hidden = responsesLoaded >= page.total;
  } catch (err) {
    $("responses").append(errorNotice(err));
  } finally {
    btn.disabled = false;
  }
}
$("responses-more").addEventListener("click", loadResponses);

/** 把答案显示成文字：选项 id → 选项文字。 */
function answerText(q, value) {
  if (q.type === "single_choice" || q.type === "multiple_choice") {
    const texts = new Map((q.options || []).map((o) => [o.id, o.text]));
    const ids = Array.isArray(value) ? value : [value];
    return ids.map((id) => texts.get(id) ?? id).join("、");
  }
  return String(value);
}

function responseCard(r, no) {
  const byId = new Map(r.answers.map((a) => [a.questionId, a.value]));
  const rows = survey.questions.map((q, i) => (byId.has(q.id)
    ? el("div", { class: "resp-row" },
        el("div", { class: "resp-q", text: `${i + 1}. ${q.title}` }),
        el("div", { class: "resp-a", text: answerText(q, byId.get(q.id)) }))
    : null)).filter(Boolean);
  return el("div", { class: "resp-card" },
    el("div", { class: "resp-head" },
      el("b", { text: `第 ${no} 份` }),
      r.username ? el("span", { class: "stat-user", text: r.username }) : null,
      el("span", { class: "muted", text: formatTime(r.submittedAt) })),
    ...(rows.length ? rows : [el("div", { class: "muted", text: "（没有作答任何题）" })]));
}
