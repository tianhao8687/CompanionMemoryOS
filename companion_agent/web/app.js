"use strict";

const $ = (id) => document.getElementById(id);
const state = { config: null, conversations: [], active: null, messages: [], busy: false, failed: null, hasMore: false, clearKey: false, loading: false };
let toastTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Companion-Client": "local-web", ...options.headers },
  });
  let payload;
  try { payload = await response.json(); } catch { throw new Error("服务没有返回有效内容，请检查本地服务是否仍在运行。"); }
  if (!response.ok) throw new Error(payload.detail?.message || "暂时无法完成，请稍后重试。");
  return payload;
}

function toast(message) {
  clearTimeout(toastTimer);
  const notice = $("toast");
  if (notice.showPopover && notice.matches(":popover-open")) notice.hidePopover();
  (document.querySelector("dialog[open]") || document.body).append(notice);
  notice.textContent = message;
  notice.hidden = false;
  // A top-layer notice stays visible above modal sheets too.
  if (notice.showPopover) { notice.popover = "manual"; notice.showPopover(); }
  toastTimer = setTimeout(() => {
    if (notice.showPopover && notice.matches(":popover-open")) notice.hidePopover();
    notice.hidden = true;
  }, 5000);
}

function ready() {
  const settings = state.config?.settings;
  return Boolean((state.config?.model_ready ?? state.config?.key_configured) && settings?.storage_consent && settings?.model_consent);
}

function setSidebar(open, restoreFocus = false) {
  const mobile = window.matchMedia("(max-width: 760px)").matches;
  const expanded = Boolean(open && mobile);
  const wasExpanded = $("sidebar").classList.contains("open");
  $("sidebar").classList.toggle("open", expanded);
  $("sidebar-backdrop").hidden = !expanded;
  $("toggle-sidebar").setAttribute("aria-expanded", String(expanded));
  document.querySelector(".chat-panel").inert = expanded;
  if (expanded) $("close-sidebar").focus();
  else if (restoreFocus && mobile && wasExpanded) $("toggle-sidebar").focus();
}

function selectSettingsTab(name) {
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    const selected = button.dataset.settingsTab === name;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll("[data-settings-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.settingsPanel !== name;
  });
  $("settings-dialog").querySelector(".settings-body").scrollTop = 0;
}

function updateModelFields() {
  const offline = $("model-mode").value === "offline";
  $("api-settings").hidden = offline;
  $("key-status").hidden = offline;
  $("model-mode-hint").textContent = offline
    ? "离线模式用固定规则演示记忆、提醒和工具流程，不能代表真实模型的聊天质量。"
    : "填写服务提供的 Key 与模型名称。保存后用于聊天，也可以测试连接。";
  $("test-connection").textContent = offline ? "验证离线模式" : "保存并测试连接";
}

function updateProfile() {
  const settings = state.config.settings;
  $("partner-name").textContent = settings.companion_name;
  $("welcome-name").textContent = settings.companion_name;
  document.querySelectorAll(".small-avatar span, .hero-avatar span").forEach((span) => { span.textContent = [...settings.companion_name][0]; });
  $("user-label").textContent = settings.user_name || "我的陪伴设置";
  $("user-avatar").textContent = [...(settings.user_name || "你")][0];
  $("connection-status").textContent = ready() ? (settings.model_mode === "offline" ? "离线演示 · 未连接真实模型" : "已配置 · 随时可以开始聊天") : "先选择对话模式与保存偏好";
  $("model-mode-label").textContent = settings.model_mode === "offline" ? "离线规则演示 · 记忆保存在本机" : "由所配置的模型回应 · 记忆保存在本机";
  $("setup-notice").hidden = ready();
  $("typing-label").textContent = `${settings.companion_name}正在想怎么回应你…`;
}

function renderConversations() {
  $("conversations").replaceChildren();
  $("conversation-count").textContent = state.conversations.length;
  for (const item of state.conversations) {
    const button = element("button", `conversation-item${item.id === state.active ? " active" : ""}`);
    button.setAttribute("aria-current", item.id === state.active ? "page" : "false");
    button.append(element("strong", "", item.title), element("small", "", new Date(item.updated_at).toLocaleDateString("zh-CN", { month: "long", day: "numeric" })));
    button.disabled = state.busy || state.loading;
    button.addEventListener("click", () => selectConversation(item.id).catch((error) => toast(error.message)));
    $("conversations").append(button);
  }
}

function renderMessages(scroll = true) {
  $("messages").replaceChildren();
  $("welcome").hidden = state.messages.length > 0;
  $("load-older").hidden = !state.hasMore;
  const replies = new Set(state.messages.filter((message) => message.role === "assistant").map((message) => message.reply_to));
  for (const message of state.messages) {
    const row = element("article", `message ${message.role}`);
    if (message.role === "assistant") {
      const avatar = element("div", "avatar");
      avatar.setAttribute("aria-hidden", "true");
      avatar.append(element("span", "", [...state.config.settings.companion_name][0]));
      row.append(avatar);
    }
    const body = element("div", "message-body");
    const heading = element("div", "message-heading");
    heading.append(element("span", "", message.role === "user" ? (state.config.settings.user_name || "你") : state.config.settings.companion_name));
    const time = element("time", "", new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }));
    time.dateTime = message.created_at;
    heading.append(time);
    body.append(heading, element("div", "bubble", message.content));
    if (message.role === "user" && !replies.has(message.id) && message === state.messages.at(-1) && !state.busy) {
      body.append(element("div", "pending-note", "等待回复 · 可以重试这条消息"));
    }
    row.append(body);
    $("messages").append(row);
  }
  if (scroll) $("messages-scroll").scrollTop = state.messages.length ? $("messages-scroll").scrollHeight : 0;
}

function rememberActive(id) {
  try { localStorage.setItem("companion-active-conversation", id); } catch { /* Local storage is optional. */ }
}

async function loadMessages(older = false) {
  const before = older && state.messages.length ? `?before=${state.messages[0].sequence}` : "";
  const result = await api(`/api/conversations/${encodeURIComponent(state.active)}/messages${before}`);
  state.messages = older ? [...result.messages, ...state.messages] : result.messages;
  state.hasMore = result.has_more;
  if (!older) {
    const last = state.messages.at(-1);
    state.failed = last?.role === "user" && last.request_id ? { conversation_id: state.active, request_id: last.request_id, content: last.content } : null;
    $("chat-error").hidden = !state.failed;
    if (state.failed) $("chat-error-text").textContent = "上一条消息还没有完整回复，可以继续重试。";
  }
  renderMessages(!older);
}

async function selectConversation(id) {
  if (state.busy || state.loading) return;
  const previous = { active: state.active, messages: state.messages, hasMore: state.hasMore, failed: state.failed };
  state.loading = true;
  state.active = id;
  rememberActive(id);
  setSidebar(false, true);
  renderConversations();
  $("send-message").disabled = true;
  try { await loadMessages(); }
  catch (error) {
    Object.assign(state, previous);
    if (previous.active) rememberActive(previous.active);
    renderMessages(false);
    throw error;
  }
  finally { state.loading = false; $("send-message").disabled = false; renderConversations(); }
}

async function refreshConversations() {
  const result = await api("/api/bootstrap");
  state.conversations = result.conversations;
  renderConversations();
}

function setBusy(busy) {
  state.busy = busy;
  $("typing").hidden = !busy;
  $("send-message").disabled = busy;
  $("new-chat").disabled = busy;
  $("retry-message").disabled = busy;
  $("load-older").disabled = busy;
  $("open-memory").disabled = busy;
  $("open-settings").disabled = busy;
  renderConversations();
}

async function sendMessage(retry = false) {
  if (state.busy || state.loading || !state.active) return;
  const text = $("message-input").value.trim();
  if (!retry && !text) return;
  if (!ready()) { openSettings(); return; }
  const item = retry ? state.failed : { conversation_id: state.active, request_id: crypto.randomUUID(), content: text };
  if (!item) return;
  if (!retry) { $("message-input").value = ""; resizeComposer(); }
  state.failed = item;
  if (!state.messages.some((message) => message.request_id === item.request_id)) {
    state.messages.push({ id: `pending-${item.request_id}`, role: "user", content: item.content, request_id: item.request_id, created_at: new Date().toISOString(), sequence: null });
  }
  setBusy(true);
  $("chat-error").hidden = true;
  renderMessages();
  try {
    const result = await requestChat(item);
    state.messages = state.messages.filter((message) => message.request_id !== item.request_id && message.id !== result.assistant.id);
    state.messages.push(result.user, result.assistant);
    state.failed = null;
    renderMessages();
    await refreshConversations().catch(() => {});
  } catch (error) {
    $("chat-error-text").textContent = error.message;
    $("chat-error").hidden = false;
  } finally {
    setBusy(false);
    renderMessages();
    $("messages-scroll").scrollTop = $("messages-scroll").scrollHeight;
    $("message-input").focus();
  }
}

function openSettings() {
  if (!state.config || state.busy) return;
  const settings = state.config.settings;
  fillLifeSettings(settings);
  $("companion-name").value = settings.companion_name;
  $("user-name").value = settings.user_name;
  $("persona-notes").value = settings.persona_notes;
  document.querySelector(`input[name="style"][value="${settings.style}"]`).checked = true;
  $("romance-consent").checked = settings.romance_consent;
  $("storage-consent").checked = settings.storage_consent;
  $("model-consent").checked = settings.model_consent;
  $("api-key").value = "";
  $("api-key").placeholder = state.config.key_configured ? "已配置，留空可保留现有 Key" : "sk-…";
  $("model").value = settings.deepseek.model;
  $("base-url").value = settings.deepseek.base_url;
  $("max-tokens").value = settings.deepseek.max_tokens;
  $("temperature").value = settings.deepseek.temperature;
  $("thinking").value = settings.deepseek.thinking;
  $("key-status").textContent = state.config.key_source === "environment" ? "从环境变量读取" : (state.config.key_configured ? "本次运行已配置" : "尚未配置");
  $("settings-message").hidden = true;
  state.clearKey = false;
  setSidebar(false, true);
  selectSettingsTab("persona");
  updateModelFields();
  $("settings-dialog").showModal();
}

async function saveSettings(test = false) {
  const form = $("settings-form");
  if (!form.checkValidity()) {
    const invalid = form.querySelector(":invalid");
    const panel = invalid?.closest("[data-settings-panel]");
    if (panel) selectSettingsTab(panel.dataset.settingsPanel);
    if (invalid?.closest("#api-settings")) $("api-settings").hidden = false;
    let ancestor = invalid?.parentElement;
    while (ancestor && ancestor !== form) {
      if (ancestor.tagName === "DETAILS") ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    form.reportValidity();
    return;
  }
  const settings = {
    ...state.config.settings,
    ...readLifeSettings(),
    companion_name: $("companion-name").value.trim(),
    user_name: $("user-name").value.trim(),
    style: document.querySelector("input[name=style]:checked").value,
    persona_notes: $("persona-notes").value.trim(),
    romance_consent: $("romance-consent").checked,
    storage_consent: $("storage-consent").checked,
    model_consent: $("model-consent").checked,
    deepseek: {
      ...state.config.settings.deepseek,
      model: $("model").value.trim(), base_url: $("base-url").value.trim(),
      max_tokens: Number($("max-tokens").value), temperature: Number($("temperature").value), thinking: $("thinking").value,
    },
  };
  const buttons = [$("save-settings"), $("test-connection")];
  buttons.forEach((button) => { button.disabled = true; });
  $("settings-message").hidden = true;
  try {
    const result = await api("/api/settings", { method: "PUT", body: JSON.stringify({ settings, api_key: $("api-key").value.trim() || null, clear_api_key: state.clearKey }) });
    state.config = result;
    state.clearKey = false;
    $("api-key").value = "";
    $("api-key").placeholder = result.key_configured ? "已配置，留空可保留现有 Key" : "sk-…";
    $("key-status").textContent = result.key_configured ? "已配置" : "尚未配置";
    updateProfile();
    renderMessages(false);
    if (test) {
      $("settings-message").dataset.tone = "info";
      $("settings-message").textContent = settings.model_mode === "offline" ? "正在验证离线对话流程…" : "设置已保存，正在实际连接模型…";
      $("settings-message").hidden = false;
      const checked = await api("/api/connection", { method: "POST", body: "{}" });
      $("settings-message").textContent = `${checked.message}（${checked.model}）`;
      $("settings-message").dataset.tone = "success";
      $("connection-status").textContent = settings.model_mode === "offline" ? "离线流程已验证 · 未连接真实模型" : "连接已验证 · 在这里听你说";
    } else {
      $("settings-dialog").close();
      toast(ready() ? "设置保存好了，开始我们的对话吧。" : "设置已保存，请检查对话模式与授权。");
    }
  } catch (error) {
    $("settings-message").textContent = error.message;
    $("settings-message").dataset.tone = "error";
    $("settings-message").hidden = false;
  } finally { buttons.forEach((button) => { button.disabled = false; }); }
}

function memoryGroup(title, records) {
  if (!records.length) return;
  const section = element("section", "memory-group");
  section.append(element("h3", "", title));
  for (const record of records) {
    const card = element("div", "memory-card");
    if (record.title) card.append(element("strong", "", record.title));
    card.append(element("p", "", record.content));
    if (record.id) addMemoryControls(card, record);
    section.append(card);
  }
  $("memory-content").append(section);
}

async function openMemories() {
  if (!state.active || state.busy) return;
  $("memory-content").replaceChildren(element("p", "memory-empty", "正在翻开我们的手札…"));
  if (!$("memory-dialog").open) $("memory-dialog").showModal();
  try {
    const data = await api(`/api/memories/${encodeURIComponent(state.active)}`);
    $("memory-content").replaceChildren();
    const tags = element("div", "relationship-tags");
    const identities = { romantic_partner: "约定的恋人", friend: "朋友", close_friend: "亲密朋友", companion: "日常陪伴", undefined: "慢慢认识", custom: "自定义关系" };
    const stages = { new: "初识，相处从这里开始", familiar: "渐渐熟悉", established: "有了共同的默契" };
    tags.append(element("span", "", identities[data.relationship.identity.type] || "日常陪伴"), element("span", "", stages[data.relationship.stage] || "慢慢认识"));
    $("memory-content").append(tags);
    memoryGroup("记得你说过", data.memories);
    renderEvents(data.events || []);
    const stateNames = { fatigue: "最近感到疲惫", sleep_loss: "最近睡得不太好", sadness: "最近有些难过", pressure: "最近有些压力", listen: "这会儿想先被倾听", problem_solve: "这会儿希望一起想办法", reduce: "最近希望表达克制一些", normal: "按平时的方式相处", hold: "暂时放缓亲密表达" };
    memoryGroup("留意你的当下", data.states.filter((item) => item.status === "active").map((item) => ({ content: stateNames[item.value] || item.value })));
    memoryGroup("相处的边界", data.relationship.boundaries.map((item) => ({ content: item.description || item.content || item.rule || "已记录的相处边界" })));
    memoryGroup("走过的小片段", data.experiences.map((item) => ({ title: item.title, content: item.summary || item.description || "来自已经发生的对话。" })));
    if (!data.memories.length && !data.events?.length && !data.experiences.length && !data.states.length && !data.relationship.boundaries.length) {
      $("memory-content").append(element("p", "memory-empty", "手札还是空白的。\n说说你的称呼、喜好，或今天的小事。\n例如：“以后叫我小雨”“记住：我喜欢白色郁金香”。"));
    }
  } catch (error) { $("memory-content").replaceChildren(element("p", "memory-empty", error.message)); }
}

function resizeComposer() {
  const input = $("message-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}

$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); sendMessage(); });
$("message-input").addEventListener("input", resizeComposer);
$("message-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); sendMessage(); }
});
$("retry-message").addEventListener("click", () => sendMessage(true));
$("open-settings").addEventListener("click", openSettings);
$("setup-now").addEventListener("click", openSettings);
$("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
$("test-connection").addEventListener("click", () => saveSettings(true));
$("clear-key").addEventListener("click", () => { state.clearKey = true; $("api-key").value = ""; $("key-status").textContent = "保存后清除；环境变量 Key 仍可用"; });
$("open-memory").addEventListener("click", openMemories);
$("toggle-sidebar").addEventListener("click", () => setSidebar(!$("sidebar").classList.contains("open")));
$("close-sidebar").addEventListener("click", () => setSidebar(false, true));
$("sidebar-backdrop").addEventListener("click", () => setSidebar(false, true));
window.matchMedia("(max-width: 760px)").addEventListener("change", () => setSidebar(false));
$("model-mode").addEventListener("change", updateModelFields);
document.querySelectorAll("[data-settings-tab]").forEach((button, index, buttons) => {
  button.addEventListener("click", () => selectSettingsTab(button.dataset.settingsTab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 :
      (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
    selectSettingsTab(buttons[next].dataset.settingsTab);
    buttons[next].focus();
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if ($("sidebar").classList.contains("open")) setSidebar(false, true);
    if ($("composer-more").open) { $("composer-more").open = false; $("composer-more").querySelector("summary").focus(); }
  }
  if (event.key === "Tab" && $("sidebar").classList.contains("open")) {
    const items = [...$("sidebar").querySelectorAll("a, button:not(:disabled)")];
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
  }
});
document.addEventListener("click", (event) => {
  if (!$("composer-more").contains(event.target) || event.target.closest(".tools-popover button")) $("composer-more").open = false;
});
$("load-older").addEventListener("click", async () => {
  if (state.loading || state.busy) return;
  state.loading = true;
  $("load-older").disabled = true;
  try { await loadMessages(true); } catch (error) { toast(error.message); }
  finally { state.loading = false; $("load-older").disabled = false; }
});
$("new-chat").addEventListener("click", async () => {
  if (state.busy || state.loading) return;
  $("new-chat").disabled = true;
  try { const item = await api("/api/conversations", { method: "POST", body: "{}" }); await refreshConversations(); await selectConversation(item.id); }
  catch (error) { toast(error.message); }
  finally { $("new-chat").disabled = false; }
});
$("export-data").addEventListener("click", async () => {
  try {
    const data = await api("/api/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = element("a"); link.href = url; link.download = "心隅-我的记录.json";
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message); }
});
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
$("settings-dialog").addEventListener("close", () => { $("api-key").value = ""; });
document.querySelectorAll("[data-starter]").forEach((button) => button.addEventListener("click", () => { $("message-input").value = button.dataset.starter; resizeComposer(); $("message-input").focus(); }));

(async function init() {
  try {
    state.config = await api("/api/bootstrap");
    state.conversations = state.config.conversations;
    updateProfile();
    let saved;
    try { saved = localStorage.getItem("companion-active-conversation"); } catch { /* Optional. */ }
    await selectConversation(state.conversations.find((item) => item.id === saved)?.id || state.conversations[0].id);
  } catch (error) { $("connection-status").textContent = "本地服务连接中断"; toast(error.message); }
})();
