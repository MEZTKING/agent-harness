// The task copies (worktrees) a project keeps: which task, its branch, whether it holds unsaved changes, and why it
// was kept. "Open its files" lists what that copy changed; "Tidy" shows what the daily tidy-up would do with each,
// by its own rule. This panel never deletes anything.
import { h, fill, get, post, toast, q, empty, plural } from "./core.js";

worktreesStyles();

const UNSAVED = { yes: "Has unsaved changes", no: "Nothing unsaved", "can't tell": "Can't tell if anything is unsaved" };

export async function worktreesPanel(seat) {
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const box = h("details", { class: "card fold wt" },
    h("summary", { title: "Copies of the project made so several tasks could be built at once" }, "Task copies"), body);
  if (!seat || !seat.path) { fill(body, empty("This project's copies are on the computer that builds it.")); return box; }
  const draw = async () => {
    let d;
    try { d = await get(`/api/worktrees?${q({ path: seat.path })}`); } catch (e) { fill(body, h("p", { class: "muted small" }, e.message)); return; }
    const items = d.items || [];
    if (!items.length) { fill(body, h("p", { class: "muted small" }, "No task copies are kept for this project.")); return; }
    const tidyBtn = h("button", { class: "small", type: "button", title: "See what the daily tidy-up would do with each copy. Nothing is removed from here." }, "Tidy");
    const tidyWords = h("p", { class: "muted small" });
    tidyBtn.onclick = async () => {
      tidyBtn.disabled = true;
      try {
        const r = await post("/api/tidy/preview", {});
        const going = items.filter((it) => (r.items || []).some((x) => x.path === it.folder));
        fill(tidyWords, going.length ? `The daily tidy-up would remove ${plural(going.length, "copy", "copies")} (${going.map((x) => x.task).join(", ")}); the rest stay, as each says. Tidying runs from Settings → Advanced.`
          : "The daily tidy-up would keep every copy here, for the reason each gives.");
      } catch (e) { toast(e.message, true); } finally { tidyBtn.disabled = false; }
    };
    fill(body, h("p", { class: "muted small" }, `${plural(items.length, "copy", "copies")} kept.`), h("div", { class: "row" }, tidyBtn), tidyWords,
      h("ul", { class: "wt-list" }, items.map((it) => row(seat, it))));
  };
  box.addEventListener("toggle", () => { if (box.open) draw(); });
  return box;
}

function row(seat, it) {
  const files = h("div", { class: "wt-files" });
  const open = h("button", { class: "small", type: "button", title: "List the files this copy changed" }, "Open its files");
  open.onclick = async () => {
    open.disabled = true;
    try {
      const r = await get(`/api/worktrees/files?${q({ path: seat.path, task: it.task })}`);
      fill(files, (r.files || []).length ? h("ul", { class: "wt-flist" }, r.files.map((f) => h("li", {}, h("code", {}, f.path), h("span", { class: "muted small" }, ` · ${f.change}`))))
        : h("p", { class: "muted small" }, "It changed no files."));
    } catch (e) { toast(e.message, true); } finally { open.disabled = false; }
  };
  return h("li", { class: "wt-row" },
    h("div", {}, h("b", { class: "wt-num" }, it.task), " ", it.title || "", h("span", { class: `wt-unsaved ${it.unsaved === "yes" ? "yes" : ""}` }, ` · ${UNSAVED[it.unsaved] || it.unsaved}`)),
    h("p", { class: "small muted" }, it.why ? `Kept because ${it.why}. ` : "", it.tidy),
    h("div", { class: "row" }, open),
    h("details", { class: "wt-more" }, h("summary", {}, "More"), h("p", { class: "small muted" }, h("code", {}, it.branch), " · ", h("code", {}, it.folder))),
    files);
}

function worktreesStyles() {
  if (typeof document === "undefined" || document.getElementById("wt-style")) return;
  document.head.append(h("style", { id: "wt-style" }, `
.wt-list, .wt-flist { list-style: none; padding-left: 0; margin: 8px 0 0; }
.wt-row { border: 1px solid var(--color-line); border-radius: var(--radius-small); padding: 8px 10px; margin-bottom: 8px; background: var(--color-sunken); }
.wt-row p { margin: 4px 0; } .wt-num { font-family: var(--font-mono); color: var(--color-accent); }
.wt-unsaved.yes { color: var(--color-warn); font-weight: 700; }
.wt-more summary { cursor: pointer; font-size: 12.5px; color: var(--color-muted); }
.wt-flist li { font-size: 12.5px; margin: 2px 0; }
`));
}
