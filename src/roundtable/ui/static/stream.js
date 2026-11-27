// A reply's words as they are written (harness/streamlog.py, GET /api/stream), under a task in Watch and in the
// project chat; the model's thinking folded behind "More". Asked for once a second while a task works, as the
// live command is: no new socket. Also: a follow-up to one task (POST /api/follow), and keepPlace – the reader's
// place kept when the window's width changes, and the newest message never hidden under the message box.
import { h, fill, get, post, q, dialog, toast, ago } from "./core.js";
import { waitJob } from "./slash.js";

const MAX = 60000;  // characters kept on the page

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "stream" }, `
.st-words { margin: 4px 0 8px 18px; padding: 8px 10px; border-left: 3px solid var(--color-accent); background: var(--color-sunken);
  border-radius: 0 var(--radius-small) var(--radius-small) 0; font-size: 13.5px; }
.st-text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; margin: 0; }
.st-head { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--color-muted); margin-bottom: 4px; }
.st-head .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-accent); }
.st-head .dot.off { background: var(--color-line-strong); }
.st-think > summary { cursor: pointer; font-size: 12.5px; color: var(--color-muted); }
.st-think pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 200px; overflow-y: auto; font: 12.5px/1.45 var(--font-body);
  color: var(--color-muted); margin: 4px 0 0; }
.st-follow { margin: 4px 0 8px 18px; }
.st-follow > summary { cursor: pointer; font-size: 13px; }
.st-follow .row { display: flex; gap: 6px; align-items: flex-start; flex-wrap: wrap; margin-top: 6px; }
.st-follow textarea { flex: 1; min-width: 200px; }
.st-qa { margin: 6px 0; padding: 6px 10px; background: var(--color-sunken); border-radius: var(--radius-small); font-size: 13px; }
.st-qa .a { white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 2px; }
.keep-place { overflow-anchor: none; scroll-padding-bottom: 16px; }
.keep-place::after { content: ""; display: block; height: 12px; flex: none; }
`));
}

// The words under one task. Shown only once there are some; gone quiet, it says the reply is finished.
export function streamUnder(path, task) {
  style();
  const text = h("pre", { class: "st-text", role: "log", "aria-live": "off", tabindex: "0" });
  const thinking = h("pre", {});
  const fold = h("details", { class: "st-think", hidden: true }, h("summary", { title: "What the model thought before it wrote. Most people never need it." }, "More: its thinking"), thinking);
  const dot = h("span", { class: "dot" });
  const said = h("span", {}, "Writing…");
  const node = h("div", { class: "st-words", hidden: true }, h("div", { class: "st-head" }, dot, said), text, fold);
  let at = 0, seen = false, waits = 0, quiet = 0;
  const add = (el, piece) => {
    if (!piece) return;
    const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    el.textContent = (el.textContent + piece).slice(-MAX);
    if (stick) el.scrollTop = el.scrollHeight;
  };
  const tick = async () => {
    if (!node.isConnected) { if (!seen && ++waits < 60) setTimeout(tick, 50); return; }
    seen = true;
    let r = null;
    try { r = await get("/api/stream?" + q({ path, task, since: at })); } catch { /* the next tick tries again */ }
    if (r) {
      if (Math.floor(r.at / 1e12) !== Math.floor(at / 1e12) && at) { text.textContent = ""; thinking.textContent = ""; }  // a new reply
      at = r.at;
      if (r.skipped && !text.textContent) text.textContent = "… ";
      add(text, r.text); add(thinking, r.thinking);
      if (text.textContent || thinking.textContent) node.hidden = false;
      fold.hidden = !thinking.textContent;
      dot.classList.toggle("off", !!r.done);
      said.textContent = r.done ? "Finished writing" : "Writing…";
      quiet = r.done ? quiet + 1 : 0;
    }
    setTimeout(tick, quiet > 3 ? 5000 : 1000);  // a finished task is asked less often
  };
  setTimeout(tick, 0);
  return node;
}

// "Ask about this task": a question to the model that built it (priced first), or a small change (a new task).
export function followBox(path, task, title = "") {
  style();
  const list = h("div", {});
  const field = h("textarea", { rows: 2, placeholder: "Why did it do it this way? Or: what should change?", "aria-label": `Your question about ${task}` });
  let mode = "ask";
  const seg = h("span", { class: "seg", role: "group", "aria-label": "Question or change" });
  const drawSeg = () => fill(seg, [["ask", "Ask", "A question to the model that built it. Nothing changes. It costs a little and asks you first."],
    ["change", "Change it", "A small new task that changes it, built and checked like any other."]].map(([id, label, tip]) =>
    h("button", { type: "button", class: id === mode ? "on" : "", "aria-pressed": String(id === mode), title: tip, onclick: () => { mode = id; drawSeg(); } }, label)));
  drawSeg();
  const send = h("button", { type: "button", class: "primary small" }, "Send");
  const node = h("details", { class: "st-follow" }, h("summary", { title: "Ask the model that built this task, or ask for a change to it" }, "Ask about this task"),
    list, h("div", { class: "row" }, field, seg, send));
  const load = async () => {
    let items = [];
    try { items = (await get("/api/follow?" + q({ path, task }))).items || []; } catch { /* an older app */ }
    fill(list, items.map((x) => h("div", { class: "st-qa" }, h("div", {}, h("b", {}, "You: "), x.question, x.at ? h("span", { class: "muted small" }, ` · ${ago(x.at)}`) : null),
      x.change ? h("div", { class: "a muted" }, `Became task ${x.change}.`) : h("div", { class: "a" }, x.answer || ""))));
  };
  node.addEventListener("toggle", () => { if (node.open) load(); });
  send.addEventListener("click", async () => {
    const text = field.value.trim();
    if (!text) { toast("Write your question first.", true); field.focus(); return; }
    send.disabled = true;
    try {
      let r = await post("/api/follow", { path, task, text, mode });
      if (r.confirm) {
        if (!(await dialog({ title: `Ask about ${title || task}?`, text: r.confirm, yes: "Ask it", no: "Not now" }))) return;
        r = await post("/api/follow", { path, task, text, mode, confirmed: true });
      }
      field.value = "";
      if (r.job) {
        toast(r.reply || "Asking…");
        const j = await waitJob(r.job);
        if (j.status === "failed") toast(String(j.error || "It didn't answer.").replace(/^\w+Error: /, ""), true);
      } else toast(r.reply || "Sent");
      await load();
    } catch (e) { toast(e.message, true); }
    finally { send.disabled = false; }
  });
  return node;
}

// DS-82: keep the reader's place in a scrolling list (a chat, a task's words) when its width changes, and keep
// the end in view when the reader was at the end – also when the message box under it grows and makes it
// shorter, so the newest message is never hidden. Call once on the scrolling element.
export function keepPlace(scroller) {
  style();
  scroller.classList.add("keep-place");
  if (typeof ResizeObserver !== "function") return scroller;
  let atEnd = true, anchor = null, offset = 0, width = scroller.clientWidth;
  const remember = () => {
    atEnd = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;
    anchor = null;
    const top = scroller.getBoundingClientRect().top;
    for (const kid of scroller.children) {
      const r = kid.getBoundingClientRect();
      if (r.bottom > top) { anchor = kid; offset = r.top - top; break; }
    }
  };
  const restore = () => {
    if (atEnd) { scroller.scrollTop = scroller.scrollHeight; return; }
    if (anchor && anchor.isConnected) scroller.scrollTop += (anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top) - offset;
  };
  scroller.addEventListener("scroll", remember, { passive: true });
  const ro = new ResizeObserver(() => {
    if (!scroller.isConnected) { ro.disconnect(); return; }
    const changed = scroller.clientWidth !== width;
    width = scroller.clientWidth;
    if (changed || atEnd) restore();  // a new width moves every line; a shorter box keeps the end in view
    remember();
  });
  ro.observe(scroller);
  // new messages: stay at the end only if the reader was there
  new MutationObserver(() => { if (atEnd) requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; }); })
    .observe(scroller, { childList: true, subtree: true, characterData: true });
  requestAnimationFrame(remember);
  return scroller;
}
