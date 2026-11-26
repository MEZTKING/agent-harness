// A project's page: its name, state and the one button that moves it on, then Overview, Plan, Watch, App, Journal
// and Settings. Works for projects on this computer, projects another computer builds (through the hub) and hub
// projects that keep only a journal.
import { h, fill, get, post, S, onHall, every, patch, refreshHall, seatOf, projectHref, projectName, money, ago, plural, page, tabs, card, empty,
  taskPill, jobName, modelName, act, toast, dialog, prose, picture, q, dot, projectState } from "./core.js";
import { needCard, runButtons } from "./needs.js";
import { hubCommand } from "./asks.js";
import { whereWords, loadMachines } from "./machines.js";
import { planTab } from "./plan.js";
import { watchTab, appTab } from "./watch.js";
import { journalTab, notesPage } from "./journal.js";

const TABS = [["overview", "Overview", "What waits for you, the tasks, the money and the planner"],
  ["plan", "Plan", "The plan: what it will build, its choices and its tasks"],
  ["watch", "Watch", "Every step the models take, as it happens"],
  ["app", "App", "The app itself, running, and pictures after each task"],
  ["journal", "Journal", "Notes, to-dos, plans and decisions about this project"],
  ["settings", "Settings", "How Roundtable works on this project"]];

export async function viewProject(id, tab = "overview") {
  await refreshHall();
  if (S.rt.notes && S.rt.notes.id === id) return notesPage(S.rt.notes);
  let seat = seatOf(id);
  if (!seat) return waitingFor(id);
  await loadMachines();
  const local = !!seat.path;
  const hubAgent = (S.ov.agents || []).some((a) => a.id === seat.id);
  const shown = TABS.filter(([k]) => k === "overview" || (k === "plan" && (local || seat.hub_name)) || (k === "watch" && (local || seat.hub_name))
    || (k === "app" && local) || (k === "journal" && (hubAgent || seat.brief)) || (k === "settings" && local));
  if (!shown.some(([k]) => k === tab)) tab = "overview";
  const head = h("header", { class: "project-head" });
  const drawHead = (s) => patch(head, JSON.stringify([s.state, s.status, s.actions, s.goal, s.where, s.waiting_for_you, s.spent_usd, s.progress]), () => {
    const goal = s.goal || s.description;
    return [
      h("a", { class: "back", href: "#/projects" }, "← Projects"),
      h("div", { class: "ph-top" },
        s.shot ? picture(s.shot.url, `${s.name}: the newest picture`, "ph-shot") : null,
        h("div", { class: "grow" },
          h("h1", {}, dot(s.id), s.name),
          h("p", { class: "ph-state" }, h("span", { class: "state " + s.status }, h("i", { class: "sdot" }), s.state || "No news yet"),
            h("span", { class: "muted" }, " · ", whereWords(s)), s.spent_usd ? h("span", { class: "muted", title: "Spent on this project so far" }, " · ", money(s.spent_usd), " spent") : null),
          goal ? h("p", { class: "ph-goal" }, goal) : null),
        h("div", { class: "ph-acts" }, moveOn(s)))];
  });
  drawHead(seat);
  const body = h("div", { class: "project-body" });
  const root = h("div", { class: "page project" }, head,
    tabs(shown.map(([k, label, tip]) => [k, label, tip, k === "watch" && seat.status === "running" ? h("i", { class: "cdl", title: "Working now" }) : null]), tab, (k) => projectHref(seat.id, k === "overview" ? "" : k)),
    body);
  onHall(root, (rt) => { const s = rt.seats.find((x) => x.id === id); if (s) { seat = s; drawHead(s); } });
  const views = { overview: overview, plan: planTab, watch: watchTab, app: appTab, journal: journalTab, settings: settingsTab };
  fill(body, await views[tab](seat, () => seatOf(id) || seat));
  return root;
}

async function waitingFor(id) {
  const box = page(projectName(id), null, h("a", { class: "back", href: "#/projects" }, "← Projects"),
    card("Getting it ready", h("p", {}, "This project isn't at the table yet. A new project appears within a few seconds while the planner starts."),
      h("div", { class: "row" }, h("a", { class: "btn", href: "#/projects" }, "Back to Projects"))));
  every(box, async () => { await refreshHall(); if (seatOf(id)) { window.dispatchEvent(new HashChangeEvent("hashchange")); return false; } }, 2500);
  return box;
}

// the one button (or two) that moves the project on
function moveOn(s) {
  if (s.path) {
    const out = runButtons({ path: s.path, actions: s.actions || [], task: s.failed_task }, () => refreshHall());
    if ((s.actions || []).includes("resume")) out.push(h("button", { title: "Builds just the next task, then stops so you can look",
      onclick: (ev) => act(ev.currentTarget, () => post("/api/project", { path: s.path, action: "run", max_tasks: 1 }), "Building the next task", () => refreshHall()) }, "Just the next task"));
    if (s.status === "running") out.push(h("a", { class: "btn primary", href: projectHref(s.id, "watch") }, h("i", { class: "cdl" }), "Watch it work"));
    if (["done", "idle"].includes(s.status) && !(s.actions || []).length) out.push(h("button", { class: s.status === "done" ? "primary" : "", title: "Give it a new goal: the planner adds tasks for it, then builds them",
      onclick: async (ev) => {
        const goal = await dialog({ title: "Add to this project", text: "What should it do next? The planner adds tasks for it, then builds them.", yes: "Add and build",
          input: { rows: 4, placeholder: "e.g. add a page with the opening hours" } });
        if (goal && goal.trim()) act(ev.currentTarget, () => post("/api/project", { path: s.path, action: "extend", goal: goal.trim() }), "Added: the planner is on it", () => { location.hash = projectHref(s.id, "watch"); });
      } }, "Add to it"));
    return out;
  }
  if (s.hub_name && s.status === "waiting") return [
    h("button", { class: "primary", title: "Sends your approval to the computer that builds it; it starts there", onclick: (ev) => act(ev.currentTarget, () => hubCommand(s, "approve")) }, "Approve and start"),
    h("a", { class: "btn", href: projectHref(s.id, "plan") }, "Read the plan")];
  if ((S.ov.agents || []).some((a) => a.id === s.id)) return [h("a", { class: "btn", href: `#/letters?to=${encodeURIComponent(s.id)}`, title: "Send a letter to the agent working on this project" }, "Write to it")];
  return [];
}

// ---------- Overview ----------
async function overview(seat, now) {
  const waits = h("div", { class: "stack" }), tasksBox = h("div"), money_ = h("div"), chat = h("div"), report = h("div"), brief = h("div");
  const grid = h("div", { class: "overview" },
    h("div", { class: "ov-main" }, waits, tasksBox, report, brief),
    h("div", { class: "ov-side" }, money_, chat));
  if (!seat.path) {  // another computer's project, or a hub project: what the hub knows
    const items = (S.rt.needs_you || []).filter((n) => n.project === seat.id);
    const { gather } = await import("./needs.js");
    const its = (await gather({ ...S.rt, needs_you: items }, true)).filter((i) => i.project === seat.id);
    fill(waits, its.length ? [h("h2", { class: "section-title" }, "Waiting for you"), its.map((i) => needCard(i, () => refreshHall(), { showProject: false }))] : null);
    fill(brief, briefCard(seat));
    fill(money_, seat.spent_usd || seat.detail ? card("Where it stands", seat.detail ? h("p", {}, seat.detail) : null, seat.spent_usd ? h("p", {}, `${money(seat.spent_usd)} spent so far`) : null) : null);
    return grid;
  }
  const path = seat.path, qp = q({ path });
  let lastSig = "";
  every(grid, async () => {
    const s = now();
    const [d, asks, plan] = await Promise.all([get(`/api/project?${qp}`), get(`/api/asks?${qp}`).catch(() => ({ asks: [] })), get(`/api/plan?${qp}`).catch(() => null)]);
    const sig = JSON.stringify([d.meta.status, d.meta.spent_usd, d.tasks.map((t) => [t.status, t.attempts.length]), (asks.asks || []).map((a) => a.stamp), d.summary.length]);
    if (sig === lastSig) return;
    lastSig = sig;
    const items = (asks.asks || []).map((a) => ({ project: seat.id, rank: a.kind === "money" || a.kind === "failed" ? 1 : 0, kind: "local-ask", ask: a, busy: a.busy }));
    items.sort((a, b) => a.rank - b.rank);
    patch(waits, JSON.stringify(items.map((i) => [i.ask.id, i.ask.stamp, i.busy])), () => items.length ? [h("h2", { class: "section-title" }, "Waiting for you"),
      items.map((i) => needCard(i, () => { lastSig = ""; }, { showProject: false }))] : null);
    fill(tasksBox, tasksCard(seat, d));
    fill(money_, moneyCard(d, plan));
    fill(report, d.summary ? card("The final report", prose(d.summary)) : null);
    if (!chat.firstChild) fill(chat, chatCard(seat));
  }, () => (now().status === "running" ? 3000 : 15000));
  return grid;
}

function tasksCard(seat, d) {
  const tasks = d.tasks;
  if (!tasks.length) return card("Tasks", h("p", { class: "muted" }, d.meta.status === "planning" ? "The planner is making the plan: the tasks appear here when it's done." : "No tasks yet: the planner makes them first."));
  const done = tasks.filter((t) => t.status === "done").length;
  const post_ = (body, ok) => (ev) => act(ev.currentTarget, () => post("/api/project", { path: seat.path, ...body }), ok, () => refreshHall());
  const busy = seat.status === "running";
  return card(h("div", { class: "card-head" }, h("h2", {}, "Tasks"), h("span", { class: "muted" }, `${done} of ${tasks.length} done`),
    h("a", { class: "spacer-left", href: projectHref(seat.id, "watch") }, "Watch the steps")),
  h("ol", { class: "tasks" }, tasks.map((t) => {
    const last = t.attempts[t.attempts.length - 1];
    const model = last ? last.model : "";
    const why = t.status === "failed" && last ? last.review || last.error || "" : "";
    return h("li", { class: "task " + t.status },
      h("div", { class: "task-top" }, h("b", {}, t.title), taskPill(t.status)),
      h("div", { class: "task-meta" }, jobName(t.role), model ? [" · ", h("span", { title: modelName(model) }, modelName(model, true))] : null,
        t.attempts.length > 1 ? ` · ${t.attempts.length} tries` : "", t.depends_on.length ? h("span", { title: "It waits for these tasks to finish first" }, ` · after ${t.depends_on.map((x) => titleOf(tasks, x)).join(", ")}`) : null),
      t.summary && t.status === "done" ? h("p", { class: "task-sum" }, t.summary.slice(0, 280)) : null,
      why ? h("p", { class: "task-why" }, "Why it stopped: ", why.slice(0, 300)) : null,
      busy ? null : h("div", { class: "row task-acts" },
        t.status === "failed" ? [h("button", { class: "small primary", title: "Try this task once more", onclick: post_({ action: "retry", task: t.id }, "It will be tried again: press Carry on to start") }, "Try again"),
          h("button", { class: "small", title: "Leave this task out", onclick: post_({ action: "skip", task: t.id }, "Left out") }, "Leave it out")] : null,
        t.status === "done" ? [h("button", { class: "small", title: "Tell Roundtable this was good work: it learns which models do well", onclick: post_({ action: "feedback", task: t.id, rating: "good" }, "Thanks: noted as good work") }, "Good work"),
          h("button", { class: "small", title: "Tell Roundtable what was wrong: it learns from it", onclick: async (ev) => {
            const note = await dialog({ title: "What wasn't right?", text: `About “${t.title}”. Roundtable uses this to choose better models next time.`, yes: "Send", input: { rows: 3, placeholder: "What was wrong?" } });
            if (note !== null) post_({ action: "feedback", task: t.id, rating: "bad", note })(ev);
          } }, "Not right"),
          h("button", { class: "small", title: "Do this task again from the start", onclick: post_({ action: "retry", task: t.id }, "It will be done again: press Carry on to start") }, "Do it again")] : null));
  })));
}
const titleOf = (tasks, id) => (tasks.find((t) => t.id === id) || {}).title || id;

function moneyCard(d, plan) {
  const spent = d.meta.spent_usd || 0;
  const est = plan && plan.doc && plan.doc.estimate ? plan.doc.estimate.cost_usd || 0 : 0;
  const unpriced = d.meta.unpriced_calls || 0;
  const pct = est ? Math.min(100, (100 * spent) / est) : 0;
  return card("Money", h("p", { class: "big" }, money(spent), h("span", { class: "muted" }, est ? ` of about ${money(est)}` : " spent")),
    est ? h("div", { class: "bar wide" + (spent > est * 1.2 ? " over" : ""), title: `${Math.round((100 * spent) / est)}% of the estimate` }, h("i", { style: `width:${pct}%` })) : null,
    spent > est * 1.2 && est ? h("p", { class: "warn small" }, "It has gone past the estimate. It stops at the project's limit and asks you before spending more.") : null,
    unpriced ? h("p", { class: "muted small", title: "Add their price in Settings → AI services so they count towards the limit" }, `${plural(unpriced, "call")} to models with no price yet aren't counted.`) : null,
    d.metrics.length ? h("details", {}, h("summary", {}, "Who did the work"), h("table", { class: "plain-table" },
      h("tr", {}, h("th", {}, "Job and model"), h("th", { class: "num" }, "Tries"), h("th", { class: "num" }, "Approved"), h("th", { class: "num" }, "Cost")),
      d.metrics.map((m) => { const [role, model] = m.key.split(" · "); return h("tr", {}, h("td", {}, jobName(role), h("div", { class: "muted small" }, modelName(model))),
        h("td", { class: "num" }, m.attempts), h("td", { class: "num" }, m.approved), h("td", { class: "num" }, money(m.cost))); }))) : null);
}

// talk to the planner: ask about the project, or give an instruction for the next tasks
let draft = "", steer = false;
function chatCard(seat) {
  const log = h("div", { class: "chat", role: "log", "aria-live": "polite" });
  let pending = null, history = [];
  const draw = () => {
    const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    fill(log, [...history.map((m) => msg(m)), pending ? [msg({ who: "owner", text: pending.text, steer: pending.steer }), h("div", { class: "msgl orc pending" }, h("small", {}, "Planner"), h("div", { class: "body" }, h("i", { class: "cdl" }), pending.steer ? "Noting it…" : "Thinking…"))] : null]);
    if (!history.length && !pending) fill(log, h("p", { class: "muted small" }, "Ask about this project (“what's left?”, “why did the logo task stop?”), or give an instruction for the next tasks (“use bigger buttons from now on”)."));
    if (atEnd) log.scrollTop = log.scrollHeight;
  };
  const msg = (m) => h("div", { class: "msgl " + (m.who === "owner" ? "you" : "orc") + (m.steer ? " steer" : "") },
    h("small", {}, m.who === "owner" ? (m.steer ? "You · instruction" : "You") : "Planner", m.at ? ` · ${ago(m.at)}` : ""), h("div", { class: "body" }, m.text),
    m.steer && m.who === "owner" ? h("div", { class: "steer-note" }, "The next tasks follow this") : null);
  const input = h("textarea", { rows: 2, class: "grow", "aria-label": "Your message", oninput: (ev) => { draft = ev.target.value; } });
  input.value = draft;
  const send = h("button", { class: "primary", type: "submit" }, "Send");
  const mode = h("div", { class: "seg", role: "group", "aria-label": "Kind of message" });
  const setMode = (v) => { steer = v; input.placeholder = v ? "An instruction for the next tasks" : "A question about this project";
    fill(mode, [[false, "Ask", "A question: the planner answers, nothing changes"], [true, "Instruct", "An instruction: the next tasks follow it"]].map(([k, t, tip]) =>
      h("button", { type: "button", class: k === v ? "on" : "", "aria-pressed": String(k === v), title: tip, onclick: () => setMode(k) }, t))); };
  setMode(steer);
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); } });
  const form = h("form", { class: "compose", onsubmit: async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text || pending) return;
    pending = { text, steer }; input.value = ""; draft = ""; send.disabled = true; draw();
    try { await post("/api/chat", { path: seat.path, message: text, steer }); if (steer) toast("Noted: the next tasks follow it"); }
    catch (e) { toast(e.message, true); input.value = text; draft = text; }
    pending = null; send.disabled = false;
    await load();
  } }, mode, h("div", { class: "row" }, input, send));
  const load = async () => { try { history = await get(`/api/chat?${q({ path: seat.path })}`); } catch { history = history || []; } draw(); };
  load();
  return card("Talk to the planner", log, form);
}

function briefCard(seat) {
  const b = seat.brief;
  if (!b) return null;
  const s = b.last_session;
  return card("Latest news",
    s ? h("div", { class: "session-note" }, h("p", {}, h("b", {}, "Last session "), h("span", { class: "muted small" }, ago(s.created_at))), h("p", {}, s.text),
      (s.next || []).length ? [h("p", { class: "muted small" }, "Next:"), h("ul", {}, s.next.map((n) => h("li", {}, n)))] : null) : null,
    (b.recent_done || []).length ? [h("h3", { class: "label" }, "Done lately"), h("ul", {}, b.recent_done.slice(-5).reverse().map((e) => h("li", {}, e.text, h("span", { class: "muted small" }, ` · ${ago(e.created_at)}`))))] : null,
    (b.open_plans || []).length ? [h("h3", { class: "label" }, "Plans"), h("ul", {}, b.open_plans.map((e) => h("li", {}, e.text)))] : null,
    !s && !(b.recent_done || []).length && !(b.open_plans || []).length ? h("p", { class: "muted" }, "No news yet. When a session works on this project, what it did shows up here.") : null,
    h("a", { href: projectHref(seat.id, "journal") }, "The whole journal"));
}

// ---------- Settings ----------
const ABOUT = { test: "The command that checks the app after each task. A task that breaks a check that passed before is sent back.",
  env: "Settings that command needs, one a line, like NAME=value. Never keys or passwords.", setup: "A command run once before the first task, to get the app ready.",
  timeout: "How long the check or set-up may take.", branch: "Where Roundtable's work goes in an existing app; never its main line.",
  rules_files: "The app's own rule files, which every model follows.", rules_budget: "At most this much of those rules goes to the models.",
  providers_allowed: "Only these AI services may see this project. None ticked: any of them.", profile: "Which set of models builds it: Budget, Balanced or Quality.",
  limits: "Money and effort limits for this project only. Empty: the app's own.", look: "Offer looks to choose from before building.",
  show_it: "Take pictures of the app's screens after each task.", notes: "Anything the planner should know about this project, in your own words." };
const LABELS = { test: ["Check command", "How the app is checked after each task"], env: ["Settings for the check", ""], setup: ["Set-up command", ""],
  timeout: ["Time allowed for the check (seconds)", ""], branch: ["Where the work goes", ""], rules_files: ["The app's own rules", ""],
  rules_budget: ["How much of those rules the models read (characters)", ""], providers_allowed: ["Only these AI services may see it", ""],
  profile: ["Set of models", ""], limits: ["Limits", ""], look: ["Choose a look first", ""], show_it: ["Pictures after each task", ""], notes: ["Notes for the planner", ""] };
const CHOICE_WORDS = { "": "The app's choice", auto: "When it makes sense", on: "Always", off: "Never" };
const LIMIT_WORDS = { max_real_usd_per_run: "Most it may spend in one go ($)", max_cost_usd: "Most it may spend in all ($)", max_attempts_per_task: "Tries per task", max_steps_per_task: "Steps per try" };
const GROUPS = [["What it costs and who builds it", ["profile", "limits", "providers_allowed"]], ["What you see", ["look", "show_it", "notes"]],
  ["How it's checked (for an existing app)", ["test", "setup", "env", "timeout", "branch", "rules_files", "rules_budget"]]];

async function settingsTab(seat) {
  if (!S.routing) { try { S.routing = await get("/api/routing"); } catch { /* the service names fall back to their ids */ } }
  const box = h("div", { class: "stack" });
  const load = async () => {
    let st;
    try { st = await get(`/api/project/settings?${q({ project: seat.path })}`); } catch (e) { fill(box, card("Settings", h("p", {}, e.message))); return; }
    const by = Object.fromEntries(st.settings.map((x) => [x.key, x]));
    const inputs = {};
    const field = (it) => {
      const [label] = LABELS[it.key] || [it.key];
      let el;
      if (it.type === "choice") {
        el = h("select", { title: ABOUT[it.key] || it.description }, it.choices.map((c) => h("option", { value: c, selected: c === (it.value ?? "") }, it.key === "profile" ? (c ? setWord(c) : "The app's choice") : CHOICE_WORDS[c] || c)));
      } else if (it.type === "number-map") {
        el = h("div", { class: "limits" }, (it.keys || Object.keys(LIMIT_WORDS)).map((k) => h("label", { class: "field small" }, h("span", { class: "label" }, LIMIT_WORDS[k] || k),
          h("input", { type: "number", step: "any", min: "0", "data-k": k, value: (it.value || {})[k] ?? "", placeholder: "default" }))));
      } else if (it.type === "map") {
        el = h("textarea", { rows: 2, title: ABOUT[it.key] || it.description, placeholder: "NAME=value, one a line" }, Object.entries(it.value || {}).map(([k, x]) => `${k}=${x}`).join("\n"));
      } else if (it.key === "notes") el = h("textarea", { rows: 3, title: ABOUT[it.key] || it.description }, it.value || "");
      else if (it.key === "providers_allowed") {
        const on = new Set(it.value || []);
        el = h("div", { class: "to-list" }, Object.entries((S.routing || {}).providers || {}).map(([pid, p]) =>
          h("label", { class: "check" }, h("input", { type: "checkbox", value: pid, checked: on.has(pid) }), p.name)));
      } else if (it.type === "lines") el = h("input", { title: ABOUT[it.key] || it.description, value: (it.value || []).join(", "), placeholder: "separate with commas" });
      else el = h("input", { title: ABOUT[it.key] || it.description, value: it.value ?? "", type: it.type === "int" ? "number" : "text" });
      inputs[it.key] = el;
      return h("div", { class: "setting" }, h("label", { class: "label", title: ABOUT[it.key] || it.description }, label,
        it.source !== "default" ? h("span", { class: "muted small", title: it.source === "roundtable.yaml" ? "From the app's own folder: the default for everyone who builds it" : "Set for this project" }, it.source === "roundtable.yaml" ? " · from the app" : " · set here") : null),
      el, h("p", { class: "muted small" }, ABOUT[it.key] || it.description));
    };
    const value = (it) => {
      const el = inputs[it.key];
      if (it.type === "number-map") { const out = {}; el.querySelectorAll("input").forEach((i) => { if (i.value !== "") out[i.dataset.k] = Number(i.value); }); return out; }
      if (it.type === "map") return el.value.replace(/\n/g, ",");
      if (it.key === "providers_allowed") return [...el.querySelectorAll("input:checked")].map((i) => i.value).join(", ");
      return el.value;
    };
    const shown = (it) => it.type === "number-map" ? Object.fromEntries(Object.entries(it.value || {})) : it.type === "map" ? Object.entries(it.value || {}).map(([k, x]) => `${k}=${x}`).join(",")
      : it.type === "lines" ? (it.value || []).join(", ") : String(it.value ?? "");
    const save = async (ev) => {
      const changes = {};
      for (const it of st.settings) {
        if (!inputs[it.key]) continue;
        const v = value(it);
        if (JSON.stringify(v) !== JSON.stringify(shown(it))) changes[it.key] = it.type === "number-map" && !Object.keys(v).length ? null : v;
      }
      if (!Object.keys(changes).length) return toast("Nothing changed");
      await act(ev.currentTarget, () => post("/api/project/settings", { project: seat.path, changes }), "Saved", load);
    };
    const never = ((S.rt.autopilot || {}).never || []).includes(seat.id);
    fill(box, (st.warnings || []).concat(st.errors || []).map((w) => h("p", { class: "warn" }, w)),
      GROUPS.map(([title, keys], i) => {
        const fields = keys.filter((k) => by[k]).map((k) => field(by[k]));
        const c = card(title, fields);
        return i === 2 ? h("details", { class: "card fold" }, h("summary", {}, title), fields) : c;
      }),
      card("Autopilot", h("label", { class: "check", title: "When on, every question on this project waits for you, even while autopilot is on" },
        h("input", { type: "checkbox", checked: never, onchange: (ev) => act(null, () => post("/api/autopilot", { action: "never", project: seat.id, never: ev.target.checked }),
          ev.target.checked ? "Autopilot leaves this project to you" : "Autopilot may answer here again", () => refreshHall()) }),
        "Never on autopilot: every question here waits for me")),
      h("div", { class: "row sticky-save" }, h("button", { class: "primary", onclick: save }, "Save"), h("span", { class: "muted small" }, "Leave a box empty to use the app's choice.")));
  };
  await load();
  return box;
}
const setWord = (s) => ({ budget: "Budget", balanced: "Balanced", quality: "Quality" }[s] || s);
