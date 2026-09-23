"use strict";

function fillLifeSettings(settings) {
  $("model-mode").value = settings.model_mode;
  $("extract-memory").checked = settings.cognition.extract_memory;
  $("model-extraction").checked = settings.cognition.model_extraction;
  $("embedding-backend").value = settings.cognition.embedding_backend;
  $("embedding-url").value = settings.cognition.embedding.base_url;
  $("embedding-model").value = settings.cognition.embedding.model;
  $("embedding-key-env").value = settings.cognition.embedding.api_key_env;
  $("proactive-enabled").checked = settings.proactive_enabled;
  $("quiet-start").value = settings.quiet_start;
  $("quiet-end").value = settings.quiet_end;
}

function readLifeSettings() {
  return {
    model_mode: $("model-mode").value,
    proactive_enabled: $("proactive-enabled").checked,
    quiet_start: Number($("quiet-start").value), quiet_end: Number($("quiet-end").value),
    cognition: { ...state.config.settings.cognition,
      extract_memory: $("extract-memory").checked,
      model_extraction: $("model-extraction").checked,
      embedding_backend: $("embedding-backend").value,
      embedding: { ...state.config.settings.cognition.embedding,
        base_url: $("embedding-url").value, model: $("embedding-model").value,
        api_key_env: $("embedding-key-env").value,
      },
    },
  };
}

async function requestChat(item) {
  const response = await fetch("/api/chat/stream", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Companion-Client": "local-web" },
    body: JSON.stringify(item),
  });
  if (!response.ok || !response.body) throw new Error("请求未完成，请重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const draft = element("article", "message assistant");
  const body = element("div", "message-body");
  const bubble = element("div", "bubble");
  body.append(element("small", "field-hint", "正在生成 · 完成后保存"), bubble);
  draft.append(body);
  let buffer = "", result = null;
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "delta") {
          if (!draft.isConnected) $("messages").append(draft);
          bubble.textContent += event.text;
          $("messages-scroll").scrollTop = $("messages-scroll").scrollHeight;
        } else if (event.type === "reset") { bubble.textContent = ""; draft.remove(); }
        else if (event.type === "status") $("typing-label").textContent = event.message;
        else if (event.type === "error") throw new Error(event.message);
        else if (event.type === "result") result = event.result;
      }
      if (chunk.done) break;
    }
    if (!result) throw new Error("回复中断，未完成的文字没有写入历史。可以重试。");
    return result;
  } finally { draft.remove(); await reader.cancel().catch(() => {}); }
}

function localButton(label, action, className = "text-button") {
  const button = element("button", className, label);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await action(); } catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  });
  return button;
}

function addMemoryControls(card, record) {
  const controls = element("div", "auto-controls");
  const decision = (action) => async () => {
    await api(`/api/memories/${record.id}/${action}`, { method: "POST", body: "{}" });
    await openMemories();
  };
  if (record.status === "active") {
    controls.append(localButton("更正", async () => {
      if (card.querySelector(".memory-editor")) { card.querySelector(".memory-editor textarea").focus(); return; }
      const editor = element("textarea"); editor.value = record.content; editor.maxLength = 2000;
      editor.setAttribute("aria-label", "更正记忆内容");
      const panel = element("div", "memory-editor");
      panel.append(editor, localButton("保存更正", async () => {
        await api(`/api/memories/${record.id}`, { method: "PUT", body: JSON.stringify({ content: editor.value, request_id: crypto.randomUUID(), conversation_id: state.active }) });
        await openMemories();
      }, "primary-button"), localButton("取消编辑", async () => { panel.remove(); controls.querySelector("button").focus(); }, "secondary-button"));
      card.append(panel); editor.focus();
    }), localButton("遗忘", decision("forget")));
  }
  const evidence = element("details");
  evidence.append(element("summary", "", "来源证据"), element("p", "field-hint", record.source_excerpt || record.content));
  controls.append(evidence); card.append(controls);
}

function renderEvents(events) {
  if (!events.length) return;
  const section = element("section", "memory-group");
  section.append(element("h3", "", "还想听你说的小事"));
  if (!state.config.settings.proactive_enabled && events.some(item => ["candidate", "scheduled"].includes(item.status))) {
    section.append(element("p", "field-hint", "在陪伴设置中开启主动关心后，才会按这些时间联系你。"));
  }
  const names = { candidate: "尚未安排关心时间", scheduled: "等待合适时机", waiting: "已关心，等你愿意再聊", cancelled: "已取消", resolved: "已结束", invalidated: "来源已失效" };
  for (const item of events) {
    const card = element("div", "memory-card");
    card.append(element("p", "", item.summary), element("small", "field-hint", names[item.status] || item.status));
    if (["candidate", "scheduled"].includes(item.status)) {
      const label = element("label", "", "何时之后可以关心我（遵守安静时段）");
      const time = element("input"); time.type = "datetime-local"; label.append(time);
      if (item.due_at) { const date = new Date(item.due_at); time.value = new Date(date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
      card.append(label, localButton("安排一次关心", async () => {
        if (!time.value) throw new Error("请选择希望开始关心的时间。");
        await api(`/api/events/${item.id}`, { method: "PUT", body: JSON.stringify({ status: "scheduled", due_at: new Date(time.value).toISOString() }) });
        await openMemories();
        if (!state.config.settings.proactive_enabled) toast("已记录时间；请在陪伴设置中开启主动关心。");
      }));
    }
    if (["candidate", "scheduled", "waiting"].includes(item.status)) {
      for (const [status, label] of [["cancelled", "先别问了"], ["resolved", "这件事结束了"]]) card.append(localButton(label, async () => {
        await api(`/api/events/${item.id}`, { method: "PUT", body: JSON.stringify({ status }) }); await openMemories();
      }));
    }
    section.append(card);
  }
  $("memory-content").append(section);
}

let channelConfig;
async function loadChannels() {
  const data = await api("/api/channels"); channelConfig = data.config;
  $("channel-transport").value = channelConfig.transport;
  $("channel-owner").value = channelConfig.owner_id;
  $("channel-enabled").checked = channelConfig.enabled;
  $("channel-state").textContent = `${data.config.enabled ? "渠道已开启" : "渠道未开启"} · ${data.logged_in ? "已有微信凭证" : "未登录微信"}\n${data.error || ""}\n` + data.deliveries.map((d) => `${d.id.slice(0, 8)} · ${d.status === "sent" ? "已送达" : "送达待核对"}`).join("\n");
}
document.querySelector('[data-auto-tab="channels"]').addEventListener("click", () => loadChannels().catch(e => toast(e.message)));
$("channel-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/channels", { method: "PUT", body: JSON.stringify({ ...channelConfig,
      transport: $("channel-transport").value, owner_id: $("channel-owner").value,
      enabled: $("channel-enabled").checked, conversation_id: state.active,
    }) }); await loadChannels(); toast("已绑定当前对话。");
  } catch (error) { toast(error.message); }
});
$("channel-demo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/channels/demo/message", { method: "POST", body: JSON.stringify({ delivery_id: crypto.randomUUID(), sender_id: $("channel-owner").value, text: $("channel-demo-text").value }) });
    $("channel-demo-text").value = ""; await loadChannels(); await loadMessages();
  } catch (error) { toast(error.message); }
});
for (const [id, step] of [["channel-login", "start"], ["channel-login-poll", "poll"]]) $(id).addEventListener("click", async () => {
  try {
    const result = await api(`/api/channels/login/${step}`, { method: "POST", body: "{}" });
    $("channel-login-result").textContent = result.status === "confirmed" ? "登录完成，可开启渠道。" : "请用支持 ClawBot 的微信完成登录，再检查结果。";
    if (result.login_url) {
      const url = new URL(result.login_url);
      if (url.protocol !== "https:") throw new Error("登录地址格式不正确。");
      const link = element("a", "", "打开微信登录入口"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
      $("channel-login-result").append(link);
    }
    await loadChannels();
  } catch (error) { toast(error.message); }
});

let recognition;
$("voice-input").addEventListener("click", () => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) { toast("当前浏览器不支持语音输入，可以继续打字。"); return; }
  if (recognition) { recognition.stop(); return; }
  recognition = new Recognition(); recognition.lang = "zh-CN"; recognition.interimResults = false;
  $("voice-status").textContent = "浏览器正在听（识别服务可能联网）；转文字后由你确认发送。";
  recognition.onresult = (event) => { $("message-input").value += event.results[0][0].transcript; resizeComposer(); };
  recognition.onerror = () => toast("语音识别未完成，请检查麦克风权限或改用打字。");
  recognition.onend = () => { recognition = null; $("voice-status").textContent = ""; };
  recognition.start();
});
$("read-reply").addEventListener("click", () => {
  if (!window.speechSynthesis) { toast("当前浏览器不支持朗读。"); return; }
  const reply = [...state.messages].reverse().find(message => message.role === "assistant");
  if (!reply) return;
  speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(reply.content); utterance.lang = "zh-CN"; speechSynthesis.speak(utterance);
});
$("stop-reply").addEventListener("click", async () => {
  window.speechSynthesis?.cancel(); recognition?.stop();
  if (state.busy && state.failed) await api(`/api/automation/cancel/${state.failed.request_id}`, { method: "POST", body: "{}" }).catch(e => toast(e.message));
});
let desktopNotifications = false;
$("browser-notifications").addEventListener("click", async () => {
  if (!("Notification" in window)) { toast("当前浏览器不支持桌面通知。"); return; }
  desktopNotifications = await Notification.requestPermission() === "granted";
  toast(desktopNotifications ? "本次页面运行期间将显示桌面提醒。" : "仍可在能力面板查看提醒。");
});
let seenNotice;
setInterval(async () => {
  if (!state.active || state.busy || state.loading) return;
  try {
    if (!document.hidden) {
      const data = await api(`/api/conversations/${state.active}/messages?limit=1`);
      if (data.messages[0] && !state.messages.some(m => m.id === data.messages[0].id)) await loadMessages();
    }
    if (desktopNotifications) {
      const automation = await api("/api/automation");
      const notice = automation.notifications.find(n => !n.seen);
      if (notice && notice.id !== seenNotice) { new Notification(notice.title, { body: notice.message }); seenNotice = notice.id; }
    }
  } catch { /* Keep the last delivered history available during reconnects. */ }
}, 5000);
