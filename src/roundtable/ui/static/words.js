// The words the owner reads, in their language (wave 9). The table is lang/<code>.json ({"English sentence":
// "translated"}, the same files the phone reads), served with the owner's own fixes by GET /api/words.
// The key is the British English sentence itself, with {name} holes, so a missing translation shows English.
// British English is the default: with it nothing is looked up and the page is exactly as it was.
// A value may be plural forms ({one, few, many, other, …}, the language's own categories), chosen by vals.n.

const HOLE = /\{(\w+)\}/g;
const RTL = new Set(["ar", "he", "fa", "ur"]);
let LANG = "en-GB", LOCALE = "en-GB", DIR = "ltr", TABLE = Object.create(null), INFO = null;
const own = Object.prototype.hasOwnProperty;

function fillIn(s, vals) {
  if (!vals) return s;
  return s.replace(HOLE, (m, k) => (own.call(vals, k) ? String(vals[k]) : m));
}
const rules = new Map();
function category(n, loc) {
  try {
    if (!rules.has(loc)) rules.set(loc, new Intl.PluralRules(loc));
    return rules.get(loc).select(Number(n));
  } catch { return Number(n) === 1 ? "one" : "other"; }
}
function pick(value, vals, fallback) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const n = vals && (own.call(vals, "n") ? vals.n : vals.count);
    const got = n === undefined ? value.other : value[category(n, LOCALE)] || value.other;
    if (typeof got === "string" && got) return got;
  }
  return fallback;
}

/** text in the chosen language with its {holes} filled from vals; a hole with no value stays as it is.
 *  text may be English plural forms, {one: "{n} task", other: "{n} tasks"}: the table's key is the other form. */
export function t(text, vals) {
  let s;
  if (text && typeof text === "object") {
    const n = vals && (own.call(vals, "n") ? vals.n : vals.count);
    s = String((n !== undefined && category(n, "en-GB") === "one" && text.one) || text.other || "");
    if (LANG !== "en-GB" && text.other && own.call(TABLE, text.other)) s = pick(TABLE[text.other], vals, s);
  } else {
    s = String(text);
    if (LANG !== "en-GB") s = swap(s, vals);
  }
  return fillIn(s, vals);
}
/** A fixed sentence on its way to the screen (h and fill): swapped when the table has it, else as it is.
 *  Spaces around it are kept, so "Cost: " finds "Cost:". */
export function auto(text) {
  if (LANG === "en-GB" || typeof text !== "string" || !text) return text;
  return swap(text, null);
}
// the table's sentence for s, keeping the spaces around it (" · patch {size}" finds "· patch {size}")
function swap(s, vals) {
  if (own.call(TABLE, s)) return pick(TABLE[s], vals, s);
  const core = s.trim();
  if (core === s || !own.call(TABLE, core)) return s;
  const at = s.indexOf(core);
  return s.slice(0, at) + pick(TABLE[core], vals, core) + s.slice(at + core.length);
}
/** Text that must never be translated (a project's name, a model's words): h and fill leave it as it is. */
export function keep(text) { return new String(text); } // eslint-disable-line no-new-wrappers
/** The chosen language's code ("en-GB" by default). */
export function lang() { return LANG; }
/** "rtl" for Arabic, Hebrew, Persian and Urdu, else "ltr". */
export function dir() { return DIR === "rtl" || RTL.has(LANG.split("-")[0]) ? "rtl" : "ltr"; }
/** The locale dates, numbers and money are written in. */
export function locale() { return LOCALE; }
/** What /api/words said (the list of languages, the label, the allowance), or null before load(). */
export function info() { return INFO; }
/** "3 minutes ago" in the chosen language (seconds: how long ago, a positive number). */
export function ago(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const f = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
  if (s < 60) return f.format(0, "second");
  if (s < 3600) return f.format(-Math.floor(s / 60), "minute");
  if (s < 86400) return f.format(-Math.floor(s / 3600), "hour");
  return f.format(-Math.floor(s / 86400), "day");
}
/** A number in the chosen language's way. */
export function number(n, opts) { try { return Number(n).toLocaleString(LOCALE, opts); } catch { return String(n); } }

/** Use a table now (tests, and load() below). */
export function use(code, table, opts = {}) {
  LANG = code || "en-GB";
  LOCALE = opts.locale || LANG;
  DIR = opts.dir || (RTL.has(LANG.split("-")[0]) ? "rtl" : "ltr");
  TABLE = Object.assign(Object.create(null), LANG === "en-GB" ? {} : table || {});
  return LANG;
}
function mark() {
  if (typeof document === "undefined" || !document.documentElement) return;
  const root = document.documentElement;
  if (root.lang !== LANG) root.lang = LANG;
  if (dir() === "rtl") root.dir = "rtl"; else root.removeAttribute("dir");
  if (root.classList) root.classList.toggle("rtl", dir() === "rtl");
  if (LANG !== "en-GB" && typeof document.querySelectorAll === "function") shell();
}
// The page's frame in index.html (the rooms, the skip link) is written before any h(): its words, swapped once.
function shell() {
  for (const el of document.querySelectorAll(".skip, #top [title], #top .rooms a, #top [placeholder], #main > .loading")) {
    if (el.title) el.title = auto(el.title);
    if (el.placeholder) el.placeholder = auto(el.placeholder);
    const label = el.getAttribute && el.getAttribute("aria-label");
    if (label) el.setAttribute("aria-label", auto(label));
    for (const n of el.childNodes) if (n.nodeType === 3 && n.data.trim()) n.data = auto(n.data);
  }
}
/** Read the chosen language and its table, and set lang and dir on <html>, before the first draw. */
export async function load() {
  try {
    const res = await fetch("/api/words");
    if (res.ok) {
      INFO = await res.json();
      use(INFO.lang, INFO.table, { locale: INFO.locale, dir: INFO.dir });
    }
  } catch { /* British English, as before */ }
  mark();
  return lang();
}
