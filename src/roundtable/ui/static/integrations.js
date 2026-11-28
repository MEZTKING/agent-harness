// One list of services (wave 8, p1-reach): every service the harness uses – model makers, picture makers, GitHub,
// web search, tool servers, plug-ins with a saved key – each Ready, Needs a key or Not answering, with Test and
// who uses it. Keys are added in the existing key form; this list never holds one. Plus the MCP catalogue: tool
// servers we have read, each pinned to a version, added with one tick (then tested).
// The API: ui/reachapi.py (/api/integrations, /api/integrations/test, /api/mcp/catalogue, /api/mcp/catalogue/add).
import { h, fill, get, post, act, card, empty, plural } from "./core.js";
import { t as wt } from "./words.js";

const STYLE = `
.svc-list { display: grid; gap: 6px; }
.svc { display: flex; gap: 10px; align-items: center; padding: 8px 10px; border: 1px solid var(--color-line);
  border-radius: var(--radius-small); background: var(--color-surface); }
.svc .grow { min-width: 0; }
.svc-name { font-weight: 600; color: var(--color-text); }
.svc-who { color: var(--color-muted); font-size: 12.5px; }
.svc-group { font-family: var(--font-display); color: var(--color-muted); margin: 10px 0 4px; font-size: 13px; }
.cat-row { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--color-line); }
.cat-row code { font-family: var(--font-mono); color: var(--color-muted); font-size: 12px; word-break: break-all; }
`;
let styled = false;
const style = () => { if (!styled) { document.head.append(h("style", {}, STYLE)); styled = true; } };
const PILL = { ready: "good", missing: "warn", not_answering: "bad", off: "" };

export function integrationsCard() {
  style();
  const box = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  const load = async () => { try { draw(await get("/api/integrations")); } catch (e) { fill(box, h("p", { class: "err" }, e.message)); } };
  const draw = (d) => fill(box,
    h("p", {}, d.words),
    d.rows.length ? d.groups.map((g) => [h("h3", { class: "svc-group" }, g),
      h("div", { class: "svc-list" }, d.rows.filter((r) => r.group === g).map((r) => row(r, load)))]) : empty("Nothing set up yet."));
  load();
  return card("Services", box);
}

function row(r, load) {
  const words = h("span", { class: "small" }, r.words);
  return h("div", { class: "svc" },
    h("span", { class: `pill ${PILL[r.state] || ""}` }, r.state_words),
    h("div", { class: "grow" }, h("div", { class: "svc-name" }, r.name), words,
      r.who && r.who.length ? h("div", { class: "svc-who", title: "Who uses it" }, "Used by " + r.who.join(", ")) : null),
    r.needs && !r.needs.saved ? h("a", { class: "btn small", href: "#/settings", title: wt("Add the {label} key in Settings → Keys", { label: r.needs.label }) }, "Add the key") : null,
    r.can_test ? h("button", { type: "button", class: "small", title: "Ask it something that costs nothing",
      onclick: (ev) => act(ev.currentTarget, () => post("/api/integrations/test", { id: r.id }), (t) => t.words, load) }, "Test") : null);
}

export function mcpCatalogue(after) {
  style();
  const box = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  const load = async () => {
    try {
      const d = await get("/api/mcp/catalogue");
      fill(box, h("p", { class: "small muted" }, wt("Tool servers we have read, each pinned to the version that was read ({checked}). Tick one to add it; it is tested straight away.", { checked: d.checked })),
        d.servers.map((s) => catRow(s, load, after)));
    } catch (e) { fill(box, h("p", { class: "err" }, e.message)); }
  };
  load();
  return card("More tool servers", h("details", { class: "fold" }, h("summary", {}, "Show the list"), box));
}

function catRow(s, load, after) {
  const tick = h("input", { type: "checkbox", checked: s.added, disabled: s.added, "aria-label": wt("Add {name}", { name: s.name }),
    title: s.added ? "Added: see it in Tool servers above" : "Add it, then test it",
    onchange: (ev) => act(ev.target, () => post("/api/mcp/catalogue/add", { id: s.id }),
      (r) => wt("Added {name}. {v1}", { name: s.name, v1: r.test && r.test.words ? r.test.words : "" }), () => { load(); if (after) after(); }) });
  return h("div", { class: "cat-row" }, tick,
    h("div", { class: "grow" }, h("div", { class: "svc-name" }, s.name, s.writes ? h("span", { class: "pill warn", title: "It can change things" }, "Can change things") : null),
      h("div", { class: "small" }, s.about), s.can ? h("div", { class: "small muted" }, "It can: " + s.can) : null,
      s.needs_missing && s.needs_missing.length ? h("div", { class: "small warn" }, "Needs " + s.needs_missing.join(" and ") + " first (Tools above).") : null,
      h("details", {}, h("summary", { class: "small" }, "More"), h("code", {}, s.command),
        s.project_folder ? h("p", { class: "small muted" }, "It works on the project's own folder.") : null)));
}

export const servicesCount = (d) => plural(d.rows.length, "service");
