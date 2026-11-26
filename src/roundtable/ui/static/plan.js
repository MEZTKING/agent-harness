// The Plan tab: the living plan. On this computer: the estimate and the set of models, your input cards, what it
// should be like, the looks, the second opinion, scope and rules, each part with its tasks, the history.
// A project another computer builds: its published plan with its cards, answered through the hub.
import { h, fill, get, post, toast, act, card, money, ago, plural, jobName, modelName, taskPill, prose, q, refreshHall, projectHref, dialog, seg } from "./core.js";
import { askCard, answerHere, answerHub, hubCommand } from "./asks.js";

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

async function localPlan(seat, redraw) {
  const path = seat.path, qp = q({ path });
  const [d, aq] = await Promise.all([get(`/api/plan?${qp}`), get(`/api/asks?${qp}&answered=1`).catch(() => ({ asks: [] }))]);
  const doc = d.doc;
  const edit = async (body, ok) => { try { await post("/api/plan", { path, ...body }); if (ok) toast(ok); await redraw(); } catch (e) { toast(e.message, true); } };
  const startJob = async (body, ok) => { try { await post("/api/plan", { path, ...body }); toast(ok); await refreshHall(); setTimeout(redraw, 1500); } catch (e) { toast(e.message, true); } };
  if (!doc) {
    return [card("No plan yet", h("p", { class: "muted" }, d.tasks.length ? "This project was planned before plans became documents: its tasks are below."
      : d.busy ? "The planner is making the plan now. It shows here in a minute or two." : "The planner hasn't made a plan yet."), d.tasks.length ? taskList(d.tasks) : null)];
  }
  const est = doc.estimate || {}, pending = doc.pending || [];
  const instr = h("textarea", { rows: 2, class: "grow", placeholder: "Tell the planner what to change (optional), e.g. “make it a 2D platformer, no multiplayer”", "aria-label": "What to change" });
  const ests = doc.estimates || {};
  const head = card(h("div", { class: "card-head" }, h("h2", {}, d.approved ? "The plan" : "The plan, waiting for you"), h("span", { class: "muted small", title: "Each change makes a new version; History below lists them" }, `version ${doc.version}`)),
    h("p", { class: "goal" }, doc.goal),
    doc.summary ? h("p", {}, doc.summary) : null,
    h("div", { class: "facts" },
      h("span", { class: "fact", title: est.note || "What the planner expects the building to cost" }, h("b", {}, `about ${money(est.cost_usd || 0)}`), "to build"),
      h("span", { class: "fact" }, h("b", {}, `about ${Math.max(1, Math.round(est.minutes || 0))} min`), "of work"),
      h("span", { class: "fact" }, h("b", {}, plural(est.tasks || 0, "task")), "to do"),
      est.unpriced && est.unpriced.length ? h("span", { class: "fact warn", title: `These models have no price yet, so the estimate leaves them out: ${est.unpriced.map((m) => modelName(m)).join(", ")}. Add their price in Settings → AI services.` },
        h("b", {}, "+ some"), "not priced") : null),
    Object.keys(ests).length ? h("div", { class: "set-pick" }, h("span", { class: "label", title: "Which models do the work. It applies to the tasks still to do." }, "Set of models"),
      seg(Object.keys(ests).map((n) => [n, `${setName(n)} · about ${money(ests[n].cost_usd || 0)}`, (SETS[n] || [])[1] || ""]), doc.profile, (n) => n !== doc.profile && edit({ action: "profile", name: n }, `This project now uses the ${setName(n)} set`), "Set of models")) : null,
    d.busy ? h("p", { class: "muted small" }, "It's working on this project now; changes wait until it stops.") : null,
    d.approved ? null : h("div", { class: "row" }, instr),
    d.approved ? h("p", { class: "muted small" }, "Approved: it's being built as it says. To change it, add to the project from its page.") : h("div", { class: "row" },
      h("button", { class: pending.length ? "primary" : "", disabled: d.busy, title: "The planner rewrites the plan with your answers and changes (a few cents)", onclick: () => startJob({ action: "revise", text: instr.value }, "Updating the plan…") },
        pending.length ? `Update the plan (${plural(pending.length, "change")})` : "Update the plan"),
      h("button", { class: pending.length ? "" : "primary", disabled: d.busy || pending.length > 0, title: pending.length ? "Update the plan with your changes first" : "Building starts now, as the plan says",
        onclick: () => startJob({ action: "approve" }, "Approved: building has started") }, "Approve and start"),
      d.open && d.open.choices ? h("span", { class: "muted small" }, `${plural(d.open.choices, "choice")} left on the recommended answer`) : null),
    pending.length ? h("details", { class: "small" }, h("summary", {}, `Your changes waiting to go in (${pending.length})`), h("ul", {}, pending.map((p) => h("li", {}, p.text)))) : null);

  const pictures = {};
  if (Object.keys((doc.look || {}).pictures || {}).length) {
    try { const r = await get(`/api/plan/looks?${qp}`); for (const [id, pp] of Object.entries(r.pictures || {})) pictures[id] = pp.desktop; } catch { /* the words still show */ }
  }
  const mine = (aq.asks || []).filter((a) => ["decision", "question", "look", "idea"].includes(a.kind));
  const waiting = mine.filter((a) => !a.answer), answered = mine.filter((a) => a.answer);
  const cardFor = (a) => askCard(a, async (ans) => { await answerHere(a, ans); await refreshHall(); await redraw(); }, { pictures, disabled: d.busy });
  const input = mine.length ? card("Your input",
    h("p", { class: "muted small" }, waiting.length ? `${plural(waiting.length, "question")} for you. Tap an answer: the recommended one is first. Or type your own with Other….`
      : "All answered. Update the plan to put your answers in, then approve it."),
    waiting.length ? h("div", { class: "asks" }, waiting.map(cardFor)) : null,
    answered.length ? h("details", {}, h("summary", {}, `Answered (${answered.length}): change an answer`), h("div", { class: "asks" }, answered.map(cardFor))) : null)
    : d.approved && (doc.decisions || []).length ? card("Choices", h("ul", {}, doc.decisions.map((c) => {
      const pick = c.options.find((op) => op.id === (c.chosen || c.recommended));
      return h("li", {}, h("b", {}, c.question), " ", pick ? pick.label : "", h("span", { class: "muted small" }, c.chosen ? " (your choice)" : " (recommended)"));
    }))) : null;

  const cr = doc.critique;
  const critique = cr ? card(h("div", { class: "card-head" }, h("h2", {}, "Second opinion"), h("span", { class: "muted small" }, `from ${modelName(cr.model)}`)),
    h("p", {}, h("span", { class: "pill " + (cr.verdict === "good" ? "good" : "warn") }, cr.verdict === "good" ? "Looks good" : "Suggested changes"),
      cr.verdict !== "good" && (doc.history || []).some((x) => x.by === "critic") ? h("span", { class: "muted small" }, " · the planner changed the plan in reply") : null),
    h("ul", {}, (cr.points || []).map((pt) => h("li", {}, h("span", { class: "pill " + ({ high: "bad", medium: "warn" }[pt.severity] || "") }, { high: "Important", medium: "Worth doing", low: "Small" }[pt.severity] || pt.severity), " ", pt.text,
      pt.suggestion ? h("div", { class: "muted small" }, "Suggestion: ", pt.suggestion) : null)))) : null;

  const listEditor = (title, tip, items, addBody, removeBody, placeholder) => {
    const inp = h("input", { class: "grow", placeholder, "aria-label": placeholder });
    const addIt = () => inp.value.trim() && edit(addBody(inp.value.trim()), "Added: update the plan to put it in");
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); addIt(); } });
    return h("div", {}, h("h3", { title: tip }, title),
      items.length ? h("ul", { class: "plain edit-list" }, items.map((it) => h("li", {}, h("span", { class: "grow" }, it.text, it.why ? h("span", { class: "muted small" }, ` · ${it.why}`) : null,
        it.by === "owner" ? h("span", { class: "pill info" }, "yours") : null),
      h("button", { class: "icon danger", disabled: d.busy, title: "Take it off", "aria-label": `Take off: ${it.text}`, onclick: () => edit(removeBody(it)) }, "×")))) : h("p", { class: "muted small" }, "Nothing yet."),
      h("div", { class: "row" }, inp, h("button", { class: "small", disabled: d.busy, onclick: addIt }, "Add")));
  };
  const scope = card("What it does and doesn't do",
    h("div", { class: "grid2" },
      listEditor("It does", "What it must do", (doc.in_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", text: v }), (it) => ({ action: "scope_remove", text: it.text }), "Add something it must do"),
      listEditor("It leaves out", "What it won't do (for now)", (doc.out_of_scope || []).map((t) => ({ text: t })), (v) => ({ action: "scope_add", out: true, text: v }), (it) => ({ action: "scope_remove", out: true, text: it.text }), "Add something to leave out")),
    listEditor("Never", "Rules every task follows", doc.dont || [], (v) => ({ action: "dont_add", text: v }), (it) => ({ action: "dont_remove", id: it.id }), "Add something it must never do"));

  const bySection = {};
  d.tasks.forEach((t) => (bySection[t.section || ""] = bySection[t.section || ""] || []).push(t));
  const spec = card("The parts, and their tasks", (doc.spec || []).map((sp) => {
    const ta = h("textarea", { rows: 5, class: "grow", "aria-label": `Change: ${sp.title}` }, sp.text);
    const editBox = h("div", { class: "stack", hidden: true }, ta, h("div", { class: "row" },
      h("button", { class: "primary small", onclick: () => edit({ action: "section", id: sp.id, text: ta.value }, "Changed: update the plan to put it in") }, "Save"),
      h("button", { class: "small", onclick: () => { editBox.hidden = true; txt.hidden = false; } }, "Cancel")));
    const txt = h("div", {}, prose(sp.text));
    return h("div", { class: "spec" },
      h("div", { class: "row" }, h("h3", { class: "grow" }, sp.title),
        d.approved ? null : h("button", { class: "small", disabled: d.busy, title: "Change what this part says", onclick: () => { editBox.hidden = false; txt.hidden = true; ta.focus(); } }, "Change")),
      txt, editBox, bySection[sp.id] ? taskList(bySection[sp.id], d.tasks) : h("p", { class: "muted small" }, "No tasks for this part."));
  }), (bySection[""] || []).length ? [h("h3", {}, "Other tasks"), taskList(bySection[""], d.tasks)] : null);

  const history = (doc.history || []).length > 1 ? h("details", { class: "card fold" }, h("summary", {}, `History (${doc.history.length} versions)`), h("ul", {}, doc.history.slice().reverse().map((x) => h("li", { class: "small" },
    `Version ${x.version} · ${ago(x.at)} · ${x.by === "critic" ? "changed after the second opinion" : x.by === "owner" ? "your changes" : x.change || "the first plan"}`,
    x.diff ? h("span", { class: "muted" }, ` (${["added", "changed", "removed"].filter((k) => x.diff[k] && x.diff[k].length).map((k) => `${x.diff[k].length} ${k}`).join(", ") || "tasks the same"})`) : null)))) : null;

  return [head, input, likeSection(doc.references || [], d.busy, edit), lookSection(doc.look || {}, d.busy, edit, startJob), critique, scope, spec, history];
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
        h("button", { class: "icon danger", disabled: busy, title: "Stop making it like this one", onclick: () => edit({ action: "reference_remove", id: r.id }, "Taken off: update the plan to put it in") }, "×")),
      rep.what_it_is ? h("p", { class: "small" }, rep.what_it_is) : null,
      r.status === "failed" ? h("p", { class: "muted small" }, r.error) : null,
      (rep.borrow || []).length ? h("p", { class: "small" }, h("b", {}, "Borrow: "), rep.borrow.join("; ")) : null,
      (rep.avoid || []).length ? h("p", { class: "small" }, h("b", {}, "Avoid: "), rep.avoid.join("; ")) : null,
      r.report ? h("p", { class: "muted small", title: "Code is only used when its licence clearly allows it, and then it's credited" }, `Licence: ${rep.licence} · its code: ${rep.code_reuse}`) : null);
  };
  return card("Make it like these",
    h("p", { class: "muted small" }, "Things you want it to be like. Roundtable makes something similar, never a copy: no names, characters, art, music or text taken."),
    refs.map(one),
    h("div", { class: "row" }, inp, h("button", { class: "small", disabled: busy, title: "It's read (a few cents) when you next update the plan",
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
  return card("Looks",
    h("p", { class: "muted small" }, dirs.length ? "The looks in detail. Choose one on the Look card above: every task then follows it."
      : "No looks yet. Roundtable can design three different looks for the app, with a picture of each, for you to choose from."),
    dirs.length ? h("div", { class: "looks" }, dirs.map(one)) : null,
    dirs.length && !Object.keys(lk.pictures || {}).length && lk.render_note ? h("p", { class: "muted small" }, lk.render_note) : null,
    h("div", { class: "row" }, brief, h("button", { class: "small", disabled: busy, title: "Asks the designer for new looks (a few cents)",
      onclick: () => startJob({ action: "looks", text: brief.value }, "Designing new looks…") }, dirs.length ? "Make new looks" : "Make looks")));
}

// ---------- a plan another computer published ----------
async function hubPlan(seat) {
  if (!seat.hub_name) return card("No plan here", h("p", { class: "muted" }, "This project keeps a journal but has no plan in Roundtable."));
  let p;
  try { p = await get(`/api/hub/plan?${q({ name: seat.hub_name })}`); } catch (e) { return card("The plan couldn't open", h("p", {}, e.message)); }
  const need = { project: seat.id, hub_agent: p.agent || seat.hub_agent, hub_name: seat.hub_name };
  const md = p.markdown.replace(/^_Plan status:.*_\s*$/m, "");
  return [card(h("div", { class: "card-head" }, h("h2", {}, "The plan"), h("span", { class: "muted small" }, p.at ? `updated ${ago(p.at)}` : "")),
    h("p", { class: "muted small" }, "Another computer builds this project. Your answers and approval go to it through the hub, and it carries on there."),
    p.summary ? h("p", { class: "facts-line" }, p.summary) : null,
    p.state && /waiting/i.test(p.state) ? h("div", { class: "row" }, h("button", { class: "primary", title: "Sends your approval to the computer that builds it",
      onclick: (ev) => act(ev.currentTarget, () => hubCommand(need, "approve"), null, () => refreshHall()) }, "Approve and start")) : null),
  (p.asks || []).length ? card("Your input", h("div", { class: "asks" }, p.asks.map((a) => askCard(a, async (ans) => { await answerHub(need, a, ans); await refreshHall(); })))) : null,
  card("What it says", prose(md))];
}
