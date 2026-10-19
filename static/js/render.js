// 题目渲染器：编辑页（预览，不可操作）与填写页共用同一份，保证所见即所得。
// 只负责显示和读取输入；校验、跳转都由后端完成。
import { el } from "./layout.js";

export const TYPE_LABELS = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  text: "文本填空",
  number: "数字填空",
};

/** 根据 validation 生成作答要求说明，如“多选，最多选 3 项”“请输入 0–120 之间的整数”。 */
export function hintFor(q) {
  const v = q.validation || {};
  if (q.type === "single_choice") return "单选";
  if (q.type === "multiple_choice") {
    const lo = v.minSelect, hi = v.maxSelect;
    if (lo && hi && lo === hi) return `多选，必须选 ${lo} 项`;
    const parts = [];
    if (lo) parts.push(`至少选 ${lo} 项`);
    if (hi) parts.push(`最多选 ${hi} 项`);
    return parts.length ? `多选，${parts.join("，")}` : "多选";
  }
  if (q.type === "text") {
    const lo = v.minLength, hi = v.maxLength;
    if (lo && hi) return lo === hi ? `请填写 ${lo} 个字` : `请填写 ${lo}–${hi} 个字`;
    if (lo) return `请至少填写 ${lo} 个字`;
    if (hi) return `最多 ${hi} 个字`;
    return "";
  }
  if (q.type === "number") {
    const kind = v.integerOnly ? "整数" : "数字";
    const has = (k) => v[k] !== undefined && v[k] !== null;
    if (has("min") && has("max")) return `请输入 ${v.min}–${v.max} 之间的${kind}`;
    if (has("min")) return `请输入不小于 ${v.min} 的${kind}`;
    if (has("max")) return `请输入不大于 ${v.max} 的${kind}`;
    return `请输入${kind}`;
  }
  return "";
}

/** 文本题用单行还是多行：最多字数不超过 50 时用单行填空线，否则用多行文本框。 */
export function isShortText(q) {
  const hi = (q.validation || {}).maxLength;
  return Boolean(hi && hi <= 50);
}

/** 把输入框中的文字转为数字答案：空为 null；不是合法数字时原样返回字符串，由后端给出错误提示。 */
export function parseNumberInput(raw) {
  const s = String(raw).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : s;
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight + 2}px`;
}

/**
 * 渲染一道题。
 * @param {object} q        题目（id、type、title、options、validation）
 * @param {number} number   题号（问卷中的原始编号，被跳过的题也保留编号）
 * @param {object} opts     { disabled, value, onChange(value, source) }；source 为 "click" 或 "input"
 * @returns {{ element, getValue, setValue, setError, setWarnings, focus }}
 */
export function createQuestionView(q, number, opts = {}) {
  const { disabled = false, onChange } = opts;
  const v = q.validation || {};
  const errorBox = el("div", { class: "q-error", hidden: true, role: "alert" });
  const warningBox = el("div");
  const body = el("div", { class: "q-body" });
  const hint = hintFor(q);

  const element = el("div", { class: "question", dataset: { questionId: q.id } },
    el("div", { class: "q-title" },
      el("span", { class: "q-number", text: `${number}.` }),
      el("span", { text: q.title }),
      v.required ? el("span", { class: "q-required", title: "必答", text: "*" }) : null),
    hint ? el("div", { class: "q-hint", text: hint }) : null,
    body, errorBox, warningBox);

  const fire = (source) => { if (onChange) onChange(getValue(), source); };
  let getValue, setValue, focus;

  if (q.type === "single_choice" || q.type === "multiple_choice") {
    const multiple = q.type === "multiple_choice";
    const inputs = (q.options || []).map((o) => {
      const input = el("input", { type: multiple ? "checkbox" : "radio", name: `q-${q.id}`, value: o.id, disabled });
      const row = el("label", { class: `option ${multiple ? "checkbox" : "radio"}${disabled ? " disabled" : ""}` },
        input, el("span", { class: "mark" }), el("span", { text: o.text }));
      body.append(row);
      return input;
    });
    const sync = () => inputs.forEach((i) => i.closest(".option").classList.toggle("is-checked", i.checked));
    // 单选点击后立即通知；多选由调用方决定何时计算（如失去焦点后）
    body.addEventListener("change", () => { sync(); fire("click"); });
    getValue = () => multiple
      ? inputs.filter((i) => i.checked).map((i) => i.value)
      : (inputs.find((i) => i.checked) || {}).value ?? null;
    setValue = (value) => {
      const chosen = new Set(multiple ? (value || []) : (value ? [value] : []));
      inputs.forEach((i) => { i.checked = chosen.has(i.value); });
      sync();
    };
    focus = () => inputs[0] && inputs[0].focus();
  } else if (q.type === "text") {
    const short = isShortText(q);
    const input = short
      ? el("input", { class: "line-input", type: "text", disabled, maxlength: v.maxLength || null })
      : el("textarea", { class: "line-textarea", rows: 2, disabled });
    const counter = v.maxLength ? el("div", { class: "char-count" }) : null;
    const updateCounter = () => { if (counter) counter.textContent = `${input.value.trim().length} / ${v.maxLength}`; };
    input.addEventListener("input", () => { if (!short) autoGrow(input); updateCounter(); fire("input"); });
    input.addEventListener("blur", () => fire("blur"));
    body.append(...[input, counter].filter(Boolean));   // counter 可能为 null，原生 append 会显示成 "null"
    getValue = () => (input.value.trim() === "" ? null : input.value);
    setValue = (value) => { input.value = value ?? ""; updateCounter(); if (!short) requestAnimationFrame(() => autoGrow(input)); };
    focus = () => input.focus();
    updateCounter();
  } else {
    // 数字题用文本框 + 数字键盘：避免浏览器自带数字框对非法输入静默清空
    const input = el("input", { class: "line-input number", type: "text", inputmode: v.integerOnly ? "numeric" : "decimal", disabled });
    input.addEventListener("input", () => fire("input"));
    input.addEventListener("blur", () => fire("blur"));
    body.append(input);
    getValue = () => parseNumberInput(input.value);
    setValue = (value) => { input.value = value ?? ""; };
    focus = () => input.focus();
  }

  if (opts.value !== undefined) setValue(opts.value);

  return {
    element,
    getValue,
    setValue,
    focus,
    setError(message) {
      errorBox.textContent = message || "";
      errorBox.hidden = !message;
      element.classList.toggle("has-error", Boolean(message));
    },
    setWarnings(messages = []) {
      warningBox.replaceChildren(...messages.map((m) => el("div", { class: "q-warning", text: m })));
      element.classList.toggle("has-warning", messages.length > 0);
    },
  };
}
