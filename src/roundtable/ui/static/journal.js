// A project's journal (the hub's shared notebook): notes, to-dos, plans, decisions and sessions, newest first; add
// one; what other agents read about the project. Also "My notes", the owner's own page.
import { h, fill, get, post, S, act, card, page, ago, empty, seg, toast, refreshHall, projectName, when, q, markdown, has } from "./core.js";

const KINDS = [["all", "Everything"], ["todo", "To-dos"], ["plan", "Plans"], ["decision", "Decisions"], ["done", "Done"], ["note", "Notes"], ["session", "Sessions"]];
const KIND_WORD = { todo: "To-do", plan: "Plan", decision: "Decided", done: "Done", note: "Note", session: "Session" };
const ADD = [["todo", "To-do", "Something to do"], ["note", "Note", "Something worth remembering"], ["plan", "Plan", "Something you mean to do later"],
  ["decision", "Decision", "Something you decided"], ["done", "Done", "Something that's finished"], ["session", "Session", "What a working session did, and what comes next"]];

export async function journalTab(seat) {
  const hubAgent = (S.ov.agents || []).some((a) => a.id === seat.id);
  if (!hubAgent) return briefOnly(seat);
  return journal(seat.id, true);
}

export async function notesPage(notes) {
  const parts = [await savedDocs(), await journal(notes.id, false)];
  if (notes.runner && notes.runner.brief) {
    const b = notes.runner.brief;
    parts.push(card("Roundtable's own list", h("p", { class: "muted small" }, "Things Roundtable noted that don't belong to one project."),
      (b.open_todos || []).length ? h("ul", { class: "entries" }, b.open_todos.map((e) => entryRow(notes.runner.id, e, true))) : h("p", { class: "muted" }, "Nothing open.")));
  }
  return page("My notes", "Your own notes, to-dos and plans that don't belong to one project. Every computer and agent connected to your hub can read them.",
    h("a", { class: "back", href: "#/" }, "← The Hall"), ...parts);
}

// The owner's saved documents in the hub (notes/*.md): titles only until one is opened.
async function savedDocs() {
  if (!(await has("/api/notes"))) return null;
  let list;
  try { list = (await get("/api/notes")).notes || []; } catch { return null; }
  if (!list.length) return null;
  const box = h("div");
  const showList = () => fill(box, card("Saved documents",
    h("ul", { class: "plain doc-list" }, list.map((n) => h("li", {}, h("button", { class: "linkish", title: "Open it", onclick: () => open(n) }, n.title))))));
  const open = async (n) => {
    fill(box, card(n.title, h("p", { class: "muted" }, "Opening it…")));
    try {
      const d = await get(`/api/note?${q({ name: n.name })}`);
      const doc = markdown(d.markdown);
      const first = doc.firstElementChild;
      if (first && /^H[1-4]$/.test(first.tagName) && first.textContent.trim() === d.title) first.remove();  // it's the card's title
      fill(box, card(h("div", { class: "card-head" }, h("h2", {}, d.title), h("button", { class: "small", onclick: showList }, "← All documents")), doc));
    } catch (e) { fill(box, card(n.title, h("p", {}, e.message), h("button", { onclick: showList }, "Back"))); }
  };
  showList();
  return box;
}

async function journal(agent, withCard) {
  const list = h("ul", { class: "entries" });
  let filter = "all", entries = [];
  const draw = () => {
    const shown = entries.filter((e) => filter === "all" || e.kind === filter).slice().reverse();
    fill(list, shown.length ? shown.map((e) => entryRow(agent, e, e.status === "open", reload)) : h("li", { class: "muted" }, filter === "all" ? "Nothing written yet. Add the first note below." : "Nothing of that kind yet."));
  };
  const reload = async () => { entries = await get(`/api/journal/${encodeURIComponent(agent)}`); draw(); };
  await reload();
  const parts = [card(h("div", { class: "card-head" }, h("h2", {}, "Journal"), seg(KINDS.map(([k, t]) => [k, t]), filter, (v) => { filter = v; draw(); }, "Show")), addForm(agent, reload), list)];
  if (withCard) parts.push(await aboutCard(agent));
  return h("div", { class: "stack" }, parts);
}

export function entryRow(agent, e, open, reload = () => refreshHall()) {
  const close = (dropped) => (ev) => act(ev.currentTarget, () => post(`/api/journal/${encodeURIComponent(agent)}/${encodeURIComponent(e.id)}/close`, dropped ? { dropped: true } : {}),
    dropped ? "Taken off the list" : "Marked done", reload);
  return h("li", { class: "entry " + (e.kind || "") + (e.priority === "high" ? " high" : "") },
    h("span", { class: "chip" }, KIND_WORD[e.kind] || e.kind),
    h("div", { class: "grow" },
      h("p", {}, e.priority === "high" ? h("b", { class: "prio", title: "Marked important" }, "Important · ") : null, e.text),
      (e.next || []).length ? h("ul", { class: "small" }, e.next.map((n) => h("li", {}, n))) : null,
      e.details ? h("details", {}, h("summary", { class: "small" }, "More"), h("p", { class: "pre-line small" }, e.details)) : null,
      h("span", { class: "muted small" }, when(e.created_at), e.source === "ui" ? " · from this app" : e.source === "harness" ? " · from Roundtable" : e.source ? " · from a session" : "",
        e.status && e.status !== "open" ? ` · ${e.status === "dropped" ? "taken off" : e.status}` : "")),
    open ? h("span", { class: "row" }, h("button", { class: "small", title: "It's done", onclick: close(false) }, "Done"),
      h("button", { class: "small icon", title: "Take it off the list without doing it", "aria-label": "Take it off", onclick: close(true) }, "×")) : null);
}

function addForm(agent, reload) {
  let kind = "todo";
  const text = h("input", { class: "grow", placeholder: "Write a to-do, a note or a decision…", "aria-label": "What to write", autocomplete: "off" });
  const high = h("input", { type: "checkbox" });
  const next = h("textarea", { rows: 2, hidden: true, placeholder: "What comes next, one a line", "aria-label": "What comes next" });
  const form = h("form", { class: "add-entry", onsubmit: async (ev) => {
    ev.preventDefault();
    if (!text.value.trim()) return toast("Write something first.", true);
    await act(form.querySelector("button.primary"), () => post(`/api/journal/${encodeURIComponent(agent)}`, { kind, text: text.value.trim(), priority: high.checked ? "high" : "normal",
      ...(kind === "session" ? { next: next.value.split("\n").map((x) => x.trim()).filter(Boolean) } : {}) }),
      "Written down", async () => { text.value = ""; next.value = ""; high.checked = false; await reload(); await refreshHall(); });
  } }, seg(ADD.map(([k, t, tip]) => [k, t, tip]), kind, (v) => { kind = v; next.hidden = v !== "session"; }, "Kind"), text,
  h("label", { class: "check small", title: "An important to-do for you shows up in Needs you" }, high, "Important"),
  h("button", { class: "primary" }, "Add"), next);
  return form;
}

async function aboutCard(agent) {
  let c;
  try { c = (await get("/api/cards")).find((x) => x.agent === agent); } catch { return null; }
  if (!c) return null;
  const f = (key, label, tip, rows) => h("label", { class: "field", title: tip }, h("span", { class: "label" }, label),
    rows ? h("textarea", { name: key, rows }, c[key] || "") : h("input", { name: key, value: c[key] || "" }));
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const d = Object.fromEntries(new FormData(form).entries());
    await act(form.querySelector("button"), () => post(`/api/cards/${encodeURIComponent(agent)}`, d), "Saved");
  } },
  f("summary", "In one line", "What the project is"), f("goal", "Its goal", "What it's working towards"), f("status", "Where it stands", "A few words on how it's going"),
  f("interfaces", "What others can use", "Parts other projects rely on: how to talk to it, what it offers", 3), f("notes", "Notes", "Anything else other agents should know", 3),
  f("change_note", "What changed (optional)", "A short note: the projects that depend on this one are told"),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Save")));
  return h("details", { class: "card fold" }, h("summary", { title: "What other agents and sessions read about this project" }, `About ${projectName(agent)} (what other agents read)`), form);
}

function briefOnly(seat) {
  const b = seat.brief || {};
  const all = [...(b.open_todos || []).map((e) => ({ ...e, kind: "todo", status: "open" })), ...(b.open_plans || []).map((e) => ({ ...e, kind: "plan" })),
    ...(b.recent_decisions || []).map((e) => ({ ...e, kind: "decision" })), ...(b.recent_done || []).map((e) => ({ ...e, kind: "done" }))]
    .sort((x, y) => String(y.created_at).localeCompare(String(x.created_at)));
  return card("Journal", h("p", { class: "muted small" }, "What Roundtable wrote about this project in the hub."),
    all.length ? h("ul", { class: "entries" }, all.map((e) => entryRow(b.agent || seat.id, e, e.status === "open"))) : empty("Nothing written about it yet."));
}
