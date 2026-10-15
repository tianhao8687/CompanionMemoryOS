"use strict";

const focusUI = (() => {
  const names = {focus:"专注中", focus_paused:"已暂停", focus_done:"时间到了", rest:"休息中", rest_paused:"休息已暂停", done:"休息结束", ended:"已结束"};
  const closed = session => !session || ["focus_done", "done", "ended"].includes(session.phase);
  const settled = session => !session || ["done", "ended"].includes(session.phase);
  const setText = (id, text) => { if ($(id).textContent !== text) $(id).textContent = text; };
  const format = seconds => String(Math.floor(seconds / 60)).padStart(2,"0") + ":" + String(seconds % 60).padStart(2,"0");
  function noticeStatus(preferences) {
    if (preferences.focus_notice === "off") return "到时提醒已关闭，回来仍可查看计时状态。";
    if (!("Notification" in window)) return "此浏览器不支持桌面通知，到时只在页面内提示。";
    if (Notification.permission === "denied") return "通知权限未开启，到时只在页面内提示。";
    if (Notification.permission === "granted") return "已允许桌面通知；网页仍需保持打开，系统挂起可能延迟提醒。";
    return "到时只在页面内提示；桌面通知需要你主动授权。";
  }
  function render(data, busy) {
    const session = data?.session, name = state.config?.settings.companion_name || "小禾";
    const phase = session?.phase;
    const preferences = data?.preferences || {focus_sound:"silent", focus_notice:"once"};
    window.nookController?.setFocus(phase === "focus");
    $("focus-clock").hidden = !session;
    $("focus-desk-entry").hidden = Boolean(session && !settled(session));
    const avatar = $("focus-avatar"), avatarId = state.config?.settings.companion_avatar;
    if (avatar.dataset.image !== String(avatarId)) {
      avatar.dataset.image = String(avatarId); avatar.replaceChildren();
      if (avatarId) { const image = element("img"); image.src = "/api/images/" + encodeURIComponent(avatarId); image.alt = ""; avatar.append(image); }
      else avatar.textContent = [...name][0];
    }
    setText("focus-note-author", name);
    const line = !session ? "坐一会儿也好。" : ({
      focus: "好，先 " + session.focus_minutes + " 分钟。",
      focus_paused: "好，暂停了。", focus_done: session.focus_minutes + " 分钟到了。",
      rest: "好，歇一会儿。", rest_paused: "休息计时暂停了。",
      done: "休息时间到了。", ended: "好，先到这里。",
    })[phase];
    setText("focus-note", line);
    setText("focus-stage", names[phase] || "准备开始");
    $("focus-active").hidden = !session || settled(session);
    $("focus-new").hidden = !session || !settled(session);
    setText("focus-current-task", session?.intention || "这一会儿");
    const action = phase?.endsWith("_paused") ? "resume" : phase === "focus_done" ? "rest" : "pause";
    $("focus-primary-action").dataset.action = action;
    setText("focus-primary-action", action === "resume" ? "继续" : action === "rest" ? "休息一下" : "暂停");
    $("focus-extend").hidden = phase !== "focus_done";
    $("focus-mini").hidden = !session || settled(session);
    setText("focus-mini-label", name + " · " + (names[phase] || ""));
    $("focus-mini-pause").hidden = phase === "focus_done";
    $("focus-mini-pause").dataset.action = action;
    setText("focus-mini-pause", action === "resume" ? "继续" : "暂停");
    document.querySelectorAll("[data-focus-ambient]").forEach(select => { if (document.activeElement !== select) select.value = preferences.focus_sound; });
    $("focus-notice-on").checked = preferences.focus_notice !== "off";
    document.querySelectorAll("[data-focus-notice-status]").forEach(node => { node.textContent = noticeStatus(preferences); });
    $("focus-allow-notice").hidden = !("Notification" in window) || Notification.permission === "granted" || Notification.permission === "denied";
    $("focus-play-rain").hidden = preferences.focus_sound !== "rain" || focusAudio.playing();
    $("focus-background-hint").textContent = closed(session) ? "想继续、聊一会儿，或先离开，都可以。" : "可以离开去做自己的事，计时会继续。";
    $("focus-progress-form").hidden = !session || !closed(session);
    document.querySelectorAll("#focus-active button, #focus-mini-pause, #focus-mini-finish, #focus-new, #focus-start, #focus-clear").forEach(button => { button.disabled = busy; });
    $("focus-start").disabled = busy || !state.active;
  }
  function time(data, offset) {
    const session = data?.session;
    const seconds = session?.deadline != null
      ? Math.max(0, Math.ceil(session.deadline - (Date.now() + offset) / 1000))
      : Math.max(0, Math.ceil(session?.remaining_seconds || 0));
    setText("focus-time", format(seconds));
    setText("focus-mini-time", session?.phase === "focus_done" ? "00:00" : format(seconds));
    document.title = closed(session) ? "心隅 · 留一盏灯，听你说" : format(seconds) + " · 陪我专注 · 心隅";
    return seconds;
  }
  function history(data) {
    const list = $("focus-history-list");
    const key = JSON.stringify(data?.history?.map(s => [s.id,s.revision]));
    if (list.dataset.key === key) return;
    list.dataset.key = key;
    list.replaceChildren();
    const timezone = state.config?.settings.calendar_timezone || "Asia/Shanghai";
    const date = seconds => new Intl.DateTimeFormat("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",timeZone:timezone}).format(new Date(seconds * 1000));
    const eventNames = {start:"开始", pause:"暂停", resume:"继续", timer_elapsed:"到时", rest:"开始休息", extend:"加五分钟", finish:"结束"};
    for (const session of data?.history || []) {
      const item = element("article","focus-history-item");
      item.append(element("p","",session.intention || "留了一段时间"),
        element("small","",date(session.started_at) + " · " + names[session.phase] + " · 计时 " + Math.floor(session.elapsed_seconds / 60) + " 分 " + Math.floor(session.elapsed_seconds % 60) + " 秒"));
      if (session.events?.length) {
        const details = element("details"), events = element("ul");
        details.append(element("summary","","查看时间记录"));
        for (const event of session.events) events.append(element("li","",date(event.at) + " · " + (eventNames[event.action] || event.action)));
        details.append(events); item.append(details);
      }
      list.append(item);
    }
    if (!list.children.length) list.append(element("p","focus-history-caption","还没有活动记录。"));
  }
  return {render, time, history, closed, settled, format, setText};
})();
