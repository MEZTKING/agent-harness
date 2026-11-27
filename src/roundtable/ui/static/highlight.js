// Colouring for code in the Files tab, the editor's preview and Markdown's fenced code: our own small tokeniser
// for Python, JavaScript (and TypeScript), JSON, HTML (and XML, SVG), CSS, Kotlin, Java, GDScript, shell and YAML.
// Comments, strings, numbers, keywords, and for HTML the tags and their attributes. It only ever makes text
// nodes inside spans (h() as text): a file's contents are never read as HTML. Any other language gets the plain
// fallback (comments, strings, numbers and common keywords).
import { h } from "./core.js";

const words = (s) => new Set(s.split(/\s+/).filter(Boolean));
const C_LIKE = { line: "//", block: ["/*", "*/"] };
const LANGS = {
  python: { line: "#", strings: ["'''", '"""', "'", '"'], kw: words("and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return self True try while with yield match case") },
  javascript: { ...C_LIKE, strings: ["`", "'", '"'], kw: words("async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield interface type enum implements private protected public readonly as") },
  json: { strings: ['"'], kw: words("true false null"), keys: true },
  css: { block: ["/*", "*/"], strings: ["'", '"'], kw: words("important inherit initial unset none auto var calc"), css: true },
  kotlin: { ...C_LIKE, strings: ['"""', '"', "'"], kw: words("as break class continue do else false for fun if in interface is null object package return super this throw true try typealias val var when while by catch constructor companion data enum finally import init internal lateinit open override private protected public sealed suspend") },
  java: { ...C_LIKE, strings: ['"""', '"', "'"], kw: words("abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new null package private protected public return short static super switch synchronized this throw throws transient true false try var void volatile while record") },
  gdscript: { line: "#", strings: ['"""', '"', "'"], kw: words("and as assert await break breakpoint class class_name const continue elif else enum export extends false for func if in is match not null onready or pass preload return self signal static super true var void while yield @export @onready") },
  shell: { line: "#", strings: ["'", '"'], kw: words("if then else elif fi for in do done while until case esac function return export local echo exit set unset cd source") },
  yaml: { line: "#", strings: ["'", '"'], kw: words("true false null yes no on off"), keys: true },
};
const ALIAS = { typescript: "javascript", js: "javascript", ts: "javascript", jsx: "javascript", tsx: "javascript", mjs: "javascript",
  py: "python", sh: "shell", bash: "shell", zsh: "shell", console: "shell", yml: "yaml", kt: "kotlin", kts: "kotlin", gd: "gdscript",
  htm: "html", xml: "html", svg: "html", vue: "html", svelte: "html", scss: "css", less: "css", jsonl: "json", jsonc: "json", webmanifest: "json" };
const FALLBACK = { line: "#", ...C_LIKE, strings: ["'", '"', "`"], kw: words("if else for while return function def class import from true false null none var let const") };
const LIMIT = 400_000;

export const langName = (lang) => ALIAS[String(lang || "").toLowerCase()] || String(lang || "").toLowerCase();

function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

function regexFor(spec) {
  const parts = [];
  if (spec.block) parts.push(`${esc(spec.block[0])}[\\s\\S]*?(?:${esc(spec.block[1])}|$)`);
  if (spec.line) parts.push(`${esc(spec.line)}[^\\n]*`);
  for (const q of spec.strings || []) {
    parts.push(q.length === 3 ? `${esc(q)}[\\s\\S]*?(?:${esc(q)}|$)` : `${esc(q)}(?:\\\\.|[^${esc(q)}\\\\\\n])*${esc(q)}?`);
  }
  parts.push("\\b0[xX][0-9a-fA-F]+\\b|\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b");
  if (spec.css) parts.push("#[0-9a-fA-F]{3,8}\\b|[.#][A-Za-z_-][\\w-]*|@[\\w-]+");
  parts.push("@?[A-Za-z_][\\w-]*");
  return new RegExp(parts.join("|"), "g");
}
const CACHE = new Map();

function classOf(t, spec, text, end) {
  if ((spec.line && t.startsWith(spec.line)) || (spec.block && t.startsWith(spec.block[0]))) return "hl-c";
  if ((spec.strings || []).some((q) => t.startsWith(q))) {
    if (spec.keys && /^\s*:/.test(text.slice(end, end + 40))) return "hl-key";  // a JSON or YAML key
    return "hl-s";
  }
  if (/^(0[xX]|\d)/.test(t)) return "hl-n";
  if (spec.css && /^[#.@]/.test(t)) return /^#[0-9a-fA-F]{3,8}$/.test(t) ? "hl-n" : "hl-k";
  if (spec.kw.has(t)) return "hl-k";
  if (spec.keys && /^\s*:/.test(text.slice(end, end + 40)) && /^\s*(-\s+)?$/.test(text.slice(text.lastIndexOf("\n", end - t.length - 1) + 1, end - t.length))) return "hl-key";
  return null;
}

function tokens(text, spec, out) {
  let re = CACHE.get(spec);
  if (!re) { re = regexFor(spec); CACHE.set(spec, re); }
  re.lastIndex = 0;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (!m[0]) { re.lastIndex++; continue; }
    const cls = classOf(m[0], spec, text, m.index + m[0].length);
    if (!cls) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(h("span", { class: cls }, m[0]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// HTML: comments, tags with their attributes and values, the rest as text (with <script> and <style> coloured too)
function html(text, out) {
  const re = /<!--[\s\S]*?(?:-->|$)|<\/?[A-Za-z][\w:-]*(?:\s+[^<>]*?)?\/?>|<!DOCTYPE[^>]*>/gi;
  let last = 0, m, inner = null;
  while ((m = re.exec(text))) {
    const before = text.slice(last, m.index);
    if (before) inner ? tokens(before, LANGS[inner], out) : out.push(before);
    const t = m[0];
    if (t.startsWith("<!--")) out.push(h("span", { class: "hl-c" }, t));
    else {
      const name = (t.match(/^<\/?([\w:-]+)/) || [])[1] || "";
      const head = t.match(/^<\/?[\w:-]+/)[0];
      out.push(h("span", { class: "hl-t" }, head));
      const rest = t.slice(head.length);
      const ar = /([\w:@.-]+)(\s*=\s*)?("[^"]*"|'[^']*'|[^\s>]+)?|[^\w:@.-]+/g;
      let a;
      while ((a = ar.exec(rest))) {
        if (a[1] && /^[/>]+$/.test(a[0])) { out.push(h("span", { class: "hl-t" }, a[0])); continue; }
        if (a[1]) {
          out.push(h("span", { class: "hl-a" }, a[1]));
          if (a[2]) out.push(a[2]);
          if (a[3]) out.push(h("span", { class: "hl-s" }, a[3]));
        } else out.push(/[/>]/.test(a[0]) ? h("span", { class: "hl-t" }, a[0]) : a[0]);
      }
      const low = name.toLowerCase();
      if (!t.startsWith("</") && (low === "script" || low === "style")) inner = low === "script" ? "javascript" : "css";
      else if (t.startsWith("</")) inner = null;
    }
    last = m.index + t.length;
  }
  if (last < text.length) inner ? tokens(text.slice(last), LANGS[inner], out) : out.push(text.slice(last));
  return out;
}

// The coloured text as nodes (an array to append); plain text for no language or a very big file.
export function highlight(text, lang) {
  text = String(text ?? "");
  const name = langName(lang);
  if (!name || text.length > LIMIT) return [text];
  if (name === "html") return html(text, []);
  return tokens(text, LANGS[name] || FALLBACK, []);
}

export function highlightStyles() {
  if (typeof document === "undefined" || document.getElementById("hl-style")) return;
  document.head.append(h("style", { id: "hl-style" }, `
.hl-t { color: var(--color-accent); }
.hl-a { color: var(--color-flare); }
.hl-key { color: var(--color-text); font-weight: 600; }
`));
}
