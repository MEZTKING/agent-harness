// Where the planners disagreed: one line on a plan made by two or three rival planners and a chair, the points
// they differed on when it is opened, who planned behind More. Nothing for a plan made by one planner.
// (harness/council.py; the record is the plan's doc.council)
import { h, money, modelName } from "./core.js";
import { t } from "./words.js";

const NUMBERS = { 2: "Two", 3: "Three" };

councilStyles();

// The one line, the same words as council.words() on the PC.
export function councilWords(c) {
  if (!c) return "";
  const n = (c.planners || []).length;
  const who = `${NUMBERS[n] || n} planners`;
  const k = (c.disagreements || []).length;
  if (!c.merged) return c.best ? `${who} each made a plan; the one the others liked best (${c.best}) was used` : `${who} each made a plan`;
  if (!k) return `${who} agreed on the whole plan`;
  return `${who} agreed on most of it; they differed on ${k} thing${k === 1 ? "" : "s"}`;
}

export function councilFold(doc) {
  const c = doc && doc.council;
  if (!c || !(c.planners || []).length) return null;
  const points = (c.disagreements || []).map((d) => h("li", { class: "cn-point" },
    h("b", {}, d.topic),
    h("ul", { class: "cn-opts" }, (d.options || []).map((o) => h("li", {}, h("span", { class: "cn-who", title: "Which planner's plan said this" }, t("Plan {who}", { who: o.who })), " ", o.says))),
    d.chosen ? h("div", { class: "small" }, "Chosen: ", d.chosen, d.why ? h("span", { class: "muted" }, ` – ${d.why}`) : null) : null));
  const more = h("details", { class: "cn-more" }, h("summary", { title: "Which models planned, what each one's plan was, and what the planners cost" }, "More"),
    h("ul", {}, (c.planners || []).map((p) => h("li", {},
      h("b", {}, t("Plan {label}", { label: p.label })), t(" · {v1} · {tasks} task{v2}", { v1: modelName(p.model), tasks: p.tasks, v2: p.tasks === 1 ? "" : "s" }),
      p.votes ? h("span", { class: "muted" }, t(" · {votes} of the planners liked it best", { votes: p.votes })) : null,
      p.summary ? h("div", { class: "muted small" }, p.summary) : null))),
    c.chair ? h("p", { class: "small" }, t("Merged by {v1}, your own planner.", { v1: modelName(c.chair) })) : null,
    c.stopped ? h("p", { class: "small muted" }, c.stopped === "cap" ? "The planners reached their spending cap, so the best plan so far was used." : t("Not merged: {stopped}.", { stopped: c.stopped })) : null,
    c.cost_usd != null ? h("p", { class: "small muted" }, t("The planners cost {v1}.", { v1: money(c.cost_usd) })) : null);
  return h("details", { class: "cn fold-part" },
    h("summary", { title: "Rival planners from different companies each planned this; your planner merged their plans into this one" }, councilWords(c)),
    h("div", { class: "cn-body" },
      points.length ? h("ul", { class: "cn-points" }, points) : h("p", { class: "muted small" }, "They didn't differ on anything that mattered."),
      more));
}

function councilStyles() {
  if (typeof document === "undefined" || document.getElementById("cn-style")) return;
  document.head.append(h("style", { id: "cn-style" }, `
.cn { margin: 6px 0; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.cn > summary { padding: 6px 10px; cursor: pointer; }
.cn-body { padding: 4px 10px 10px; }
.cn-points { margin: 4px 0 0 18px; padding: 0; }
.cn-point { margin: 0 0 8px; }
.cn-opts { margin: 2px 0 2px 16px; padding: 0; }
.cn-who { font-size: 12px; padding: 0 6px; border-radius: var(--radius-small); border: 1px solid var(--color-line); color: var(--color-muted); }
.cn-more { margin-top: 8px; font-size: 13px; }
.cn-more ul { margin: 4px 0 0 18px; padding: 0; }
`));
}
