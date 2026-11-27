// Watch and App: following the work like a session (every step, changes in colour, pictures) and the app itself.
// Several tasks run at once: the ones still going sit side by side at the top, each one line with where its time
// went and how full its context is; the details (the split in words, tokens, files changed) are folded.
import { h, fill, get, post, act, every, card, money, ago, clock, jobName, modelName, taskPill, picture, fileSize, q, refreshHall } from "./core.js";
import { hubSession } from "./machines.js";
import { hubCommand } from "./asks.js";

const rawUrl = (kind, path, name, task) => `/raw/${kind}?` + new URLSearchParams({ path, name, ...(task ? { task } : {}) });
const shotUrl = (path, rec, kind) => rawUrl("shot", path, (rec.pictures || {})[kind] || `${kind}.png`, rec.dir || rec.task);
const SHOT_NAMES = { desktop: "Computer", phone: "Phone", dark: "Dark", start: "Early on", middle: "Halfway" };

export async function watchTab(seat, now) {
  const term = h("div", { class: "term", role: "log", "aria-live": "polite" }, h("p", { class: "t-meta" }, "Loading…"));
  const outs = h("div");
  const nowBox = h("div");
  const details = h("div");
  const open = new Set();
  let cursor = 0, stick = true, held = [], runId = null;
  term.addEventListener("scroll", () => { stick = term.scrollHeight - term.scrollTop - term.clientHeight < 40; });
  term.addEventListener("load", () => { if (stick) term.scrollTop = term.scrollHeight; }, true);
  const status = h("span", { class: "muted small" });
  const box = h("div", { class: "watch" }, nowBox,
    h("section", { class: "card term-card" }, h("div", { class: "card-head" }, h("h2", {}, "The work, step by step"), status), term),
    outs, details);
  const path = seat.path;
  return every(box, async () => {
    const s = now();
    status.textContent = s.status === "running" ? "Following it live" : "";
    let d;
    if (path) d = await get(`/api/project/session?${q({ path, since: cursor })}`);
    else {
      d = await hubSession(s, "", held.length);
      if (!d) { fill(term, h("p", { class: "t-meta" }, "Another computer builds this project. Its steps show here when that computer shares them through the hub.")); return false; }
      if (d.run && d.run.run_id !== runId) { runId = d.run.run_id; held = []; if (d.run.since) d = await hubSession(s, runId, 0) || d; }
      held = held.concat(d.events || []);
      status.textContent = d.live ? `Following it live${d.claim && d.claim.machine_name ? ` on ${d.claim.machine_name}` : ""}` : d.run ? `The newest build, ${ago(d.run.ended || d.run.started)}` : "";
      fill(term, held.length ? remoteSteps(held) : h("p", { class: "t-meta" }, s.status === "done" ? "This project was built before Roundtable kept a step list."
        : d.message || "No build of this project has been watched yet: it shows here once one starts."));
      if (stick) term.scrollTop = term.scrollHeight;
      return;
    }
    if (d.changed === false) return;
    cursor = d.cursor || 0;
    fill(nowBox, s.status === "running" ? workingNow(d.tasks || [], d.running || []) : null);
    fill(outs, (d.outputs || []).length ? card("What it made", h("p", { class: "muted small" }, "Pictures and files the project made, newest first."), outputList(path, d.outputs)) : null);
    fill(term, (d.tasks || []).length ? d.tasks.map((t, i) => h("div", { class: "t-task" },
      h("div", { class: "t-head" }, h("span", { class: "t-prompt" }, "▶"), h("b", {}, t.title || t.id), h("span", { class: "t-meta" }, ` · ${jobName(t.role)}`),
        h("span", { class: "spacer" }), taskPill(t.status), t.cost ? h("span", { class: "t-cost", title: "What this task cost" }, money(t.cost)) : null),
      taskSummary(t, `${i}:sum`, open),
      t.steps.map((st, j) => stepNode(path, st, `${i}:${j}`, open)),
      changedFiles(t, `${i}:files`, open),
      t.outputs && t.outputs.length ? h("div", { class: "t-outs" }, outputList(path, t.outputs)) : null))
      : h("p", { class: "t-meta" }, "Nothing yet: the steps appear here as soon as the first task starts."));
    if (stick) term.scrollTop = term.scrollHeight;
    if (path && !details.firstChild) fill(details, await moreDetails(path));
  }, () => (now().status === "running" ? 2500 : 20000));
}

// ---------- where the time went, how full the context is, what changed ----------
watchStyles();
export function dur(ms) {
  const n = Math.max(0, Math.round(Number(ms) || 0));
  if (n < 1000) return "under a second";
  const sec = Math.round(n / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), hr = Math.floor(m / 60);
  return hr ? `${hr}h ${m % 60}m` : `${m}m ${sec % 60 ? `${sec % 60}s` : ""}`.trim();
}
const PART_TIP = {
  first: "Waiting for the model's first word after Roundtable sent it the work",
  writing: "The model writing its answer",
  model: "The model thinking and writing (this model doesn't say when its first word came)",
  tools: "Reading, writing and running things in the project",
  you: "Waiting for your answer to an Ask me first card",
  other: "Roundtable's own work between the steps: saving, checking, plugins",
};
// the bar: only time that was recorded; nothing recorded, no bar (never a bar of zeros)
export function timeBar(time) {
  if (!time || !(time.parts || []).length) return null;
  const total = time.total_ms || time.parts.reduce((a, p) => a + p.ms, 0);
  return h("span", { class: "tw-time", title: time.parts.map((p) => `${p.label}: ${dur(p.ms)}`).join("\n") + (time.unrecorded ? "\nSome earlier steps weren't timed." : "") },
    h("span", { class: "tw-bar", role: "img", "aria-label": "Where the time went: " + time.parts.map((p) => `${p.label} ${dur(p.ms)}`).join(", ") },
      time.parts.map((p) => h("span", { class: "tw-seg tw-" + p.key, style: `flex-grow:${Math.max(p.ms, total / 100)}` }))),
    h("span", { class: "tw-total" }, dur(total)));
}
const pct = (x) => `${Math.round(x * 100)}%`;
const tokens = (n) => (n >= 10000 ? `${Math.round(n / 1000)}k` : Number(n).toLocaleString("en-GB"));
// the gauge: tokens of the newest model call against the model's window (no window known: the tokens alone)
export function gauge(ctx) {
  if (!ctx) return null;
  const tip = ctx.share != null ? `The newest model call used ${Number(ctx.used).toLocaleString("en-GB")} of ${Number(ctx.window).toLocaleString("en-GB")} tokens it can hold.`
    : `The newest model call used ${Number(ctx.used).toLocaleString("en-GB")} tokens. How much this model can hold isn't known.`;
  const level = ctx.share == null ? "" : ctx.share >= 0.85 ? " full" : ctx.share >= 0.6 ? " high" : "";
  return h("span", { class: "tw-gauge" + level, title: tip + (ctx.cache_hit != null ? ` ${pct(ctx.cache_hit)} of what it read came from the cache (cheaper).` : "") },
    ctx.share != null ? h("span", { class: "tw-meter" }, h("span", { style: `width:${Math.max(2, ctx.share * 100)}%` })) : null,
    ctx.share != null ? `${pct(ctx.share)} full` : `${tokens(ctx.used)} tokens`);
}
function taskSummary(t, key, open) {
  const bar = timeBar(t.time), g = gauge(t.context);
  if (!bar && !g) return null;
  const rows = [
    ...(t.time ? t.time.parts.map((p) => h("li", {}, h("span", { class: "tw-key tw-" + p.key }), `${p.label}: ${dur(p.ms)}`)) : []),
    t.time && t.time.unrecorded ? h("li", { class: "t-meta" }, "Some earlier steps weren't timed, so they're left out.") : null,
    t.context ? h("li", {}, `Context: ${Number(t.context.used).toLocaleString("en-GB")} tokens` + (t.context.window ? ` of ${Number(t.context.window).toLocaleString("en-GB")}` : "") + ` (${modelName(t.context.model)})`) : null,
    t.context && t.context.cache_hit != null ? h("li", {}, `From the cache: ${pct(t.context.cache_hit)} of what the models read`) : null,
  ];
  const det = h("details", { class: "tw-sum", open: open.has(key) }, h("summary", { title: "Where this task's time went – click for the details" }, bar, g), h("ul", { class: "tw-list" }, rows));
  det.addEventListener("toggle", () => (det.open ? open.add(key) : open.delete(key)));
  return det;
}
function changedFiles(t, key, open) {
  const list = t.changes || [];
  if (!list.length) return null;
  const add = list.reduce((a, c) => a + c.added, 0), del = list.reduce((a, c) => a + c.removed, 0);
  const det = h("details", { class: "t-tool tw-files", open: open.has(key) },
    h("summary", { title: "The files this task changed" }, h("span", { class: "t-dot" }, "●"), h("b", {}, `Changed ${list.length} file${list.length > 1 ? "s" : ""}`),
      h("span", { class: "t-detail" }, ` · +${add} −${del}`)),
    h("ul", { class: "tw-list" }, list.map((c) => h("li", {}, c.path, h("span", { class: "t-detail" }, ` ${c.new ? "new · " : ""}+${c.added} −${c.removed}`)))));
  det.addEventListener("toggle", () => (det.open ? open.add(key) : open.delete(key)));
  return det;
}
// the tasks still going, side by side: one row each
export function workingNow(tasks, running) {
  const last = new Map(tasks.map((t) => [t.id, t]));
  const live = (running || []).map((id) => last.get(id)).filter(Boolean);
  if (!live.length) return null;
  return h("section", { class: "card tw-now" }, h("div", { class: "card-head" }, h("h2", {}, live.length > 1 ? `Working on ${live.length} tasks at once` : "Working on")),
    h("div", { class: "tw-rows" }, live.map((t) => h("div", { class: "tw-row" },
      h("div", { class: "tw-title" }, h("b", {}, t.title || t.id), h("span", { class: "muted small" }, ` ${t.id} · ${jobName(t.role)}`), h("span", { class: "spacer" }), taskPill(t.status)),
      h("div", { class: "tw-doing muted small", title: t.now || "" }, t.now || "Starting"),
      h("div", { class: "tw-line" }, timeBar(t.time) || h("span", { class: "muted small" }, "No times yet"), gauge(t.context))))));
}
function watchStyles() {
  if (typeof document === "undefined" || document.getElementById("tw-style")) return;
  document.head.append(h("style", { id: "tw-style" }, `
.tw-now .tw-rows { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
.tw-row { border: 1px solid var(--color-oak-line); border-radius: var(--radius-small); padding: 10px 12px; background: var(--color-sunken); min-width: 0; }
.tw-title { display: flex; align-items: baseline; gap: 6px; } .tw-title .spacer { flex: 1; } .tw-title b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tw-doing { margin: 4px 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tw-line, .tw-sum > summary { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.tw-sum { margin: 2px 0 8px 18px; } .tw-sum > summary { list-style: none; cursor: pointer; } .tw-sum > summary::-webkit-details-marker { display: none; }
.tw-time { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; }
.tw-bar { display: inline-flex; width: 180px; height: 8px; border-radius: 4px; overflow: hidden; background: color-mix(in srgb, currentColor 15%, transparent); gap: 1px; }
.tw-seg { display: block; height: 100%; flex-basis: 0; }
.tw-first { background: #9c8b74; } .tw-writing, .tw-model { background: #e8a33d; } .tw-tools { background: #7fa35c; } .tw-you { background: #d0643f; } .tw-other { background: #6f5a46; }
.tw-gauge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.tw-meter { display: inline-block; width: 56px; height: 6px; border-radius: 3px; background: color-mix(in srgb, currentColor 18%, transparent); overflow: hidden; }
.tw-meter > span { display: block; height: 100%; background: #7fa35c; } .tw-gauge.high .tw-meter > span { background: #e8a33d; } .tw-gauge.full .tw-meter > span { background: #d0643f; }
.tw-list { margin: 6px 0 4px; padding-left: 18px; font-size: 12px; list-style: none; } .tw-list li { margin: 2px 0; }
.tw-key { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
`));
}

// a build on another machine, line by line as it shares them (sync.py's session lines)
const REMOTE_CLASS = { review: (e) => "t-review " + (e.approved ? "ok" : "no"), error: () => "t-review no", change: () => "t-tool", tool: (e) => "t-tool" + (e.error ? " bad" : ""),
  turn: () => "t-say", cost: () => "t-meta", note: () => "t-meta", status: () => "t-meta", run_started: () => "t-meta", run_done: () => "t-meta", shots: () => "t-meta", task_done: () => "t-meta" };
function remoteSteps(events) {
  const out = [], byTask = new Map();  // several tasks at once: a line carrying a task id goes to that task
  let box = null;
  for (const e of events) {
    if (e.kind === "task_started") {
      box = h("div", { class: "t-task" }, h("div", { class: "t-head" }, h("span", { class: "t-prompt" }, "▶"), h("b", {}, e.title || e.task || "A task"),
        e.role ? h("span", { class: "t-meta" }, ` · ${jobName(e.role)}`) : null, e.index && e.total ? h("span", { class: "t-meta" }, ` · ${e.index} of ${e.total}`) : null));
      out.push(box);
      if (e.task) byTask.set(e.task, box);
      continue;
    }
    if (e.kind === "cost") continue;  // shown with the turn it paid for
    const line = e.kind === "turn" && e.model && /^Attempt \d+ on /.test(e.line) ? `Working with ${modelName(e.model)}` : e.line;
    const el = h("div", { class: "t-line " + (REMOTE_CLASS[e.kind] || (() => "t-meta"))(e) }, h("span", {}, line), e.at ? h("span", { class: "t-cost" }, clock(e.at)) : null);
    const into = (e.task && byTask.get(e.task)) || box || (box = (out.push(h("div", { class: "t-task" })), out[out.length - 1]));
    into.append(el);
  }
  return out;
}

function stepNode(path, s, key, open) {
  const cost = s.cost ? h("span", { class: "t-cost", title: "What this model turn cost" }, money(s.cost)) : null;
  if (s.kind === "say") return h("div", { class: "t-say" + (s.who === "reviewer" ? " rev" : "") }, h("span", { class: "t-dot" }, "⏺"),
    h("div", {}, s.who === "reviewer" ? h("b", {}, "Reviewer  ") : null, s.text), cost);
  if (s.kind === "attempt") { const n = (String(s.text).match(/Attempt (\d+)/) || [])[1]; return h("div", { class: "t-meta" }, n && n !== "1" ? `Try ${n}, with ${modelName(s.model)}` : `Working with ${modelName(s.model)}`); }
  if (s.kind === "review") return h("div", { class: "t-review " + (s.approved ? "ok" : "no") }, s.approved ? "✓ Approved" : "✗ Sent back", h("span", {}, "  " + (s.text || "")));
  if (s.kind === "finish") return h("div", { class: "t-meta" }, "✓ Finished: ", s.text);
  if (s.kind === "error") return h("div", { class: "t-review no" }, "! A model didn't answer: ", String(s.text).replace(/^[^:]+\/[^:]+:\s*/, ""));
  if (s.kind === "shots") {
    const rec = { dir: s.dir || s.task, task: s.task, pictures: {} };
    return h("div", { class: "t-shots" }, h("div", { class: "t-meta" }, s.pictures.length ? `Pictures of the app${s.errors ? ` · the page reported ${s.errors} error${s.errors > 1 ? "s" : ""}` : ""}` : `No pictures: ${s.note}`),
      s.pictures.length && path ? h("div", { class: "strip" }, s.pictures.map((k) => picture(shotUrl(path, rec, k), `${SHOT_NAMES[k] || k} · after this task`))) : null);
  }
  const body = s.diff ? diffView(s.diff) : s.output ? h("pre", { class: "t-out" }, s.output) : null;
  const line = [h("span", { class: "t-dot" + (s.error ? " bad" : "") }, "●"), h("b", {}, s.label), s.detail ? h("span", { class: "t-detail" + (s.error ? " bad" : "") }, " · " + s.detail) : null, cost];
  if (!body) return h("div", { class: "t-tool" }, line);
  const det = h("details", { class: "t-tool", open: open.has(key) }, h("summary", { title: "Show what it did" }, line), body);
  det.addEventListener("toggle", () => (det.open ? open.add(key) : open.delete(key)));
  return det;
}
function diffView(text) {
  return h("pre", { class: "diff" }, String(text || "").split("\n").map((ln) => h("span", { class:
    ln.startsWith("+++") || ln.startsWith("---") ? "dh" : ln.startsWith("@@") ? "dk" : ln.startsWith("+") ? "da" : ln.startsWith("-") ? "dd" : "" }, ln + "\n")));
}
function outputList(path, outs) {
  if (!path) return null;
  const pics = outs.filter((o) => o.kind === "image"), files = outs.filter((o) => o.kind !== "image");
  return [pics.length ? h("div", { class: "strip outs" }, pics.slice(0, 24).map((o) => h("figure", {}, picture(rawUrl("file", path, o.path), o.path), h("figcaption", {}, o.path.split("/").pop())))) : null,
    files.length ? h("ul", { class: "files" }, files.map((o) => h("li", {}, h("a", { href: rawUrl("file", path, o.path), download: o.path.split("/").pop(), title: "Save this file" }, "⤓ ", o.path),
      h("span", { class: "muted small" }, ` ${fileSize(o.size)}`)))) : null];
}
async function moreDetails(path) {
  let d;
  try { d = await get(`/api/project?${q({ path })}`); } catch { return null; }
  return h("details", { class: "card fold" }, h("summary", { title: "The full record, for when you want every detail" }, "Every detail"),
    h("h3", {}, "The full log"), h("pre", { class: "log" }, d.events.map((e) => `${(e.at || "").slice(11, 16)}  ${e.text}`).join("\n") || "Empty"),
    h("h3", {}, `Its files (${d.files.length})`), h("pre", { class: "log short" }, d.files.join("\n") || "None yet"));
}

// ---------- App: the real app running, and its pictures ----------
export async function appTab(seat, now) {
  if (!seat.path) return hubApp(seat, now);
  const box = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
  let sig = "";
  return every(box, async () => {
    const s = now();
    const L = await get(`/api/project/live?${q({ path: seat.path })}`);
    const sg = JSON.stringify([L.latest && L.latest.at, L.history.length, L.preview, L.entry, s.status]);
    if (sg !== sig) { sig = sg; fill(box, liveApp(L), livePictures(seat.path, L, s.status === "done", seat)); }
  }, () => (now().status === "running" ? 4000 : 15000));
}

// "Take pictures now": for a finished project built before Roundtable took pictures
function takeButton(fn) {
  return h("div", { class: "row" }, h("button", { class: "primary", title: "Opens the app as it is now and takes its pictures (no AI, no cost)",
    onclick: (ev) => act(ev.currentTarget, fn, "Taking the pictures: they show here in a minute", () => refreshHall()) }, "Take pictures now"));
}

// a project another computer builds: the pictures and steps it published to the hub
async function hubApp(seat, now) {
  const box = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
  let sig = "";
  return every(box, async () => {
    const s = now();
    const L = await get(`/api/hub/live?${q({ name: seat.hub_name })}`);
    const sg = JSON.stringify([L.latest && L.latest.at, Object.keys(L.pictures), s.status]);
    if (sg === sig) return;
    sig = sg;
    const kinds = Object.keys(L.pictures || {}), rec = L.latest || {}, finished = s.status === "done";
    fill(box, card(h("div", { class: "card-head" }, h("h2", {}, finished && kinds.length ? "Final pictures" : "Pictures"),
      rec.at && kinds.length ? h("span", { class: "muted small" }, finished ? day(rec.at) : ago(rec.at)) : null),
    kinds.length ? h("div", { class: "shots" }, kinds.map((k) => h("figure", { class: "shot " + k }, picture(L.pictures[k], SHOT_NAMES[k] || k), h("figcaption", {}, SHOT_NAMES[k] || k))))
      : [h("p", { class: "muted" }, finished ? "No pictures of this project yet." : "The computer that builds it takes pictures after every finished task. None yet."),
        finished ? takeButton(() => hubCommand(s, "show_it")) : null]));
  }, () => (now().status === "running" ? 6000 : 30000));
}
const day = (iso) => { try { return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); } catch { return String(iso).slice(0, 10); } };
function liveApp(L) {
  if (!L.preview) {
    return card("The app", h("p", { class: "muted" }, L.entry ? "The app opens here in the Roundtable Hold desktop app." : "Nothing to open yet: the app's first page hasn't been made."),
      L.start_command ? h("p", { class: "small muted" }, "It has its own way of starting: Roundtable shows its page as it is for now.") : null);
  }
  const frame = h("iframe", { class: "live-frame", src: L.preview, title: "The app, live", sandbox: "allow-scripts allow-same-origin allow-forms" });
  const wrap = h("div", { class: "live-wrap" }, frame);
  const size = (phone) => { wrap.classList.toggle("phone", phone); sizes.querySelectorAll("button").forEach((b) => { const on = (b.dataset.k === "phone") === phone; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }); };
  const sizes = h("div", { class: "seg", role: "group", "aria-label": "Screen size" },
    h("button", { type: "button", class: "on", "aria-pressed": "true", "data-k": "desktop", title: "As wide as this window", onclick: () => size(false) }, "Computer"),
    h("button", { type: "button", "aria-pressed": "false", "data-k": "phone", title: "As wide as a phone", onclick: () => size(true) }, "Phone"));
  return card(h("div", { class: "card-head" }, h("h2", {}, "The app, live"),
    h("div", { class: "row" }, sizes,
      h("button", { class: "small", title: "Load the app again (after a task changed it)", onclick: () => { frame.src = L.preview; } }, "Reload"),
      h("a", { class: "btn small", href: L.preview, target: "_blank", rel: "noopener", title: "Open the app in its own window" }, "Open in a window"))),
  h("p", { class: "small muted" }, "The real app, running from its folder. It can't reach the internet or Roundtable itself."),
  wrap);
}
function livePictures(path, L, finished = false, seat = null) {
  const rec = L.latest;
  if (!rec && finished) return card("Pictures", h("p", { class: "muted" }, "No pictures of this project yet."),
    takeButton(() => post("/api/project", { path, action: "show_it" })));
  if (!rec) return card("Pictures", h("p", { class: "muted" }, "Roundtable takes pictures of the app after every finished task. None yet."));
  const kinds = Object.keys(rec.pictures || {}), errs = rec.errors || [];
  const earlier = (L.history || []).filter((r) => Object.keys(r.pictures || {}).length);
  return card(h("div", { class: "card-head" }, h("h2", {}, finished ? "Final pictures" : "Pictures"),
    h("span", { class: "muted small" }, finished ? day(rec.at) : [rec.title ? `after “${rec.title}”` : "after the newest task", ` · ${ago(rec.at)}`])),
    kinds.length ? h("div", { class: "shots" }, kinds.map((k) => h("figure", { class: "shot " + k }, picture(shotUrl(path, rec, k), SHOT_NAMES[k] || k), h("figcaption", {}, SHOT_NAMES[k] || k))))
      : h("p", { class: "muted" }, rec.failed || rec.note || "No pictures this time."),
    kinds.length && rec.note ? h("p", { class: "small muted" }, rec.note) : null,
    errs.length ? h("details", {}, h("summary", { title: "Errors the page wrote while the pictures were taken" }, `The page reported ${errs.length} error${errs.length > 1 ? "s" : ""}`), h("pre", { class: "log short" }, errs.join("\n"))) : null,
    earlier.length > 1 ? h("details", {}, h("summary", {}, `Earlier pictures (${earlier.length - 1})`), h("div", { class: "strip" }, earlier.map((r) => h("figure", {}, picture(shotUrl(path, r, "desktop"), r.title || "An earlier picture"),
      h("figcaption", {}, r.title || "", h("span", { class: "muted" }, " " + ago(r.at))))))) : null);
}
