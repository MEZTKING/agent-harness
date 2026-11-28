// The checking dial and who did each task (harness/dial.py, ui/tandemapi.py). Short first: three buttons with
// prices next to the model sets, and one line under each task; everything else behind "More".
import { h, fill, get, q, has, money, dialog } from "./core.js";

export const LEVELS = ["lean", "balanced", "maximum"];
const NAMES = { lean: "Lean", balanced: "Balanced", maximum: "Maximum" };
const TIPS = {
  lean: "One model builds each task and one checks it, as before",
  balanced: "Tasks the planner marked hard get a second builder and a second checker; risky ones a second checker. Easy tasks may try a newer model",
  maximum: "Every task gets two builders (three when hard) and up to three checkers, and three planners write rival plans that a chair merges",
};

tandemStyles();

// "Models: Balanced · Checking: Balanced": both always labelled, the model sets have a Balanced too.
export function checkingLabel(doc, profileName) {
  const lv = (doc && doc.checking) || "lean";
  return (profileName ? `Models: ${profileName} · ` : "") + `Checking: ${NAMES[lv] || "Lean"}`;
}

// Words for the confirm before Maximum: both figures and what its planners cost.
export function maximumWords(doc) {
  const est = (doc && doc.checking_estimates) || {};
  const now = (doc && doc.checking) || "lean";
  const a = est[now] || {}, b = est.maximum || {};
  let text = `Maximum checking: about ${money(b.cost_usd)} instead of about ${money(a.cost_usd)} (${NAMES[now] || "Lean"}).`;
  if (b.planning_usd) text += ` Three planners and a chair cost about ${money(b.planning_usd)} of that, the next time it plans.`;
  return text;
}

// Three buttons with prices, labelled "Checking". edit(name) changes it (the plan's "checking" action).
export function checkingChoice(doc, edit) {
  const est = (doc && doc.checking_estimates) || null;
  if (!est) return null;  // a plan made before the dial, or an older PC
  const now = doc.checking || "lean";
  const row = h("div", { class: "tq-choice", role: "group", "aria-label": "Checking" });
  const buttons = LEVELS.map((lv) => {
    const e = est[lv] || {};
    const price = e.cost_usd == null || e.unpriced ? "price not known" : "about " + money(e.cost_usd);
    return h("button", {
      type: "button", class: "tq-level" + (lv === now ? " on" : ""), "aria-pressed": String(lv === now),
      title: TIPS[lv] + (e.extra_usd ? `. Extra checking: about ${money(e.extra_usd)}` : ""),
      onclick: async (ev) => {
        if (lv === now) return;
        if (lv === "maximum" && !(await dialog({ title: "Use Maximum checking?", text: maximumWords(doc), yes: "Use Maximum" }))) return;
        const btn = ev.currentTarget;
        btn.disabled = true;
        try { await edit(lv); } finally { btn.disabled = false; }
      },
    }, h("b", {}, NAMES[lv]), h("span", { class: "tq-price" }, price));
  });
  row.append(h("span", { class: "tq-head", title: "How much extra checking this plan gets. It never changes by itself" }, "Checking"), ...buttons);
  return row;
}

// One project's who-did-what, fetched once (null when the PC has no /api/tandem).
export async function tandemFor(path) {
  if (!(await has("/api/tandem"))) return null;
  try { return await get("/api/tandem?" + q({ path })); } catch (e) { return null; }
}

// "Built by Claude Opus · checked by GPT and Gemini · they disagreed" under a task; t is tandem.tasks[id].
export function tandemLine(t) {
  if (!t || !t.line) return null;
  return h("div", { class: "tq-line small" + (t.disagreed ? " tq-split" : ""),
    title: t.same_maker ? "One checker was made by the same company as the builder: it may miss the same things" : "Who built this task and who checked it" }, t.line);
}

// Behind More: each try, why a rival won, each checker's verdict and the words it quoted.
export function tandemFold(t) {
  if (!t || !(t.fold || []).length) return null;
  return h("details", { class: "tq-fold small" }, h("summary", { title: "Each try, why one was chosen and what each checker said" }, "More"),
    h("ul", {}, t.fold.map((x) => h("li", {}, x))));
}

// The line and its fold together, for a task row.
export function tandemRow(t) {
  const line = tandemLine(t);
  if (!line) return null;
  return fill(h("div", { class: "tq" }), line, tandemFold(t));
}

function tandemStyles() {
  if (typeof document === "undefined" || document.getElementById("tq-style")) return;
  document.head.append(h("style", { id: "tq-style" }, `
.tq-choice { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0; }
.tq-head { font-weight: 600; margin-inline-end: 4px; }
.tq-level { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 6px 10px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); color: var(--color-text); cursor: pointer; font: inherit; }
.tq-level.on { border-color: var(--color-accent); box-shadow: inset 0 0 0 1px var(--color-accent); }
.tq-level:disabled { opacity: 0.6; cursor: wait; }
.tq-price { font-size: 12px; color: var(--color-muted); }
.tq { margin: 2px 0 4px; }
.tq-line { color: var(--color-muted); }
.tq-split { color: var(--color-warn); }
.tq-fold > summary { cursor: pointer; color: var(--color-muted); }
.tq-fold ul { margin: 4px 0 0 18px; padding: 0; }
`));
}
