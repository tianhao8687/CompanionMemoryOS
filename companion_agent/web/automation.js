"use strict";

let automationState = null;
let automationLoading = false;
let lastNotificationId;
const autoStatus = { pending: "待确认 · 尚未执行", running: "执行中", succeeded: "已完成", failed: "失败", uncertain: "结果待核对", denied: "已拒绝", active: "等待触发", paused: "已暂停", cancelled: "已取消", completed: "已结束" };

function autoMessage(text, tone = "info") {
  $("automation-message").textContent = text;
  $("automation-message").dataset.tone = tone;
  $("automation-message").hidden = !text;
}

async function autoAction(button, work) {
  if (button) button.disabled = true;
  autoMessage("");
  try { await work(); await loadAutomation(); if (!state.busy) await loadMessages(); }
  catch (error) { autoMessage(error.message, "error"); }
  finally { if (button) button.disabled = false; }
}

function actionButton(label, work, primary = false) {
  const button = element("button", primary ? "primary-button" : "secondary-button", label);
  button.type = "button";
  button.addEventListener("click", () => autoAction(button, work));
  return button;
}

function autoCard(title, status, details) {
  const card = element("article", "auto-card");
  const heading = element("div", "auto-section-heading");
  const badge = element("span", "auto-state", autoStatus[status] || status);
  badge.dataset.status = status;
  heading.append(element("strong", "", title), badge);
  card.append(heading);
  if (details) card.append(element("p", "", details));
  return card;
}

function displayTool(name) {
  const tool = automationState?.tools.find((item) => item.name === name);
  return tool ? `${tool.server_id} / ${tool.remote_name}` : name;
}

function renderAutomation() {
  const data = automationState;
  $("action-approvals").replaceChildren();
  $("action-history").replaceChildren();
  for (const item of data.actions) {
    const card = autoCard(displayTool(item.tool_name), item.status, new Date(item.created_at).toLocaleString("zh-CN"));
    const details = element("details");
    details.append(element("summary", "", "查看参数与结果"), element("pre", "", JSON.stringify({ parameters: item.arguments, result: item.result }, null, 2)));
    card.append(details);
    if (item.status === "pending") {
      details.open = true;
      const controls = element("div", "auto-controls");
      controls.append(actionButton("确认并继续", async () => { const result = await api(`/api/automation/actions/${item.id}/approve`, { method: "POST", body: "{}" }); if (result.continuation_error) autoMessage(result.continuation_error); }, true), actionButton("拒绝", async () => { await api(`/api/automation/actions/${item.id}/deny`, { method: "POST", body: "{}" }); }));
      card.append(controls);
      $("action-approvals").append(card);
    } else {
      if (item.status === "succeeded") card.append(actionButton("恢复尚未完成的回复", () => api(`/api/automation/actions/${item.id}/resume`, { method: "POST", body: "{}" })));
      $("action-history").append(card);
    }
  }
  if (!$("action-history").children.length) $("action-history").append(element("p", "empty-state", "还没有执行记录。\n完成的小事，会留在这里。"));
  $("schedule-list").replaceChildren();
  for (const job of data.jobs) {
    const info = job.data;
    const card = autoCard(info.title, job.status, `${new Date(job.next_run).toLocaleString("zh-CN")} · ${info.repeat === "once" ? "一次" : info.repeat === "daily" ? "每天" : `每 ${info.interval_minutes} 分钟`}\n${info.message}`);
    if (job.last_result) {
      let resultText = job.last_result;
      try { const result = JSON.parse(resultText); resultText = result.message || autoStatus[result.status] || "查看操作记录了解详情"; } catch { /* Recovery messages are plain text. */ }
      card.append(element("p", "field-hint", `上次执行：${resultText}`));
    }
    if (["active", "paused"].includes(job.status)) {
      const controls = element("div", "auto-controls");
      const next = job.status === "paused" ? "active" : "paused";
      controls.append(actionButton(next === "active" ? "恢复" : "暂停", () => api(`/api/automation/schedules/${job.id}/${next}`, { method: "POST", body: "{}" })), actionButton("取消任务", () => api(`/api/automation/schedules/${job.id}/cancelled`, { method: "POST", body: "{}" })));
      card.append(controls);
    }
    $("schedule-list").append(card);
  }
  if (!data.jobs.length) $("schedule-list").append(element("p", "empty-state", "还没有安排提醒。\n留一个时间，让小事被记得。"));
  $("notification-list").replaceChildren();
  for (const item of data.notifications) $("notification-list").append(autoCard(item.title, item.seen ? "已读" : "未读", `${item.message}\n${new Date(item.created_at).toLocaleString("zh-CN")}`));
  if (!data.notifications.length) $("notification-list").append(element("p", "empty-state", "暂时没有新提醒。\n到时间了，我会在这里提醒你。"));
  $("automation-badge").hidden = !data.actions.some((item) => item.status === "pending") && !data.notifications.some((item) => !item.seen);
  renderServers();
  const selectedTool = $("schedule-tool").value;
  $("schedule-tool").replaceChildren(new Option("只在应用内提醒", ""));
  for (const tool of data.tools) $("schedule-tool").add(new Option(`${tool.server_id} / ${tool.remote_name}`, tool.name));
  $("schedule-tool").value = selectedTool;
}

function renderServers() {
  $("mcp-server-list").replaceChildren();
  if (!automationState.config.servers.length) $("mcp-server-list").append(element("p", "empty-state", "还没有连接工具。\n从下面添加一个你信任的服务。"));
  for (const server of automationState.config.servers) {
    const catalog = automationState.catalog[server.id] || [];
    const card = autoCard(server.label, server.enabled ? "已启用" : "已停用", `${server.transport} · ${catalog.length} 个已发现工具`);
    const controls = element("div", "auto-controls");
    controls.append(actionButton("编辑", async () => fillServer(server)), actionButton("连接并发现工具", () => api(`/api/automation/servers/${server.id}/connect`, { method: "POST", body: "{}" })), actionButton(server.enabled ? "停用" : "启用", async () => {
      const config = structuredClone(automationState.config);
      config.servers.find((item) => item.id === server.id).enabled = !server.enabled;
      await saveAutomationConfig(config);
    }));
    card.append(controls);
    for (const tool of catalog) {
      const section = element("details", "auto-tool-rule");
      section.append(element("summary", "", tool.name));
      section.append(element("p", "field-hint", tool.description));
      const label = element("label", "", "调用权限");
      const select = element("select");
      for (const [value, title] of [["ask", "每次确认"], ["allow", "允许自动调用"], ["off", "禁用"]]) select.add(new Option(title, value));
      const rule = server.tools[tool.name] || { mode: "ask", arguments: {} };
      select.value = rule.mode;
      label.append(select);
      const limits = element("label", "", "参数白名单 JSON（选填）");
      const input = element("textarea");
      input.rows = 2; input.value = JSON.stringify(rule.arguments || {});
      limits.append(input);
      section.append(label, limits, actionButton("保存此工具权限", async () => {
        const config = structuredClone(automationState.config);
        config.servers.find((item) => item.id === server.id).tools[tool.name] = { mode: select.value, arguments: JSON.parse(input.value || "{}") };
        await saveAutomationConfig(config);
      }));
      card.append(section);
    }
    $("mcp-server-list").append(card);
  }
}

async function saveAutomationConfig(config) {
  await api("/api/automation/config", { method: "PUT", body: JSON.stringify(config) });
}

async function loadAutomation(fill = false) {
  automationState = await api("/api/automation");
  if (fill) {
    const loop = automationState.config.loop;
    $("loop-enabled").checked = loop.enabled;
    $("loop-steps").value = loop.max_steps;
    $("loop-calls").value = loop.max_tool_calls;
    $("loop-timeout").value = loop.timeout_seconds;
    $("loop-tokens").value = loop.max_total_tokens;
  }
  renderAutomation();
}

function fillServer(server) {
  $("mcp-id").value = server.id;
  $("mcp-label").value = server.label;
  $("mcp-transport").value = server.transport;
  $("mcp-command").value = server.command || "";
  $("mcp-args").value = JSON.stringify(server.args || [], null, 2);
  $("mcp-env").value = JSON.stringify(server.env || {}, null, 2);
  $("mcp-url").value = server.url || "";
  $("mcp-bearer").value = server.bearer_env || "";
  $("mcp-timeout").value = server.timeout_seconds || 20;
  $("mcp-enabled").checked = server.enabled;
  updateTransport();
}

function updateTransport() {
  const local = $("mcp-transport").value === "stdio";
  $("mcp-local-fields").hidden = !local;
  $("mcp-remote-fields").hidden = local;
}

$("open-automation").addEventListener("click", async () => {
  $("automation-dialog").showModal(); autoMessage("");
  try { await loadAutomation(true); } catch (error) { autoMessage(error.message, "error"); }
});
document.querySelectorAll("[data-auto-tab]").forEach((button) => button.addEventListener("click", () => {
  autoMessage("");
  document.querySelectorAll("[data-auto-tab]").forEach((tab) => {
    const selected = tab === button;
    tab.setAttribute("aria-pressed", String(selected));
    $(`auto-${tab.dataset.autoTab}`).hidden = !selected;
  });
  document.querySelector(".automation-body").scrollTop = 0;
}));
$("refresh-automation").addEventListener("click", (event) => autoAction(event.currentTarget, async () => {}));
$("loop-form").addEventListener("submit", (event) => {
  event.preventDefault();
  autoAction(event.submitter, async () => {
    const config = structuredClone(automationState.config);
    config.loop = { enabled: $("loop-enabled").checked, max_steps: Number($("loop-steps").value), max_tool_calls: Number($("loop-calls").value), timeout_seconds: Number($("loop-timeout").value), max_total_tokens: Number($("loop-tokens").value) };
    await saveAutomationConfig(config);
  });
});
$("mcp-form").addEventListener("submit", (event) => {
  event.preventDefault();
  autoAction(event.submitter, async () => {
    const config = structuredClone(automationState.config);
    const id = $("mcp-id").value.trim();
    const previous = config.servers.find((item) => item.id === id);
    const local = $("mcp-transport").value === "stdio";
    const server = { id, label: $("mcp-label").value.trim(), enabled: $("mcp-enabled").checked, transport: $("mcp-transport").value, command: local ? $("mcp-command").value.trim() : "", args: local ? JSON.parse($("mcp-args").value) : [], env: local ? JSON.parse($("mcp-env").value) : {}, url: local ? "" : $("mcp-url").value.trim(), bearer_env: local ? "" : $("mcp-bearer").value.trim(), timeout_seconds: Number($("mcp-timeout").value), tools: previous?.tools || {} };
    config.servers = [...config.servers.filter((item) => item.id !== id), server];
    await saveAutomationConfig(config);
    autoMessage("服务已保存，点击“连接并发现工具”完成连接。");
  });
});
$("mcp-transport").addEventListener("change", updateTransport);
$("add-phone-template").addEventListener("click", (event) => autoAction(event.currentTarget, async () => {
  fillServer(await api("/api/automation/phone-template"));
  autoMessage("请把启动参数中的设备序列号和联系人改成你的实际值，再启用并保存。adb 不在 PATH 时可增加 --adb 和绝对路径。");
}));
$("schedule-repeat").addEventListener("change", () => { $("schedule-interval-label").hidden = $("schedule-repeat").value !== "interval"; });
$("schedule-form").addEventListener("submit", (event) => {
  event.preventDefault();
  autoAction(event.submitter, async () => {
    const text = $("schedule-message").value.trim();
    const tool = $("schedule-tool").value;
    await api("/api/automation/schedules", { method: "POST", body: JSON.stringify({ title: text.slice(0, 100), message: text, at: new Date($("schedule-at").value).toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai", repeat: $("schedule-repeat").value, interval_minutes: $("schedule-repeat").value === "interval" ? Number($("schedule-interval").value) : null, conversation_id: state.active, tool_name: tool || null, arguments: tool ? JSON.parse($("schedule-arguments").value) : {} }) });
    $("schedule-message").value = ""; toast("任务已保存。");
  });
});
$("read-notifications").addEventListener("click", (event) => autoAction(event.currentTarget, () => api("/api/automation/notifications/read", { method: "POST", body: "{}" })));
$("cancel-run").addEventListener("click", async () => {
  if (!state.failed?.request_id) return;
  try { await api(`/api/automation/cancel/${encodeURIComponent(state.failed.request_id)}`, { method: "POST", body: "{}" }); toast("已请求停止；正在进行的调用返回后停止后续步骤。"); }
  catch (error) { toast(error.message); }
});
setInterval(async () => {
  if (automationLoading || !state.config || document.hidden) return;
  automationLoading = true;
  try {
    const data = await api("/api/automation");
    const latest = data.notifications[0];
    if (lastNotificationId !== undefined && latest && latest.id !== lastNotificationId && !latest.seen) toast(`${latest.title}：${latest.message.slice(0, 100)}`);
    lastNotificationId = latest?.id || "";
    $("automation-badge").hidden = !data.actions.some((item) => item.status === "pending") && !data.notifications.some((item) => !item.seen);
    // Keep forms and pending confirmation targets stable while the user is editing.
  } catch { /* The normal connection UI handles unavailable local services. */ }
  finally { automationLoading = false; }
}, 6000);
