// The answer card: one shape for every question, choice, idea, look, plan approval, failed task and money stop.
// The recommended answer comes first and is marked; "Other…" opens a box for your own words. Number keys pick,
// Enter sends. An option that spends past the estimate or can't be undone asks "Are you sure?" on the card first.
import { h, fill, post, toast, projectName } from "./core.js";

const KIND_WORDS = { decision: "Choice", question: "Question", look: "Look", profile: "Models", idea: "Idea", approve: "Plan",
  failed: "Stopped", money: "Money", wizard: "" };
const HINTS = { decision: "Tap the choice you want.", question: "Tap an answer, or Other… to type your own.", idea: "Add it to the plan, or leave it out.",
  look: "Tap the look you like.", approve: "Nothing is built until you say so.", failed: "Try it again, or carry on without it.",
  money: "Nothing more is spent until you say so.", profile: "Which set of models does the work." };

// opts: {pictures: {id: src}, onSkip, compact, project, sendLabel, disabled, extra, hint}
export function askCard(ask, onAnswer, opts = {}) {
  const picked = new Set((ask.answer && ask.answer.chosen) || []);
  const textOnly = !(ask.options || []).length;
  const card = h("article", { class: "ask" + (opts.compact ? " compact" : "") + (ask.answer ? " answered" : ""), tabindex: "0", "data-ask": ask.id,
    "aria-label": ask.question });
  const other = h("textarea", { class: "grow", rows: ask.id === "idea" || ask.id === "like" ? 3 : 2, placeholder: ask.other_hint || "Type your own answer",
    "aria-label": ask.other_hint || "Your own answer" });
  if (ask.answer && ask.answer.other) other.value = ask.answer.other;
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
      return h("button", { class: "ask-opt" + (on ? " on" : "") + (o.id === rec ? " rec" : ""), type: "button", disabled: opts.disabled,
        "aria-pressed": ask.multi || ask.answer ? String(on) : null, title: o.confirm ? "You'll be asked to make sure first" : `Press ${i + 1}`, onclick: () => pick(o) },
      o.picture && opts.pictures && opts.pictures[o.picture] ? h("img", { class: "ask-pic", src: opts.pictures[o.picture], alt: o.label }) : null,
      h("b", {}, ask.multi ? h("i", { class: "tick" + (on ? " on" : "") }) : h("kbd", {}, i + 1), h("span", { class: "grow" }, o.label),
        o.id === rec ? h("span", { class: "rec-mark", title: "What Roundtable would pick" }, "Recommended") : null),
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
