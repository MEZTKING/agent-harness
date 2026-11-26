// Watch and App: following the work like a session (every step, changes in colour, pictures) and the app itself.
import { h, fill, get, every, card, money, ago, jobName, modelName, taskPill, picture, fileSize, q, prose } from "./core.js";
import { hubSession } from "./machines.js";

const rawUrl = (kind, path, name, task) => `/raw/${kind}?` + new URLSearchParams({ path, name, ...(task ? { task } : {}) });
const shotUrl = (path, rec, kind) => rawUrl("shot", path, (rec.pictures || {})[kind] || `${kind}.png`, rec.dir || rec.task);
const SHOT_NAMES = { desktop: "Computer", phone: "Phone", dark: "Dark", start: "Early on", middle: "Halfway" };

export async function watchTab(seat, now) {
  const term = h("div", { class: "term", role: "log", "aria-live": "polite" }, h("p", { class: "t-meta" }, "Loading…"));
  const outs = h("div");
  const details = h("div");
  const open = new Set();
  let cursor = 0, stick = true;
  term.addEventListener("scroll", () => { stick = term.scrollHeight - term.scrollTop - term.clientHeight < 40; });
  term.addEventListener("load", () => { if (stick) term.scrollTop = term.scrollHeight; }, true);
  const status = h("span", { class: "muted small" });
  const box = h("div", { class: "watch" },
    h("section", { class: "card term-card" }, h("div", { class: "card-head" }, h("h2", {}, "The work, step by step"), status), term),
    outs, details);
  const path = seat.path;
  return every(box, async () => {
    const s = now();
    status.textContent = s.status === "running" ? "Following it live" : "";
    let d;
    if (path) d = await get(`/api/project/session?${q({ path, since: cursor })}`);
    else {
      d = await hubSession(s);
      if (!d) { fill(term, h("p", { class: "t-meta" }, "Another computer builds this project. Its steps show here when that computer shares them through the hub.")); return false; }
    }
    if (d.changed === false) return;
    cursor = d.cursor || 0;
    fill(outs, (d.outputs || []).length ? card("What it made", h("p", { class: "muted small" }, "Pictures and files the project made, newest first."), outputList(path, d.outputs)) : null);
    fill(term, (d.tasks || []).length ? d.tasks.map((t, i) => h("div", { class: "t-task" },
      h("div", { class: "t-head" }, h("span", { class: "t-prompt" }, "▶"), h("b", {}, t.title || t.id), h("span", { class: "t-meta" }, ` · ${jobName(t.role)}`),
        h("span", { class: "spacer" }), taskPill(t.status), t.cost ? h("span", { class: "t-cost", title: "What this task cost" }, money(t.cost)) : null),
      t.steps.map((st, j) => stepNode(path, st, `${i}:${j}`, open)),
      t.outputs && t.outputs.length ? h("div", { class: "t-outs" }, outputList(path, t.outputs)) : null))
      : h("p", { class: "t-meta" }, "Nothing yet: the steps appear here as soon as the first task starts."));
    if (stick) term.scrollTop = term.scrollHeight;
    if (path && !details.firstChild) fill(details, await moreDetails(path));
  }, () => (now().status === "running" ? 2500 : 20000));
}

function stepNode(path, s, key, open) {
  const cost = s.cost ? h("span", { class: "t-cost", title: "What this model turn cost" }, money(s.cost)) : null;
  if (s.kind === "say") return h("div", { class: "t-say" + (s.who === "reviewer" ? " rev" : "") }, h("span", { class: "t-dot" }, "⏺"),
    h("div", {}, s.who === "reviewer" ? h("b", {}, "Reviewer  ") : null, s.text), cost);
  if (s.kind === "attempt") { const n = (String(s.text).match(/Attempt (\d+)/) || [])[1]; return h("div", { class: "t-meta" }, n && n !== "1" ? `Try ${n}, with ${modelName(s.model)}` : `Working with ${modelName(s.model)}`); }
  if (s.kind === "review") return h("div", { class: "t-review " + (s.approved ? "ok" : "no") }, s.approved ? "✓ Approved" : "✗ Sent back", h("span", {}, "  " + (s.text || "")));
  if (s.kind === "finish") return h("div", { class: "t-meta" }, "✓ Finished: ", s.text);
  if (s.kind === "error") return h("div", { class: "t-review no" }, "! A model didn't answer: ", String(s.text).replace(/^[^:]+\/[^:]+:\s*/, ""));
  if (s.kind === "shots") {
    const rec = { dir: s.dir || s.task, task: s.task, pictures: {} };
    return h("div", { class: "t-shots" }, h("div", { class: "t-meta" }, s.pictures.length ? `Pictures of the app${s.errors ? ` · the page reported ${s.errors} error${s.errors > 1 ? "s" : ""}` : ""}` : `No pictures: ${s.note}`),
      s.pictures.length && path ? h("div", { class: "strip" }, s.pictures.map((k) => picture(shotUrl(path, rec, k), `${SHOT_NAMES[k] || k} · after this task`))) : null);
  }
  const body = s.diff ? diffView(s.diff) : s.output ? h("pre", { class: "t-out" }, s.output) : null;
  const line = [h("span", { class: "t-dot" + (s.error ? " bad" : "") }, "●"), h("b", {}, s.label), s.detail ? h("span", { class: "t-detail" + (s.error ? " bad" : "") }, " · " + s.detail) : null, cost];
  if (!body) return h("div", { class: "t-tool" }, line);
  const det = h("details", { class: "t-tool", open: open.has(key) }, h("summary", { title: "Show what it did" }, line), body);
  det.addEventListener("toggle", () => (det.open ? open.add(key) : open.delete(key)));
  return det;
}
function diffView(text) {
  return h("pre", { class: "diff" }, String(text || "").split("\n").map((ln) => h("span", { class:
    ln.startsWith("+++") || ln.startsWith("---") ? "dh" : ln.startsWith("@@") ? "dk" : ln.startsWith("+") ? "da" : ln.startsWith("-") ? "dd" : "" }, ln + "\n")));
}
function outputList(path, outs) {
  if (!path) return null;
  const pics = outs.filter((o) => o.kind === "image"), files = outs.filter((o) => o.kind !== "image");
  return [pics.length ? h("div", { class: "strip outs" }, pics.slice(0, 24).map((o) => h("figure", {}, picture(rawUrl("file", path, o.path), o.path), h("figcaption", {}, o.path.split("/").pop())))) : null,
    files.length ? h("ul", { class: "files" }, files.map((o) => h("li", {}, h("a", { href: rawUrl("file", path, o.path), download: o.path.split("/").pop(), title: "Save this file" }, "⤓ ", o.path),
      h("span", { class: "muted small" }, ` ${fileSize(o.size)}`)))) : null];
}
async function moreDetails(path) {
  let d;
  try { d = await get(`/api/project?${q({ path })}`); } catch { return null; }
  return h("details", { class: "card fold" }, h("summary", { title: "The full record, for when you want every detail" }, "Every detail"),
    h("h3", {}, "The full log"), h("pre", { class: "log" }, d.events.map((e) => `${(e.at || "").slice(11, 16)}  ${e.text}`).join("\n") || "Empty"),
    h("h3", {}, `Its files (${d.files.length})`), h("pre", { class: "log short" }, d.files.join("\n") || "None yet"));
}

// ---------- App: the real app running, and its pictures ----------
export async function appTab(seat, now) {
  const box = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
  let sig = "";
  return every(box, async () => {
    const L = await get(`/api/project/live?${q({ path: seat.path })}`);
    const s = JSON.stringify([L.latest && L.latest.at, L.history.length, L.preview, L.entry]);
    if (s !== sig) { sig = s; fill(box, liveApp(L), livePictures(seat.path, L)); }
  }, () => (now().status === "running" ? 4000 : 15000));
}
function liveApp(L) {
  if (!L.preview) {
    return card("The app", h("p", { class: "muted" }, L.entry ? "The app opens here in the Roundtable Hold desktop app." : "Nothing to open yet: the app's first page hasn't been made."),
      L.start_command ? h("p", { class: "small muted" }, "It has its own way of starting: Roundtable shows its page as it is for now.") : null);
  }
  const frame = h("iframe", { class: "live-frame", src: L.preview, title: "The app, live", sandbox: "allow-scripts allow-same-origin allow-forms" });
  const wrap = h("div", { class: "live-wrap" }, frame);
  const size = (phone) => { wrap.classList.toggle("phone", phone); sizes.querySelectorAll("button").forEach((b) => { const on = (b.dataset.k === "phone") === phone; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }); };
  const sizes = h("div", { class: "seg", role: "group", "aria-label": "Screen size" },
    h("button", { type: "button", class: "on", "aria-pressed": "true", "data-k": "desktop", title: "As wide as this window", onclick: () => size(false) }, "Computer"),
    h("button", { type: "button", "aria-pressed": "false", "data-k": "phone", title: "As wide as a phone", onclick: () => size(true) }, "Phone"));
  return card(h("div", { class: "card-head" }, h("h2", {}, "The app, live"),
    h("div", { class: "row" }, sizes,
      h("button", { class: "small", title: "Load the app again (after a task changed it)", onclick: () => { frame.src = L.preview; } }, "Reload"),
      h("a", { class: "btn small", href: L.preview, target: "_blank", rel: "noopener", title: "Open the app in its own window" }, "Open in a window"))),
  h("p", { class: "small muted" }, "The real app, running from its folder. It can't reach the internet or Roundtable itself."),
  wrap);
}
function livePictures(path, L) {
  const rec = L.latest;
  if (!rec) return card("Pictures", h("p", { class: "muted" }, "Roundtable takes pictures of the app after every finished task. None yet."));
  const kinds = Object.keys(rec.pictures || {}), errs = rec.errors || [];
  const earlier = (L.history || []).filter((r) => Object.keys(r.pictures || {}).length);
  return card(h("div", { class: "card-head" }, h("h2", {}, "Pictures"), h("span", { class: "muted small" }, rec.title ? `after “${rec.title}”` : "after the newest task", ` · ${ago(rec.at)}`)),
    kinds.length ? h("div", { class: "shots" }, kinds.map((k) => h("figure", { class: "shot " + k }, picture(shotUrl(path, rec, k), SHOT_NAMES[k] || k), h("figcaption", {}, SHOT_NAMES[k] || k))))
      : h("p", { class: "muted" }, rec.failed || rec.note || "No pictures this time."),
    kinds.length && rec.note ? h("p", { class: "small muted" }, rec.note) : null,
    errs.length ? h("details", {}, h("summary", { title: "Errors the page wrote while the pictures were taken" }, `The page reported ${errs.length} error${errs.length > 1 ? "s" : ""}`), h("pre", { class: "log short" }, errs.join("\n"))) : null,
    earlier.length > 1 ? [h("h3", {}, "Earlier"), h("div", { class: "strip" }, earlier.map((r) => h("figure", {}, picture(shotUrl(path, r, "desktop"), r.title || "An earlier picture"),
      h("figcaption", {}, r.title || "", h("span", { class: "muted" }, " " + ago(r.at))))))] : null);
}
