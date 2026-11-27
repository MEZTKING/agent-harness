// The Plan tab, short first: the plan's title, where it stands, your cards, the tasks; everything else under "More
// about this plan". On this computer it can be changed until it's approved.
// A project another computer builds: its published plan with its cards, answered through the hub.
import { h, fill, clean, get, post, toast, act, card, money, ago, plural, jobName, modelName, taskPill, prose, markdown, q, refreshHall, projectHref, dialog, seg } from "./core.js";
import { askCard, answerHere, answerHub, hubCommand } from "./asks.js";
import { composer } from "./compose.js";
import { kindCard } from "./kinds.js";
import { doneCard } from "./donelist.js";
import { stagedTaskList } from "./stages.js";
import { pounds } from "./pounds.js";

const SETS = { budget: ["Budget", "Cheapest that still works"], balanced: ["Balanced", "Strong models where it matters, cheaper ones for the rest"], quality: ["Quality", "The strongest model for every job"] };
const setName = (n) => (SETS[n] || [n[0].toUpperCase() + n.slice(1)])[0];

export async function planTab(seat) {
  if (!seat.path) return hubPlan(seat);
  const box = h("div", { class: "plan-page" }, h("p", { class: "muted" }, "Loading the plan…"));
  const draw = async () => {
    try { fill(box, await localPlan(seat, draw)); } catch (e) { fill(box, card("The plan couldn't open", h("p", {}, e.message), h("button", { onclick: draw }, "Try again"))); }
  };
  await draw();
  return box;
}

// Short first: the title, one sentence of where it stands, what waits for you, the tasks one line each; the rest
// (the builders' brief, scope, spec, the second opinion, prices, history) folded under "More about this plan".
async function localPlan(seat, redraw) {
  const path = seat.path, qp = q({ path });
  const [d, aq] = await Promise.all([get(`/api/plan?${qp}`), get(`/api/asks?${qp}&answered=1`).catch(() => ({ asks: [] }))]);
  const doc = d.doc;
  const edit = async (body, ok) => { try { await post("/api/plan", { path, ...body }); if (ok) toast(ok); await redraw(); } catch (e) { toast(e.message, true); } };
  const startJob = async (body, ok) => { try { await post("/api/plan", { path, ...body }); toast(ok); await refreshHall(); setTimeout(redraw, 1500); } catch (e) { toast(e.message, true); } };
  if (!doc) {
    return [card("No plan yet", h("p", { class: "muted" }, d.tasks.length ? "This project was planned before plans became documents: its tasks are below."
      : d.busy ? "The planner is making the plan now. It shows here in a minute or two." : "The planner hasn't made a plan yet."), d.tasks.length ? taskLines(d.tasks) : null)];
  }
  const words = d.words || {}, pending = doc.pending || [], locked = d.approved;
  const finished = d.status === "done";
  const mine = (aq.asks || []).filter((a) => ["decision", "question", "look", "idea"].includes(a.kind));
  const waiting = mine.filter((a) => !a.answer), answered = mine.filter((a) => a.answer);
  const pictures = {};
  if (waiting.some((a) => a.kind === "look") && Object.keys((doc.look || {}).pictures || {}).length) {
    try { const r = await get(`/api/plan/looks?${qp}`); for (const [id, pp] of Object.entries(r.pictures || {})) pictures[id] = pp.desktop; } catch { /* the words still show */ }
  }
  const cardFor = (a) => askCard(a, async (ans) => { await answerHere(a, ans); await refreshHall(); await redraw(); }, { pictures, disabled: d.busy });

  // the top: title, where it stands, the estimate only while it waits for approval
  // the words wait in the plan for Update the plan; pictures and files go to the planner with them (compose.js)
  const noteBox = composer({ key: `note:${seat.path}`, project: seat.path, rows: 2, label: "What to change",
    placeholder: "What should change? e.g. “no multiplayer”", sendLabel: "Add this note",
    onSend: async ({ text, key, items }) => {
      await post("/api/plan", { path: seat.path, action: "note", text });
      if (items.length) await post("/api/attach/send", { key, path: seat.path, as: "note", text });
      toast("Noted: press Update the plan to put it in");
      await redraw();
    } });
  noteBox.hidden = true;
  const note = { get value() { return noteBox.composer.text(); }, focus: () => noteBox.composer.focus() };
  const top = card(
    h("div", { class: "card-head" }, h("h2", { class: "plan-title" }, words.title || "The plan"),
      h("span", { class: "muted small", title: "Each change makes a new version; More about this plan lists them" }, `version ${doc.version}`)),
    h("p", { class: "plan-state" }, h("i", { class: "sdot " + (finished ? "good" : locked ? "busy" : "wait") }), words.state || ""),
    !locked && words.estimate ? h("p", { class: "muted small", title: (doc.estimate || {}).note || "What the planner expects the building to cost" }, words.estimate[0].toUpperCase() + words.estimate.slice(1),
      pounds((doc.estimate || {}).cost_usd) ? ` (${pounds(doc.estimate.cost_usd)})` : "") : null,
    d.busy ? h("p", { class: "muted small" }, "It's working on this project now; changes wait until it stops.") : null,
    locked ? null : h("div", { class: "row" },
      pending.length ? h("button", { class: "primary", disabled: d.busy, title: "The planner rewrites the plan with your answers and changes (a few cents)",
        onclick: () => startJob({ action: "revise", text: note.value }, "Updating the plan…") }, `Update the plan (${plural(pending.length, "change")})`) : null,
      h("button", { class: pending.length ? "" : "primary", disabled: d.busy || pending.length > 0, title: pending.length ? "Update the plan with your changes first" : "Building starts now, as the plan says",
        onclick: () => startJob({ action: "approve" }, "Approved: building has started") }, "Approve and start"),
      h("button", { class: "small", disabled: d.busy, title: "Tell the planner what to change; it waits until you update the plan", onclick: () => { noteBox.hidden = !noteBox.hidden; if (!noteBox.hidden) note.focus(); } }, "Tell the planner")),
    locked ? null : noteBox,
    pending.length ? h("details", { class: "small" }, h("summary", {}, `Your changes waiting to go in (${pending.length})`), h("ul", {}, pending.map((p) => h("li", {}, p.text)))) : null);

  const input = waiting.length && !locked ? h("div", { class: "asks" }, waiting.map(cardFor)) : null;
  const done = d.tasks.filter((t) => t.status === "done").length;
  const tasks = d.tasks.length ? card(h("div", { class: "card-head" }, h("h2", {}, "Tasks"), h("span", { class: "muted small" }, `${done} of ${d.tasks.length} done`)),
    stagedTaskList(d.tasks, doc.stages, taskLines)) : null;  // under a heading per stage when the plan has stages

  // More about this plan: each part its own fold
  const ests = doc.estimates || {};
  const fold = (title, ...kids) => { const body = clean(kids); return body.length ? h("details", { class: "fold-part" }, h("summary", {}, title), h("div", {}, body)) : null; };
  const bySection = {};
  d.tasks.forEach((t) => (bySection[t.section || ""] = bySection[t.section || ""] || []).push(t));
  const cr = doc.critique;
  const more = h("details", { class: "card fold more" }, h("summary", { title: "The builders' brief, what's in and out, the parts, the second opinion, the prices and the history" }, "More about this plan"),
    fold("What it will be", doc.summary ? h("p", {}, doc.summary) : null),
    fold("The builders' brief", h("p", { class: "muted small" }, "What the planner was asked to build, as written for the builders."), prose(doc.goal)),
    answered.length && !locked ? fold(`Your answers (${answered.length}): change one`, h("div", { class: "asks" }, answered.map(cardFor))) : null,
    locked && (doc.decisions || []).length ? fold(`Choices (${doc.decisions.length})`, h("ul", {}, doc.decisions.map((c) => {
      const pick = c.options.find((op) => op.id === (c.chosen || c.recommended));
      return h("li", {}, h("b", {}, c.question), " ", pick ? pick.label : "", h("span", { class: "muted small" }, c.chosen ? " (your choice)" : " (recommended)"));
    }))) : null,
    Object.keys(ests).length ? fold("Sets of models and their prices",
      locked ? h("ul", {}, Object.keys(ests).map((n) => h("li", {}, `${setName(n)}: about ${money(ests[n].cost_usd || 0)}`, n === doc.profile ? h("span", { class: "muted small" }, " (used)") : null)))
        : seg(Object.keys(ests).map((n) => [n, `${setName(n)} · about ${money(ests[n].cost_usd || 0)}`, (SETS[n] || [])[1] || ""]), doc.profile, (n) => n !== doc.profile && edit({ action: "profile", name: n }, `This project now uses the ${setName(n)} set`), "Set of models")) : null,
    fold("What it does and doesn't do", scopeLists(doc, locked || d.busy, edit)),
    (doc.spec || []).length ? fold(`The parts (${doc.spec.length})`, (doc.spec || []).map((sp) => specPart(sp, bySection[sp.id], d.tasks, locked || d.busy, edit))) : null,
    (doc.references || []).length || !locked ? fold("Make it like these", likeSection(doc.references || [], d.busy || locked, edit)) : null,
    (doc.look || {}).directions && (doc.look.directions.length || !locked) ? fold("Looks", lookSection(doc.look || {}, d.busy || locked, edit, startJob)) : null,
    cr ? fold(`Second opinion${cr.verdict === "good" ? ": looks good" : ""}`, h("p", { class: "muted small" }, `From ${modelName(cr.model)}`),
      h("ul", {}, (cr.points || []).map((pt) => h("li", {}, h("span", { class: "pill " + ({ high: "bad", medium: "warn" }[pt.severity] || "") }, { high: "Important", medium: "Worth doing", low: "Small" }[pt.severity] || pt.severity), " ", pt.text,
        pt.suggestion ? h("div", { class: "muted small" }, "Suggestion: ", pt.suggestion) : null)))) : null,
    (doc.history || []).length > 1 ? fold(`History (${doc.history.length} versions)`, h("ul", {}, doc.history.slice().reverse().map((x) => h("li", { class: "small" },
      `Version ${x.version} · ${ago(x.at)} · ${x.by === "critic" ? "changed after the second opinion" : x.by === "owner" ? "your changes" : x.change || "the first plan"}`)))) : null);

  const kind = doc.kind ? kindCard(doc.kind, path, () => { refreshHall(); redraw(); }) : null;  // "This looks like a website. Right?"
  const doneList = doneCard(seat);  // "Done when: 5 of 7 ✓", each thing on opening (donelist.js)
  return [kind, top, doneList, input, tasks, more];
}

// one line a task: a tick when done, a dot otherwise
export function taskLines(tasks) {
  const mark = { done: ["✓", "good"], running: ["●", "busy"], failed: ["!", "bad"], skipped: ["–", "muted"] };
  return h("ol", { class: "task-lines" }, tasks.map((t) => {
    const [m, c] = mark[t.status] || ["○", "muted"];
    return h("li", { class: t.status, title: `${t.title} · ${jobName(t.role || "")}` }, h("span", { class: "tl-mark " + c, "aria-label": t.status }, m), h("span", { class: "tl-title" }, t.title));
  }));
}

function scopeLists(doc, readOnly, edit) {
  const listEditor = (title, tip, items, addBody, removeBody, placeholder) => {
    const inp = h("input", { class: "grow", placeholder, "aria-label": placeholder });
    const addIt = () => inp.value.trim() && edit(addBody(inp.value.trim()), "Added: update the plan to put it in");
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); addIt(); } });
    return h("div", {}, h("h3", { title: tip }, title),
      items.length ? h("ul", { class: "plain edit-list" }, items.map((it) => h("li", {}, h("span", { class: "grow" }, it.text, it.why ? h("span", { class: "muted small" }, ` · ${it.why}`) : null,
        it.by === "owner" ? h("span", { class: "pill info" }, "yours") : null),
      readOnly ? null : h("button", { class: "icon danger", title: "Take it off", "aria-label": `Take off: ${it.text}`, onclick: () => edit(removeBody(it)) }, "×")))) : h("p", { class: "muted small" }, "Nothing yet."),
      readOnly ? null : h("div", { class: "row" }, inp, h("button", { class: "small", onclick: addIt }, "Add")));
  };
  return [h("div", { class: "grid2" },
    listEditor("It does", "What it must do", (doc.in_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", text: v }), (it) => ({ action: "scope_remove", text: it.text }), "Add something it must do"),
    listEditor("It leaves out", "What it won't do (for now)", (doc.out_of_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", out: true, text: v }), (it) => ({ action: "scope_remove", out: true, text: it.text }), "Add something to leave out")),
  listEditor("Never", "Rules every task follows", doc.dont || [], (v) => ({ action: "dont_add", text: v }), (it) => ({ action: "dont_remove", id: it.id }), "Add something it must never do")];
}

function specPart(sp, tasks, all, readOnly, edit) {
  const ta = h("textarea", { rows: 5, class: "grow", "aria-label": `Change: ${sp.title}` }, sp.text);
  const txt = h("div", {}, prose(sp.text));
  const editBox = h("div", { class: "stack", hidden: true }, ta, h("div", { class: "row" },
    h("button", { class: "primary small", onclick: () => edit({ action: "section", id: sp.id, text: ta.value }, "Changed: update the plan to put it in") }, "Save"),
    h("button", { class: "small", onclick: () => { editBox.hidden = true; txt.hidden = false; } }, "Cancel")));
  return h("details", { class: "fold-part spec" }, h("summary", {}, sp.title),
    readOnly ? null : h("div", { class: "row" }, h("span", { class: "grow" }), h("button", { class: "small", title: "Change what this part says", onclick: () => { editBox.hidden = false; txt.hidden = true; ta.focus(); } }, "Change")),
    txt, editBox, tasks ? taskList(tasks, all) : null);
}

export function taskList(tasks, all = tasks) {
  const title = (id) => (all.find((t) => t.id === id) || {}).title || id;
  return h("ol", { class: "tasks compact" }, tasks.map((t) => {
    const last = t.attempts[t.attempts.length - 1];
    return h("li", { class: "task " + t.status }, h("div", { class: "task-top" }, h("b", {}, t.title), taskPill(t.status)),
      h("div", { class: "task-meta" }, jobName(t.role), last ? ` · ${modelName(last.model, true)}` : "", t.depends_on.length ? ` · after ${t.depends_on.map(title).join(", ")}` : ""));
  }));
}

// "Make it like this": what the owner wants it to be like, as the researcher read each one
function likeSection(refs, busy, edit) {
  const inp = h("input", { class: "grow", placeholder: "A link, a project or a description, e.g. “the queue from Spotify”", "aria-label": "Something to make it like" });
  const state = { new: "Not read yet", failed: "Couldn't read it" };
  const one = (r) => {
    const rep = r.report || {};
    return h("div", { class: "ref" },
      h("div", { class: "row" }, h("b", { class: "grow" }, rep.title || r.input),
        state[r.status] ? h("span", { class: "pill " + (r.status === "failed" ? "warn" : "") }, state[r.status]) : null,
        busy ? null : h("button", { class: "icon danger", title: "Stop making it like this one", onclick: () => edit({ action: "reference_remove", id: r.id }, "Taken off: update the plan to put it in") }, "×")),
      rep.what_it_is ? h("p", { class: "small" }, rep.what_it_is) : null,
      r.status === "failed" ? h("p", { class: "muted small" }, r.error) : null,
      (rep.borrow || []).length ? h("p", { class: "small" }, h("b", {}, "Borrow: "), rep.borrow.join("; ")) : null,
      (rep.avoid || []).length ? h("p", { class: "small" }, h("b", {}, "Avoid: "), rep.avoid.join("; ")) : null,
      r.report ? h("p", { class: "muted small", title: "Code is only used when its licence clearly allows it, and then it's credited" }, `Licence: ${rep.licence} · its code: ${rep.code_reuse}`) : null);
  };
  return h("div", {},
    h("p", { class: "muted small" }, "Things you want it to be like. The harness makes something similar, never a copy: no names, characters, art, music or text taken."),
    refs.map(one),
    busy ? null : h("div", { class: "row" }, inp, h("button", { class: "small", title: "It's read (a few cents) when you next update the plan",
      onclick: () => inp.value.trim() && edit({ action: "reference_add", text: inp.value.trim() }, "Added: update the plan to read it and use it") }, "Add")));
}

// the looks: the designer's directions side by side
function lookSection(lk, busy, edit, startJob) {
  const dirs = lk.directions || [];
  const brief = h("input", { class: "grow", placeholder: "A starting point for new looks (optional), e.g. “like an old record shop”", "aria-label": "A starting point for new looks" });
  const swatch = (hex, title) => h("span", { class: "swatch", title, style: `background:${hex}` });
  const one = (x) => {
    const chosen = lk.chosen === x.id, light = x.palette.light;
    return h("div", { class: "look" + (chosen ? " chosen" : "") },
      h("b", {}, x.name, chosen ? h("span", { class: "pill info" }, "your choice") : null),
      h("p", { class: "small" }, x.mood),
      h("p", { class: "muted small" }, "What makes it stand out: ", x.signature),
      h("div", { class: "row swatches", title: "Its colours" }, ["background", "surface", "text", "accent"].map((k) => swatch(light[k], k)),
        h("span", { class: "muted small" }, `${x.fonts.display.family} and ${x.fonts.body.family}`)));
  };
  return h("div", {},
    h("p", { class: "muted small" }, dirs.length ? "The looks in detail. Choose one on the Look card above: every task then follows it."
      : "No looks yet. The harness can design three different looks for the app, with a picture of each, for you to choose from."),
    dirs.length ? h("div", { class: "looks" }, dirs.map(one)) : null,
    dirs.length && !Object.keys(lk.pictures || {}).length && lk.render_note ? h("p", { class: "muted small" }, lk.render_note) : null,
    busy ? null : h("div", { class: "row" }, brief, h("button", { class: "small", title: "Asks the designer for new looks (a few cents)",
      onclick: () => startJob({ action: "looks", text: brief.value }, "Designing new looks…") }, dirs.length ? "Make new looks" : "Make looks")));
}

// ---------- a plan another computer published ----------
async function hubPlan(seat) {
  if (!seat.hub_name) return card("No plan here", h("p", { class: "muted" }, "This project keeps a journal but has no plan in the harness."));
  let p;
  try { p = await get(`/api/hub/plan?${q({ name: seat.hub_name })}`); } catch (e) { return card("The plan couldn't open", h("p", {}, e.message)); }
  const need = { project: seat.id, hub_agent: p.agent || seat.hub_agent, hub_name: seat.hub_name };
  const md = splitPlan(p.markdown);
  const st = (p.state || "").toLowerCase();
  const finished = /^done/.test(st) || (md.tasks.length && md.tasks.every((t) => t.status === "done") && !/waiting/.test(st));
  const waiting = !finished && /waiting/.test(st);
  const state = p.plan_state || (finished ? `Finished – ${plural(md.tasks.length, "task")}` : waiting ? "Waiting for you" : md.tasks.length
    ? `${md.tasks.filter((t) => t.status === "done").length} of ${md.tasks.length} tasks done` : p.state);
  const est = waiting ? (p.estimate || md.estimate.replace(", about ", " and ")) : "";
  const top = card(h("div", { class: "card-head" }, h("h2", { class: "plan-title" }, p.plan_title || p.goal || "The plan"), h("span", { class: "muted small" }, p.at ? `updated ${ago(p.at)}` : "")),
    h("p", { class: "plan-state" }, h("i", { class: "sdot " + (finished ? "good" : waiting ? "wait" : "busy") }), state,
      h("span", { class: "muted small", title: "Your answers and approval go to that computer through the hub, and it carries on there" }, " · built on another computer")),
    est ? h("p", { class: "muted small" }, est[0].toUpperCase() + est.slice(1)) : null,
    waiting ? h("div", { class: "row" }, h("button", { class: "primary", title: "Sends your approval to the computer that builds it",
      onclick: (ev) => act(ev.currentTarget, () => hubCommand(need, "approve"), null, () => refreshHall()) }, "Approve and start")) : null);
  const asks = (p.asks || []).length && !finished ? h("div", { class: "asks" }, p.asks.map((a) => askCard(a, async (ans) => { await answerHub(need, a, ans); await refreshHall(); }))) : null;
  const done = md.tasks.filter((t) => t.status === "done").length;
  const tasks = md.tasks.length ? card(h("div", { class: "card-head" }, h("h2", {}, "Tasks"), h("span", { class: "muted small" }, `${done} of ${md.tasks.length} done`)), taskLines(md.tasks)) : null;
  const parts = [p.plan_summary ? null : md.intro.length ? ["What it will be", md.intro.join("\n\n")] : null, ...md.sections.map((x) => [x.title, x.body])].filter(Boolean);
  const more = parts.length ? h("details", { class: "card fold more" }, h("summary", {}, "More about this plan"),
    parts.map(([t, body]) => h("details", { class: "fold-part" }, h("summary", {}, t), markdown(body)))) : null;
  return [top, asks, tasks, more];
}

// A published plan's markdown in parts: the heading (old plans: the builders' brief), the intro, the estimate line,
// the tasks ("- [T1] done Title (role)") and every other section.
export function splitPlan(text) {
  const out = { heading: "", intro: [], estimate: "", tasks: [], sections: [] };
  let cur = null;
  for (const raw of String(text || "").replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (/^_Plan status:/.test(line)) continue;
    const h1 = line.match(/^# (.*)$/), h2 = line.match(/^## (.*)$/);
    if (h1 && !out.heading && !cur) { out.heading = h1[1]; continue; }
    if (h2) { cur = { title: h2[1].replace(/\s*\[[\w.-]+\]$/, ""), body: "" }; out.sections.push(cur); continue; }
    if (!cur) {
      if (/^Estimate:/.test(line)) out.estimate = line.replace(/^Estimate:\s*/, "");
      else if (/^Settings:/.test(line)) out.sections.push(cur = { title: "Sets of models", body: line + "\n" }), cur = null;
      else if (line.trim()) out.intro.push(line.replace(/\s*\{[\w.:-]+\}$/, ""));
      continue;
    }
    cur.body += line.replace(/\s*\{[\w.:-]+\}$/, "") + "\n";
  }
  const old = out.heading.match(/^Plan v\d+:\s*(.*)$/);
  if (old) out.sections.unshift({ title: "The builders' brief", body: old[1] });
  const t = out.sections.findIndex((x) => /^tasks$/i.test(x.title));
  if (t >= 0) {
    for (const ln of out.sections[t].body.split("\n")) {
      const m = ln.match(/^- \[([\w.-]+)\]\s+(\w+)\s+(.*?)(?:\s+\(([^)]*)\))?$/);
      if (m) out.tasks.push({ id: m[1], status: m[2], title: m[3], role: m[4] || "" });
    }
    out.sections.splice(t, 1);
  }
  return out;
}
