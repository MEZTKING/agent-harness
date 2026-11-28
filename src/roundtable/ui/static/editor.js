// Change a file from the Files tab: a plain text area with line numbers, find (Ctrl+F), tab handling and
// Ctrl+S, in our own code (no Monaco: the app has no build step and loads nothing from outside).
// Saving goes through /api/files/save (ui/editapi.py): refused when the file changed since it was opened (both
// versions are shown), asks first while a task is building that file, and every save can be put back.
import { h, fill, get, post, q, toast, dialog, act, ago } from "./core.js";
import { t as wt } from "./words.js";

// openEditor(box, {path, file, line, onDone}) draws the editor into box. onDone(saved) when it's closed.
export async function openEditor(box, { path, file, line = 0, onDone = () => {} }) {
  editorStyles();
  fill(box, h("p", { class: "muted" }, "Opening for changes…"));
  let d;
  try { d = await get(`/api/files/edit?${q({ path, file })}`); } catch (e) { fill(box, h("p", { class: "bad" }, e.message)); return; }
  if (d.elsewhere) { fill(box, h("p", { class: "bad" }, d.elsewhere)); return; }
  let base = d.base, saved = d.text, dirty = false, closed = false;
  const indent = /^\t/m.test(d.text) ? "\t" : (d.text.match(/^( {2,4})\S/m) || [, "    "])[1];
  const area = h("textarea", { class: "ed-area", spellcheck: "false", wrap: "off", "aria-label": wt("The text of {name}", { name: d.name }), autocomplete: "off" });
  area.value = d.text;
  const gutter = h("div", { class: "ed-gutter", "aria-hidden": "true" });
  const state = h("span", { class: "muted small grow", "aria-live": "polite" });
  const findField = h("input", { type: "search", placeholder: "Find", "aria-label": "Find in this file", class: "ed-find" });
  const findCount = h("span", { class: "muted small" });
  const findRow = h("div", { class: "row ed-findrow", hidden: true }, findField, findCount,
    h("button", { type: "button", title: "The one before (Shift+Enter)", onclick: () => find(-1) }, "↑"),
    h("button", { type: "button", title: "The next one (Enter)", onclick: () => find(1) }, "↓"),
    h("button", { type: "button", title: "Close find (Esc)", onclick: () => closeFind() }, "✕"));
  const saveBtn = h("button", { class: "primary", type: "button", title: "Save your changes (Ctrl+S). Each save can be put back from Your edits." }, "Save");
  const closeBtn = h("button", { type: "button", title: "Stop changing this file" }, "Done");
  const notice = h("div");

  const lines = () => {
    const n = area.value.split("\n").length;
    if (gutter._n !== n) { gutter._n = n; gutter.textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n"); }
    gutter.scrollTop = area.scrollTop;
  };
  const mark = () => {
    dirty = area.value !== saved;
    state.textContent = dirty ? "Changed, not saved yet" : "Saved";
    saveBtn.disabled = !dirty || null;
  };
  area.addEventListener("input", () => { lines(); mark(); });
  area.addEventListener("scroll", () => { gutter.scrollTop = area.scrollTop; });

  // tab and shift+tab indent the chosen lines; Enter keeps the line's indent
  area.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") { ev.preventDefault(); save(false); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "f") { ev.preventDefault(); openFind(); return; }
    if (ev.key === "Escape" && !findRow.hidden) { ev.preventDefault(); closeFind(); return; }
    if (ev.key === "Tab" && !ev.ctrlKey && !ev.altKey) { ev.preventDefault(); tab(area, indent, ev.shiftKey); lines(); mark(); return; }
    if (ev.key === "Enter" && !ev.shiftKey && !ev.ctrlKey) {
      const s = area.selectionStart, start = area.value.lastIndexOf("\n", s - 1) + 1;
      const lead = area.value.slice(start, s).match(/^[ \t]*/)[0];
      if (lead) { ev.preventDefault(); insert(area, "\n" + lead); lines(); mark(); }
    }
  });

  let hits = [], at = -1;
  function openFind() { findRow.hidden = false; const sel = area.value.slice(area.selectionStart, area.selectionEnd); if (sel && !sel.includes("\n")) findField.value = sel; findField.focus(); findField.select(); search(); }
  function closeFind() { findRow.hidden = true; area.focus(); }
  function search() {
    hits = [];
    at = -1;
    const t = findField.value.toLowerCase();
    if (t) { const low = area.value.toLowerCase(); for (let i = low.indexOf(t); i >= 0 && hits.length < 10000; i = low.indexOf(t, i + t.length)) hits.push(i); }
    findCount.textContent = t ? (hits.length ? `${hits.length} found` : "Not found") : "";
  }
  function find(step) {
    if (!hits.length) return;
    at = (at + step + hits.length) % hits.length;
    select(area, hits[at], hits[at] + findField.value.length);
    findCount.textContent = `${at + 1} of ${hits.length}`;
  }
  findField.addEventListener("input", () => { search(); find(1); findField.focus(); });
  findField.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); find(ev.shiftKey ? -1 : 1); findField.focus(); }
    if (ev.key === "Escape") { ev.preventDefault(); closeFind(); }
  });

  async function save(confirmed) {
    if (!dirty || closed) return;
    saveBtn.disabled = true;
    let r;
    try { r = await post("/api/files/save", { path, file, text: area.value, base, confirm: confirmed || undefined }); }
    catch (e) { toast(e.message, true); mark(); return; }
    if (r.needs_confirm) {
      if (await dialog({ title: "Save while it's being built?", text: r.words, yes: "Save anyway" })) return save(true);
      mark();
      return;
    }
    if (r.conflict) { showConflict(r); mark(); return; }
    base = r.base;
    saved = area.value;
    fill(notice);
    mark();
    toast(r.words || "Saved.");
  }
  function showConflict(r) {
    const theirs = h("textarea", { class: "ed-area ed-theirs", readonly: true, wrap: "off", "aria-label": "The file as it is now" });
    theirs.value = r.theirs;
    fill(notice, h("div", { class: "ed-conflict", role: "alert" },
      h("p", {}, h("b", {}, "This file changed while you were editing. "), "Below is the file as it is now. Keep yours to write over it, or take the new one and lose your changes."),
      theirs,
      h("div", { class: "row" },
        h("button", { type: "button", class: "primary", title: "Save your version over the new one (the new one stays in the history)", onclick: () => { base = r.base; fill(notice); save(false); } }, "Keep mine"),
        h("button", { type: "button", title: "Throw away your changes and carry on from the new version", onclick: () => { area.value = saved = r.theirs; base = r.base; fill(notice); lines(); mark(); } }, "Take the new one"))));
  }
  saveBtn.addEventListener("click", () => save(false));
  closeBtn.addEventListener("click", async () => {
    if (dirty && !(await dialog({ title: "Leave without saving?", text: "Your changes to this file aren't saved yet. They'll be lost.", yes: "Leave", danger: true }))) return;
    closed = true;
    onDone(saved !== d.text);
  });

  fill(box, h("div", { class: "ed" },
    h("div", { class: "row ed-head" }, state,
      h("button", { type: "button", title: "Find in this file (Ctrl+F)", onclick: openFind }, "Find"), saveBtn, closeBtn),
    d.warn ? h("p", { class: "ed-warn small", role: "note" }, d.warn) : null,
    h("p", { class: "muted small" }, d.git ? "Each save is kept in the project's history, so it can be put back." : "This file isn't kept in git: the old text is kept in the project's own records before each save, so it can be put back."),
    findRow, notice,
    h("div", { class: "ed-box" }, gutter, area)));
  lines();
  mark();
  area.focus();
  if (line > 0) goToLine(area, line);
  return { isDirty: () => dirty };
}

function insert(area, text) {
  const s = area.selectionStart, e = area.selectionEnd;
  area.setRangeText(text, s, e, "end");
}

function tab(area, indent, out) {
  const v = area.value, s = area.selectionStart, e = area.selectionEnd;
  if (s === e && !out) { insert(area, indent); return; }
  const start = v.lastIndexOf("\n", s - 1) + 1;
  const end = e > s && v[e - 1] === "\n" ? e - 1 : e;
  const chunk = v.slice(start, end).split("\n");
  const changed = chunk.map((l) => (out ? l.replace(new RegExp("^(\\t| {1," + Math.max(1, indent.length) + "})"), "") : indent + l)).join("\n");
  area.setRangeText(changed, start, end, "preserve");
  area.setSelectionRange(start, start + changed.length);
}

function select(area, a, b) {
  area.focus();
  area.setSelectionRange(a, b);
  const before = area.value.slice(0, a).split("\n").length - 1;
  const lh = parseFloat(getComputedStyle(area).lineHeight) || 18;
  area.scrollTop = Math.max(0, before * lh - area.clientHeight / 2);
}

export function goToLine(area, line) {
  const v = area.value;
  let at = 0;
  for (let n = 1; n < line && at >= 0; n++) at = v.indexOf("\n", at) + 1 || -1;
  if (at < 0) at = v.length;
  const end = v.indexOf("\n", at);
  select(area, at, end < 0 ? v.length : end);
}

// "Your edits": the newest hand edits, each with Put it back
export async function editsList(box, path, after) {
  editorStyles();
  let d;
  try { d = await get(`/api/files/edits?${q({ path })}`); } catch (e) { fill(box, h("p", { class: "bad" }, e.message)); return; }
  if (!d.edits.length) { fill(box); return; }
  fill(box, h("details", { class: "ed-edits" },
    h("summary", {}, wt("Your edits ({length})", { length: d.edits.length })),
    h("ul", { class: "plain" }, d.edits.map((e) => h("li", { class: "row" },
      h("span", { class: "grow" }, h("code", {}, e.file), h("span", { class: "muted small" }, " · ", ago(e.at), e.undone ? " · put back" : "")),
      e.undone ? null : h("button", { type: "button", title: "Put this file back as it was before this edit (only while the file hasn't changed since)",
        onclick: (ev) => act(ev.currentTarget, async () => {
          if (!(await dialog({ title: "Put it back?", text: wt("{file} goes back to how it was before this edit.", { file: e.file }), yes: "Put it back" }))) return null;
          return post("/api/files/undo_edit", { path, id: e.id });
        }, (r) => (r ? r.words : ""), async (r) => { if (r) { await editsList(box, path, after); if (after) after(e.file); } }) }, "Put it back"))))));
}

export function editorStyles() {
  if (typeof document === "undefined" || document.getElementById("ed-style")) return;
  document.head.append(h("style", { id: "ed-style" }, `
.ed { display: flex; flex-direction: column; gap: 8px; }
.ed-head { gap: 8px; align-items: center; }
.ed-box { display: flex; border: 1px solid var(--color-line-strong); border-radius: var(--radius-small); background: var(--color-sunken); height: 62vh; overflow: hidden; }
.ed-gutter { white-space: pre; text-align: end; padding-block: 8px; padding-inline: 10px 8px; color: var(--color-muted); font: 13px/1.5 var(--font-mono); overflow: hidden; user-select: none; border-inline-end: 1px solid var(--color-line); min-width: 3em; }
.ed-area { flex: 1; min-width: 0; resize: none; border: 0; outline: none; padding: 8px; background: transparent; color: var(--color-text); font: 13px/1.5 var(--font-mono); tab-size: 4; white-space: pre; overflow: auto; }
.ed-box:focus-within { border-color: var(--color-accent); }
.ed-theirs { height: 30vh; width: 100%; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.ed-findrow { gap: 6px; align-items: center; }
.ed-find { flex: 1; min-width: 0; }
.ed-warn { background: var(--color-warn-soft); color: var(--color-text); border-inline-start: 3px solid var(--color-warn); padding: 6px 10px; border-radius: var(--radius-small); }
.ed-conflict { background: var(--color-bad-soft); border-inline-start: 3px solid var(--color-bad); padding: 8px 12px; border-radius: var(--radius-small); display: flex; flex-direction: column; gap: 8px; }
.ed-edits { margin-top: 10px; }
.ed-edits ul { list-style: none; padding: 0; margin: 6px 0 0; display: flex; flex-direction: column; gap: 4px; }
`));
}
