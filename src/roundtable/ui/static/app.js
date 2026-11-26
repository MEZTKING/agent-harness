// Roundtable Hold UI - vanilla JS, no build step. Every node is built with h() (textContent),
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
// Budget / balanced / quality: which set of models the project uses, with each one's estimate.
function profilePicker(doc, edit) {
  const ests = doc.estimates || {};
  const names = Object.keys(ests);
  if (!names.length) return null;
  return h("div", { class: "row plan-profiles", title: "Which models do the work. You can change it any time; it applies to the tasks still to do." },
    h("span", { class: "muted small" }, "Setting"),
    names.map((n) => h("button", {
      class: n === doc.profile ? "primary" : "",
      onclick: () => n !== doc.profile && edit({ action: "profile", name: n }, `This project now uses the ${n} setting`),
    }, `${n[0].toUpperCase()}${n.slice(1)} · about ${money(ests[n].cost_usd || 0)}`)));
}

// ---------- questions to tap (asks.py) ----------
// One card for every question: a header chip, the question, big option buttons (the recommended one
// first and marked), ticks and Done when several answers fit, and "Other…" opening a text box.
// Keys: 1-9 pick an option, the next number opens Other…, Enter sends. An option with `confirm`
// shows an "Are you sure?" card first. onAnswer({chosen, other, confirmed}) does the work and may
// return a reply line; opts: {pictures: {id: src}, onSkip, compact, title}.
function askCard(ask, onAnswer, opts = {}) {
  const picked = new Set((ask.answer && ask.answer.chosen) || []);
  const textOnly = !ask.options.length;
  const card = h("div", { class: "ask" + (opts.compact ? " compact" : "") + (ask.answer ? " answered" : ""), tabindex: "0", "data-ask": ask.id });
  const other = h("textarea", { class: "ask-text grow", rows: ask.id === "like" ? 3 : 2, placeholder: ask.other_hint || "Type your own answer",
    "aria-label": ask.other_hint || "Your own answer" });
  if (ask.answer && ask.answer.other) other.value = ask.answer.other;
  const chosenNow = () => (ask.multi ? [...picked] : []);
  const otherRow = h("div", { class: "ask-other row" }, other,
    h("button", { class: "primary", type: "button", disabled: opts.disabled, onclick: () => send(chosenNow()) }, opts.sendLabel || "Send"));
  let busy = false;
  async function send(chosen, confirmed = false) {
    if (busy) return;
    const text = other.value.trim();
    if (!chosen.length && !text) { toast(textOnly ? "Type your answer first." : "Pick an answer, or type one.", true); showOther(true); return; }
    const sure = !confirmed && ask.options.find((o) => chosen.includes(o.id) && o.confirm);
    if (sure) { card.replaceChildren(...confirmParts(sure, () => send(chosen, true), draw)); card.focus(); return; }
    busy = true; card.classList.add("sending");
    try { await onAnswer({ chosen, other: text, confirmed }); }
    catch (e) { toast(e.message, true); }
    busy = false; card.classList.remove("sending");
  }
  // the second card for anything that spends beyond the estimate or can't be undone
  const confirmParts = (opt, yes, no) => [
    h("div", { class: "ask-head" }, h("span", { class: "chip warn" }, "Check")),
    h("b", { class: "ask-q" }, "Are you sure?"),
    h("div", { class: "ask-detail" }, opt.confirm),
    h("div", { class: "ask-opts" },
      h("button", { class: "ask-opt rec", type: "button", onclick: yes }, h("b", {}, h("kbd", {}, 1), "Yes, go ahead"), h("span", {}, opt.label)),
      h("button", { class: "ask-opt", type: "button", onclick: no }, h("b", {}, h("kbd", {}, 2), "No, go back"), h("span", {}, "Nothing is changed.")))];
  const pick = (o) => {
    if (!ask.multi) return send([o.id]);
    picked.has(o.id) ? picked.delete(o.id) : picked.add(o.id);
    draw(); card.focus();
  };
  function showOther(open) { otherRow.hidden = !open; if (open) setTimeout(() => other.focus(), 0); }
  other.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(chosenNow()); }
    if (ev.key === "Escape" && !textOnly) { other.value = ""; showOther(false); card.focus(); }
  });
  card.addEventListener("keydown", (ev) => {
    if (ev.target !== card || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const btns = [...card.querySelectorAll(".ask-opt")], n = Number(ev.key);
    if (n >= 1 && n <= btns.length) { ev.preventDefault(); btns[n - 1].click(); }
    else if (ev.key === "Enter" && ask.multi) { ev.preventDefault(); send([...picked]); }
  });
  function draw() {
    const rec = ask.recommended;
    const optButtons = ask.options.map((o, i) => {
      const on = picked.has(o.id);
      return h("button", { class: "ask-opt" + (on ? " on" : "") + (o.id === rec ? " rec" : ""), type: "button", disabled: opts.disabled,
        "aria-pressed": ask.multi || ask.answer ? String(on) : null, title: o.confirm ? "You'll be asked to make sure first" : `Press ${i + 1}`, onclick: () => pick(o) },
      o.picture && opts.pictures && opts.pictures[o.picture] ? h("img", { class: "ask-pic", src: opts.pictures[o.picture], alt: o.label }) : null,
      h("b", {}, ask.multi ? h("i", { class: "tick" + (on ? " on" : "") }) : h("kbd", {}, i + 1), o.label, o.id === rec ? h("span", { class: "rec-mark" }, "Recommended") : null),
      o.description ? h("span", {}, o.description) : null);
    });
    const otherBtn = ask.allow_other !== false && !textOnly ? h("button", { class: "ask-opt other", type: "button", disabled: opts.disabled,
      title: `Type your own answer (press ${ask.options.length + 1})`, onclick: () => showOther(otherRow.hidden) },
    h("b", {}, h("kbd", {}, ask.options.length + 1), "Other…"), h("span", {}, ask.other_hint || "Type your own answer")) : null;
    card.replaceChildren(...[
      h("div", { class: "ask-head" }, h("span", { class: "chip", title: opts.title || "" }, ask.header),
        opts.project ? h("span", { class: "muted small" }, opts.project) : null, ask.answer ? h("span", { class: "pill good" }, "answered") : null),
      h("b", { class: "ask-q" }, ask.question),
      ask.detail ? h("div", { class: "ask-detail" }, ask.detail) : null,
      textOnly ? null : h("div", { class: "ask-opts" + (ask.pictures ? " pics" : "") }, optButtons, otherBtn),
      ask.allow_other !== false ? otherRow : null,
      h("div", { class: "ask-foot" },
        ask.multi ? h("button", { class: "primary", type: "button", disabled: opts.disabled, onclick: () => send([...picked]) }, "Done") : null,
        opts.onSkip ? h("button", { class: "link-btn", type: "button", title: "Leave this for later. It comes back if things change.", onclick: opts.onSkip }, "Not now") : null,
        opts.extra || null,
        h("span", { class: "muted small" }, ask.multi ? "Tick all that fit, then Done." : textOnly ? "Enter sends." : "Tap one, or type your own."))]
      .filter(Boolean));  // replaceChildren would write "null" for a missing part
    otherRow.hidden = !(textOnly || other.value);
  }
  draw();
  return card;
}

// Answer a card of a project through /api/asks; a long step (a run, a plan update) comes back as a job.
async function answerAsk(ask, a) {
  const r = await api("POST", "/api/asks", { path: ask.path, id: ask.id, stamp: ask.stamp, ...a });
  toast(r.reply || "Done");
  return r;
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
let setupChecked = false;
function route() { const p = (location.hash || "#/roundtable").slice(2).split("?")[0].split("/"); return [p[0] === "where" || !p[0] ? "roundtable" : p[0], ...p.slice(1).map(decodeURIComponent)]; }
function setActive(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name ||
    (name === "project" && a.dataset.nav === "projects") || ((name === "run" || name === "new") && a.dataset.nav === "runs") ||
    (name === "job" && a.dataset.nav === "jobs")));
  // on a phone the rooms scroll sideways: keep the current one in view
  const rooms = document.querySelector(".rooms"), on = rooms && rooms.querySelector("a.active");
  if (rooms && on && rooms.scrollWidth > rooms.clientWidth) rooms.scrollLeft = Math.max(0, on.offsetLeft - rooms.offsetLeft - 24);
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
    if (OV.harness) loadAutopilot(true); else document.getElementById("autopilot").replaceChildren();
    if (!setupChecked) {  // first launch of the desktop app: go to setup
      setupChecked = true;
      try { const st = await api("GET", "/api/setup"); if (st.desktop && !st.setup_done && view !== "setup") { location.hash = "#/setup"; return; } } catch { /* ignore */ }
    }
    const views = { setup: viewSetup, settings: viewSettings, roundtable: viewRoundtable, projects: viewProjects, project: viewProject, messages: viewMessages,
      runs: viewRuns, run: viewRun, plan: viewPlan, new: viewNew, models: viewModels, improve: viewImprove, jobs: viewJobs, job: viewJob };
    const node = await (views[view] || viewRoundtable)(...args);
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
    h("p", { class: "muted" }, OV.hub_error || ""), h("p", {}, "Set HUB_CONFIG or pass --hub-config to roundtable ui."));
}
function needHarness() {
  if (OV.harness) return null;
  return h("div", { class: "card" }, h("h2", {}, "Harness not configured"),
    h("p", { class: "muted" }, OV.harness_error || ""), h("p", {}, "Set HARNESS_CONFIG or pass --harness-config to roundtable ui."));
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
// The Roundtable: every project (hub journal + harness runs) as a seat, what needs the owner, and for the selected
// seat its plan, a chat with its orchestrator and the live minutes. It refreshes itself in place; sections are only
// redrawn when their data changed, so typing, scroll positions and animations are left alone.
const RT_POLL_MS = 4000;
let rtSel = null;       // the selected seat; survives refreshes and re-renders
let rtDraft = "";       // unsent chat text
let rtSteer = false;    // chat mode: ask (false) or steer (true)
try { rtSel = sessionStorage.getItem("rt-seat"); } catch { /* storage unavailable */ }
function tagClass(id) { let n = 0; for (const ch of String(id)) n = (n * 31 + ch.charCodeAt(0)) >>> 0; return "tg" + (n % 8); }
const tagDot = (id) => h("i", { class: "tagc " + tagClass(id) });
function clock(ts) { const d = new Date(ts); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour12: false }); }
function patch(el, sig, build) {  // redraw el only when sig changed, and never under the user's cursor
  if (el._sig === sig) return false;
  const a = document.activeElement;
  if (el._sig !== undefined && a && el.contains(a) && a.value) return false;
  el._sig = sig;
  el.replaceChildren(...[build()].flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false));
  return true;
}
function taskTree(tasks) {
  const ids = new Set(tasks.map((t) => t.id)), kids = {}, roots = [];
  tasks.forEach((t) => {
    const deps = (t.depends_on || []).filter((d) => ids.has(d) && d !== t.id), parent = deps[deps.length - 1];
    if (parent) (kids[parent] = kids[parent] || []).push(t); else roots.push(t);
  });
  const cls = { done: "done", running: "run", failed: "fail" };
  const node = (t, depth) => {
    const last = t.attempts[t.attempts.length - 1], deps = t.depends_on || [];
    const model = (last && last.model) || (t.image_options && t.image_options.style) || "";
    const why = t.status === "failed" && last ? (last.review || last.error || "") : "";
    return h("li", {},
      h("div", { class: "node " + (cls[t.status] || "pend") }, h("i", { class: "dot" }),
        h("div", { class: "b" }, h("b", {}, t.id), " ", t.title,
          h("small", {}, [t.role, model, t.attempts.length ? `${t.attempts.length} attempt(s)${last.outcome ? ", " + last.outcome : ""}` : "",
            deps.length > 1 ? "after " + deps.join(", ") : ""].filter(Boolean).join(" · ")),
          why ? h("small", { class: "why" }, why.slice(0, 200)) : null),
        statusPill(t.status)),
      kids[t.id] && depth < 30 ? h("ul", {}, kids[t.id].map((k) => node(k, depth + 1))) : null);
  };
  return h("ul", { class: "tree" }, roots.map((t) => node(t, 0)));
}

async function viewRoundtable() {
  let data = null, feed = [], proj = null, chat = null, projPath = null, pending = null, ticks = 0, offline = false;
  const stats = h("div", { class: "rt-stats" }), strip = h("div", { class: "rt-strip" }), needs = h("div", { class: "card needs" });
  const plan = h("div", { class: "rt-col" }), chatHead = h("div", { class: "card-head" }), chatLog = h("div", { class: "chat" });
  const chatBox = h("div"), feedHead = h("div", { class: "card-head" }), feedLog = h("div", { class: "feed" });
  const sel = () => (data ? data.seats.find((s) => s.id === rtSel) : null);
  const post = (path, body) => api("POST", "/api/project", { path, ...body });
  const run = async (btn, fn, ok) => {  // one-click action: do it, say so, refresh in place
    if (btn) btn.disabled = true;
    try { await fn(); if (ok) toast(ok); } catch (e) { toast(e.message, true); }
    await refresh(true);
  };
  const actionButtons = (path, actions, task, small) => actions.map((a) => {
    const cls = (small ? "icon " : "") + (a === "skip" ? "" : "primary");
    if (a === "approve") return h("button", { class: cls, onclick: (ev) => run(ev.currentTarget, async () => { await post(path, { action: "approve" }); await post(path, { action: "run" }); }, "Plan approved: the run has started") }, "Approve plan");
    if (a === "retry") return h("button", { class: cls, onclick: (ev) => run(ev.currentTarget, async () => { await post(path, { action: "retry", task }); await post(path, { action: "run" }); }, `Retrying ${task}`) }, "Retry task");
    if (a === "skip") return h("button", { class: cls, onclick: (ev) => run(ev.currentTarget, async () => { await post(path, { action: "skip", task }); await post(path, { action: "run" }); }, `${task} skipped`) }, "Skip");
    if (a === "budget") return h("button", { class: cls, onclick: (ev) => run(ev.currentTarget, () => post(path, { action: "raise_budget" }), "Budget raised: resuming") }, "Raise budget");
    if (a === "resume") return h("button", { class: cls, onclick: (ev) => run(ev.currentTarget, () => post(path, { action: "run" }), "Resumed") }, "Resume");
    return null;
  });
  const choose = (id) => {
    if (id === rtSel) return;
    rtSel = id;
    try { sessionStorage.setItem("rt-seat", id); } catch { /* storage unavailable */ }
    strip.querySelectorAll(".seat").forEach((x) => x.classList.toggle("on", x.dataset.seat === id));
    refresh(true);
  };

  async function load(full) {
    try {
      [data, feed] = await Promise.all([api("GET", "/api/roundtable"), api("GET", "/api/activity?limit=120")]);
      offline = false;
    } catch (e) { offline = true; if (!data) throw e; return; }
    if (!sel()) { const first = data.seats.find((s) => s.status === "running" || s.status === "waiting") || data.seats[0]; rtSel = first ? first.id : null; }
    const s = sel();
    if (s && s.path) {
      if (full || s.status === "running" || projPath !== s.path || ticks % 5 === 0) {
        const path = s.path, q = encodeURIComponent(path);
        const [p, c] = await Promise.all([api("GET", `/api/project?path=${q}`).catch(() => null), api("GET", `/api/chat?path=${q}`).catch(() => null)]);
        if (rtSel !== s.id) return;  // the user picked another seat meanwhile
        if (projPath !== path) { proj = null; chat = null; }
        proj = p || proj; chat = c || chat || []; projPath = path;
      }
    } else { proj = null; chat = null; projPath = null; }
  }

  function seatCard(s, i, n) {
    const p = s.progress, total = p ? p.total : 0, failed = s.failed_task ? 1 : 0;
    const label = { running: "Running", waiting: "Needs you", idle: "Idle", done: "Done" }[s.status] || s.status;
    const cls = { running: "info", waiting: s.failed_task ? "bad" : "warn", idle: "", done: "good" }[s.status] || "";
    const count = total ? `${p.done}/${total} tasks` : s.open_todos ? `${s.open_todos} todo(s)` : "";
    const now = s.detail || (s.last_session ? s.last_session.text : "") || (s.last_activity ? `last activity ${ago(s.last_activity)}` : s.description || "no activity yet");
    return h("div", { class: `seat ${s.status}${s.id === rtSel ? " on" : ""}`, role: "button", tabindex: "0", "data-seat": s.id, title: `${s.id}: ${label}${s.detail ? " · " + s.detail : ""}`,
      style: `--a:${Math.round((360 * i) / n)}deg`,
      onclick: () => choose(s.id), onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); choose(s.id); } } },
    h("div", { class: "nm" }, tagDot(s.id), h("span", {}, s.id), s.high ? h("span", { class: "seat-high", title: `${s.high} high priority` }) : null,
      s.unread ? h("span", { class: "badge", title: `${s.unread} unread` }, s.unread) : null,
      s.autopilot ? h("span", { class: "ap-mark", title: "Autopilot answers this project's questions while you're away" }, "autopilot") : null),
    h("div", { class: "st" }, h("span", { class: "pill " + cls }, s.status === "running" ? h("i", { class: "cdl" }) : null, label), h("span", {}, count)),
    h("div", { class: "bar" }, total ? [h("i", { style: `width:${(100 * p.done) / total}%` }),
      s.status === "running" && p.done < total ? h("i", { class: "run", style: `width:${100 / total}%` }) : null,
      failed ? h("i", { class: "fail", style: `width:${100 / total}%` }) : null] : null),
    h("div", { class: "now" }, now),
    total || s.spent_usd ? h("div", { class: "st" }, h("span", {}, total ? `${Math.round((100 * p.done) / total)}% done` : ""), s.spent_usd ? h("b", {}, money(s.spent_usd)) : null) : null);
  }
  // the empty chair at the table: start a new project
  const chair = (i, n) => h("a", { class: "seat chair", href: "#/new", style: `--a:${Math.round((360 * i) / n)}deg`,
    title: "A few questions, then the planner makes a plan for you to check" }, h("b", {}, "+ Pull up a chair"), h("span", {}, "Write a new idea"));

  // a waiting project's next card, answered right here; the rest wait on its plan page
  function needAsk(n) {
    const a = n.ask, more = n.asks > 1 ? h("a", { class: "btn icon", href: `#/plan/${encodeURIComponent(n.path)}`, title: "See every question on the plan page" }, `${n.asks - 1} more`) : null;
    return h("div", { class: "need need-ask" }, askCard(a, async (ans) => { await answerAsk(a, ans); await refresh(true); }, {
      compact: true, project: n.project, extra: more,
      onSkip: a.kind === "approve" || a.kind === "money" ? null : () => run(null, () => api("POST", "/api/asks", { path: a.path, id: a.id, stamp: a.stamp, skip: true }), "Left for later"),
    }));
  }

  function needItem(n) {
    if (n.kind === "run" && n.ask) return needAsk(n);
    let acts = null;
    if (n.kind === "run") acts = (n.actions || []).includes("approve")
      ? h("a", { class: "btn icon primary", href: `#/plan/${encodeURIComponent(n.path)}` }, "Open plan")
      : [actionButtons(n.path, n.actions || [], n.task, true), h("a", { class: "btn icon", href: `#/run/${encodeURIComponent(n.path)}` }, "View")];
    else if (n.kind === "todo") acts = h("button", { class: "icon primary", onclick: (ev) => run(ev.currentTarget, () => api("POST", `/api/journal/${n.project}/${n.id}/close`, {}), "Marked done") }, "✓ done");
    else if (n.kind === "messages") acts = h("a", { class: "btn icon primary", href: `#/messages/${encodeURIComponent(n.project)}` }, "Read");
    return h("div", { class: "need" }, tagDot(n.project),
      h("div", { class: "t" }, h("b", { class: "link", onclick: () => choose(n.project) }, n.project), " · ", n.text,
        h("small", {}, { run: "harness run", todo: "high-priority todo", messages: "letters for you" }[n.kind] || n.kind, n.at ? ` · ${ago(n.at)}` : "")),
      h("div", { class: "acts" }, acts));
  }

  function planColumn(s) {
    if (!s) return h("div", { class: "card" }, h("div", { class: "empty" }, "No projects yet. Start one with “+ New project”, or add agents to your hub."));
    const out = [];
    if (s.path) {
      const tasks = proj && projPath === s.path ? proj.tasks : null, p = s.progress || { done: 0, total: 0 };
      out.push(h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, tagDot(s.id), s.id),
          h("span", { class: "muted small" }, [p.total ? `${p.done} of ${p.total} done` : "", money(s.spent_usd)].filter(Boolean).join(" · "))),
        h("div", { class: "row rt-acts" }, statusPill(s.status === "waiting" ? (s.failed_task ? "failed" : proj ? proj.meta.status : "waiting") : s.status),
          h("span", { class: "spacer" }), actionButtons(s.path, (s.actions || []).filter((a) => a !== "approve"), s.failed_task, true),
          h("a", { class: "btn icon" + ((s.actions || []).includes("approve") ? " primary" : ""), href: `#/plan/${encodeURIComponent(s.path)}` }, "Open plan"),
          h("a", { class: "btn icon", href: `#/run/${encodeURIComponent(s.path)}` }, "Open run"), neverButton(s)),
        s.detail ? h("div", { class: "small muted rt-detail" }, s.detail) : null,
        h("h3", {}, "Plan"),
        s.goal ? h("div", { class: "goal" }, h("b", {}, "Goal"), s.goal) : null,
        tasks === null ? h("div", { class: "empty" }, "Loading the plan…")
          : tasks.length ? taskTree(tasks) : h("div", { class: "empty" }, s.status === "running" ? "The orchestrator is drawing up the plan…" : "No tasks yet: the planner runs first.")));
    }
    if (s.brief) out.push(s.path ? h("div", { class: "card" }, h("details", {}, h("summary", {}, `Journal (${s.open_todos || 0} open todo(s))`), h("div", { class: "nested" }, briefCard(s.brief, true)))) : briefCard(s.brief, true));
    return out;
  }

  function neverButton(s) {  // one project can stay away from autopilot
    const never = ((data.autopilot || {}).never || []).includes(s.id);
    return h("button", { class: "icon", title: never ? "Autopilot leaves this project alone. Let it answer here too while you're away."
      : "Autopilot never answers for this project: every question waits for you.",
    onclick: (ev) => run(ev.currentTarget, () => api("POST", "/api/autopilot", { action: "never", project: s.id, never: !never }),
      never ? `Autopilot may answer for ${s.id} again` : `${s.id} is never on autopilot`) }, never ? "Allow autopilot" : "Never on autopilot");
  }

  function chatMessages(s) {
    if (!s || !s.path) return h("div", { class: "empty" }, s ? "This project keeps a journal but has no harness run, so there is no orchestrator to talk to here." : "Pick a seat to talk to its orchestrator.");
    const rows = (chat || []).map((m) => h("div", { class: "msgl " + (m.who === "owner" ? "you" : "orc") + (m.steer && m.who === "owner" ? " steer" : "") },
      h("small", {}, m.who === "owner" ? `You · ${m.steer ? "steer" : "ask"}` : `Orchestrator${m.model ? " · " + m.model : ""}`, m.at ? ` · ${clock(m.at)}` : ""),
      h("div", { class: "body" }, m.text),
      m.steer && m.who === "owner" ? h("div", { class: "steer-note" }, "Instruction for the next tasks") : null));
    if (pending && pending.path === s.path) rows.push(
      h("div", { class: "msgl you" + (pending.steer ? " steer" : "") }, h("small", {}, `You · ${pending.steer ? "steer" : "ask"}`), h("div", { class: "body" }, pending.text)),
      h("div", { class: "msgl orc pending" }, h("small", {}, "Orchestrator"), h("div", { class: "body" }, h("i", { class: "cdl" }), pending.steer ? "noting the instruction…" : "thinking…")));
    return rows.length ? rows : h("div", { class: "empty" }, "Ask the orchestrator about this project (“what's left?”, “why did T3 fail?”), or steer it with an instruction for the next tasks.");
  }

  function chatCompose(s) {
    if (!s || !s.path) return s ? h("div", { class: "row", style: "margin-top:10px" }, h("a", { class: "btn primary", href: "#/messages" }, "Message this project")) : null;
    const input = h("input", { name: "message", class: "grow", autocomplete: "off", value: rtDraft, oninput: (ev) => { rtDraft = ev.target.value; } });
    const ask = h("button", { type: "button" }, "Ask"), steer = h("button", { type: "button" }, "Steer");
    const send = h("button", { class: "primary" }, "Send");
    const mode = (v) => { rtSteer = v; ask.classList.toggle("on", !v); steer.classList.toggle("on", v);
      input.placeholder = v ? "An instruction for the next tasks, e.g. “use 32x32 sprites from now on”" : "Ask about this project, e.g. “what's left?”"; };
    ask.addEventListener("click", () => mode(false)); steer.addEventListener("click", () => mode(true)); mode(rtSteer);
    const form = h("form", { class: "compose", onsubmit: async (ev) => {
      ev.preventDefault();
      const text = input.value.trim(), path = s.path, isSteer = rtSteer;
      if (!text || pending) return;
      pending = { path, text, steer: isSteer }; input.value = ""; rtDraft = ""; send.disabled = true; draw();
      try { await api("POST", "/api/chat", { path, message: text, steer: isSteer }); if (isSteer) toast("Instruction stored for the next tasks"); }
      catch (e) { toast(e.message, true); if (!input.value) { input.value = text; rtDraft = text; } }
      pending = null; send.disabled = false;
      await refresh(true);
    } }, h("div", { class: "seg" }, ask, steer), input, send);
    return form;
  }

  function draw() {
    if (!data) return;
    const s = sel();
    document.getElementById("jobs-badge").hidden = !data.running_jobs; document.getElementById("jobs-badge").textContent = data.running_jobs;
    const unread = data.seats.reduce((n, x) => n + (x.id === data.agent || !data.agent ? x.unread || 0 : 0), 0);
    const synced = data.synced_at ? `synced ${ago(data.synced_at)}` : "auto-refresh on";
    patch(stats, JSON.stringify([offline, synced, data.sync_error, data.health, data.spend_today, unread]), () => [
      h("span", { class: "live" + (offline ? " off" : ""), title: data.sync_error || "" }, h("i", {}), h("b", {}, offline ? "offline" : "live"), ` · ${offline ? "retrying…" : synced}`,
        data.sync_error ? h("span", { class: "pill warn", title: data.sync_error }, "sync problem") : null),
      h("a", { class: "stat", href: "#/models", title: data.health.map((x) => `${x.model}: ${x.passed}/${x.total}`).join("\n") || "No health probe yet" }, "Models ",
        data.health.length ? [h("span", { class: "health" }, data.health.map((x) => h("i", { class: x.state }))),
          h("span", { class: "muted" }, ["ok", "warn", "bad"].map((k) => { const n = data.health.filter((x) => x.state === k).length; return n ? `${n} ${{ ok: "ok", warn: "off", bad: "down" }[k]}` : ""; }).filter(Boolean).join(" · "))]
          : h("span", { class: "muted" }, "not probed yet")),
      h("a", { class: "stat", href: "#/messages" }, "Unread ", h("b", {}, unread)),
      h("a", { class: "btn primary", href: "#/new", title: "A few questions, then the planner makes a plan for you to check" }, "+ New project")]);
    const today = document.getElementById("today-spend");
    today.hidden = false; today.querySelector("b").textContent = money(data.spend_today);
    if (data.autopilot) drawAutopilot(data.autopilot, true);
    const n = data.seats.length + 1, waiting = data.seats.filter((x) => x.status === "waiting").length;
    strip.classList.toggle("ring", n <= 8);   // up to seven seats and the empty chair sit around the table; more make a list
    patch(strip, JSON.stringify([rtSel, data.seats.map((x) => ({ ...x, brief: null, last_activity: x.last_activity ? ago(x.last_activity) : "" }))]), () =>
      [h("div", { class: "hall-centre", "aria-hidden": "true" }, h("i", { class: "flame" }), h("b", {}, "The Hall"),
        h("span", {}, `${data.seats.length} seat${data.seats.length === 1 ? "" : "s"}${waiting ? ` · ${waiting} need${waiting === 1 ? "s" : ""} you` : ""}`)),
      data.seats.length ? data.seats.map((x, i) => seatCard(x, i, n)) : h("div", { class: "empty" }, "Nobody at the table yet."), chair(n - 1, n)]);
    patch(needs, JSON.stringify(data.needs_you.map((n) => ({ ...n, at: n.at ? ago(n.at) : "" }))), () => [
      h("div", { class: "card-head" }, h("h2", {}, "Needs you"), data.needs_you.length ? h("span", { class: "cnt" }, data.needs_you.length) : null),
      data.needs_you.length ? h("div", { class: "list" }, data.needs_you.map(needItem)) : h("div", { class: "empty" }, "Nothing is waiting on you.")]);
    patch(plan, JSON.stringify([s, projPath, proj && proj.tasks, proj && proj.meta.status, (data.autopilot || {}).never]), () => planColumn(s));
    patch(chatHead, JSON.stringify([s && s.id, s && s.path]), () => [h("h2", {}, s && !s.path ? "Chat" : "Chat with the orchestrator"), s ? h("span", { class: "muted small" }, s.id) : null]);
    const atEnd = chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight < 40;
    if (patch(chatLog, JSON.stringify([s && s.id, s && s.path, chat, pending]), () => chatMessages(s)) && atEnd) chatLog.scrollTop = chatLog.scrollHeight;
    patch(chatBox, JSON.stringify([s && s.id, s && s.path]), () => chatCompose(s));
    patch(feedHead, String(offline), () => [h("h2", {}, "Minutes, live"), h("span", { class: "live" + (offline ? " off" : "") }, h("i", {}), "all projects")]);
    const top = feedLog.scrollTop, height = feedLog.scrollHeight;
    if (patch(feedLog, JSON.stringify([feed.length, feed[0], feed[feed.length - 1]]), () => (feed.length ? feed.map((f) =>
      h("div", {}, h("time", { title: f.at }, clock(f.at)), h("span", { class: "p link " + tagClass(f.project), onclick: () => choose(f.project) }, f.project),
        f.who ? h("span", { class: "w" }, f.who) : null,
        h("span", { title: f.text, class: "a" + (/journal:done|approved|passed|\bdone\b/i.test(f.kind + " " + f.text) ? " ok" : /reject|fail|error/i.test(f.text) ? " no" : f.kind === "steer" ? " wn" : "") }, f.text)))
      : h("div", { class: "empty" }, "Nothing has happened yet."))) && top > 0) feedLog.scrollTop = top + (feedLog.scrollHeight - height);
  }

  async function refresh(full) { await load(full); if (root.isConnected || !root._drawn) { draw(); root._drawn = true; } }
  const root = h("div", { class: "rt" },
    h("div", { class: "rt-head" }, h("h1", {}, "Roundtable"), stats),
    h("div", { class: "rt-top" }, strip, needs),
    h("div", { class: "rt-three" }, plan, h("div", { class: "card" }, chatHead, chatLog, chatBox), h("div", { class: "card" }, feedHead, feedLog)));
  await refresh(true);
  const tick = async () => {
    if (!root.isConnected) return;
    ticks++;
    try { await refresh(false); } catch { /* keep trying */ }
    if (root.isConnected) timer = setTimeout(tick, RT_POLL_MS);
  };
  timer = setTimeout(tick, RT_POLL_MS);
  return root;
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
    const job = await act(() => api("POST", "/api/projects", { dir: d.dir, goal: d.goal, approve: !!d.approve, references: d.references || "" }), "Project started");
    if (job) location.hash = `#/job/${job.id}`;
  } },
  h("div", { class: "row" }, field("dir", { placeholder: "Folder name (e.g. bakery-site)", required: true, class: "grow" }),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "approve", value: "1", checked: true }), "Let me approve the plan first")),
  h("textarea", { name: "goal", placeholder: "Describe the goal: what should be built, constraints, assets…", required: true }),
  h("label", { class: "stack", title: "Roundtable reads each one first and makes something similar: the ideas, how it works and its style, never its name, art, music or text. Code only where its licence allows, with credit." },
    h("span", { class: "small muted" }, "Make it like this (links, repos or a description, one per line)"),
    h("textarea", { name: "references", rows: 2, placeholder: "e.g. https://example.com/a-game-you-like\nowner/repository\nthe queue from Spotify" })),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Start project"), h("span", { class: "muted small" }, `relative folders go under ${OV.projects_dir}`)));
  return h("div", {}, h("h1", {}, "Runs"), h("p", { class: "sub" }, "Projects run by the harness: plan → route to the best model per role → review → commit."),
    h("div", { class: "card" }, projects.length ? h("table", {},
      h("tr", {}, h("th", {}, "Project"), h("th", {}, "Status"), h("th", {}, "Tasks"), h("th", { class: "num" }, "Spent"), h("th", {}, "Updated")),
      projects.map((p) => h("tr", {},
        h("td", {}, h("a", { href: `#/run/${encodeURIComponent(p.path)}` }, p.name), h("div", { class: "muted small" }, (p.goals[p.goals.length - 1] || "").slice(0, 110))),
        h("td", {}, statusPill(p.job_running ? "running" : p.status)), h("td", { class: "small" }, taskCounts(p.tasks)),
        h("td", { class: "num" }, money(p.spent_usd), p.unpriced_calls ? h("div", { class: "muted small" }, `+${p.unpriced_calls} unpriced`) : null),
        h("td", { class: "small muted" }, ago(p.updated_at))))) : h("div", { class: "empty" }, "No harness projects yet.")),
    section("New project", h("p", { class: "muted" }, "Answer a few questions by tapping; the planner then makes a plan for you to check."),
      h("a", { class: "btn primary", href: "#/new" }, "+ New project"),
      h("details", { style: "margin-top:12px" }, h("summary", { class: "small muted" }, "Or type the folder and the goal yourself"), form)));
}

// ---------- a new project: a few cards to tap ----------
async function viewNew() {
  const nh = needHarness(); if (nh) return nh;
  const w = await api("GET", "/api/asks?wizard=1");
  const answers = {};
  let step = 0;
  const root = h("div", { class: "wizard asks" });
  const said = (a) => {
    const ans = answers[a.id] || {};
    return [...(ans.chosen || []).map((c) => (a.options.find((o) => o.id === c) || {}).label || c), ans.other].filter(Boolean).join(" · ");
  };
  const summary = (a, i) => h("div", { class: "ask answered compact wizard-row" },
    h("div", { class: "ask-head" }, h("span", { class: "chip" }, a.header), h("span", { class: "grow" }, h("span", { class: "muted small" }, a.question), h("br"), h("b", {}, said(a))),
      h("button", { class: "icon", title: "Change this answer", onclick: () => { step = i; draw(); } }, "Change")));
  const next = () => { step = w.asks.findIndex((a) => !answers[a.id]); if (step < 0) step = w.asks.length; };
  const start = () => h("div", { class: "ask ready" },
    h("div", { class: "ask-head" }, h("span", { class: "chip" }, "Ready")),
    h("b", { class: "ask-q" }, "Make the plan?"),
    h("div", { class: "ask-detail" }, "The planner writes a plan with its own questions for you. Nothing is built until you approve it. Making the plan costs a little (usually a few cents)."),
    h("div", { class: "ask-opts" },
      h("button", { class: "ask-opt rec", type: "button", onclick: async (ev) => {
        ev.currentTarget.disabled = true;
        try { const r = await api("POST", "/api/asks", { wizard: answers }); toast(r.reply); location.hash = `#/job/${r.job.id}`; }
        catch (e) { toast(e.message, true); ev.currentTarget.disabled = false; }
      } }, h("b", {}, h("kbd", {}, 1), "Make the plan", h("span", { class: "rec-mark" }, "Recommended")), h("span", {}, "You'll see it, with its questions, in a minute or two.")),
      h("button", { class: "ask-opt", type: "button", onclick: () => { step = 0; draw(); } }, h("b", {}, h("kbd", {}, 2), "Go back"), h("span", {}, "Look at your answers again."))));
  function draw() {
    const kids = w.asks.map((a, i) => {
      if (i === step) return askCard(a, async (ans) => {
        if (a.required && !ans.other) throw new Error("Write your idea in a few words first.");
        answers[a.id] = ans; next(); draw();
      }, { sendLabel: "Next" });
      return answers[a.id] ? summary(a, i) : null;
    });
    if (step >= w.asks.length) kids.push(start());
    root.replaceChildren(...kids.filter(Boolean));
    const live = root.querySelector(".ask:not(.wizard-row)");
    if (live) setTimeout(() => (live.querySelector("textarea:not([hidden])") && !live.querySelector(".ask-other").hidden ? live.querySelector("textarea") : live).focus(), 0);
  }
  draw();
  return h("div", {}, h("a", { href: "#/roundtable", class: "muted small" }, "← Roundtable"), h("h1", {}, "New project"),
    h("p", { class: "sub" }, "Tap an answer, or choose Other… to type your own. Number keys pick, Enter sends. ",
      h("span", { class: "link", title: w.projects_dir }, "Where it's saved")), root);
}

// ---------- the living plan ----------
async function viewPlan(path) {
  const q = encodeURIComponent(path);
  const [d, aq] = await Promise.all([api("GET", `/api/plan?path=${q}`), api("GET", `/api/asks?path=${q}&answered=1`).catch(() => ({ asks: [] }))]);
  const doc = d.doc;
  const edit = async (body, ok) => { try { await api("POST", "/api/plan", { path, ...body }); if (ok) toast(ok); await render(); } catch (e) { toast(e.message, true); } };
  const startJob = async (body, ok) => { try { const j = await api("POST", "/api/plan", { path, ...body }); toast(ok); location.hash = `#/job/${j.id}`; } catch (e) { toast(e.message, true); } };
  const back = h("a", { href: "#/roundtable", class: "muted small" }, "← Roundtable");
  if (!doc) {
    return h("div", {}, back, h("h1", {}, `Plan · ${d.name}`),
      section("No plan document", h("p", { class: "muted" }, d.tasks.length ? "This project was planned before plans became documents: its tasks are below." : "The planner hasn't run yet."),
        d.tasks.length ? taskTree(d.tasks) : null));
  }
  const o = d.open, est = doc.estimate || {};
  const pending = doc.pending || [];
  const instr = h("textarea", { rows: 2, class: "grow", placeholder: "Tell the planner what to change (optional), e.g. “make it a 2D platformer, no multiplayer”" });
  const busy = d.busy ? h("p", { class: "small muted" }, "A job is running on this project; edits wait until it finishes.") : null;
  const head = h("div", { class: "card plan-head" },
    h("div", { class: "card-head" }, h("h2", {}, `Plan v${doc.version}`), h("span", { class: "muted small" }, d.approved ? "approved" : "waiting for you")),
    h("div", { class: "goal" }, h("b", {}, "Goal"), doc.goal),
    doc.summary ? h("p", {}, doc.summary) : null,
    h("div", { class: "row plan-est" },
      h("span", { class: "pill info" }, `about ${money(est.cost_usd || 0)}`),
      est.unpriced && est.unpriced.length ? h("span", { class: "pill warn", title: "Add prices for these in Settings > AI providers / pricing" }, `+ unpriced: ${est.unpriced.join(", ")}`) : null,
      h("span", { class: "pill" }, `about ${Math.round(est.minutes || 0)} min`),
      h("span", { class: "pill" }, `${est.tasks || 0} task(s) to do`),
      h("span", { class: "muted small", title: est.note || "" }, "estimate")),
    profilePicker(doc, edit),
    busy,
    h("div", { class: "row", style: "margin-top:10px" }, instr),
    h("div", { class: "row" },
      h("button", { class: pending.length ? "primary" : "", disabled: d.busy, onclick: () => startJob({ action: "revise", text: instr.value }, "Updating the plan…") },
        pending.length ? `Update plan (${pending.length} change${pending.length > 1 ? "s" : ""})` : "Update plan"),
      h("button", { class: pending.length ? "" : "primary", disabled: d.busy || d.approved || pending.length > 0, title: pending.length ? "Apply your changes first" : "",
        onclick: () => startJob({ action: "approve" }, "Approved: building has started") }, d.approved ? "Approved" : "Approve & start"),
      o.choices ? h("span", { class: "muted small" }, `${o.choices} choice(s) left on the recommendation`) : null),
    pending.length ? h("details", { class: "small" }, h("summary", {}, `Your changes waiting to be applied (${pending.length})`), h("ul", {}, pending.map((p) => h("li", {}, p.text)))) : null);

  // the planner's choices, questions, ideas and the look, as cards to tap (asks.py)
  const pictures = {};
  if (Object.keys((doc.look || {}).pictures || {}).length) {
    try { const r = await api("GET", `/api/plan/looks?path=${q}`); for (const [id, pp] of Object.entries(r.pictures || {})) pictures[id] = pp.desktop; } catch { /* the cards still show the words */ }
  }
  const cardFor = (a) => askCard(a, async (ans) => {
    const r = await answerAsk(a, ans);
    if (r.job) location.hash = `#/job/${r.job.id}`; else await render();
  }, { pictures, disabled: d.busy });
  const mine = (aq.asks || []).filter((a) => ["decision", "question", "look", "idea"].includes(a.kind));
  const waiting = mine.filter((a) => !a.answer), answered = mine.filter((a) => a.answer);
  const madeChoices = d.approved && (doc.decisions || []).length ? section("Choices", h("ul", {}, doc.decisions.map((c) => {
    const pick = c.options.find((op) => op.id === (c.chosen || c.recommended));
    return h("li", {}, h("b", {}, c.question), " ", pick ? pick.label : "", h("span", { class: "muted small" }, c.chosen ? " (your choice)" : " (recommended)"));
  }))) : null;
  const input = mine.length ? section("Your input",
    h("p", { class: "muted small" }, waiting.length ? `${waiting.length} question${waiting.length > 1 ? "s" : ""} for you. Tap an answer: the recommended one is first. Or type your own with Other….`
      : "All answered. Update the plan to apply your answers, then approve it."),
    waiting.length ? h("div", { class: "asks" }, waiting.map(cardFor)) : null,
    answered.length ? h("details", { class: "answered-list" }, h("summary", {}, `Answered (${answered.length}): change an answer`),
      h("div", { class: "asks" }, answered.map(cardFor))) : null) : madeChoices;

  const looks = lookSection(doc.look || {}, d.busy, q, edit, startJob);
  const like = likeSection(doc.references || [], d.busy, edit);

  const cr = doc.critique;
  const critique = cr ? section(`Second opinion · ${cr.model}`,
    h("p", {}, h("span", { class: "pill " + (cr.verdict === "good" ? "good" : "warn") }, cr.verdict === "good" ? "looks good" : "suggested changes"),
      h("span", { class: "muted small" }, ` on plan v${cr.version || 1}` + (cr.verdict !== "good" && (doc.history || []).some((x) => x.by === "critic") ? " · the planner revised the plan in response" : ""))),
    h("ul", {}, (cr.points || []).map((pt) => h("li", {}, h("span", { class: "pill " + ({ high: "bad", medium: "warn" }[pt.severity] || "") }, pt.severity), " ", pt.text,
      pt.suggestion ? h("div", { class: "muted small" }, "Suggestion: ", pt.suggestion) : null)))) : null;

  const listEditor = (title, items, addBody, removeBody, placeholder) => {
    const inp = h("input", { class: "grow", placeholder });
    return h("div", {}, h("h3", {}, title),
      h("ul", { class: "plain" }, items.map((it) => h("li", { class: "row" }, h("span", { class: "grow" }, it.text, it.why ? h("span", { class: "muted small" }, ` · ${it.why}`) : null, it.by === "owner" ? h("span", { class: "pill info", style: "margin-left:6px" }, "yours") : null),
        h("button", { class: "icon danger", disabled: d.busy, onclick: () => edit(removeBody(it)) }, "×")))),
      h("div", { class: "row" }, inp, h("button", { class: "icon", disabled: d.busy, onclick: () => edit(addBody(inp.value)) }, "Add")));
  };
  const scope = section("Scope and rules",
    h("div", { class: "grid2" },
      listEditor("In scope", (doc.in_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", text: v }), (it) => ({ action: "scope_remove", text: it.text }), "add something it must do"),
      listEditor("Out of scope", (doc.out_of_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", out: true, text: v }), (it) => ({ action: "scope_remove", out: true, text: it.text }), "add something to leave out")),
    listEditor("Don't", doc.dont || [], (v) => ({ action: "dont_add", text: v }), (it) => ({ action: "dont_remove", id: it.id }), "add something not to do"));

  const bySection = {};
  d.tasks.forEach((t) => (bySection[t.section || ""] = bySection[t.section || ""] || []).push(t));
  const spec = section("Spec and tasks", (doc.spec || []).map((sp) => {
    const ta = h("textarea", { rows: 4, style: "display:none;width:100%" }, sp.text);
    const save = h("button", { class: "icon primary", style: "display:none", onclick: () => edit({ action: "section", id: sp.id, text: ta.value }, "Section changed") }, "Save");
    const txt = h("p", { class: "pre" }, sp.text);
    return h("div", { class: "spec" },
      h("div", { class: "row" }, h("h3", { class: "grow" }, sp.title, h("span", { class: "muted small" }, ` ${sp.id}`)),
        h("button", { class: "icon", disabled: d.busy, onclick: () => { ta.style.display = ""; save.style.display = ""; txt.style.display = "none"; } }, "Edit")),
      txt, ta, save,
      bySection[sp.id] ? taskTree(bySection[sp.id]) : h("div", { class: "muted small" }, "no tasks under this section"));
  }), (bySection[""] || []).length ? [h("h3", {}, "Other tasks"), taskTree(bySection[""])] : null);

  const history = (doc.history || []).length > 1 ? section("History", h("ul", {}, doc.history.slice().reverse().map((hh) => h("li", { class: "small" },
    `v${hh.version} · ${ago(hh.at)} · ${hh.by === "critic" ? "revised after the second opinion" : hh.by === "owner" ? "your changes" : hh.change || "first plan"}`,
    hh.diff ? h("span", { class: "muted" }, ` (${["added", "changed", "removed"].filter((k) => hh.diff[k] && hh.diff[k].length).map((k) => `${hh.diff[k].length} ${k}`).join(", ") || "tasks unchanged"})`) : null)))) : null;

  return h("div", { class: "plan-page" }, back, h("h1", {}, `Plan · ${d.name}`),
    h("p", { class: "sub" }, "Tap your answers, cut or add, then Update plan. Nothing is built until you approve."),
    head, input, like, looks, critique, scope, spec, history);
}

// "Make it like this": what the owner wants it to be like, as the scout read each one; add or remove.
function likeSection(refs, busy, edit) {
  const inp = h("input", { class: "grow", placeholder: "A link, a GitHub repository or a description, e.g. “the queue from Spotify”" });
  const state = { new: "not read yet", failed: "couldn't read it" };
  const card = (r) => {
    const rep = r.report || {};
    return h("div", { class: "decision" },
      h("div", { class: "row" }, h("b", { class: "grow" }, `${r.id} · ${rep.title || r.input}`),
        state[r.status] ? h("span", { class: "pill " + (r.status === "failed" ? "warn" : "") }, state[r.status]) : null,
        h("button", { class: "icon danger", disabled: busy, title: "Stop making it like this one", onclick: () => edit({ action: "reference_remove", id: r.id }, "Removed. Update the plan to apply it.") }, "×")),
      rep.what_it_is ? h("div", { class: "small" }, rep.what_it_is) : null,
      r.status === "failed" ? h("div", { class: "muted small" }, r.error) : null,
      (rep.borrow || []).length ? h("div", { class: "small" }, h("b", {}, "Borrow: "), rep.borrow.join("; ")) : null,
      (rep.avoid || []).length ? h("div", { class: "small" }, h("b", {}, "Avoid: "), rep.avoid.join("; ")) : null,
      r.report ? h("div", { class: "muted small", title: "Code is only used when the licence clearly allows it, and then it's credited" },
        `Licence: ${rep.licence} · code: ${rep.code_reuse}`) : null,
      (rep.unreadable || []).length ? h("div", { class: "muted small" }, "Couldn't read: ", rep.unreadable.join("; ")) : null);
  };
  return section("Like these",
    h("p", { class: "muted small" }, "Things you want it to be like. Roundtable makes something similar, never a copy: no names, characters, art, music or text taken."),
    refs.map(card),
    h("div", { class: "row" }, inp, h("button", { disabled: busy, title: "It's read (a model call, so it costs a little) when you next update the plan",
      onclick: () => edit({ action: "reference_add", text: inp.value }, "Added. Update the plan to read it and use it.") }, "Add")));
}

// The look: the designer's directions side by side, a "Choose this look" button each, and "Make new looks".
function lookSection(lk, busy, q, edit, startJob) {
  const dirs = lk.directions || [];
  const brief = h("input", { class: "grow", placeholder: "A starting point for new looks (optional), e.g. “like an old record shop”" });
  const swatch = (hex, title) => h("span", { class: "swatch", title: `${title} ${hex}`, style: `background:${hex}` });
  const card = (x) => {
    const chosen = lk.chosen === x.id, light = x.palette.light;
    return h("div", { class: "look" + (chosen ? " chosen" : "") },
      h("b", {}, `${x.id} · ${x.name}`, chosen ? h("span", { class: "pill info", style: "margin-left:6px" }, "your choice") : null),
      h("div", { class: "small" }, x.mood),
      h("div", { class: "muted small" }, "Signature: ", x.signature),
      h("div", { class: "row swatches", title: "Its colours (light)" }, ["background", "surface", "text", "accent"].map((k) => swatch(light[k], k)),
        h("span", { class: "muted small" }, `${x.fonts.display.family} · ${x.fonts.body.family}`)));
  };
  return section("Look",
    h("p", { class: "muted small" }, dirs.length ? "The looks in detail. Choose one with the Look card under Your input; every task then follows its design file."
      : "No looks yet. Roundtable can design three different looks for the app, with a picture of each, for you to choose from."),
    dirs.length ? h("div", { class: "looks" }, dirs.map(card)) : null,
    dirs.length && !Object.keys(lk.pictures || {}).length && lk.render_note ? h("p", { class: "muted small" }, lk.render_note) : null,
    h("div", { class: "row" }, brief, h("button", { disabled: busy, title: "Asks the designer for new looks (a model call, so it costs a little)",
      onclick: () => startJob({ action: "looks", text: brief.value }, "Designing new looks…") }, dirs.length ? "Make new looks" : "Make looks")));
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

// ---------- setup & settings ----------
function keysCard(st) {
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const keys = {};
    form.querySelectorAll("input[data-key]").forEach((i) => { if (i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
    if (!Object.keys(keys).length) return toast("Paste at least one key", true);
    await act(() => api("POST", "/api/setup/keys", { keys }), "Keys saved");
  } },
  st.keys.map((k) => h("div", { class: "row" },
    h("span", { style: "width:210px" }, k.label, " ", k.set ? h("span", { class: "pill good" }, "saved") : h("span", { class: "pill" }, "not set")),
    h("input", { type: "password", class: "grow", "data-key": k.name, placeholder: k.set ? "•••••••• (paste a new key to replace it)" : `paste your ${k.label} API key`, autocomplete: "off", disabled: !st.desktop }),
    k.set && st.desktop ? h("button", { type: "button", class: "icon danger", onclick: () => { if (confirm(`Remove the ${k.label} key?`)) act(() => api("POST", "/api/setup/keys", { keys: { [k.name]: "" } }), "Key removed"); } }, "Remove") : null)),
  st.desktop ? h("div", { class: "row" }, h("button", { class: "primary" }, "Save keys"),
    h("span", { class: "muted small" }, st.secure_keys ? "Stored in your system's credential manager (Windows Credential Manager), never in plain files." : "Stored in a private file in your Roundtable Hold folder.")) :
    h("p", { class: "muted small" }, "Running from the terminal: keys come from environment variables (ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, …)."));
  return section("API keys", h("p", { class: "muted small" }, "Only the providers you use need a key. You can change these any time in Settings."), form);
}

function hubCard(st) {
  const url = field("url", { class: "grow", placeholder: "https://github.com/you/agent-hub-data" });
  const connect = async () => {
    const j = await act(() => api("POST", "/api/setup/hub", { mode: "github", url: url.value }), "Connecting…");
    if (j && j.id) location.hash = `#/job/${j.id}`;
  };
  return section("Your hub (projects, journal, messages)",
    h("p", {}, "Now: ", st.hub.mode === "git" ? h("span", { class: "pill good" }, "synced with GitHub") : st.hub.mode === "file" ? h("span", { class: "pill info" }, "this computer only") : h("span", { class: "pill bad" }, "not set up"),
      st.hub.where ? h("span", { class: "muted small" }, " · " + st.hub.where) : null),
    st.hub.error ? h("p", { class: "small", style: "color:var(--bad)" }, st.hub.error) : null,
    st.desktop ? [
      h("p", { class: "muted small" }, "Sync with a GitHub repository (like your agent-hub-data) to share your journal and projects with every computer and Claude session."),
      st.git ? h("div", { class: "row" }, url, h("button", { class: "primary", onclick: connect }, "Connect"))
        : h("p", { class: "small" }, "GitHub sync needs Git: install ", h("a", { href: "https://git-scm.com/download/win", target: "_blank", rel: "noopener" }, "Git for Windows"), ", then reopen Roundtable Hold. Until then everything works on this computer only."),
      st.hub.mode === "git" ? h("div", { class: "row", style: "margin-top:8px" }, h("button", { onclick: () => { if (confirm("Stop syncing and keep the hub on this computer only?")) act(() => api("POST", "/api/setup/hub", { mode: "local" }), "Hub is now local"); } }, "Use this computer only")) : null,
    ] : h("p", { class: "muted small" }, `Configured in ${st.config_paths.hub}.`));
}

async function viewSetup() {
  const st = await api("GET", "/api/setup");
  const projects = field("projects_dir", { class: "grow", value: st.projects_dir });
  const me = st.agents.length ? select("agent", st.agents, st.agent || st.agents[0]) : null;
  return h("div", {},
    h("h1", {}, "Welcome to Roundtable Hold"),
    h("p", { class: "sub" }, "Three quick steps and you're ready: add your API keys, connect your hub, pick a projects folder."),
    keysCard(st), hubCard(st),
    section("Finish",
      h("div", { class: "row" }, h("span", { style: "width:210px" }, "Projects folder"), projects),
      me ? h("div", { class: "row", style: "margin-top:8px" }, h("span", { style: "width:210px" }, "You are"), me, h("span", { class: "muted small" }, "(your identity in the hub)")) : null,
      h("div", { class: "row", style: "margin-top:12px" },
        h("button", { class: "primary", onclick: async () => {
          await api("POST", "/api/setup/done", { projects_dir: projects.value, agent: me ? me.value : null });
          toast("All set!"); location.hash = "#/roundtable";
        } }, "Start using Roundtable Hold"),
        h("button", { onclick: async () => { const j = await act(() => api("POST", "/api/probes", {}), "Checking your models…"); if (j && j.id) location.hash = `#/job/${j.id}`; } }, "Check my models first"))));
}

async function providersCard() {
  let data;
  try { data = await api("GET", "/api/providers"); } catch (e) { return section("AI providers", h("p", { class: "muted" }, e.message)); }
  const out = h("div", { class: "small", style: "margin-top:8px" });
  const models = new Set();
  const modelList = h("datalist", { id: "known-models" });
  const addModels = (pid, list) => { list.forEach((m) => models.add(`${pid}/${m}`)); modelList.replaceChildren(...[...models].sort().map((m) => h("option", { value: m }))); };
  data.roles.forEach((r) => r.models.forEach((m) => models.add(m)));
  addModels("", []);
  const showResult = (pid, r) => out.replaceChildren(r.ok ? h("span", {}, h("span", { class: "pill good" }, "OK"), ` ${pid}: ${r.models} model(s), e.g. ${r.sample.slice(0, 6).join(", ")}`)
    : h("span", {}, h("span", { class: "pill bad" }, "failed"), ` ${pid}: ${r.error}`));
  const table = h("table", {}, h("tr", {}, h("th", {}, "Provider"), h("th", {}, "Type"), h("th", {}, "Key"), h("th", {}, "")),
    data.providers.map((p) => h("tr", {},
      h("td", {}, h("strong", {}, p.id), p.base_url ? h("div", { class: "muted small" }, p.base_url) : null),
      h("td", { class: "small" }, p.type, h("div", { class: "muted small" }, p.source)),
      h("td", {}, !p.needs_key ? h("span", { class: "pill" }, "none needed") : p.key_set ? h("span", { class: "pill good" }, "set") : h("span", { class: "pill warn" }, `missing: ${p.api_key_env}`)),
      h("td", { class: "actions" }, h("div", { class: "row" },
        h("button", { class: "icon", onclick: async () => { out.textContent = `testing ${p.id}…`; try { showResult(p.id, await api("POST", "/api/providers", { action: "test", id: p.id })); } catch (e) { toast(e.message, true); } } }, "Test"),
        h("button", { class: "icon", onclick: async () => { out.textContent = `loading ${p.id} models…`; try { const r = await api("POST", "/api/providers", { action: "models", id: p.id }); addModels(p.id, r.models); out.replaceChildren(h("pre", {}, r.models.map((m) => `${p.id}/${m}`).join("\n"))); } catch (e) { out.textContent = ""; toast(e.message, true); } } }, "Models"),
        p.source === "custom.yaml" ? h("button", { class: "icon danger", onclick: () => { if (confirm(`Remove provider ${p.id}?`)) act(() => api("POST", "/api/providers", { action: "remove", id: p.id }), "Removed"); } }, "Remove") : null)))));
  // add a provider
  const presetIds = Object.keys(data.presets);
  const preset = select("preset", presetIds.map((id) => [id, data.presets[id].name]), "openrouter");
  const idIn = field("id", { placeholder: "name (optional)", style: "width:150px" });
  const urlIn = field("base_url", { class: "grow", placeholder: "base URL (custom only)" });
  const keyIn = h("input", { type: "password", name: "key", class: "grow", placeholder: data.desktop ? "API key (saved securely)" : "set the key as an environment variable", disabled: !data.desktop, autocomplete: "off" });
  const hdr = field("auth_header", { placeholder: "key header, e.g. api-key (optional)" });
  const qry = field("query", { class: "grow", placeholder: "query params, e.g. api-version=2025-01-01 (optional)" });
  const docs = h("a", { target: "_blank", rel: "noopener" });
  const sync = () => { const p = data.presets[preset.value]; urlIn.value = p.base_url || ""; urlIn.disabled = !p.custom; docs.href = p.docs || "#"; docs.textContent = p.docs ? "where to get a key" : ""; keyIn.disabled = !data.desktop || (!p.api_key_env && !p.custom); };
  preset.addEventListener("change", sync); sync();
  const addForm = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const query = {};
    qry.value.split(/[,&]/).map((x) => x.trim()).filter(Boolean).forEach((kv) => { const [k, ...v] = kv.split("="); query[k.trim()] = v.join("=").trim(); });
    try {
      const r = await api("POST", "/api/providers", { action: "add", preset: preset.value, id: idIn.value, base_url: urlIn.value, key: keyIn.value, auth_header: hdr.value, query });
      toast(`Added ${r.added.id}`);
      await render();
      showResult(r.added.id, r.test);
    } catch (e) { toast(e.message, true); }
  } },
  h("div", { class: "row" }, preset, idIn, docs),
  h("div", { class: "row" }, urlIn, keyIn),
  h("details", {}, h("summary", { class: "small" }, "advanced (Azure, custom gateways)"), h("div", { class: "row", style: "margin-top:6px" }, hdr, qry)),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Add provider"), h("span", { class: "muted small" }, "Saved to custom.yaml; tested right away. Anything not listed: choose Custom (any OpenAI-compatible URL) or add a plugin (see README).")));
  // which model does what
  const roleRows = data.roles.map((r) => {
    const inp = field("models", { style: "width:100%", value: r.models.join(", "), list: "known-models", placeholder: "provider/model, fallback, …" });
    return h("tr", {}, h("td", {}, h("strong", {}, r.name), h("div", { class: "muted small" }, r.kind)),
      h("td", { style: "width:70%" }, inp), h("td", {}, h("button", { class: "icon", onclick: () => act(() => api("POST", "/api/assign", { role: r.name, models: inp.value }), `${r.name} updated`) }, "Save")));
  });
  return h("div", {},
    section("AI providers", h("p", { class: "muted small" }, "Any API works: pick one of the built-in providers, a custom OpenAI-compatible URL, or a plugin."), table, out,
      h("h3", {}, "Add a provider"), addForm),
    section("Which model does what", h("p", { class: "muted small" }, "Primary model first, then fallbacks, separated by commas. Click Models on a provider to fill the suggestions."),
      modelList, h("table", {}, h("tr", {}, h("th", {}, "Role"), h("th", {}, "Models"), h("th", {}, "")), roleRows)));
}

const SHOW_PHONE = false;  // turned on with the Roundtable Mobile release
async function phoneCard() {
  let st;
  try { st = await api("GET", "/api/phone"); } catch (e) { return section("Phone (Roundtable Mobile)", h("p", { class: "muted" }, e.message)); }
  const box = h("div");
  const call = async (body, ok) => { try { const r = await api("POST", "/api/phone", body); if (ok) toast(ok); draw(r); } catch (e) { toast(e.message, true); } };
  let timer = null;
  function draw(s) {
    clearTimeout(timer);
    const pairing = s.pairing ? h("div", { class: "row", style: "align-items:flex-start;margin-top:10px" },
      h("img", { src: s.pairing.qr, alt: "Pairing QR code", width: 220, height: 220, style: "border-radius:8px" }),
      h("div", { class: "stack" },
        h("p", {}, "In Roundtable Mobile tap ", h("strong", {}, "Pair with a PC"), " and scan this code."),
        h("p", {}, "Or type the code: ", h("strong", { style: "font-size:20px;letter-spacing:3px" }, s.pairing.code)),
        h("p", { class: "muted small" }, `Valid for ${Math.max(0, Math.ceil(s.pairing.expires_in / 60))} more minute(s), once.`))) : null;
    const devices = s.devices.length ? h("table", {}, h("tr", {}, h("th", {}, "Paired phone"), h("th", {}, "Paired"), h("th", {}, "Last seen"), h("th", {}, "")),
      s.devices.map((d) => h("tr", {}, h("td", {}, d.name), h("td", { class: "small" }, ago(d.paired_at)), h("td", { class: "small" }, ago(d.last_seen)),
        h("td", { class: "actions" }, h("button", { class: "icon danger", onclick: () => { if (confirm(`Remove ${d.name}? It will need to pair again.`)) call({ action: "revoke", device_id: d.id }, "Phone removed"); } }, "Remove")))))
      : h("p", { class: "muted small" }, "No phones paired yet.");
    box.replaceChildren(
      h("p", {}, "Now: ", s.running ? h("span", { class: "pill good" }, `on · port ${s.port}`) : s.enabled ? h("span", { class: "pill bad" }, "on, but not running") : h("span", { class: "pill" }, "off"),
        s.running && s.addresses.length ? h("span", { class: "muted small" }, " · reachable at " + s.addresses.join(", ")) : null),
      s.error ? h("p", { class: "small", style: "color:var(--bad)" }, s.error) : null,
      h("p", { class: "muted small" }, "Paired phones can see every project, approve, retry, steer and chat, and read and send hub messages. Settings, API keys and updates stay on this PC. The connection is encrypted; away from home it works through Tailscale."),
      h("div", { class: "row" },
        s.running ? h("button", { class: "primary", onclick: () => call({ action: "pair" }) }, "Pair a phone") : h("button", { class: "primary", onclick: () => call({ action: "enable" }, "Phone access is on") }, "Turn on phone access"),
        s.enabled ? h("button", { onclick: () => { if (confirm("Turn off phone access? Paired phones stay paired and reconnect when you turn it on again.")) call({ action: "disable" }, "Phone access is off"); } }, "Turn off") : null),
      pairing, h("h3", {}, "Paired phones"), devices);
    if (s.pairing) timer = setTimeout(async () => { if (box.isConnected) draw(await api("GET", "/api/phone")); }, 4000);
  }
  draw(st);
  return section("Phone (Roundtable Mobile)", box);
}

// ---------- Settings → Backups ----------
function fileSize(n) { const u = ["bytes", "KB", "MB", "GB"]; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return i ? `${n.toFixed(1)} ${u[i]}` : `${n} bytes`; }
// Settings → Plugins: switch them on and off, change their settings, add one (after showing what it may do).
async function pluginsCard() {
  let st;
  try { st = await api("GET", "/api/plugins"); } catch (e) { return section("Plugins", h("p", { class: "muted" }, e.message)); }
  const trust = "A plugin is someone's program: it runs with the same access as Roundtable Hold. Roundtable can't hold it to what it says, so only add plugins from people you trust.";
  const post = async (body, ok) => {
    try {
      const r = await api("POST", "/api/plugins", body);
      if (r && r.needs_ok) {
        const perms = (r.needs_ok.permissions || []).map((p) => `• ${p.words}`).join("\n");
        if (!confirm(`${r.message || "This plugin asks for:"}\n\n${perms || "• nothing special"}\n\n${trust}\n\nAdd it?`)) return;
        return post({ ...body, confirmed: (r.needs_ok.permissions || []).map((p) => p.id) }, ok);
      }
      if (ok) toast(ok);
      render();
    } catch (e) { toast(e.message, true); }
  };
  const rows = st.plugins.map((p) => {
    const fields = (p.settings || []).map((f) => {
      const input = f.type === "boolean"
        ? h("input", { type: "checkbox", checked: !!f.value, title: f.description })
        : h("input", { class: "grow", value: f.value ?? "", title: f.description, placeholder: String(f.default ?? "") });
      input.dataset.key = f.key;
      input.dataset.type = f.type;
      return h("label", { class: "row small", title: f.description }, h("span", { class: "muted" }, f.key), input);
    });
    const saveSettings = () => {
      const values = {};
      for (const el of fields.map((l) => l.querySelector("input"))) values[el.dataset.key] = el.type === "checkbox" ? el.checked : el.value;
      post({ action: "settings", id: p.id, values }, "Saved");
    };
    return h("div", { class: "card plugin" },
      h("div", { class: "card-head" },
        h("b", {}, p.name || p.id), h("span", { class: "muted small" }, ` ${p.version || ""}${p.builtin ? " · built in" : ""}`),
        h("label", { class: "small", title: p.enabled ? "Switch it off" : "Switch it on" },
          h("input", { type: "checkbox", checked: p.enabled, onchange: (ev) => post({ action: ev.target.checked ? "enable" : "disable", id: p.id }, ev.target.checked ? "Switched on" : "Switched off") }),
          " on")),
      h("p", { class: "small" }, p.description || ""),
      p.problem ? h("p", { class: "small warn" }, p.problem) : null,
      (p.permissions || []).length ? h("p", { class: "small muted", title: trust }, "May: " + p.permissions.map((x) => x.words).join("; ")) : null,
      fields.length ? h("details", { class: "small" }, h("summary", {}, "Settings"), ...fields, h("button", { onclick: saveSettings }, "Save settings")) : null,
      p.builtin ? null : h("button", { class: "small", onclick: () => confirm(`Remove ${p.name || p.id}?`) && post({ action: "remove", id: p.id }, "Removed") }, "Remove"));
  });
  const source = h("input", { class: "grow", placeholder: "a folder, a GitHub link or a Python package name", title: "Where the plugin comes from. You'll see what it may do before anything is installed." });
  return section("Plugins",
    h("p", { class: "muted small" }, "Extra abilities for Roundtable, like the token saver. ", h("span", { title: trust }, "Only add plugins from people you trust.")),
    ...rows,
    h("div", { class: "row" }, source, h("button", { onclick: () => source.value.trim() && post({ action: "add", source: source.value.trim() }, "Plugin added") }, "Add a plugin")));
}

async function backupsCard() {
  let st;
  try { st = await api("GET", "/api/backup"); } catch (e) { return section("Backups", h("p", { class: "muted" }, e.message)); }
  const box = h("div");
  const save = async (body, ok) => { try { const r = await api("POST", "/api/backup", { action: "settings", ...body }); if (ok) toast(ok); draw(r); } catch (e) { toast(e.message, true); } };
  function draw(s) {
    const set = s.settings;
    const folder = h("input", { class: "grow", value: set.to === "auto" ? "" : set.to, placeholder: "a folder, e.g. D:\\Backups or your OneDrive folder",
      title: "Leave empty to use Google Drive. Any folder works: OneDrive, a USB stick, another disk." });
    const phrase = h("input", { type: "password", class: "grow", autocomplete: "off",
      placeholder: s.passphrase_remembered ? "•••••••• (remembered until you close the app)" : "passphrase (optional, recommended)",
      title: "Locks the backup so only someone with the passphrase can open it. It's never saved: if you forget it, the backup can't be opened." });
    const remember = h("input", { type: "checkbox", checked: s.passphrase_remembered, onchange: async (ev) => {
      if (ev.target.checked && !phrase.value) { ev.target.checked = false; return toast("Type the passphrase first", true); }
      try { draw(await api("POST", "/api/backup", { action: "passphrase", passphrase: phrase.value, remember: ev.target.checked })); toast(ev.target.checked ? "Remembered until you close the app" : "Forgotten"); }
      catch (e) { toast(e.message, true); }
    } });
    const pick = h("select", { class: "grow" }, s.backups.map((b) => h("option", { value: b.path }, `${b.name} · ${fileSize(b.size)}${b.locked ? " · locked" : ""}`)));
    const other = h("input", { class: "grow", placeholder: "or the full path of a backup file" });
    const now = async () => {
      if (set.encrypt && !phrase.value && !s.passphrase_remembered) return toast("Type the passphrase first: backups are set to be locked.", true);
      const j = await act(() => api("POST", "/api/backup", { action: "now", passphrase: phrase.value, remember: remember.checked }), "Backing up…");
      if (j && j.id) location.hash = `#/job/${j.id}`;
    };
    const restore = async () => {
      const file = other.value.trim() || pick.value;
      if (!file) return toast("Choose a backup to restore", true);
      try {
        const info = await api("POST", "/api/backup", { action: "inspect", file, passphrase: phrase.value });
        const text = info.lines.join("\n") + "\n\nA safety backup of what's here now is made first. Afterwards, type your API keys again and pair your phones again.\n\nRestore now?";
        if (!confirm(text)) return;
        const j = await api("POST", "/api/backup", { action: "restore", file, passphrase: phrase.value, confirm: true });
        toast("Restoring…");
        location.hash = `#/job/${j.id}`;
      } catch (e) { toast(e.message, true); }
    };
    const last = s.last.last_at ? `${ago(s.last.last_at)} · ${fileSize(s.last.last_size || 0)}` : "none yet";
    box.replaceChildren(
      h("p", { class: "muted small" }, "A backup holds your settings, what Roundtable has learned, and every project's plan and history. It never holds your API keys."),
      s.destination ? h("p", {}, "Backups go to: ", h("strong", { title: s.destination }, s.destination))
        : h("p", { class: "small", style: "color:var(--bad)" }, s.no_drive),
      h("div", { class: "row" }, folder,
        h("button", { onclick: () => save({ to: folder.value.trim() || "auto" }, "Saved") }, "Use this folder"),
        set.to !== "auto" ? h("button", { title: s.found.length ? s.found[0] : "Google Drive for desktop isn't installed", onclick: () => save({ to: "auto" }, "Backups go to Google Drive") }, "Use Google Drive") : null),
      h("p", {}, "Last backup: ", last, s.last.last_error ? h("span", { class: "pill warn", title: s.last.last_error }, "problem") : null),
      s.last.last_error ? h("p", { class: "small", style: "color:var(--bad)" }, s.last.last_error) : null,
      h("div", { class: "row" },
        h("label", { class: "check", title: "Once a day while Roundtable Hold is open, never while a project is running" },
          h("input", { type: "checkbox", checked: set.daily, onchange: (ev) => save({ daily: ev.target.checked }, ev.target.checked ? "Daily backups on" : "Daily backups off") }), "Back up every day"),
        h("label", { class: "check", title: "Older backups from this PC are deleted; nothing else in the folder is touched" }, "Keep the newest ",
          h("input", { type: "number", min: 1, max: 100, value: set.keep, style: "width:60px", onchange: (ev) => save({ keep: Number(ev.target.value) }, "Saved") }), " backups"),
        h("label", { class: "check", title: "Recommended: a backup holds your plans. The daily backup needs the passphrase typed once each time the app opens." },
          h("input", { type: "checkbox", checked: set.encrypt, onchange: (ev) => save({ encrypt: ev.target.checked }, "Saved") }), "Lock with a passphrase")),
      h("div", { class: "row" }, phrase,
        h("label", { class: "check", title: "Kept in memory only, until you close the app, so the daily backup can be locked" }, remember, "Remember until I close the app"),
        h("button", { class: "primary", onclick: now }, "Back up now")),
      h("h3", {}, "Restore"),
      h("p", { class: "muted small" }, "Puts a backup's settings, plans and history back. Projects whose folders are gone are made again."),
      h("div", { class: "row" }, s.backups.length ? pick : h("span", { class: "muted small" }, "No backups in that folder yet."), other,
        h("button", { class: "danger", onclick: restore, title: "Shows what it would replace and asks first" }, "Restore…")));
  }
  draw(st);
  return section("Backups", box);
}

// Settings > Look: light, dark, or the computer's choice (theme.js applies it before the page draws).
function lookCard() {
  let now = "system";
  try { now = localStorage.getItem("rt-theme") || "system"; } catch { /* storage unavailable */ }
  const pick = (v) => {
    try { if (v === "system") localStorage.removeItem("rt-theme"); else localStorage.setItem("rt-theme", v); } catch { /* storage unavailable */ }
    if (v === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
    card.replaceWith(lookCard());
  };
  const choices = [["light", "Light", "Warm parchment and oak"], ["dark", "Dark", "The hall by candlelight"], ["system", "Same as this computer", "Follows the computer's light or dark setting"]];
  const card = section("Look",
    h("p", { class: "muted small" }, "How Roundtable looks on this computer."),
    h("div", { class: "look-pick", role: "group", "aria-label": "Light or dark" }, choices.map(([v, label, tip]) =>
      h("button", { class: v === now ? "on" : "", type: "button", title: tip, "aria-pressed": String(v === now), onclick: () => pick(v) }, label))));
  return card;
}

async function viewSettings() {
  const [st, upd] = await Promise.all([api("GET", "/api/setup"), api("GET", "/api/update").catch(() => ({}))]);
  const editor = async (which) => {
    let c;
    try { c = await api("GET", `/api/config?which=${which}`); }
    catch (e) {  // e.g. no hub set up yet: say so, don't break the whole Settings page
      return h("details", {}, h("summary", {}, `${which}.yaml`, h("span", { class: "muted small" }, " · not set up yet")),
        h("p", { class: "muted small" }, which === "hub"
          ? "There's no hub file yet. Set up the hub in the Hub card above (or run the setup again)."
          : `There's no ${which}.yaml yet. Run the setup again to make one.`));
    }
    const ta = h("textarea", { style: "min-height:320px;font-family:ui-monospace,monospace;font-size:12px" }, c.text);
    return h("details", {}, h("summary", {}, `${which}.yaml`, h("span", { class: "muted small" }, ` · ${c.path}`)),
      h("p", { class: "muted small" }, which === "harness" ? "Providers, which model does which role, prices, limits." : "Projects (agents) and who may read or message whom."),
      ta, h("div", { class: "row" }, h("button", { class: "primary", onclick: () => act(() => api("POST", "/api/config", { which, text: ta.value }), (r) => `Saved (backup: ${r.backup})`) }, "Save"),
        h("span", { class: "muted small" }, "Checked before saving; a backup of the old file is kept.")));
  };
  const editors = await Promise.all(["harness", "hub"].map(editor));
  return h("div", {}, h("h1", {}, "Settings"),
    h("p", { class: "sub" }, `Roundtable Hold ${st.version}`, st.home ? ` · data in ${st.home}` : ""),
    lookCard(), keysCard(st), await providersCard(), hubCard(st), await backupsCard(), await pluginsCard(), SHOW_PHONE ? await phoneCard() : null,
    section("Config files (advanced)", editors),
    section("Updates",
      h("p", {}, upd.message || upd.error || "…"),
      h("div", { class: "row" },
        h("button", { class: "primary", disabled: !upd.available, onclick: async () => { const j = await act(() => api("POST", "/api/update", {}), "Updating…"); if (j && j.id) location.hash = `#/job/${j.id}`; } }, upd.available ? "Install update" : "Up to date"),
        h("button", { onclick: () => render() }, "Check again"))),
    st.desktop ? section("Setup", h("button", { onclick: () => (location.hash = "#/setup") }, "Run the setup again")) : null);
}

// ---------- autopilot: the header toggle, its card and what it did ----------
let AP = null, apOpen = false;
const AP_UNTIL = [
  ["", "Off when I'm back", "It stays on until you turn it off yourself."],
  ["1h", "1 hour", "It turns itself off in an hour."],
  ["tonight", "Tonight", "It turns itself off at 8am tomorrow morning."],
  ["custom", "Custom", "Pick the time it turns itself off."],
];
async function loadAutopilot(soft = false) {
  try { drawAutopilot(await api("GET", "/api/autopilot?limit=40"), soft); } catch { /* the header can do without it */ }
}
function drawAutopilot(st, soft = false) {  // soft: the Hall's refresh; an open card isn't redrawn under the owner's hands
  const box = document.getElementById("autopilot");
  if (!box) return;
  const was = AP && AP.on;
  AP = { ...(AP || {}), ...st };
  if (soft && apOpen && box.querySelector(".ap-card") && was === AP.on) {
    box.querySelector(".ap-toggle").replaceWith(autopilotButton());
    return;
  }
  box.replaceChildren(...[autopilotButton(), apOpen ? autopilotCard() : null].filter(Boolean));
}
function autopilotButton() {
  const on = AP.on;
  const btn = h("button", { type: "button", class: "ap-toggle" + (on ? " on" : ""), "aria-expanded": String(apOpen), "aria-haspopup": "dialog",
    title: on ? "Autopilot is answering what waits for you with the recommended answers. Click to see what it did or turn it off."
      : "Autopilot: while you're away, Roundtable answers what waits for you with the recommended answers. Click to set it up.",
    onclick: () => { apOpen = !apOpen; drawAutopilot({}); if (apOpen) loadAutopilot(); } },
  h("i", { class: "ap-dot", "aria-hidden": "true" }), h("b", {}, "Autopilot"), on ? h("span", { class: "ap-label" }, AP.label) : null);
  return btn;
}
function autopilotCard() {
  const close = () => { apOpen = false; drawAutopilot({}); };
  const card = h("div", { class: "ap-card", role: "dialog", "aria-label": "Autopilot", onkeydown: (ev) => { if (ev.key === "Escape") close(); } },
    h("div", { class: "card-head" }, h("h2", {}, "Autopilot"), h("button", { class: "link-btn", type: "button", onclick: close, title: "Close" }, "Close")),
    AP.on ? autopilotOn() : autopilotOff(),
    h("h3", {}, "What autopilot did"), autopilotLog());
  return card;
}
function autopilotOn() {
  const turnOff = h("button", { class: "primary", type: "button", onclick: async () => {
    try { drawAutopilot(await api("POST", "/api/autopilot", { action: "off" })); toast("Autopilot is off"); } catch (e) { toast(e.message, true); }
  } }, "Turn off");
  return [h("p", { class: "ap-now" }, h("b", {}, "On"), ` · ${AP.label}`),
    h("p", { class: "small muted" }, "It answers with the recommended answer, tries a failed task once more and starts a plan when its cost fits the limit. Money pauses and anything that asks “Are you sure?” wait for you."),
    h("div", { class: "row" }, turnOff)];
}
function autopilotOff() {
  let until = "";
  const custom = h("input", { type: "time", value: "08:00", hidden: true, "aria-label": "Turn off at",
    title: "The time it turns itself off (this computer's time)" });
  const choices = h("div", { class: "ap-seg", role: "group", "aria-label": "Until" }, AP_UNTIL.map(([v, label, tip]) =>
    h("button", { type: "button", class: v === until ? "on" : "", title: tip, "aria-pressed": String(v === until), onclick: (ev) => {
      until = v; custom.hidden = v !== "custom";
      choices.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b === ev.currentTarget); b.setAttribute("aria-pressed", String(b === ev.currentTarget)); });
    } }, label)));
  const cap = h("input", { type: "number", min: "0.5", max: "1000", step: "0.5", value: Number(AP.spend_cap_usd || 2).toFixed(2), class: "ap-cap",
    "aria-label": "Spend limit in dollars", title: "The most autopilot may spend while it's on. When it gets there it turns itself off. Real money: checked against your providers' balances where they report one." });
  const go = h("button", { class: "primary", type: "button", onclick: async () => {
    go.disabled = true;
    try {
      const r = await api("POST", "/api/autopilot", { action: "on", until: until === "custom" ? custom.value : until, cap: Number(cap.value) });
      drawAutopilot(r); toast(`Autopilot is on, ${r.label}`);
    } catch (e) { toast(e.message, true); go.disabled = false; }
  } }, "Turn on");
  return [h("p", { class: "small muted" }, "While you're away, Roundtable answers what waits for you with the recommended answer and writes down every choice. It never raises a limit, never picks anything that asks “Are you sure?”, and never deletes, publishes or releases anything."),
    h("label", { class: "stack", title: "When autopilot turns itself off" }, h("span", { class: "small muted" }, "Until"), choices, custom),
    h("label", { class: "stack ap-capline" }, h("span", { class: "small muted", title: "The most it may spend while it's on, on every project together" }, "Spend limit"),
      h("span", { class: "row" }, h("b", {}, "$"), cap, h("span", { class: "small muted" }, "then it stops"))),
    h("div", { class: "row" }, go)];
}
function autopilotLog() {
  const log = AP.log || [];
  if (!log.length) return h("div", { class: "empty" }, "Nothing yet. Its choices show up here, newest first.");
  return h("ul", { class: "ap-log" }, log.map((e) => h("li", { class: "ap-" + e.kind },
    h("time", { title: e.at }, ago(e.at)),
    e.project ? h("a", { href: e.path ? `#/plan/${encodeURIComponent(e.path)}` : "#/roundtable", title: "Open the project's plan",
      onclick: () => { apOpen = false; drawAutopilot({}); } }, e.project) : null,
    h("span", {}, e.text))));
}
document.addEventListener("click", (ev) => {  // a click elsewhere closes the card
  const box = document.getElementById("autopilot");
  if (apOpen && box && !box.contains(ev.target) && ev.target.isConnected) { apOpen = false; drawAutopilot({}); }
});

// ---------- updater banner (checked once per page load) ----------
async function checkUpdate() {
  const el = document.getElementById("update-banner");
  try {
    const st = await api("GET", "/api/update");
    if (!st.available) return;
    el.replaceChildren(h("strong", {}, "Update available"), h("span", { class: "muted small" }, st.message),
      h("span", { class: "spacer" }),
      h("button", { class: "primary", onclick: async () => {
        const j = await act(() => api("POST", "/api/update", {}), "Updating…");
        if (j && j.id) { el.hidden = true; location.hash = `#/job/${j.id}`; }
      } }, "Update now"),
      h("button", { onclick: () => (el.hidden = true) }, "Later"));
    el.hidden = false;
  } catch { /* offline: no banner */ }
}

render();
checkUpdate();
