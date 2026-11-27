// News for the owner on the desktop: pop-ups (the system's, else a toast in the app), the bell with the last 20,
// and the switches per kind for Settings → Notifications. The news itself comes from /api/notifications (notify.py),
// the same rules the phone uses. Loaded once by the shell; does nothing when this copy has no such route.
import { h, fill, get, post, toast, has, act, projectHref, ago } from "./core.js";
import { answerHere, answerHub } from "./asks.js";

const KEEP = 20;
const ICON = "icon.png";
const state = { items: [], next: null, settings: null, kinds: [], unread: 0, open: false, started: false };

function readSeen() { try { return Number(localStorage.getItem("rt-notify-seen") || 0); } catch { return 0; } }
function writeSeen(n) { try { localStorage.setItem("rt-notify-seen", String(n)); } catch { /* fine */ } }

// the project on screen right now, while the window is in front: its news makes no pop-up
function onScreen() {
  if (document.hidden || !document.hasFocus()) return null;
  const parts = (location.hash || "").slice(2).split("?")[0].split("/").map(decodeURIComponent);
  return parts[0] === "p" ? parts[1] : null;
}

function wanted(n) {
  const s = state.settings;
  return !!(s && s.popups && (s.kinds || {})[n.kind] !== false);
}

function openNews(n) {
  try { window.focus(); } catch { /* fine */ }
  location.hash = projectHref(n.project);
}

function popup(n) {
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      const pop = new Notification(n.title, { body: n.text, tag: n.key, icon: ICON });
      pop.onclick = () => { openNews(n); pop.close(); };
      return;
    } catch { /* fall back to the app's own */ }
  }
  toast(n.text ? `${n.title}: ${n.text}` : n.title);
}

function announce(fresh) {
  const here = onScreen();
  const show = fresh.filter((n) => wanted(n) && n.project !== here);
  const first = show.length > 4 ? show.slice(0, 3) : show;
  first.forEach(popup);
  if (show.length > first.length) {
    const more = show.length - first.length;
    popup({ key: "more", project: "", title: `${more} more things for you`, text: "Open the bell to see them." });
  }
}

// ---------- the bell ----------
const STYLE = `
.notify-bell { position: relative; }
.notify-bell .badge { position: absolute; top: -6px; right: -6px; }
.notify-panel { position: fixed; top: 64px; right: 16px; z-index: 60; width: min(380px, calc(100vw - 32px)); max-height: 70vh; overflow: auto;
  background: var(--color-surface); border: 1px solid var(--color-line); border-radius: 14px; box-shadow: var(--shadow); padding: 10px 12px; }
.notify-panel h2 { font-size: 16px; margin: 4px 4px 8px; }
.notify-item { padding: 8px 4px; border-top: 1px solid var(--color-line); }
.notify-item:first-of-type { border-top: 0; }
.notify-item b { display: block; }
.notify-item p { margin: 2px 0 6px; }
.notify-item .row { gap: 6px; flex-wrap: wrap; }
.notify-kinds label { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; }
`;

function bellIcon() {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", "18"); svg.setAttribute("height", "18"); svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", "M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zm-2 15a2 2 0 0 0 4 0");
  path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor"); path.setAttribute("stroke-width", "2"); path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

function bellButton() {
  const badge = h("span", { class: "badge", hidden: true });
  const btn = h("button", { class: "notify-bell small", type: "button", title: "Your latest news: finished, needs you, stopped, money and paused",
    "aria-label": "Your latest news", onclick: () => toggle() }, bellIcon(), badge);
  btn.badge = badge;
  return btn;
}

function drawBadge() {
  const b = state.bell && state.bell.badge;
  if (!b) return;
  b.hidden = !state.unread;
  b.textContent = state.unread > 9 ? "9+" : String(state.unread);
}

function answer(n, opt) {
  const reply = { chosen: [opt.id], other: "", confirmed: false };
  if (n.via === "hub" && n.hub_agent) return answerHub({ hub_agent: n.hub_agent, project: n.project }, n.ask, reply);
  return answerHere({ ...n.ask, path: n.ask.path || n.path }, reply);
}

function item(n) {
  const btns = (n.buttons || []).length && n.ask && (n.path || n.ask.path || n.via === "hub")
    ? n.buttons.map((b) => h("button", { class: "small", type: "button", onclick: (ev) => act(ev.currentTarget, () => answer(n, b), null, () => {
      n.buttons = []; drawPanel();
    }) }, b.label))
    : [];
  return h("div", { class: "notify-item" },
    h("b", {}, n.title),
    n.text ? h("p", { class: "small" }, n.text) : null,
    h("div", { class: "row" }, ...btns,
      n.project ? h("a", { class: "btn small", href: projectHref(n.project), onclick: () => toggle(false) }, "Open") : null,
      h("span", { class: "muted small" }, ago(n.at))));
}

function drawPanel() {
  if (!state.panel) return;
  const list = state.items.slice(-KEEP).reverse();
  fill(state.panel, h("h2", {}, "Your news"),
    list.length ? list.map(item) : h("p", { class: "muted" }, "Nothing new. News shows here when a project finishes, stops or needs you."),
    h("p", { class: "small" }, h("a", { href: "#/settings/notifications", onclick: () => toggle(false) }, "Choose which news pops up")));
}

function toggle(on) {
  state.open = on === undefined ? !state.open : on;
  if (state.open) {
    if (!state.panel) { state.panel = h("div", { class: "notify-panel", role: "dialog", "aria-label": "Your news" }); document.body.append(state.panel); }
    state.panel.hidden = false;
    drawPanel();
    state.unread = 0;
    if (state.next !== null) writeSeen(state.next);
    drawBadge();
  } else if (state.panel) state.panel.hidden = true;
}

// ---------- polling ----------
async function poll() {
  try {
    const r = await get("/api/notifications" + (state.next === null ? "" : `?since=${state.next}`));
    state.settings = r.settings; state.kinds = r.kinds || state.kinds;
    const fresh = r.news || [];
    const first = state.next === null;
    state.next = r.next;
    if (fresh.length) {
      state.items = state.items.concat(fresh).slice(-KEEP);
      const seen = readSeen();
      state.unread += fresh.filter((n) => n.n > seen).length;
      // the first look after opening the app shows only what came since it was last opened
      announce(first ? fresh.filter((n) => n.n > seen) : fresh);
      drawBadge();
      if (state.open) drawPanel();
    }
  } catch { /* offline for a moment: try again later */ }
  setTimeout(poll, document.hidden ? 60000 : 20000);
}

export async function startNotify() {
  if (state.started) return;
  state.started = true;
  if (!(await has("/api/notifications"))) return;
  document.head.append(h("style", {}, STYLE));
  const end = document.querySelector("#top .top-end");
  if (end) { state.bell = bellButton(); end.prepend(state.bell); }
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && state.open) toggle(false); });
  poll();
}

// ---------- Settings → Notifications ----------
export async function notifySettings() {
  let s, kinds;
  try {
    const r = await get("/api/notifications?since=" + (state.next ?? 0));
    s = r.settings; kinds = r.kinds || [];
  } catch (e) {
    return h("section", { class: "card" }, h("h2", {}, "Notifications"), h("p", {}, `This copy can't show news yet: ${e.message}`));
  }
  const save = (changes) => act(null, () => post("/api/notifications/settings", changes), "Saved", (r) => { state.settings = r; s = r; });
  const perm = h("p", { class: "small muted" });
  const drawPerm = () => {
    if (!("Notification" in window)) fill(perm, "This window can't show the system's pop-ups, so news shows inside the app instead.");
    else if (Notification.permission === "granted") fill(perm, "Pop-ups show even while the app is behind other windows.");
    else if (Notification.permission === "denied") fill(perm, "The system's pop-ups are blocked, so news shows inside the app instead.");
    else fill(perm, h("button", { class: "small", type: "button", title: "Lets news pop up even while the app is behind other windows",
      onclick: async () => { try { await Notification.requestPermission(); } catch { /* fine */ } drawPerm(); } }, "Allow pop-ups on this computer"));
  };
  drawPerm();
  const rows = kinds.map((k) => h("label", { title: k.hint },
    h("input", { type: "checkbox", checked: (s.kinds || {})[k.id] !== false, onchange: (ev) => save({ kinds: { [k.id]: ev.target.checked } }) }),
    h("span", {}, h("b", {}, k.name), h("br"), h("span", { class: "small muted" }, k.hint))));
  return h("section", { class: "card" },
    h("h2", {}, "Notifications"),
    h("p", {}, "Which news pops up on this computer. The bell keeps the last 20 either way. Your phone has its own switches."),
    h("label", { class: "check", title: "Turn every pop-up off or on" },
      h("input", { type: "checkbox", checked: s.popups, onchange: (ev) => save({ popups: ev.target.checked }) }), "Pop-ups on"),
    h("div", { class: "notify-kinds" }, rows),
    perm);
}

startNotify();
