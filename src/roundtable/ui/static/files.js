// The Files tab of a project's page: its folder to browse, any file to open (text and code lightly coloured,
// markdown drawn, CSV as a table, JSON folded, pictures, PDFs in the browser's own viewer), Save a copy, and the
// commands its tasks ran, each with its exit code and its output folded, plus "Run the tests".
// Everything is built with h() as text: a file's contents are never run or read as HTML. API: ui/filesapi.py.
import { BRAND, h, fill, get, post, q, every, card, toast, act, ago, fileSize, plural, picture, markdown } from "./core.js";

const pfile = (path, file, download) => "/raw/pfile?" + q({ path, file, download: download ? "1" : "" });
const ICONS = { folder: "📁", image: "🖼", pdf: "📄", markdown: "📝", csv: "▦", json: "{ }", code: "</>", text: "≡", other: "•" };
const KIND_WORDS = { image: "Picture", pdf: "PDF", markdown: "Document", csv: "Table", json: "Data (JSON)", code: "Code", text: "Text", other: "File" };

export async function filesTab(seat, now) {
  if (!seat.path) {  // built on another machine: say where its files are
    let d = null;
    try { d = await get(`/api/files?${q({ name: seat.hub_name || seat.id })}`); } catch { /* the words below */ }
    return card("Files", h("p", {}, (d && d.words) || `This project's files aren't on this computer. Open ${BRAND.name} on the computer that builds it.`));
  }
  const path = seat.path;
  const list = h("div", { class: "files-list" }, h("p", { class: "muted" }, "Loading…"));
  const view = h("div", { class: "files-view" }, viewerEmpty());
  const log = h("div");
  const box = h("div", { class: "stack" },
    h("section", { class: "card files-card" },
      h("div", { class: "card-head" }, h("h2", {}, "Files"),
        h("span", { class: "muted small", title: "Hidden files, keys and the harness's own records are never shown" }, "Read only")),
      h("div", { class: "files-split" }, list, view)),
    log);
  const open = async (dir) => {
    try { drawList(await get(`/api/files?${q({ path, dir })}`)); } catch (e) { fill(list, h("p", { class: "bad" }, e.message)); }
  };
  const drawList = (d) => {
    if (!d.here) return fill(list, h("p", {}, d.words));
    fill(list,
      h("nav", { class: "crumbs", "aria-label": "Where you are in the project" },
        d.crumbs.map((c, i) => [i ? h("span", { class: "muted" }, " / ") : null,
          i === d.crumbs.length - 1 ? h("b", {}, c.name) : h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); open(c.dir); } }, c.name)])),
      d.items.length ? h("ul", { class: "files-items" }, d.items.map((it) => h("li", {},
        h("button", { class: "file-row", type: "button", title: it.folder ? "Open this folder" : `Open ${it.name}`,
          onclick: () => (it.folder ? open(it.path) : showFile(path, it, view)) },
          h("span", { class: "file-ic", "aria-hidden": "true" }, ICONS[it.kind] || "•"),
          h("span", { class: "grow" }, it.name),
          it.folder ? null : h("span", { class: "muted small" }, fileSize(it.size))))))
        : h("p", { class: "muted" }, "This folder is empty."),
      d.more ? h("p", { class: "muted small" }, `And ${plural(d.more, "more file")}, not shown.`) : null);
  };
  open("");
  commandLog(path, now, log);
  return box;
}

function viewerEmpty() {
  return h("div", { class: "empty" }, h("p", {}, "Pick a file to open it here."));
}

async function showFile(path, it, view) {
  fill(view, h("p", { class: "muted" }, "Opening…"));
  let f;
  try { f = await get(`/api/files/open?${q({ path, file: it.path })}`); } catch (e) { fill(view, h("p", { class: "bad" }, e.message)); return; }
  const head = h("div", { class: "files-view-head" },
    h("div", { class: "grow" }, h("h3", {}, f.name), h("p", { class: "muted small" }, [KIND_WORDS[f.kind] || "File", fileSize(f.size), f.file].join(" · "))),
    h("a", { class: "btn", href: pfile(path, f.file, true), download: f.name, title: "Save a copy of this file on this computer" }, "Save a copy"));
  fill(view, head, f.words ? h("p", { class: "muted" }, f.words) : null, f.too_big ? null : body(path, f));
}

function body(path, f) {
  switch (f.kind) {
    case "image": return h("div", { class: "files-pic" }, picture(pfile(path, f.file), f.name));
    case "pdf": return [h("iframe", { class: "files-pdf", src: pfile(path, f.file), title: f.name }),
      h("p", { class: "muted small" }, "If the PDF doesn't show, press Save a copy and open it from there.")];
    case "markdown": return markdown(f.text);
    case "csv": return csvTable(f.rows || []);
    case "json": return jsonTree(f.text);
    case "code": case "text": return codeView(f.text || "", f.kind === "code" ? f.lang : "");
    default: return null;
  }
}

function csvTable(rows) {
  if (!rows.length) return h("p", { class: "muted" }, "This table is empty.");
  const [head, ...rest] = rows;
  return h("div", { class: "md-table files-table" }, h("table", { class: "plain-table" },
    h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, c)))),
    h("tbody", {}, rest.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
}

// JSON as a tree: the top level open, everything deeper folded
export function jsonTree(text) {
  let v;
  try { v = JSON.parse(text); } catch { return codeView(text, "json"); }
  let budget = 4000;
  const node = (key, val, depth) => {
    const label = key === null ? null : h("span", { class: "hl-k" }, JSON.stringify(key), ": ");
    if (val === null || typeof val !== "object") {
      const cls = typeof val === "string" ? "hl-s" : typeof val === "number" ? "hl-n" : "hl-k";
      return h("div", { class: "jt-leaf" }, label, h("span", { class: cls }, JSON.stringify(val)));
    }
    const arr = Array.isArray(val), keys = arr ? val.map((_, i) => i) : Object.keys(val);
    const sum = arr ? `[ ${plural(keys.length, "item")} ]` : `{ ${plural(keys.length, "field")} }`;
    if (--budget < 0) return h("div", { class: "jt-leaf muted" }, label, sum);
    return h("details", { class: "jt", open: depth === 0 || null }, h("summary", {}, label, h("span", { class: "muted" }, sum)),
      h("div", { class: "jt-kids" }, keys.map((k) => node(arr ? null : k, val[k], depth + 1))));
  };
  return h("div", { class: "jt-root mono" }, node(null, v, 0));
}

// -- light colouring of code: comments, strings, numbers and keywords; text nodes only --------------------
const KEYWORDS = new Set(("and as async await break case catch class const continue def default del do elif else enum export extends "
  + "false final finally fn for from fun func function if import in interface is lambda let match new nil none not null "
  + "object or package pass private protected public raise return self static struct super switch this throw true try "
  + "type typeof val var void when while with yield True False None").split(" "));
const HASH = new Set(["python", "shell", "yaml", "toml", "ruby", "gdscript", "powershell", "ini"]);
const TOKEN = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->|#[^\n]*|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g;

export function highlight(text, lang) {
  if (!lang || text.length > 300_000) return [text];
  const out = [];
  let last = 0, m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(text))) {
    const t = m[0], c = t[0];
    let cls = null;
    const skip = (c === "#" && !HASH.has(lang)) || (t.startsWith("//") && HASH.has(lang));
    if (skip) { TOKEN.lastIndex = m.index + 1; continue; }  // not a comment in this language: look inside it
    if (c === "#") cls = "hl-c";
    else if (t.startsWith("//") || t.startsWith("/*") || t.startsWith("<!--")) cls = "hl-c";
    else if (c === '"' || c === "'" || c === "`") cls = "hl-s";
    else if (/\d/.test(c)) cls = "hl-n";
    else if (KEYWORDS.has(t)) cls = "hl-k";
    if (!cls) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(h("span", { class: cls }, t));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function codeView(text, lang) {
  const lines = text.split("\n").length;
  return h("pre", { class: "log files-code", "data-lines": lines, tabindex: "0" }, h("code", {}, highlight(text, lang)));
}

// -- the command log ------------------------------------------------------------------------------
const KIND_WHO = { task: "", checks: "Checks", baseline: "Checks", setup: "Set-up", tests: "You" };

function commandLog(path, now, box) {
  let sig = "";
  const draw = async () => {
    const d = await get(`/api/files/log?${q({ path })}`);
    if (!d.here) return fill(box, card("Commands it ran", h("p", {}, d.words)));
    const s = JSON.stringify([d.commands.length, d.commands[0] && d.commands[0].at, d.can_run, d.why_not]);
    if (s === sig) return;
    sig = s;
    const failed = d.commands.filter((c) => c.passed === false).length;
    const runBtn = d.test_command
      ? h("button", { class: "primary", disabled: !d.can_run || null, title: d.can_run ? `Runs the project's own test command: ${d.test_command}` : d.why_not,
        onclick: (ev) => act(ev.currentTarget, async () => {
          const job = await post("/api/files/run_tests", { path });
          followTests(job, box, () => { sig = ""; draw(); });
          return job;
        }, "Running the tests: the result shows here") }, "Run the tests")
      : null;
    fill(box, h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Commands it ran"), runBtn),
      h("p", {}, d.commands.length
        ? `${plural(d.commands.length, "command")}` + (failed ? `, ${failed} didn't work.` : ", all worked.") + " Open one to see its output."
        : "No commands yet: they show here as the tasks run them."),
      d.test_command ? null : h("p", { class: "muted small" }, d.why_not),
      h("div", { class: "cmd-log" }, d.commands.map(commandRow))));
  };
  return every(box, draw, () => (now().status === "running" ? 5000 : 20000));
}

function commandRow(c) {
  const mark = c.passed === true ? h("span", { class: "good", title: "It worked" }, "✓") : c.passed === false ? h("span", { class: "bad", title: "It didn't work" }, "✗") : h("span", { class: "muted" }, "·");
  const who = KIND_WHO[c.kind] || (c.who === "reviewer" ? "Reviewer" : "");
  const task = c.task ? `${c.task}${c.task_title ? " " + c.task_title : ""}` : "";
  return h("details", { class: "cmd" },
    h("summary", { title: c.at ? new Date(c.at).toLocaleString() : "" }, mark, " ", h("code", {}, c.command || "(no command)"),
      h("span", { class: "muted small" }, " · ", [c.words, who, task, c.at ? ago(c.at) : ""].filter(Boolean).join(" · "))),
    c.output ? h("pre", { class: "log short" }, c.output) : h("p", { class: "muted small" }, "No output was kept."));
}

async function followTests(job, box, done) {
  if (!job || !job.id) return;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    let j;
    try { j = await get(`/api/jobs/${encodeURIComponent(job.id)}`); } catch (e) { toast(e.message, true); return; }
    if (j.status !== "running") {
      toast((j.result && j.result.words) || j.error || "Finished.", j.status !== "done" || !(j.result && j.result.ok));
      return done();
    }
    if (!box.isConnected) return;
  }
}

