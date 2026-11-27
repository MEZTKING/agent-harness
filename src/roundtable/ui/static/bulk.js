// Answer these: when three or more cards wait in Needs you, tick the ones to settle and give each its recommended
// answer in one go. A card whose recommended answer spends money or can't be undone, and every command, is never in
// the tick-all: it is answered on its own card. Each answer goes with the stamp of the question the owner saw, so a
// question that changed meanwhile is refused, as when it is answered alone.
import { h, fill, post, toast, plural, projectName } from "./core.js";
import { answerHub } from "./asks.js";

bulkStyles();

// Why this card must be answered alone ("" when the recommended answer can be given with the others).
export function aloneWhy(ask) {
  if (!ask) return "It isn't a question with answers to pick.";
  if (ask.kind === "command") return "A command is always answered on its own.";
  const opt = (ask.options || []).find((o) => o.id === ask.recommended);
  if (!ask.recommended || !opt) return "It has no recommended answer.";
  if (opt.confirm) return "Its recommended answer spends money or can't be undone.";
  return "";
}

// items: Needs you's gathered items ({project, kind: "local-ask" | "hub-ask", ask, need}); done(): redraw after.
export function bulkBar(items, done) {
  const cards = (items || []).filter((i) => i.ask && (i.kind === "local-ask" || i.kind === "hub-ask") && !i.busy);
  if (cards.length < 3) return null;
  const ok = cards.filter((i) => !aloneWhy(i.ask)), alone = cards.filter((i) => aloneWhy(i.ask));
  if (!ok.length) return null;
  const ticks = new Map();
  const count = h("span", { class: "muted small" });
  const go = h("button", { class: "primary", type: "button", disabled: true,
    title: "Each ticked card gets the answer marked as recommended on it" }, "Use the recommended answer for the ticked ones");
  const recount = () => { const n = [...ticks.values()].filter((c) => c.checked).length; go.disabled = !n; count.textContent = n ? `${plural(n, "card")} ticked` : "Tick the cards to answer"; };
  const row = (it) => {
    const box = h("input", { type: "checkbox", "aria-label": `Answer ${it.ask.question}`, onchange: recount });
    ticks.set(it, box);
    const rec = (it.ask.options || []).find((o) => o.id === it.ask.recommended);
    return h("label", { class: "bk-row" }, box, h("span", {}, h("b", {}, projectName(it.project)), " · ", it.ask.question,
      h("span", { class: "muted small" }, ` → ${rec ? rec.label : ""}`)));
  };
  const all = h("button", { class: "small", type: "button", title: "Tick every card that can take its recommended answer" }, "Tick all");
  all.onclick = () => { ticks.forEach((c) => { c.checked = true; }); recount(); };
  const list = h("div", { class: "bk-list" }, ok.map(row),
    alone.length ? h("p", { class: "muted small bk-alone" }, `Answered on their own card: ${alone.map((i) => `${projectName(i.project)} (${aloneWhy(i.ask).toLowerCase().replace(/\.$/, "")})`).join("; ")}.`) : null);
  go.onclick = async () => {
    const picked = [...ticks.entries()].filter(([, c]) => c.checked).map(([it]) => it);
    go.disabled = true;
    try {
      const local = picked.filter((i) => i.kind === "local-ask"), hub = picked.filter((i) => i.kind === "hub-ask");
      const words = [];
      if (local.length) {
        const r = await post("/api/board/answer-several", { items: local.map((i) => ({ path: i.ask.path, id: i.ask.id, stamp: i.ask.stamp })) });
        words.push(r.reply);
        for (const l of r.left || []) toast(`${l.id}: ${l.why}`, true);
      }
      for (const i of hub) {
        try { await answerHub(i.need, i.ask, { chosen: [i.ask.recommended] }); } catch (e) { toast(e.message, true); }
      }
      if (hub.length) words.push(`${plural(hub.length, "answer")} sent to the other computer`);
      if (words.length) toast(words.join(". "));
    } catch (e) { toast(e.message, true); }
    if (done) await done();
  };
  recount();
  return h("details", { class: "card fold bk" }, h("summary", { title: "Settle several cards at once with their recommended answers" },
    `Answer these (${ok.length} of ${cards.length} can take the recommended answer)`),
    h("div", { class: "row bk-top" }, all, count), list, h("div", { class: "row" }, go));
}

function bulkStyles() {
  if (typeof document === "undefined" || document.getElementById("bk-style")) return;
  document.head.append(h("style", { id: "bk-style" }, `
.bk { margin-bottom: 12px; } .bk-top { gap: 10px; align-items: center; margin: 6px 0; }
.bk-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0 10px; }
.bk-row { display: flex; gap: 8px; align-items: baseline; padding: 4px 6px; border-radius: var(--radius-small); }
.bk-row:hover { background: var(--color-sunken); }
.bk-alone { margin: 6px 0 0; }
`));
}
