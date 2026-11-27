// Needs you: everything waiting for the owner, grouped by project, then questions and decisions → money and stopped
// work → to-dos → letters, each answered on its card.
import { h, fill, get, post, toast, act, S, onHall, refreshHall, projectName, projectHref, page, empty, dot, ago, plural, patch, q, dialog, seatOf } from "./core.js";
import { askCard, answerHere, answerHub, skipHere, hubCommand } from "./asks.js";

const RANK_WORDS = ["Questions and decisions", "Money, commands and stopped work", "To-dos", "Letters"];
const askRank = (a) => (a.kind === "money" || a.kind === "failed" || a.kind === "command" ? 1 : 0);
const after = async (done) => { await refreshHall(); if (done) await done(); };

// What waits, as items: {project, rank, kind, ...}; local projects' every card from /api/asks, the rest from the Hall.
export async function gather(rt, full = true) {
  const items = [];
  const local = new Set();
  if (full && S.ov && S.ov.harness) {
    try {
      const r = await get("/api/asks");
      for (const a of r.asks || []) {
        const seat = rt.seats.find((s) => s.path === a.path) || seatOf(a.project);
        const id = seat ? seat.id : a.project;
        local.add(id);
        // a waiting command is answered while its project works: that's the point of it
        items.push({ project: id, rank: askRank(a), kind: "local-ask", ask: a, busy: a.busy && a.kind !== "command" });
      }
    } catch { /* fall back to the Hall's first cards */ }
  }
  for (const n of rt.needs_you || []) {
    if (n.kind === "run") {
      if (local.has(n.project)) continue;
      if (n.ask) items.push({ project: n.project, rank: n.rank, kind: "local-ask", ask: n.ask, more: n.asks - 1 });
      else items.push({ project: n.project, rank: n.rank, kind: "run", need: n });
    } else if (n.kind === "ask") {
      let asks = [n.ask];
      if (full && n.asks > 1) {
        try { asks = (await get(`/api/hub/plan?${q({ name: n.hub_name })}`)).asks || asks; } catch { /* the first card still works */ }
      }
      asks.forEach((a) => items.push({ project: n.project, rank: askRank(a), kind: "hub-ask", ask: a, need: n, more: full ? 0 : n.asks - 1 }));
    } else items.push({ project: n.project, rank: n.rank, kind: n.kind, need: n });
  }
  return items;
}

// One card, answered in place. done() runs after an answer (the page refreshes itself).
export function needCard(it, done, opts = {}) {
  const name = projectName(it.project);
  // the harness's own cards (a fix to itself) belong to no project
  const proj = opts.showProject === false || !it.project ? null : h("a", { href: projectHref(it.project), title: "Open this project" }, dot(it.project), name);
  const more = it.more > 0 ? h("a", { class: "btn small", href: "#/needs", title: "See every card waiting for you" }, `${it.more} more here`) : null;
  if (it.kind === "local-ask") {
    const a = it.ask;
    const skippable = !["approve", "money", "failed", "command"].includes(a.kind);
    return askCard(a, async (ans) => {
      const r = await answerHere(a, ans);
      if (r.job) toast("Working on it: watch it on the project's page");
      await after(done);
    }, { compact: opts.compact, project: proj, disabled: it.busy, extra: [more,
      a.link ? h("a", { class: "btn small", href: a.link, target: "_blank", rel: "noopener", title: "Opens the draft pull request on GitHub" }, "Look at it") : null,
      it.busy ? h("span", { class: "muted small" }, "It's working on this project now; answer when it stops.") : null],
      onSkip: skippable ? async () => { try { await skipHere(a); } catch (e) { toast(e.message, true); } await after(done); } : null });
  }
  if (it.kind === "hub-ask") {
    return askCard(it.ask, async (ans) => { await answerHub(it.need, it.ask, ans); await after(done); },
      { compact: opts.compact, project: proj, extra: [more, h("a", { class: "btn small", href: projectHref(it.project, "plan") }, "Read the plan"),
        h("span", { class: "muted small", title: "Your answer goes to the computer that builds it, through the hub" }, "Runs on another computer")] });
  }
  const n = it.need;
  const box = (chip, text, ...acts) => h("article", { class: "need-card" + (opts.compact ? " compact" : "") },
    h("div", { class: "ask-head" }, h("span", { class: "chip" }, chip), proj, n.at ? h("span", { class: "muted small" }, ago(n.at)) : null),
    h("p", { class: "need-text" }, text), h("div", { class: "row" }, acts));
  if (it.kind === "plan") {
    return box("Plan", "The plan is ready. Read it, then approve it to start building.",
      h("button", { class: "primary", title: "Sends your approval to the computer that builds it; it starts there", onclick: (ev) =>
        act(ev.currentTarget, () => hubCommand(n, "approve"), null, () => after(done)) }, "Approve and start"),
      h("a", { class: "btn", href: projectHref(it.project, "plan") }, "Read the plan first"));
  }
  if (it.kind === "run") return box(n.actions.includes("budget") ? "Money" : "Stopped", sentence(n.text), runButtons(n, () => after(done)));
  if (it.kind === "todo") {
    return box("To-do", n.text,
      h("button", { class: "primary", title: "Done: it comes off the list", onclick: (ev) => act(ev.currentTarget,
        () => post(`/api/journal/${encodeURIComponent(n.agent || n.project)}/${encodeURIComponent(n.id)}/close`, {}), "Done: off your list", () => after(done)) }, "Done"),
      h("button", { title: "Take it off the list without doing it", onclick: (ev) => act(ev.currentTarget,
        () => post(`/api/journal/${encodeURIComponent(n.agent || n.project)}/${encodeURIComponent(n.id)}/close`, { dropped: true }), "Taken off your list", () => after(done)) }, "Not needed"));
  }
  if (it.kind === "messages") return lettersCard(n, done, opts, proj);
  return box("Waiting", n.text);
}
const sentence = (t) => { const s = String(t || "").trim(); return s ? s[0].toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? "" : ".") : ""; };

// the buttons that move a project on this computer along
export function runButtons(n, done) {
  const path = n.path, t = n.task || n.failed_task;
  const go = (body) => post("/api/project", { path, ...body });
  const b = (label, tip, fn, ok, primary = true) => h("button", { class: primary ? "primary" : "", title: tip, onclick: (ev) => act(ev.currentTarget, fn, ok, done) }, label);
  return (n.actions || []).map((a) => {
    if (a === "approve") return b("Approve and start", "Building starts now, as the plan says", () => post("/api/plan", { path, action: "approve" }), "Approved: building has started");
    if (a === "retry") return b("Try it again", "The task is tried once more, then building carries on", async () => { await go({ action: "retry", task: t }); await go({ action: "run" }); }, "Trying again");
    if (a === "skip") return b("Carry on without it", "This task is left out and building carries on", async () => { await go({ action: "skip", task: t }); await go({ action: "run" }); }, "Left out: carrying on", false);
    if (a === "budget") return b("Raise the limit and carry on", "Doubles this project's spending limit and carries on", () => go({ action: "raise_budget" }), "Limit raised: carrying on");
    if (a === "resume") return b("Carry on", "Picks up where it stopped", () => go({ action: "run" }), "Carrying on");
    return null;
  });
}

// unread letters, read on the card; reply or mark them read
function lettersCard(n, done, opts, proj) {
  const box = h("article", { class: "need-card letters-card" + (opts.compact ? " compact" : "") },
    h("div", { class: "ask-head" }, h("span", { class: "chip" }, "Letters"), proj), h("p", { class: "muted small" }, "Loading…"));
  (async () => {
    let msgs = [];
    try { msgs = (await get(`/api/inbox/${encodeURIComponent(n.project)}`)).slice(-(opts.compact ? 2 : 8)).reverse(); } catch (e) { fill(box, h("p", {}, e.message)); return; }
    const { letterRow } = await import("./letters.js");
    fill(box, h("div", { class: "ask-head" }, h("span", { class: "chip" }, "Letters"), proj),
      msgs.length ? msgs.map((m) => letterRow(m, n.project, () => after(done), true)) : h("p", {}, "No unread letters now."),
      h("div", { class: "row" }, h("a", { class: "btn", href: "#/letters" }, "All letters"),
        msgs.length ? h("button", { onclick: (ev) => act(ev.currentTarget, () => post(`/api/inbox/${encodeURIComponent(n.project)}/read`, { ids: msgs.map((m) => m.id) }),
          "Marked as read", () => after(done)) }, "Mark all read") : null));
  })();
  return box;
}

export async function viewNeeds() {
  const list = h("div", { class: "needs-page" });
  const head = h("p", { class: "sub" });
  let loading = false, again = false;
  const draw = async () => {
    if (loading) { again = true; return; }
    loading = true;
    try {
      const rt = S.rt;
      const items = await gather(rt);
      const groups = new Map();
      for (const it of items) { if (!groups.has(it.project)) groups.set(it.project, []); groups.get(it.project).push(it); }
      const ordered = [...groups.entries()].sort((a, b) => Math.min(...a[1].map((x) => x.rank)) - Math.min(...b[1].map((x) => x.rank)));
      head.textContent = items.length ? `${plural(items.length, "thing")} waiting, across ${plural(ordered.length, "project")}. Answer here: nothing is sent until you tap.`
        : "";
      patch(list, JSON.stringify(items.map((i) => [i.project, i.kind, i.ask && [i.ask.id, i.ask.stamp, i.busy], i.need && [i.need.text, i.need.id, i.need.actions]])), () =>
        items.length ? ordered.map(([pid, its]) => {
          its.sort((a, b) => a.rank - b.rank);
          const counts = {};
          its.forEach((i) => { const k = i.kind === "todo" ? "to-do" : i.kind === "messages" ? "letters" : i.rank === 1 ? "stop" : "question"; counts[k] = (counts[k] || 0) + 1; });
          const summary = Object.entries(counts).map(([k, c]) => k === "letters" ? "unread letters" : plural(c, k === "stop" ? "money or stopped task" : k)).join(", ");
          return h("section", { class: "need-group", id: `need-${pid}` },
            h("header", { class: "need-group-head" }, h("h2", {}, h("a", { href: projectHref(pid) }, dot(pid), projectName(pid)), h("span", { class: "count" }, its.length)),
              h("span", { class: "muted" }, summary)),
            [0, 1, 2, 3].map((r) => {
              const these = its.filter((i) => i.rank === r);
              return these.length ? h("div", { class: "need-rank" }, h("h3", { class: "label" }, RANK_WORDS[r]), these.map((i) => needCard(i, draw, { showProject: false }))) : null;
            }));
        }) : empty("Nothing is waiting for you. When a project has a question, a plan to approve or a to-do for you, it shows up here.",
          h("a", { class: "btn primary", href: "#/new" }, "+ Start a new project")));
    } finally {
      loading = false;
      if (again) { again = false; draw(); }
    }
  };
  const root = page("Needs you", null, head, list);
  onHall(root, () => draw());
  return root;
}
