// The office: a second view of Home where each agent can be seen at work (office.py, officeart.py, ui/officeapi.py).
// Every picture is Retro Diffusion's pixel art from office/manifest.json; this file only places the pictures and
// moves them (frames stepped from the sheets, positions eased between the manifest's fixed spots). It draws no shape
// of its own. The scene rides the Hall's own refresh (onHall): no timer of its own runs while the view isn't shown.
import { h, fill, get, onHall, seatByPath, projectHref, has } from "./core.js";
import { t } from "./words.js";

const VIEW_KEY = "rt-home-view";       // "ring" | "office", remembered on this computer
const MOTION_KEY = "rt-office-motion"; // "off" when the owner turned Play animations off
const WORK_SPOTS = new Set(["desk", "terminal", "shelf", "whiteboard"]);
const WALK_SPEED = 48;                 // room pixels a second
const STEP_MS = { walk: 140, work: 220 };
const DIRS = { down: 0, left: 1, right: 2, up: 3 };

let ART = null;                        // the pictures, loaded once: {doc, img: {id: Image}}

officeStyles();

function store(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { /* storage unavailable */ }
  return null;
}

/** "ring" or "office": what Home showed last time (the Ring until the office has its pictures). */
export function homeView() { return store(VIEW_KEY) === "office" ? "office" : "ring"; }
export function setHomeView(v) { store(VIEW_KEY, v === "office" ? "office" : "ring"); }

/** Whether this copy of the app has the office and its pictures. */
export async function officeAvailable() {
  try { return (await has("/api/office")) && !!(await loadArt()); } catch { return false; }
}

/** The "Ring | Office" switch for Home, or null when there's no office art yet (then the Ring stays). */
export async function officeSwitch(onPick) {
  if (!(await officeAvailable())) return null;
  const now = homeView();
  const pick = (v) => {
    setHomeView(v);
    sw.querySelectorAll(".of-pick").forEach((b) => { const on = b.dataset.v === v; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    if (onPick) onPick(v);
  };
  const btn = (v, label, tip) => h("button", { type: "button", class: "of-pick" + (now === v ? " on" : ""), "data-v": v, "aria-pressed": String(now === v), title: tip, onclick: () => pick(v) }, label);
  const sw = h("div", { class: "of-switch", role: "group", "aria-label": "How Home shows your projects" },
    btn("ring", "Ring", "Your projects round the ring"), btn("office", "Office", "Your agents at work in a little office"));
  return sw;
}

function loadImage(url) {
  return new Promise((ok) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => ok(null); im.src = url; });
}

async function loadArt() {
  if (ART) return ART.doc.art ? ART : null;
  const doc = await get("/api/office/art");
  const img = {};
  if (doc.art) {
    await Promise.all(Object.entries(doc.pieces || {}).map(async ([id, p]) => { img[id] = await loadImage(p.url); }));
  }
  ART = { doc, img };
  return doc.art ? ART : null;
}

function motionOn() {
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  return !reduced && store(MOTION_KEY) !== "off";
}

/** Draw the office into node; it follows the Hall's refresh until node leaves the page. */
export async function officeView(node) {
  const head = h("div", { class: "of-head" });
  const rooms = h("div", { class: "of-rooms" });
  fill(node, h("section", { class: "of", "aria-label": "The office" }, head, rooms));
  const art = await loadArt().catch(() => null);
  if (!art) {
    fill(rooms, h("p", { class: "muted" }, "The office has no pictures yet, so Home shows the Ring."));
    return node;
  }
  const views = new Map();               // room id -> {wrap, canvas, layer, buttons, actors}
  const where = new Map();               // actor id -> {x, y, fx, fy, tx, ty, start, dur, dir}
  let scene = null, frame = 0, motion = motionOn();

  const toggle = h("input", { type: "checkbox", checked: motion, onchange: (e) => { store(MOTION_KEY, e.target.checked ? "on" : "off"); motion = motionOn(); tick(); } });
  const head_ = () => fill(head, h("span", { class: "of-words" }, scene ? scene.words : ""),
    h("label", { class: "of-motion", title: t("Move the figures. Off, or when your computer asks for less motion, the office stays still.") }, toggle, " ", "Play animations"));

  async function refresh() {
    try { scene = await get("/api/office"); } catch { return; }
    head_();
    layout();
    tick();
  }

  function layout() {
    const want = scene.rooms || [];
    for (const [id, v] of views) if (!want.find((r) => r.id === id)) { v.wrap.remove(); views.delete(id); }
    for (const r of want) {
      let v = views.get(r.id);
      if (!v) {
        const canvas = h("canvas", { class: "of-canvas", role: "img" });
        const layer = h("div", { class: "of-layer" });
        const title = h("h3", { class: "of-title" });
        const line = h("span", { class: "muted small" });
        const wrap = h("figure", { class: "of-room", dir: "ltr" }, h("figcaption", {}, title, " ", line), h("div", { class: "of-stage" }, canvas, layer));
        v = { wrap, canvas, layer, title, line, buttons: new Map() };
        views.set(r.id, v);
      }
      rooms.append(v.wrap);  // keeps the order the scene gives
      fill(v.title, h("span", { raw: true }, r.name));
      fill(v.line, r.line || r.word || "");
      v.canvas.setAttribute("aria-label", t("{name}: {line}", { name: r.name, line: r.line || r.word || "" }));
      v.room = r;
      v.actors = (scene.actors || []).filter((a) => a.project === r.id);
      placeActors(v);
    }
    rooms.querySelector(".of-more")?.remove();
    if (scene.more) rooms.append(h("a", { class: "of-more", href: "#/projects", title: t("Every project, in a list") }, t("and {n} more", { n: scene.more })));
    if (!want.length) rooms.append(h("p", { class: "of-empty muted" }, "Nobody is working right now. When a project builds, its agents show up here."));
    else rooms.querySelector(".of-empty")?.remove();
  }

  function spotOf(at, taken) {
    const spots = (art.doc.spots || {})[at] || (art.doc.spots || {}).middle || [[0, 0]];
    const i = taken[at] = (taken[at] || 0) + 1;
    return spots[(i - 1) % spots.length];
  }

  function placeActors(v) {
    const taken = {};
    const now = performance.now();
    for (const [id, b] of v.buttons) if (!v.actors.find((a) => a.id === id)) { b.remove(); v.buttons.delete(id); }
    for (const a of v.actors) {
      const [tx, ty] = spotOf(a.at, taken);
      let p = where.get(a.id);
      if (!p) { p = { x: tx, y: ty, tx, ty, fx: tx, fy: ty, start: now, dur: 0, dir: "down" }; where.set(a.id, p); }
      if (p.tx !== tx || p.ty !== ty) {
        const dx = tx - p.x, dy = ty - p.y;
        p.fx = p.x; p.fy = p.y; p.tx = tx; p.ty = ty; p.start = now;
        p.dur = Math.min(3000, Math.max(400, (Math.hypot(dx, dy) / WALK_SPEED) * 1000));
        p.dir = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? "left" : "right") : (dy < 0 ? "up" : "down");
      }
      let b = v.buttons.get(a.id);
      if (!b) {
        b = h("button", { type: "button", class: "of-actor", onclick: () => openActor(a.id) });
        v.layer.append(b);
        v.buttons.set(a.id, b);
      }
      const tip = t("{name} ({job}): {doing}", { name: a.name, job: a.job, doing: a.doing });
      b.title = tip;
      b.setAttribute("aria-label", tip);
      b.classList.toggle("flare", a.tone === "flare");
    }
  }

  function openActor(id) {
    const a = (scene.actors || []).find((x) => x.id === id);
    if (!a) return;
    const seat = seatByPath(a.path);
    if (a.task && seat) import("./focus.js").then((m) => m.openFocus(seat, a.task)).catch(() => {});
    else location.hash = projectHref(seat ? seat.id : a.project);
  }

  function scaleFor(v) {
    const room = art.doc.room;
    const dpr = window.devicePixelRatio || 1;
    const css = Math.max(room.width, v.wrap.clientWidth || room.width);
    return { k: Math.max(1, Math.floor((css * dpr) / room.width)), dpr };  // whole device pixels: the pixels stay crisp
  }

  function piece(id) { return art.img[id] || null; }
  function put(ctx, id, x, y, w, hh) { const im = piece(id); if (im) ctx.drawImage(im, x, y, w || im.width, hh || im.height); }
  function cell(ctx, id, col, row, x, y, w, hh) {   // one frame of a sheet
    const im = piece(id), spec = (art.doc.pieces[id] || {}).sheet || { cols: 1, rows: 1 };
    if (!im) return false;
    const fw = im.width / spec.cols, fh = im.height / spec.rows;
    ctx.drawImage(im, (col % spec.cols) * fw, (row % spec.rows) * fh, fw, fh, x, y, w, hh);
    return true;
  }

  function paint(v, ms) {
    const room = art.doc.room, actor = art.doc.actor || { draw: [48, 48], feet: [24, 44], bubble_above: 8 };
    const { k, dpr } = scaleFor(v);
    const c = v.canvas;
    if (c.width !== room.width * k) { c.width = room.width * k; c.height = room.height * k; }
    c.style.width = `${(room.width * k) / dpr}px`;
    c.style.height = `${(room.height * k) / dpr}px`;
    const ctx = c.getContext("2d");
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, room.width, room.height);
    const wall = piece(room.wall), floor = piece(room.floor);
    for (let x = 0; wall && x < room.width; x += 64) put(ctx, room.wall, x, 0, 64, room.wall_height);
    for (const x of room.windows_at || []) put(ctx, room.window, x, 0, 64, room.wall_height);
    for (let y = room.wall_height; floor && y < room.height; y += 64) for (let x = 0; x < room.width; x += 64) put(ctx, room.floor, x, y, 64, 64);
    for (const p of art.doc.props || []) { const d = (art.doc.pieces[p.piece] || {}).draw; put(ctx, p.piece, p.x, p.y, d && d[0], d && d[1]); }
    const [aw, ah] = actor.draw, [fx, fy] = actor.feet;
    const list = (v.actors || []).map((a) => ({ a, p: where.get(a.id) })).filter((x) => x.p);
    for (const { p } of list) {
      const f = p.dur && motion ? Math.min(1, (ms - p.start) / p.dur) : 1;
      const e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      p.x = p.fx + (p.tx - p.fx) * e; p.y = p.fy + (p.ty - p.fy) * e; p.moving = f < 1;
      if (!p.moving) { p.dur = 0; p.fx = p.tx; p.fy = p.ty; }
    }
    list.sort((m, n) => m.p.y - n.p.y);
    for (const { a, p } of list) {
      const fig = (art.doc.agents || {})[a.agent] || (art.doc.agents || {})["helper-a"] || {};
      const x = Math.round(p.x - fx), y = Math.round(p.y - fy);
      const step = (kind) => (motion ? Math.floor(ms / STEP_MS[kind]) : 0);
      if (p.moving) cell(ctx, fig.walk, step("walk"), DIRS[p.dir] || 0, x, y, aw, ah);
      else if (WORK_SPOTS.has(a.at) && piece(fig.work)) cell(ctx, fig.work, step("work"), 0, x, y, aw, ah);
      else cell(ctx, fig.walk, 0, DIRS.down, x, y, aw, ah);
      const bub = a.bubble && (art.doc.bubbles || {})[a.bubble];
      if (bub) { const d = (art.doc.pieces[bub] || {}).draw || [20, 20]; put(ctx, bub, x + aw / 2 - d[0] / 2, y - d[1] - (actor.bubble_above || 0) + 12, d[0], d[1]); }
      const b = v.buttons.get(a.id);
      if (b) {  // the button over the figure, in the room's own (left to right) coordinates
        b.style.insetInlineStart = `${(x / room.width) * 100}%`;
        b.style.insetBlockStart = `${(y / room.height) * 100}%`;
        b.style.inlineSize = `${(aw / room.width) * 100}%`;
        b.style.blockSize = `${(ah / room.height) * 100}%`;
      }
    }
    return list.some((x) => x.p.moving);
  }

  function tick() {
    cancelAnimationFrame(frame);
    const ms = performance.now();
    for (const v of views.values()) paint(v, ms);
    if (motion && node.isConnected && views.size) frame = requestAnimationFrame(tick);  // only while shown
  }

  onHall(node, () => refresh());  // the Hall's own refresh, while node is on the page
  await refresh();
  return node;
}

function officeStyles() {
  if (typeof document === "undefined" || document.getElementById("of-style")) return;
  document.head.append(h("style", { id: "of-style" }, `
.of { display: flex; flex-direction: column; gap: 10px; }
.of-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.of-words { flex: 1; color: var(--color-text); }
.of-motion { color: var(--color-muted); font-size: 13px; cursor: pointer; }
.of-rooms { display: grid; grid-template-columns: repeat(auto-fit, minmax(384px, 1fr)); gap: 12px; }
.of-room { margin: 0; padding: 8px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); text-align: start; }
.of-room figcaption { margin-block-end: 6px; }
.of-title { display: inline; font-size: 14px; margin: 0; color: var(--color-text); }
.of-stage { position: relative; inline-size: max-content; max-inline-size: 100%; }
.of-canvas { display: block; image-rendering: pixelated; image-rendering: crisp-edges; }
.of-layer { position: absolute; inset: 0; }
.of-actor { position: absolute; padding: 0; border: 1px solid transparent; border-radius: var(--radius-small); background: transparent; cursor: pointer; }
.of-actor:hover, .of-actor:focus-visible { border-color: var(--color-accent); }
.of-actor.flare { border-color: var(--color-flare); }
.of-more { align-self: center; }
.of-switch { display: inline-flex; border: 1px solid var(--color-line-strong); border-radius: var(--radius-small); overflow: hidden; }
.of-pick { border: 0; border-radius: 0; padding: 4px 12px; background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.of-pick.on { background: var(--color-accent); color: var(--color-accent-text); }
`));
}
