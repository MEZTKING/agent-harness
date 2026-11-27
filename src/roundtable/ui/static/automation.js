// Automations: work that starts by itself – at a time you pick, from GitHub issues with a label, or when a check
// fails on GitHub. A plain list (what, when, last run, next run, on/off, Run now, Edit) and an add form in plain words.
// The API: ui/automationapi.py. The "in 5 hours" / "2 minutes late" words follow DSH Mobile's AutomationPresentation.kt
// (MIT, Copyright (c) 2026 DSH Mobile contributors).
import { h, fill, get, post, act, ago, money, page, card, empty, seg, dialog } from "./core.js";

const DAYS = [["mon", "M", "Monday"], ["tue", "T", "Tuesday"], ["wed", "W", "Wednesday"], ["thu", "T", "Thursday"],
  ["fri", "F", "Friday"], ["sat", "S", "Saturday"], ["sun", "S", "Sunday"]];
const KINDS = [["schedule", "At a time", "Starts at the times you pick"],
  ["issues", "GitHub issues", "Open issues with a label you choose become work"],
  ["ci", "A failed check", "When a check fails on GitHub, a task to fix it is made"]];
const WHATS = [["idea", "Plan a new idea"], ["goal", "Plan a project's next goal"], ["health", "Check my models work"], ["backup", "Back up my settings"]];
const zone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; } };

// "in 5 hours", "due now", "2 minutes late"
export function inWords(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (isNaN(t)) return "";
  const s = (t - now) / 1000, a = Math.abs(s);
  if (a < 60) return "due now";
  const [n, unit] = a >= 86400 ? [a / 86400, "day"] : a >= 3600 ? [a / 3600, "hour"] : [a / 60, "minute"];
  const c = Math.max(1, s > 0 ? Math.ceil(n) : Math.floor(n));
  const w = `${c} ${unit}${c === 1 ? "" : "s"}`;
  return s > 0 ? `in ${w}` : `${w} late`;
}
const local = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };

let DATA = null;
export async function viewAutomations() {
  const box = h("div", {});
  const draw = (d) => { DATA = d; fill(box, body(d, draw)); };
  draw(await get("/api/automations"));
  return page("Automations", "Work that starts by itself. Building always waits for your OK, unless you let one start by itself within a limit.", box);
}

function body(d, draw) {
  const send = (b, btn) => act(btn, () => post("/api/automations", b), (r) => r.done, draw);
  const needsKey = !d.github.set && d.automations.some((a) => a.kind !== "schedule");
  return [
    d.message ? h("p", { class: "banner" }, d.message) : null,
    needsKey ? keyCard(send) : null,
    card("Your automations", d.automations.length ? h("ul", { class: "plain auto-list" }, d.automations.map((a) => row(a, d, send, draw)))
      : empty("None yet. Add one below: for example, plan the next goal of a project every weekday at 9:00.")),
    card("Add an automation", form(null, d, send)),
    d.github.set ? h("details", { class: "fold" }, h("summary", {}, "Your GitHub key"),
      h("p", { class: "small muted" }, `Roundtable reads GitHub with ${d.github.which}. It asks GitHub every few minutes; nothing on the internet can reach this computer.`),
      keyForm(send, "Change it")) : null,
  ];
}

function keyCard(send) {
  return card("Your GitHub key", h("p", {}, "To read issues and checks, Roundtable needs a GitHub key that can read those repositories (a fine-grained key with Issues and Actions: read)."),
    keyForm(send, "Save"));
}
function keyForm(send, label) {
  const f = h("input", { type: "password", autocomplete: "off", class: "grow", placeholder: "github_pat_…", "aria-label": "GitHub key",
    title: "Kept in this computer's own key store, never in a file Roundtable writes" });
  return h("div", { class: "row" }, f, h("button", { class: "primary", type: "button", onclick: (ev) => { const v = f.value; f.value = ""; send({ action: "github_key", key: v }, ev.currentTarget); } }, label));
}

function row(a, d, send, draw) {
  const last = a.last_run ? h("span", { class: a.last_ok === false ? "err" : "" }, `Last run ${ago(a.last_run)}: ${a.last_result}`) : h("span", { class: "muted" }, "Not run yet");
  const next = a.next_run ? h("span", { title: new Date(a.next_run).toLocaleString() }, `Next: ${local(a.next_run)} (${inWords(a.next_run)})`)
    : h("span", { class: "muted" }, a.on ? "No more runs" : "Off");
  const edit = h("div", { hidden: true });
  return h("li", { class: "auto" + (a.on ? "" : " off") },
    h("div", { class: "card-head" }, h("h3", {}, a.name),
      h("label", { class: "switch", title: a.on ? "On: it runs at its times. Click to turn it off." : "Off: it doesn't run. Click to turn it on." },
        h("input", { type: "checkbox", checked: a.on, onchange: (ev) => send({ action: ev.target.checked ? "on" : "off", id: a.id }, ev.target) }), a.on ? "On" : "Off")),
    h("p", {}, a.what, " ", h("span", { class: "muted" }, a.when_words + ".")),
    h("p", { class: "small" }, last, h("br"), next),
    (a.waiting || []).map((w) => h("div", { class: "waits row" }, h("span", { class: "grow" }, w.text),
      h("button", { class: "primary", type: "button", onclick: (ev) => send({ action: "start", id: a.id, key: w.key }, ev.currentTarget) }, "Start it"),
      h("button", { type: "button", onclick: (ev) => send({ action: "dismiss", id: a.id, key: w.key }, ev.currentTarget) }, "Not now"))),
    h("div", { class: "row" },
      h("button", { type: "button", title: "Do it now. Building still waits for your OK.", onclick: (ev) => send({ action: "run", id: a.id }, ev.currentTarget) }, "Run now"),
      a.editable ? h("button", { type: "button", onclick: () => { edit.hidden = !edit.hidden; if (!edit.firstChild) fill(edit, form(a, d, send)); } }, "Edit")
        : h("span", { class: "small muted", title: "Written in Roundtable's settings file (automation: list:)" }, "Set in Roundtable's settings")),
    edit,
    h("details", {}, h("summary", { class: "small" }, "More"),
      h("p", { class: "small" }, a.money, a.spent_usd ? ` Spent so far: ${money(a.spent_usd)}.` : ""),
      (a.made || []).length ? [h("h4", {}, "What it made"), h("ul", { class: "small" }, a.made.map((m) =>
        h("li", {}, h("time", { title: m.at }, ago(m.at)), " ", m.text, m.project ? ` (${m.project.split(/[\\/]/).pop()})` : "",
          m.link ? [" · ", h("a", { href: m.link, target: "_blank", rel: "noopener" }, "on GitHub")] : "")))] : null,
      a.editable ? h("button", { class: "danger small", type: "button", onclick: async (ev) => {
        if (await dialog({ title: "Remove this automation?", text: `“${a.name}” stops and is removed. What it already made stays.`, yes: "Remove", danger: true }))
          send({ action: "remove", id: a.id }, ev.currentTarget);
      } }, "Remove") : null));
}

// the add (or edit) form, in plain words with a schedule picker
function form(a, d, send) {
  const v = a ? JSON.parse(JSON.stringify(a)) : { kind: "schedule", do: { what: "goal" }, when: { kind: "weekly", days: ["mon", "tue", "wed", "thu", "fri"], time: "09:00" }, make: "idea", branch: "main" };
  let kind = v.kind;
  const parts = h("div", { class: "stack" });
  const text = (val, ph, label, rows) => { const el = h(rows ? "textarea" : "input", { class: "grow", rows: rows || null, placeholder: ph, "aria-label": label }); el.value = val || ""; return el; };
  const projects = (val) => { const s = h("select", { "aria-label": "Project" }, h("option", { value: "" }, "Pick a project…"), d.projects.map((p) => h("option", { value: p.path, selected: p.path === val }, p.name))); return s; };
  const name = text(v.name && a ? v.name : "", "A short name (optional)", "Name");
  // schedule
  const what = h("select", { "aria-label": "What it does" }, WHATS.map(([k, l]) => h("option", { value: k, selected: (v.do || {}).what === k }, l)));
  const goal = text((v.do || {}).text, "What to plan, in a sentence or two", "What to plan", 2);
  const sProject = projects((v.do || {}).project);
  const w = v.when || { kind: "weekly", days: ["mon", "tue", "wed", "thu", "fri"], time: "09:00" };
  const days = new Set(w.days || []);
  const pick = w.kind === "once" ? "once" : days.size === 7 ? "daily" : [...days].join() === "mon,tue,wed,thu,fri" ? "weekdays" : [...days].join() === "sat,sun" ? "weekends" : "some";
  let often = pick;
  const time = h("input", { type: "time", value: w.time || (w.at || "T09:00").split("T")[1], "aria-label": "Time", title: "This computer's time" });
  const day = h("input", { type: "date", value: (w.at || "").split("T")[0] || new Date().toISOString().slice(0, 10), "aria-label": "Day" });
  const dayBtns = h("div", { class: "seg", role: "group", "aria-label": "Days" }, DAYS.map(([k, l, full]) =>
    h("button", { type: "button", class: days.has(k) ? "on" : "", title: full, "aria-pressed": String(days.has(k)), onclick: (ev) => {
      if (days.has(k)) days.delete(k); else days.add(k);
      ev.currentTarget.classList.toggle("on", days.has(k)); ev.currentTarget.setAttribute("aria-pressed", String(days.has(k)));
    } }, l)));
  const showWhen = () => { dayBtns.hidden = often !== "some"; day.hidden = often !== "once"; };
  const oftenSeg = seg([["daily", "Every day"], ["weekdays", "Weekdays"], ["weekends", "Weekends"], ["some", "Some days"], ["once", "Once"]], often, (x) => { often = x; showWhen(); }, "How often");
  showWhen();
  // GitHub
  const repo = text(v.repo, "owner/name, for example acme/shop", "GitHub repository");
  const label = text(v.label || "roundtable", "the label", "Label");
  let make = v.make || "idea";
  const gProject = projects(v.project);
  const branch = text(v.branch || "main", "main", "Branch");
  // money
  const self = h("input", { type: "checkbox", checked: !!v.start_by_itself });
  const cap = h("input", { type: "number", min: "0.5", step: "0.5", value: Number(v.cap_usd || 2).toFixed(2), class: "ap-cap", "aria-label": "Spending limit in dollars",
    title: "The most it may spend by itself, in all. When it gets there it asks you first again." });
  const capRow = h("span", { class: "row" }, "up to $", cap, h("span", { class: "small muted" }, "in all, then it asks you again"));
  const showCap = () => { capRow.hidden = !self.checked; };
  self.addEventListener("change", showCap); showCap();

  const drawParts = () => {
    const goalPart = () => { goal.hidden = !["idea", "goal"].includes(what.value); sProject.hidden = what.value !== "goal"; };
    what.onchange = goalPart; goalPart();
    if (kind === "schedule") fill(parts, h("label", { class: "stack" }, h("span", { class: "label" }, "What it does"), what), goal, sProject,
      h("div", { class: "stack" }, h("span", { class: "label" }, "When"), oftenSeg, dayBtns, h("span", { class: "row" }, day, "at", time)));
    else fill(parts, h("label", { class: "stack" }, h("span", { class: "label" }, "Repository"), repo),
      kind === "issues" ? [h("label", { class: "stack" }, h("span", { class: "label", title: "Only open issues with this label are picked up" }, "Label"), label),
        h("div", { class: "stack" }, h("span", { class: "label" }, "Each issue becomes"),
          seg([["idea", "A new idea"], ["task", "A task on a project"]], make, (x) => { make = x; gProject.hidden = x !== "task"; }, "Each issue becomes"), gProject)]
        : [h("label", { class: "stack" }, h("span", { class: "label" }, "Branch"), branch), h("label", { class: "stack" }, h("span", { class: "label" }, "Fix tasks go to"), gProject)]);
    gProject.hidden = kind === "issues" && make !== "task";
  };
  drawParts();
  const collect = () => {
    const out = { kind, name: name.value, start_by_itself: self.checked, cap_usd: self.checked ? Number(cap.value) : 0 };
    if (kind === "schedule") {
      const set = { daily: DAYS.map((x) => x[0]), weekdays: ["mon", "tue", "wed", "thu", "fri"], weekends: ["sat", "sun"], some: [...days] }[often];
      const offset = -new Date().getTimezoneOffset();
      out.when = often === "once" ? { kind: "once", at: `${day.value}T${time.value}`, zone: zone(), offset_min: offset } : { kind: "weekly", days: set, time: time.value, zone: zone(), offset_min: offset };
      out.do = { what: what.value, text: goal.value, project: sProject.value };
    } else {
      Object.assign(out, { repo: repo.value, project: gProject.value });
      if (kind === "issues") Object.assign(out, { label: label.value, make }); else out.branch = branch.value;
    }
    return out;
  };
  return h("div", { class: "stack auto-form" },
    a ? null : seg(KINDS, kind, (x) => { kind = x; drawParts(); }, "What starts it"),
    parts,
    h("label", { class: "row", title: "Off: it plans, and building waits for your OK. On: it builds by itself while the plan's estimate fits what's left of the limit." },
      self, "Let it start building by itself"), capRow,
    h("label", { class: "stack" }, h("span", { class: "label" }, "Name"), name),
    h("div", { class: "row" }, h("button", { class: "primary", type: "button", onclick: (ev) =>
      send(a ? { action: "edit", id: a.id, changes: collect() } : { action: "add", automation: collect() }, ev.currentTarget) }, a ? "Save" : "Add")));
}

