"use strict";

// Progressive enhancement: native input/datalist controls remain the fallback.
(() => {
  if (!("showPopover" in document.createElement("div"))) return;
  const popups = new Set();
  let nextId = 0;
  const pad = (value) => String(value).padStart(2, "0");
  const dateValue = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

  function wrap(input, label, calendar = false) {
    const wrapper = document.createElement("div"); wrapper.className = "control-input";
    const trigger = document.createElement("button"); trigger.type = "button";
    trigger.className = "control-trigger"; trigger.setAttribute("aria-label", label);
    trigger.setAttribute("aria-expanded", "false");
    if (calendar) {
      trigger.innerHTML = '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="4"/><path d="M7 3v4M17 3v4M3 10h18M8 14h2M14 14h2M8 17h2"/></svg>';
    } else {
      const arrow = document.createElement("span"); arrow.className = "control-chevron";
      arrow.setAttribute("aria-hidden", "true"); trigger.append(arrow);
    }
    input.before(wrapper); wrapper.append(input, trigger);
    return { wrapper, trigger };
  }

  function makePopup(anchor, trigger, className, role) {
    const panel = document.createElement("div");
    panel.id = `control-menu-${++nextId}`; panel.className = `control-popover ${className}`;
    panel.popover = "auto"; panel.setAttribute("role", role);
    (anchor.closest("dialog") || document.body).append(panel);
    trigger.setAttribute("aria-controls", panel.id); trigger.setAttribute("aria-haspopup", role);
    const isOpen = () => panel.matches(":popover-open");
    function position() {
      if (!isOpen()) return;
      if (!anchor.getClientRects().length) { close(); return; }
      const rect = anchor.getBoundingClientRect();
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
      panel.style.width = `${Math.min(className === "calendar-popover" ? 310 : Math.max(rect.width, 250), width - 20)}px`;
      panel.style.maxHeight = `${Math.min(className === "calendar-popover" ? 520 : 330, height - 20)}px`;
      const box = panel.getBoundingClientRect();
      const below = top + height - rect.bottom - 8;
      const above = rect.top - top - 8;
      const y = below >= box.height || below >= above ? rect.bottom + 7 : rect.top - box.height - 7;
      panel.style.left = `${Math.max(left + 10, Math.min(rect.left, left + width - box.width - 10))}px`;
      panel.style.top = `${Math.max(top + 10, Math.min(y, top + height - box.height - 10))}px`;
    }
    function close(focus = false) {
      if (isOpen()) panel.hidePopover();
      if (focus && trigger.isConnected) trigger.focus();
    }
    panel.addEventListener("toggle", () => trigger.setAttribute("aria-expanded", String(isOpen())));
    panel.addEventListener("keydown", (event) => {
      const select = event.target.closest("select");
      if (select && CSS.supports("selector(select:open)") && select.matches(":open")) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    });
    const popup = { panel, anchor, position, isOpen, close, open() { panel.showPopover(); position(); } };
    popups.add(popup);
    return popup;
  }

  function enhanceModels(input) {
    const list = input.list;
    if (!list) return;
    input.setAttribute("aria-label", input.labels[0]?.textContent.trim() || "模型名称");
    const values = [...list.options].map((option) => option.value);
    const { wrapper, trigger } = wrap(input, "显示模型建议");
    const popup = makePopup(wrapper, trigger, "model-popover", "listbox");
    popup.panel.setAttribute("aria-label", "模型建议");
    input.removeAttribute("list"); input.autocomplete = "off";
    input.setAttribute("role", "combobox"); input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", popup.panel.id); input.setAttribute("aria-expanded", "false");
    let visible = [], active = -1, choosing = false;
    function highlight(index) {
      active = index;
      [...popup.panel.querySelectorAll("[role=option]")].forEach((option, i) => { option.dataset.active = String(i === active); });
      const option = popup.panel.querySelector('[data-active="true"]');
      if (option) { input.setAttribute("aria-activedescendant", option.id); option.scrollIntoView({ block: "nearest" }); }
      else input.removeAttribute("aria-activedescendant");
    }
    function choose(value) {
      input.value = value; popup.close(); input.focus();
      choosing = true;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      choosing = false;
    }
    function render(filter = "") {
      visible = values.filter((value) => value.toLowerCase().includes(filter.trim().toLowerCase()));
      popup.panel.replaceChildren(); active = -1; input.removeAttribute("aria-activedescendant");
      visible.forEach((value, index) => {
        const option = document.createElement("div"); option.className = "model-suggestion";
        option.id = `${popup.panel.id}-${index}`; option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(value === input.value)); option.textContent = value;
        option.addEventListener("mousedown", (event) => event.preventDefault());
        option.addEventListener("click", () => choose(value)); popup.panel.append(option);
      });
      const hint = document.createElement("p"); hint.className = "control-hint";
      hint.textContent = "也可以直接输入服务提供的模型名称。"; popup.panel.append(hint);
      popup.position();
    }
    function open() { render(); popup.open(); input.focus(); }
    trigger.addEventListener("click", () => { if (popup.isOpen()) popup.close(); else open(); });
    input.addEventListener("input", () => { if (!choosing) { render(input.value); popup.open(); } });
    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault(); if (!popup.isOpen()) open();
        if (visible.length) highlight(active < 0 ? (event.key === "ArrowDown" ? 0 : visible.length - 1) : (active + (event.key === "ArrowDown" ? 1 : -1) + visible.length) % visible.length);
      } else if (event.key === "Enter" && popup.isOpen() && active >= 0) {
        event.preventDefault(); choose(visible[active]);
      } else if (event.key === "Escape" && popup.isOpen()) {
        event.preventDefault(); event.stopPropagation(); popup.close();
      } else if (event.key === "Tab") popup.close();
    });
    popup.panel.addEventListener("toggle", () => {
      input.setAttribute("aria-expanded", String(popup.isOpen()));
      if (!popup.isOpen()) input.removeAttribute("aria-activedescendant");
    });
  }

  function parseDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/.exec(value.trim());
    if (!match) return null;
    const [, year, month, day, hour, minute] = match.map(Number);
    const date = new Date(year, month - 1, day, hour, minute);
    return year >= 100 && date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day && date.getHours() === hour && date.getMinutes() === minute ? date : null;
  }

  function enhanceDate(input) {
    const editor = document.createElement("input"); editor.type = "text";
    editor.id = `${input.id || `date-${++nextId}`}-display`; editor.required = input.required;
    editor.placeholder = "年-月-日 时:分"; editor.autocomplete = "off";
    editor.value = input.value.replace("T", " "); editor.maxLength = 16;
    for (const name of ["aria-label", "aria-describedby"]) if (input.hasAttribute(name)) editor.setAttribute(name, input.getAttribute(name));
    const labels = [...input.labels];
    if (!editor.hasAttribute("aria-label")) editor.setAttribute("aria-label", labels[0]?.textContent.trim() || "日期与时间");
    input.type = "hidden"; input.required = false; input.before(editor);
    labels.forEach((label) => { if (label.htmlFor === input.id && input.id) label.htmlFor = editor.id; });
    const { wrapper, trigger } = wrap(editor, "选择日期与时间", true);
    const popup = makePopup(wrapper, trigger, "calendar-popover", "dialog");
    popup.panel.setAttribute("aria-label", "选择日期与时间");
    let draft, month;
    function sync() {
      const parsed = parseDate(editor.value);
      editor.setCustomValidity(editor.value.trim() && !parsed ? "请输入有效时间，例如 2026-09-24 20:30。" : "");
      input.value = parsed ? `${dateValue(parsed)}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}` : "";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    editor.addEventListener("input", sync);
    const heading = document.createElement("div"); heading.className = "calendar-heading";
    const title = document.createElement("strong"); title.setAttribute("aria-live", "polite");
    const nav = document.createElement("div"); nav.className = "calendar-nav";
    function button(text, label, action, className = "") {
      const node = document.createElement("button"); node.type = "button"; node.textContent = text;
      if (label) node.setAttribute("aria-label", label); node.className = className;
      node.addEventListener("click", action); return node;
    }
    nav.append(button("‹", "上个月", () => { month.setMonth(month.getMonth() - 1); renderDays(); }), button("›", "下个月", () => { month.setMonth(month.getMonth() + 1); renderDays(); }));
    heading.append(title, nav);
    const week = document.createElement("div"); week.className = "calendar-week"; week.setAttribute("aria-hidden", "true");
    for (const day of ["一", "二", "三", "四", "五", "六", "日"]) { const label = document.createElement("span"); label.textContent = day; week.append(label); }
    const days = document.createElement("div"); days.className = "calendar-days";
    days.setAttribute("role", "group"); days.setAttribute("aria-label", "日期，使用方向键移动");
    function renderDays(focus = false) {
      title.textContent = `${month.getFullYear()} 年 ${month.getMonth() + 1} 月`; days.replaceChildren();
      const start = (month.getDay() + 6) % 7;
      for (let i = 0; i < start; i++) days.append(document.createElement("span"));
      const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
      const selectedInMonth = draft.getFullYear() === month.getFullYear() && draft.getMonth() === month.getMonth();
      for (let day = 1; day <= count; day++) {
        const value = new Date(month.getFullYear(), month.getMonth(), day);
        const selected = dateValue(value) === dateValue(draft);
        const cell = button(String(day), `${value.getFullYear()}年${value.getMonth() + 1}月${day}日`, () => {
          draft.setFullYear(value.getFullYear(), value.getMonth(), day); renderDays(true);
        });
        cell.dataset.date = dateValue(value); cell.setAttribute("aria-pressed", String(selected));
        cell.tabIndex = selected || (!selectedInMonth && day === 1) ? 0 : -1;
        if (dateValue(value) === dateValue(new Date())) cell.setAttribute("aria-current", "date");
        days.append(cell);
      }
      if (focus) days.querySelector('[tabindex="0"]').focus();
      popup.position();
    }
    days.addEventListener("keydown", (event) => {
      const value = event.target.dataset.date;
      if (!value || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(event.key)) return;
      event.preventDefault();
      const date = parseDate(`${value} 12:00`);
      const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key];
      if (delta) date.setDate(date.getDate() + delta);
      else if (event.key === "Home") date.setDate(date.getDate() - (date.getDay() + 6) % 7);
      else if (event.key === "End") date.setDate(date.getDate() + 6 - (date.getDay() + 6) % 7);
      else { const day = date.getDate(); date.setDate(1); date.setMonth(date.getMonth() + (event.key === "PageDown" ? 1 : -1)); date.setDate(Math.min(day, new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate())); }
      draft.setFullYear(date.getFullYear(), date.getMonth(), date.getDate());
      month = new Date(draft.getFullYear(), draft.getMonth(), 1); renderDays(true);
    });
    const time = document.createElement("div"); time.className = "calendar-time";
    const timeLabel = document.createElement("span"); timeLabel.textContent = "时间"; time.append(timeLabel);
    const hour = document.createElement("select"), minute = document.createElement("select");
    hour.setAttribute("aria-label", "小时"); minute.setAttribute("aria-label", "分钟");
    for (let i = 0; i < 24; i++) hour.add(new Option(pad(i), String(i)));
    for (let i = 0; i < 60; i++) minute.add(new Option(pad(i), String(i)));
    time.append(hour, document.createTextNode(":"), minute);
    const footer = document.createElement("div"); footer.className = "calendar-footer";
    footer.append(button("今天", "选择今天", () => { const today = new Date(); draft.setFullYear(today.getFullYear(), today.getMonth(), today.getDate()); month = new Date(draft.getFullYear(), draft.getMonth(), 1); renderDays(true); }, "text-button"),
      button("清空", "清空时间", () => { editor.value = ""; sync(); popup.close(); editor.focus(); }, "text-button"),
      button("确定时间", "确定时间", () => {
        editor.value = `${dateValue(draft)} ${pad(hour.value)}:${pad(minute.value)}`; sync(); popup.close(); editor.focus();
      }, "primary-button"));
    const caption = document.createElement("p"); caption.className = "calendar-caption"; caption.textContent = "按这台设备的本地时间安排";
    popup.panel.append(heading, week, days, time, footer, caption);
    function open() {
      draft = parseDate(editor.value) || new Date();
      if (!parseDate(editor.value)) { draft.setHours(draft.getHours() + 1, 0, 0, 0); }
      month = new Date(draft.getFullYear(), draft.getMonth(), 1);
      hour.value = String(draft.getHours()); minute.value = String(draft.getMinutes()); renderDays();
      popup.open(); days.querySelector('[tabindex="0"]').focus();
    }
    trigger.addEventListener("click", () => { if (popup.isOpen()) popup.close(); else open(); });
    editor.addEventListener("keydown", (event) => { if (event.altKey && event.key === "ArrowDown") { event.preventDefault(); open(); } });
  }

  function scan(root) {
    if (!(root instanceof Element) && root !== document) return;
    if (root.matches?.('input[type="datetime-local"]')) enhanceDate(root);
    root.querySelectorAll('input[type="datetime-local"]').forEach(enhanceDate);
  }
  const model = document.getElementById("model"); if (model) enhanceModels(model);
  scan(document);
  new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) if (node.isConnected) scan(node);
    for (const popup of popups) if (!popup.anchor.isConnected) { popup.panel.remove(); popups.delete(popup); }
  }).observe(document.body, { childList: true, subtree: true });
  function reposition() { for (const popup of popups) popup.position(); }
  window.addEventListener("resize", reposition);
  window.visualViewport?.addEventListener("resize", reposition);
  window.visualViewport?.addEventListener("scroll", reposition);
  document.addEventListener("scroll", (event) => {
    for (const popup of popups) if (!popup.panel.contains(event.target)) popup.position();
  }, true);
  document.addEventListener("focusin", (event) => {
    for (const popup of popups) if (popup.isOpen() && !popup.panel.contains(event.target) && !popup.anchor.contains(event.target)) popup.close();
  });
  document.addEventListener("close", (event) => {
    if (event.target instanceof HTMLDialogElement) for (const popup of popups) if (event.target.contains(popup.panel)) popup.close();
  }, true);
})();
