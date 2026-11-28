// The proof run (proofrun.py, ui/proofrunapi.py): proofRunCard() for Settings or the Learning page. Short first: one
// line of what it is and one of where it stands; the three numbers, the tasks and what needed a person behind More.
// Start plans and prices it (a few cents); Build it spends, after a yes, and never past its limit. Nothing shows on
// an older PC.
import { h, fill, get, post, has, act, dialog, money, every } from "./core.js";
import { t } from "./words.js";

proofRunStyles();

export function proofRunCard() {
  const box = h("section", { class: "card pr" },
    h("div", { class: "card-head" }, h("h2", { title: t("Builds one small made-up game from one idea, to show the whole harness works, for a known price") }, t("Prove it"))));
  const body = h("div", {}, h("p", { class: "muted small" }, t("Looking…")));
  box.append(body);
  let sig = "";
  const load = async () => {
    if (!(await has("/api/proofrun"))) { box.remove(); return false; }
    let v;
    try { v = await get("/api/proofrun"); }
    catch (e) { fill(body, h("p", { class: "muted" }, t("Couldn't read the proof run. Open this page again to retry."))); return true; }
    const now = JSON.stringify([v.phase, v.busy, v.words, (v.steps || []).length]);
    if (now !== sig) { sig = now; fill(body, ...parts(v, load)); }
    return true;
  };
  every(box, load, () => 5000);
  return box;
}

function parts(v, reload) {
  const out = [h("p", {}, t("Build a small game from one idea. About $1, at most $3."))];
  if (v.busy) out.push(h("p", { class: "pr-state" }, t("Working on it… (Activity → Background work shows each step)")));
  else if (v.ready) out.push(h("p", { class: "pr-state" }, v.words));
  const acts = h("div", { class: "pr-acts" });
  if (!v.busy && (!v.ready || v.phase === "prepared")) acts.append(button(t("Start"), t("Plans and prices it first: nothing is built until you say yes"), "/api/proofrun/start", reload));
  if (!v.busy && v.phase === "estimated") acts.append(button(t("Build it"), t("Builds the game now; it stops at its limit whatever happens"), "/api/proofrun/build", reload));
  if (!v.busy && (v.phase === "done" || v.phase === "stopped")) acts.append(button(t("Start a new one"), t("Puts this proof run aside (kept, renamed) so you can start again"), "/api/proofrun/new", reload, true));
  if (acts.childElementCount) out.push(acts);
  if (v.ready && v.money) out.push(more(v));
  return out;
}

function button(label, tip, route, reload, small = false) {
  const b = h("button", { class: small ? "btn small" : "btn", title: tip }, label);
  b.addEventListener("click", () => act(b, async () => {
    const q = await post(route, {});
    if (q && q.confirm) {
      if (!(await dialog({ title: t("Are you sure?"), text: q.question, yes: label }))) return;
      await post(route, { confirm: true });
    }
    await reload();
  }));
  return b;
}

function usd(x) { return x === null || x === undefined ? t("not known") : money(x); }

function more(v) {
  const m = v.money || {};
  const box = h("details", { class: "pr-more" }, h("summary", { title: t("The three numbers, the tasks and every place a person had to step in") }, t("More")));
  const rows = (m.table || []).map((r) => h("tr", {}, h("td", {}, t(r.what)), h("td", { class: "pr-usd" }, usd(r.usd))));
  box.append(h("table", { class: "pr-table" }, h("tbody", {}, ...rows)));
  if (m.gap_pct !== null && m.gap_pct !== undefined) box.append(h("p", { class: "muted small" }, t("Gap from the estimate: {gap}%", { gap: (m.gap_pct > 0 ? "+" : "") + m.gap_pct })));
  if (m.real_words) box.append(h("p", { class: "muted small" }, m.real_words));
  const tk = v.tasks || {};
  if (tk.total) box.append(h("p", {}, t("{n} of {total} tasks passed the first time; {r} after a retry; {f} stuck.",
    { n: (tk.first_time || []).length, total: tk.total, r: (tk.retried || []).length, f: (tk.failed || []).length })));
  const people = v.people || [];
  box.append(h("h3", { class: "pr-h" }, t("Where a person had to step in")),
    people.length ? h("ul", { class: "pr-list" }, ...people.map((p) => h("li", {}, `${p.where}: ${p.what}`))) : h("p", { class: "muted small" }, t("Nowhere.")));
  const said = [v.looks && v.looks.words, v.sounds && v.sounds.words, v.seeing && v.seeing.words].filter(Boolean);
  if (said.length) box.append(h("p", { class: "muted small" }, said.join(" ")));
  if (v.time && v.time.minutes !== null && v.time.minutes !== undefined) box.append(h("p", { class: "muted small" }, t("It took {m} minutes.", { m: v.time.minutes })));
  return box;
}

function proofRunStyles() {
  if (typeof document === "undefined" || document.getElementById("pr-style")) return;
  document.head.append(h("style", { id: "pr-style" }, `
.pr-state { margin: 4px 0; }
.pr-acts { display: flex; gap: 8px; margin: 8px 0 4px; flex-wrap: wrap; }
.pr-more { margin-top: 6px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); padding: 4px 10px; }
.pr-more > summary { cursor: pointer; padding: 2px 0; }
.pr-table { border-collapse: collapse; margin: 6px 0; }
.pr-table td { padding-block: 2px; padding-inline: 0 12px; text-align: start; }
.pr-usd { font-variant-numeric: tabular-nums; }
.pr-h { font-size: 1em; margin: 8px 0 2px; }
.pr-list { margin: 4px 0; padding-inline-start: 18px; }
`));
}
