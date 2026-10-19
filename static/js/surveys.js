// 我的问卷：列表、新建。
import { api, requireLogin } from "./api.js";
import { createDeadlinePicker } from "./deadline.js";
import { bindOptionHighlight, el, errorNotice, formatTime, linkBox, renderTopbar, statusBadge } from "./layout.js";

const $ = (id) => document.getElementById(id);

if (requireLogin()) {
  renderTopbar("surveys");
  loadList();
}
bindOptionHighlight($("policy-group"));
bindOptionHighlight($("anonymous-group"));
const deadline = createDeadlinePicker();
$("deadline-slot").append(deadline.element);

// ---------- 新建 ----------
$("new-btn").addEventListener("click", () => {
  $("new-form").hidden = false;
  $("new-btn").hidden = true;
  $("title").focus();
});
$("cancel-btn").addEventListener("click", () => {
  $("new-form").hidden = true;
  $("new-btn").hidden = false;
  $("new-message").replaceChildren();
  deadline.setValue(null);
});

$("new-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("new-message").replaceChildren();
  const body = {
    title: $("title").value,
    description: $("description").value,
    submissionPolicy: document.querySelector('input[name="policy"]:checked').value,
    allowAnonymous: $("anonymous").checked,
    deadline: deadline.getValue(),   // 带时区的 ISO 或 null
  };
  $("create-btn").disabled = true;
  try {
    const survey = await api("POST", "/api/surveys", body);
    location.href = `/surveys/${survey.id}/edit`;
  } catch (err) {
    $("new-message").replaceChildren(errorNotice(err));
    $("create-btn").disabled = false;
  }
});

// ---------- 列表 ----------
async function loadList() {
  try {
    const surveys = await api("GET", "/api/surveys");
    $("list").replaceChildren(...(surveys.length ? surveys.map(surveyItem) : [emptyState()]));
  } catch (err) {
    $("list").replaceChildren(el("div", { class: "paper-body" }, errorNotice(err)));
  }
}

function emptyState() {
  return el("div", { class: "empty" }, "还没有问卷，点击上方“新建问卷”开始吧");
}

function surveyItem(s) {
  const meta = [
    `${s.questionCount} 道题`,
    `${s.responseCount} 份答卷`,
    `创建于 ${formatTime(s.createdAt)}`,
  ];
  if (s.settings.deadline) meta.push(`截止 ${formatTime(s.settings.deadline)}`);
  if (s.settings.allowAnonymous) meta.push("匿名");

  return el("div", { class: "survey-item" },
    el("h3", {}, el("a", { href: `/surveys/${s.id}/edit`, text: s.title }), statusBadge(s)),
    el("div", { class: "meta", text: meta.join(" · ") }),
    s.status === "draft"
      ? el("div", { class: "muted", text: "发布后即可通过链接分发" })
      : linkBox(s.url),
    el("div", { class: "actions mt" },
      el("a", { class: "btn small ghost", href: `/surveys/${s.id}/edit`, text: s.status === "draft" ? "编辑题目" : "查看 / 设置" }),
      el("a", { class: "btn small ghost", href: `/surveys/${s.id}/stats`, text: "统计结果" }),
      s.status !== "draft"
        ? el("a", { class: "btn small ghost", href: `/survey/${s.shortCode}`, target: "_blank", text: "打开填写页" })
        : null,
    ),
  );
}
