// The Files tab of a project's page, in three parts:
//  - Files: the project's folder to browse and any file to open (code coloured, Markdown as GitHub draws it, CSV
//    as a table, JSON folded, pictures, PDFs, notebooks, archives, Word, Excel and PowerPoint, video and sound),
//    Find in the file, Save a copy, and Change for any text file (editor.js), with Your edits to put one back.
//  - History: the project's git history, each change with its files and lines (gitlog.js).
//  - Browser: pages the project started on this computer, view only (browser.js).
// Below, the commands its tasks ran, each with its exit code and output, plus "Run the tests".
// Other pages open a file or a page here with openInFiles / openInBrowser, or link words with pathLinker.
// Everything is built with h() as text: a file's contents are never run or read as HTML. API: ui/filesapi.py,
// ui/editapi.py.
import { BRAND, h, fill, get, post, q, every, card, toast, act, ago, fileSize, plural, picture, has, seg, projectHref } from "./core.js";
import { highlight as colour, highlightStyles } from "./highlight.js";
import { gfm, linkPaths, richView, findBar, previewStyles } from "./preview.js";
import { openEditor, editsList } from "./editor.js";
import { historyView } from "./gitlog.js";
import { browserView } from "./browser.js";

const pfile = (path, file, download) => "/raw/pfile?" + q({ path, file, download: download ? "1" : "" });
const ICONS = { folder: "📁", image: "🖼", pdf: "📄", markdown: "📝", csv: "▦", json: "{ }", code: "</>", text: "≡", other: "•",
  notebook: "📓", archive: "🗜", office: "📄", video: "🎞", audio: "♪" };
const KIND_WORDS = { image: "Picture", pdf: "PDF", markdown: "Document", csv: "Table", json: "Data (JSON)", code: "Code", text: "Text", other: "File",
  notebook: "Notebook", archive: "Archive", office: "Office file", video: "Video", audio: "Sound" };
const EDITABLE = new Set(["text", "code", "markdown", "csv", "json"]);

// -- opening from elsewhere ---------------------------------------------------------------------------------
const pending = new Map();  // project id -> {part, file, line, url}
function request(seat, ask) {
  const id = seat.id || seat;
  pending.set(id, ask);
  const href = projectHref(id, "files");
  if (location.hash.split("?")[0] === href) window.dispatchEvent(new CustomEvent("rt-files-open", { detail: { id } }));
  else location.hash = href;
}
export const openInFiles = (seat, file, line = 0) => request(seat, { part: "files", file, line });
export const openInBrowser = (seat, url) => request(seat, { part: "browser", url });

// pathLinker(seat) -> (text) => nodes: paths that exist in the project link to Files, local addresses to the Browser
const known = new Map();  // project path -> {at, files}
export async function pathLinker(seat) {
  const plain = (text) => [String(text ?? "")];
  if (!seat || !seat.path || !(await has("/api/files/all"))) return plain;
  let k = known.get(seat.path);
  if (!k || Date.now() - k.at > 60_000) {
    try { k = { at: Date.now(), files: new Set((await get(`/api/files/all?${q({ path: seat.path })}`)).files) }; known.set(seat.path, k); }
    catch { return plain; }
  }
  return (text) => linkPaths(text, k.files, { onPath: (p, l) => openInFiles(seat, p, l), onUrl: (u) => openInBrowser(seat, u) });
}

// -- the tab ---------------------------------------------------------------------------------------------------
export async function filesTab(seat, now) {
  if (!seat.path) {  // built on another machine: say where its files are
    let d = null;
    try { d = await get(`/api/files?${q({ name: seat.hub_name || seat.id })}`); } catch { /* the words below */ }
    return card("Files", h("p", {}, (d && d.words) || `This project's files aren't on this computer. Open ${BRAND.name} on the computer that builds it.`));
  }
  highlightStyles();
  previewStyles();
  filesStyles();
  const path = seat.path;
  const editing = await has("/api/files/save");
  const parts = [["files", "Files", "The project's folder and its files"]];
  if (await has("/api/git/log")) parts.push(["history", "History", "Every change to the project, newest first"]);
  if (await has("/api/browser")) parts.push(["browser", "Browser", "Pages the project started on this computer, shown here"]);
  const main = h("div");
  const filesPart = filesBrowser(seat, editing);
  let historyPart = null, browserPart = null, part = "files";
  const segBox = h("div");
  const show = (p) => {
    part = p;
    if (p === "history") fill(main, historyPart || (historyPart = historyView(path)));
    else if (p === "browser") fill(main, browserPart || (browserPart = browserView(path)));
    else fill(main, filesPart.box);
  };
  const drawSeg = () => fill(segBox, parts.length > 1 ? seg(parts, part, show, "Which part of the files") : null);
  const log = h("div");
  const box = h("div", { class: "stack" },
    h("section", { class: "card files-card" },
      h("div", { class: "card-head" }, h("h2", {}, "Files"), segBox,
        h("span", { class: "muted small", title: "Hidden files, keys and the harness's own records are never shown or changed" },
          editing ? "Keys and hidden files stay private" : "Read only")),
      main),
    log);
  const take = () => {
    const ask = pending.get(seat.id);
    if (!ask) return;
    pending.delete(seat.id);
    if (ask.part === "browser" && parts.some(([k]) => k === "browser")) {
      show("browser");
      browserPart.open(ask.url);
    } else if (ask.file) {
      show("files");
      filesPart.openPath(ask.file, ask.line);
    }
    drawSeg();
  };
  const onAsk = (ev) => {
    if (!box.isConnected) { window.removeEventListener("rt-files-open", onAsk); return; }
    if (ev.detail && ev.detail.id === seat.id) take();
  };
  window.addEventListener("rt-files-open", onAsk);
  show("files");
  drawSeg();
  take();
  commandLog(seat, now, log);
  return box;
}

// -- the folder and one file ------------------------------------------------------------------------------------
function filesBrowser(seat, editing) {
  const path = seat.path;
  const list = h("div", { class: "files-list" }, h("p", { class: "muted" }, "Loading…"));
  const view = h("div", { class: "files-view" }, viewerEmpty());
  const edits = h("div");
  const box = h("div", {}, h("div", { class: "files-split" }, list, view), edits);
  let current = null;  // the open file, so a save can show it again
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
          onclick: () => (it.folder ? open(it.path) : showFile(it.path)) },
          h("span", { class: "file-ic", "aria-hidden": "true" }, ICONS[it.preview] || ICONS[it.kind] || "•"),
          h("span", { class: "grow" }, it.name),
          it.folder ? null : h("span", { class: "muted small" }, fileSize(it.size))))))
        : h("p", { class: "muted" }, "This folder is empty."),
      d.more ? h("p", { class: "muted small" }, `And ${plural(d.more, "more file")}, not shown.`) : null);
  };
  const refreshEdits = () => (editing ? editsList(edits, path, (file) => { if (current === file) showFile(file); }) : null);

  async function showFile(file, line = 0) {
    current = file;
    fill(view, h("p", { class: "muted" }, "Opening…"));
    let f;
    try { f = await get(`/api/files/open?${q({ path, file })}`); } catch (e) { fill(view, h("p", { class: "bad" }, e.message)); return; }
    const canEdit = editing && EDITABLE.has(f.kind) && !f.too_big && typeof f.text === "string" && !f.preview;
    const textual = typeof f.text === "string" && !f.too_big && !f.preview;
    const content = h("div", { class: "files-body" });
    const findSlot = h("div");
    const head = h("div", { class: "files-view-head" },
      h("div", { class: "grow" }, h("h3", {}, f.name),
        h("p", { class: "muted small" }, [KIND_WORDS[f.preview] || KIND_WORDS[f.kind] || "File", fileSize(f.size), f.file].join(" · "))),
      textual ? h("button", { type: "button", title: "Find words in this file", onclick: () => toggleFind() }, "Find") : null,
      canEdit ? h("button", { type: "button", class: "primary", title: "Change this file here. Each save can be put back.",
        onclick: () => openEditor(view, { path, file: f.file, line, onDone: (changed) => { showFile(f.file); if (changed) refreshEdits(); } }) }, "Change") : null,
      h("a", { class: "btn", href: pfile(path, f.file, true), download: f.name, title: "Save a copy of this file on this computer" }, "Save a copy"));
    const toggleFind = () => {
      if (findSlot.firstChild) { fill(findSlot); fill(content, body(path, f, line, (p) => showFile(p))); return; }
      const draw = (nodes) => fill(content, h("pre", { class: "log files-code" }, h("code", {}, nodes)));
      fill(findSlot, findBar(() => f.text, draw, () => fill(content, body(path, f, line, (p) => showFile(p)))));
      findSlot.querySelector("input").focus();
    };
    fill(view, head, findSlot, f.words && !f.preview ? h("p", { class: "muted" }, f.words) : null, content);
    if (f.preview) {
      fill(content, h("p", { class: "muted" }, "Opening…"));
      let d;
      try { d = await get(`/api/files/preview?${q({ path, file: f.file })}`); }
      catch (e) { fill(content, h("p", { class: "bad" }, e.message)); return; }
      fill(content, richView(d, { raw: (p) => pfile(path, p), lang: d.language, picture: (p) => (p ? pfile(path, p) : ""),
        onPath: (p, l) => showFile(p, l), base: dirOf(f.file), asPdf: (btn) => officePdf(path, f, content, btn) }));
    } else if (!f.too_big) fill(content, body(path, f, line, (p) => showFile(p)));
    if (line && content.querySelector(".fv-code")) jumpTo(content.querySelector(".fv-code"), line);
  }
  open("");
  refreshEdits();
  return { box, openPath: (file, line) => { open(dirOf(file)); showFile(file, line); } };
}

const dirOf = (file) => String(file || "").split("/").slice(0, -1).join("/");

async function officePdf(path, f, content, btn) {
  await act(btn, async () => {
    let job = await post("/api/files/as_pdf", { path, file: f.file });
    for (let i = 0; i < 120 && job.status === "running"; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      job = await get(`/api/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status !== "done") throw new Error(job.error || "The PDF couldn't be made. Save a copy to open it instead.");
    fill(content, h("iframe", { class: "files-pdf", src: "/raw/officepdf?" + q({ path, file: f.file }), title: f.name }),
      h("p", { class: "muted small" }, "Made by LibreOffice on this computer. If it doesn't show, press Save a copy and open it from there."));
    return job;
  });
}

function viewerEmpty() {
  return h("div", { class: "empty" }, h("p", {}, "Pick a file to open it here."));
}

function body(path, f, line, onPath) {
  switch (f.kind) {
    case "image": return h("div", { class: "files-pic" }, picture(pfile(path, f.file), f.name));
    case "pdf": return [h("iframe", { class: "files-pdf", src: pfile(path, f.file), title: f.name }),
      h("p", { class: "muted small" }, "If the PDF doesn't show, press Save a copy and open it from there.")];
    case "markdown": return gfm(f.text, { picture: (p) => (p ? pfile(path, p) : ""), base: dirOf(f.file), onPath });
    case "csv": return csvTable(f.rows || []);
    case "json": return jsonTree(f.text);
    case "code": case "text": return codeView(f.text || "", f.kind === "code" ? f.lang : "", line);
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

// the colouring lives in highlight.js now; kept here under its old name for anything that imported it
export const highlight = colour;

function codeView(text, lang, line = 0) {
  const n = text.split("\n").length;
  const view = h("div", { class: "fv-code", tabindex: "0" },
    h("pre", { class: "fv-gutter", "aria-hidden": "true" }, Array.from({ length: n }, (_, i) => i + 1).join("\n")),
    h("pre", { class: "fv-text" }, h("code", {}, colour(text, lang))),
    h("div", { class: "fv-mark", hidden: true }));
  if (line) setTimeout(() => jumpTo(view, line), 0);
  return view;
}

function jumpTo(view, line) {
  const pre = view.querySelector(".fv-text"), mark = view.querySelector(".fv-mark");
  if (!pre || !mark) return;
  const lh = parseFloat(getComputedStyle(pre).lineHeight) || 19;
  const top = (line - 1) * lh + (parseFloat(getComputedStyle(pre).paddingTop) || 0);
  mark.hidden = false;
  mark.style.top = `${top}px`;
  mark.style.height = `${lh}px`;
  view.scrollTop = Math.max(0, top - view.clientHeight / 3);
}

// -- the command log ------------------------------------------------------------------------------
const KIND_WHO = { task: "", checks: "Checks", baseline: "Checks", setup: "Set-up", tests: "You" };

function commandLog(seat, now, box) {
  const path = seat.path;
  let sig = "", link = (t) => [t], linked = false;
  pathLinker(seat).then((fn) => { link = fn; linked = true; sig = ""; }).catch(() => {});
  const draw = async () => {
    const d = await get(`/api/files/log?${q({ path })}`);
    if (!d.here) return fill(box, card("Commands it ran", h("p", {}, d.words)));
    const s = JSON.stringify([d.commands.length, d.commands[0] && d.commands[0].at, d.can_run, d.why_not, linked]);
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
      h("div", { class: "cmd-log" }, d.commands.map((c) => commandRow(c, link)))));
  };
  return every(box, draw, () => (now().status === "running" ? 5000 : 20000));
}

function commandRow(c, link) {
  const mark = c.passed === true ? h("span", { class: "good", title: "It worked" }, "✓") : c.passed === false ? h("span", { class: "bad", title: "It didn't work" }, "✗") : h("span", { class: "muted" }, "·");
  const who = KIND_WHO[c.kind] || (c.who === "reviewer" ? "Reviewer" : "");
  const task = c.task ? `${c.task}${c.task_title ? " " + c.task_title : ""}` : "";
  return h("details", { class: "cmd" },
    h("summary", { title: c.at ? new Date(c.at).toLocaleString() : "" }, mark, " ", h("code", {}, c.command || "(no command)"),
      h("span", { class: "muted small" }, " · ", [c.words, who, task, c.at ? ago(c.at) : ""].filter(Boolean).join(" · "))),
    c.output ? h("pre", { class: "log short" }, link(c.output)) : h("p", { class: "muted small" }, "No output was kept."));
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

function filesStyles() {
  if (typeof document === "undefined" || document.getElementById("fv-style")) return;
  document.head.append(h("style", { id: "fv-style" }, `
.files-card .card-head { gap: 12px; flex-wrap: wrap; }
.fv-code { position: relative; display: flex; max-height: 62vh; overflow: auto; border-radius: var(--radius-small); background: var(--color-sunken); font: 13px/1.5 var(--font-mono); }
.fv-gutter, .fv-text { margin: 0; padding: 8px; white-space: pre; font: inherit; background: none; }
.fv-gutter { color: var(--color-muted); text-align: right; user-select: none; border-right: 1px solid var(--color-line); position: sticky; left: 0; background: var(--color-sunken); }
.fv-text { flex: 1; tab-size: 4; }
.fv-mark { position: absolute; left: 0; right: 0; background: var(--color-accent-soft); opacity: 0.6; pointer-events: none; }
`));
}
