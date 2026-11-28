// A card in the chat (1.5.0): what the chat offers to do, with its price and two buttons. Short first: a title,
// one sentence, the price; the rest behind "More". The card's title, sentence, price and command are made by the app
// from the parsed command (chat.py card_for), never from the model's words, and a tap is the only thing that runs
// it: every spend or change goes through POST /api/chats/tap/pc, and what can't be undone asks "Are you sure?" first.
// States: open (the buttons), queued (waiting for a machine), running, done, cancelled.
import { h, fill, post, dialog, toast, money } from "./core.js";
import { t, keep } from "./words.js";

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "chatcard" }, `
.cc { display: flex; flex-direction: column; gap: 6px; margin-block-start: 10px; padding-block: 12px; padding-inline: 14px;
  border: 1px solid var(--color-line-strong); border-radius: var(--radius); background: var(--color-raised); color: var(--color-text); max-inline-size: 460px; }
.cc-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }
.cc-title { font-weight: 700; font-size: 14.5px; }
.cc-price { font-size: 13px; color: var(--color-muted); font-variant-numeric: tabular-nums; }
.cc-line { margin: 0; font-size: 13.5px; color: var(--color-text); }
.cc-acts { display: flex; flex-wrap: wrap; gap: 8px; margin-block-start: 4px; }
.cc-state { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-muted); }
.cc-state .cc-dot { inline-size: 8px; block-size: 8px; border-radius: 50%; background: var(--color-line-strong); flex: none; }
.cc.queued { border-style: dashed; }
.cc.queued .cc-dot { background: var(--color-warn); }
.cc.running .cc-dot { background: var(--color-accent); }
.cc.done .cc-dot { background: var(--color-good); }
.cc.cancelled { opacity: .82; }
.cc-more > summary { cursor: pointer; font-size: 12.5px; color: var(--color-muted); inline-size: fit-content; }
.cc-more p { margin-block: 4px 0; font-size: 12.5px; color: var(--color-muted); white-space: pre-wrap; overflow-wrap: anywhere; }
.cc-more code { font: 12px/1.4 var(--font-mono); color: var(--color-muted); }
.cc-note { margin: 0; font-size: 12.5px; color: var(--color-muted); }
@media (prefers-reduced-motion: no-preference) { .cc.running .cc-dot { animation: cc-pulse 1.4s ease-in-out infinite; } }
@keyframes cc-pulse { 50% { opacity: .35; } }
`));
}

// Buttons that open a part of the app instead of being sent: the keys, This phone's set-up, the money.
const OPENS = { add_key: "#/settings/keys", change_key: "#/settings/keys", setup_phone: "#/settings/phone", top_up: "#/settings/spending" };

/** Money in plain words: "0.1¢" under a cent, "$1.40" from a cent up, "" for nothing. */
export function cents(usd) {
  const n = Number(usd);
  if (!isFinite(n) || n <= 0) return "";
  if (n < 0.0005) return t("under 0.1¢");
  if (n < 0.01) return t("{n}¢", { n: (n * 100).toFixed(1).replace(/\.0$/, "") });
  return money(n);
}

/** The price words: "About $1.40 · stops at $2.00", "Free", or "" when the card has no price. */
export function priceWords(card) {
  const p = card.price_usd, cap = card.cap_usd;
  const parts = [];
  if (typeof p === "number") parts.push(p > 0 ? t("About {usd}", { usd: cents(p) }) : t("Free"));
  if (typeof cap === "number" && cap > 0) parts.push(t("stops at {usd}", { usd: cents(cap) }));
  return parts.join(" · ");
}

const STATE_WORDS = { queued: "Queued", running: "Working on it…", done: "Done", cancelled: "Not done" };

/** One card. opts: chat (its id), onLine(line) – the card's line as it is after a tap, trusted (false: the card was
 *  made on another device, so it shows without its buttons), plain (the app's own notice: buttons only). */
export function chatCard(card, opts = {}) {
  style();
  const node = h("article", { class: "cc " + (card.state || "open"), "aria-label": card.title ? keep(card.title) : t("What it offers to do") });
  draw(node, card, opts);
  return node;
}

function draw(node, card, opts) {
  node.className = "cc " + (card.state || "open") + (opts.plain ? " plain" : "");
  const price = priceWords(card);
  const head = card.title || price ? h("div", { class: "cc-head" },
    card.title ? h("span", { class: "cc-title" }, keep(card.title)) : null,
    price ? h("span", { class: "cc-price", title: t("What it is likely to cost, and where it stops whatever happens") }, keep(price)) : null) : null;
  const line = card.line && !opts.plain ? h("p", { class: "cc-line" }, keep(card.line)) : null;
  const buttons = (card.buttons || []).filter((b) => b && b.id);
  const acts = opts.trusted === false
    ? h("p", { class: "cc-note" }, t("This was offered on another device. Ask again here to do it from this computer."))
    : buttons.length && (card.state === "open" || card.state === "queued" || !card.state)
      ? h("div", { class: "cc-acts" }, buttons.map((b) => button(node, card, b, opts)))
      : null;
  const state = card.state && card.state !== "open"
    ? h("div", { class: "cc-state", role: "status" }, h("i", { class: "cc-dot", "aria-hidden": "true" }),
      card.state === "queued" && card.queued_for ? t("Queued for {who}", { who: card.queued_for }) : t(STATE_WORDS[card.state] || "Done"))
    : null;
  const more = card.more || card.command
    ? h("details", { class: "cc-more" }, h("summary", { title: t("What exactly it will do") }, t("More")),
      card.more ? h("p", { raw: true }, card.more) : null,
      card.command ? h("p", {}, t("The command: "), h("code", { raw: true }, card.command)) : null)
    : null;
  fill(node, head, line, state, acts, opts.plain ? null : more);
}

function button(node, card, b, opts) {
  const opens = OPENS[b.id];
  const tip = { do: card.confirm ? t("It can't be undone, so it asks you first") : t("Do it now"), not_now: t("Nothing is done; the card stays here"),
    cancel: t("Take it off the queue: nothing is done"), here: t("Do it on this device instead of waiting"),
    raise_today: t("Let the chat spend more today; it goes back tomorrow") }[b.id] || "";
  return h("button", { type: "button", class: "small" + (b.primary ? " primary" : ""), title: tip,
    onclick: async (ev) => {
      if (opens) { location.hash = opens; return; }
      await tap(ev.currentTarget, node, card, b, opts);
    } }, keep(b.words));
}

async function tap(btn, node, card, b, opts) {
  // what can't be undone asks first, as its button elsewhere would
  if (b.id === "do" && card.confirm) {
    const yes = await dialog({ title: t("Are you sure?"), text: keep(card.confirm), yes: t("Yes, do it"), no: t("No, go back"), danger: true });
    if (!yes) return;
  }
  if (b.id === "raise_today") {
    const yes = await dialog({ title: t("Raise today's chat allowance?"), text: t("The chat may spend more today, on every device together. It goes back to the usual limit tomorrow."),
      yes: t("Raise it for today"), no: t("Not now") });
    if (!yes) return;
  }
  const spends = b.id === "do" || b.id === "here" || b.id === "raise_today";
  for (const x of node.querySelectorAll("button")) x.disabled = true;
  try {
    let r = await post("/api/chats/tap/pc", { chat: opts.chat, card: card.id, button: b.id, confirmed: spends });
    if (r && r.confirm) {  // the server asks once more (a price that moved, something that can't be undone)
      const yes = await dialog({ title: t("Are you sure?"), text: keep(r.confirm), yes: t("Yes, do it"), no: t("No, go back") });
      if (!yes) { for (const x of node.querySelectorAll("button")) x.disabled = false; return; }
      r = await post("/api/chats/tap/pc", { chat: opts.chat, card: card.id, button: b.id, confirmed: true });
    }
    const line = r && r.line;
    if (line && line.card) draw(node, line.card, opts);
    else draw(node, { ...card, state: b.id === "not_now" || b.id === "cancel" ? "cancelled" : "running" }, opts);
    if (line && opts.onLine) opts.onLine(line);
  } catch (e) {
    toast(e.message, true);
    for (const x of node.querySelectorAll("button")) if (x.isConnected) x.disabled = false;
  }
}
