"use strict";

(() => {
  const dialog = $("nook-dialog"), canvas = $("nook-room");
  const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  let room = null, selected = null, timer = null, generation = 0, at = null;
  let layout = null, background = null, scenePromise = null, view = "all";
  let camera = [0, 0, 1000], frame = null;
  const spriteCache = new WeakMap();

  function sprite(target, art) {
    target.width = art.rows.length; target.height = art.rows.length;
    const ctx = target.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    art.rows.forEach((row, y) => [...row].forEach((pixel, x) => {
      if (pixel !== ".") {
        ctx.fillStyle = art.palette[parseInt(pixel, 16)]; ctx.fillRect(x, y, 1, 1);
      }
    }));
  }
  function spriteData(art) {
    if (spriteCache.has(art)) return spriteCache.get(art);
    const image = document.createElement("canvas"); sprite(image, art);
    let left = art.rows.length, right = 0, bottom = 0;
    art.rows.forEach((row, y) => [...row].forEach((p, x) => {
      if (p !== ".") { left = Math.min(left, x); right = Math.max(right, x + 1); bottom = y + 1; }
    }));
    const value = {image, middle: (left + right) / 2, bottom};
    spriteCache.set(art, value); return value;
  }
  // The last painted row rests on the surface, regardless of transparent padding.
  function objectRect(item) {
    const zone = layout.zones[item.zone], anchor = zone.slots[item.slot];
    const pixels = spriteData(item.art), scale = zone.size / item.art.rows.length;
    return {x: anchor[0] - pixels.middle * scale, y: anchor[1] - pixels.bottom * scale, size: zone.size, anchor};
  }
  function displayedItems() {
    return (room?.items || []).filter(o => o.displayed).sort((a, b) => {
      const ay = layout.zones[a.zone].slots[a.slot][1], by = layout.zones[b.zone].slots[b.slot][1];
      return ay - by || a.id.localeCompare(b.id);
    });
  }
  function scene() {
    const ctx = canvas.getContext("2d"); ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#f5eddc"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!layout || !background) return;
    ctx.save(); ctx.scale(canvas.width / camera[2], canvas.height / camera[2]);
    ctx.translate(-camera[0], -camera[1]);
    ctx.drawImage(background, 0, 0, layout.side, layout.side);
    for (const item of displayedItems()) {
      const box = objectRect(item);
      if (item.zone !== "wall") {
        ctx.fillStyle = "#58483f30";
        ctx.fillRect(box.anchor[0] - box.size * .22, box.anchor[1] - 2, box.size * .44, 4);
      }
      ctx.drawImage(spriteData(item.art).image, box.x, box.y, box.size, box.size);
      if (item.id === selected) {
        ctx.strokeStyle = "#78907c"; ctx.lineWidth = 2;
        ctx.strokeRect(box.x - 3, box.y - 3, box.size + 6, box.size + 6);
      }
    }
    ctx.restore();
  }
  function focusZone(zone, animate = true) {
    if (!layout) return;
    view = zone; canvas.dataset.view = zone;
    $("nook-view-label").textContent = zone === "all" ? "整个小窝" : `靠近看看 · ${layout.zones[zone].label}`;
    $("nook-overview").hidden = zone === "all";
    for (const button of $("nook-zones").children) button.setAttribute("aria-pressed", String(button.dataset.zone === zone));
    const next = zone === "all" ? [0, 0, layout.side] : layout.zones[zone].view;
    cancelAnimationFrame(frame);
    if (!animate || reducedMotion() || !dialog.open) { camera = [...next]; scene(); return; }
    const start = [...camera], started = performance.now();
    function step(now) {
      const progress = Math.min(1, (now - started) / 240), ease = 1 - (1 - progress) ** 3;
      camera = next.map((v, i) => start[i] + (v - start[i]) * ease); scene();
      if (progress < 1 && dialog.open) frame = requestAnimationFrame(step);
    }
    frame = requestAnimationFrame(step);
  }
  async function ensureScene() {
    if (layout && background) return;
    if (scenePromise) return scenePromise;
    $("nook-scene-message").hidden = false;
    $("nook-scene-message").textContent = "正在打开窗边的小窝…";
    scenePromise = (async () => {
      const response = await fetch("/static/nook/room.json");
      if (!response.ok) throw new Error("房间图片暂时无法读取，请刷新小窝。");
      const definition = await response.json(), image = new Image();
      const ready = new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("房间图片暂时无法读取，请刷新小窝。"));
      });
      image.src = "/static/nook/" + definition.image; await ready;
      layout = definition; background = image;
      $("nook-zones").replaceChildren();
      for (const [key, value] of Object.entries(layout.zones)) {
        const button = element("button", "", value.label);
        button.type = "button"; button.dataset.zone = key;
        button.setAttribute("aria-label", `靠近${value.label}`);
        button.addEventListener("click", () => focusZone(key)); $("nook-zones").append(button);
      }
      $("nook-scene-message").hidden = true; canvas.dataset.ready = "true";
      focusZone(view, false);
    })().catch(error => {
      $("nook-scene-message").textContent = error.message; throw error;
    }).finally(() => { scenePromise = null; });
    return scenePromise;
  }
  function choose(id) {
    selected = id;
    const item = room.items.find(o => o.id === id);
    if (item?.displayed) focusZone(item.zone);
    scene(); details(); chips();
    $("nook-detail").scrollIntoView({behavior: reducedMotion() ? "instant" : "smooth", block: "nearest"});
  }
  function chips() {
    $("nook-items").replaceChildren(); $("nook-stored").replaceChildren();
    let stored = 0;
    for (const item of room.items) {
      const button = element("button", "", (item.pinned ? "♡ " : "") + item.title); button.type = "button";
      button.setAttribute("aria-pressed", String(item.id === selected));
      const art = element("canvas", "nook-sprite"); art.setAttribute("aria-hidden", "true"); sprite(art, item.art); button.prepend(art);
      button.addEventListener("click", () => choose(item.id));
      $(item.displayed ? "nook-items" : "nook-stored").append(button);
      if (!item.displayed) stored++;
    }
    $("nook-stored-count").textContent = String(stored);
  }
  function details() {
    const area = $("nook-detail"); area.replaceChildren();
    const item = room.items.find(o => o.id === selected); area.hidden = !item;
    if (!item) return;
    const closeup = element("canvas", "nook-closeup");
    closeup.setAttribute("role", "img"); closeup.setAttribute("aria-label", `${item.title}，像素画放大近看`); sprite(closeup, item.art);
    closeup.style.width = closeup.style.height = `${item.art.rows.length * 4}px`;
    area.append(closeup, element("h3", "", item.title), element("small", "", item.reality_layer === "roleplay" ? "故事里的纪念品 · AI 原创像素画" : "回忆的纪念品 · AI 原创像素画"), element("p", "", item.meaning));
    const evidence = element("details"), summary = element("summary", "", "看看创作来源"); evidence.append(summary);
    for (const source of item.evidence) {
      evidence.append(element("small", "", new Date(source.at).toLocaleDateString("zh-CN")), element("blockquote", "", source.content));
      if (source.conversation_id) evidence.append(localButton("回到这段聊天", async () => {
        try { await selectConversation(source.conversation_id); dialog.close(); }
        catch (error) { showError(error); }
      }));
    }
    area.append(evidence);
    const actions = element("div", "nook-actions");
    if (!at) {
      actions.append(localButton("聊聊这件", () => {
        if (state.busy || state.loading) return;
        const input = $("message-input"), invitation = `我们聊聊小窝里的「${item.title}」吧。`;
        const draft = [input.value.trim(), invitation].filter(Boolean).join("\n");
        if (draft.length > 6000) { showError(new Error("草稿太长了，请先整理后再聊这件物品。")); return; }
        input.value = draft;
        input.dispatchEvent(new Event("input", {bubbles: true}));
        dialog.close(); resizeComposer(); input.focus();
      }));
      actions.append(localButton(item.pinned ? "取消珍藏" : "珍藏这一版", async () => {
        try {
          await api(`/api/nook/objects/${encodeURIComponent(item.id)}`, {method: "PUT", body: JSON.stringify({pinned: !item.pinned})});
          await load();
        } catch (error) { showError(error); }
      }));
      if (item.pinned) area.append(element("p", "", "已珍藏：TA 会保留这一版和它的位置。"));
    }
    actions.append(localButton("回到小窝", () => {
      selected = null; details(); chips(); focusZone("all");
      canvas.scrollIntoView({behavior: reducedMotion() ? "instant" : "smooth", block: "start"});
    }));
    if (!at) actions.append(localButton(item.displayed ? "收进收纳盒" : "摆回小窝", async () => {
      await api(`/api/nook/objects/${encodeURIComponent(item.id)}`, {method: "PUT", body: JSON.stringify({displayed: !item.displayed})}); await load();
    }));
    area.append(actions);
  }
  async function load() {
    const current = ++generation;
    const value = await api("/api/nook" + (at ? "?at=" + encodeURIComponent(at) : ""));
    if (current !== generation || !dialog.open) return;
    room = value; if (!room.items.some(o => o.id === selected)) selected = null;
    $("nook-enabled").checked = room.enabled; $("nook-limit").value = String(room.daily_limit);
    if (!$("nook-limit").value) { const option = element("option", "", String(room.daily_limit)); $("nook-limit").append(option); $("nook-limit").value = String(room.daily_limit); }
    $("nook-status").textContent = room.message; $("nook-create").disabled = room.busy || !room.enabled || !!at;
    $("nook-empty").hidden = room.items.some(o => o.displayed);
    const slider = $("nook-time"); slider.max = String(room.timeline.length); slider.disabled = !room.timeline.length;
    slider.value = String(at ? Math.max(0, room.timeline.indexOf(at)) : room.timeline.length);
    $("nook-date").textContent = at ? new Date(at).toLocaleString("zh-CN") : "现在";
    scene(); chips(); details(); clearTimeout(timer);
    if (room.busy) timer = setTimeout(() => load().catch(showError), 1600);
  }
  function showError(error) { $("nook-status").textContent = error.message; }
  function openRoom() {
    dialog.showModal(); at = null; selected = null; view = "all"; camera = [0, 0, 1000];
    focusZone("all", false); scene(); ensureScene().catch(showError); load().catch(showError);
  }
  $("open-nook").addEventListener("click", openRoom);
  dialog.addEventListener("close", () => { clearTimeout(timer); cancelAnimationFrame(frame); generation++; });
  $("nook-refresh").addEventListener("click", () => { ensureScene().catch(showError); load().catch(showError); });
  $("nook-overview").addEventListener("click", () => focusZone("all"));
  $("nook-time").addEventListener("change", () => { at = room.timeline[Number($("nook-time").value)] || null; load().catch(showError); });
  async function saveSettings() {
    try {
      await api("/api/nook/settings", {method: "PUT", body: JSON.stringify({enabled: $("nook-enabled").checked, daily_limit: Number($("nook-limit").value)})});
      state.config = await api("/api/bootstrap"); await load();
    } catch (e) { showError(e); }
  }
  $("nook-enabled").addEventListener("change", saveSettings); $("nook-limit").addEventListener("change", saveSettings);
  $("nook-create").addEventListener("click", async () => {
    $("nook-create").disabled = true;
    try {
      const result = await api("/api/nook/create", {method: "POST", body: JSON.stringify({conversation_id: state.active})});
      await load(); $("nook-status").textContent = result.message;
    } catch (e) { showError(e); $("nook-create").disabled = false; }
  });
  function insidePolygon(x, y, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, yi] = points[i], [xj, yj] = points[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  canvas.addEventListener("click", event => {
    if (!layout || !background) return;
    const bounds = canvas.getBoundingClientRect();
    const x = camera[0] + (event.clientX - bounds.left) * camera[2] / bounds.width;
    const y = camera[1] + (event.clientY - bounds.top) * camera[2] / bounds.height;
    for (const item of displayedItems().reverse()) {
      const box = objectRect(item), side = item.art.rows.length;
      const px = Math.floor((x - box.x) * side / box.size), py = Math.floor((y - box.y) * side / box.size);
      if (px >= 0 && px < side && py >= 0 && py < side && item.art.rows[py][px] !== ".") { choose(item.id); return; }
    }
    for (const [key, zone] of Object.entries(layout.zones)) {
      if (insidePolygon(x, y, zone.polygon)) { focusZone(key); return; }
    }
  });
})();
