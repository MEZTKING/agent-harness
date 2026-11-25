// Agent Hub UI - vanilla JS, no build step. Every node is built with h() (textContent),
// never innerHTML, because journal entries, messages and logs contain model output.
"use strict";

// ---------- helpers ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $main = () => document.getElementById("main");
function toast(text, err = false) {
  const t = h("div", { class: "toast" + (err ? " err" : "") }, text);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), err ? 7000 : 3500);
}
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.headers["X-Agent-Hub"] = "1";
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* non-json */ }
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}
async function act(fn, ok) {  // run an action, toast result or error, then re-render
  try { const r = await fn(); if (ok) toast(typeof ok === "function" ? ok(r) : ok); await render(); return r; }
  catch (e) { toast(e.message, true); }
}
function ago(ts) {
  if (!ts) return "never";
  const s = Math.floor((Date.now() - Date.parse(ts)) / 1000);
  if (s < 60) return "just now";
  for (const [u, n] of [["d", 86400], ["h", 3600], ["m", 60]]) if (s >= n) return `${Math.floor(s / n)}${u} ago`;
}
const money = (x) => "$" + (Number(x) || 0).toFixed(x && x < 0.1 ? 4 : 2);
function statusPill(s) {
  const cls = { done: "good", approved: "good", applied: "good", OK: "good", ok: "good", BOOST: "good", running: "info",
    tested: "info", proposed: "info", pending: "", NEW: "info", failed: "bad", blocked: "bad", REGRESSION: "bad", DOWN: "bad",
    rejected: "", rolled_back: "warn", awaiting_approval: "warn", paused_budget: "warn", paused: "warn", SLOW: "warn",
    VERBOSE: "warn", planning: "info" }[s] ?? "";
  return h("span", { class: "pill " + cls }, String(s || "?").replace(/_/g, " "));
}
const field = (name, attrs = {}) => h("input", { name, ...attrs });
function formData(form) { return Object.fromEntries(new FormData(form).entries()); }
function select(name, options, value, attrs = {}) {
  return h("select", { name, ...attrs }, options.map((o) => {
    const [v, label] = Array.isArray(o) ? o : [o, o];
    return h("option", { value: v, selected: v === value }, label);
  }));
}
const section = (title, ...kids) => h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, title)), ...kids);

// ---------- state & routing ----------
let OV = null;          // overview
let timer = null;       // auto-refresh timer for the current view
function route() { const p = (location.hash || "#/where").slice(2).split("?")[0].split("/"); return [p[0] || "where", ...p.slice(1).map(decodeURIComponent)]; }
function setActive(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name ||
    (name === "project" && a.dataset.nav === "projects") || (name === "run" && a.dataset.nav === "runs") ||
    (name === "job" && a.dataset.nav === "jobs")));
}
async function render(auto = false) {
  clearTimeout(timer);
  const [view, ...args] = route();
  setActive(view);
  try {
    OV = await api("GET", "/api/overview");
    document.querySelectorAll("[data-harness]").forEach((e) => (e.hidden = !OV.harness));
    const badge = document.getElementById("jobs-badge");
    badge.hidden = !OV.running_jobs; badge.textContent = OV.running_jobs;
    document.getElementById("nav-foot").textContent = OV.hub ? `hub: ${OV.hub_path}` : "";
    const views = { where: viewWhere, projects: viewProjects, project: viewProject, messages: viewMessages,
      runs: viewRuns, run: viewRun, models: viewModels, improve: viewImprove, jobs: viewJobs, job: viewJob };
    const node = await (views[view] || viewWhere)(...args);
    const typing = document.activeElement && $main().contains(document.activeElement) && document.activeElement.value;
    if (auto && typing) { autoRefresh(3000); return; } // don't clobber what the user is typing
    $main().replaceChildren(node);
  } catch (e) {
    $main().replaceChildren(h("div", { class: "card" }, h("h2", {}, "Something went wrong"), h("p", { class: "muted" }, e.message)));
  }
}
function autoRefresh(ms) { clearTimeout(timer); timer = setTimeout(() => render(true), ms); }
window.addEventListener("hashchange", () => render());

function needHub() {
  if (OV.hub) return null;
  return h("div", { class: "card" }, h("h2", {}, "Hub not configured"),
    h("p", { class: "muted" }, OV.hub_error || ""), h("p", {}, "Set HUB_CONFIG or pass --hub-config to agent-hub ui."));
}
function needHarness() {
  if (OV.harness) return null;
  return h("div", { class: "card" }, h("h2", {}, "Harness not configured"),
    h("p", { class: "muted" }, OV.harness_error || ""), h("p", {}, "Set HARNESS_CONFIG or pass --harness-config to agent-hub ui."));
}

// ---------- journal widgets ----------
function entryActions(agent, e) {
  return h("span", { class: "row" },
    h("button", { class: "icon", title: "Done", onclick: () => act(() => api("POST", `/api/journal/${agent}/${e.id}/close`, {}), "Marked done") }, "✓ done"),
    h("button", { class: "icon danger", title: "Drop", onclick: () => act(() => api("POST", `/api/journal/${agent}/${e.id}/close`, { dropped: true }), "Dropped") }, "✕"));
}
function quickAdd(agent, compact = false) {
  const next = h("textarea", { name: "next", placeholder: "Next steps, one per line", hidden: true });
  const prio = select("priority", [["normal", "normal"], ["high", "high priority"], ["low", "low"]], "normal");
  const kind = select("kind", ["todo", "done", "plan", "decision", "note", "session"], "todo", {
    onchange: (ev) => { next.hidden = ev.target.value !== "session"; prio.hidden = !["todo", "plan"].includes(ev.target.value); },
  });
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const d = formData(form);
    if (!d.text.trim()) return;
    const body = { kind: d.kind, text: d.text, priority: d.priority };
    if (d.kind === "session") body.next = (d.next || "").split("\n").map((s) => s.trim()).filter(Boolean);
    await act(() => api("POST", `/api/journal/${agent}`, body), `Logged ${d.kind}`);
  } },
  h("div", { class: "row" }, kind, field("text", { class: "grow", placeholder: compact ? "Add to journal…" : "What happened, or what needs doing?", autocomplete: "off" }), prio, h("button", { class: "primary" }, "Add")),
  next);
  return form;
}
function briefCard(b, full = false) {
  const s = b.last_session;
  return h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", {}, h("a", { href: `#/project/${encodeURIComponent(b.agent)}` }, b.agent)),
      h("span", { class: "muted small" }, b.repo ? b.repo + " · " : "", b.last_activity ? ago(b.last_activity) : "no activity")),
    b.description && full ? h("p", { class: "muted small" }, b.description) : null,
    s ? h("div", { class: "session" }, h("div", {}, h("strong", {}, "Last session "), h("span", { class: "muted small" }, ago(s.created_at))),
      h("div", {}, s.text), s.next.length ? h("ul", { class: "next" }, s.next.map((n) => h("li", {}, n))) : null) : null,
    h("h3", {}, `To do (${b.open_todos.length})`),
    b.open_todos.length ? h("ul", { class: "items" }, b.open_todos.slice(0, full ? 999 : 6).map((e) =>
      h("li", {}, h("span", { class: "text" }, e.priority === "high" ? h("span", { class: "prio-high" }, "! ") : null, e.text,
        h("span", { class: "muted small" }, ` · ${e.id}`)), entryActions(b.agent, e)))) : h("div", { class: "empty" }, "Nothing open"),
    b.open_todos.length > 6 && !full ? h("div", { class: "small" }, h("a", { href: `#/project/${b.agent}` }, `+ ${b.open_todos.length - 6} more`)) : null,
    b.open_plans.length ? [h("h3", {}, `Plans (${b.open_plans.length})`), h("ul", { class: "items" },
      b.open_plans.slice(0, full ? 999 : 4).map((e) => h("li", {}, h("span", { class: "text" }, e.text), entryActions(b.agent, e))))] : null,
    b.recent_done.length ? [h("h3", {}, "Recently done"), h("ul", { class: "items" },
      b.recent_done.slice(-(full ? 5 : 3)).reverse().map((e) => h("li", {}, h("span", { class: "text" }, e.text), h("span", { class: "muted small" }, ago(e.created_at)))))] : null,
    full && b.recent_decisions.length ? [h("h3", {}, "Decisions"), h("ul", { class: "items" }, b.recent_decisions.map((e) => h("li", {}, h("span", { class: "text" }, e.text))))] : null,
    h("div", { style: "margin-top:12px" }, quickAdd(b.agent, true)));
}

// ---------- views ----------
async function viewWhere() {
  if (!OV.hub) return needHub();
  const briefs = await api("GET", "/api/where");
  const active = briefs.filter((b) => b.last_activity), quiet = briefs.filter((b) => !b.last_activity);
  const todos = active.reduce((n, b) => n + b.open_todos.length, 0);
  const high = active.reduce((n, b) => n + b.open_todos.filter((e) => e.priority === "high").length, 0);
  return h("div", {},
    h("h1", {}, "Where was I?"),
    h("p", { class: "sub" }, `${active.length} active project(s) · ${todos} open todo(s)`, high ? h("span", { class: "prio-high" }, ` · ${high} high priority`) : null),
    active.length ? h("div", { class: "grid" }, active.map((b) => briefCard(b))) : h("div", { class: "card" }, "No journal entries yet. Add one below or with ", h("code", {}, "agent-hub log todo \"…\"")),
    quiet.length ? h("div", { class: "card", style: "margin-top:14px" }, h("h2", {}, "Quiet projects"),
      h("ul", { class: "items" }, quiet.map((b) => h("li", {}, h("span", { class: "text" }, h("a", { href: `#/project/${b.agent}` }, b.agent), " ",
        h("span", { class: "muted small" }, b.description || ""))))) ) : null);
}

async function viewProjects() {
  if (!OV.hub) return needHub();
  const [cards, briefs] = await Promise.all([api("GET", "/api/cards"), api("GET", "/api/where")]);
  const byAgent = Object.fromEntries(briefs.map((b) => [b.agent, b]));
  return h("div", {}, h("h1", {}, "Projects"), h("p", { class: "sub" }, "Every agent in the hub and what it's doing."),
    h("div", { class: "card" }, h("table", {},
      h("tr", {}, h("th", {}, "Project"), h("th", {}, "Status"), h("th", {}, "Summary"), h("th", { class: "num" }, "Todos"), h("th", {}, "Last activity")),
      cards.map((c) => { const b = byAgent[c.agent] || {}; return h("tr", {},
        h("td", {}, h("a", { href: `#/project/${encodeURIComponent(c.agent)}` }, c.agent), h("div", { class: "muted small" }, c.repo)),
        h("td", {}, c.status || h("span", { class: "muted" }, "-")), h("td", { class: "small" }, c.summary),
        h("td", { class: "num" }, (b.open_todos || []).length), h("td", { class: "small muted" }, ago(b.last_activity))); }))));
}

async function viewProject(agent) {
  if (!OV.hub) return needHub();
  const [briefs, cards, entries] = await Promise.all([api("GET", "/api/where"), api("GET", "/api/cards"),
    api("GET", `/api/journal/${encodeURIComponent(agent)}`)]);
  const b = briefs.find((x) => x.agent === agent), card = cards.find((c) => c.agent === agent);
  if (!b) return h("div", { class: "card" }, `Unknown project ${agent}`);
  let filter = "all";
  const list = h("div");
  const draw = () => list.replaceChildren(h("table", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Kind"), h("th", {}, "Entry"), h("th", {}, "State")),
    entries.filter((e) => filter === "all" || e.kind === filter).reverse().map((e) => h("tr", {},
      h("td", { class: "small muted" }, e.created_at.replace("T", " ").slice(0, 16)), h("td", {}, h("span", { class: "pill" }, e.kind)),
      h("td", {}, e.priority === "high" ? h("span", { class: "prio-high" }, "! ") : null, e.text,
        e.next.length ? h("ul", { class: "small" }, e.next.map((n) => h("li", {}, n))) : null,
        e.details ? h("details", {}, h("summary", { class: "small" }, "details"), h("pre", {}, e.details)) : null,
        h("div", { class: "muted small" }, e.id, e.source ? ` · via ${e.source}` : "")),
      h("td", {}, e.status ? statusPill(e.status) : null, e.status === "open" ? entryActions(agent, e) : null)))));
  const tabs = h("div", { class: "tabs" }, ["all", "session", "todo", "plan", "done", "decision", "note"].map((k) =>
    h("button", { class: k === filter ? "on" : "", onclick: (ev) => { filter = k; tabs.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === ev.target)); draw(); } }, k)));
  draw();
  const cardForm = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault(); const d = formData(cardForm);
    await act(() => api("POST", `/api/cards/${agent}`, d), "Card saved");
  } },
  ["summary", "goal", "status"].map((k) => h("label", { class: "stack" }, h("span", { class: "small muted" }, k), field(k, { value: card[k] || "" }))),
  h("label", { class: "stack" }, h("span", { class: "small muted" }, "interfaces (APIs, contracts others rely on)"), h("textarea", { name: "interfaces" }, card.interfaces || "")),
  h("label", { class: "stack" }, h("span", { class: "small muted" }, "notes"), h("textarea", { name: "notes" }, card.notes || "")),
  h("div", { class: "row" }, field("change_note", { class: "grow", placeholder: "Change note (notifies dependents), optional" }), h("button", { class: "primary" }, "Save card")));
  return h("div", {}, h("h1", {}, agent), h("p", { class: "sub" }, card.repo || "", card.repo ? " · " : "", b.description || ""),
    briefCard(b, true),
    section("Journal history", tabs, list),
    h("div", { class: "card" }, h("details", {}, h("summary", {}, "Project card (shared with other agents)"), h("div", { style: "margin-top:10px" }, cardForm))));
}

async function viewMessages(asAgent) {
  if (!OV.hub) return needHub();
  const agents = OV.agents.map((a) => a.id);
  const me = asAgent || OV.agent || agents[0];
  const showAll = new URLSearchParams(location.hash.split("?")[1] || "").get("all") === "1";
  const msgs = await api("GET", `/api/inbox/${encodeURIComponent(me)}${showAll ? "?all=1" : ""}`);
  const unread = msgs.filter((m) => !m.read).map((m) => m.id);
  const compose = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const to = [...compose.querySelectorAll("input[name=to]:checked")].map((x) => x.value);
    const d = formData(compose);
    if (!to.length) return toast("Pick at least one recipient", true);
    await act(() => api("POST", "/api/send", { from: d.from, to, kind: d.kind, subject: d.subject, body: d.body }), "Sent");
  } },
  h("div", { class: "row" }, h("span", { class: "muted" }, "From"), select("from", agents, me), h("span", { class: "muted" }, "as"), select("kind", ["ask", "notify", "request"], "ask")),
  h("div", { class: "row" }, h("span", { class: "muted" }, "To"), agents.filter((a) => a !== me).map((a) => h("label", { class: "check" }, h("input", { type: "checkbox", name: "to", value: a }), a))),
  field("subject", { placeholder: "Subject", required: true }), h("textarea", { name: "body", placeholder: "Message", required: true }),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Send")));
  return h("div", {}, h("h1", {}, "Messages"),
    h("div", { class: "row sub" }, h("span", {}, "Inbox of"), select("as", agents, me, { onchange: (e) => (location.hash = `#/messages/${encodeURIComponent(e.target.value)}`) }),
      h("a", { href: `#/messages/${encodeURIComponent(me)}${showAll ? "" : "?all=1"}` }, showAll ? "show unread only" : "show all"),
      h("span", { class: "spacer" }),
      unread.length ? h("button", { onclick: () => act(() => api("POST", `/api/inbox/${me}/read`, { ids: unread }), "Marked read") }, `Mark ${unread.length} read`) : null),
    h("div", { class: "card" }, msgs.length ? msgs.slice().reverse().map((m) => {
      const replyBox = h("form", { class: "row", hidden: true, onsubmit: async (ev) => {
        ev.preventDefault(); const d = formData(replyBox);
        await act(() => api("POST", "/api/reply", { as: me, message_id: m.id, body: d.body }), "Reply sent");
      } }, field("body", { class: "grow", placeholder: "Reply…" }), h("button", { class: "primary" }, "Send"));
      const thread = h("div");
      return h("div", { class: "msg" + (m.read ? "" : " unread") },
        h("div", { class: "row" }, h("strong", {}, m.subject), h("span", { class: "pill" }, m.kind), h("span", { class: "muted small" }, `from ${m.sender} · ${ago(m.created_at)}`)),
        h("div", { style: "white-space:pre-wrap;margin:6px 0" }, m.body),
        h("div", { class: "row" },
          h("button", { class: "icon", onclick: () => { replyBox.hidden = !replyBox.hidden; } }, "Reply"),
          h("button", { class: "icon", onclick: async () => {
            const t = await api("GET", `/api/thread?as=${encodeURIComponent(me)}&thread=${encodeURIComponent(m.thread_id)}`);
            thread.replaceChildren(h("pre", {}, t.map((x) => `${x.sender} → ${x.recipient} (${ago(x.created_at)}): ${x.body}`).join("\n\n")));
          } }, "Thread"),
          !m.read ? h("button", { class: "icon", onclick: () => act(() => api("POST", `/api/inbox/${me}/read`, { ids: [m.id] })) }, "Mark read") : null),
        replyBox, thread);
    }) : h("div", { class: "empty" }, showAll ? "No messages." : "No unread messages.")),
    section("New message", compose));
}

// ---------- harness views ----------
function taskCounts(c) { return ["done", "running", "pending", "failed"].filter((k) => c[k]).map((k) => `${c[k]} ${k}`).join(" · ") || "no tasks"; }

async function viewRuns() {
  const nh = needHarness(); if (nh) return nh;
  const projects = await api("GET", "/api/projects");
  if (projects.some((p) => p.job_running)) autoRefresh(4000);
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault(); const d = formData(form);
    const job = await act(() => api("POST", "/api/projects", { dir: d.dir, goal: d.goal, approve: !!d.approve }), "Project started");
    if (job) location.hash = `#/job/${job.id}`;
  } },
  h("div", { class: "row" }, field("dir", { placeholder: "Folder name (e.g. bakery-site)", required: true, class: "grow" }),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "approve", value: "1", checked: true }), "Let me approve the plan first")),
  h("textarea", { name: "goal", placeholder: "Describe the goal: what should be built, constraints, assets…", required: true }),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Start project"), h("span", { class: "muted small" }, `relative folders go under ${OV.projects_dir}`)));
  return h("div", {}, h("h1", {}, "Runs"), h("p", { class: "sub" }, "Projects run by the harness: plan → route to the best model per role → review → commit."),
    h("div", { class: "card" }, projects.length ? h("table", {},
      h("tr", {}, h("th", {}, "Project"), h("th", {}, "Status"), h("th", {}, "Tasks"), h("th", { class: "num" }, "Spent"), h("th", {}, "Updated")),
      projects.map((p) => h("tr", {},
        h("td", {}, h("a", { href: `#/run/${encodeURIComponent(p.path)}` }, p.name), h("div", { class: "muted small" }, (p.goals[p.goals.length - 1] || "").slice(0, 110))),
        h("td", {}, statusPill(p.job_running ? "running" : p.status)), h("td", { class: "small" }, taskCounts(p.tasks)),
        h("td", { class: "num" }, money(p.spent_usd), p.unpriced_calls ? h("div", { class: "muted small" }, `+${p.unpriced_calls} unpriced`) : null),
        h("td", { class: "small muted" }, ago(p.updated_at))))) : h("div", { class: "empty" }, "No harness projects yet.")),
    section("New project", form));
}

async function viewRun(path) {
  const nh = needHarness(); if (nh) return nh;
  const [d, jobs] = await Promise.all([api("GET", `/api/project?path=${encodeURIComponent(path)}`), api("GET", "/api/jobs")]);
  const job = jobs.find((j) => j.target === d.path && j.status === "running");
  const lastJob = jobs.find((j) => j.target === d.path);
  if (job) autoRefresh(2500);
  const st = d.meta.status;
  const post = (body, msg) => act(() => api("POST", "/api/project", { path: d.path, ...body }), msg);
  const runJob = async (body) => { const j = await act(() => api("POST", "/api/project", { path: d.path, ...body }), "Started"); if (j) location.hash = `#/job/${j.id}`; };
  const extendForm = h("form", { class: "row", onsubmit: (ev) => { ev.preventDefault(); runJob({ action: "extend", goal: formData(extendForm).goal }); } },
    field("goal", { class: "grow", placeholder: "Add a new goal / feature to this project…", required: true }), h("button", {}, "Extend"));
  let log = null;
  if (job || lastJob) {
    const full = await api("GET", `/api/jobs/${(job || lastJob).id}`);
    log = section(job ? "Live run log" : `Last run (${full.status})`, h("pre", { class: "log" }, full.log.slice(-150).join("\n") || "…"));
  }
  return h("div", {},
    h("h1", {}, d.name), h("p", { class: "sub" }, d.path),
    h("div", { class: "card" },
      h("div", { class: "row" }, statusPill(job ? "running" : st), h("span", {}, `Spent ${money(d.meta.spent_usd)}`),
        d.meta.unpriced_calls ? h("span", { class: "muted small" }, `+${d.meta.unpriced_calls} unpriced calls`) : null, h("span", { class: "spacer" }),
        st === "awaiting_approval" && !job ? h("button", { class: "primary", onclick: async () => { await post({ action: "approve" }, "Plan approved"); runJob({ action: "run" }); } }, "Approve plan & run") : null,
        !job && st !== "done" && st !== "awaiting_approval" ? h("button", { class: "primary", onclick: () => runJob({ action: "run" }) }, st === "planning" ? "Plan & run" : "Resume") : null,
        !job ? h("button", { onclick: () => runJob({ action: "run", max_tasks: 1 }) }, "Run 1 task") : null),
      h("h3", {}, "Goals"), h("ol", {}, d.meta.goals.map((g) => h("li", {}, g))),
      !job ? extendForm : null),
    log,
    section("Task board", d.tasks.length ? h("table", {},
      h("tr", {}, h("th", {}, "Task"), h("th", {}, "Role"), h("th", {}, "Status"), h("th", {}, "Result"), h("th", {}, "")),
      d.tasks.map((t) => h("tr", {},
        h("td", {}, h("strong", {}, t.id), " ", t.title, t.depends_on.length ? h("div", { class: "muted small" }, "after " + t.depends_on.join(", ")) : null),
        h("td", {}, t.role, t.image_options && t.image_options.style ? h("div", { class: "muted small" }, t.image_options.style) : null),
        h("td", {}, statusPill(t.status), h("div", { class: "muted small" }, `${t.attempts.length} attempt(s)`)),
        h("td", { class: "small" }, t.summary.slice(0, 300),
          t.attempts.length ? h("details", {}, h("summary", {}, "attempts"), h("pre", {}, t.attempts.map((a, i) =>
            `#${i + 1} ${a.model} → ${a.outcome}${a.cost_usd ? ` (${money(a.cost_usd)})` : ""}${a.review ? "\n   review: " + a.review : ""}${a.error ? "\n   error: " + a.error : ""}`).join("\n\n"))) : null),
        h("td", { class: "actions" }, job ? null : h("div", { class: "row" },
          t.status === "failed" ? [h("button", { class: "icon", onclick: () => post({ action: "retry", task: t.id }, `${t.id} re-opened`) }, "Retry"),
            h("button", { class: "icon", onclick: () => post({ action: "skip", task: t.id }, `${t.id} skipped`) }, "Skip")] : null,
          t.status === "done" ? [h("button", { class: "icon", title: "Good result", onclick: () => post({ action: "feedback", task: t.id, rating: "good" }, "Thanks: noted as good") }, "👍"),
            h("button", { class: "icon", title: "Bad result", onclick: () => { const note = prompt("What was wrong? (feeds self-improvement)") || ""; post({ action: "feedback", task: t.id, rating: "bad", note }, "Noted as bad"); } }, "👎"),
            h("button", { class: "icon", onclick: () => post({ action: "retry", task: t.id }, `${t.id} re-opened`) }, "Redo")] : null))))) : h("div", { class: "empty" }, "No tasks yet: the planner runs first.")),
    d.summary ? section("Completion report", h("pre", {}, d.summary)) : null,
    d.metrics.length ? section("Models used", h("table", {}, h("tr", {}, h("th", {}, "Role · model"), h("th", { class: "num" }, "Attempts"), h("th", { class: "num" }, "Approved"), h("th", { class: "num" }, "Cost")),
      d.metrics.map((m) => h("tr", {}, h("td", {}, m.key), h("td", { class: "num" }, m.attempts), h("td", { class: "num" }, m.approved), h("td", { class: "num" }, money(m.cost)))))) : null,
    h("div", { class: "card" }, h("details", {}, h("summary", {}, `Event log (${d.events.length})`), h("pre", { class: "log" }, d.events.map((e) => `${e.at.slice(11, 19)}  ${e.text}`).join("\n")))),
    h("div", { class: "card" }, h("details", {}, h("summary", {}, `Files (${d.files.length})`), h("pre", {}, d.files.join("\n")))));
}

function spark(runs) {
  return h("span", { class: "spark", title: "oldest → newest" }, runs.slice(-15).map((r) => {
    const f = r.total ? r.passed / r.total : 0;
    return h("i", { class: f === 1 ? "ok" : f >= 0.6 ? "mid" : "no", title: `${r.at.replace("T", " ").slice(0, 16)}: ${r.passed}/${r.total}` });
  }));
}

async function viewModels() {
  const nh = needHarness(); if (nh) return nh;
  const [roles, probes, jobs] = await Promise.all([api("GET", "/api/roles"), api("GET", "/api/probes"), api("GET", "/api/jobs")]);
  let running = jobs.find((j) => j.target === "probe" && j.status === "running");
  const last = jobs.find((j) => j.target === "probe");
  if (running) { autoRefresh(2500); running = await api("GET", `/api/jobs/${running.id}`); }
  const pform = h("form", { class: "row", onsubmit: async (ev) => {
    ev.preventDefault(); const d = formData(pform);
    await act(() => api("POST", "/api/probes", { roles: d.role ? [d.role] : [], images: !!d.images }), "Probe started");
  } },
  select("role", [["", "all models"], ...roles.roles.map((r) => [r.name, `role: ${r.name}`])], ""),
  h("label", { class: "check" }, h("input", { type: "checkbox", name: "images", value: "1" }), "also generate a test image (costs a few cents)"),
  h("button", { class: "primary", disabled: !!running }, running ? "Probing…" : "Run health probe"));
  let result = null;
  if (last && last.status !== "running" && Array.isArray(last.result)) {
    result = h("table", {}, h("tr", {}, h("th", {}, "Model"), h("th", { class: "num" }, "Score"), h("th", { class: "num" }, "Usual"), h("th", { class: "num" }, "Time s"), h("th", {}, "Status"), h("th", {}, "Notes")),
      last.result.map((r) => h("tr", {}, h("td", {}, r.model), h("td", { class: "num" }, `${r.passed}/${r.total}`),
        h("td", { class: "num" }, r.baseline_score === null ? "-" : Math.round(r.baseline_score * 100) + "%"), h("td", { class: "num" }, r.seconds.toFixed(1)),
        h("td", {}, r.status.map(statusPill)), h("td", { class: "small" }, r.notes.join("; ")))));
  }
  return h("div", {}, h("h1", {}, "Models & health"),
    h("p", { class: "sub" }, "Who does what, and whether each model is behaving like it usually does."),
    section("Role routing", h("table", {}, h("tr", {}, h("th", {}, "Role"), h("th", {}, "Models (primary → fallbacks)"), h("th", {}, "Notes")),
      roles.roles.map((r) => h("tr", {}, h("td", {}, h("strong", {}, r.name), " ", r.planner ? h("span", { class: "pill info" }, "planner") : null, r.reviewer ? h("span", { class: "pill info" }, "reviewer") : null,
        r.kind === "image" ? h("span", { class: "pill" }, "image") : null),
        h("td", {}, r.models.map((m, i) => [i ? " → " : "", h("code", {}, m)]), r.learned ? [" ", h("span", { class: "pill good" }, "learned")] : null),
        h("td", { class: "small muted" }, r.description, Object.keys(r.options).length ? h("div", {}, h("code", {}, JSON.stringify(r.options))) : null))))),
    section("Health probe", h("p", { class: "muted small" }, "Auto-graded checks (tool use, JSON, instructions, reasoning, fixing a bug) compared with each model's own history. Run it before big changes."),
      pform, running ? h("pre", { class: "log", style: "margin-top:10px" }, (running.log || []).join("\n") || "starting…") : null,
      result ? h("div", { style: "margin-top:12px" }, h("div", { class: "muted small" }, `Latest probe (${ago(last.ended)})`), result) : null),
    section("History", probes.models.length ? h("table", {}, h("tr", {}, h("th", {}, "Model"), h("th", {}, "Runs (oldest → newest)"), h("th", {}, "Latest")),
      probes.models.map((m) => { const r = m.runs[m.runs.length - 1]; return h("tr", {}, h("td", {}, m.model), h("td", {}, spark(m.runs)),
        h("td", { class: "small" }, `${r.passed}/${r.total} · ${ago(r.at)}`, h("details", {}, h("summary", {}, "results"),
          h("pre", {}, r.results.map((x) => `${x.passed ? "pass" : "FAIL"} ${x.probe.padEnd(13)} ${(x.seconds || 0).toFixed(1)}s  ${x.error || x.detail || ""}`).join("\n"))))); })) : h("div", { class: "empty" }, "No probe runs yet.")));
}

async function viewImprove() {
  const nh = needHarness(); if (nh) return nh;
  const [data, roles, jobs] = await Promise.all([api("GET", "/api/proposals"), api("GET", "/api/roles"), api("GET", "/api/jobs")]);
  const running = jobs.find((j) => j.target === "improve" && j.status === "running");
  if (running) autoRefresh(2500);
  const startJob = async (body, msg) => { const j = await act(() => api("POST", "/api/improve", body), msg); if (j && j.id) location.hash = `#/job/${j.id}`; };
  const propose = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault(); const d = formData(propose);
    const body = { action: "propose", role: d.role, kind: d.kind, why: d.why, risk: d.risk };
    try {
      if (d.kind === "routing") body.models = d.value.split(/[,\s]+/).filter(Boolean);
      else if (d.kind === "options") body.options = JSON.parse(d.value || "{}");
      else body.prompt_text = d.value;
    } catch { return toast("Options must be JSON, e.g. {\"effort\": \"high\"}", true); }
    await act(() => api("POST", "/api/improve", body), "Proposal added");
  } },
  h("div", { class: "row" }, select("role", roles.roles.map((r) => r.name)), select("kind", [["routing", "routing (models)"], ["options", "options (JSON)"], ["prompt", "prompt (full text)"]], "routing"),
    select("risk", ["low", "medium", "high"], "medium"), field("why", { class: "grow", placeholder: "Why?" })),
  h("textarea", { name: "value", placeholder: "routing: provider/model, provider/model …   ·   options: {\"effort\": \"high\"}   ·   prompt: the complete new prompt" }),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Add proposal")));
  const open = data.proposals.filter((p) => ["proposed", "tested"].includes(p.status));
  const closed = data.proposals.filter((p) => !["proposed", "tested"].includes(p.status));
  const propCard = (p) => h("div", { class: "msg" },
    h("div", { class: "row" }, h("strong", {}, p.id), statusPill(p.status), h("span", { class: "pill" }, `risk: ${p.risk}`), h("span", { class: "pill" }, p.source), h("span", { class: "muted small" }, ago(p.created_at))),
    h("div", { style: "margin:6px 0" }, h("code", {}, p.summary)),
    h("div", { class: "small" }, p.rationale),
    p.kind === "prompt" ? h("details", {}, h("summary", { class: "small" }, "proposed prompt"), h("pre", {}, p.change.prompt_text)) : null,
    p.test ? h("div", { class: "small", style: "margin-top:4px" }, "Replay test: ", statusPill(p.test.verdict), ` on ${p.test.tasks_compared} task(s): current ${p.test.current.approved} approved (${money(p.test.current.cost_usd)}), proposed ${p.test.candidate.approved} approved (${money(p.test.candidate.cost_usd)})`, p.test.note ? ` · ${p.test.note}` : "") : null,
    ["proposed", "tested"].includes(p.status) ? h("div", { class: "row", style: "margin-top:8px" },
      h("button", { disabled: !!running, onclick: () => startJob({ action: "test", id: p.id, samples: 3, max_cost: 2 }, "Replay test started") }, "Test (replay)"),
      h("button", { class: "primary", disabled: !!running, onclick: () => startJob({ action: "apply", id: p.id }, "Applying (health-check first)") }, "Apply"),
      h("button", { disabled: !!running, onclick: () => { if (confirm("Apply without a passed test or healthy probe?")) startJob({ action: "apply", id: p.id, force: true }, "Force-applying"); } }, "Force apply"),
      h("button", { class: "danger", onclick: () => act(() => api("POST", "/api/improve", { action: "reject", id: p.id }), "Rejected") }, "Reject")) : null);
  const applied = data.history.filter((x) => x.event === "applied").reverse();
  return h("div", {}, h("h1", {}, "Improve"),
    h("p", { class: "sub" }, `The harness learns from its runs. Auto-apply policy: `, h("code", {}, data.policy), ". Your harness.yaml is never rewritten; learned changes are layered on top and can be rolled back."),
    h("div", { class: "card" }, h("div", { class: "row" },
      h("button", { class: "primary", disabled: !!running, onclick: () => startJob({ action: "analyze" }, "Analyzing") }, "Analyze history (free)"),
      h("button", { disabled: !!running, onclick: () => startJob({ action: "analyze", llm: true, max_cost: 2 }, "Analyst model started") }, "Analyze with the analyst model"),
      running ? h("span", { class: "muted" }, `running: ${running.title}…`) : null)),
    section(`Open proposals (${open.length})`, open.length ? open.map(propCard) : h("div", { class: "empty" }, "No open proposals. Run an analysis or suggest one below.")),
    section("Suggest a change", propose),
    section("Learned so far", Object.keys((data.learned || {}).roles || {}).length || data.learned_prompts.length ?
      h("pre", {}, JSON.stringify(data.learned, null, 2) + (data.learned_prompts.length ? `\nlearned prompts: ${data.learned_prompts.join(", ")}` : "")) : h("div", { class: "empty" }, "Nothing learned yet: running on harness.yaml as written."),
      applied.length ? h("table", { style: "margin-top:10px" }, h("tr", {}, h("th", {}, "Version"), h("th", {}, "Change"), h("th", {}, "When"), h("th", {}, "")),
        applied.map((x) => h("tr", {}, h("td", {}, `v${x.version}`), h("td", { class: "small" }, x.summary), h("td", { class: "small muted" }, ago(x.at)),
          h("td", {}, h("button", { class: "icon danger", onclick: () => { if (confirm(`Roll back to before v${x.version}? Later versions are undone too.`)) act(() => api("POST", "/api/improve", { action: "rollback", version: x.version }), "Rolled back"); } }, "Roll back"))))) : null),
    closed.length ? h("div", { class: "card" }, h("details", {}, h("summary", {}, `Decided proposals (${closed.length})`), closed.map(propCard))) : null);
}

async function viewJobs() {
  const jobs = await api("GET", "/api/jobs");
  if (jobs.some((j) => j.status === "running")) autoRefresh(3000);
  return h("div", {}, h("h1", {}, "Jobs"), h("p", { class: "sub" }, "Background work started from this UI (runs, probes, tests). Jobs live until the UI server stops."),
    h("div", { class: "card" }, jobs.length ? h("table", {}, h("tr", {}, h("th", {}, "Job"), h("th", {}, "Status"), h("th", {}, "Started"), h("th", {}, "Ended")),
      jobs.map((j) => h("tr", {}, h("td", {}, h("a", { href: `#/job/${j.id}` }, j.title)), h("td", {}, statusPill(j.status), j.error ? h("div", { class: "small", style: "color:var(--bad)" }, j.error.slice(0, 160)) : null),
        h("td", { class: "small muted" }, ago(j.started)), h("td", { class: "small muted" }, j.ended ? ago(j.ended) : "")))) : h("div", { class: "empty" }, "No jobs yet.")));
}

async function viewJob(id) {
  const j = await api("GET", `/api/jobs/${encodeURIComponent(id)}`);
  if (j.status === "running") autoRefresh(1500);
  const runPath = j.kind === "run" && j.target ? j.target : null;
  return h("div", {}, h("h1", {}, j.title), h("div", { class: "row sub" }, statusPill(j.status), h("span", { class: "muted" }, `started ${ago(j.started)}`),
      runPath ? h("a", { href: `#/run/${encodeURIComponent(runPath)}` }, "open project →") : null),
    j.error ? h("div", { class: "card", style: "border-color:var(--bad)" }, j.error) : null,
    section("Log", h("pre", { class: "log" }, j.log.join("\n") || "…")),
    j.result && typeof j.result === "object" && !Array.isArray(j.result) ? section("Result", h("pre", {}, JSON.stringify(j.result, null, 2))) : null);
}

render();
