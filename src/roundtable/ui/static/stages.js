// The plan's stages: a strip on the project's overview (where it stands, stage by stage) and the task list grouped
// under each stage. Short first: one sentence and the strip; the parts, the warnings and who changes which file fold
// under "More". (harness/stages.py, ui/stagesapi.py)
import { h, fill, get, q, has } from "./core.js";
import { t as wt } from "./words.js";

const STATE_WORDS = { done: "Built", now: "Being built", stuck: "Something didn't pass", waiting: "Waiting" };
const STATE_TIPS = {
  done: "Every task of this stage is finished",
  now: "The harness is building this stage now. Later stages wait until it's finished, so there's always something that works",
  stuck: "A task of this stage didn't pass. The later stages wait until it's sorted",
  waiting: "This stage starts once the one before it is finished",
};

stagesStyles();

// Tasks grouped by their stage, in the stages' order; tasks with no known stage (added along the way, or a plan
// without stages) come last in a group with no id. A plan without stages gives one group with every task.
export function groupByStage(tasks, stages) {
  const list = stages || [];
  if (!list.length) return [{ id: "", title: "", shows: "", tasks: tasks.slice() }];
  const ids = list.map((s) => s.id);
  const groups = list.map((s) => ({ id: s.id, title: s.title || s.id, shows: s.shows || "", tasks: [] }));
  const rest = { id: "", title: "Added along the way", shows: "", tasks: [] };
  for (const t of tasks) {
    const i = ids.indexOf(t.stage);
    (i >= 0 ? groups[i] : rest).tasks.push(t);
  }
  return groups.filter((g) => g.tasks.length).concat(rest.tasks.length ? [rest] : []);
}

// The task list under a heading per stage. ``render(tasks)`` draws one group's list (plan.js's taskList).
export function stagedTaskList(tasks, stages, render) {
  const groups = groupByStage(tasks, stages);
  if (groups.length === 1 && !groups[0].id) return render(groups[0].tasks);
  return h("div", { class: "stg-groups" }, groups.map((g, i) => h("div", { class: "stg-group" },
    h("div", { class: "stg-group-head" },
      h("b", {}, g.id ? wt("Stage {v1}: {title}", { v1: i + 1, title: g.title }) : g.title),
      g.shows ? h("span", { class: "muted small", title: "What you can try once this stage is finished" }, wt(" · then you can try {shows}", { shows: g.shows })) : null),
    render(g.tasks))));
}

// The overview's strip: one plain sentence and a chip per stage. Nothing shows for a plan without stages, or when
// this copy of the app is older and has no /api/stages.
export function stagesStrip(seat) {
  const box = h("div", { class: "stg" });
  if (!seat || !seat.path) return box;
  (async () => {
    if (!(await has("/api/stages"))) return;
    try {
      const v = await get("/api/stages?" + q({ path: seat.path }));
      if (!(v.stages || []).length) return;
      fill(box, ...stripBody(v));
    } catch (e) { /* the strip is a help: the overview shows without it */ }
  })();
  return box;
}

function stripBody(v) {
  const out = [h("p", { class: "stg-words" }, v.words || "")];
  out.push(h("ol", { class: "stg-chips", "aria-label": "The stages" }, v.stages.map((s, i) => h("li", {
    class: "stg-chip stg-" + s.state,
    title: `${STATE_TIPS[s.state] || ""}${s.shows ? ". At the end you can try: " + s.shows : ""}`,
  }, h("span", { class: "stg-n" }, String(i + 1)), h("span", {}, s.title),
    h("span", { class: "muted small" }, ` ${s.done}/${s.total} · ${STATE_WORDS[s.state] || s.state}`)))));
  const more = moreBody(v);
  if (more.length) out.push(h("details", { class: "stg-more" }, h("summary", { title: "The parts, and which task changes which file" }, "More"), ...more));
  return out;
}

function moreBody(v) {
  const out = [];
  if ((v.parts || []).length) {
    out.push(h("p", { class: "small" }, h("b", {}, "Parts: "), v.parts.map((p) => `${p.name || p.id} (in ${p.folder}/)`).join("; ")));
  }
  if ((v.warnings || []).length) {
    out.push(h("ul", { class: "small stg-warn", title: "Things the harness noticed in the plan. It deals with them itself" },
      v.warnings.map((w) => h("li", {}, w.text || ""))));
  }
  if ((v.strayed || []).length) {
    out.push(h("ul", { class: "small muted", title: "Files a task changed that its plan didn't name. Only noted, never a failure" },
      v.strayed.map((s) => h("li", {}, wt("{task} also changed {v1}", { task: s.task, v1: s.files.join(", ") })))));
  }
  const files = Object.entries(v.files || {});
  if (files.length) {
    out.push(h("details", { class: "small" }, h("summary", {}, "Which task changes which file"),
      h("ul", {}, files.map(([id, fs]) => h("li", {}, `${id}: ${fs.join(", ")}`)))));
  }
  return out;
}

function stagesStyles() {
  if (typeof document === "undefined" || document.getElementById("stg-style")) return;
  document.head.append(h("style", { id: "stg-style" }, `
.stg-words { margin: 4px 0 6px; }
.stg-chips { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 0; padding: 0; }
.stg-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); font-family: var(--font-body); }
.stg-n { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700; background: var(--color-line); }
.stg-done .stg-n { background: var(--color-good-soft); color: var(--color-good); }
.stg-now { border-color: var(--color-good); }
.stg-stuck { border-color: var(--color-bad); }
.stg-stuck .stg-n { background: var(--color-bad-soft); color: var(--color-bad); }
.stg-waiting { opacity: 0.75; }
.stg-more { margin-top: 6px; }
.stg-more > summary { cursor: pointer; }
.stg-warn li { color: var(--color-warn); }
.stg-group + .stg-group { margin-top: 10px; }
.stg-group-head { margin: 4px 0; }
`));
}
