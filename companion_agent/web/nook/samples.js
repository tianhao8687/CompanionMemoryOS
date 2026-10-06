"use strict";

// Visual samples are local art assets. They never call the memory or model APIs.
(() => {
  const canvas = document.getElementById("sample-room");
  const ctx = canvas.getContext("2d");
  const status = document.getElementById("sample-status");
  const cards = [...document.querySelectorAll(".sample-card")];
  const buttons = [...document.querySelectorAll("#sample-views button")];
  const items = [
    {id: "daisy", title: "向阳的小雏菊", zone: "window", slot: 1, file: "daisy-planter-v1.png"},
    {id: "moon", title: "晚安月亮灯", zone: "shelf", slot: 1, file: "moon-lamp-v1.png"},
    {id: "coffee", title: "咖啡小火箭", zone: "desk", slot: 1, file: "coffee-rocket-v1.png"},
  ];
  let layout, room, camera = [0, 0, 1000], selected = null, scale = 1.35, frame;

  async function loadImage(src) {
    const image = new Image();
    image.src = src;
    await image.decode();
    return image;
  }

  function paintedBounds(image) {
    const work = document.createElement("canvas");
    work.width = image.naturalWidth; work.height = image.naturalHeight;
    const workCtx = work.getContext("2d", {willReadFrequently: true});
    workCtx.drawImage(image, 0, 0);
    const pixels = workCtx.getImageData(0, 0, work.width, work.height).data;
    let left = work.width, top = work.height, right = 0, bottom = 0;
    for (let y = 0; y < work.height; y++) for (let x = 0; x < work.width; x++) {
      if (pixels[(y * work.width + x) * 4 + 3] > 20) {
        left = Math.min(left, x); top = Math.min(top, y);
        right = Math.max(right, x + 1); bottom = Math.max(bottom, y + 1);
      }
    }
    if (!right || !bottom) throw new Error("有一件样品没有显示出来，请刷新重试。");
    return {left, top, width: right - left, height: bottom - top};
  }

  function rect(item) {
    const zone = layout.zones[item.zone], [x, y] = zone.slots[item.slot];
    const size = zone.size * scale;
    const ratio = size / Math.max(item.bounds.width, item.bounds.height);
    const width = item.bounds.width * ratio, height = item.bounds.height * ratio;
    return {x: x - width / 2, y: y - height, width, height, anchor: [x, y]};
  }

  function drawItem(target, item, box) {
    const b = item.bounds;
    target.drawImage(item.image, b.left, b.top, b.width, b.height, box.x, box.y, box.width, box.height);
  }

  function draw() {
    if (!room || !layout) return;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#f2ead9"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.save(); ctx.scale(canvas.width / camera[2], canvas.height / camera[2]);
    ctx.translate(-camera[0], -camera[1]);
    ctx.drawImage(room, 0, 0, layout.side, layout.side);
    for (const item of [...items].sort((a, b) => rect(a).anchor[1] - rect(b).anchor[1])) {
      const box = rect(item);
      ctx.fillStyle = "#58483f30";
      ctx.fillRect(box.anchor[0] - box.width * .3, box.anchor[1] - 1, box.width * .6, 3);
      drawItem(ctx, item, box);
    }
    ctx.restore();
  }

  function focus(view, item = null) {
    if (!layout || !room) return;
    selected = item?.id || null;
    cards.forEach(card => card.setAttribute("aria-pressed", String(card.dataset.item === selected)));
    buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
    document.getElementById("sample-caption").textContent = view === "all"
      ? "三件小物件，三个温暖的角落。"
      : `${layout.zones[view].label} · ${item?.title || items.find(value => value.zone === view).title}`;
    canvas.dataset.view = view;
    const next = view === "all" ? [0, 0, layout.side] : layout.zones[view].view;
    cancelAnimationFrame(frame);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      camera = [...next]; draw(); return;
    }
    const previous = [...camera], start = performance.now();
    function step(now) {
      const t = Math.min(1, (now - start) / 270), ease = 1 - (1 - t) ** 3;
      camera = next.map((value, i) => previous[i] + (value - previous[i]) * ease);
      draw();
      if (t < 1) frame = requestAnimationFrame(step);
    }
    frame = requestAnimationFrame(step);
  }

  cards.forEach(card => card.addEventListener("click", () => {
    const item = items.find(value => value.id === card.dataset.item);
    focus(item.zone, item);
  }));
  buttons.forEach(button => button.addEventListener("click", () => focus(button.dataset.view)));
  document.getElementById("sample-size").addEventListener("input", event => {
    scale = Number(event.target.value) / 100;
    document.getElementById("sample-size-value").textContent = `${event.target.value}%`;
    draw();
  });
  canvas.addEventListener("click", event => {
    if (!layout || !room) return;
    const bounds = canvas.getBoundingClientRect();
    const x = camera[0] + (event.clientX - bounds.left) / bounds.width * camera[2];
    const y = camera[1] + (event.clientY - bounds.top) / bounds.height * camera[2];
    // Pad small sprites for touch; buttons offer the same action with labels.
    const pad = 20 * camera[2] / bounds.width;
    const item = [...items].reverse().find(value => {
      const box = rect(value);
      return x >= box.x - pad && x <= box.x + box.width + pad
        && y >= box.y - pad && y <= box.y + box.height + pad;
    });
    if (item) focus(item.zone, item);
    else focus("all");
  });

  async function init() {
    const response = await fetch("room.json");
    if (!response.ok) throw new Error("小窝暂时没有打开，请刷新重试。");
    layout = await response.json();
    const [background] = await Promise.all([
      loadImage(layout.image),
      ...items.map(async item => {
        item.image = await loadImage(`samples/${item.file}`);
        item.bounds = paintedBounds(item.image);
        const thumb = cards.find(card => card.dataset.item === item.id).querySelector("canvas");
        const target = thumb.getContext("2d"); target.imageSmoothingEnabled = false;
        const ratio = 200 / Math.max(item.bounds.width, item.bounds.height);
        const width = item.bounds.width * ratio, height = item.bounds.height * ratio;
        drawItem(target, item, {x: (240 - width) / 2, y: (240 - height) / 2, width, height});
      }),
    ]);
    room = background; status.hidden = true;
    canvas.dataset.ready = "true"; canvas.dataset.view = "all";
    draw();
  }
  init().catch(error => { status.textContent = error.message; status.setAttribute("role", "alert"); });
})();
