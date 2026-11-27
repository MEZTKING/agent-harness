// The command line (a project's tab) and a running task's command, live (in Watch).
// The command line is the owner's own tool on this computer: it runs as them, keys kept out, never on the phone.
// It isn't a full terminal: programs that take over the whole screen won't work, and the page says so.
import { h, fill, get, post, q, toast } from "./core.js";

const MAX_TEXT = 400000; // characters kept on the page; older lines scroll away

// ---------- the command line ----------
export async function terminalTab(seat) {
  terminalStyles();
  const out = h("pre", { class: "tm-out", role: "log", "aria-live": "polite", tabindex: "0" });
  const where = h("span", { class: "tm-where", title: "The folder commands run in. Type cd <folder> to move." });
  const state = h("span", { class: "muted small" });
  const field = h("input", { class: "tm-in", type: "text", spellcheck: "false", autocomplete: "off",
    "aria-label": "Type a command", placeholder: "Type a command, then Enter" });
  const stopBtn = h("button", { class: "small danger", type: "button", hidden: true,
    title: "End what is running now, and everything it started" }, "Stop");
  const clearBtn = h("button", { class: "small", type: "button", title: "Empty this window (nothing is undone)" }, "Clear");
  const newBtn = h("button", { class: "small", type: "button", title: "Close this command line and start a fresh one in the project's folder" }, "Start again");
  let sid = null, since = 0, running = false, history = [], hpos = 0, alive = true;

  const box = h("div", { class: "tm" },
    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Command line"), state),
      h("p", { class: "muted small" }, "Type commands in this project's folder. They run as you, on this computer."),
      h("details", { class: "tm-more" }, h("summary", {}, "More"),
        h("p", { class: "small" }, "This isn't a full terminal: programs that take over the whole window (text editors, top, some installers' menus) won't work here. ",
          "While a program runs, what you type goes to it. Stop ends it and everything it started."),
        h("p", { class: "small" }, "Your keys are kept out of these commands, as they are for the builders. It only works in the app's own window on this computer, never from your phone.")),
      h("div", { class: "tm-bar" }, where, h("span", { class: "spacer" }), stopBtn, clearBtn, newBtn),
      out,
      h("form", { class: "tm-form" }, h("span", { class: "tm-prompt", "aria-hidden": "true" }, ">"), field,
        h("button", { class: "small primary", type: "submit" }, "Run"))));

  const show = (v) => {
    running = !!v.running;
    if (v.folder) where.textContent = v.folder;
    stopBtn.hidden = !running;
    field.placeholder = running ? "Type into the program that is running, then Enter" : "Type a command, then Enter";
    state.textContent = running ? `Running: ${v.line || ""}`.slice(0, 80) : "Ready";
  };
  const add = (text) => {
    if (!text) return;
    const stick = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
    out.textContent = (out.textContent + text).slice(-MAX_TEXT);
    if (stick) out.scrollTop = out.scrollHeight;
  };
  const start = async (fresh) => {
    const v = await post("/api/terminal/open", { path: seat.path, fresh: !!fresh });
    sid = v.id; since = 0; history = v.history || []; hpos = history.length;
    out.textContent = "";
    show(v);
  };
  const loop = async () => {
    for (let i = 0; i < 60 && !box.isConnected; i++) await new Promise((r) => setTimeout(r, 50)); // until it is shown
    while (alive && box.isConnected) {  // leaving the tab stops reading; the command line stays open for 30 minutes
      if (!sid) { await new Promise((r) => setTimeout(r, 300)); continue; }
      try {
        const r = await get(`/api/terminal/read?${q({ id: sid, since, wait: 15 })}`);
        if (r.cut) add("\n… (older output was let go)\n");
        add(r.text);
        since = r.next;
        show(r);
        if (r.closed) { sid = null; await start(false); }
      } catch (e) {
        state.textContent = String(e.message || e);
        if (/closed|Open a new one/.test(String(e.message))) { try { await start(false); } catch { /* shown above */ } }
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  };

  box.querySelector("form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const line = field.value;
    field.value = "";
    if (!sid) return;
    try {
      if (running) show(await post("/api/terminal/input", { id: sid, text: line }));
      else {
        if (line.trim()) { history = history.concat(line).slice(-100); hpos = history.length; }
        show(await post("/api/terminal/run", { id: sid, line }));
      }
    } catch (e) { toast(String(e.message || e), true); }
    field.focus();
  });
  field.addEventListener("keydown", (ev) => {
    if (running || !history.length) return;
    if (ev.key === "ArrowUp") { hpos = Math.max(0, hpos - 1); field.value = history[hpos] || ""; ev.preventDefault(); }
    if (ev.key === "ArrowDown") { hpos = Math.min(history.length, hpos + 1); field.value = history[hpos] || ""; ev.preventDefault(); }
  });
  stopBtn.addEventListener("click", async () => { try { show(await post("/api/terminal/stop", { id: sid })); } catch (e) { toast(String(e.message || e), true); } });
  clearBtn.addEventListener("click", () => { out.textContent = ""; field.focus(); });
  newBtn.addEventListener("click", async () => {
    try { if (sid) await post("/api/terminal/close", { id: sid }); await start(true); } catch (e) { toast(String(e.message || e), true); }
  });

  try { await start(false); } catch (e) {
    alive = false;
    return h("div", { class: "tm" }, h("section", { class: "card" }, h("h2", {}, "Command line"), h("p", {}, String(e.message || e))));
  }
  loop();
  setTimeout(() => field.focus(), 0);
  return box;
}

// ---------- a task's command, as it prints (Watch: a Run step still going) ----------
export function liveOutput(path, task) {
  terminalStyles();
  const pre = h("pre", { class: "tm-live-out", role: "log", "aria-live": "polite" });
  const words = h("span", { class: "muted small" }, "Waiting for its output…");
  const stopBtn = h("button", { class: "small danger", type: "button", title: "Stop this one command. The task carries on and is told you stopped it." }, "Stop this command");
  const node = h("div", { class: "tm-live" }, h("div", { class: "tm-bar" }, words, h("span", { class: "spacer" }), stopBtn), pre);
  let since = 0, n = null, seen = false, waits = 0;
  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    try { const r = await post("/api/terminal/task/stop", { path, task, n }); toast(r.words); }
    catch (e) { toast(String(e.message || e), true); }
  });
  const tick = async () => {
    if (!node.isConnected) { if (!seen && ++waits < 60) setTimeout(tick, 50); return; } // gone from the page: stop
    seen = true;
    try {
      const r = await get(`/api/terminal/task?${q({ path, task, since, n })}`);
      if (n !== null && r.n !== n) pre.textContent = "";
      n = r.n;
      if (r.skipped) pre.textContent = "… (the start is in the task's log)\n";
      const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
      pre.textContent = (pre.textContent + (r.text || "")).slice(-MAX_TEXT);
      if (stick) pre.scrollTop = pre.scrollHeight;
      since = r.next;
      words.textContent = r.command ? `${r.words} ${r.command}`.slice(0, 120) : r.words;
      words.title = r.command || "";
      stopBtn.hidden = !r.running;
      stopBtn.disabled = false;
      if (!r.running && r.ended) return; // finished: nothing more will come
    } catch { /* the next tick tries again */ }
    setTimeout(tick, 1200);
  };
  setTimeout(tick, 0);
  return node;
}

function terminalStyles() {
  if (typeof document === "undefined" || document.getElementById("tm-style")) return;
  document.head.append(h("style", { id: "tm-style" }, `
.tm-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 6px 0; } .tm-bar .spacer { flex: 1; }
.tm-where { font-family: var(--font-mono, monospace); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.tm-out, .tm-live-out { background: var(--term-bg); color: var(--term-text); border: 1px solid var(--term-line); border-radius: var(--radius-small);
  font: 13px/1.45 var(--font-mono, monospace); padding: 10px 12px; margin: 0; white-space: pre-wrap; word-break: break-word; overflow: auto; }
.tm-out { height: min(60vh, 560px); }
.tm-live-out { max-height: 260px; min-height: 2.5em; }
.tm-form { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.tm-prompt { font-family: var(--font-mono, monospace); font-weight: 700; }
.tm-in { flex: 1; font: 14px var(--font-mono, monospace); min-width: 0; }
.tm-more { margin: 4px 0 8px; } .tm-more > summary { cursor: pointer; font-size: 13px; }
.tm-live { margin: 4px 0 8px 18px; }
`));
}
