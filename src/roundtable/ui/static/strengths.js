// What each model is good at, learned from real runs (ui/strengthsapi.py, harness/router.py). Short first: one
// plain line per model; the full table by kind of work sits behind "More".
import { h, get, has, card, empty, money } from "./core.js";

strengthsStyles();

// The Strengths tab's body for the Models page, or a note when this copy of the app has no strength map.
export async function strengthsTab(path) {
  if (!(await has("/api/strengths"))) return empty("This computer's copy of the app doesn't keep a strength map yet.");
  let s;
  try { s = await get("/api/strengths" + (path ? "?path=" + encodeURIComponent(path) : "")); }
  catch (e) { return empty("Couldn't read what each model is good at. Try again in a moment."); }
  if (!(s.lines || []).length) {
    return empty(`Nothing learned yet. After a model has tried ${s.min_samples || 5} tasks of one kind, the harness shows what it's best at here and sends that kind of work to it.`);
  }
  return card(null,
    h("p", { class: "muted small" }, "Each task goes to the model that wins its kind of work. Learned from real runs."),
    h("ul", { class: "st-lines" }, s.lines.map((l) =>
      h("li", { title: `${l.label}: approved ${l.approved} of the ${l.n} ${l.tag} tasks it tried` },
        h("b", {}, l.label), h("span", { class: "muted" }, " · "), l.words))),
    strengthsMore(s.table || []));
}

function strengthsMore(rows) {
  if (!rows.length) return null;
  return h("details", { class: "st-more" },
    h("summary", { title: "Every model's score on every kind of work" }, "More"),
    h("table", { class: "plain-table st-table" },
      h("thead", {}, h("tr", {}, ["Job", "Model", "Kind of work", "Approved", "Score", "Per finished task"].map((x) => h("th", {}, x)))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", {}, r.role), h("td", { title: r.model }, r.label), h("td", {}, r.tag_words || r.tag),
        h("td", {}, `${r.approved} of ${r.n}`), h("td", {}, Math.round((r.quality || 0) * 100) + "%"),
        h("td", { title: "What one approved result cost, failed tries included" }, r.cost_per_success == null ? "–" : money(r.cost_per_success)))))));
}

function strengthsStyles() {
  if (typeof document === "undefined" || document.getElementById("st-style")) return;
  document.head.append(h("style", { id: "st-style" }, `
.st-lines { list-style: none; margin: 8px 0; padding: 0; display: grid; gap: 6px; }
.st-lines li { padding: 6px 10px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.st-more { margin-top: 10px; }
.st-more > summary { cursor: pointer; color: var(--color-muted); }
.st-table { margin-top: 8px; width: 100%; font-family: var(--font-body); }
`));
}
