// Shared helpers: elements, the API, polling, dialogs and the words the owner reads.
// Every node is built with h() (text, never HTML): journal entries, letters and logs hold model output.
import * as words from "./words.js";

/** The name the owner reads (brand.py's twin). Names machines read stay "roundtable". */
export const BRAND = Object.freeze({ name: "Darkness Harness", short: "Darkness", legacy: "Roundtable Hold" });

// Words the owner reads pass through words.auto (wave 9: their language); { raw: true } keeps a node's own text
// and attributes as they are (a project's name, a plan, a model's words, code).
const WORDY = new Set(["title", "placeholder", "aria-label", "alt"]);
const say = (raw, v) => (raw || typeof v !== "string" ? v : words.auto(v));
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  const raw = !!(attrs && attrs.raw === true);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "raw") continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "tip") el.title = say(raw, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, WORDY.has(k) ? say(raw, v) : v);
  }
  add(el, kids, raw);
  return el;
}
function add(el, kids, raw = false) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false || kid === "") continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(raw ? String(kid) : textOf(kid)));
  }
}
const textOf = (kid) => (typeof kid === "string" ? words.auto(kid) : String(kid));
export const clean = (list) => [list].flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false && x !== "");
export function fill(el, ...kids) { el.replaceChildren(...clean(kids).map((k) => (k instanceof Node ? k : document.createTextNode(textOf(k))))); return el; }

// ---------- the API ----------
export async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.headers["X-Agent-Hub"] = "1";
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try { res = await fetch(path, opts); } catch { throw new Error(words.t("{name} isn't answering. If the window was left open a long time, close and open the app again.", { name: BRAND.name })); }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new Error(String((data && data.error) || words.t("Something went wrong ({status}). Try again in a moment.", { status: res.status })).replace(/\s*\(https?:[^)]*\)/g, ""));
  return data;
}
export const get = (path) => api("GET", path);
export const post = (path, body) => api("POST", path, body);
export const q = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();

// The routes this copy of the app has: optional parts (another computer's sessions, machines) are only asked for when there.
let FEATURES = null;
export async function features() {
  if (!FEATURES) { try { FEATURES = new Set((await get("/api/features")).routes); } catch { FEATURES = new Set(); } }
  return FEATURES;
}
export async function has(route) { return (await features()).has(route); }

// ---------- feedback ----------
export function toast(text, err = false) {
  const t = h("div", { class: "toast" + (err ? " err" : ""), role: err ? "alert" : "status" }, text);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), err ? 8000 : 3500);
}
// one click: do it, say so, and let the page refresh; the button rests while it works
export async function act(btn, fn, ok, after) {
  if (btn) btn.disabled = true;
  try {
    const r = await fn();
    if (ok) toast(typeof ok === "function" ? ok(r) : ok);
    if (after) await after(r);
    return r;
  } catch (e) { toast(e.message, true); return undefined; }
  finally { if (btn && btn.isConnected) btn.disabled = false; }
}

// A dialog in the page's own look (never the browser's): resolves true / false, or the typed text.
export function dialog({ title, text, yes = "Yes", no = "Cancel", danger = false, input = null, wide = false, body = null }) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const field = input ? h(input.rows ? "textarea" : "input", { class: "grow", rows: input.rows || null, placeholder: input.placeholder || "",
      type: input.type || null, "aria-label": input.label || title, autocomplete: "off" }) : null;
    if (field && input.value) field.value = input.value;
    const done = (v) => { box.remove(); document.removeEventListener("keydown", key, true); if (prev && prev.focus) prev.focus(); resolve(v); };
    const ok = h("button", { class: danger ? "danger solid" : "primary", type: "button", onclick: () => done(field ? field.value : true) }, yes);
    const key = (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); done(field ? null : false); }
      if (ev.key === "Enter" && field && !input.rows) { ev.preventDefault(); done(field.value); }
    };
    const box = h("div", { class: "modal-back", onclick: (ev) => { if (ev.target === box) done(field ? null : false); } },
      h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title },
        h("h2", {}, title), text ? h("p", { class: "pre-line" }, text) : null, body, field,
        h("div", { class: "row end" }, no ? h("button", { type: "button", onclick: () => done(field ? null : false) }, no) : null, ok)));
    document.addEventListener("keydown", key, true);
    document.body.append(box);
    setTimeout(() => (field || ok).focus(), 0);
  });
}

// ---------- living pages ----------
// Run fn now and every ms while node is on the page; stops by itself when the page changes, or when fn returns false.
export function every(node, fn, ms) {
  let seen = false, waits = 0;
  const tick = async () => {
    if (!node.isConnected) { if (seen || ++waits > 60) return; setTimeout(tick, 50); return; }
    seen = true;
    try { if ((await fn()) === false) return; } catch { /* the next tick tries again */ }
    if (node.isConnected) setTimeout(tick, typeof ms === "function" ? ms() : ms);
  };
  setTimeout(tick, 0);
  return node;
}
// Redraw el only when what it shows changed, and never under the owner's cursor while they type.
export function patch(el, sig, build) {
  if (el._sig === sig) return false;
  const a = document.activeElement;
  if (el._sig !== undefined && a && el.contains(a) && (a.value || a.tagName === "TEXTAREA")) return false;
  el._sig = sig;
  fill(el, build());
  return true;
}

// ---------- the Hall's data, shared by every room (one request every few seconds) ----------
export const S = { rt: null, ov: null, setup: null, routing: null, listeners: new Set(), offline: false };
export function onHall(node, fn) {  // fn(rt) now and whenever the Hall's data changes, while node is shown
  const l = { node, fn };
  S.listeners.add(l);
  if (S.rt) setTimeout(() => node.isConnected && fn(S.rt), 0);
  return node;
}
export async function refreshHall() {
  try { S.rt = await get("/api/roundtable"); S.offline = false; }
  catch { S.offline = true; }
  for (const l of [...S.listeners]) {
    if (!l.node.isConnected && l.node._shown) { S.listeners.delete(l); continue; }
    if (l.node.isConnected) { l.node._shown = true; if (S.rt) try { l.fn(S.rt); } catch (e) { console.warn(e); } }
  }
  return S.rt;
}
// how many things wait for the owner: every card counts, not just one per project
export const needsCount = (rt) => (rt.needs_you || []).reduce((n, x) => n + (x.kind === "messages" ? 0 : x.asks || 1), 0);
export async function hall() { return S.rt || refreshHall(); }
export function seatOf(id) { return S.rt ? S.rt.seats.find((s) => s.id === id) : null; }
export function seatByPath(path) {
  if (!S.rt || !path) return null;
  return S.rt.seats.find((s) => s.path === path) || S.rt.seats.find((s) => s.id === String(path).split(/[\\/]/).pop());
}
export function projectName(id) {
  const name = nameOf(id);
  return words.lang() === "en-GB" ? name : words.keep(name);  // a project's name is never translated
}
function nameOf(id) {
  const s = seatOf(id);
  if (s) return s.name;
  if (S.rt && S.rt.notes && S.rt.notes.id === id) return S.rt.notes.name;
  const a = S.ov && (S.ov.agents || []).find((x) => x.id === id);
  return a ? a.name : readable(id);
}
export const readable = (id) => String(id || "").split(/[-_.\s]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ") || String(id || "");
export const projectHref = (id, tab) => `#/p/${encodeURIComponent(id)}${tab ? "/" + tab : ""}`;

// ---------- words ----------
export const money = (x) => {
  const n = Number(x) || 0, d = n > 0 && n < 0.01 ? 4 : 2, loc = words.locale();
  return "$" + (loc === "en-GB" ? n.toFixed(d) : n.toLocaleString(loc, { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false }));
};
// the browser's own way for British English (as before wave 9), the chosen language's otherwise
const dateLocale = () => (words.lang() === "en-GB" ? undefined : words.locale());
export function ago(ts) {
  if (!ts) return "";
  const s = Math.floor((Date.now() - Date.parse(ts)) / 1000);
  if (isNaN(s)) return "";
  if (words.lang() !== "en-GB" && s < 30 * 86400) return words.ago(s);  // the chosen language's own words
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) { const n = Math.floor(s / 3600); return `${n} hour${n > 1 ? "s" : ""} ago`; }
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : new Date(ts).toLocaleDateString(dateLocale());
}
export function clock(ts) { const d = new Date(ts); return isNaN(d) ? "" : d.toLocaleTimeString(words.locale(), { hour: "2-digit", minute: "2-digit" }); }
export const when = (ts) => h("time", { datetime: ts, title: ts ? new Date(ts).toLocaleString(dateLocale()) : "" }, ago(ts));
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
export function fileSize(n) { const u = ["bytes", "KB", "MB", "GB"]; let i = 0; n = Number(n) || 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return i ? `${n.toFixed(1)} ${u[i]}` : `${n} bytes`; }

const PROJECT_STATES = { planning: "Making the plan", awaiting_approval: "The plan is ready for you", running: "Building",
  paused: "Paused part-way", paused_budget: "Stopped at the spending limit", blocked: "Stopped: a task needs you", done: "Finished" };
export const projectState = (s) => PROJECT_STATES[s] || (s ? readable(s) : "Not started");
const TASK_STATES = { pending: ["Waiting its turn", ""], running: ["Being built", "info"], done: ["Done", "good"], failed: ["Didn't work", "bad"],
  skipped: ["Skipped", ""], blocked: ["Held up", "warn"], approved: ["Approved", "good"], rejected: ["Sent back", "warn"] };
export function taskPill(s) { const [w, c] = TASK_STATES[s] || [readable(s), ""]; return h("span", { class: "pill " + c }, w); }
const JOB_STATES = { running: ["Working", "info"], done: ["Finished", "good"], failed: ["Didn't work", "bad"] };
export function jobPill(s) { const [w, c] = JOB_STATES[s] || [readable(s), ""]; return h("span", { class: "pill " + c }, w); }

// jobs (roles) and models in plain words; the Models page's data refines these when it's loaded
const JOBS = { orchestrator: "Planner", planner: "Planner", manager: "Project manager", critic: "Critic", designer: "Designer", coder: "Coder",
  scout: "Researcher", stylist: "Stylist", reviewer: "Reviewer", illustrator: "Illustrator", artist: "Pixel artist", writer: "Writer", tester: "Tester",
  owner: "You" };
export const jobName = (role) => (S.routing && (S.routing.jobs.find((j) => j.role === role) || {}).name) || JOBS[role] || readable(role);
const PROVIDERS = { anthropic: "Anthropic", deepseek: "DeepSeek", openai: "OpenAI", openai_images: "OpenAI", gemini: "Google", openrouter: "OpenRouter",
  openrouter_images: "OpenRouter", openference: "Openference", retrodiffusion: "Retro Diffusion", scripted: "Test models" };
const WORDS = { gpt: "GPT", glm: "GLM", deepseek: "DeepSeek", openai: "OpenAI", rd: "RD", ai: "AI", xl: "XL" };
function pretty(name) {
  if (name.includes(" ")) return name;
  const out = [];
  for (const w of name.split(/[-_]+/).filter(Boolean)) {
    if (/^\d+$/.test(w) && out.length && /^\d+(\.\d+)*$/.test(out[out.length - 1])) out[out.length - 1] += "." + w;
    else out.push(WORDS[w.toLowerCase()] || w[0].toUpperCase() + w.slice(1));
  }
  return out.join(" ") || name;
}
export const providerName = (pid) => (S.routing && S.routing.providers[pid] && S.routing.providers[pid].name) || PROVIDERS[pid] || PROVIDERS[String(pid).replace(/_images$/, "")] || readable(pid);
export function modelName(ref, short = false) {
  if (!ref) return "";
  const i = String(ref).indexOf("/");
  if (i < 0) return pretty(String(ref));
  const pid = ref.slice(0, i), name = pretty(ref.slice(i + 1).split("/").pop());
  return short ? name : `${name} (${providerName(pid)})`;
}
export const modelTag = (ref) => h("span", { class: "model", title: ref ? `${modelName(ref)}` : "" }, modelName(ref, true));

// ---------- small building blocks ----------
export const card = (title, ...kids) => h("section", { class: "card" }, title ? h("div", { class: "card-head" }, typeof title === "string" ? h("h2", {}, title) : title) : null, ...kids);
export const empty = (text, ...more) => h("div", { class: "empty" }, h("p", {}, text), ...more);
export function page(title, sub, ...kids) {
  return h("div", { class: "page" }, h("header", { class: "page-head" }, h("div", {}, h("h1", {}, title), sub ? h("p", { class: "sub" }, sub) : null)), ...kids);
}
export function tabs(items, current, hrefOf, label) {
  return h("nav", { class: "tabs", "aria-label": label || "Parts of this page" }, items.map(([k, text, tip, extra]) =>
    h("a", { class: "tab" + (k === current ? " on" : ""), href: hrefOf(k), title: tip || "", "aria-current": k === current ? "page" : null }, text, extra || null)));
}
export function seg(options, value, onpick, label) {  // a row of choices, one on
  const box = h("div", { class: "seg", role: "group", "aria-label": label || "" });
  for (const [v, text, tip] of options) {
    box.append(h("button", { type: "button", class: v === value ? "on" : "", "aria-pressed": String(v === value), title: tip || "", onclick: (ev) => {
      box.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b === ev.currentTarget); b.setAttribute("aria-pressed", String(b === ev.currentTarget)); });
      onpick(v);
    } }, text));
  }
  return box;
}
// a little colour for each project, always the same one
export function tint(id) { let n = 0; for (const ch of String(id)) n = (n * 31 + ch.charCodeAt(0)) >>> 0; return "tg" + (n % 8); }
export const dot = (id) => h("i", { class: "tagc " + tint(id), "aria-hidden": "true" });

// pictures: shown small, full size on a click
export function enlarge(src, label) {
  const close = () => { box.remove(); document.removeEventListener("keydown", esc); };
  const esc = (ev) => { if (ev.key === "Escape") close(); };
  const box = h("div", { class: "lightbox", role: "dialog", "aria-label": label, onclick: close },
    h("img", { src, alt: label }), h("p", {}, label, h("span", { class: "muted" }, " · click anywhere to close")));
  document.addEventListener("keydown", esc);
  document.body.append(box);
}
export function picture(src, label, cls = "") {
  return h("button", { class: "pic " + cls, type: "button", title: `${label}: click to see it full size`, onclick: () => enlarge(src, label) },
    h("img", { src, alt: label, loading: "lazy" }));
}

// A plain-text report with headings and lists drawn as such (never as HTML).
export function prose(text) {
  const box = h("div", { class: "prose" });
  let list = null;
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trimEnd();
    const m = line.match(/^(#{1,4})\s+(.*)$/), li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (li) { if (!list) { list = h("ul"); box.append(list); } list.append(h("li", { raw: true }, strip(li[1]))); continue; }
    list = null;
    if (!line.trim()) continue;
    if (m) box.append(h(m[1].length <= 2 ? "h3" : "h4", { raw: true }, strip(m[2])));
    else if (/^\s*```/.test(line)) continue;
    else box.append(h("p", { raw: true }, strip(line)));
  }
  return box;
}
const strip = (s) => s.replace(/\*\*(.*?)\*\*/g, "$1").replace(/`([^`]*)`/g, "$1").replace(/^_+|_+$/g, "");

// Readable markdown for documents (the hub's saved notes): headings, lists, tables, quotes, code, rules; inline
// bold, italic, code and links. Built as nodes, never as HTML text; a link opens outside the app.
export function markdown(text) {
  const box = h("div", { class: "prose md" });
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let list = null, para = [];
  const flush = () => { if (para.length) { box.append(h("p", { raw: true }, inlineMd(para.join(" ")))); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd(), t = line.trim();
    if (/^```/.test(t)) {
      flush(); list = null;
      const code = [];
      for (i++; i < lines.length && !/^```/.test(lines[i].trim()); i++) code.push(lines[i]);
      box.append(h("pre", { raw: true, class: "log short" }, code.join("\n")));
      continue;
    }
    if (!t) { flush(); list = null; continue; }
    const hd = t.match(/^(#{1,6})\s+(.*)$/);
    if (hd) { flush(); list = null; box.append(h(hd[1].length <= 1 ? "h2" : hd[1].length === 2 ? "h3" : "h4", { raw: true }, inlineMd(hd[2]))); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { flush(); list = null; box.append(h("hr")); continue; }
    if (t.startsWith("|") && t.endsWith("|")) {
      flush(); list = null;
      const rows = [];
      for (; i < lines.length && /^\|.*\|$/.test(lines[i].trim()); i++) {
        const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
      }
      i--;
      const [head, ...body] = rows;
      box.append(h("div", { class: "md-table" }, h("table", { class: "plain-table" },
        head ? h("thead", {}, h("tr", {}, head.map((c) => h("th", { raw: true }, inlineMd(c))))) : null,
        h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => h("td", { raw: true }, inlineMd(c)))))))));
      continue;
    }
    if (t.startsWith(">")) { flush(); list = null; box.append(h("blockquote", { raw: true }, inlineMd(t.replace(/^>\s?/, "")))); continue; }
    const li = line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/);
    if (li) {
      flush();
      const tag = li[2] ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) { list = h(tag); box.append(list); }
      list.append(h("li", { raw: true }, inlineMd(li[3].replace(/^\[[ xX]\]\s+/, ""))));
      continue;
    }
    list = null;
    para.push(t);
  }
  flush();
  return box;
}

const SAFE_LINK = /^(https?:|mailto:)/i;
export function inlineMd(s) {
  const out = [];
  const re = /\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?])|(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])|(?<![\w_])_([^_\s][^_]*?)_(?![\w_])/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(words.keep(s.slice(last, m.index)));
    if (m[1] || m[2]) out.push(h("b", { raw: true }, m[1] || m[2]));
    else if (m[3]) out.push(h("code", { raw: true }, m[3]));
    else if (m[4]) out.push(SAFE_LINK.test(m[5]) ? h("a", { href: m[5], target: "_blank", rel: "noopener noreferrer", title: m[5], raw: true }, m[4]) : m[4]);
    else if (m[6]) out.push(h("a", { href: m[6], target: "_blank", rel: "noopener noreferrer" }, m[6]));
    else if (m[7] || m[8]) out.push(h("i", { raw: true }, m[7] || m[8]));
    last = re.lastIndex;
  }
  if (last < s.length) out.push(words.keep(s.slice(last)));
  return out;
}
