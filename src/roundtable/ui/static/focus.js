// Focus: one task full screen – its steps, the command it is running now, the files it changed – with Stop and
// Back (Esc leaves too). The steps are drawn by Watch's own functions (watch.js stepNode and changedFiles, when that
// module exports them); until then a plain line per step stands in.
import { h, fill, get, post, toast, q, taskPill, jobName, money } from "./core.js";
import { liveOutput } from "./terminal.js";

let OPEN = null;

export async function openFocus(seat, taskId) {
  if (!seat || !seat.path || !taskId) return;
  if (OPEN) OPEN.close();
  focusStyles();
  const watch = await import("./watch.js").catch(() => ({}));
  const path = seat.path;
  const title = h("h2", { id: "fx-title" }, taskId);
  const pill = h("span");
  const meta = h("span", { class: "muted small" });
  const steps = h("div", { class: "term fx-steps", role: "log", "aria-live": "polite" }, h("p", { class: "t-meta" }, "Loading…"));
  const live = h("div", { class: "fx-live" });
  const files = h("div", { class: "fx-files" });
  const back = h("button", { type: "button", title: "Back to where you were (Esc)" }, "Back");
  const stop = h("button", { class: "danger", type: "button", title: "Stop the command this task is running now. The task carries on and is told you stopped it." }, "Stop its command");
  const shell = h("div", { class: "fx", role: "dialog", "aria-modal": "true", "aria-labelledby": "fx-title" },
    h("header", { class: "fx-head" }, h("span", { class: "fx-num" }, taskId), title, pill, meta, h("span", { class: "spacer" }), stop, back),
    h("div", { class: "fx-body" }, h("div", { class: "fx-main" }, steps), h("aside", { class: "fx-side" }, live, files)));
  const open = new Set();
  let timer = null, liveNode = null, stick = true;
  steps.addEventListener("scroll", () => { stick = steps.scrollHeight - steps.scrollTop - steps.clientHeight < 40; });
  const close = () => { clearTimeout(timer); document.removeEventListener("keydown", onKey, true); shell.remove(); if (OPEN && OPEN.shell === shell) OPEN = null; };
  const onKey = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); close(); } };
  back.onclick = close;
  stop.onclick = async () => {
    stop.disabled = true;
    try { toast((await post("/api/terminal/task/stop", { path, task: taskId })).words || "Stopped"); } catch (e) { toast(e.message, true); }
    finally { stop.disabled = false; }
  };
  document.addEventListener("keydown", onKey, true);
  document.body.append(shell);
  OPEN = { shell, close };
  back.focus();

  const draw = async () => {
    if (!shell.isConnected) return;
    let d = null;
    try { d = await get(`/api/project/session?${q({ path })}`); } catch (e) { fill(steps, h("p", { class: "t-meta" }, e.message)); }
    const runs = ((d && d.tasks) || []).filter((t) => t.id === taskId);
    const t = runs[runs.length - 1];
    if (!t) fill(steps, h("p", { class: "t-meta" }, "This task hasn't started yet: its steps show here once it does."));
    else {
      fill(title, t.title || t.id);
      fill(pill, taskPill(t.status));
      fill(meta, [jobName(t.role), t.cost ? money(t.cost) : ""].filter(Boolean).join(" · "));
      fill(steps, t.steps.length ? t.steps.map((s, j) => (watch.stepNode ? watch.stepNode(path, s, `f:${j}`, open) : plainStep(s)))
        : h("p", { class: "t-meta" }, "Starting…"));
      if (stick) steps.scrollTop = steps.scrollHeight;
      if (t.status === "running") { if (!liveNode) liveNode = liveOutput(path, t.id); fill(live, h("h3", {}, "Running now"), liveNode); }
      else { liveNode = null; fill(live); }
      stop.hidden = t.status !== "running";
      const ch = t.changes || [];
      fill(files, watch.changedFiles ? watch.changedFiles(t, "f:files", open)
        : [h("h3", {}, ch.length ? `Files it changed (${ch.length})` : "No files changed yet"),
          ch.length ? h("ul", { class: "fx-list" }, ch.map((c) => h("li", {}, h("code", {}, c.path), h("span", { class: "muted small" }, ` +${c.added} −${c.removed}`)))) : null]);
    }
    timer = setTimeout(draw, t && t.status === "running" ? 2500 : 15000);
  };
  await draw();
}

function plainStep(s) {
  const text = s.label || s.text || "";
  return h("div", { class: s.kind === "say" ? "t-say" : s.kind === "review" ? "t-review " + (s.approved ? "ok" : "no") : "t-tool" },
    h("span", { class: "t-dot" + (s.error ? " bad" : "") }, s.kind === "say" ? "⏺" : "●"), " ", text);
}

function focusStyles() {
  if (document.getElementById("fx-style")) return;
  document.head.append(h("style", { id: "fx-style" }, `
.fx { position: fixed; inset: 0; z-index: 50; background: var(--color-background); display: flex; flex-direction: column; }
.fx-head { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-bottom: 1px solid var(--color-line); background: var(--color-raised); }
.fx-head h2 { margin: 0; font: 700 18px/1.2 var(--font-display); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fx-head .spacer { flex: 1; }
.fx-num { font: 700 13px/1 var(--font-mono); color: var(--color-accent); }
.fx-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 12px; padding: 12px 18px; }
.fx-main { min-height: 0; display: flex; } .fx-steps { flex: 1; overflow: auto; max-height: none; }
.fx-side { min-height: 0; overflow: auto; } .fx-side h3 { margin: 4px 0 6px; font-size: 14px; }
.fx-list { list-style: none; padding-left: 4px; margin: 0; font-size: 12.5px; } .fx-list li { margin: 2px 0; }
@media (max-width: 800px) { .fx-body { grid-template-columns: 1fr; } }
`));
}
