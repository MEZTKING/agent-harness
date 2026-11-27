// Proof for one finished task: the app before and after it (a slider), what a model that can see said, and the
// tests. Folded by default: the one line shows; the pictures load when it is opened. (harness/proof.py, ui/proofapi.py)
import { h, fill, get, q, has, enlarge } from "./core.js";

const NAMES = { desktop: "Computer", phone: "Phone", dark: "Dark mode", start: "Start", middle: "Playing" };
const MARK = { shows_it: "✓", does_not: "✗", cant_tell: "?" };
const MARK_TIP = {
  shows_it: "A model that can see looked at the pictures and thinks they show what the task asked for",
  does_not: "A model that can see looked at the pictures and doesn't think they show what the task asked for. It's advice: the reviewer decides",
  cant_tell: "A model that can see looked but couldn't tell from the pictures",
};

proofStyles();

// One task's proof card, or nothing when this copy of the app has no proof (an older PC).
export function proofCard(path, task) {
  const det = h("details", { class: "pf" });
  const head = h("summary", { title: "Proof that this task did what it should: click to see the pictures before and after" },
    h("span", { class: "pf-mark" }, "…"), h("span", { class: "pf-words muted" }, "Looking for this task's proof…"));
  const body = h("div", { class: "pf-body" });
  det.append(head, body);
  let loaded = false;
  (async () => {
    if (!(await has("/api/proof"))) { det.remove(); return; }
    try {
      const p = await get("/api/proof?" + q({ path, task }));
      if (!p.found) { det.remove(); return; }
      fill(head, mark(p), h("span", { class: "pf-words" }, p.words || ""));
    } catch (e) { det.remove(); }
  })();
  det.addEventListener("toggle", async () => {
    if (!det.open || loaded) return;
    loaded = true;
    fill(body, h("p", { class: "muted small" }, "Loading the pictures…"));
    try { fill(body, ...proofBody(await get("/api/proof?" + q({ path, task, inline: 1 })))); }
    catch (e) { loaded = false; fill(body, h("p", { class: "muted" }, "Couldn't load the proof. Close and open it again to retry.")); }
  });
  return det;
}

function mark(p) {
  const j = p.judge || {};
  const v = j.looked ? j.verdict : null;
  return h("span", { class: "pf-mark pf-" + (v || "none"), title: v ? MARK_TIP[v] : "Nobody looked at the pictures: no model that can see was set, or the check was off or too dear" }, v ? MARK[v] : "–");
}

export function proofBody(p) {
  const img = p.images || { before: {}, after: {} };
  const pairs = p.pairs || [];
  const out = [];
  if (pairs.length) {
    out.push(h("div", { class: "pf-pairs" }, pairs.map((pr) => compare(pr, img.before[pr.kind], img.after[pr.kind]))));
  } else {
    out.push(h("p", { class: "muted small" }, (p.after && (p.after.note || p.after.failed)) || "No pictures for this task: it has no screens to show."));
  }
  const j = p.judge || {};
  if (j.looked && (j.problems || []).length) {
    out.push(h("div", { class: "pf-probs" }, h("b", {}, "What it noticed"), h("ul", {}, j.problems.map((x) => h("li", {}, x)))));
  }
  if (p.lines_text) out.push(h("p", { class: "pf-lines", title: "What this kind of project must show before it counts as proven" }, p.lines_text));
  const t = p.tests;
  if (t && t.words) out.push(testsPart(t));
  const more = [];
  if (j.model) more.push(h("li", {}, `Looked at by ${j.model}` + (j.cost_usd ? ` · $${Number(j.cost_usd).toFixed(4)}` : "")));
  if (p.before && p.before.commit) more.push(h("li", {}, `Before: version ${String(p.before.commit).slice(0, 8)}` + (p.before.reused ? " (pictures kept from earlier)" : "")));
  if (p.after && p.after.commit) more.push(h("li", {}, `After: version ${String(p.after.commit).slice(0, 8)}`));
  if (more.length) out.push(h("details", { class: "pf-more" }, h("summary", { title: "Who looked, what it cost, which versions" }, "More"), h("ul", {}, more)));
  return out;
}

function testsPart(t) {
  const tails = [t.before && t.before.tail ? ["Before the run", t.before.tail] : null, t.after && t.after.tail ? ["After this task", t.after.tail] : null].filter(Boolean);
  return h("div", { class: "pf-tests" }, h("p", { title: t.command ? `The project's test command: ${t.command}` : "The project's own tests" }, t.words),
    (t.broke || []).length ? h("p", { class: "small pf-bad" }, "Broke: " + t.broke.slice(0, 6).join(", ")) : null,
    tails.length ? h("details", {}, h("summary", { title: "The last lines the tests wrote" }, "The tests' last lines"),
      tails.map(([label, text]) => h("div", {}, h("b", { class: "small" }, label), h("pre", { class: "log short" }, text)))) : null);
}

// one picture before and after: drag the slider to wipe from one to the other
function compare(pr, before, after) {
  const name = NAMES[pr.kind] || pr.kind;
  const cap = h("figcaption", {}, h("b", {}, name), h("span", { class: "muted" }, " · " + pr.words));
  if (!after) return h("figure", { class: "pf-pair" }, h("p", { class: "muted small" }, "The picture is too big to show here."), cap);
  if (!before) {
    return h("figure", { class: "pf-pair" }, h("button", { type: "button", class: "pf-frame", title: `${name}, after the task: click to see it full size`, onclick: () => enlarge(after, `${name}, after`) },
      h("img", { src: after, alt: `${name}, after the task` }), h("span", { class: "pf-tag pf-tag-r" }, "New")), cap);
  }
  const top = h("div", { class: "pf-top" }, h("img", { src: before, alt: `${name}, before the task` }));
  const slider = h("input", { type: "range", min: "0", max: "100", value: "50", class: "pf-slide", "aria-label": `${name}: slide between before and after`,
    title: "Slide left to see more of after, right to see more of before" });
  const set = () => { top.style.clipPath = `inset(0 ${100 - Number(slider.value)}% 0 0)`; };
  slider.addEventListener("input", set);
  set();
  const frame = h("div", { class: "pf-frame" }, h("img", { src: after, alt: `${name}, after the task`, onclick: () => enlarge(after, `${name}, after`) }), top,
    h("span", { class: "pf-tag" }, "Before"), h("span", { class: "pf-tag pf-tag-r" }, "After"));
  return h("figure", { class: "pf-pair" }, frame, slider, cap);
}

function proofStyles() {
  if (typeof document === "undefined" || document.getElementById("pf-style")) return;
  document.head.append(h("style", { id: "pf-style" }, `
.pf { margin: 6px 0; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.pf > summary { display: flex; align-items: center; gap: 8px; padding: 6px 10px; cursor: pointer; list-style: none; }
.pf > summary::-webkit-details-marker { display: none; }
.pf-mark { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: 12px; font-weight: 700; background: var(--color-line); flex: none; }
.pf-shows_it { background: var(--color-good-soft); color: var(--color-good); }
.pf-does_not { background: var(--color-bad-soft); color: var(--color-bad); }
.pf-cant_tell { background: var(--color-warn-soft); color: var(--color-warn); }
.pf-words { overflow: hidden; text-overflow: ellipsis; }
.pf-body { padding: 4px 10px 10px; }
.pf-pairs { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
.pf-pair { margin: 0; min-width: 0; }
.pf-frame { position: relative; display: block; padding: 0; border: 1px solid var(--color-line); border-radius: 6px; overflow: hidden; background: var(--color-surface); width: 100%; }
.pf-frame img { display: block; width: 100%; height: auto; cursor: zoom-in; }
.pf-top { position: absolute; inset: 0; pointer-events: none; } .pf-top img { width: 100%; }
.pf-tag { position: absolute; top: 6px; left: 6px; font-size: 11px; padding: 1px 6px; border-radius: 4px; background: color-mix(in srgb, var(--color-text) 70%, transparent); color: var(--color-surface); pointer-events: none; }
.pf-tag-r { left: auto; right: 6px; }
.pf-slide { width: 100%; margin: 4px 0 0; accent-color: var(--color-accent); }
.pf-pair figcaption { font-size: 12px; }
.pf-probs ul, .pf-more ul { margin: 4px 0 0 18px; padding: 0; }
.pf-tests p { margin: 8px 0 2px; } .pf-bad { color: var(--color-bad); }
.pf-lines { margin: 8px 0 0; font-size: 13px; }
.pf-more { margin-top: 8px; font-size: 12px; }
`));
}
