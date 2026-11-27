// The done list: what a person can do with the finished thing, and whether each was shown to work. One line
// first ("Done when: 5 of 7 ✓"), the items when it is opened, each item's evidence behind More.
// (harness/donelist.py, harness/donestage.py, ui/doneapi.py)
import { h, fill, get, q, has, enlarge } from "./core.js";

const MARK_TIP = {
  passed: "It was shown to work",
  failed: "It was tried and doesn't work yet",
  unchecked: "It couldn't be checked here, so it has no tick",
  open: "Not checked yet",
};
const HOW_TIP = {
  journey: "The harness tries these steps in the app itself",
  page_opens: "It must open with no errors",
  command: "A command that must succeed",
  file_exists: "A file that must be there",
  play: "Someone plays it",
  look: "A person (or a model that can see) looks at it",
  owner: "Only you can say",
};

doneStyles();

// The card for a seat (or anything with .path); nothing when this copy of the app has no done list (an older PC)
// or the plan has none.
export function doneCard(seat) {
  const path = seat && (seat.path || seat.project_path);
  const det = h("details", { class: "dl" });
  if (!path) return det;
  const head = h("summary", { title: "What finished means for this project: open it to see each thing and whether it works" },
    h("span", { class: "dl-words muted" }, "Looking for the done list…"));
  const body = h("div", { class: "dl-body" });
  det.append(head, body);
  (async () => {
    if (!(await has("/api/done"))) { det.remove(); return; }
    try {
      const d = await get("/api/done?" + q({ path }));
      if (!(d.items || []).length) { det.remove(); return; }
      fill(head, h("span", { class: "dl-words" + (d.failed ? " dl-bad" : "") }, d.words));
      fill(body, ...doneBody(path, d));
    } catch (e) { det.remove(); }
  })();
  return det;
}

// The one line alone (the project overview), or null while it loads or when there is no list.
export async function doneLine(path) {
  if (!path || !(await has("/api/done"))) return null;
  try {
    const d = await get("/api/done?" + q({ path }));
    return (d.items || []).length ? h("p", { class: "dl-line" + (d.failed ? " dl-bad" : ""), title: "What finished means: open the plan to see each thing" }, d.words) : null;
  } catch (e) { return null; }
}

export function doneBody(path, d) {
  const list = h("ul", { class: "dl-items" }, (d.items || []).map((i) => itemRow(path, i)));
  const out = [list];
  if (d.unchecked) out.push(h("p", { class: "muted small", title: "Nothing is ticked unless it was really shown to work" },
    `${d.unchecked} couldn't be checked yet or here: they show no tick.`));
  return out;
}

function itemRow(path, i) {
  const state = i.state || "open";
  const mark = { passed: "✓", failed: "✗", unchecked: "?", open: "·" }[state] || "·";
  const tags = [];
  if (i.must === false) tags.push(h("span", { class: "dl-tag", title: "Nice to have: it doesn't stop the project being finished" }, "nice to have"));
  if (i.by === "owner") tags.push(h("span", { class: "dl-tag", title: "You added this one; it's kept word for word" }, "yours"));
  if (i.by === "kind") tags.push(h("span", { class: "dl-tag", title: "Every project of this kind is checked for this" }, "for its kind"));
  const li = h("li", { class: "dl-item dl-" + state },
    h("span", { class: "dl-mark", title: MARK_TIP[state] }, mark),
    h("div", { class: "dl-main" },
      h("div", {}, h("span", { title: HOW_TIP[i.how] || "" }, i.text), " ", ...tags),
      i.words ? h("div", { class: "muted small" }, i.words) : null,
      state !== "open" ? more(path, i) : null));
  return li;
}

// the item's evidence (pictures, what the check wrote), loaded only when More is opened
function more(path, i) {
  const det = h("details", { class: "dl-more" }, h("summary", { title: "What the check saw: pictures and its notes" }, "More"));
  const box = h("div", {});
  det.append(box);
  let loaded = false;
  det.addEventListener("toggle", async () => {
    if (!det.open || loaded) return;
    loaded = true;
    fill(box, h("p", { class: "muted small" }, "Loading…"));
    try {
      const e = await get("/api/done/evidence?" + q({ path, item: i.id }));
      if (!e.found) { fill(box, h("p", { class: "muted small" }, e.words || "Nothing to show.")); return; }
      const pics = (e.pictures || []).map((p) => h("button", { type: "button", class: "dl-pic", title: "Click to see it full size", onclick: () => enlarge(p.data, i.text) },
        h("img", { src: p.data, alt: `${i.text}: ${p.name}` })));
      const texts = Object.entries(e.texts || {}).map(([k, v]) => h("div", {}, h("b", { class: "small" }, k), h("pre", { class: "log short" }, v)));
      const steps = (i.steps || []).map((s) => h("li", {}, Object.entries(s).map(([k, v]) => `${k}${v === true ? "" : ": " + v}`).join(", ")));
      fill(box, pics.length ? h("div", { class: "dl-pics" }, pics) : null, ...texts,
        steps.length ? h("div", {}, h("b", { class: "small", title: "The steps the harness tries in the app" }, "Steps"), h("ol", { class: "small" }, steps)) : null,
        !pics.length && !texts.length && !steps.length ? h("p", { class: "muted small" }, "The check left nothing more to show.") : null);
    } catch (err) { loaded = false; fill(box, h("p", { class: "muted small" }, "Couldn't load it. Close and open More again to retry.")); }
  });
  return det;
}

function doneStyles() {
  if (typeof document === "undefined" || document.getElementById("dl-style")) return;
  document.head.append(h("style", { id: "dl-style" }, `
.dl { margin: 6px 0; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.dl > summary { padding: 6px 10px; cursor: pointer; }
.dl-words, .dl-line { font-family: var(--font-body, inherit); }
.dl-line { margin: 4px 0; }
.dl-bad { color: var(--color-bad); }
.dl-body { padding: 4px 10px 10px; }
.dl-items { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.dl-item { display: flex; gap: 8px; align-items: flex-start; }
.dl-main { min-width: 0; flex: 1; }
.dl-mark { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: 12px; font-weight: 700; background: var(--color-line); flex: none; }
.dl-passed .dl-mark { background: var(--color-good-soft); color: var(--color-good); }
.dl-failed .dl-mark { background: var(--color-bad-soft); color: var(--color-bad); }
.dl-unchecked .dl-mark { background: var(--color-warn-soft); color: var(--color-warn); }
.dl-tag { font-size: 11px; padding: 0 6px; border-radius: var(--radius-small); border: 1px solid var(--color-line); color: var(--color-text); opacity: .8; }
.dl-more { margin-top: 4px; font-size: 12px; }
.dl-pics { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 220px)); gap: 6px; margin: 4px 0; }
.dl-pic { padding: 0; border: 1px solid var(--color-line); border-radius: var(--radius-small); overflow: hidden; background: var(--color-surface); cursor: zoom-in; }
.dl-pic img { display: block; width: 100%; height: 140px; object-fit: cover; }
`));
}
