// Search everything: the box in the top bar, the Search page (#/search/<words>), and the memory files.
// The API is ui/searchapi.py (GET /api/search, /api/search/peek, /api/memory; POST /api/memory, /api/memory/note).
// Results open the right place: a project's Plan or Journal, Letters, or a window with the file, note or memory.
import { h, fill, get, post, q, act, toast, dialog, page, card, empty, seg, markdown, when, refreshHall, seatByPath,
  projectHref, S } from "./core.js";

// this page's few looks, kept here so style.css stays as it is
const CSS = `
.sr-box { display: flex; align-items: center; }
.sr-box input { width: 210px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--color-line);
  background: var(--color-surface); color: var(--color-text); font: inherit; font-size: 14px; }
.sr-box input:focus { width: 280px; outline: 2px solid var(--color-accent); outline-offset: 1px; }
.sr-hits { list-style: none; margin: 0; padding: 0; }
.sr-hit { border-top: 1px solid var(--color-line); }
.sr-hit:first-child { border-top: 0; }
.sr-hit button { all: unset; box-sizing: border-box; display: block; width: 100%; padding: 10px 4px; cursor: pointer; }
.sr-hit button:hover, .sr-hit button:focus-visible { background: color-mix(in srgb, var(--color-text) 6%, transparent); }
.sr-title { font-weight: 700; }
.sr-where { color: var(--color-muted); font-size: 13.5px; }
.sr-snip { margin-top: 2px; font-size: 14px; overflow-wrap: anywhere; }
.sr-hit mark { background: color-mix(in srgb, var(--color-warn) 35%, transparent); color: inherit; border-radius: 3px; }
.sr-peek { max-height: 60vh; overflow: auto; font: 13px/1.45 ui-monospace, monospace; white-space: pre; margin: 0; }
.sr-peek .on { background: color-mix(in srgb, var(--color-warn) 25%, transparent); }
.sr-memory { width: 100%; min-height: 50vh; font: 13.5px/1.5 ui-monospace, monospace; }
@media (max-width: 720px) { .sr-box input, .sr-box input:focus { width: 140px; } }
`;
function addLooks() {
  if (document.getElementById("sr-css")) return;
  document.head.append(h("style", { id: "sr-css" }, CSS));
}

const KINDS = [["", "Everything", "Look in every place"], ["plan,task", "Plans and tasks", "The plans and every task, with their reviews"],
  ["memory", "Memory", "What the harness remembers about each project and this computer"],
  ["journal,letter,note", "Journal and letters", "The hub's journal, your letters and your saved notes"],
  ["file", "Files", "The projects' own files: names and text"]];

// The box in the top bar. Enter (or a pause in typing) opens the Search page; Ctrl+K or "/" jumps to it.
export function mountSearch(host) {
  if (!host) return;
  addLooks();
  const box = h("input", { type: "search", placeholder: "Search everything", "aria-label": "Search everything",
    title: "Look for any word in your plans, tasks, journal, letters, memory, notes and project files (Ctrl+K)", autocomplete: "off" });
  box.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && box.value.trim()) { ev.preventDefault(); location.hash = `#/search/${encodeURIComponent(box.value.trim())}`; }
    if (ev.key === "Escape") { box.value = ""; box.blur(); }
  });
  fill(host, h("form", { class: "sr-box", role: "search", onsubmit: (ev) => ev.preventDefault() }, box));
  host.hidden = false;
  document.addEventListener("keydown", (ev) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target && ev.target.tagName) || "") || (ev.target && ev.target.isContentEditable);
    if ((ev.key === "k" && (ev.ctrlKey || ev.metaKey)) || (ev.key === "/" && !typing)) { ev.preventDefault(); box.focus(); box.select(); }
  });
}

// The Search page: #/search/<words>
export async function viewSearch(words = "") {
  addLooks();
  let kinds = "", timer = null, gen = 0;
  const field = h("input", { type: "search", class: "grow", value: words, placeholder: "What are you looking for?",
    "aria-label": "Words to look for", autocomplete: "off" });
  const status = h("p", { class: "muted", "aria-live": "polite" });
  const list = h("div");
  const draw = async () => {
    const text = field.value.trim();
    const mine = ++gen;
    if (!text) { fill(status, "Type a word or two. \"Quoted words\" must be together."); fill(list); return; }
    fill(status, "Looking…");
    let res;
    try { res = await get(`/api/search?${q({ q: text, kinds })}`); }
    catch (e) { if (mine === gen) { fill(status, e.message); fill(list); } return; }
    if (mine !== gen) return;
    fill(status, res.words || "");
    const hits = res.hits || [];
    fill(list, hits.length ? card(null, h("ul", { class: "sr-hits" }, hits.map((x) => hitRow(x, text))))
      : empty("Nothing matches every word. Try fewer words, or look in Everything."));
  };
  field.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { history.replaceState(null, "", `#/search/${encodeURIComponent(field.value.trim())}`); draw(); }, 300);
  });
  field.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); clearTimeout(timer); draw(); } });
  const where = seg(KINDS.map(([v, t, tip]) => [v, t, tip]), "", (v) => { kinds = v; draw(); }, "Where to look");
  const more = h("p", { class: "muted small" },
    h("button", { class: "link-btn", type: "button", title: "What the harness remembers about this computer: the tools it found and your own notes",
      onclick: () => openMemory({ machine: true }) }, "This computer's memory"));
  setTimeout(() => field.focus(), 0);
  draw();
  return page("Search", "Find any word in your plans, tasks, journal, letters, memory, notes and files.",
    h("div", { class: "stack" }, h("div", { class: "row" }, field), where, status, list, more));
}

function marked(text, words) {
  const terms = (String(words).toLowerCase().match(/"[^"]+"|[\w.+#/-]+/g) || []).map((t) => t.replace(/"/g, "")).filter(Boolean);
  const s = String(text || "");
  if (!terms.length) return [s];
  const out = [];
  const low = s.toLowerCase();
  let i = 0;
  while (i < s.length) {
    let best = -1, len = 0;
    for (const t of terms) { const at = low.indexOf(t, i); if (at >= 0 && (best < 0 || at < best)) { best = at; len = t.length; } }
    if (best < 0) { out.push(s.slice(i)); break; }
    if (best > i) out.push(s.slice(i, best));
    out.push(h("mark", {}, s.slice(best, best + len)));
    i = best + len;
  }
  return out;
}

function hitRow(x, words) {
  return h("li", { class: "sr-hit" }, h("button", { type: "button", title: openTip(x), onclick: () => openHit(x) },
    h("div", { class: "sr-title" }, marked(x.title, words)),
    h("div", { class: "sr-where" }, x.where, x.at ? [" · ", when(x.at)] : null),
    x.snippet ? h("div", { class: "sr-snip" }, marked(x.snippet, words)) : null));
}

function openTip(x) {
  const room = (x.open || {}).room;
  return { project: "Opens the project's plan", file: "Shows the file around the words", memory: "Opens the memory, where you can edit it",
    journal: "Opens the project's journal", letter: "Opens your letters", note: "Opens the saved note", hub_plan: "Opens the plan" }[room] || "Opens it";
}

export async function openHit(x) {
  const o = x.open || {};
  try {
    if (o.room === "project") return goProject(o.path, o.tab || "plan");
    if (o.room === "journal") { location.hash = projectHref(o.agent, "journal"); return; }
    if (o.room === "letter") { location.hash = "#/letters"; return; }
    if (o.room === "hub_plan") {
      await refreshHall();
      const seat = S.rt && S.rt.seats.find((s) => s.hub_name === o.name || s.id === o.name);
      if (seat) { location.hash = projectHref(seat.id, "plan"); return; }
      toast("That project isn't at the table right now. Refresh the Hall and try again.", true); return;
    }
    if (o.room === "note") {
      const d = await get(`/api/note?${q({ name: o.name })}`);
      await dialog({ title: d.title || x.title, body: h("div", { style: "max-height: 60vh; overflow: auto" }, markdown(d.markdown)), yes: "Close", no: null, wide: true });
      return;
    }
    if (o.room === "memory") return openMemory(o);
    if (o.room === "file") return openFile(o, x);
  } catch (e) { toast(e.message, true); }
}

async function goProject(path, tab) {
  await refreshHall();
  const seat = seatByPath(path);
  if (!seat) { toast("That project isn't at the table right now. Refresh the Hall and try again.", true); return; }
  location.hash = projectHref(seat.id, tab === "overview" ? "" : tab);
}

async function openFile(o, x) {
  const p = await get(`/api/search/peek?${q({ path: o.path, file: o.file, line: o.line || 0 })}`);
  const body = p.words ? h("p", {}, p.words) : h("pre", { class: "sr-peek" }, (p.lines || []).map((line, i) => {
    const n = (p.from || 1) + i;
    return h("div", { class: n === p.line ? "on" : "" }, `${String(n).padStart(4)}  ${line}`);
  }));
  const go = await dialog({ title: o.file, text: x.where, body, yes: "Open the project", no: "Close", wide: true });
  if (go) await goProject(o.path, "overview");
}

// The memory file of a project ({path}) or this computer ({machine: true}); {archive: true} shows the older lines.
export async function openMemory(o) {
  const src = o.machine ? { machine: 1 } : { path: o.path };
  if (o.archive) {
    const a = await get(`/api/memory?${q({ ...src, archive: 1 })}`);
    await dialog({ title: `${a.where}: older memory`, text: a.words, wide: true, yes: "Close", no: null,
      body: a.markdown ? h("pre", { class: "sr-peek", style: "white-space: pre-wrap" }, a.markdown) : null });
    return;
  }
  const m = await get(`/api/memory?${q(src)}`);
  const area = h("textarea", { class: "sr-memory", "aria-label": "The memory, as text you can edit", spellcheck: "true" });
  area.value = m.markdown || "";
  const counts = h("p", { class: "muted" }, m.words || "");
  const extra = o.machine ? h("button", { class: "small", type: "button", title: "Looks at which tools this computer has again and writes them under Tools found",
    onclick: (ev) => act(ev.currentTarget, () => post("/api/memory/machine/check", {}), "Looked again", (r) => { area.value = r.markdown; fill(counts, r.words); }) },
  "Check the tools again") : null;
  const body = h("div", { class: "stack" },
    h("p", { class: "muted small" }, "The harness reads this before planning and before each task. Rules never move; when it gets long, the oldest notes move word for word to the archive."),
    counts, area, extra);
  const save = await dialog({ title: `${m.where}: memory`, body, yes: "Save", no: "Cancel", wide: true });
  if (!save) return;
  await act(null, () => post("/api/memory", { ...src, markdown: area.value }),
    (r) => (r.moved ? `Saved. ${r.moved} older line${r.moved === 1 ? "" : "s"} moved to the archive.` : "Saved"));
}

// A small "Memory" button for a project's page (the coordinator places it): opens the editor.
export function memoryButton(path) {
  return h("button", { class: "small", type: "button", title: "What the harness remembers about this project: rules, facts and recent notes. You can edit it.",
    onclick: () => openMemory({ path }).catch((e) => toast(e.message, true)) }, "Memory");
}
