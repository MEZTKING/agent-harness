// Richer previews for the Files tab, and links from words to files.
//  - linkPaths(text, files, opts): a path that exists in the project (src/app.py, src/app.py:12) becomes a link
//    that opens it in Files at that line; a local web address (http://localhost:5173) opens in the Browser.
//  - gfm(text, opts): Markdown as GitHub draws it: tables with alignment, task lists, front matter as a small
//    table, fenced code coloured by highlight.js, strike-through, nested lists. Pictures from outside and badges
//    are never fetched (their words show instead); a picture inside the project shows from the project.
//  - richView(d, opts): a notebook, an archive's list, Word, Excel or PowerPoint, video and sound.
//  - findBar(target, getText): find in any text preview.
// Everything is built with h() as text: nothing from a file is ever read as HTML. API: ui/editapi.py.
import { h, fill, plural, fileSize, picture } from "./core.js";
import { highlight, highlightStyles } from "./highlight.js";

// -- links from words to files ---------------------------------------------------------------------------
const PATHISH = /(?:^|[\s("'`\[<])((?:\.\/)?(?:[\w@.+-]+\/)*[\w@+-][\w@.+-]*\.[A-Za-z0-9]{1,10})(?::(\d+))?(?::\d+)?(?=$|[\s)"'`\],.;:!?>])/g;
const LOCAL_URL = /https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{2,5})?(?:\/[^\s"'<>`)\]]*)?/gi;

// files: a Set (or array) of the project's paths, as /api/files/all gives them.
// opts.onPath(path, line) and opts.onUrl(url): what a click does (each optional; without it nothing is linked).
export function linkPaths(text, files, opts = {}) {
  text = String(text ?? "");
  const known = files instanceof Set ? files : new Set(files || []);
  const hits = [];
  if (opts.onUrl) {
    for (const m of text.matchAll(LOCAL_URL)) {
      const url = m[0].replace(/[.,;:!?]+$/, "");
      hits.push({ at: m.index, end: m.index + url.length, url });
    }
  }
  if (opts.onPath && known.size) {
    for (const m of text.matchAll(PATHISH)) {
      const path = m[1].replace(/^\.\//, "");
      if (!known.has(path)) continue;
      const at = m.index + m[0].indexOf(m[1]);
      const end = at + m[1].length + (m[2] ? m[2].length + 1 : 0);
      if (hits.some((x) => at < x.end && end > x.at)) continue;  // inside a web address
      hits.push({ at, end, path, line: m[2] ? Number(m[2]) : 0 });
    }
  }
  if (!hits.length) return [text];
  hits.sort((a, b) => a.at - b.at);
  const out = [];
  let last = 0;
  for (const x of hits) {
    if (x.at < last) continue;
    if (x.at > last) out.push(text.slice(last, x.at));
    const shown = text.slice(x.at, x.end);
    out.push(x.url
      ? h("a", { href: "#", class: "plink", title: "Open this page in the Browser (here in the app)", onclick: (ev) => { ev.preventDefault(); opts.onUrl(x.url); } }, shown)
      : h("a", { href: "#", class: "plink", title: x.line ? `Open ${x.path} at line ${x.line} in Files` : `Open ${x.path} in Files`,
        onclick: (ev) => { ev.preventDefault(); opts.onPath(x.path, x.line); } }, shown));
    last = x.end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// -- Markdown, as GitHub draws it --------------------------------------------------------------------------
const SAFE_LINK = /^(https?:|mailto:)/i;

// opts.picture(relPath) -> a src for a picture inside the project ("" to show its words); opts.onPath(path)
// opens a relative link in Files; opts.base: the Markdown file's folder.
export function gfm(text, opts = {}) {
  highlightStyles();
  previewStyles();
  const box = h("div", { class: "prose md gfm" });
  let lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  if (lines[0] === "---") {  // front matter
    const end = lines.indexOf("---", 1);
    if (end > 0) {
      const rows = lines.slice(1, end).map((l) => l.match(/^([\w .-]+):\s*(.*)$/)).filter(Boolean);
      if (rows.length) box.append(h("div", { class: "md-table" }, h("table", { class: "plain-table gfm-front" },
        h("tbody", {}, rows.map((r) => h("tr", {}, h("th", {}, r[1].trim()), h("td", {}, r[2])))))));
      lines = lines.slice(end + 1);
    }
  }
  block(lines, box, opts);
  return box;
}

function block(lines, box, opts) {
  let para = [];
  const flush = () => { if (para.length) { box.append(h("p", {}, inline(para.join("\n"), opts))); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i], t = line.trim();
    const fence = t.match(/^(`{3,}|~{3,})\s*([\w+#.-]*)/);
    if (fence) {
      flush();
      const code = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith(fence[1]); i++) code.push(lines[i]);
      box.append(h("pre", { class: "log short gfm-code", "data-lang": fence[2] || null }, h("code", {}, highlight(code.join("\n"), fence[2]))));
      continue;
    }
    if (!t) { flush(); continue; }
    const hd = t.match(/^(#{1,6})\s+(.*?)\s*#*$/);
    if (hd) { flush(); box.append(h("h" + Math.min(6, hd[1].length + 1), {}, inline(hd[2], opts))); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t.replace(/\s/g, ""))) { flush(); box.append(h("hr")); continue; }
    if (t.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      flush();
      const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
      const head = cells(line);
      const align = cells(lines[i + 1]).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : null));
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes("|"); i++) rows.push(cells(lines[i]));
      i--;
      const td = (tag, c, k) => h(tag, { style: align[k] ? `text-align: ${align[k]}` : null }, inline(c, opts));
      box.append(h("div", { class: "md-table" }, h("table", { class: "plain-table" },
        h("thead", {}, h("tr", {}, head.map((c, k) => td("th", c, k)))),
        h("tbody", {}, rows.map((r) => h("tr", {}, head.map((_, k) => td("td", r[k] || "", k))))))));
      continue;
    }
    if (t.startsWith(">")) {
      flush();
      const quoted = [];
      for (; i < lines.length && lines[i].trim().startsWith(">"); i++) quoted.push(lines[i].trim().replace(/^>\s?/, ""));
      i--;
      const q = h("blockquote");
      block(quoted, q, opts);
      box.append(q);
      continue;
    }
    if (/^\s*(?:[-*+]|\d+[.)])\s+/.test(line)) {
      flush();
      const items = [];
      for (; i < lines.length; i++) {
        const l = lines[i];
        if (!l.trim()) { if (i + 1 < lines.length && /^\s*(?:[-*+]|\d+[.)])\s+/.test(lines[i + 1])) continue; break; }
        if (!/^\s*(?:[-*+]|\d+[.)])\s+/.test(l) && !/^\s{2,}/.test(l)) break;
        items.push(l);
      }
      i--;
      box.append(list(items, opts));
      continue;
    }
    para.push(t);
  }
  flush();
}

function list(items, opts) {
  const indent = (l) => l.match(/^\s*/)[0].replace(/\t/g, "    ").length;
  const base = indent(items[0]);
  const ordered = /^\s*\d+[.)]/.test(items[0]);
  const start = ordered ? Number(items[0].match(/\d+/)[0]) : null;
  const el = h(ordered ? "ol" : "ul", { start: start && start !== 1 ? String(start) : null });
  let li = null, sub = [];
  const close = () => { if (li && sub.length) li.append(list(sub, opts)); sub = []; };
  for (const l of items) {
    const m = l.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)$/);
    if (m && indent(l) <= base) {
      close();
      const task = m[1].match(/^\[([ xX])\]\s+(.*)$/);
      li = h("li", { class: task ? "gfm-task" : null },
        task ? h("input", { type: "checkbox", checked: task[1] !== " " || null, disabled: true, "aria-label": task[1] !== " " ? "Done" : "Not done" }) : null,
        inline(task ? task[2] : m[1], opts));
      el.append(li);
    } else if (li) {
      if (m) sub.push(l); else li.append(" ", inline(l.trim(), opts));
    }
  }
  close();
  return el;
}

export function inline(s, opts = {}) {
  const out = [];
  const re = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)|\[!\[([^\]]*)\]\([^)]*\)\]\([^)]*\)|\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?])|(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])|(?<![\w_])_([^_\s][^_]*?)_(?![\w_])|\n/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    if (m[0] === "\n") out.push(" ");
    else if (m[1] !== undefined || m[3] !== undefined) {  // a picture (or a badge inside a link)
      const alt = m[1] !== undefined ? m[1] : m[3];
      const src = m[2] || "";
      const local = src && !/^[a-z]+:/i.test(src) && !src.startsWith("//") && opts.picture ? opts.picture(resolve(opts.base, src)) : "";
      out.push(local ? picture(local, alt || src) : h("span", { class: "gfm-pic", title: "Pictures from outside the project aren't loaded here" }, "▣ ", alt || "picture"));
    } else if (m[4] || m[5]) out.push(h("b", {}, inline(m[4] || m[5], opts)));
    else if (m[6]) out.push(h("s", {}, inline(m[6], opts)));
    else if (m[7]) out.push(h("code", {}, m[7]));
    else if (m[8]) {
      const href = m[9];
      if (SAFE_LINK.test(href)) out.push(h("a", { href, target: "_blank", rel: "noopener noreferrer", title: href }, inline(m[8], opts)));
      else if (!/^[a-z]+:/i.test(href) && !href.startsWith("#") && opts.onPath) {
        const path = resolve(opts.base, href.split("#")[0]);
        out.push(h("a", { href: "#", title: `Open ${path} in Files`, onclick: (ev) => { ev.preventDefault(); opts.onPath(path, 0); } }, inline(m[8], opts)));
      } else out.push(inline(m[8], opts));
    } else if (m[10]) out.push(h("a", { href: m[10], target: "_blank", rel: "noopener noreferrer" }, m[10]));
    else if (m[11] || m[12]) out.push(h("i", {}, m[11] || m[12]));
    last = re.lastIndex;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

// a relative link from the Markdown file's folder, kept inside the project ("" when it would leave it)
export function resolve(base, rel) {
  const parts = (rel.startsWith("/") ? [] : String(base || "").split("/").filter(Boolean));
  for (const p of decodeURI(rel).split("/")) {
    if (!p || p === ".") continue;
    if (p === "..") { if (!parts.length) return ""; parts.pop(); } else parts.push(p);
  }
  return parts.join("/");
}

// -- the rich views ------------------------------------------------------------------------------------------
// d: /api/files/preview's answer; opts.raw(file) -> the /raw/pfile address; opts.lang for a notebook's code.
export function richView(d, opts = {}) {
  previewStyles();
  highlightStyles();
  if (d.words && (d.failed || !d.preview)) return h("p", { class: "muted" }, d.words);
  switch (d.preview) {
    case "video": return h("video", { class: "pv-media", controls: true, preload: "metadata", src: opts.raw(d.file), title: d.name });
    case "audio": return h("audio", { class: "pv-audio", controls: true, preload: "metadata", src: opts.raw(d.file), title: d.name });
    case "archive": return archiveView(d);
    case "notebook": return notebookView(d, opts);
    case "office": return officeView(d, opts);
    default: return d.words ? h("p", { class: "muted" }, d.words) : null;
  }
}

function archiveView(d) {
  const shown = d.entries || [];
  return h("div", { class: "pv-archive" },
    h("p", {}, `${plural(d.count, "item")}, ${fileSize(d.total)} when unpacked. Nothing is unpacked to show this list.`),
    d.unsafe ? h("p", { class: "bad small", title: "A name like ../file would land outside the folder it's unpacked into" },
      `${plural(d.unsafe, "name")} would land outside the folder if unpacked: take care with this archive.`) : null,
    h("div", { class: "files-table" }, h("table", { class: "plain-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "Size"))),
      h("tbody", {}, shown.map((e) => h("tr", { class: e.unsafe ? "pv-unsafe" : null },
        h("td", { class: "mono" }, (e.folder ? "📁 " : "") + e.name, e.link ? h("span", { class: "muted" }, " (link)") : null, e.unsafe ? h("span", { class: "bad" }, " ⚠") : null),
        h("td", { class: "muted" }, e.folder ? "" : fileSize(e.size))))))),
    d.more ? h("p", { class: "muted small" }, `And ${plural(d.more, "more item")}, not listed.`) : null);
}

function notebookView(d, opts) {
  return h("div", { class: "pv-nb" },
    (d.cells || []).map((c) => h("div", { class: "pv-cell pv-" + c.type },
      c.type === "markdown" ? gfm(c.source, opts)
        : h("div", { class: "pv-in" },
          h("span", { class: "pv-count muted small", title: "The order this cell was last run in" }, c.type === "code" ? `[${c.count ?? " "}]` : ""),
          h("pre", { class: "log short" }, h("code", {}, c.type === "code" ? highlight(c.source, d.language) : c.source))),
      (c.outputs || []).map((o) => o.kind === "image"
        ? h("div", { class: "pv-out" }, h("img", { src: `data:${o.mime};base64,${o.data}`, alt: "A picture this cell made", class: "pv-img" }))
        : h("pre", { class: "log short pv-out" + (o.kind === "error" ? " bad" : "") }, o.text)))),
    d.more ? h("p", { class: "muted small" }, `And ${plural(d.more, "more cell")}, not shown.`) : null,
    h("p", { class: "muted small" }, "A notebook is shown as it was saved: it isn't run here."));
}

function runs(rs) { return (rs || []).map((r) => (r.bold && r.italic ? h("b", {}, h("i", {}, r.text)) : r.bold ? h("b", {}, r.text) : r.italic ? h("i", {}, r.text) : r.text)); }

function table(rows) {
  if (!rows || !rows.length) return h("p", { class: "muted" }, "This table is empty.");
  const width = Math.max(...rows.map((r) => r.length));
  const [head, ...rest] = rows;
  return h("div", { class: "md-table files-table" }, h("table", { class: "plain-table" },
    h("thead", {}, h("tr", {}, Array.from({ length: width }, (_, k) => h("th", {}, head[k] || "")))),
    h("tbody", {}, rest.map((r) => h("tr", {}, Array.from({ length: width }, (_, k) => h("td", {}, r[k] || "")))))));
}

function officeView(d, opts) {
  const pdf = opts.asPdf && d.can_pdf ? h("button", { type: "button", title: "Shows the file exactly as it looks, made into a PDF by LibreOffice on this computer", onclick: (ev) => opts.asPdf(ev.currentTarget) }, "Open as PDF") : null;
  const head = h("div", { class: "row pv-office-head" }, h("span", { class: "muted small grow" }, d.pdf_words || "A simple view: the text and tables, without the look."), pdf);
  let main = null;
  if (d.office === "docx") {
    main = h("div", { class: "prose md" }, (d.blocks || []).map((b) =>
      b.type === "heading" ? h("h" + Math.min(6, b.level + 1), {}, b.text)
        : b.type === "list" ? h(b.ordered ? "ol" : "ul", {}, b.items.map((it) => h("li", {}, runs(it))))
          : b.type === "table" ? table(b.rows) : h("p", { class: "pre-line" }, runs(b.runs))));
  } else if (d.office === "xlsx") {
    const sheets = d.sheets || [];
    const body = h("div");
    const show = (k) => fill(body, table(sheets[k].rows), sheets[k].cut ? h("p", { class: "muted small" }, "Only the first 500 rows and 60 columns are shown.") : null);
    const tabs = sheets.length > 1 ? h("div", { class: "row pv-sheets", role: "tablist" }, sheets.map((s, k) =>
      h("button", { type: "button", role: "tab", onclick: (ev) => { for (const b of ev.currentTarget.parentNode.children) b.removeAttribute("aria-selected"); ev.currentTarget.setAttribute("aria-selected", "true"); show(k); }, "aria-selected": k === 0 ? "true" : null }, s.name))) : null;
    if (sheets.length) show(0); else fill(body, h("p", { class: "muted" }, "This workbook has no sheets."));
    main = h("div", {}, tabs, body);
  } else if (d.office === "pptx") {
    main = h("ol", { class: "pv-slides" }, (d.slides || []).map((s) => h("li", { class: "pv-slide" },
      h("b", {}, s.title || "(no title)"), s.lines.length ? h("ul", {}, s.lines.map((l) => h("li", {}, l))) : null)));
  }
  return h("div", { class: "pv-office" }, head, main);
}

// -- find in a text preview -------------------------------------------------------------------------------------
// target: the element showing the text; draw(nodes) puts nodes in it; text(): the plain text; plain(): back to normal
export function findBar(text, draw, plain) {
  previewStyles();
  let hits = [], at = -1;
  const count = h("span", { class: "muted small", "aria-live": "polite" });
  const field = h("input", { type: "search", class: "grow", placeholder: "Find in this file", "aria-label": "Find in this file" });
  const go = (step) => {
    if (!hits.length) return;
    if (at >= 0) hits[at].classList.remove("fx-now");
    at = (at + step + hits.length) % hits.length;
    hits[at].classList.add("fx-now");
    hits[at].scrollIntoView({ block: "center" });
    count.textContent = `${at + 1} of ${hits.length}`;
  };
  const run = () => {
    const q = field.value;
    at = -1;
    if (!q) { hits = []; count.textContent = ""; plain(); return; }
    const t = text(), low = t.toLowerCase(), ql = q.toLowerCase(), nodes = [];
    hits = [];
    let last = 0, i;
    while ((i = low.indexOf(ql, last)) >= 0 && hits.length < 5000) {
      if (i > last) nodes.push(t.slice(last, i));
      const mark = h("mark", { class: "fx-hit" }, t.slice(i, i + q.length));
      hits.push(mark);
      nodes.push(mark);
      last = i + q.length;
    }
    nodes.push(t.slice(last));
    draw(nodes);
    count.textContent = hits.length ? "" : "Not found";
    go(1);
  };
  field.addEventListener("input", run);
  field.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); go(ev.shiftKey ? -1 : 1); }
    if (ev.key === "Escape") { field.value = ""; run(); }
  });
  return h("div", { class: "row fx-bar" }, field, count,
    h("button", { type: "button", title: "The one before (Shift+Enter)", onclick: () => go(-1) }, "↑"),
    h("button", { type: "button", title: "The next one (Enter)", onclick: () => go(1) }, "↓"));
}

export function previewStyles() {
  if (typeof document === "undefined" || document.getElementById("pv-style")) return;
  document.head.append(h("style", { id: "pv-style" }, `
.plink { color: var(--color-accent); text-decoration: underline dotted; }
.gfm h2, .gfm h3, .gfm h4, .gfm h5, .gfm h6, .gfm h7 { margin: 16px 0 8px; }
.gfm-task { list-style: none; margin-left: -1.2em; }
.gfm-task input { margin-right: 6px; }
.gfm-pic { color: var(--color-muted); border: 1px dashed var(--color-line-strong); border-radius: var(--radius-small); padding: 0 6px; font-size: 13px; }
.gfm-front th { color: var(--color-muted); font-weight: 600; text-align: left; }
.gfm-code { white-space: pre; overflow-x: auto; }
.pv-media { width: 100%; max-height: 62vh; background: var(--color-shade); border-radius: var(--radius-small); }
.pv-audio { width: 100%; }
.pv-unsafe td { background: var(--color-bad-soft); }
.pv-nb { display: flex; flex-direction: column; gap: 12px; max-height: 70vh; overflow: auto; }
.pv-cell { border-left: 3px solid var(--color-line); padding-left: 10px; }
.pv-code { border-left-color: var(--color-accent-soft); }
.pv-in { display: flex; gap: 8px; align-items: flex-start; }
.pv-in pre { flex: 1; min-width: 0; margin: 0; }
.pv-count { font-family: var(--font-mono); min-width: 3em; padding-top: 6px; }
.pv-out { margin: 6px 0 0 3.5em; }
.pv-img { max-width: 100%; background: var(--color-paper); border-radius: var(--radius-small); }
.pv-office { display: flex; flex-direction: column; gap: 10px; max-height: 70vh; overflow: auto; }
.pv-office-head { gap: 8px; align-items: center; }
.pv-sheets { gap: 4px; flex-wrap: wrap; margin-bottom: 8px; }
.pv-sheets [aria-selected="true"] { background: var(--color-accent-soft); border-color: var(--color-accent); }
.pv-slides { display: flex; flex-direction: column; gap: 8px; padding-left: 1.5em; }
.pv-slide { border: 1px solid var(--color-line); border-radius: var(--radius-small); padding: 8px 12px; }
.fx-bar { gap: 6px; align-items: center; margin: 0 0 8px; }
.fx-hit { background: var(--color-warn-soft); color: var(--color-text); border-radius: 2px; }
.fx-hit.fx-now { outline: 2px solid var(--color-warn); }
`));
}
