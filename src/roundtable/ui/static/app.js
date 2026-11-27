// Roundtable Hold – the desktop command centre. Plain ES modules, no build step.
// The shell: the rooms in the header, the router, today's spend, the work running now and the update banner.
import { h, fill, get, post, S, refreshHall, seatByPath, money, act, needsCount } from "./core.js";
import { drawAutopilot, loadAutopilot } from "./autopilot.js";
import { viewHall } from "./hall.js";
import { viewNeeds } from "./needs.js";
import { viewProjects, viewNew } from "./projects.js";
import { viewProject } from "./project.js";
import { viewLetters } from "./letters.js";
import { viewActivity } from "./activity.js";
import { viewModels } from "./models.js";
import { viewSettings, viewSetup } from "./settings.js";
import { viewTools } from "./tools.js";
import "./notify.js";
import "./whatsnew.js";
import { viewSearch, mountSearch } from "./search.js";
import { viewAutomations } from "./automation.js";
import { viewGallery } from "./gallery.js";
import { pounds } from "./pounds.js";

const ROOMS = { tools: viewTools, automations: viewAutomations, hall: viewHall, needs: viewNeeds, projects: viewProjects, new: viewNew, p: viewProject, letters: viewLetters,
  activity: viewActivity, models: viewModels, settings: viewSettings, setup: viewSetup, search: viewSearch,
  gallery: viewGallery };
const ROOM_OF = { new: "projects", p: "projects", setup: "settings", automations: "settings" };

// old addresses (bookmarks, links in letters and the autopilot's log) still land in the right place
function translate(parts) {
  const [a, ...rest] = parts;
  const byPath = (path, tab) => { const s = seatByPath(path); return ["p", s ? s.id : String(path).split(/[\\/]/).pop(), tab]; };
  switch (a) {
    case "": case "roundtable": case "where": return ["hall"];
    case "runs": return ["projects"];
    case "run": return byPath(rest[0], new URLSearchParams(location.hash.split("?")[1] || "").get("tab") === "session" ? "watch" : "");
    case "plan": return byPath(rest[0], "plan");
    case "project": return ["p", rest[0]];
    case "messages": return ["letters", ...rest];
    case "jobs": return ["activity", "work"];
    case "job": return ["activity", "work", rest[0]];
    case "improve": return ["models", "learning"];
    default: return parts;
  }
}
function route() {
  const raw = (location.hash || "#/").slice(2).split("?")[0].split("/").map(decodeURIComponent);
  return translate(raw);
}

let generation = 0, setupChecked = false;
async function render() {
  const gen = ++generation;
  const [room, ...args] = route();
  const view = ROOMS[room] || viewHall;
  const active = ROOM_OF[room] || (ROOMS[room] ? room : "hall");
  document.querySelectorAll("[data-room]").forEach((a) => {
    const on = a.dataset.room === active;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  try {
    if (!S.ov) S.ov = await get("/api/overview");
    if (!setupChecked) {
      setupChecked = true;
      try {
        S.setup = await get("/api/setup");
        if (S.setup.desktop && !S.setup.setup_done && room !== "setup") { location.hash = "#/setup"; return; }
      } catch { /* the rooms work without it */ }
    }
    if (!S.rt) await refreshHall();
    const node = await view(...args.filter((x) => x !== undefined));
    if (gen !== generation) return;  // the owner moved on meanwhile
    fill(document.getElementById("main"), node);
    window.scrollTo(0, 0);
  } catch (e) {
    if (gen !== generation) return;
    fill(document.getElementById("main"), h("div", { class: "page" }, h("section", { class: "card" }, h("h2", {}, "This page couldn't open"),
      h("p", {}, e.message), h("div", { class: "row" }, h("button", { class: "primary", onclick: () => render() }, "Try again"), h("a", { class: "btn", href: "#/" }, "Back to the Hall")))));
  }
}
window.addEventListener("hashchange", () => render());

// ---------- the header: what waits, letters, work running, today's spend, autopilot ----------
function header(rt) {
  const needs = needsCount(rt);
  const letters = rt.notes ? rt.notes.unread || 0 : 0;
  const nb = document.getElementById("needs-badge"), lb = document.getElementById("letters-badge");
  nb.hidden = !needs; nb.textContent = needs; nb.title = `${needs} thing${needs === 1 ? "" : "s"} waiting for you`;
  lb.hidden = !letters; lb.textContent = letters; lb.title = `${letters} unread letter${letters === 1 ? "" : "s"}`;
  const w = document.getElementById("working");
  w.hidden = !rt.running_jobs;
  w.querySelector("span").textContent = rt.running_jobs === 1 ? "1 job running" : `${rt.running_jobs} jobs running`;
  document.querySelector("#today b").textContent = money(rt.spend_today);
  const gbp = pounds(rt.spend_today);  // "≈ £0.95" beside the dollars, when the owner wants pounds
  const tp = document.getElementById("today-gbp");
  if (tp) { tp.textContent = gbp ? ` ${gbp}` : ""; tp.hidden = !gbp; }
  if (rt.autopilot) drawAutopilot(rt.autopilot, true);
  document.title = needs ? `(${needs}) Roundtable Hold` : "Roundtable Hold";
}
const headerNode = document.getElementById("top");
S.listeners.add({ node: headerNode, fn: header });
async function poll() {
  await refreshHall();
  setTimeout(poll, document.hidden ? 15000 : 5000);
}

// ---------- updates: a banner once per start ----------
async function checkUpdate() {
  const el = document.getElementById("banner");
  try {
    const st = await get("/api/update");
    if (!st.available) return;
    fill(el, h("b", {}, "A new Roundtable Hold is ready"), h("span", { class: "muted" }, st.latest && /^\d+\.\d+/.test(st.latest) ? `Version ${st.latest}` : ""),
      h("span", { class: "spacer" }),
      h("button", { class: "primary", title: "Backs up your settings first, then updates", onclick: (ev) => act(ev.currentTarget, () => post("/api/update", {}), "Updating…",
        (j) => { el.hidden = true; if (j && j.id) location.hash = `#/activity/work/${j.id}`; }) }, "Update now"),
      h("button", { onclick: () => (el.hidden = true) }, "Later"));
    el.hidden = false;
  } catch { /* offline: no banner */ }
}

// keyboard: g then a letter moves between rooms (g h Hall, g n Needs you, g p Projects, g l Letters, g a Activity, g m Models, g s Settings)
let gKey = 0;
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (ev.ctrlKey || ev.metaKey || ev.altKey || (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable))) return;
  if (ev.key === "g") { gKey = Date.now(); return; }
  if (Date.now() - gKey < 1200) {
    const to = { h: "#/", n: "#/needs", p: "#/projects", l: "#/letters", a: "#/activity", m: "#/models", s: "#/settings" }[ev.key];
    if (to) { ev.preventDefault(); location.hash = to; }
    gKey = 0;
  }
});

render().then(() => { setTimeout(poll, 5000); loadAutopilot(); checkUpdate(); });
mountSearch(document.getElementById("search"));
