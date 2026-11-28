// What each service and job may use, what's left, and who has seen a project (harness/usage.py, ui/usageapi.py).
// usageCard() for Settings, jobCaps() for Models, seenList(path) for a project's settings. Each shows nothing
// on an older PC without /api/usage. Short first: one line per service; the rest behind More.
import { h, fill, get, post, q, has, act, plural } from "./core.js";
import { t } from "./words.js";

const SERVICE_FIELDS = [
  ["usd_per_month", "$ a month", "The most this service may cost in a calendar month, across every project. Empty or 0: no limit", 0.5],
  ["usd_per_day", "$ a day", "The most this service may cost in one day, across every project. Empty or 0: no limit", 0.5],
  ["tokens_per_day", "Tokens a day", "The most text (in tokens) this service may handle in one day. Useful for the coding helpers on your subscriptions, which have no price. Empty or 0: no limit", 1000],
];
const JOB_FIELDS = [
  ["usd_per_project", "$ a project", "The most this job may cost on any one project. When it's reached the project waits for you. Empty or 0: no limit", 0.5],
  ["tokens_per_project", "Tokens a project", "The most text (in tokens) this job may use on any one project. Empty or 0: no limit", 1000],
];

usageStyles();

// Settings: one line per service ("DeepSeek: $3.10 of $20 this month"); the limits and the real balance behind More.
export function usageCard() {
  const box = h("section", { class: "card us" },
    h("div", { class: "card-head" }, h("h2", { title: "What each AI service has used, and the limits you set" }, "What's used")));
  const body = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  box.append(body);
  const load = async (balance) => {
    if (!(await has("/api/usage"))) { box.remove(); return; }
    try { fill(body, ...services(await get("/api/usage?" + q({ balance: balance ? 1 : "" })), load)); }
    catch (e) { fill(body, h("p", { class: "muted" }, "Couldn't read what's been used. Open Settings again to retry.")); }
  };
  load(false);
  return box;
}

function services(v, reload) {
  const list = v.services || [];
  if (!list.length) return [h("p", { class: "muted" }, "Nothing used yet.")];
  const lines = h("ul", { class: "us-lines" }, list.map((s) =>
    h("li", { class: s.reached ? "us-hit" : "", title: s.reached || "" }, s.words, s.reached ? h("b", {}, " · limit reached") : null)));
  const more = h("details", { class: "us-more" }, h("summary", { title: "Today's figures, the money left in each account, and your limits" }, "More"));
  const rows = list.map((s) => serviceRow(s));
  const save = h("button", { class: "btn", title: "Keep these limits. They apply to every project at once" }, "Save limits");
  save.addEventListener("click", () => act(save, async () => {
    const body = { services: {} };
    rows.forEach((r) => { body.services[r.id] = r.values(); });
    await post("/api/usage/limits", body);
    await reload(false);
  }, "Limits saved"));
  const bal = h("button", { class: "btn small", title: "Ask the services that say so how much money is left in your account" }, "Check the real balance");
  bal.addEventListener("click", () => act(bal, () => reload(true)));
  more.append(...rows.map((r) => r.el), h("div", { class: "us-acts" }, save, bal),
    h("p", { class: "muted small" }, v.note || ""));
  return [h("p", { class: "muted small" }, v.words || ""), lines, more];
}

function serviceRow(s) {
  const used = s.used || {};
  const facts = [
    `Today ${money(used.day_usd)}, ${plural(Number(used.day_tokens) || 0, "token")}`,
    `this month ${money(used.month_usd)}, ${plural(Number(used.month_tokens) || 0, "token")}`,
  ];
  const inputs = fields(SERVICE_FIELDS, s.caps || {}, s.name);
  const el = h("div", { class: "us-row" },
    h("div", { class: "us-name" }, h("b", {}, s.name),
      h("span", { class: "muted small" }, " · " + facts.join(", "))),
    s.balance_words ? h("div", { class: "small" + (s.balance ? "" : " muted") }, s.balance_words) : null,
    s.unpriced_words ? h("div", { class: "small muted", title: "Calls without a price count as nothing in dollars; their tokens are still counted" }, s.unpriced_words) : null,
    h("div", { class: "us-fields" }, inputs.els));
  return { id: s.id, el, values: inputs.values };
}

function fields(spec, caps, who) {
  const got = {};
  const els = spec.map(([key, label, tip, step]) => {
    const input = h("input", { type: "number", min: "0", step: String(step), value: caps[key] ? String(caps[key]) : "",
      placeholder: "No limit", "aria-label": `${who}: ${label}` });
    got[key] = input;
    return h("label", { class: "us-field", title: tip }, h("span", { class: "small muted" }, label), input);
  });
  return { els, values: () => Object.fromEntries(Object.entries(got).map(([k, el]) => [k, Number(el.value) || 0])) };
}

// Models → Jobs: how much each job may use on one project.
export function jobCaps() {
  const box = h("div", { class: "us" });
  (async () => {
    if (!(await has("/api/usage"))) { box.remove(); return; }
    try {
      const v = await get("/api/usage");
      const rows = (v.jobs || []).map((j) => ({ role: j.role, name: j.name, ...fields(JOB_FIELDS, j.caps || {}, j.name) }));
      const set = rows.filter((r) => Object.values(r.values()).some(Boolean)).length;
      const det = h("details", { class: "us-more" },
        h("summary", { title: "So one job can't run up the bill: when a job reaches its limit on a project, the project waits for you" },
          set ? t("Limits per project: set for {v1}", { v1: plural(set, "job") }) : "Limits per project: none set"));
      const save = h("button", { class: "btn" }, "Save job limits");
      save.addEventListener("click", () => act(save, async () => {
        const body = { jobs: {} };
        rows.forEach((r) => { body.jobs[r.role] = r.values(); });
        await post("/api/usage/limits", body);
      }, "Job limits saved"));
      det.append(...rows.map((r) => h("div", { class: "us-row" }, h("div", { class: "us-name" }, h("b", {}, r.name)),
        h("div", { class: "us-fields" }, r.els))), h("div", { class: "us-acts" }, save));
      fill(box, det);
    } catch (e) { fill(box, h("p", { class: "muted small" }, "Couldn't read the job limits. Open this page again to retry.")); }
  })();
  return box;
}

// A project's settings, under "Who may see it": which makers have received this project.
export function seenList(path) {
  const box = h("div", { class: "us us-seen" });
  (async () => {
    if (!(await has("/api/usage/seen"))) { box.remove(); return; }
    try {
      const v = await get("/api/usage/seen?" + q({ path }));
      const rows = v.makers || [];
      const more = rows.length ? h("details", { class: "us-more" }, h("summary", { title: "Each maker, the service it came through, and when" }, "More"),
        h("ul", { class: "us-lines" }, rows.map((r) => h("li", {},
          t("{maker_name} through {service_name}: {v1}, first {v2}, last {v3}", { maker_name: r.maker_name, service_name: r.service_name, v1: plural(r.calls, "call"), v2: day(r.first), v3: day(r.last) })))),
        h("p", { class: "muted small" }, v.note || "")) : null;
      fill(box, h("p", { class: "small", title: "Every model that was sent this project's work, counted by the company that made it" }, v.words), more);
    } catch (e) { box.remove(); }
  })();
  return box;
}

const money = (x) => { const n = Number(x) || 0; return "$" + (n > 0 && n < 0.01 ? n.toFixed(4) : n.toFixed(2)); };
const day = (ts) => { const d = new Date(ts); return isNaN(d) ? "–" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };

function usageStyles() {
  if (typeof document === "undefined" || document.getElementById("us-style")) return;
  document.head.append(h("style", { id: "us-style" }, `
.us-lines { margin: 4px 0; padding-inline-start: 18px; }
.us-lines li { margin: 2px 0; }
.us-hit { color: var(--color-warn); }
.us-more { margin-top: 6px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); padding: 4px 10px; }
.us-more > summary { cursor: pointer; padding: 2px 0; }
.us-row { padding: 8px 0; border-top: 1px solid var(--color-line); }
.us-row:first-of-type { border-top: none; }
.us-name { margin-bottom: 4px; }
.us-fields { display: flex; flex-wrap: wrap; gap: 10px; }
.us-field { display: flex; flex-direction: column; gap: 2px; min-width: 120px; }
.us-field input { width: 120px; font-family: var(--font-body); background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-line-strong); border-radius: var(--radius-small); padding: 4px 6px; }
.us-acts { display: flex; gap: 8px; margin: 8px 0 4px; flex-wrap: wrap; }
`));
}
