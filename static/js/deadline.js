// 截止时间组件：默认“不限截止时间”；快捷按钮“1 天后、3 天后、7 天后、30 天后、自定义”；
// 点“自定义”才展开日期和时间选择；选好后用中文显示“截止于 2026年11月30日 23:59”，旁边“清除”。
// 对外的值是带时区的 ISO 字符串（后端要求带时区）或 null（不限）。新建问卷和编辑页共用。
import { el } from "./layout.js";

const QUICK_DAYS = [1, 3, 7, 30];
const pad = (n) => String(n).padStart(2, "0");

/** n 天后当天的 23:59（本地时间）。截止时间一般取到当天结束。 */
export function daysLaterEndOfDay(n, now = new Date()) {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + n, 23, 59, 0, 0);
  return d;
}

/** Date -> “2026年11月30日 23:59”（本地时间）。 */
export function formatDeadline(date) {
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Date -> <input type="date"> / <input type="time"> 的值。 */
export function toDateInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
export function toTimeInput(date) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 日期框和时间框的值 -> 本地时间 Date；任一为空或不合法时返回 null。 */
export function fromDateTimeInputs(dateStr, timeStr) {
  if (!dateStr || !timeStr) return null;
  const [y, m, d] = dateStr.split("-").map(Number);
  const [hh, mm] = timeStr.split(":").map(Number);
  const date = new Date(y, m - 1, d, hh, mm, 0, 0);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * 创建截止时间组件。
 * @param {{ value?: string|null, disabled?: boolean, onChange?: (iso: string|null) => void }} opts
 * @returns {{ element: HTMLElement, getValue: () => string|null, setValue: (iso: string|null) => void,
 *             setDisabled: (b: boolean) => void }}
 */
export function createDeadlinePicker(opts = {}) {
  let current = opts.value ? new Date(opts.value) : null;   // Date 或 null（不限）
  let disabled = Boolean(opts.disabled);

  const display = el("span");
  const clearBtn = el("button", { class: "btn link muted", type: "button", text: "清除" });
  const pastHint = el("span", { class: "field-error" });
  const currentLine = el("div", { class: "current" }, display, clearBtn, pastHint);

  const customBtn = el("button", { class: "btn small ghost", type: "button", text: "自定义" });
  const quickButtons = QUICK_DAYS.map((n) =>
    el("button", { class: "btn small ghost", type: "button", text: `${n} 天后`, onclick: () => choose(daysLaterEndOfDay(n)) }));
  const quickRow = el("div", { class: "quick" }, ...quickButtons, customBtn);

  const dateInput = el("input", { class: "input", type: "date", "aria-label": "截止日期" });
  const timeInput = el("input", { class: "input", type: "time", "aria-label": "截止时间" });
  const customRow = el("div", { class: "custom", hidden: true },
    el("span", { class: "muted", text: "日期" }), dateInput,
    el("span", { class: "muted", text: "时间" }), timeInput);

  const element = el("div", { class: "deadline" }, currentLine, quickRow, customRow);

  function render() {
    display.replaceChildren(current
      ? el("span", {}, "截止于 ", el("b", { text: formatDeadline(current) }))
      : el("span", { class: "muted", text: "不限截止时间" }));
    clearBtn.hidden = !current || disabled;
    pastHint.textContent = current && current <= new Date() ? "截止时间必须晚于现在" : "";
    quickRow.hidden = disabled;
    if (disabled) customRow.hidden = true;
    customBtn.classList.toggle("active", !customRow.hidden);
  }

  function choose(date) {
    current = date;
    if (current) {
      // 自定义框始终显示当前选择，展开时不会出现空白的“yyyy/mm/dd”
      dateInput.value = toDateInput(current);
      timeInput.value = toTimeInput(current);
    }
    render();
    if (opts.onChange) opts.onChange(getValue());
  }

  function getValue() {
    return current ? current.toISOString() : null;   // toISOString 以 Z 结尾，带时区
  }

  customBtn.addEventListener("click", () => {
    customRow.hidden = !customRow.hidden;
    if (!customRow.hidden && !dateInput.value) {
      const initial = current || daysLaterEndOfDay(7);
      dateInput.value = toDateInput(initial);
      timeInput.value = toTimeInput(initial);
      if (!current) choose(initial);
    }
    render();
  });
  const onCustomInput = () => {
    const date = fromDateTimeInputs(dateInput.value, timeInput.value);
    if (date) choose(date);
  };
  dateInput.addEventListener("change", onCustomInput);
  timeInput.addEventListener("change", onCustomInput);
  clearBtn.addEventListener("click", () => {
    customRow.hidden = true;
    choose(null);
  });

  if (current) { dateInput.value = toDateInput(current); timeInput.value = toTimeInput(current); }
  render();

  return {
    element,
    getValue,
    setValue(iso) { current = iso ? new Date(iso) : null; render(); },
    setDisabled(b) { disabled = Boolean(b); render(); },
  };
}
