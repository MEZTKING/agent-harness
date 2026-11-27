// Search by meaning, asking a question, your documents and the memory picture (ui/recallapi.py).
// askBox(): the "Ask" box for the top of the Search page. documentsPage(): the "Your documents" tab.
// memoryPicture(): the "Who knows what" tab. Each brings its own looks (theme tokens only, no pictures).
import { h, fill, get, post, act, toast, dialog, card, empty, money, plural, when, BRAND } from "./core.js";

const CSS = `
.rc-ask { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rc-ask input { flex: 1 1 260px; padding: 8px 12px; border-radius: var(--radius-small); border: 1px solid var(--color-line);
  background: var(--color-surface); color: var(--color-text); font: inherit; }
.rc-answer { margin-top: 10px; }
.rc-quote { border-left: 3px solid var(--color-accent); padding: 4px 10px; margin: 8px 0; }
.rc-src { color: var(--color-muted); font-size: 13px; }
.rc-piece { border-top: 1px solid var(--color-line); padding: 8px 2px; }
.rc-piece:first-child { border-top: 0; }
.rc-piece p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; }
.rc-drop { border: 2px dashed var(--color-line); border-radius: var(--radius); padding: 22px; text-align: center; }
.rc-drop.on { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 8%, transparent); }
.rc-doc { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--color-line); padding: 10px 2px; }
.rc-doc:first-child { border-top: 0; }
.rc-doc .grow { flex: 1 1 200px; }
.rc-tag { font-size: 12.5px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--color-line); color: var(--color-muted); }
.rc-svg { width: 100%; height: auto; max-height: 70vh; }
.rc-svg line { stroke: var(--color-line); stroke-linecap: round; }
.rc-svg line.checked { stroke: var(--color-accent); }
.rc-svg line.used { stroke: var(--color-good); }
.rc-svg circle { stroke: var(--color-background); stroke-width: 2; }
.rc-svg .n-agent circle, .rc-svg .n-job circle { fill: var(--color-accent); }
.rc-svg .n-project circle { fill: var(--color-flare); }
.rc-svg .n-document circle { fill: var(--color-good); }
.rc-svg .n-topic circle { fill: var(--color-warn); }
.rc-svg .n-seat circle { fill: var(--color-muted); }
.rc-svg text { fill: var(--color-text); font: 12px var(--font-body); }
.rc-key { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; color: var(--color-muted); }
.rc-key i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.rc-key .k-agent { background: var(--color-accent); } .rc-key .k-project { background: var(--color-flare); }
.rc-key .k-document { background: var(--color-good); } .rc-key .k-topic { background: var(--color-warn); }
`;
function addLooks() {
  if (document.getElementById("rc-css")) return;
  document.head.append(h("style", { id: "rc-css" }, CSS));
}

const more = (summary, ...kids) => h("details", {}, h("summary", { title: "Show the details" }, summary || "More"), ...kids);

// a piece's date: a day only ("2026-11-27") says today, yesterday or the day; a full time says how long ago
function day(at) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(at))) return when(at);
  const d = new Date(`${at}T12:00:00`), now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  const words = days === 0 ? "today" : days === 1 ? "yesterday" : d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  return h("time", { datetime: at }, words);
}

function pieceRow(p) {
  return h("div", { class: "rc-piece" },
    h("div", {}, h("strong", {}, p.title), p.private ? h("span", { class: "rc-tag", title: "This one is never given to a model" }, " Never leaves this computer") : null),
    h("div", { class: "rc-src" }, p.kind_words, " · ", p.where, p.at ? [" · ", day(p.at)] : null),
    h("p", {}, p.text));
}

// ---------- Ask ----------
export function askBox() {
  addLooks();
  const field = h("input", { type: "text", placeholder: "Ask: what did we decide about…?", "aria-label": "Your question",
    autocomplete: "off", maxlength: "500" });
  const out = h("div", { class: "rc-answer", "aria-live": "polite" });
  const findBtn = h("button", { type: "button", class: "btn", title: "Search by meaning, on this computer. Free: nothing is sent anywhere." }, "Find");
  const askBtn = h("button", { type: "button", class: "btn primary", title: "A cheap model answers from what's found, with quotes. You see the price first." }, "Ask");
  const showPieces = (pieces) => pieces.length ? more(`What was found (${pieces.length})`, pieces.map(pieceRow)) : null;
  findBtn.addEventListener("click", () => act(findBtn, async () => {
    const text = field.value.trim();
    if (!text) return toast("Write what you're looking for first.", true);
    const res = await get(`/api/recall?q=${encodeURIComponent(text)}`);
    fill(out, h("p", { class: "muted" }, res.words), (res.pieces || []).map(pieceRow));
  }));
  askBtn.addEventListener("click", () => act(askBtn, async () => {
    const question = field.value.trim();
    if (!question) return toast("Write your question first.", true);
    const quote = await post("/api/recall/ask", { question });
    if (!quote.price_usd && quote.price_usd !== null) {  // nothing to send: shown as it is
      fill(out, h("p", {}, quote.words), (quote.pieces || []).map(pieceRow));
      return;
    }
    const price = quote.price_usd === null ? "an unknown price" : `about ${money(quote.price_usd)}`;
    const ok = await dialog({ title: "Ask a model?", yes: "Ask",
      text: `This costs ${price}. ${quote.model_label || "A cheap model"} answers from ${plural((quote.pieces || []).length - (quote.held || 0), "piece")} of your own things.`
        + (quote.held ? ` ${plural(quote.held, "piece")} stay on this computer.` : "") });
    if (!ok) return;
    const res = await post("/api/recall/ask", { question, confirm: true });
    fill(out,
      res.answer ? h("p", {}, res.answer) : h("p", {}, res.words),
      (res.quotes || []).map((x) => h("blockquote", { class: "rc-quote" }, h("div", {}, `“${x.text}”`),
        h("div", { class: "rc-src", title: x.found ? "These words are in the source" : "The model's words: check the source" }, x.source, x.found ? "" : " (not word for word)"))),
      h("p", { class: "muted small" }, res.words, res.cost_usd ? ` Cost ${money(res.cost_usd)}.` : ""),
      showPieces(res.pieces || []),
      res.model ? more("Which model", h("p", { class: "muted small" }, res.model)) : null);
  }));
  field.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); findBtn.click(); } });
  return card("Ask about anything", h("p", { class: "muted small", title: "Words that mean the same are found too, such as sign-in and login. It all stays on this computer until you tap Ask." },
    "Search by meaning (on this computer)"), h("div", { class: "rc-ask" }, field, findBtn, askBtn), out);
}

// ---------- Your documents ----------
function readFile(file) {
  return new Promise((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",", 2)[1] || "");
    r.onerror = () => bad(new Error("That file couldn't be read. Try again."));
    r.readAsDataURL(file);
  });
}

function whoPicker(projects, current, onpick) {
  const all = current === "all";
  const box = h("div", { class: "stack" });
  const allBox = h("input", { type: "checkbox", checked: all });
  const ticks = projects.map((p) => [p, h("input", { type: "checkbox", checked: !all && (current || []).includes(p.id) })]);
  const send = () => onpick(allBox.checked ? "all" : ticks.filter(([, t]) => t.checked).map(([p]) => p.id));
  allBox.addEventListener("change", send);
  ticks.forEach(([, t]) => t.addEventListener("change", () => { allBox.checked = false; send(); }));
  fill(box, h("label", {}, allBox, " All projects"), ticks.map(([p, t]) => h("label", {}, t, " ", p.name)));
  return box;
}

export async function documentsPage() {
  addLooks();
  const host = h("div", { class: "stack" });
  const draw = async (data) => {
    data = data || await get("/api/documents");
    const list = data.documents || [];
    const drop = h("div", { class: "rc-drop", tabindex: "0", title: "Text, Markdown, web pages, CSV, JSON, Word (.docx) or PDF (found by its name)" },
      h("p", {}, "Drop files here"), h("p", { class: "muted small" }, "Your agents look them up instead of guessing."));
    const picker = h("input", { type: "file", multiple: true, hidden: true });
    const upload = async (files) => {
      for (const f of files) {
        try { data = await post("/api/documents", { action: "add", name: f.name, data: await readFile(f) }); toast(`Added ${f.name}`); }
        catch (e) { toast(e.message, true); }
      }
      draw(data);
    };
    drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("on"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("on"));
    drop.addEventListener("drop", (ev) => { ev.preventDefault(); drop.classList.remove("on"); upload([...ev.dataTransfer.files]); });
    drop.addEventListener("click", () => picker.click());
    drop.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); picker.click(); } });
    picker.addEventListener("change", () => upload([...picker.files]));
    const linkBtn = h("button", { type: "button", class: "btn", title: "Its files are read where they are. Nothing is written into it." }, "Link a folder");
    linkBtn.addEventListener("click", async () => {
      const folder = await dialog({ title: "Link a folder", text: "Paste the folder's path. Its files are read where they are, never changed.",
        yes: "Link", input: { placeholder: "C:\\Users\\you\\Documents\\Notes" } });
      if (!folder) return;
      try { draw(await post("/api/documents", { action: "link", folder })); } catch (e) { toast(e.message, true); }
    });
    const rows = list.map((d) => {
      const priv = h("input", { type: "checkbox", checked: !!d.private });
      priv.addEventListener("change", async () => {
        try { data = await post("/api/documents", { action: "change", id: d.id, private: priv.checked }); toast(priv.checked ? "It never leaves this computer now." : "Your agents may look it up now."); }
        catch (e) { toast(e.message, true); }
      });
      const rm = h("button", { type: "button", class: "btn", title: "Moved aside, not deleted" }, "Remove");
      rm.addEventListener("click", async () => {
        if (!await dialog({ title: `Remove ${d.title}?`, text: "It's moved aside, not deleted. Your agents stop looking it up.", yes: "Remove" })) return;
        try { draw(await post("/api/documents", { action: "remove", id: d.id })); } catch (e) { toast(e.message, true); }
      });
      return h("div", { class: "rc-doc" },
        h("div", { class: "grow" }, h("strong", {}, d.title), h("div", { class: "rc-src" }, d.kind_words, " · ", d.who, d.note ? ` · ${d.note}` : "")),
        h("label", { title: "Shown in your own search, never given to a model" }, priv, " Never leaves this computer"),
        rm,
        more("Who may use it", whoPicker(data.projects || [], d.projects, async (v) => {
          try { data = await post("/api/documents", { action: "change", id: d.id, projects: v }); } catch (e) { toast(e.message, true); }
        })));
    });
    fill(host, h("p", {}, data.words), drop, picker, h("div", { class: "row" }, linkBtn),
      list.length ? card(null, rows) : null,
      data.removed ? h("p", { class: "muted small" }, `${plural(data.removed, "document")} moved aside.`) : null);
  };
  try { await draw(); } catch (e) { fill(host, empty(e.message)); }
  return host;
}

// ---------- Who knows what ----------
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  kids.flat().forEach((k) => k && el.append(k instanceof Node ? k : document.createTextNode(String(k))));
  return el;
}

function layout(nodes) {
  // the projects in the middle ring, the agents and jobs on the left arc, documents on the right, topics below
  const W = 760, H = 460, pos = {};
  const groups = { project: [], agent: [], job: [], document: [], topic: [], seat: [] };
  nodes.forEach((n) => (groups[n.kind] || groups.seat).push(n));
  // ellipses that fit the picture (a circle as wide as the picture would put the ends of an arc outside it)
  const arc = (list, cx, cy, rx, ry, from, to) => list.forEach((n, i) => {
    const a = list.length === 1 ? (from + to) / 2 : from + (to - from) * (i / (list.length - 1));
    pos[n.id] = [cx + rx * Math.cos(a), cy + ry * Math.sin(a)];
  });
  arc(groups.project, W / 2, H / 2 - 20, 90, 90, -Math.PI * 0.9, Math.PI * 0.9);
  arc([...groups.agent, ...groups.job, ...groups.seat], W / 2, H / 2 - 20, 290, H / 2 - 50, Math.PI * 0.65, Math.PI * 1.35);
  arc(groups.document, W / 2, H / 2 - 20, 250, H / 2 - 50, -Math.PI * 0.35, Math.PI * 0.35);
  arc(groups.topic, W / 2, H - 30, 230, Math.PI, Math.PI * 2);
  groups.topic.forEach((n, i) => { pos[n.id] = [120 + i * ((W - 240) / Math.max(1, groups.topic.length - 1)), H - 24]; });
  return { W, H, pos };
}

export async function memoryPicture() {
  addLooks();
  const host = h("div", { class: "stack" });
  let g;
  try { g = await get("/api/recall/graph"); } catch (e) { return fill(host, empty(e.message)); }
  if (!(g.nodes || []).length) return fill(host, empty(g.sentence || "Nothing to show yet."));
  g.nodes.forEach((n) => { if (n.kind === "topic") n.label = String(n.label).replace(/^[\w-]+:/, "").replace(/[-_]/g, " "); });  // "kind:website" → "website"
  const { W, H, pos } = layout(g.nodes);
  const top = Math.max(1, ...g.edges.map((e) => e.count));
  const svg = s("svg", { class: "rc-svg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": g.sentence },
    g.edges.filter((e) => pos[e.from] && pos[e.to]).map((e) => s("line", { x1: pos[e.from][0], y1: pos[e.from][1], x2: pos[e.to][0], y2: pos[e.to][1],
      class: e.kind, "stroke-width": String(1 + 5 * (e.count / top)) }, s("title", {}, e.words))),
    g.nodes.filter((n) => pos[n.id]).map((n) => s("g", { class: `n-${n.kind}` },
      s("circle", { cx: pos[n.id][0], cy: pos[n.id][1], r: String(7 + Math.min(10, Math.sqrt(n.weight || 1) * 2)) }, s("title", {}, n.label)),
      s("text", { x: pos[n.id][0] + 14, y: pos[n.id][1] + 4 }, n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label))));
  fill(host, h("p", {}, g.sentence), card(null, svg,
    h("div", { class: "rc-key", "aria-hidden": "true" }, [["agent", "Agents and jobs"], ["project", "Projects"], ["document", "Your documents"], ["topic", "Busiest topics"]]
      .map(([k, t]) => h("span", {}, h("i", { class: `k-${k}` }), t)))),
    more("The same as a list", h("ul", {}, (g.lines || []).map((l) => h("li", {}, l)))));
  return host;
}

export const RECALL_NAME = `${BRAND.short}: search by meaning (on this computer)`;
