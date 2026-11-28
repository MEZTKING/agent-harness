// "/" commands in the message box (harness/slash.py, ui/chatapi.py): a menu while the box starts with "/", and
// running one. Each command does what one of the app's buttons does; one that spends or undoes work asks
// "Are you sure?" first, as the button would. Slow ones (summing up the chat, the tests, a plug-in) come back as
// a background job, followed here for as long as it takes: nothing gives up after 30 seconds.
import { h, fill, get, post, q, dialog, toast } from "./core.js";
import { t as wt } from "./words.js";

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "slash" }, `
.slash-menu { position: absolute; z-index: 6; inset-inline-start: 0; inset-inline-end: 0; bottom: calc(100% + 4px); max-height: 260px; overflow: auto; margin: 0; padding: 4px;
  list-style: none; background: var(--color-surface); border: 1px solid var(--color-line); border-radius: var(--radius-small); box-shadow: var(--shadow); }
.slash-menu li { display: flex; gap: 10px; align-items: baseline; padding: 5px 8px; border-radius: 4px; cursor: pointer; }
.slash-menu li.on, .slash-menu li:hover { background: var(--color-accent-soft); }
.slash-menu b { font: 600 13px/1.4 var(--font-mono); white-space: nowrap; }
.slash-menu span { font-size: 12.5px; color: var(--color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slash-reply { white-space: pre-line; font-size: 13px; margin: 0; padding: 6px 10px; border-inline-start: 3px solid var(--color-accent); background: var(--color-sunken);
  border-radius: 0 var(--radius-small) var(--radius-small) 0; }
.slash-reply.busy::before { content: "… "; }
`));
}

const cache = new Map();  // project -> the commands, asked for once a visit
export async function commands(path) {
  if (!cache.has(path)) cache.set(path, get("/api/commands?" + q({ path })).then((r) => r.commands || []).catch(() => []));
  return cache.get(path);
}

// Follow a background job until it ends, however long that takes (DS-83). onLine(text) hears its newest log line.
export async function waitJob(job, onLine) {
  let since = 0;
  for (;;) {
    let j;
    try { j = await get(`/api/jobs/${encodeURIComponent(job.id)}?since=${since}`); }
    catch (e) { if (/has gone/.test(String(e.message))) throw e; await new Promise((r) => setTimeout(r, 2000)); continue; }
    since = j.log_size || since;
    if (onLine && (j.log || []).length) onLine(String(j.log[j.log.length - 1]).replace(/^\d\d:\d\d:\d\d\s+/, ""));
    if (j.status !== "running") return j;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

// Run one command line. opts: confirmed, onOpen(page), onReply(text, busy). Resolves with the last words shown.
export async function runCommand(path, line, opts = {}) {
  const say = (t, busy = false) => { if (opts.onReply) opts.onReply(t, busy); else if (!busy) toast(t); return t; };
  let r = await post("/api/commands/pc", { path, line, confirmed: !!opts.confirmed });
  if (r.confirm) {
    const yes = await dialog({ title: "Are you sure?", text: r.confirm, yes: "Yes, go ahead", no: "No, go back" });
    if (!yes) return say("Nothing was done.");
    r = await post("/api/commands/pc", { path, line, confirmed: true });
  }
  if (r.open && opts.onOpen) opts.onOpen(r.open);
  if (!r.job) return say(r.reply || "Done.");
  say(r.reply || "Working on it…", true);
  const j = await waitJob(r.job, (l) => say(`${r.reply || "Working on it…"}\n${l}`, true));
  if (j.status === "failed") return say(`It didn't finish: ${String(j.error || "").replace(/^\w+Error: /, "")}`);
  const res = j.result || {};
  return say(res.reply || (res.status ? `Ended as: ${String(res.status).replace(/_/g, " ")}.` : "Done."));
}

// The menu under a message box: shown while the box starts with "/" and the first word is still being typed.
// Returns {keydown(ev) -> true when it used the key, update()}.
export function slashMenu(area, path, holder) {
  style();
  const list = h("ul", { class: "slash-menu", role: "listbox", hidden: true, "aria-label": "Commands" });
  holder.append(list);
  let items = [], pick = 0;
  const shown = () => !list.hidden && items.length;
  async function update() {
    const m = /^\/(\S*)$/.exec(area.value.slice(0, area.selectionStart));
    if (!m) { list.hidden = true; return; }
    const word = m[1].toLowerCase();
    const all = await commands(path);
    items = all.filter((c) => c.name.startsWith(word)).concat(all.filter((c) => !c.name.startsWith(word) && c.name.includes(word))).slice(0, 30);
    pick = Math.min(pick, Math.max(0, items.length - 1));
    draw();
  }
  function draw() {
    list.hidden = !items.length;
    fill(list, items.map((c, i) => h("li", { role: "option", class: i === pick ? "on" : "", "aria-selected": String(i === pick),
      title: c.confirm ? wt("{words}. It asks you first.", { words: c.words }) : c.words, onmousedown: (ev) => { ev.preventDefault(); choose(c); } },
    h("b", {}, `/${c.name}${c.args ? " " + c.args : ""}`), h("span", {}, c.words))));
  }
  function choose(c) {
    area.value = `/${c.name}` + (c.args ? " " : "");
    area.setSelectionRange(area.value.length, area.value.length);
    list.hidden = true;
    area.dispatchEvent(new Event("input"));
    area.focus();
  }
  function keydown(ev) {
    if (!shown()) return false;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); pick = (pick + (ev.key === "ArrowDown" ? 1 : items.length - 1)) % items.length; draw(); return true; }
    if (ev.key === "Tab" || (ev.key === "Enter" && !ev.ctrlKey && !ev.metaKey)) { ev.preventDefault(); choose(items[pick]); return true; }
    if (ev.key === "Escape") { list.hidden = true; return true; }
    return false;
  }
  area.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
  return { keydown, update };
}

// A line under the box for a command's answer (kept until the next command).
export function replyLine() {
  style();
  const p = h("p", { class: "slash-reply", role: "status", "aria-live": "polite", hidden: true });
  p.show = (text, busy) => { p.hidden = !text; p.textContent = text || ""; p.classList.toggle("busy", !!busy); };
  return p;
}
