"use strict";

(() => {
  let data = null, busy = false, fetching = false, offset = 0, generation = 0, lastFetch = 0;
  let setupSource = "chat", startRequest = null, miniWindow, progressRequest = null;
  const cards = new Map(), notifying = new Set();
  const room = $("nook-dialog"), setup = $("focus-setup-dialog");
  const preferences = () => data?.preferences || {focus_sound:"silent", focus_notice:"once"};
  const paint = () => { focusUI.render(data, busy); focusUI.time(data, offset); if ($("focus-history-dialog").open) focusUI.history(data); };
  function error(message = "") {
    for (const id of ["focus-error","focus-setup-error"]) { $(id).textContent = message; $(id).hidden = !message; }
  }
  async function notify(next) {
    const session = next.session;
    if (!session || !["focus_done","done"].includes(session.phase) || preferences().focus_notice === "off") return;
    if (next.server_now - session.ended_at > 120 || session.notice_revision === session.revision) return;
    const key = session.id + ":" + session.revision;
    if (notifying.has(key)) return;
    notifying.add(key);
    try {
      const claim = await api("/api/focus/notice",{method:"POST",body:JSON.stringify({session_id:session.id,revision:session.revision})});
      if (!claim.claimed) return;
      const message = session.phase === "focus_done" ? session.focus_minutes + " 分钟到了。" : "休息时间到了。";
      toast(message);
      if ("Notification" in window && Notification.permission === "granted") {
        const notice = new Notification(state.config.settings.companion_name, {body:message,tag:"xinyu-focus",silent:true});
        notice.onclick = () => { window.focus(); openRoom(); notice.close(); };
      }
    } catch { notifying.delete(key); /* A failed delivery can be retried on the next sync. */ }
  }
  function receive(next) {
    if (!next.preferences) next.preferences = preferences();
    const before = data?.session;
    data = next; offset = next.server_now * 1000 - Date.now();
    if (focusUI.closed(next.session) || preferences().focus_sound === "silent") focusAudio.stop();
    if (before?.id !== next.session?.id) { progressRequest = null; $("focus-progress").value = ""; $("focus-progress-result").textContent = ""; }
    paint(); notify(next);
  }
  async function refresh() {
    if (fetching || busy || !state.config || !state.active) return;
    fetching = true; lastFetch = Date.now(); const ticket = generation;
    try {
      const next = await api("/api/focus?conversation_id=" + encodeURIComponent(state.active));
      if (ticket === generation) { receive(next); error(); }
    } catch { if (ticket === generation) error("暂时连不上计时服务。恢复连接后会核对时间。"); }
    finally { fetching = false; }
  }
  async function mutate(path, body, method = "POST") {
    if (busy) return false;
    busy = true; generation++; paint(); error();
    try { receive(await api(path,{method,...(body ? {body:JSON.stringify(body)} : {})})); return true; }
    catch (failure) {
      try { receive(await api("/api/focus?conversation_id=" + encodeURIComponent(state.active))); } catch { /* Keep last known state. */ }
      error(failure.message); toast(failure.message); return false;
    } finally { busy = false; paint(); }
  }
  async function playRain() {
    if (preferences().focus_sound !== "rain" || focusUI.closed(data?.session)) return;
    try { await focusAudio.play(); } catch (failure) { error(failure.message); }
    paint();
  }
  async function act(action) {
    if (!data?.session) return;
    const session = data.session;
    if (await mutate("/api/focus/action",{session_id:session.id,revision:session.revision,action})) {
      if (action === "resume" || action === "extend") await playRain();
      if (action === "finish") focusAudio.stop();
    }
  }
  async function start(values, source = "chat") {
    if (busy || !state.active) return false;
    const key = JSON.stringify(values);
    if (startRequest?.key !== key) startRequest = {key,body:{request_id:crypto.randomUUID(),conversation_id:state.active,...values}};
    // Unlock only user-selected audio during the explicit start gesture.
    if (preferences().focus_sound === "rain") { try { await focusAudio.play(); } catch { /* Show a play button. */ } }
    const ok = await mutate("/api/focus",startRequest.body);
    if (ok) {
      startRequest = null;
      if (setup.open) setup.close();
      toast("好，先 " + values.focus_minutes + " 分钟。");
      if (source === "room") openRoom();
      else { if (room.open) room.close(); $("message-input").focus(); }
    } else if (focusUI.closed(data?.session)) focusAudio.stop();
    paint(); return ok;
  }
  async function openRoom() { await window.nookController.open(); paint(); await refresh(); }
  async function openSetup(source = "chat") {
    setupSource = source;
    await refresh();
    if (data?.session && !focusUI.closed(data.session)) { await openRoom(); return; }
    if (!setup.open) setup.showModal();
    paint(); $("focus-intention").focus();
  }
  $("open-focus").addEventListener("click",() => openSetup());
  $("nook-desk-focus").addEventListener("click",() => openSetup("room"));
  $("focus-mini-open").addEventListener("click",openRoom);
  $("focus-desk-entry").addEventListener("click",() => openSetup("room"));
  $("focus-new").addEventListener("click",() => openSetup("room"));
  $("focus-primary-action").addEventListener("click",() => act($("focus-primary-action").dataset.action));
  $("focus-mini-pause").addEventListener("click",() => act($("focus-mini-pause").dataset.action));
  for (const id of ["focus-finish","focus-mini-finish"]) $(id).addEventListener("click",() => act("finish"));
  $("focus-extend").addEventListener("click",() => act("extend"));
  $("focus-form").addEventListener("submit",async event => {
    event.preventDefault();
    if (!$("focus-form").reportValidity()) return;
    await start({intention:$("focus-intention").value.trim(),focus_minutes:Number($("focus-minutes").value),rest_minutes:Number($("focus-rest-minutes").value)},setupSource);
  });
  document.querySelectorAll("[data-focus-minutes]").forEach(button => button.addEventListener("click",() => {
    $("focus-minutes").value = button.dataset.focusMinutes;
    document.querySelectorAll("[data-focus-minutes]").forEach(b => b.setAttribute("aria-pressed",String(b === button)));
  }));
  $("focus-minutes").addEventListener("input",() => document.querySelectorAll("[data-focus-minutes]").forEach(b => b.setAttribute("aria-pressed",String(b.dataset.focusMinutes === $("focus-minutes").value))));
  async function savePreference(dimension,value) {
    await mutate("/api/focus/preferences",{request_id:crypto.randomUUID(),conversation_id:state.active,dimension,value},"PUT");
    if (dimension === "focus_sound") await playRain();
  }
  document.querySelectorAll("[data-focus-ambient]").forEach(select => select.addEventListener("change",async () => {
    if (select.value === "rain" && !focusUI.closed(data?.session)) { try { await focusAudio.play(); } catch { /* Explicit play remains available. */ } }
    await savePreference("focus_sound",select.value);
  }));
  $("focus-play-rain").addEventListener("click",playRain);
  $("focus-notice-on").addEventListener("change",() => savePreference("focus_notice",$("focus-notice-on").checked ? "once" : "off"));
  $("focus-allow-notice").addEventListener("click",async () => {
    if (!("Notification" in window)) return;
    try { await Notification.requestPermission(); } catch { error("浏览器暂时无法申请通知权限，到时仍可在页面内查看。"); }
    paint();
  });
  $("focus-popout").addEventListener("click",() => {
    miniWindow = window.open("/static/focus-mini.html","xinyu-focus-mini","popup,width=340,height=220,resizable=yes");
    if (!miniWindow) error("小窗被浏览器拦截了，请允许弹出窗口；聊天里仍可查看计时。");
    else { miniWindow.focus(); $("focus-background-hint").textContent = "已打开独立小窗，可拖到角落；此浏览器窗口不会强制置顶。"; }
  });
  $("focus-history-open").addEventListener("click",async () => {
    await refresh(); focusUI.history(data);
    if (!$("focus-history-dialog").open) $("focus-history-dialog").showModal();
  });
  $("focus-clear").addEventListener("click",async () => {
    if (!window.confirm("清除已结束的活动记录？手札中由你保存的进展仍可单独查看或遗忘。")) return;
    await mutate("/api/focus/history",null,"DELETE"); focusUI.history(data);
  });
  $("focus-progress").addEventListener("input",() => { progressRequest = null; });
  $("focus-progress-form").addEventListener("submit",async event => {
    event.preventDefault();
    const content = $("focus-progress").value.trim();
    if (!content || !data?.session) { $("focus-progress-result").textContent = "写下想留住的那一点进展就好。"; return; }
    const button = event.submitter; button.disabled = true;
    progressRequest ||= {request_id:crypto.randomUUID(),session_id:data.session.id,content};
    try {
      await api("/api/focus/progress",{method:"POST",body:JSON.stringify(progressRequest)});
      $("focus-progress-result").textContent = "已收进记忆手札，来源是你刚才写下的这句话。";
    } catch (failure) { $("focus-progress-result").textContent = failure.message; }
    finally { button.disabled = false; }
  });
  function card(container,message) {
    const initial = message.focus_proposal;
    if (!initial) return;
    if (!cards.has(message.id)) cards.set(message.id,{...initial});
    const values = cards.get(message.id), form = element("form","focus-card");
    form.setAttribute("aria-label","专注确认卡");
    const label = element("label","","想做的事（可不填）"), input = element("input");
    input.value = values.intention; input.maxLength = 160; input.placeholder = "留一点时间";
    input.addEventListener("input",() => { values.intention = input.value; }); label.append(input);
    const timeLabel = element("label","","时间 / 分钟"), duration = element("input");
    duration.type = "number"; duration.min = "1"; duration.max = "120"; duration.step = "1"; duration.required = true; duration.value = values.focus_minutes;
    duration.addEventListener("input",() => { values.focus_minutes = Number(duration.value); }); timeLabel.append(duration);
    const footer = element("footer"), submit = element("button","primary-button","开始");
    submit.type = "submit"; footer.append(element("span","","准备好再开始"),submit);
    form.append(label,timeLabel,footer);
    form.addEventListener("submit",async event => {
      event.preventDefault(); if (!form.reportValidity()) return;
      submit.disabled = true;
      try { if (await start({...values},"chat")) { submit.textContent = "已开始"; } }
      finally { submit.disabled = false; }
    });
    container.append(form);
  }
  document.addEventListener("visibilitychange",() => { if (!document.hidden) refresh(); });
  window.addEventListener("pageshow",refresh);
  setInterval(() => {
    const seconds = focusUI.time(data,offset);
    if (!state.config) return;
    const interval = data?.session && !focusUI.settled(data.session) ? 5000 : 20000;
    if (Date.now() - lastFetch >= interval || (data?.session?.deadline && seconds === 0 && Date.now() - lastFetch > 1000)) refresh();
  },1000);
  window.focusController = {refresh,card,openSetup,openRoom};
  paint();
})();
