// Activity: the minutes of every project in plain words, and the work the app is doing in the background.
import { h, fill, get, S, every, patch, projectName, projectHref, jobName, modelName, clock, ago, page, tabs, empty, card, dot, jobPill, seatByPath, prose, readable } from "./core.js";

const TOOL_WORDS = { write_file: "Wrote", edit_file: "Changed", read_file: "Read", run_command: "Ran", list_files: "Looked through",
  search: "Searched for", finish_task: "Finished", submit_review: "Review:", web_search: "Searched the web for",
  web_read: "Read a page:" };
const JOURNAL = { todo: "To-do", done: "Done", plan: "Plan", decision: "Decided", note: "Note", session: "Session" };

// one step of the minutes as the owner reads it: [who, what, tone]
export function feedWords(f) {
  const t = String(f.text || "");
  const who = [f.task, f.role ? jobName(f.role) : "", f.model ? modelName(f.model, true) : ""].filter(Boolean).join(" · ");
  switch (f.kind) {
    case "task_start": { const m = t.match(/^\[([^\]]+)\]\s*(.*?)\s*(?:\(([^)]*)\))?$/); return [who, `Started: ${m ? m[2] : t}`, ""]; }
    case "attempt": { const m = t.match(/attempt (\d+)/); return [who, `Try ${m ? m[1] : ""} with ${modelName(f.model)}`.replace("Try  ", "Try "), ""]; }
    case "tool_call": {
      const [tool, ...rest] = t.split(" ");
      if (tool === "submit_review") return [who, rest.join(" ").startsWith("approved") ? "Approved the work" : "Sent the work back", rest.join(" ").startsWith("approved") ? "ok" : "no"];
      const failed = t.endsWith("(failed)");
      return [who, `${TOOL_WORDS[tool] || readable(tool)} ${rest.join(" ").replace(/\s*\(failed\)$/, "")}`.trim() + (failed ? " – it didn't work" : ""), failed ? "no" : ""];
    }
    case "review": { const ok = /approved/i.test(t) && !/REJECTED/.test(t); return [who || "Reviewer", (ok ? "Approved: " : "Sent back: ") + t.replace(/^review:\s*(approved|REJECTED)\s*-\s*/i, ""), ok ? "ok" : "no"]; }
    case "task_end": { const ok = /\]\s*done:/.test(t); return [who, (ok ? "Finished: " : "Didn't work: ") + t.replace(/^\[[^\]]+\]\s*\w+:\s*/, ""), ok ? "ok" : "no"]; }
    case "plan": return [who || "Planner", "Made the plan", "ok"];
    case "planning": return ["Planner", `Making the plan with ${modelName(f.model)}`, ""];
    case "status": { const m = t.match(/status:\s*(\w+)/); return ["", `Now: ${m ? statusWords(m[1]) : t}`, ""]; }
    case "steer": return ["You", `Instruction: ${t.replace(/^owner instruction:\s*/, "")}`, "wn"];
    case "goal": return ["You", `New goal: ${t.replace(/^new goal:\s*/, "")}`, ""];
    case "provider_error": return [who, `A model didn't answer: ${t.replace(/^provider error \([^)]*\):\s*/, "")}`, "no"];
    case "backup": return ["Backups", t, ""];
    default:
      if (String(f.kind).startsWith("journal:")) {
        const k = f.kind.slice(8), text = t.replace(/^\[[^\]]+\]\s*/, "").replace(/^goal:\s*/i, "Goal: ").replace(/^harness /, "Roundtable ");
        return [JOURNAL[k] || readable(k), text ? text[0].toUpperCase() + text.slice(1) : text, k === "done" ? "ok" : ""];
      }
      return [who, t, ""];
  }
}
const statusWords = (s) => ({ done: "finished", running: "building", awaiting_approval: "the plan waits for you", blocked: "stopped, a task needs you",
  paused_budget: "stopped at the spending limit", paused: "paused", planning: "making the plan" }[s] || readable(s).toLowerCase());

export function feedLine(f, withProject = true) {
  const [who, what, tone] = feedWords(f);
  return h("li", { class: "feed-line " + tone },
    h("time", { datetime: f.at, title: f.at ? new Date(f.at).toLocaleString() : "" }, clock(f.at)),
    withProject ? (f.project === "backups" ? h("span", { class: "p" }, "Backups") : h("a", { class: "p", href: projectHref(f.project) }, dot(f.project), projectName(f.project))) : null,
    who ? h("span", { class: "w" }, who) : null,
    h("span", { class: "a", title: what }, what));
}

export async function viewActivity(tab = "minutes", jobId) {
  if (tab === "work" && jobId) return viewJob(jobId);
  const t = tabs([["minutes", "Minutes", "Every step on every project, newest first"], ["work", "Background work", "What the app is doing right now, and lately"]],
    tab, (k) => `#/activity${k === "minutes" ? "" : "/" + k}`);
  return page("Activity", tab === "work" ? "Work this app started (building, checks, backups, updates), with what each one did. The list starts again when the app restarts."
    : "What every project did, in order, newest first.", t, tab === "work" ? jobsList() : minutes());
}

function minutes() {
  let only = "";
  const pick = h("select", { "aria-label": "Show one project", title: "Show one project only", onchange: (ev) => { only = ev.target.value; list._sig = undefined; refresh(); } });
  const list = h("ul", { class: "feed" });
  const box = card(h("div", { class: "card-head" }, h("h2", {}, "Minutes"), h("label", { class: "row small" }, "Show", pick)), list);
  let feed = [];
  const refresh = () => {
    const names = [...new Set(feed.map((f) => f.project))];
    if (pick.options.length !== names.length + 1) {
      fill(pick, h("option", { value: "" }, "Every project"), names.map((n) => h("option", { value: n, selected: n === only }, n === "backups" ? "Backups" : projectName(n))));
    }
    const shown = feed.filter((f) => !only || f.project === only);
    patch(list, JSON.stringify([only, shown.length, shown[0] && shown[0].at, shown[0] && shown[0].text]), () =>
      shown.length ? shown.map((f) => feedLine(f, !only)) : h("li", { class: "muted" }, "Nothing has happened yet. Start a project and its steps show up here."));
  };
  return every(box, async () => { feed = await get("/api/activity?limit=300"); refresh(); }, 5000);
}

const KIND_WORDS = { run: "Building", plan: "The plan", probe: "Health check", improve: "Learning", setup: "Set-up", update: "Update", backup: "Backup" };
export function jobTitle(j) {
  const s = j.target ? seatByPath(j.target) : null;
  const name = s ? s.name : "";
  const t = String(j.title || "");
  if (j.kind === "run") return t.startsWith("new project") ? `Starting ${name || readable(t.slice(12))}` : `Building ${name || readable(t.split(" ").slice(1).join(" "))}` + (t.includes("(") ? ` ${t.slice(t.indexOf("("))}` : "");
  if (j.kind === "plan") return t.startsWith("new looks") ? `New looks for ${name}` : `Updating the plan of ${name || "a project"}`;
  if (j.kind === "probe") return "Checking the models";
  if (j.kind === "update") return "Updating Roundtable Hold";
  if (j.kind === "setup") return "Connecting the hub";
  if (j.kind === "backup") return t.startsWith("restore") ? "Restoring a backup" : "Backing up";
  if (j.kind === "improve") return t.startsWith("analyze") ? "Looking for improvements" : t.startsWith("replay") ? "Testing a suggestion" : t.startsWith("apply") ? "Using a suggestion" : readable(t);
  return t[0] ? t[0].toUpperCase() + t.slice(1) : "Work";
}

function jobsList() {
  const box = h("div");
  return every(box, async () => {
    const jobs = await get("/api/jobs");
    patch(box, JSON.stringify(jobs.map((j) => [j.id, j.status, j.ended])), () => jobs.length ? card(null, h("ul", { class: "jobs" }, jobs.map((j) => {
      const s = j.target ? seatByPath(j.target) : null;
      return h("li", {}, h("a", { href: `#/activity/work/${j.id}` }, h("b", {}, jobTitle(j))), jobPill(j.status),
        h("span", { class: "muted small" }, `started ${ago(j.started)}`, j.ended ? ` · ended ${ago(j.ended)}` : ""),
        s ? h("a", { class: "small", href: projectHref(s.id, j.kind === "run" ? "watch" : "plan") }, "Open the project") : null,
        j.error ? h("div", { class: "err small" }, friendlyError(j.error)) : null);
    }))) : empty("Nothing is running, and nothing has run since the app started. Building, health checks, backups and updates show up here while they work.",
      h("a", { class: "btn", href: "#/projects" }, "Go to your projects")));
  }, () => 3000);
}
export const friendlyError = (e) => String(e || "").replace(/^[A-Z]\w*(Error|Exception): /, "").replace(/\s*\(https?:[^)]*\)/g, "").replace(/https?:\/\/\S+/g, "the web");

async function viewJob(id) {
  const log = h("pre", { class: "log", role: "log", "aria-live": "polite" });
  const head = h("div", { class: "row" });
  const result = h("div");
  let since = 0, lines = [];
  const steps = h("details", { open: true }, h("summary", {}, "What it did, step by step"), log);
  const root = page("Background work", null, h("a", { class: "back", href: "#/activity/work" }, "← All background work"), card(head, result, steps));
  return every(root, async () => {
    const j = await get(`/api/jobs/${encodeURIComponent(id)}?since=${since}`);
    lines = lines.concat(j.log); since = j.log_size;
    const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent = lines.join("\n") || "Starting…";
    if (stick) log.scrollTop = log.scrollHeight;
    const s = j.target ? seatByPath(j.target) : null;
    patch(head, JSON.stringify([j.status, j.title]), () => [h("h2", {}, jobTitle(j)), jobPill(j.status), h("span", { class: "muted small" }, `started ${ago(j.started)}`),
      s ? h("a", { class: "btn small", href: projectHref(s.id, j.kind === "run" ? "watch" : "plan") }, "Open the project") : null]);
    patch(result, JSON.stringify([j.status, j.error, j.result]), () => [
      j.error ? h("p", { class: "err" }, friendlyError(j.error)) : null,
      j.error && j.kind === "backup" ? h("a", { class: "btn small", href: "#/settings/backups" }, "Open the backup settings") : null,
      j.error && j.kind === "setup" ? h("a", { class: "btn small", href: "#/settings/hub" }, "Open the hub settings") : null,
      j.status === "done" && j.result ? resultWords(j.result) : null]);
    if (j.status !== "running") steps.open = false;  // finished: the result says it; the steps fold away
    return j.status === "running";  // finished: keep the page, stop asking
  }, 1500);
}
function resultWords(r) {
  if (typeof r !== "object" || Array.isArray(r)) return null;
  const parts = [];
  if (r.reply) parts.push(r.reply);
  if (r.message) parts.push(r.message);
  if (r.status) parts.push(`Now: ${statusWords(r.status)}.`);
  if (r.file) parts.push("The backup is saved.");
  if (r.version) parts.push("The change is in use.");
  if (r.verdict) parts.push(`The test says: ${r.verdict.toLowerCase()}.`);
  return parts.length ? prose(parts.join("\n")) : null;
}
