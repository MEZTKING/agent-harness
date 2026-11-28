// The page for an iPhone on your Wi-Fi (webphone.py): pairing, the sign-in kept by the page, and the desktop's own
// screens in their narrow layout. Every call goes to the phone server's /api/… with the paired token, so it meets
// the same allowed list and refusals as the Android app. Off until the owner said yes (nothing is served before).
import { h, fill, toast, S, refreshHall } from "../core.js";
import { t } from "../words.js";
import { appFrame } from "../appframe.js";

const KEY = "darkness.webphone.token";
const DEVICE = "iPhone (web page)";
const store = { get() { try { return sessionStorage.getItem(KEY) || localStorage.getItem(KEY) || ""; } catch { return ""; } },
  set(token, keep) { try { (keep ? localStorage : sessionStorage).setItem(KEY, token); } catch { /* private browsing: this visit only */ } memory = token; },
  clear() { try { sessionStorage.removeItem(KEY); localStorage.removeItem(KEY); } catch { /* nothing kept */ } memory = ""; } };
let memory = store.get();

// the desktop's modules call fetch("/api/…"): the page adds its sign-in to those calls, and to nothing else
const plainFetch = window.fetch.bind(window);
window.fetch = (input, opts = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (memory && url.startsWith("/api/")) opts = { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${memory}` } };
  return plainFetch(input, opts);
};

const main = () => document.getElementById("main");

function pairing(error = "") {
  document.getElementById("rooms").hidden = true;
  const code = h("input", { type: "text", inputmode: "text", autocomplete: "one-time-code", maxlength: "12", "aria-label": "The code on the PC", placeholder: "Code" });
  const keep = h("input", { type: "checkbox" });
  const out = h("p", { class: "small", "aria-live": "polite" }, error);
  const go = async (ev) => {
    ev.preventDefault();
    fill(out, "Checking…");
    try {
      const res = await plainFetch("/api/pair/claim", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.value.trim(), device_name: DEVICE }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || t("The PC said no ({n}). Try again.", { n: res.status }));
      store.set(data.token, keep.checked);
      start();
    } catch (e) { fill(out, e.message); }
  };
  fill(main(), h("div", { class: "page" }, h("section", { class: "card wp-pair" },
    h("h2", {}, "Pair this iPhone with the PC"),
    h("p", {}, "On the PC: Settings → Your phone → Pair a phone. Type the code it shows."),
    h("details", {}, h("summary", { title: "Why Safari warned you, and how to check it's your PC" }, "About Safari's warning"),
      h("p", { class: "small" }, "The PC made its own certificate, so Safari can't vouch for it. Before you typed anything, you should have opened the certificate in Safari's warning and checked its SHA-256 matches the letters on the PC (Settings → The page for an iPhone). If they don't match, close this page.")),
    h("form", { class: "stack", onsubmit: go }, code,
      h("label", { class: "check", title: "Without this you pair again each time Safari is closed" }, keep, "Keep me signed in on this iPhone"),
      h("button", { class: "primary", type: "submit" }, "Pair")),
    out)));
  code.focus();
}

const ROOMS = {
  hall: async () => (await import("../hall.js")).viewHall(),
  needs: async () => (await import("../needs.js")).viewNeeds(),
  projects: async () => (await import("../projects.js")).viewProjects(),
  p: async (id, ...rest) => (await import("../project.js")).viewProject(id, ...rest),
  app: async (path) => h("div", { class: "page" }, h("section", { class: "card" }, h("h2", {}, "Your app"), appFrame(decodeURIComponent(path || "")))),
};
const ROOM_OF = { p: "projects", app: "projects" };

let generation = 0;
async function render() {
  const gen = ++generation;
  const [room, ...args] = (location.hash || "#/").slice(2).split("?")[0].split("/").map(decodeURIComponent);
  const name = ROOMS[room] ? room : "hall";
  document.querySelectorAll("[data-room]").forEach((a) => a.classList.toggle("on", a.dataset.room === (ROOM_OF[name] || name)));
  try {
    if (!S.rt) await refreshHall();
    const node = await ROOMS[name](...args.filter((x) => x !== undefined && x !== ""));
    if (gen === generation) fill(main(), node);
  } catch (e) {
    if (gen !== generation) return;
    if (/isn't paired/.test(e.message)) { store.clear(); pairing("This iPhone was removed on the PC. Pair it again."); return; }
    fill(main(), h("div", { class: "page" }, h("section", { class: "card" }, h("h2", {}, "This page couldn't open"), h("p", {}, e.message),
      h("button", { class: "primary", onclick: () => render() }, "Try again"))));
  }
}

async function start() {
  if (!memory) return pairing();
  const res = await plainFetch("/api/ping", { headers: { Authorization: `Bearer ${memory}` } }).catch(() => null);
  if (!res) { fill(main(), h("p", {}, "The PC isn't answering. Check this iPhone is on the same Wi-Fi, then reload.")); return; }
  if (res.status === 401) { store.clear(); return pairing(); }
  document.getElementById("rooms").hidden = false;
  S.ov = S.ov || {};
  window.addEventListener("hashchange", render);
  await render();
  setInterval(() => { if (!document.hidden) refreshHall().catch(() => null); }, 10000);
  toast("Connected to the PC");
}
start();
