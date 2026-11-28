// The answer card: one shape for every question, choice, idea, look, plan approval, failed task and money stop.
// The recommended answer comes first and is marked; "Other…" opens a box for your own words. Number keys pick,
// Enter sends. An option that spends past the estimate or can't be undone asks "Are you sure?" on the card first.
// A command waiting for "Ask me first" shows the whole command (a long one folded, with Show all).
// A question may carry a timer (asktimer.py): the card says what happens when it runs out, and typing an
// answer holds the clock while you write.
import { h, fill, get, post, toast, projectName, q } from "./core.js";

const AT = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
const RUNS_OUT = { recommended: "it takes the recommended answer", nothing: "it keeps waiting and nothing is done", pause: "the project waits for your answer" };
const RAN_OUT = { recommended: (l) => `it took the recommended answer${l ? ` (${l})` : ""}. You can still change it`, nothing: () => "nothing was done. It still waits for you",
  pause: () => "the project is paused until you answer" };

// The timer's line on a card ("" for none).
export function timerLine(ask) {
  if (ask.kind === "command") return null;  // its own line (commandBlock)
  if (ask.timed_out) {
    const t = ask.timed_out, words = (RAN_OUT[t.did] || RAN_OUT.nothing)(t.label);
    return h("p", { class: "muted small ask-timer", title: "This question had a time limit" }, `The time ran out${AT(t.at) ? ` at ${AT(t.at)}` : ""}: ${words}.`);
  }
  if (!ask.expires_at || !RUNS_OUT[ask.on_expire]) return null;
  return h("p", { class: "muted small ask-timer", title: "Typing an answer stops the clock while you write" },
    ask.held ? "The clock is stopped while you write." : `If nobody answers by ${AT(ask.expires_at)}, ${RUNS_OUT[ask.on_expire]}.`);
}

// Tell the timer the owner is typing (at most every 30 seconds).
function holdWhileTyping(ask) {
  let last = 0;
  return () => {
    if (!ask.expires_at || !ask.path || Date.now() - last < 30000) return;
    last = Date.now();
    post("/api/asktimer", { path: ask.path, id: ask.id, hold: true }).catch(() => {});
  };
}

const KIND_WORDS = { decision: "Choice", question: "Question", look: "Look", profile: "Models", idea: "Idea", approve: "Plan",
  failed: "Stopped", money: "Money", command: "Command", wizard: "", kind: "Kind" };
const HINTS = { decision: "Tap the choice you want.", question: "Tap an answer, or Other… to type your own.", idea: "Add it to the plan, or leave it out.",
  look: "Tap the look you like.", approve: "Nothing is built until you say so.", failed: "Try it again, or carry on without it.",
  money: "Nothing more is spent until you say so.", profile: "Which set of models does the work.",
  command: "It waits for your tap. Read the command first." };

// The command on a command card: all of it, or its first lines with Show all for a long one.
export function commandBlock(ask) {
  const full = String(ask.command || "");
  const pre = h("pre", { class: "log short ask-cmd", "aria-label": "The command" }, ask.folded ? ask.preview || full.slice(0, 1200) : full);
  const until = ask.expires_at ? new Date(ask.expires_at) : null;
  const foot = h("p", { class: "muted small" },
    until && !isNaN(until) ? `If nobody answers by ${until.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}, it doesn't run.` : "");
  if (!ask.folded) return h("div", { class: "ask-command" }, pre, foot);
  let open = false;
  const btn = h("button", { class: "link-btn", type: "button", title: "Show the whole command before you answer",
    onclick: () => { open = !open; pre.textContent = open ? full : ask.preview || full.slice(0, 1200); btn.textContent = open ? "Show less" : `Show all (${ask.lines || 1} lines)`; } },
  `Show all (${ask.lines || 1} lines)`);
  return h("div", { class: "ask-command" }, pre, h("div", { class: "row" }, btn), foot);
}

// opts: {pictures: {id: src}, onSkip, compact, project, sendLabel, disabled, extra, hint}
export function askCard(ask, onAnswer, opts = {}) {
  const picked = new Set((ask.answer && ask.answer.chosen) || []);
  const textOnly = !(ask.options || []).length;
  const card = h("article", { class: "ask" + (opts.compact ? " compact" : "") + (ask.answer ? " answered" : ""), tabindex: "0", "data-ask": ask.id,
    "aria-label": ask.question });
  const other = h("textarea", { class: "grow", rows: ask.id === "idea" || ask.id === "like" ? 3 : 2, placeholder: ask.other_hint || "Type your own answer",
    "aria-label": ask.other_hint || "Your own answer" });
  if (ask.answer && ask.answer.other) other.value = ask.answer.other;
  other.addEventListener("input", holdWhileTyping(ask));
  const chosenNow = () => (ask.multi ? [...picked] : []);
  const otherRow = h("div", { class: "ask-other row" }, other,
    h("button", { class: "primary", type: "button", disabled: opts.disabled, onclick: () => send(chosenNow()) }, opts.sendLabel || "Send"));
  let busy = false;
  async function send(chosen, confirmed = false) {
    if (busy) return;
    const text = other.value.trim();
    if (!chosen.length && !text) { toast(textOnly ? "Type your answer first." : "Tap an answer, or type one.", true); showOther(true); return; }
    const sure = !confirmed && (ask.options || []).find((o) => chosen.includes(o.id) && o.confirm);
    if (sure) { fill(card, confirmParts(sure, () => send(chosen, true), draw)); card.focus(); return; }
    busy = true; card.classList.add("sending"); card.setAttribute("aria-busy", "true");
    try { await onAnswer({ chosen, other: text, confirmed }); }
    catch (e) { toast(e.message, true); }
    busy = false; card.classList.remove("sending"); card.removeAttribute("aria-busy");
  }
  const confirmParts = (opt, yes, no) => [
    h("div", { class: "ask-head" }, h("span", { class: "chip warn" }, "Check")),
    h("h3", { class: "ask-q" }, "Are you sure?"),
    h("p", { class: "ask-detail" }, opt.confirm),
    h("div", { class: "ask-opts" },
      h("button", { class: "ask-opt rec", type: "button", onclick: yes }, h("b", {}, h("kbd", {}, 1), "Yes, go ahead"), h("span", {}, opt.label)),
      h("button", { class: "ask-opt", type: "button", onclick: no }, h("b", {}, h("kbd", {}, 2), "No, go back"), h("span", {}, "Nothing is changed.")))];
  const pick = (o) => {
    if (!ask.multi) return send([o.id]);
    picked.has(o.id) ? picked.delete(o.id) : picked.add(o.id);
    draw(); card.focus();
  };
  function showOther(open) { otherRow.hidden = !open; if (open) setTimeout(() => other.focus(), 0); }
  other.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(chosenNow()); }
    if (ev.key === "Escape" && !textOnly) { other.value = ""; showOther(false); card.focus(); }
  });
  card.addEventListener("keydown", (ev) => {
    if (ev.target !== card || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const btns = [...card.querySelectorAll(".ask-opt")], n = Number(ev.key);
    if (n >= 1 && n <= btns.length) { ev.preventDefault(); btns[n - 1].click(); }
    else if (ev.key === "Enter" && ask.multi) { ev.preventDefault(); send([...picked]); }
  });
  function draw() {
    const rec = ask.recommended, options = ask.options || [];
    const optButtons = options.map((o, i) => {
      const on = picked.has(o.id);
      return h("button", { class: "ask-opt" + (on ? " on" : "") + (o.id === rec ? " rec" : "") + (o.disabled ? " off" : ""), type: "button", disabled: opts.disabled || o.disabled,
        "aria-pressed": ask.multi || ask.answer ? String(on) : null, title: o.tip || (o.confirm ? "You'll be asked to make sure first" : `Press ${i + 1}`), onclick: () => pick(o) },
      o.picture && opts.pictures && opts.pictures[o.picture] ? h("img", { class: "ask-pic", src: opts.pictures[o.picture], alt: o.label }) : null,
      h("b", {}, ask.multi ? h("i", { class: "tick" + (on ? " on" : "") }) : h("kbd", {}, i + 1), h("span", { class: "grow" }, o.label),
        o.disabled ? h("span", { class: "muted small" }, o.group || "Coming") : null,
        o.id === rec ? h("span", { class: "rec-mark", title: "What the harness would pick" }, "Recommended") : null),
      o.description ? h("span", {}, o.description) : null);
    });
    const otherBtn = ask.allow_other !== false && !textOnly ? h("button", { class: "ask-opt other", type: "button", disabled: opts.disabled,
      title: `Type your own answer (press ${options.length + 1})`, onclick: () => showOther(otherRow.hidden) },
    h("b", {}, h("kbd", {}, options.length + 1), "Other…"), h("span", {}, ask.other_hint || "Type your own answer")) : null;
    fill(card,
      h("div", { class: "ask-head" },
        KIND_WORDS[ask.kind] !== "" ? h("span", { class: "chip" }, ask.header || KIND_WORDS[ask.kind] || "Question") : null,
        opts.project ? h("span", { class: "ask-proj" }, opts.project) : null,
        ask.answer ? h("span", { class: "pill good" }, "Answered") : null),
      h("h3", { class: "ask-q" }, ask.question),
      ask.detail ? h("p", { class: "ask-detail" }, ask.detail) : null,
      ask.kind === "command" ? commandBlock(ask) : null,
      ask.engine && ask.path ? engineOffer(ask) : null,
      ask.more ? h("details", { class: "ask-more" }, h("summary", { title: "The exact steps it would run" }, "More"), h("pre", { class: "small" }, ask.more)) : null,
      timerLine(ask),
      opts.hint !== false && HINTS[ask.kind] ? h("p", { class: "ask-hint" }, HINTS[ask.kind]) : null,
      textOnly ? null : h("div", { class: "ask-opts" + (Object.keys(opts.pictures || {}).length ? " pics" : "") }, optButtons, otherBtn),
      ask.allow_other !== false ? otherRow : null,
      h("div", { class: "ask-foot" },
        ask.multi ? h("button", { class: "primary", type: "button", disabled: opts.disabled, onclick: () => send([...picked]) }, "Done") : null,
        opts.onSkip ? h("button", { class: "link-btn", type: "button", title: "Leave this for later. It comes back if things change.", onclick: opts.onSkip }, "Not now") : null,
        opts.extra || null));
    otherRow.hidden = !(textOnly || other.value);
  }
  draw();
  return card;
}

// A task stopped because a coding helper isn't installed: install it (only a checked download) and carry on.
function engineOffer(ask) {
  const box = h("div", { class: "ask-engine" });
  get(`/api/engines/offer?${q({ engine: ask.engine })}`).then((o) => {
    fill(box, h("p", { class: "small" }, o.words),
      o.auto ? h("button", { class: "primary", type: "button", title: o.checked || "",
        onclick: async (ev) => {
          ev.currentTarget.disabled = true;
          try { await post("/api/engines/install", { engine: ask.engine, path: ask.path, task: (ask.source || {}).task || "" }); toast("Installing: it carries on by itself when it's done (Activity → Background work)."); }
          catch (e) { toast(e.message, true); ev.currentTarget.disabled = false; }
        } }, "Install it and carry on") : null);
  }).catch(() => {});
  return box;
}

// Answer a card of a project on this computer; a long step it starts (a run, a plan update) comes back as a job.
export async function answerHere(ask, a) {
  const r = await post("/api/asks", { path: ask.path, id: ask.id, stamp: ask.stamp, ...a });
  toast(r.reply || "Done");
  return r;
}
export async function skipHere(ask) {
  const r = await post("/api/asks", { path: ask.path, id: ask.id, stamp: ask.stamp, skip: true });
  toast("Left for later");
  return r;
}
// Answer a card of a project another computer runs: it goes to that computer through the hub.
export async function answerHub(need, ask, a) {
  const r = await post("/api/hub/command", { agent: need.hub_agent, folder: need.project, action: "answer",
    fields: { id: ask.id, stamp: ask.stamp, chosen: a.chosen, other: a.other, confirmed: a.confirmed } });
  toast(r.reply || `Sent to ${projectName(need.project)}`);
  return r;
}
export async function hubCommand(seatOrNeed, action, fields = {}) {
  const r = await post("/api/hub/command", { agent: seatOrNeed.hub_agent, folder: seatOrNeed.project || seatOrNeed.id, action, fields });
  toast(r.reply || "Sent");
  return r;
}
