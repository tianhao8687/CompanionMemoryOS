"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let session, offset = 0, busy = false, last = 0, settings, pendingNotice;
  const names = {focus:"专注中",focus_paused:"已暂停",focus_done:"时间到了",rest:"休息中",rest_paused:"已暂停",done:"休息结束",ended:"已结束"};
  async function api(path, body) {
    const result = await fetch(path,{credentials:"same-origin",...(body ? {method:"POST",headers:{"Content-Type":"application/json","X-Companion-Client":"local-web"},body:JSON.stringify(body)} : {})});
    const data = await result.json();
    if (!result.ok) throw new Error(data.error?.message || data.detail?.message || "同步失败，请稍后重试。");
    return data;
  }
  function time() {
    const seconds = session?.deadline != null ? Math.max(0,Math.ceil(session.deadline - (Date.now()+offset)/1000)) : Math.ceil(session?.remaining_seconds || 0);
    $("time").textContent = String(Math.floor(seconds/60)).padStart(2,"0") + ":" + String(seconds%60).padStart(2,"0");
  }
  async function refresh() {
    if (busy) return;
    last = Date.now();
    try {
      settings = (await api("/api/bootstrap")).settings;
      const data = await api("/api/focus");
      session = data.session; offset = data.server_now * 1000 - Date.now();
      $("name").textContent = settings.companion_name;
      const avatar = $("avatar"), id = settings.companion_avatar;
      if (avatar.dataset.image !== String(id)) {
        avatar.dataset.image = String(id); avatar.replaceChildren();
        if (id) { const image = document.createElement("img"); image.src = "/api/images/" + encodeURIComponent(id); image.alt = ""; avatar.append(image); }
        else avatar.textContent = [...settings.companion_name][0];
      }
      $("phase").textContent = names[session?.phase] || "没有正在进行的计时";
      $("pause").textContent = session?.phase?.endsWith("_paused") ? "继续" : "暂停";
      $("pause").disabled = !session || ["focus_done","done","ended"].includes(session.phase);
      $("finish").disabled = !session || ["done","ended"].includes(session.phase);
      $("error").textContent = ""; time();
      const key = session?.id + ":" + session?.revision;
      if (session && ["focus_done","done"].includes(session.phase) && data.server_now - session.ended_at <= 120 && data.preferences?.focus_notice !== "off" && pendingNotice !== key) {
        pendingNotice = key;
        if (("Notification" in window) && Notification.permission === "granted") {
          const result = await api("/api/focus/notice",{session_id:session.id,revision:session.revision});
          if (result.claimed) new Notification(settings.companion_name,{body:session.phase === "focus_done" ? session.focus_minutes + " 分钟到了。" : "休息时间到了。",tag:"xinyu-focus",silent:true});
        }
      }
    } catch (error) { $("error").textContent = error.message; }
  }
  async function act(action) {
    if (!session || busy) return;
    busy = true; $("pause").disabled = $("finish").disabled = true;
    try { await api("/api/focus/action",{session_id:session.id,revision:session.revision,action}); }
    catch (error) { $("error").textContent = error.message; }
    finally { busy = false; await refresh(); }
  }
  $("pause").onclick = () => act(session?.phase?.endsWith("_paused") ? "resume" : "pause");
  $("finish").onclick = () => act("finish");
  document.addEventListener("visibilitychange",refresh);
  setInterval(() => { time(); if (Date.now()-last>3000) refresh(); },1000);
  refresh();
})();
