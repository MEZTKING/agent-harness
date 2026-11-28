// The chat (1.5.0), in place of Letters: one chat a project and one for everything, the Hall. Type, and the answer
// writes itself out; its thinking is folded behind "More"; under it, small and grey, which device answered and what
// it cost (the model behind "More"). When the chat offers to do something it ends with a card (chatcard.js): the
// price and two buttons, and only a tap runs it. Old letters sit folded at the top under "Earlier messages"; what
// agents say to each other shows as small grey lines that can be read but not answered.
// Server side: ui/chatsapi.py (GET /api/chats, /api/chats/read, POST /api/chats/say, /tap/pc, /stop, GET /file).
// The answer's words are asked for once a second while it writes (as stream.js does): no new socket.
// Safety: the model's words are drawn as text only. No picture or link from them is ever loaded or made clickable;
// the only pictures shown are the chat's own attached files, read through the app as data.
import { BRAND, h, fill, get, post, q, toast, dialog, every, patch, S, clock, readable, projectName, fileSize, enlarge } from "./core.js";
import { composer } from "./compose.js";
import { keepPlace } from "./stream.js";
import { chatCard, cents } from "./chatcard.js";
import { talkButton, speak, canSpeak } from "./voice.js";
import { t, keep, locale } from "./words.js";

export const HALL = "hall";
const SHOWN = 60;  // the newest lines drawn at first; older ones behind a button
const FAST = 1000, SLOW = 4000;

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "chat" }, `
.cv { display: flex; flex-direction: column; gap: 10px; block-size: clamp(440px, 72vh, 860px); min-inline-size: 0; }
.cv.short { block-size: clamp(380px, 56vh, 640px); }
.cv-log { flex: 1 1 auto; min-block-size: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 16px;
  padding-block: 8px 4px; padding-inline: 4px 10px; }
.cv-row { display: flex; flex-direction: column; gap: 4px; max-inline-size: min(760px, 88%); }
.cv-row.you { align-self: flex-end; align-items: flex-end; }
.cv-row.them { align-self: flex-start; }
.cv-who { font-size: 12px; font-weight: 700; color: var(--color-muted); padding-inline: 4px; }
.cv-bubble { padding-block: 11px; padding-inline: 16px; border-radius: var(--radius); font-size: 14.5px; line-height: 1.55;
  overflow-wrap: anywhere; color: var(--color-text); }
.cv-row.you .cv-bubble { background: var(--color-accent-soft); border-end-end-radius: var(--radius-small); white-space: pre-wrap; }
.cv-row.them .cv-bubble { background: var(--color-raised); border: 1px solid var(--color-line); border-end-start-radius: var(--radius-small); }
.cv-text p { margin-block: 0 8px; white-space: pre-wrap; }
.cv-text p:last-child { margin-block-end: 0; }
.cv-text ul, .cv-text ol { margin-block: 0 8px; padding-inline-start: 22px; }
.cv-text .cv-h { font-weight: 700; }
.cv-text code { font: 13px/1.4 var(--font-mono); padding-inline: 4px; border-radius: 4px; background: var(--color-sunken); color: var(--color-text); }
.cv-text pre { margin-block: 0 8px; padding-block: 8px; padding-inline: 10px; border-radius: var(--radius-small); background: var(--color-sunken);
  color: var(--color-text); font: 12.5px/1.45 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; max-block-size: 320px; overflow-y: auto; }
.cv-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; font-size: 12px; color: var(--color-muted); padding-inline: 4px; }
.cv-foot button { min-block-size: 22px; padding-block: 0; padding-inline: 6px; font-size: 12px; border: none; background: transparent; color: var(--color-muted); }
.cv-foot button:hover { color: var(--color-text); }
.cv-more > summary { cursor: pointer; inline-size: fit-content; font-size: 12px; color: var(--color-muted); }
.cv-more[open] { inline-size: 100%; }
.cv-more .cv-think { margin-block: 6px 0; padding-block: 8px; padding-inline: 10px; border-inline-start: 3px solid var(--color-line-strong);
  background: var(--color-sunken); color: var(--color-muted); font: 12.5px/1.5 var(--font-body); white-space: pre-wrap; overflow-wrap: anywhere;
  max-block-size: 260px; overflow-y: auto; border-radius: var(--radius-small); }
.cv-more .cv-model { margin-block: 4px 0; font-size: 12px; color: var(--color-muted); }
.cv-files { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.cv-pic { padding: 0; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); overflow: hidden;
  inline-size: 160px; block-size: 120px; display: grid; place-items: center; color: var(--color-muted); font-size: 12px; }
.cv-pic img { inline-size: 100%; block-size: 100%; object-fit: cover; display: block; }
.cv-file { display: inline-flex; gap: 6px; align-items: center; padding-block: 4px; padding-inline: 8px; border-radius: var(--radius-small);
  border: 1px solid var(--color-line); background: var(--color-sunken); color: var(--color-text); font-size: 12.5px; }
.cv-file .muted { color: var(--color-muted); }
.cv-day { align-self: center; font-size: 12px; color: var(--color-muted); padding-block: 2px; padding-inline: 10px; border-radius: 999px;
  background: var(--color-sunken); }
.cv-agent { align-self: stretch; font-size: 12.5px; color: var(--color-muted); padding-inline: 8px; }
.cv-agent > summary { cursor: pointer; list-style: none; display: flex; gap: 6px; align-items: baseline; font-weight: 400; }
.cv-agent > summary > span:first-child { font-weight: 600; white-space: nowrap; }
.cv-agent[open] .cv-clip { visibility: hidden; }
.cv-agent > summary::-webkit-details-marker { display: none; }
.cv-agent > summary::before { content: "›"; color: var(--color-line-strong); }
.cv-agent[open] > summary::before { content: "⌄"; }
.cv-agent .cv-clip { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-inline-size: 0; flex: 1; }
.cv-agent .cv-agent-text { margin-block: 4px 2px; padding-inline-start: 14px; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--color-muted); }
.cv-notice { align-self: stretch; display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding-block: 10px; padding-inline: 14px;
  border: 1px solid var(--color-warn); border-radius: var(--radius); background: var(--color-warn-soft); color: var(--color-text); font-size: 13.5px; }
.cv-notice .cv-notice-text { flex: 1 1 240px; }
.cv-notice .cc { margin: 0; padding: 0; border: none; background: transparent; }
.cv-earlier { align-self: stretch; border: 1px dashed var(--color-line-strong); border-radius: var(--radius); padding-block: 8px; padding-inline: 12px;
  background: var(--color-surface); }
.cv-earlier > summary { cursor: pointer; font-size: 13px; color: var(--color-muted); font-weight: 600; }
.cv-earlier .cv-old { display: flex; flex-direction: column; gap: 10px; margin-block-start: 10px; }
.cv-earlier .cv-old .cv-row { max-inline-size: 100%; }
.cv-earlier .cv-bubble { font-size: 13.5px; }
.cv-older { align-self: center; }
.cv-live .cv-bubble { min-inline-size: 64px; }
.cv-live .cv-writing { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--color-muted); padding-inline: 4px; }
.cv-dots { display: inline-flex; gap: 4px; }
.cv-dots i { inline-size: 6px; block-size: 6px; border-radius: 50%; background: var(--color-accent); }
.cv-live .cv-out { white-space: pre-wrap; }
@media (prefers-reduced-motion: no-preference) {
  .cv-dots i { animation: cv-bob 1.2s ease-in-out infinite; }
  .cv-dots i:nth-child(2) { animation-delay: .15s; } .cv-dots i:nth-child(3) { animation-delay: .3s; }
  .cv-row.new { animation: cv-in .25s ease-out; }
}
@keyframes cv-bob { 50% { opacity: .3; transform: translateY(-2px); } }
@keyframes cv-in { from { opacity: 0; transform: translateY(4px); } }
.cv-empty { margin: auto; text-align: center; max-inline-size: 460px; display: flex; flex-direction: column; gap: 10px; align-items: center; color: var(--color-muted); }
.cv-empty h2 { margin: 0; font-size: 18px; color: var(--color-text); }
.cv-empty p { margin: 0; font-size: 13.5px; }
.cv-ideas { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.cv-ideas button { border-radius: 999px; font-size: 13px; }
.cv-box { flex: none; }
.cv-box .compose { padding-block: 10px; padding-inline: 12px; border: 1px solid var(--color-line-strong); border-radius: var(--radius); background: var(--color-surface); }
.cv-box .compose:focus-within { border-color: var(--color-accent); }
.cv-box .compose textarea { min-block-size: 46px; max-block-size: 220px; border: none; background: transparent; resize: none; padding-inline: 2px; color: var(--color-text); }
.cv-box .compose textarea:focus { outline: none; box-shadow: none; }
.cv-box .vo { flex-direction: row; align-items: center; }
.cv-box .vo .row { margin: 0; }
.cv-page { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 18px; align-items: start; }
.cv-list { display: flex; flex-direction: column; gap: 2px; }
.cv-list a { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0 8px; padding-block: 8px; padding-inline: 10px; border-radius: var(--radius-small);
  color: var(--color-text); text-decoration: none; }
.cv-list a:hover { background: var(--color-sunken); }
.cv-list a.on { background: var(--color-accent-soft); }
.cv-list .cv-name { font-weight: 600; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cv-list .cv-last { grid-column: 1 / -1; font-size: 12px; color: var(--color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cv-list .cv-badge { align-self: center; min-inline-size: 20px; padding-inline: 6px; border-radius: 999px; background: var(--color-accent); color: var(--color-accent-text);
  font-size: 11.5px; font-weight: 700; text-align: center; }
.cv-list .cv-wait { align-self: center; font-size: 11.5px; color: var(--color-warn); }
.cv-list-fold > summary { cursor: pointer; font-size: 13px; color: var(--color-muted); }
@media (max-width: 860px) { .cv-page { grid-template-columns: minmax(0, 1fr); } .cv-page > .cv-side { order: 2; } .cv { block-size: 78vh; } }
`));
}

// -- names and addresses -----------------------------------------------------------------------------------------
/** A project's chat id from its hub key (chatstore.chat_id's twin): "hall" for none. */
export function chatIdOf(key) {
  if (!key) return HALL;
  const s = String(key).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80).replace(/^-+|-+$/g, "") || "x";
  return s === HALL ? "project-hall" : s;
}
export const chatHref = (id) => `#/chat/${encodeURIComponent(id || HALL)}`;

/** The project seat a chat belongs to (Hall's data), or null. */
export function seatForChat(id) {
  if (!S.rt || !id || id === HALL) return null;
  return (S.rt.seats || []).find((s) => s.chat === id || chatIdOf(s.key || s.id) === id) || null;
}
let NAMES = new Map();  // chat id -> name, from GET /api/chats
const nameOf = (id) => (id === HALL ? t("Hall") : NAMES.get(id) || (seatForChat(id) || {}).name || readable(id));

// cost in plain money: "0.1¢" for the usual tenth of a cent, "$0.03" once it's more than a cent (chatcard.js)
export const costWords = cents;

function dayWords(at) {
  const d = new Date(at);
  if (isNaN(d)) return "";
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(new Date()) - day(d)) / 86400000);
  if (diff === 0) return t("Today");
  if (diff === 1) return t("Yesterday");
  try { return d.toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long" }); } catch { return d.toDateString(); }
}

// -- the model's words, as text only ------------------------------------------------------------------------------
// Paragraphs, lists, headings, code, bold and `code`. A link's words are shown with its address as plain text; a
// picture from the words is never loaded (its description is shown instead).
export function richText(text) {
  const box = h("div", { class: "cv-text" });
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let list = null, para = [];
  const flush = () => { if (para.length) { box.append(h("p", { raw: true }, inline(para.join("\n")))); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i], tr = ln.trim();
    if (/^```/.test(tr)) {
      flush(); list = null;
      const code = [];
      for (i++; i < lines.length && !/^```/.test(lines[i].trim()); i++) code.push(lines[i]);
      box.append(h("pre", { raw: true }, code.join("\n")));
      continue;
    }
    if (!tr) { flush(); list = null; continue; }
    const hd = tr.match(/^#{1,6}\s+(.*)$/);
    if (hd) { flush(); list = null; box.append(h("p", { raw: true, class: "cv-h" }, inline(hd[1]))); continue; }
    const li = ln.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/);
    if (li) {
      flush();
      const tag = li[2] ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) { list = h(tag); box.append(list); }
      list.append(h("li", { raw: true }, inline(li[3])));
      continue;
    }
    list = null;
    para.push(ln);
  }
  flush();
  return box;
}
function inline(s) {
  const out = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`|!\[([^\]]*)\]\(([^)\s]*)[^)]*\)|\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    if (m[1]) out.push(h("b", { raw: true }, m[1]));
    else if (m[2]) out.push(h("code", { raw: true }, m[2]));
    else if (m[3] !== undefined && m[4] !== undefined) out.push(m[3] ? `[${m[3]}]` : "[…]");  // never loaded
    else if (m[5]) out.push(m[5] === m[6] ? m[5] : `${m[5]} (${m[6]})`);  // never a link
    last = re.lastIndex;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

// -- what the app says itself when nothing can answer (chat.CANNOT's words) ---------------------------------------
const CANT = {
  off: ["The chat is switched off in Settings.", "Open Settings", "#/settings/spending"],
  allowance: ["Today's chat allowance is used.", "Raise it for today", "raise"],
  key_refused: ["DeepSeek refused the key. Your message is kept.", "Change the key", "#/settings/keys"],
  no_credit: ["The DeepSeek account is empty. Your message is kept.", "Top up", "#/settings/spending"],
  offline: ["No internet. Your message is kept and sent when you're back.", null, null],
  no_key: ["No AI service with a key can answer yet. Add a key and the chat answers at once.", "Add a key", "#/settings/keys"],
  no_machine: ["Nothing can answer right now. Your message is kept and answered when a computer with a key is next on.", "Add a DeepSeek key", "#/settings/keys"],
};

// -- one chat ------------------------------------------------------------------------------------------------------
/** The chat for `chat` ("hall" or a project's chat id). opts: project (its folder: @ lists its files and "/" its
 *  commands), name (who answers, for the line above an answer), short (a shorter column), ideas (three things to
 *  ask, shown while the chat is empty). */
export function chatView(chat, opts = {}) {
  style();
  chat = chat || HALL;
  const name = opts.name || nameOf(chat);
  const log = h("div", { class: "cv-log", role: "log", "aria-live": "polite", "aria-label": t("The conversation") });
  keepPlace(log);
  const notice = h("div", { class: "cv-notice", role: "status", hidden: true });
  const root = h("section", { class: "cv" + (opts.short ? " short" : ""), "aria-label": t("Chat with {name}", { name: keep(name) }) });

  const lines = new Map();  // id -> line
  const nodes = new Map();  // id -> {sig, node}
  let at = "", earlier = [], showAll = false, me = null, can = { answer: true, why: "" };
  let turn = "", answering = null, first = true;
  const seen = new Set();   // ids drawn before, so only new ones slide in
  const waiters = new Map();  // turn -> resolve(line), for Talk

  const order = (a, b) => (String(a.at) < String(b.at) ? -1 : String(a.at) > String(b.at) ? 1
    : String(a.seat || "") < String(b.seat || "") ? -1 : String(a.seat || "") > String(b.seat || "") ? 1 : String(a.id) < String(b.id) ? -1 : 1);
  const mine = () => new Set([...lines.values()].filter((l) => l.who === "owner" && (me === null || l.seat === me || l._local)).map((l) => l.id));
  function merge(list) {
    for (const l of list || []) {
      if (!l || !l.id) continue;
      if (l.earlier) { if (!earlier.some((x) => x.id === l.id)) earlier.push(l); continue; }
      lines.set(l.id, l);
      if (waiters.has(l.id)) { waiters.get(l.id)(l); waiters.delete(l.id); }
    }
  }

  // -- the live answer, writing itself out --
  const out = h("div", { class: "cv-out" });
  const think = h("div", { class: "cv-think" });
  const thinkFold = h("details", { class: "cv-more", hidden: true }, h("summary", { title: t("What the model thought before it answered. Most people never need it.") }, t("More: its thinking")), think);
  const stopBtn = h("button", { type: "button", class: "small", title: t("Stop the answer here. What it wrote so far is kept.") }, t("Stop"));
  const writing = h("div", { class: "cv-writing" }, h("span", { class: "cv-dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")), h("span", {}, t("Writing…")), stopBtn);
  const live = h("div", { class: "cv-row them cv-live" }, h("span", { class: "cv-who" }, keep(name)), h("div", { class: "cv-bubble" }, out), writing, thinkFold);
  const typing = typer(out);
  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    try { await post("/api/chats/stop", { chat, turn: (answering && answering.turn) || turn }); } catch (e) { toast(e.message, true); }
  });

  function drawLive() {
    const done = !turn || lines.has(turn);
    if (done) { if (live.isConnected) live.remove(); return; }
    const text = (answering && answering.text) || "";
    typing.set(text);
    think.textContent = (answering && answering.thinking) || "";
    thinkFold.hidden = !think.textContent;
    writing.hidden = !!(answering && answering.done);
    if (!live.isConnected || live !== log.lastElementChild) log.append(live);
  }

  // -- the lines --
  function nodeFor(l) {
    const sig = JSON.stringify([l.text, l.thinking, l.card, l.state, l.cost_usd, l.files, l.model, me]);
    const had = nodes.get(l.id);
    if (had && had.sig === sig) return had.node;
    const node = lineNode(l, { chat, name, trusted: trustOf(l), onLine: (x) => { merge([x]); draw(); } });
    if (!first && !seen.has(l.id)) node.classList.add("new");
    seen.add(l.id);
    nodes.set(l.id, { sig, node });
    return node;
  }
  function trustOf(l) {  // a card is honoured only when it answers a line typed on this device (chatstore's trust rule)
    if (!l.card) return true;
    if (l.who === "app") return true;  // the app's own notice: its buttons open settings or ask the server
    if (l.who !== "chat") return false;
    return me === null || mine().has(l.answers);
  }
  const fixed = new Map();  // the day lines, the Earlier fold, the older button and the empty state, kept between draws
  const keepNode = (k, make) => { if (!fixed.has(k)) fixed.set(k, make()); return fixed.get(k); };
  let drawn = [];
  function draw() {
    const all = [...lines.values()].sort(order);
    const hidden = showAll ? 0 : Math.max(0, all.length - SHOWN);
    const shown = all.slice(hidden);
    const kids = [];
    if (earlier.length) kids.push(keepNode("earlier:" + earlier.length, () => earlierFold(earlier, { chat, name })));
    if (hidden) kids.push(keepNode("older:" + hidden, () => h("button", { type: "button", class: "small cv-older", onclick: () => { showAll = true; draw(); } }, t("Show {n} older messages", { n: hidden }))));
    let day = "";
    for (const l of shown) {
      const d = dayWords(l.at);
      if (d && d !== day) { kids.push(keepNode("day:" + d, () => h("div", { class: "cv-day", raw: true }, d))); day = d; }
      kids.push(nodeFor(l));
    }
    if (!shown.length && !earlier.length && !turn) kids.push(keepNode("empty", emptyState));
    if (kids.length !== drawn.length || kids.some((k, i) => k !== drawn[i])) { drawn = kids; fill(log, kids); }
    drawLive();
    first = false;
  }
  function emptyState() {
    const ideas = opts.ideas || (chat === HALL
      ? ["What's happening today?", "What waits for me?", "What did I spend today?"]
      : ["Where does it stand?", "What's waiting for me?", "What has it cost so far?"]);
    return h("div", { class: "cv-empty" },
      h("h2", {}, chat === HALL ? t("Ask about anything") : t("Ask about {name}", { name: keep(name) })),
      h("p", {}, chat === HALL ? t("Every project, what waits for you, what was spent today and which computers are on.")
        : t("Where it stands, what's next, what it cost. Ask it to do something and it shows a card with the price first.")),
      h("div", { class: "cv-ideas" }, ideas.map((x) => h("button", { type: "button", class: "small", title: t("Put this in the box"),
        onclick: () => { box.composer.setText(t(x)); box.composer.focus(); } }, x))));
  }

  // -- what can't answer, said plainly with its button --
  function drawNotice() {
    const newest = [...lines.values()].sort(order).pop();
    if (can.answer !== false || !can.why || (newest && newest.who === "app")) { notice.hidden = true; return; }  // said once, in the chat
    const [words, btn, where] = CANT[can.why] || [t("The chat can't answer right now. Your message is kept."), null, null];
    fill(notice, h("span", { class: "cv-notice-text" }, words),
      btn ? h("button", { type: "button", class: "small primary", onclick: async (ev) => {
        if (where !== "raise") { location.hash = where; return; }
        const yes = await dialog({ title: t("Raise today's chat allowance?"), text: t("The chat may spend more today, on every device together. It goes back to the usual limit tomorrow."),
          yes: t("Raise it for today"), no: t("Not now") });
        if (!yes) return;
        ev.currentTarget.disabled = true;
        try { const r = await post("/api/chats/tap/pc", { chat, card: "app-allowance", button: "raise_today", confirmed: true }); if (r && r.line) merge([r.line]); await tick(); }
        catch (e) { toast(e.message, true); }
      } }, btn) : null);
    notice.hidden = false;
  }

  // -- reading --
  let busy = false;
  async function tick() {
    if (busy) return;
    busy = true;
    try {
      const r = await get("/api/chats/read?" + q({ chat, since: at }));
      if (r.seat !== undefined && r.seat !== null) me = r.seat;
      if (first && Array.isArray(r.earlier)) earlier = r.earlier.slice();
      merge(r.lines);
      if (r.at) at = r.at;
      answering = r.answering || null;
      if (answering && answering.turn && !turn) turn = answering.turn;
      if (answering && !turn) turn = "live";
      if (turn === "live" && !answering) turn = "";
      can = r.can || can;
      drawNotice();
      draw();
    } finally { busy = false; }
  }
  every(root, tick, () => (turn && !lines.has(turn) ? FAST : SLOW));

  // -- sending --
  async function send({ text, key, items }) {
    const local = { id: "local-" + Date.now(), at: new Date().toISOString(), who: "owner", seat: me || "", text, _local: true,
      files: (items || []).map((x) => ({ name: x.name, size: x.size || 0, kind: /^image\//.test(x.type || "") || x.preview ? "picture" : "file", _preview: x.preview })) };
    lines.set(local.id, local);
    draw();
    requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });  // what you sent, and the answer coming, in view
    let r;
    try { r = await post("/api/chats/say", { chat, text, key }); }
    catch (e) { lines.delete(local.id); nodes.delete(local.id); draw(); throw e; }
    if (r && r.line && r.line.who === "owner") { lines.delete(local.id); nodes.delete(local.id); merge([r.line]); }
    else if (r && r.line) merge([r.line]);  // the app's own line: nothing could answer (the message is shown as typed)
    turn = (r && r.turn) || "";
    answering = null;
    stopBtn.disabled = false;
    draw();
    setTimeout(tick, 300);
    return turn;
  }
  const ask = async (text) => {  // Talk: send what was said, and hear the answer
    const tn = await send({ text, key: "", items: [] });
    if (!tn) return "";
    const line = await new Promise((res) => { waiters.set(tn, res); setTimeout(() => { if (waiters.has(tn)) { waiters.delete(tn); res(null); } }, 120000); });
    return line ? line.text : "";
  };

  const box = composer({ key: `chat:${chat}`, project: opts.project || "", rows: 2, label: t("Your message"),
    placeholder: chat === HALL ? t("Ask about anything, or say what you want done") : t("Ask about {name}, or say what you want done", { name: keep(name) }),
    enterSends: true, slash: !!opts.project, slashSends: true, queue: false, cls: "cv-compose", sendLabel: t("Send"), onSend: send });
  const area = box.querySelector("textarea");
  if (area) {
    area.title = t("Enter sends. Shift and Enter starts a new line. Type / for the commands, @ for a file.");
    const grow = () => { area.style.blockSize = "auto"; area.style.blockSize = Math.min(220, area.scrollHeight + 2) + "px"; };
    area.addEventListener("input", grow);
  }
  const talk = talkButton(chat, { ask });
  if (talk) { const bar = box.querySelector(".compose-bar"); if (bar) bar.insertBefore(talk, bar.querySelector(".spacer")); }

  fill(root, log, notice, h("div", { class: "cv-box" }, box));
  root.chat = { refresh: tick, send: (text) => send({ text, key: `chat:${chat}`, items: [] }), id: chat };
  return root;
}

// a gentle typewriter: the words already arrived are written out over a moment, never faster than they come
function typer(el) {
  let target = "", shown = 0, raf = 0;
  const still = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function step() {
    const left = target.length - shown;
    if (left <= 0) { raf = 0; return; }
    shown += Math.max(1, Math.ceil(left / 24));
    el.textContent = target.slice(0, shown);
    raf = requestAnimationFrame(step);
  }
  return {
    set(text) {
      text = String(text || "");
      if (!text.startsWith(target.slice(0, shown))) shown = 0;
      target = text;
      if (still() || typeof requestAnimationFrame !== "function") { shown = text.length; el.textContent = text; return; }
      if (!raf) step();
    },
  };
}

// -- one line -------------------------------------------------------------------------------------------------------
function lineNode(l, ctx) {
  if (l.who === "agent") return agentLine(l);
  if (l.who === "app") {
    return h("div", { class: "cv-notice", role: "status" }, h("span", { class: "cv-notice-text", raw: true }, l.text),
      l.card ? chatCard(l.card, { chat: ctx.chat, plain: true, onLine: ctx.onLine }) : null);
  }
  if (l.who === "owner") {
    return h("div", { class: "cv-row you" },
      l.text ? h("div", { class: "cv-bubble", raw: true }, l.text) : null,
      filesOf(l, ctx.chat),
      h("div", { class: "cv-foot" }, h("time", { datetime: l.at, title: fullDate(l.at), raw: true }, stamp(l.at)),
        l.state === "waiting" ? h("span", { title: t("No computer or phone with a key could answer yet. The first one to come on answers it.") }, t("Waiting for an answer")) : null));
  }
  // chat (the model) or project (a project's agent writing to the owner)
  const who = l.who === "project" ? t("{name} wrote to you", { name: keep(l.from ? String(projectName(l.from)) : ctx.name) }) : keep(ctx.name);
  const cost = costWords(l.cost_usd);
  const more = l.thinking || l.model
    ? h("details", { class: "cv-more" }, h("summary", { title: t("Its thinking and which model answered") }, t("More")),
      l.model ? h("p", { class: "cv-model" }, t("Answered by {model}", { model: keep(l.model) })) : null,
      l.thinking ? h("div", { class: "cv-think", raw: true }, l.thinking) : null)
    : null;
  return h("div", { class: "cv-row them" }, h("span", { class: "cv-who" }, who),
    h("div", { class: "cv-bubble" }, richText(l.text),
      l.card ? chatCard(l.card, { chat: ctx.chat, trusted: ctx.trusted, onLine: ctx.onLine }) : null),
    filesOf(l, ctx.chat),
    h("div", { class: "cv-foot" },
      l.device ? h("span", { raw: true, title: t("Which device answered") }, l.device) : null,
      cost ? h("span", { title: t("What this answer cost") }, keep(cost)) : null,
      h("time", { datetime: l.at, title: fullDate(l.at), raw: true }, stamp(l.at)),
      canSpeak() && l.text ? h("button", { type: "button", title: t("Read this answer aloud with your computer's voice") , onclick: () => speak(l.text) }, t("Read aloud")) : null,
      more));
}
function stamp(at) {
  const d = new Date(at);
  if (isNaN(d)) return "";
  return new Date().toDateString() === d.toDateString() ? clock(at) : t("{day}, {time}", { day: dayWords(at), time: clock(at) });
}
const fullDate = (at) => { const d = new Date(at); return isNaN(d) ? "" : d.toLocaleString(locale()); };

function agentLine(l) {
  const from = String(projectName(l.from || "")), to = l.to ? String(projectName(l.to)) : t("everyone");
  const first = String(l.text || "").split("\n").find((x) => x.trim()) || "";
  return h("details", { class: "cv-agent", title: t("What agents said to each other. You can read it; answers go to them, not from here.") },
    h("summary", {}, h("span", {}, t("{from} told {to}:", { from: keep(from), to: keep(to) })), h("span", { class: "cv-clip", raw: true }, first),
      h("time", { datetime: l.at, title: fullDate(l.at), raw: true }, stamp(l.at))),
    h("div", { class: "cv-agent-text", raw: true }, l.text));
}

const PICS = new Map();  // chat|name -> data: address (the chat's own files only)
function filesOf(l, chat) {
  const files = l.files || [];
  if (!files.length) return null;
  return h("div", { class: "cv-files" }, files.map((f) => {
    const fname = f.sha && f.ext ? `${f.sha}.${f.ext}` : f.name;
    if (f.kind === "picture" && !f.on) {
      const btn = h("button", { type: "button", class: "cv-pic", title: t("{name}: click to see it full size", { name: keep(f.name) }) }, keep(f.name));
      const show = (src) => { if (!/^data:image\/(png|jpeg|webp|gif);base64,/.test(src)) return; fill(btn, h("img", { src, alt: keep(f.name) })); btn.onclick = () => enlarge(src, keep(f.name)); };
      if (f._preview && /^(data|blob):/.test(f._preview)) fill(btn, h("img", { src: f._preview, alt: keep(f.name) }));
      else if (PICS.has(chat + "|" + fname)) show(PICS.get(chat + "|" + fname));
      else get("/api/chats/file?" + q({ chat, name: fname })).then((r) => { if (r && r.data) { PICS.set(chat + "|" + fname, r.data); show(r.data); } }).catch(() => {});
      return btn;
    }
    return h("span", { class: "cv-file", title: f.on ? t("Kept on {device}: it was too big to share", { device: keep(f.on) }) : keep(f.name) },
      h("span", { raw: true }, f.name), h("span", { class: "muted" }, keep(fileSize(f.size))), f.on ? h("span", { class: "muted" }, t("on {device}", { device: keep(f.on) })) : null);
  }));
}

function earlierFold(list, ctx) {
  const items = list.slice().sort((a, b) => (String(a.at) < String(b.at) ? -1 : 1));
  const body = h("div", { class: "cv-old" });
  const fold = h("details", { class: "cv-earlier" },
    h("summary", { title: t("Your old letters, kept as they were. Read them here; anything new goes in the chat below.") }, t("Earlier messages ({n})", { n: items.length })), body);
  fold.addEventListener("toggle", () => {  // drawn when first opened: there may be hundreds
    if (fold.open && !body.firstChild) fill(body, items.map((l) => lineNode({ ...l, card: null }, { ...ctx, trusted: false })));
  });
  return fold;
}

// -- the list of chats ------------------------------------------------------------------------------------------------
/** Every chat, Hall first, then the newest spoken-in; `current` is marked. */
export function chatList(current) {
  style();
  const nav = h("nav", { class: "cv-list", "aria-label": t("Chats") });
  every(nav, async () => {
    const r = await get("/api/chats");
    const chats = sortChats(r.chats || []);
    for (const c of chats) if (c.name) NAMES.set(c.id, c.name);
    patch(nav, JSON.stringify([chats, current]), () => chats.map((c) => {
      const last = c.last && typeof c.last === "object" ? c.last.text || "" : typeof c.last === "string" && !/^\d{4}-\d\d-\d\dT/.test(c.last) ? c.last : "";
      return h("a", { href: chatHref(c.id), class: c.id === current ? "on" : "", "aria-current": c.id === current ? "page" : null,
        title: c.waiting ? t("A message waits for an answer") : "" },
      h("span", { class: "cv-name" }, c.id === HALL ? t("Hall") : keep(c.name || readable(c.id))),
      c.unread ? h("span", { class: "cv-badge", title: t("New messages") }, String(c.unread)) : c.waiting ? h("span", { class: "cv-wait" }, t("Waiting")) : h("span"),
      last ? h("span", { class: "cv-last", raw: true }, String(last).split("\n")[0].slice(0, 90)) : null);
    }));
  }, 5000);
  return nav;
}
function sortChats(list) {
  const when = (c) => String((c.last && typeof c.last === "object" ? c.last.at : c.last) || "");
  const hall = list.filter((c) => c.id === HALL), rest = list.filter((c) => c.id !== HALL).sort((a, b) => (when(a) < when(b) ? 1 : -1));
  return [hall.length ? hall[0] : { id: HALL, name: "Hall", unread: 0, waiting: 0 }, ...rest];
}

/** How many chats have something new (the header's count). */
export async function newChats() {
  try { return ((await get("/api/chats")).chats || []).filter((c) => c.unread > 0).length; } catch { return 0; }
}

// -- the page: #/chat/<id> --------------------------------------------------------------------------------------------
export async function viewChat(id = HALL) {
  style();
  id = decodeURIComponent(id || HALL);
  try { const r = await get("/api/chats"); for (const c of r.chats || []) if (c.name) NAMES.set(c.id, c.name); } catch { /* the list shows what it can */ }
  const seat = seatForChat(id);
  const name = nameOf(id);
  const sub = id === HALL ? t("Ask about any project, what waits for you or what was spent. Anything that spends shows its price and waits for your tap.")
    : t("Ask about this project, or say what to do. Anything that spends shows its price and waits for your tap.");
  const head = h("header", { class: "page-head" }, h("div", {}, h("h1", {}, id === HALL ? t("Hall") : keep(name)), h("p", { class: "sub" }, sub)),
    seat ? h("a", { class: "btn small", href: `#/p/${encodeURIComponent(seat.id)}`, title: t("The project's page: its plan, tasks and money") }, t("Open the project")) : null);
  return h("div", { class: "page" }, head, h("div", { class: "cv-page" },
    h("aside", { class: "cv-side" }, chatList(id)),
    chatView(id, { project: seat ? seat.path : "", name: id === HALL ? BRAND.short : name })));
}

/** Needs you: "Music player wrote to you", opening its chat. n: {project, chat?, count?, unread?, text?} */
export function wroteCard(n) {
  style();
  const id = n.chat || chatIdOf(n.project);
  const count = n.count || n.unread || 1;
  return h("article", { class: "need-card wrote-card" },
    h("p", {}, h("b", {}, t("{name} wrote to you", { name: keep(nameOf(id) === readable(id) && n.name ? n.name : nameOf(id)) })),
      count > 1 ? h("span", { class: "muted small" }, t(" · {n} new messages", { n: count })) : null),
    n.text ? h("p", { class: "muted small", raw: true }, String(n.text).slice(0, 200)) : null,
    h("div", { class: "row" }, h("a", { class: "btn primary small", href: chatHref(id) }, t("Open the chat"))));
}
