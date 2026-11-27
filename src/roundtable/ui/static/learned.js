// What the harness learned (ui/learnedapi.py, improve/ledger.py): one plain line per change with an Undo, before
// and after behind More; what waits for the owner; what it can never change (folded). Short first.
import { h, fill, get, post, card, empty, act, dialog, ago, has } from "./core.js";

learnedStyles();

const STATE = { on: ["In use", "good"], watching: ["Being watched", "info"], undone: ["Undone", "warn"], put_back: ["Put back", "good"] };

// The Learning tab's body for the Models page. `suggestions` (optional): a node or an async function giving one,
// the harness's open suggestions, shown inside "Waiting for you".
export async function learnedTab({ suggestions } = {}) {
  if (!(await has("/api/learned"))) return empty("This computer's copy of the app can't show what it learned yet.");
  const box = h("div", { class: "stack ln-tab" });
  const load = async () => {
    let v;
    try { v = await get("/api/learned"); }
    catch (e) { fill(box, empty("Couldn't read what the harness learned. Try again in a moment.")); return; }
    const extra = typeof suggestions === "function" ? await suggestions(load) : suggestions || null;
    fill(box,
      h("p", { class: "muted small ln-wallet", title: "Learning by itself only spends this weekly allowance" }, (v.wallet || {}).words || ""),
      learnedPart(v, load),
      waitingPart(v, load, extra),
      neverPart(v));
  };
  await load();
  return box;
}

function learnedPart(v, reload) {
  const lines = v.lines || [];
  return card("What it learned", lines.length
    ? h("ul", { class: "ln-lines" }, lines.map((l) => lineRow(l, reload)))
    : h("p", { class: "muted" }, "Nothing yet: it works exactly as you set it."),
    (v.not_here || []).length ? h("details", { class: "ln-more" }, h("summary", { title: "Changes from your other machines that need a model this one doesn't have" }, `Not usable here (${v.not_here.length})`),
      h("ul", { class: "ln-plain" }, v.not_here.map((x) => h("li", {}, x.words, h("span", { class: "muted small" }, ` · ${x.why}`))))) : null);
}

function lineRow(l, reload) {
  const [word, tone] = STATE[l.state] || [l.state, ""];
  return h("li", { class: "ln-line" + (l.state === "undone" ? " ln-out" : "") },
    h("div", { class: "row" },
      h("span", { class: "grow" }, l.words),
      h("span", { class: "pill " + tone, title: l.state === "watching" ? "The next tasks are compared with before; a clear drop undoes it by itself" : "" }, word),
      h("span", { class: "muted small", title: "Who made this change" }, `${l.by} · ${ago(l.when)}`),
      l.can_undo ? h("button", { class: "small danger", title: "Take this one change out; everything else stays", onclick: async (ev) => {
        if (await dialog({ title: "Undo this change?", text: "Only this change is taken out. You can put it back later.", yes: "Undo", danger: true }))
          act(ev.currentTarget, () => post("/api/learned", { action: "undo", id: l.id }), "Undone", reload);
      } }, "Undo") : null,
      l.can_put_back ? h("button", { class: "small", title: "Use this change again; it is watched again", onclick: (ev) =>
        act(ev.currentTarget, () => post("/api/learned", { action: "put_back", id: l.id }), "Put back", reload) }, "Put back") : null),
    beforeAfter(l));
}

function beforeAfter(l) {
  const ba = l.before_after;
  if (!ba) return null;
  let body = null;
  if (ba.diff) {
    body = h("div", { class: "ln-diff" }, ba.diff.filter((d) => d.op !== "same").slice(0, 80).map((d) =>
      h("div", { class: "ln-" + d.op, title: d.op === "new" ? "Added" : "Taken out" }, (d.op === "new" ? "+ " : "– ") + d.text)));
  } else if (ba.before || ba.after) {
    const words = (x) => Array.isArray(x) ? x.join(", then ") : Object.entries(x || {}).map(([k, val]) => `${k} ${val}`).join(", ");
    body = h("p", { class: "small" }, ba.before && ba.before.length ? `Before: ${words(ba.before)}. ` : "", `Now: ${words(ba.after)}.`);
  }
  return body ? h("details", { class: "ln-more" }, h("summary", { title: "What it was and what it is now" }, "More"), body) : null;
}

function waitingPart(v, reload, extra) {
  const items = v.waiting || [];
  const rows = items.map((w) => h("li", { class: "ln-line" },
    h("div", { class: "row" },
      h("span", { class: "grow" }, w.words, w.from ? h("span", { class: "muted small" }, ` · from ${w.from}`) : null),
      w.can_apply ? h("button", { class: "small primary", title: "Use this change", onclick: (ev) =>
        act(ev.currentTarget, () => post("/api/learned", { action: "apply", id: w.id }), "In use", reload) }, "Use it") : null,
      w.can_apply ? h("button", { class: "small", title: "Don't use this change", onclick: (ev) =>
        act(ev.currentTarget, () => post("/api/learned", { action: "turn_down", id: w.id }), "Turned down", reload) }, "Turn down") : null),
    h("p", { class: "muted small" }, w.why)));
  return card(`Waiting for you${items.length ? ` (${items.length})` : ""}`,
    rows.length ? h("ul", { class: "ln-lines" }, rows) : (extra ? null : h("p", { class: "muted" }, "Nothing waits for you.")),
    extra);
}

function neverPart(v) {
  const never = v.never || [];
  if (!never.length) return null;
  return h("details", { class: "card fold" }, h("summary", { title: "The harness can never change these by itself" }, "What it can never change"),
    h("ul", { class: "ln-plain" }, never.map((x) => h("li", {}, x))));
}

function learnedStyles() {
  if (typeof document === "undefined" || document.getElementById("ln-style")) return;
  document.head.append(h("style", { id: "ln-style" }, `
.ln-lines { list-style: none; margin: 8px 0; padding: 0; display: grid; gap: 6px; }
.ln-line { padding: 6px 10px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.ln-out > .row > .grow { color: var(--color-muted); }
.ln-more { margin-top: 6px; }
.ln-more > summary { cursor: pointer; color: var(--color-muted); }
.ln-plain { margin: 6px 0; padding-left: 18px; }
.ln-diff { font-family: var(--font-mono); font-size: 0.85em; max-height: 320px; overflow: auto; margin-top: 6px; }
.ln-new { color: var(--color-good); }
.ln-gone { color: var(--color-warn); }
.ln-wallet { margin: 0 0 4px; }
`));
}
