// The words the owner reads, in their language (wave 9). A stub with its frozen shape: wave 9's words helper
// fills it from lang/<code>.json ({"English sentence": "translated"}, the same files the phone reads).
// The key is the British English sentence itself, with {name} holes, so a missing translation shows English.
// Until it is filled every sentence stays British English and nothing on the page changes.

const HOLE = /\{(\w+)\}/g;
const RTL = new Set(["ar", "he", "fa", "ur"]);
let LANG = "en-GB";

/** text in the chosen language with its {holes} filled from vals; a hole with no value stays as it is. */
export function t(text, vals) {
  const s = String(text);
  if (!vals) return s;
  return s.replace(HOLE, (m, k) => (Object.prototype.hasOwnProperty.call(vals, k) ? String(vals[k]) : m));
}
/** A fixed sentence on its way to the screen (h and fill): swapped when the table has it, else as it is. */
export function auto(text) { return text; }
/** The chosen language's code ("en-GB" by default). */
export function lang() { return LANG; }
/** "rtl" for Arabic, Hebrew, Persian and Urdu, else "ltr". */
export function dir() { return RTL.has(LANG.split("-")[0]) ? "rtl" : "ltr"; }
/** The locale dates, numbers and money are written in. */
export function locale() { return LANG; }
/** Read the chosen language and its table, and set lang and dir on <html>, before the first draw. */
export async function load() {
  const root = document.documentElement;
  if (root.lang !== lang()) root.lang = lang();
  if (dir() === "rtl") root.dir = "rtl"; else root.removeAttribute("dir");
  return lang();
}
