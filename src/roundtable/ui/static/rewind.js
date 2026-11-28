// Undo a task, go back to before it, put it back, or try another way from it (ui/rewindapi.py).
// rewindButton(seat, task): "Undo this task" on a finished task; historyCard(seat): what each task changed.
// The files are always shown first; nothing is ever deleted (Put it back undoes it).
import { h, fill, get, post, q, toast, dialog, card, plural, when, refreshHall } from "./core.js";
import { t } from "./words.js";

const MODES = [
  ["undo_task", "Undo just this task", "Takes back only what this task changed. Later work stays."],
  ["back_to_before", "Go back to before it", "The project as it was before this task started. This task and the later ones go back to to-do."],
];
const MAX_FILES = 8;

rewindStyles();

function fileList(files) {
  if (!files.length) return h("p", { class: "muted" }, "No files change.");
  const row = (f) => h("li", { title: f.from ? t("Was {from}", { from: f.from }) : "" }, h("code", {}, f.path), " ", h("span", { class: "muted" }, f.words || f.change));
  const first = files.slice(0, MAX_FILES), rest = files.slice(MAX_FILES);
  return h("div", {}, h("ul", { class: "rw-files" }, first.map(row)),
    rest.length ? h("details", {}, h("summary", { title: "Every file that changes" }, t("More ({length})", { length: rest.length })), h("ul", { class: "rw-files" }, rest.map(row))) : null);
}

function previewBody(pv) {
  const kids = [h("p", { class: pv.blocked ? "rw-blocked" : "" }, pv.words)];
  if (!pv.blocked) kids.push(fileList(pv.files));
  if (!pv.blocked && pv.hand_edits && pv.hand_edits.length) {
    kids.push(h("p", { class: "muted", title: "Files you changed yourself since the last task" },
      pv.hand_edits_kept ? t("Your own edits to {v1} stay as they are.", { v1: plural(pv.hand_edits.length, "file") })
        : t("Your own edits to {v1} are kept safe and come back with Put it back.", { v1: plural(pv.hand_edits.length, "file") })));
  }
  return kids;
}

async function loadPreview(seat, task, mode) {
  return get(`/api/rewind/preview?${q({ path: seat.path, task: task.id, mode })}`);
}

// the dialog: the two ways back, the files for the one chosen, then Undo it
async function undoDialog(seat, task, startMode = "undo_task", after) {
  let mode = startMode, pv;
  try { pv = await loadPreview(seat, task, mode); } catch (e) { toast(e.message, true); return; }
  const shown = h("div", { class: "rw-preview" });
  const pick = h("div", { class: "row rw-modes", role: "radiogroup", "aria-label": "Which way back" });
  const draw = () => {
    fill(pick, MODES.map(([m, label, tip]) => h("button", { type: "button", role: "radio", "aria-checked": String(m === mode),
      class: m === mode ? "primary" : "", title: tip, onclick: async () => {
        if (m === mode) return;
        try { pv = await loadPreview(seat, task, m); mode = m; draw(); } catch (e) { toast(e.message, true); }
      } }, label)));
    fill(shown, previewBody(pv));
    const yes = shown.closest(".modal") && shown.closest(".modal").querySelector("button.danger");
    if (yes) { yes.disabled = !!pv.blocked; yes.title = pv.blocked || ""; }
  };
  const body = h("div", {}, pick, shown);
  setTimeout(draw, 0);
  draw();
  const ok = await dialog({ title: t("Undo “{v1}”?", { v1: task.title || task.id }), body, yes: "Undo it", danger: true, wide: true });
  if (!ok || pv.blocked) return;
  try {
    const res = await post("/api/rewind", { path: seat.path, task: task.id, mode, stamp: pv.stamp });
    toast(res.words);
    refreshHall();
    if (after) after();
  } catch (e) { toast(e.message, true); }
}

export function rewindButton(seat, task, after) {
  if (!seat || !seat.path || !task) return null;
  return h("button", { type: "button", class: "small", title: "See which files would change back, then choose. You can put it back afterwards.",
    onclick: () => undoDialog(seat, task, "undo_task", after) }, "Undo this task");
}

async function tryAnotherWay(seat, row, after) {
  const name = await dialog({ title: "Try another way from here", yes: "Make the copy",
    text: t("Starts a separate copy of this project as it was after “{title}”, with the plan and the tasks after it to do again. It costs nothing until you run it.", { title: row.title }),
    input: { label: "Name of the copy", value: `${seat.name || seat.id}-another-way` } });
  if (!name) return;
  try {
    const res = await post("/api/rewind/fork", { path: seat.path, task: row.id, name });
    toast(res.words);
    refreshHall();
    if (after) after();
  } catch (e) { toast(e.message, true); }
}

async function putBack(seat, last, after) {
  const ok = await dialog({ title: "Put it back?", text: t("{words} This puts the project and its tasks back as they were before.", { words: last.words }), yes: "Put it back" });
  if (!ok) return;
  try { toast((await post("/api/rewind/undo", { path: seat.path })).words); refreshHall(); if (after) after(); } catch (e) { toast(e.message, true); }
}

function historyRow(seat, d, r, redraw) {
  return h("li", { class: "rw-row" + (r.undone ? " rw-undone" : "") },
    h("div", { class: "rw-line" }, h("b", {}, r.title), h("span", { class: "muted" }, r.words), r.at ? when(r.at) : null,
      h("span", { class: "spacer" }),
      r.can_undo && d.can_change ? rewindButton(seat, r, redraw) : null,
      r.can_undo ? h("button", { type: "button", class: "small", title: "A separate copy from this point, to try something different", onclick: () => tryAnotherWay(seat, r, redraw) }, "Try another way") : null),
    r.files.length ? h("details", {}, h("summary", { title: "The files this task changed" }, "More"),
      fileList(r.files), r.summary ? h("p", { class: "muted" }, r.summary) : null,
      r.can_go_back && d.can_change ? h("button", { type: "button", class: "small", title: "The project as it was before this task started",
        onclick: () => undoDialog(seat, r, "back_to_before", redraw) }, "Go back to before it") : null) : null);
}

export async function historyCard(seat) {
  const box = h("div", { class: "rw-history" });
  const redraw = async () => {
    let d;
    try { d = await get(`/api/rewind?${q({ path: seat.path })}`); } catch (e) { fill(box, h("p", { class: "muted" }, e.message)); return; }
    const kids = [];
    if (d.last) {
      kids.push(h("div", { class: "rw-last row" }, h("span", {}, d.last.words), h("span", { class: "spacer" }),
        d.last.can_put_back ? h("button", { type: "button", class: "small", onclick: () => putBack(seat, d.last, redraw) }, "Put it back")
          : h("span", { class: "muted", title: d.last.why_not }, "Can't be put back now")));
    }
    if (!d.can_change && d.why_not) kids.push(h("p", { class: "muted" }, d.why_not));
    kids.push(d.rows.length ? h("ul", { class: "rw-rows" }, d.rows.map((r) => historyRow(seat, d, r, redraw)))
      : h("p", { class: "muted" }, "No task has finished yet."));
    fill(box, kids);
  };
  if (seat && seat.path) await redraw();
  else fill(box, h("p", { class: "muted" }, "The history is on the computer that builds this project."));
  return card(h("h2", { title: "What each finished task changed. Undo one, go back, or try another way from it." }, "What each task changed"), box);
}

function rewindStyles() {
  if (typeof document === "undefined" || document.getElementById("rw-style")) return;
  document.head.append(h("style", { id: "rw-style" }, `
.rw-rows { list-style: none; margin: 0; padding: 0; }
.rw-row { border-top: 1px solid var(--color-line); padding: 8px 0; }
.rw-row:first-child { border-top: 0; }
.rw-line { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; } .rw-line .spacer { flex: 1; }
.rw-undone b { text-decoration: line-through; opacity: .7; }
.rw-files { margin: 6px 0; padding-inline-start: 18px; font-size: 13px; } .rw-files li { margin: 2px 0; }
.rw-modes { gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.rw-blocked { color: var(--color-flare); }
.rw-last { gap: 10px; align-items: center; padding: 8px 10px; margin-bottom: 8px; border-radius: var(--radius-small); background: var(--color-sunken); }
.rw-last .spacer { flex: 1; }
`));
}
