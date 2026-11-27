// The Browser in the Files tab (DS-81, the desktop side): web pages the project's agents and commands started on
// this computer (http://localhost:5173 and the like), shown in a frame here. View only: it starts nothing and opens
// no port; the page in the frame is sandboxed (no pop-ups, it can't take over the app or reach the harness, its
// own cookies stay its own). Only addresses on this computer are shown, because that's all the app's frame may
// open; localhost is shown through 127.0.0.1. Address bar, back, forward, reload, open in your own browser and
// copy link. API: GET /api/browser (ui/editapi.py).
import { h, fill, get, q, toast, ago } from "./core.js";

const LOCAL = /^(https?):\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d{2,5})?(\/.*)?$/i;

// the address the frame may open ("" when it isn't on this computer)
export function frameUrl(text) {
  let t = String(text || "").trim();
  if (/^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:|\/|$)/i.test(t)) t = "http://" + t;
  if (/^:\d{2,5}/.test(t)) t = "http://127.0.0.1" + t;
  if (/^\d{2,5}$/.test(t)) t = "http://127.0.0.1:" + t;
  const m = t.match(LOCAL);
  if (!m) return "";
  if (m[3] && !(Number(m[3].slice(1)) > 0 && Number(m[3].slice(1)) < 65536)) return "";
  const port = m[3] ? m[3].slice(1) : (m[1].toLowerCase() === "https" ? "443" : "80");
  // never the app itself: a frame on the app's own address would be the app (its pages refuse frames too)
  if (typeof location !== "undefined" && /^(127\.0\.0\.1|localhost|\[::1\])$/i.test(location.hostname)
      && port === (location.port || (location.protocol === "https:" ? "443" : "80"))) return "";
  return `${m[1].toLowerCase()}://127.0.0.1${m[3] || ""}${m[4] || "/"}`;
}

// browserView(path, {start}) -> the element; .open(url) shows a page (for links from Watch and the chat)
export function browserView(path, { start = "" } = {}) {
  browserStyles();
  const back = [], fwd = [];
  let here = "";
  const field = h("input", { type: "text", class: "grow", placeholder: "http://localhost:5173", "aria-label": "Web address on this computer", spellcheck: "false", autocomplete: "off" });
  const frame = h("iframe", { class: "br-frame", title: "The page", sandbox: "allow-scripts allow-forms allow-same-origin allow-downloads", referrerpolicy: "no-referrer" });
  const empty = h("div", { class: "br-empty" }, h("p", { class: "muted" }, "Pick a page below, or type an address on this computer."));
  const stage = h("div", { class: "br-stage" }, empty);
  const list = h("div", { class: "br-list" });
  const note = h("p", { class: "muted small" });
  const b = (label, title, fn) => h("button", { type: "button", title, "aria-label": title, onclick: fn }, label);
  const backBtn = b("←", "Back", () => { if (back.length) { fwd.push(here); show(back.pop(), false); } });
  const fwdBtn = b("→", "Forward", () => { if (fwd.length) { back.push(here); show(fwd.pop(), false); } });
  const reloadBtn = b("⟳", "Load the page again", () => { if (here) { frame.src = "about:blank"; setTimeout(() => { frame.src = here; }, 30); } });
  const openBtn = h("a", { class: "btn", target: "_blank", rel: "noopener noreferrer", title: "Open this page in your own web browser" }, "Open in browser");
  const copyBtn = b("Copy link", "Copy this page's address", async () => {
    try { await navigator.clipboard.writeText(here); toast("Link copied."); } catch { toast("The link couldn't be copied: select the address and copy it.", true); }
  });
  const buttons = () => {
    backBtn.disabled = !back.length || null;
    fwdBtn.disabled = !fwd.length || null;
    for (const x of [reloadBtn, copyBtn]) x.disabled = !here || null;
    if (here) openBtn.setAttribute("href", here); else openBtn.removeAttribute("href");
  };

  function show(url, remember = true) {
    const f = frameUrl(url);
    if (!f) {
      toast("Only pages on this computer open here (like http://localhost:5173). Open other sites in your own browser.", true);
      return;
    }
    if (remember && here && here !== f) { back.push(here); fwd.length = 0; }
    here = f;
    field.value = f;
    frame.src = f;
    if (!frame.isConnected) fill(stage, frame);
    buttons();
  }
  field.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); show(field.value); } });

  const load = async () => {
    let d;
    try { d = await get(`/api/browser?${q({ path })}`); } catch (e) { fill(list, h("p", { class: "bad" }, e.message)); return; }
    note.textContent = d.words || "Pages here can't see the app, your keys or your other projects.";
    if (!d.local) { field.disabled = true; fill(stage, h("div", { class: "br-empty" }, h("p", {}, d.words))); }
    fill(list, d.addresses.length
      ? h("ul", { class: "br-addresses" }, d.addresses.map((a) => h("li", {},
        h("button", { type: "button", class: "br-addr", disabled: !d.local || null, title: `Open ${a.url} here`, onclick: () => show(a.url) },
          h("span", { class: "mono grow" }, a.url), h("span", { class: "muted small" }, [a.from, a.at ? ago(a.at) : ""].filter(Boolean).join(" · "))))))
      : h("p", { class: "muted small" }, "No local pages yet: when a task starts a web server, its address shows here."));
    if (start && d.local) show(start);
  };

  const box = h("div", { class: "br" },
    h("div", { class: "row br-bar" }, backBtn, fwdBtn, reloadBtn, field, b("Go", "Open this address", () => show(field.value)), openBtn, copyBtn),
    stage, note, h("h3", { class: "br-h" }, "Pages the project started"), list);
  box.open = (url) => show(url);
  buttons();
  load();
  return box;
}

export function browserStyles() {
  if (typeof document === "undefined" || document.getElementById("br-style")) return;
  document.head.append(h("style", { id: "br-style" }, `
.br { display: flex; flex-direction: column; gap: 10px; }
.br-bar { gap: 6px; align-items: center; flex-wrap: wrap; }
.br-bar input { min-width: 12em; font-family: var(--font-mono); }
.br-stage { border: 1px solid var(--color-line-strong); border-radius: var(--radius-small); overflow: hidden; background: var(--color-paper); }
.br-frame { display: block; width: 100%; height: 62vh; border: 0; background: var(--color-paper); }
.br-empty { padding: 32px 16px; text-align: center; background: var(--color-surface); }
.br-h { font-size: 15px; margin-top: 6px; }
.br-addresses { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.br-addr { display: flex; gap: 10px; width: 100%; text-align: left; background: none; border: 0; padding: 6px 8px; border-radius: var(--radius-small); color: var(--color-text); }
.br-addr:hover { background: var(--color-raised); }
`));
}
