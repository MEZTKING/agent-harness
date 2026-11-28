// Models: who does each job (and their backups) for every set of models, the models' health, and what the harness
// has learned from its own runs. Every choice is made from a list; nothing is typed in code.
import { h, fill, get, post, S, act, card, page, tabs, empty, ago, money, plural, every, patch, jobName, modelName, toast, dialog, seg, readable, has } from "./core.js";
import { strengthsTab } from "./strengths.js";
import { jobCaps } from "./usage.js";
import { learnedTab } from "./learned.js";
import { walletCard } from "./wallet.js";
import { permsCell } from "./perms.js";
import { t as wt } from "./words.js";

export async function viewModels(tab = "jobs") {
  if (!S.ov.harness) return page("Models", null, card("The harness can't build on this computer yet",
    h("p", {}, "Its settings are missing or have a problem. Open Settings to set it up."), h("a", { class: "btn primary", href: "#/settings" }, "Open Settings")));
  const t = tabs([["jobs", "Who does what", "Which model does each job, and its backups"], ["health", "Health check", "Whether each model answers like it usually does"],
    ["strengths", "Strengths", "What each model is best at, learned from real runs"],
    ["agents", "Agents", "Your named agents: one for each job, with a face, notes and what they learned"],
    ["learning", "What it learned", "What the harness changed from its own runs, each with an Undo, and what waits for you"]], tab, (k) => `#/models${k === "jobs" ? "" : "/" + k}`);
  const body = tab === "health" ? await health() : tab === "learning" ? await learning() : tab === "strengths" ? await strengthsTab()
    : tab === "agents" ? await agents() : await jobs();
  return page("Models", tab === "jobs" ? "Each job goes to the model you choose; if it can't answer, its backups take over in order." : null, t, body);
}

async function agents() { const { agentsTab } = await import("./agents.js"); return agentsTab(); }

async function loadRouting() { S.routing = await get("/api/routing"); return S.routing; }

// Your other machines and phone follow the base choices and the default set too (shared settings, when the hub is there).
async function share(changes) {
  if (!S.ov.hub || !(await has("/api/settings/shared"))) return;
  try { await post("/api/settings/shared", { changes }); } catch (e) { toast(wt("Saved here, but your other machines weren't told: {message}", { message: e.message }), true); }
}

// ---------- who does what ----------
let shownSet = null;
async function jobs() {
  const R = await loadRouting();
  const box = h("div", { class: "stack" });
  const draw = () => {
    const sets = R.sets;
    if (shownSet === null || (shownSet && !sets.some((s) => s.id === shownSet))) shownSet = R.default_set || (sets[0] || {}).id || "";
    const setTabs = sets.length ? h("div", { class: "set-tabs" },
      seg([...sets.map((s) => [s.id, s.name + (s.id === R.default_set ? " (used by default)" : ""), s.about]), ["", "Base choice", "Used when a set doesn't name the job"]],
        shownSet, (v) => { shownSet = v; draw(); }, "Set of models"),
      shownSet && shownSet !== R.default_set ? h("button", { class: "small", title: "Every project uses this set unless it picks its own (on its Settings tab)",
        onclick: (ev) => act(ev.currentTarget, async () => { const r = await post("/api/routing", { default_set: shownSet }); await share({ default_profile: shownSet }); return r; }, "Done: projects use this set unless they pick their own", async (r) => { Object.assign(R, r); S.routing = R; draw(); }) }, "Use this set by default") : null) : null;
    const about = shownSet ? (sets.find((s) => s.id === shownSet) || {}).about : "Used for a job when the set a project uses doesn't name it.";
    const warn = (R.warnings || []).length ? h("div", {}, R.warnings.map((w) => h("p", { class: "warn small",
      title: "A checker from another maker catches more. Add a model from another company to the reviewer job, or keep it as it is" }, w))) : null;
    fill(box, warn, setTabs, about ? h("p", { class: "muted small" }, about[0].toUpperCase() + about.slice(1) + (/[.]$/.test(about) ? "" : ".")) : null,
      card(null, h("div", { class: "jobs-table", role: "table", "aria-label": "Who does each job" },
        h("div", { class: "jt-row jt-head", role: "row" }, h("span", { role: "columnheader" }, "Job"), h("span", { role: "columnheader" }, "Does the work"), h("span", { role: "columnheader" }, "If it can't answer"), h("span", {})),
        R.jobs.map((j) => jobRow(R, j, shownSet, draw)))),
      jobCaps(), keysNote(R));
  };
  draw();
  return box;
}

function entryFor(j, set) { return (set && j.sets[set]) || j.base; }
function keyOk(R, ref) { const p = R.providers[String(ref).split("/")[0]]; return !p || !p.needs_key || p.key_set; }

function jobRow(R, j, set, redraw) {
  const e = entryFor(j, set), inherited = set && !j.sets[set];
  const [main, ...backups] = e.models;
  const row = h("div", { class: "jt-row", role: "row" },
    h("span", { role: "cell", class: "jt-job" }, h("b", { title: j.about }, j.name), h("small", { class: "muted" }, j.about),
      j.kind === "image" ? h("span", { class: "pill" }, "pictures") : null, j.learned ? h("span", { class: "pill good", title: "The harness changed this from what it learned (Learning tab)" }, "learned") : null),
    h("span", { role: "cell" }, modelChip(R, main), e.effort ? h("span", { class: "pill", title: "How hard it thinks before answering" }, wt("thinks: {effort}", { effort: e.effort })) : null,
      inherited ? h("small", { class: "muted", title: "This set doesn't name this job, so the base choice is used" }, " · base choice") : null),
    h("span", { role: "cell", class: "jt-backups" }, backups.length ? backups.map((m) => modelChip(R, m, true)) : h("span", { class: "muted small" }, "No backup")),
    h("span", { role: "cell" }, h("button", { class: "small", title: wt("Choose who does the {name} job", { name: j.name }), onclick: () => row.replaceWith(editor(R, j, set, redraw)) }, "Change")));
  // what this job may do (perms.js): filled in when it's known, nothing on an older app
  permsCell(j.role).then((el) => { if (el) row.querySelector(".jt-job").append(el); }).catch(() => {});
  return row;
}
function modelChip(R, m, small = false) {
  if (!m) return h("span", { class: "muted" }, "Nobody");
  const ok = keyOk(R, m.ref);
  return h("span", { class: "mchip" + (small ? " small" : "") + (ok ? "" : " nokey"), title: ok ? m.label : wt("{label}: there's no key for {v1} yet, so it's skipped", { label: m.label, v1: R.providers[m.ref.split("/")[0]].name }) },
    m.label, ok ? null : h("a", { href: `#/settings/keys`, class: "addkey", title: "Add the key in Settings" }, "add the key"));
}

function editor(R, j, set, redraw) {
  const e = entryFor(j, set);
  const list = e.models.map((m) => m.ref);
  let effort = e.effort || "";
  const rows = h("ol", { class: "pick-list" });
  const choices = () => {
    const groups = {};
    for (const c of R.choices) (groups[R.providers[c.provider] ? R.providers[c.provider].name : c.provider] ||= []).push(c);
    return groups;
  };
  const picker = (ref, i) => {
    const sel = h("select", { "aria-label": i ? wt("Backup {i}", { i }) : "Does the work", onchange: async (ev) => {
      if (ev.target.value === "__other") {
        const v = await otherModel(R);
        if (v) { if (!R.choices.some((c) => c.ref === v)) R.choices.push({ ref: v, label: modelName(v), provider: v.split("/")[0] }); list[i] = v; }
        draw(); return;
      }
      list[i] = ev.target.value; draw();
    } },
    Object.entries(choices()).map(([g, cs]) => h("optgroup", { label: g }, cs.map((c) => h("option", { value: c.ref, selected: c.ref === ref }, c.label.replace(/ \([^)]*\)$/, "") + (keyOk(R, c.ref) ? "" : " – no key yet"))))),
    !R.choices.some((c) => c.ref === ref) ? h("option", { value: ref, selected: true }, modelName(ref)) : null,
    h("option", { value: "__other" }, "Another model…"));
    return h("li", {}, h("span", { class: "label" }, i ? wt("Backup {i}", { i }) : "Does the work"), sel,
      h("span", { class: "row" },
        i > 0 ? h("button", { type: "button", class: "icon", title: "Move up", "aria-label": "Move up", onclick: () => { [list[i - 1], list[i]] = [list[i], list[i - 1]]; draw(); } }, "↑") : null,
        list.length > 1 ? h("button", { type: "button", class: "icon danger", title: "Take it off", "aria-label": "Take it off", onclick: () => { list.splice(i, 1); draw(); } }, "×") : null));
  };
  const draw = () => fill(rows, list.map(picker));
  draw();
  const save = h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, async () => {
    const r = await post("/api/routing", { role: j.role, models: list, set: set || "", ...(set ? { effort } : {}) });
    if (!set) await share({ roles: { [j.role]: list.length === 1 ? list[0] : list } });
    return r;
  },
    wt("{name}: saved", { name: j.name }), (r) => { Object.assign(R, r); S.routing = R; redraw(); }) }, "Save");
  return h("div", { class: "jt-edit", role: "row" },
    h("div", { class: "jt-edit-head" }, h("b", {}, wt("Who does the {name} job", { name: j.name })), h("span", { class: "muted small" }, set ? wt("in the {v1} set", { v1: (R.sets.find((s) => s.id === set) || {}).name }) : "when a set doesn't say")),
    rows,
    h("div", { class: "row" }, h("button", { type: "button", class: "small", onclick: () => { list.push(R.choices.find((c) => !list.includes(c.ref))?.ref || list[0]); draw(); } }, "+ Add a backup"),
      set && j.kind !== "image" ? h("label", { class: "row small", title: "How hard it thinks before answering: harder is slower and costs more, and is better at difficult work" }, "Thinks",
        h("select", { onchange: (ev) => { effort = ev.target.value; } }, [["", "as usual"], ...R.efforts.map((x) => [x, x])].map(([v, t]) => h("option", { value: v, selected: v === effort }, t)))) : null),
    h("div", { class: "row" }, save, h("button", { onclick: () => redraw() }, "Cancel")));
}

// a model not in the list: choose the service, then pick from its own list (or type the name it uses)
async function otherModel(R) {
  const pids = Object.keys(R.providers);
  const prov = h("select", { "aria-label": "Service" }, pids.map((p) => h("option", { value: p }, R.providers[p].name)));
  const name = h("input", { class: "grow", placeholder: "The model's name, as the service writes it", "aria-label": "Model name", list: "known-names" });
  const names = h("datalist", { id: "known-names" });
  const note = h("p", { class: "muted small" });
  const fetchNames = async () => {
    note.textContent = "Asking the service for its models…";
    try { const r = await post("/api/providers", { action: "models", id: prov.value }); fill(names, r.models.map((m) => h("option", { value: m }))); note.textContent = `${plural(r.models.length, "model")} found: start typing to pick one.`; }
    catch (e) { note.textContent = e.message; }
  };
  const body = h("div", { class: "stack" }, h("label", { class: "field" }, h("span", { class: "label" }, "Service"), prov),
    h("div", { class: "row" }, name, h("button", { type: "button", class: "small", title: "Ask the service which models it has", onclick: fetchNames }, "List its models")), names, note);
  const ok = await dialog({ title: "Another model", text: "Choose the service it comes from, then the model.", yes: "Use it", body, wide: true });
  return ok && name.value.trim() ? `${prov.value}/${name.value.trim()}` : null;
}

function keysNote(R) {
  const missing = Object.entries(R.providers).filter(([pid, p]) => p.needs_key && !p.key_set && R.jobs.some((j) => [j.base, ...Object.values(j.sets)].some((e) => e.models.some((m) => m.ref.startsWith(pid + "/")))));
  if (!missing.length) return null;
  return card("Some models have no key yet", h("p", {}, wt("Without a key they're skipped and the backup does the job: {v1}.", { v1: missing.map(([, p]) => p.name).join(", ") })),
    h("a", { class: "btn primary", href: "#/settings/keys" }, "Add the keys"));
}

// ---------- health ----------
const PROBE = { OK: ["Fine", "good"], NEW: ["First check", "info"], SLOW: ["Slower than usual", "warn"], FAST: ["Faster than usual", "good"], VERBOSE: ["Wordier than usual", "warn"],
  DOWN: ["Not answering", "bad"], REGRESSION: ["Worse than usual", "bad"], BOOST: ["Better than usual", "good"] };
const probePill = (s) => { const [w, c] = PROBE[s] || [readable(s), ""]; return h("span", { class: "pill " + c }, w); };
async function health() {
  const R = S.routing || await loadRouting();
  const box = h("div", { class: "stack" });
  let which = "", images = false;
  const run = card("Check the models",
    h("p", { class: "muted small" }, "Short tests each model is marked on (using tools, writing data, following instructions, reasoning, fixing a bug), compared with how it usually does. Run it before big changes; it costs a few cents."),
    h("div", { class: "row" }, h("select", { "aria-label": "Which models", onchange: (ev) => { which = ev.target.value; } },
      h("option", { value: "" }, "Every model"), R.jobs.map((j) => h("option", { value: j.role }, wt("The {name} job's models", { name: j.name })))),
    h("label", { class: "check", title: "Also makes one test picture (a few cents more)" }, h("input", { type: "checkbox", onchange: (ev) => { images = ev.target.checked; } }), "Picture models too"),
    h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, () => post("/api/probes", { roles: which ? [which] : [], images }), "Checking the models…", () => { live._sig = undefined; }) }, "Check now")));
  const live = h("div");
  const hist = h("div");
  every(box, async () => {
    const [jobs, probes] = await Promise.all([get("/api/jobs"), get("/api/probes")]);
    const running = jobs.find((j) => j.target === "probe" && j.status === "running"), last = jobs.find((j) => j.target === "probe");
    let full = null;
    if (running) full = await get(`/api/jobs/${running.id}`);
    patch(live, JSON.stringify([running && full.log.length, last && last.status]), () => running ? card("Checking now…", h("pre", { class: "log short" }, full.log.join("\n") || "Starting…"))
      : last && Array.isArray(last.result) ? card(wt("The latest check, {v1}", { v1: ago(last.ended) }), h("table", { class: "plain-table" },
        h("tr", {}, h("th", {}, "Model"), h("th", { class: "num" }, "Passed"), h("th", { class: "num" }, "Usually"), h("th", { class: "num" }, "Seconds"), h("th", {}, "How it did"), h("th", {}, "Notes")),
        last.result.map((r) => h("tr", {}, h("td", {}, modelName(r.model)), h("td", { class: "num" }, wt("{passed} of {total}", { passed: r.passed, total: r.total })),
          h("td", { class: "num" }, r.baseline_score === null ? "–" : Math.round(r.baseline_score * 100) + "%"), h("td", { class: "num" }, r.seconds.toFixed(1)),
          h("td", {}, r.status.map(probePill)), h("td", { class: "small" }, r.notes.join("; ")))))) : null);
    patch(hist, JSON.stringify(probes.models.map((m) => [m.model, m.runs.length])), () => card("Over time", probes.models.length ? h("table", { class: "plain-table" },
      h("tr", {}, h("th", {}, "Model"), h("th", {}, "Checks, oldest to newest"), h("th", {}, "Latest")),
      probes.models.map((m) => { const r = m.runs[m.runs.length - 1]; return h("tr", {}, h("td", {}, modelName(m.model)), h("td", {}, spark(m.runs)),
        h("td", { class: "small" }, wt("{passed} of {total} · {v1}", { passed: r.passed, total: r.total, v1: ago(r.at) }), h("details", {}, h("summary", {}, "Each test"),
          h("ul", { class: "plain small" }, r.results.map((x) => h("li", {}, x.passed ? "✓ " : "✗ ", readable(x.probe), ` · ${(x.seconds || 0).toFixed(1)}s`, x.error || x.detail ? h("span", { class: "muted" }, ` · ${x.error || x.detail}`) : null)))))); }))
      : empty("No checks yet. Press Check now to see how each model is doing.")));
    if (!running) return undefined;
  }, () => 4000);
  fill(box, run, live, hist);
  return box;
}
function spark(runs) {
  return h("span", { class: "spark", title: "Each mark is one check, oldest first" }, runs.slice(-15).map((r) => {
    const f = r.total ? r.passed / r.total : 0;
    return h("i", { class: f === 1 ? "ok" : f >= 0.6 ? "mid" : "no", title: wt("{v1}: {passed} of {total}", { v1: new Date(r.at).toLocaleString(), passed: r.passed, total: r.total }) });
  }));
}

// ---------- learning ----------
const POLICY = { none: "The harness only suggests: nothing changes until you choose Use it.", low: "The harness uses small, tested changes by itself; anything bigger waits for you.",
  medium: "The harness uses small and medium tested changes by itself; big ones wait for you." };
const RISK = { low: "Small change", medium: "Medium change", high: "Big change" };
const PSTATE = { proposed: ["Suggested", "info"], tested: ["Tested", "info"], applied: ["In use", "good"], rejected: ["Turned down", ""], rolled_back: ["Undone", "warn"] };
function describe(p) {
  const job = jobName(p.role);
  if (p.kind === "routing") return `${job}: ${(p.change.models || []).map((m) => modelName(m)).join(", then ")}`;
  if (p.kind === "options") return `${job}: ${Object.entries(p.change.options || {}).map(([k, v]) => (k === "effort" ? `thinks ${v}` : `${readable(k).toLowerCase()} ${v}`)).join(", ")}`;
  return `${job}: new instructions`;
}
async function learning() {
  const R = S.routing || await loadRouting();
  // learning's weekly money on top, then what it learned (one line each, with Undo), what waits for you (today's
  // suggestions among it) and what it can never change (improve/ledger.py)
  return h("div", { class: "stack" }, walletCard(), await learnedTab({ suggestions: (reload) => suggestions(R, reload), walletLine: false }));
}
async function suggestions(R, reload) {
  const [data, jobs] = await Promise.all([get("/api/proposals"), get("/api/jobs")]);
  const running = jobs.find((j) => j.target === "improve" && j.status === "running");
  const startJob = (body, msg) => (ev) => act(ev.currentTarget, () => post("/api/improve", body), msg, (j) => { if (j && j.id) location.hash = `#/activity/work/${j.id}`; });
  const open = data.proposals.filter((p) => ["proposed", "tested"].includes(p.status));
  const closed = data.proposals.filter((p) => ["rejected"].includes(p.status));
  const prop = (p) => {
    const [w, c] = PSTATE[p.status] || [readable(p.status), ""];
    return h("article", { class: "proposal" },
      h("div", { class: "row" }, h("b", { class: "grow" }, describe(p)), h("span", { class: "pill " + c }, w), h("span", { class: "pill" }, RISK[p.risk] || p.risk),
        h("span", { class: "muted small" }, p.source === "owner" ? "your idea" : "the harness's idea", ` · ${ago(p.created_at)}`)),
      h("details", {}, h("summary", { class: "small" }, "More"), h("p", { class: "small" }, p.rationale),
        p.kind === "prompt" ? h("p", { class: "pre-line small" }, p.change.prompt_text) : null),
      p.test ? h("p", { class: "small" }, wt("Tested on {v1}: now {approved} approved for {v2}, with the change {approved2} for {v3}. ", { v1: plural(p.test.tasks_compared, "earlier task"), approved: p.test.current.approved, v2: money(p.test.current.cost_usd), approved2: p.test.candidate.approved, v3: money(p.test.candidate.cost_usd) }),
        h("b", {}, p.test.passed ? "Better or as good." : "Not better."), p.test.note ? ` ${p.test.note}` : "") : null,
      ["proposed", "tested"].includes(p.status) ? h("div", { class: "row" },
        h("button", { disabled: !!running, title: "Tries the change on practice tasks and a few earlier tasks, to compare (up to $2)", onclick: startJob({ action: "test", id: p.id, samples: 3, max_cost: 2 }, "Testing it…") }, "Test it"),
        h("button", { class: "primary", disabled: !!running, title: "Checks the models answer, then uses it", onclick: startJob({ action: "apply", id: p.id }, "Using it…") }, "Use it"),
        h("button", { disabled: !!running, title: "Use it without a passed test", onclick: async (ev) => {
          if (await dialog({ title: "Use it without a test?", text: "It hasn't passed a test yet. You can undo it later under What it learned.", yes: "Use it anyway" })) startJob({ action: "apply", id: p.id, force: true }, "Using it…")(ev);
        } }, "Use it without a test"),
        h("button", { class: "danger", onclick: (ev) => act(ev.currentTarget, () => post("/api/improve", { action: "reject", id: p.id }), "Turned down", reload) }, "Turn down")) : null);
  };
  return h("div", { class: "stack" },
    h("p", {}, POLICY[data.policy] || wt("Policy: {policy}.", { policy: data.policy })),
    h("div", { class: "row" },
      h("button", { class: "primary", disabled: !!running, title: "Looks through the finished tasks for better choices (free)", onclick: startJob({ action: "analyze" }, "Looking…") }, "Look for improvements"),
      h("button", { disabled: !!running, title: "A model reads the history too and suggests changes (up to $2)", onclick: startJob({ action: "analyze", llm: true, max_cost: 2 }, "A model is looking…") }, "Ask a model to look"),
      running ? h("a", { href: `#/activity/work/${running.id}` }, "Working on it now…") : null),
    open.length ? open.map(prop) : h("p", { class: "muted" }, "No suggestions waiting. Press Look for improvements after a few projects, or suggest one below."),
    suggest(R, reload),
    closed.length ? h("details", { class: "fold" }, h("summary", {}, wt("Turned down ({length})", { length: closed.length })), closed.map(prop)) : null);
}
function suggest(R, reload) {
  let kind = "routing";
  const role = h("select", { "aria-label": "Which job" }, R.jobs.map((j) => h("option", { value: j.role }, j.name)));
  const model = h("select", { "aria-label": "Model" }, R.choices.map((c) => h("option", { value: c.ref }, c.label)));
  const backup = h("select", { "aria-label": "Backup" }, h("option", { value: "" }, "No backup"), R.choices.map((c) => h("option", { value: c.ref }, c.label)));
  const effort = h("select", { "aria-label": "How hard it thinks" }, R.efforts.map((x) => h("option", { value: x }, x)));
  const text = h("textarea", { rows: 6, placeholder: "The job's complete new instructions", "aria-label": "New instructions" });
  const why = h("input", { class: "grow", placeholder: "Why? (optional)", "aria-label": "Why" });
  const risk = h("select", { "aria-label": "How big a change" }, Object.entries(RISK).map(([k, v]) => h("option", { value: k, selected: k === "medium" }, v)));
  const parts = h("div", { class: "stack" });
  const draw = () => fill(parts, kind === "routing" ? h("div", { class: "row" }, h("span", { class: "label" }, "Does the work"), model, h("span", { class: "label" }, "Backup"), backup)
    : kind === "options" ? h("div", { class: "row" }, h("span", { class: "label" }, "Thinks"), effort) : text);
  draw();
  return h("details", { class: "card fold" }, h("summary", {}, "Suggest a change yourself"),
    h("p", { class: "muted small" }, "It waits with the others: test it, then use it. To change a job straight away, use Who does what instead."),
    h("div", { class: "row" }, h("span", { class: "label" }, "Job"), role, seg([["routing", "Its models"], ["options", "How hard it thinks"], ["prompt", "Its instructions"]], kind, (v) => { kind = v; draw(); }, "What to change")),
    parts, h("div", { class: "row" }, why, risk,
      h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, () => post("/api/improve", { action: "propose", role: role.value, kind, why: why.value, risk: risk.value,
        models: [model.value, backup.value].filter(Boolean), options: { effort: effort.value }, prompt_text: text.value }), "Suggestion added", reload) }, "Add the suggestion")));
}
