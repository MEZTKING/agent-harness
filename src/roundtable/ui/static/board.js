// The board: every task as a card in a column (To do, Building, Waiting for you, Stuck, Done, and Left out when
// there are any), each with its id (like T12), its short title and one line; who built and checked it is under
// "More". A card moves only through the few moves the harness allows (boardstage.py): the buttons on it are the
// moves it has. Also the Hall's helpers for the state word (working, resting, waiting, gone quiet) and the order
// of projects by hand, kept on this computer.
import { h, fill, get, post, toast, dialog, every, card, empty, q, plural, jobName, modelName } from "./core.js";
import { openFocus } from "./focus.js";

boardStyles();

export async function boardTab(seat, now) {
  const box = h("div", { class: "bd" });
  if (!seat.path) {
    return fill(box, empty("This project is built on another computer: its board shows on that computer."));
  }
  const path = seat.path;
  let sig = "";
  const draw = async () => {
    let d;
    try { d = await get(`/api/board?${q({ path })}`); } catch (e) { fill(box, empty(e.message)); return; }
    const s = JSON.stringify(d);
    if (s === sig) return;
    sig = s;
    fill(box, boardView(seat, d, () => { sig = ""; return draw(); }));
  };
  return every(box, draw, () => (now().status === "running" ? 3000 : 15000));
}

function boardView(seat, d, redraw) {
  const total = d.columns.reduce((n, c) => n + c.cards.length, 0);
  const head = h("p", { class: "bd-sub muted" }, total ? `${plural(total, "task")}.` : "No tasks yet: they show here once the plan is made.",
    d.state ? h("span", { class: `bd-state ${d.state.state}`, title: d.state.line || "" }, " ", d.state.word) : null,
    d.why_not ? h("span", { class: "warn" }, " ", d.why_not) : d.busy ? h("span", {}, " A run is going: only the order of To do can change until it stops.") : null);
  return [head,
    h("div", { class: "bd-cols", role: "list" }, d.columns.map((c) => h("section", { class: `bd-col ${c.id}`, role: "listitem", "aria-label": c.title },
      h("h3", { class: "bd-col-head" }, c.title, h("span", { class: "count" }, c.cards.length)),
      c.cards.length ? c.cards.map((t) => taskCard(seat, t, redraw)) : h("p", { class: "muted small bd-none" }, "Nothing here")))),
    d.earlier && d.earlier.count ? h("details", { class: "card fold bd-earlier" },
      h("summary", { title: "Finished tasks of earlier goals, put away so the board stays short. Nothing was deleted." }, d.earlier.title),
      h("ul", { class: "bd-earlier-list" }, d.earlier.cards.map((t) => h("li", {}, h("b", { class: "bd-num" }, t.number), " ", t.title,
        h("span", { class: "muted small" }, ` · goal ${t.goal} · ${t.line}`))))) : null];
}

function taskCard(seat, t, redraw) {
  const m = t.more || {};
  const more = [m.role ? `Job: ${jobName(m.role)}` : "", m.built_by ? `Built by ${modelName(m.built_by)}` : "",
    m.checked_by ? `Checked by ${modelName(m.checked_by)}` : "", m.tries ? `${plural(m.tries, "try", "tries")}` : "",
    m.after && m.after.length ? `Needs ${m.after.join(", ")} first` : ""].filter(Boolean);
  return h("article", { class: `bd-card ${t.column}`, "data-task": t.id },
    h("div", { class: "bd-card-head" }, h("b", { class: "bd-num", title: "The task's number" }, t.number), h("span", { class: "bd-title" }, t.title)),
    h("p", { class: "bd-line small muted", title: t.line }, t.line),
    h("div", { class: "bd-moves" },
      (t.moves || []).map((mv) => h("button", { class: "small", type: "button", title: MOVE_TIPS[mv.to] || "", onclick: (ev) => doMove(ev.currentTarget, seat, t, mv, redraw) }, mv.label)),
      h("button", { class: "small", type: "button", title: "See this one task full screen: its steps, what it's running and the files it changed",
        onclick: () => openFocus(seat, t.id) }, "Focus")),
    more.length ? h("details", { class: "bd-more" }, h("summary", { title: "Who built and checked it" }, "More"), h("p", { class: "small muted" }, more.join(" · "))) : null);
}

const MOVE_TIPS = {
  up: "Build this one earlier (among the tasks that are ready)",
  down: "Build this one later",
  left_out: "Leave it out: the tasks after it carry on without it. You can put it back",
  todo: "Put it back in To do: it's built when the project next runs",
  done: "Keep the work as it is in the files and count it as done",
};

async function doMove(btn, seat, t, mv, redraw) {
  const send = (confirmed) => post("/api/board/move", { path: seat.path, task: t.id, to: mv.to, confirmed });
  btn.disabled = true;
  try {
    let r;
    try { r = await send(false); } catch (e) {
      if (!String(e.message).startsWith("Are you sure?")) throw e;
      const yes = await dialog({ title: `${t.number} ${t.title}`, text: e.message.replace(/^Are you sure\?\s*/, ""), yes: mv.label });
      if (!yes) return;
      r = await send(true);
    }
    toast(r.reply || "Moved");
    await redraw();
  } catch (e) { toast(e.message, true); }
  finally { if (btn.isConnected) btn.disabled = false; }
}

// ---------- the Hall: the state word, and the order of projects by hand ----------
let STATES = null;
export async function loadStates() {  // {states: {path: {state, word, line}}, order: [seat ids]}
  try { STATES = await get("/api/board/states"); } catch { STATES = STATES || { states: {}, order: [] }; }
  return STATES;
}
export function stateWord(seat) {  // "Working", "Resting", "Waiting for you", "Gone quiet" (or null)
  const st = STATES && seat.path ? STATES.states[seat.path] : null;
  return st ? h("span", { class: `bd-state ${st.state}`, title: st.line || "" }, st.word) : null;
}
// The owner's order, with what needs them still first (needsFirst(seat) says which).
export function orderSeats(seats, needsFirst) {
  const order = (STATES && STATES.order) || [];
  const rank = new Map(order.map((id, i) => [id, i]));
  return [...seats].map((s, i) => [s, i]).sort(([a, i], [b, j]) => {
    const na = needsFirst(a) ? 0 : 1, nb = needsFirst(b) ? 0 : 1;
    if (na !== nb) return na - nb;
    const ra = rank.has(a.id) ? rank.get(a.id) : order.length + i, rb = rank.has(b.id) ? rank.get(b.id) : order.length + j;
    return ra - rb;
  }).map(([s]) => s);
}
export function orderButtons(seat, shown, after) {  // up and down on one project; shown: the seats in their order now
  const move = async (ev, way) => {
    ev.preventDefault(); ev.stopPropagation();
    const ids = shown.map((s) => s.id), i = ids.indexOf(seat.id), j = i + way;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { STATES = { ...(STATES || { states: {} }), order: (await post("/api/board/order", { order: ids })).order }; if (after) await after(); }
    catch (e) { toast(e.message, true); }
  };
  return h("span", { class: "bd-order" },
    h("button", { class: "small", type: "button", title: "Show this project higher on Home (what needs you still comes first)", "aria-label": `Move ${seat.name} up`, onclick: (ev) => move(ev, -1) }, "↑"),
    h("button", { class: "small", type: "button", title: "Show this project lower on Home", "aria-label": `Move ${seat.name} down`, onclick: (ev) => move(ev, 1) }, "↓"));
}

function boardStyles() {
  if (typeof document === "undefined" || document.getElementById("bd-style")) return;
  document.head.append(h("style", { id: "bd-style" }, `
.bd-sub { margin: 0 0 10px; }
.bd-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; align-items: start; }
.bd-col { background: var(--color-sunken); border: 1px solid var(--color-line); border-radius: var(--radius); padding: 8px; min-width: 0; }
.bd-col-head { display: flex; align-items: center; gap: 6px; margin: 2px 4px 8px; font: 700 14px/1.2 var(--font-display); }
.bd-col-head .count { margin-left: auto; color: var(--color-muted); font-weight: 600; }
.bd-col.waiting .bd-col-head { color: var(--color-flare); } .bd-col.stuck .bd-col-head { color: var(--color-bad); } .bd-col.done .bd-col-head { color: var(--color-good); }
.bd-card { background: var(--color-surface); border: 1px solid var(--color-line); border-radius: var(--radius-small); padding: 8px 10px; margin-bottom: 8px; }
.bd-card.waiting { border-color: var(--color-flare); } .bd-card.stuck { border-color: var(--color-bad); } .bd-card.building { border-color: var(--color-accent); }
.bd-card-head { display: flex; gap: 6px; align-items: baseline; min-width: 0; }
.bd-num { font: 700 12.5px/1.2 var(--font-mono); color: var(--color-accent); flex: none; }
.bd-title { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bd-line { margin: 4px 0 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bd-moves { display: flex; flex-wrap: wrap; gap: 4px; }
.bd-more summary { cursor: pointer; font-size: 12.5px; color: var(--color-muted); margin-top: 4px; }
.bd-more p { margin: 4px 0 0; }
.bd-none { margin: 4px; }
.bd-earlier { margin-top: 12px; } .bd-earlier-list { list-style: none; padding-left: 4px; margin: 6px 0; } .bd-earlier-list li { margin: 3px 0; }
.bd-state { font-weight: 700; } .bd-state.working { color: var(--color-good); } .bd-state.waiting { color: var(--color-flare); }
.bd-state.quiet { color: var(--color-warn); } .bd-state.resting { color: var(--color-muted); }
.bd-order { display: inline-flex; gap: 2px; } .bd-order button { min-height: 24px; padding: 0 7px; }
`));
}
