// Tools: what this computer has for building things (found or not, with Install), and the tool servers
// (MCP) that let helpers work inside other programs, each given to the jobs that use it.
// The API is ui/toolsapi.py (GET /api/tools and POST /api/tools/...); read loosely so a missing field never breaks it.
import { h, fill, get, post, act, toast, dialog, page, card, empty, jobName, has } from "./core.js";
import { webSearchCard } from "./websearch.js";
import { marketPage } from "./market.js";
import { integrationsCard, mcpCatalogue } from "./integrations.js";
import { t as wt } from "./words.js";

const ROW = "padding: 10px 0; border-top: 1px solid var(--color-line)";  // no stylesheet change: style.css isn't this page's
const STATE = { found: ["Found", "good"], old: ["Too old", "warn"], broken: ["Didn't start", "bad"], missing: ["Not found", ""] };
const pill = (state) => { const [w, c] = STATE[state] || STATE.missing; return h("span", { class: "pill " + c }, w); };

export async function viewTools() {
  const body = h("div", { class: "stack" });
  const draw = async (fresh = false) => {
    let t;
    try { t = fresh ? await post("/api/tools/check", {}) : await get("/api/tools"); }
    catch (e) { fill(body, card("Tools", h("p", {}, e.message))); return; }
    const web = await has("/api/websearch") ? await webSearchCard().catch(() => null) : null;  // look things up on the web
    // the list of plug-ins and skills, and Make one (plugins/market.py, ui/marketapi.py)
    const market = await has("/api/market") ? card("Plug-ins and skills", await marketPage().catch((e) => h("p", { class: "muted" }, e.message))) : null;
    // one list of every service it can reach, and the pinned tool servers to add with a tick (ui/reachapi.py)
    const [svc, cat] = await Promise.all([has("/api/integrations"), has("/api/mcp/catalogue")]);
    fill(body, summary(t, draw), groups(t, draw), svc ? integrationsCard() : null, web, market, servers(t, draw),
      cat ? mcpCatalogue(() => draw()) : null);
  };
  await draw();
  return page("Tools", "What this computer has for building apps and games.", body);
}

function summary(t, draw) {
  const missing = (t.tools || []).filter((x) => x.state !== "found");
  const text = missing.length ? `${missing.length} of ${(t.tools || []).length} not ready: press Install on the ones your projects need.`
    : "Everything is here.";
  return h("div", { class: "row" }, h("p", { class: "grow" }, text),
    h("button", { class: "small", title: "Looks for every tool again (after you installed something yourself, say)",
      onclick: (ev) => act(ev.currentTarget, () => draw(true), "Looked again") }, "Check again"));
}

function groups(t, draw) {
  const by = {};
  for (const x of t.tools || []) (by[x.group] = by[x.group] || []).push(x);
  return (t.groups || Object.keys(by)).filter((g) => by[g]).map((g) => card(g, by[g].map((x) => toolRow(x, t, draw))));
}

function toolRow(x, t, draw) {
  const log = h("pre", { class: "log small", hidden: true, "aria-live": "polite" });
  const inst = x.install || {};
  let action = null;
  if (x.state !== "found" && inst.can) {
    const label = x.state === "old" ? "Update" : "Install";
    action = h("button", { class: "small primary", disabled: !!inst.blocked, title: inst.blocked || wt("Installs {name} on this computer{v1}", { name: x.name, v1: inst.admin ? " (Windows asks you to allow it)" : "" }),
      onclick: (ev) => install(ev.currentTarget, x, log, draw) }, label);
  }
  const more = h("details", {}, h("summary", { class: "small muted" }, "More"),
    h("dl", { class: "small" },
      x.where ? [h("dt", {}, "Where"), h("dd", {}, x.where)] : null,
      x.detail ? [h("dt", {}, "Also"), h("dd", {}, x.detail)] : null,
      (x.also || []).length ? [h("dt", {}, "Other copies"), h("dd", {}, x.also.join("; "))] : null,
      x.min_version ? [h("dt", {}, "Needs"), h("dd", {}, wt("{min_version} or newer", { min_version: x.min_version }))] : null,
      inst.shown ? [h("dt", {}, "Install command"), h("dd", {}, h("code", {}, inst.shown))] : null,
      inst.note ? [h("dt", {}, "After installing"), h("dd", {}, inst.note)] : null));
  return h("div", { class: "tool-row", id: `tool-${x.id}`, style: ROW },
    h("div", { class: "row" }, h("b", { title: x.why }, x.name), pill(x.state),
      x.version ? h("span", { class: "muted small" }, x.version) : null, h("span", { class: "spacer grow" }), action),
    h("p", { class: "muted small" }, x.state === "found" ? x.why : (inst.blocked || (inst.can ? x.why : inst.text) || x.why)),
    more, log);
}

async function install(btn, x, log, draw) {
  let r = await act(btn, () => post("/api/tools/install", { tool: x.id }));
  if (!r) return;
  if (r.confirm) {
    if (!(await dialog({ title: r.title || wt("Install {name}?", { name: x.name }), text: r.confirm, yes: "Install" }))) return;
    r = await act(btn, () => post("/api/tools/install", { tool: x.id, confirm: true }));
    if (!r) return;
  }
  await follow(r, btn, log, draw);
}

// shows a background job's log under the row until it ends, then looks again
async function follow(job, btn, log, draw) {
  if (!job || !job.id) return;
  log.hidden = false;
  btn.disabled = true;
  const lines = [];
  let since = 0;
  for (;;) {
    let j;
    try { j = await get(`/api/jobs/${encodeURIComponent(job.id)}?since=${since}`); } catch (e) { toast(e.message, true); break; }
    lines.push(...(j.log || []).map((l) => l.replace(/^\d\d:\d\d:\d\d\s+/, "")));
    since = j.log_size || since;
    log.textContent = lines.slice(-12).join("\n");
    if (j.status !== "running") {
      const words = (j.result && j.result.words) || j.error || "Finished.";
      toast(words, j.status !== "done" || (j.result && j.result.ok === false));
      break;
    }
    if (!log.isConnected) return;
    await new Promise((r) => setTimeout(r, 1500));
  }
  if (btn.isConnected) btn.disabled = false;
  await draw(true);
}

// ---------- tool servers (MCP) ----------
function servers(t, draw) {
  if (t.servers_error) return card("Tool servers", h("p", {}, t.servers_error));
  const list = (t.servers || []).map((s) => serverRow(s, t, draw));
  const add = (t.known || []).map((k) => h("div", { class: "tool-row", style: ROW },
    h("div", { class: "row" }, h("b", { title: k.about }, k.name), k.added ? h("span", { class: "pill good" }, "added") : null,
      h("span", { class: "spacer grow" }),
      k.prepare ? h("button", { class: "small", title: "Puts the add-on it needs into Blender (once)",
        onclick: (ev) => { const b = ev.currentTarget;
          act(b, () => post("/api/tools/servers/prepare", { known: k.id }), null, (j) => follow(j, b, b.closest(".tool-row").querySelector("pre"), draw)); } }, "Put it in Blender") : null,
      k.added ? null : h("button", { class: "small primary", title: wt("Adds {name} so you can give it to a job", { name: k.name }),
        onclick: (ev) => act(ev.currentTarget, () => post("/api/tools/servers/add", { known: k.id }), wt("{name} added", { name: k.name }), () => draw()) }, "Add")),
    h("p", { class: "muted small" }, k.about),
    h("details", {}, h("summary", { class: "small muted" }, "How to turn it on"), h("p", { class: "small" }, k.steps)),
    h("pre", { class: "log small", hidden: true })));
  return card("Tool servers",
    h("p", { class: "muted small" }, "Programs that let your helpers work inside other apps, such as Unreal, Godot and Blender."),
    list.length ? list : empty("No tool servers yet. Add one below."),
    h("h3", {}, "Add one"), add,
    h("div", { class: "row" }, h("button", { class: "small", title: "A server that isn't on the list: its program or its address",
      onclick: (ev) => addOwn(ev.currentTarget, draw) }, "Add your own…")));
}

function serverRow(s, t, draw) {
  const out = h("p", { class: "small", "aria-live": "polite" });
  const jobs = (s.jobs || []).length ? `Used by: ${s.jobs.join(", ")}` : "No job uses it yet.";
  return h("div", { class: "tool-row", style: ROW },
    h("div", { class: "row" }, h("b", { title: s.where }, s.name), s.enabled === false ? h("span", { class: "pill" }, "off") : null,
      h("span", { class: "muted small grow" }, jobs),
      h("button", { class: "small", title: "Starts it (or reaches it) and lists its tools",
        onclick: (ev) => { out.className = "small"; out.textContent = "Testing… (up to a minute)";
          act(ev.currentTarget, () => post("/api/tools/servers/test", { name: s.name }), null, (r) => {
            out.className = "small " + (r.ok ? "good" : "bad"); out.textContent = r.words; }); } }, "Test"),
      h("button", { class: "small", title: "Choose which jobs may use its tools", onclick: (ev) => give(ev.currentTarget, s, t, draw) }, "Give to a job"),
      s.removable ? h("button", { class: "small danger", onclick: async (ev) => {
        if (await dialog({ title: wt("Remove {name}?", { name: s.name }), text: "Jobs that use it stop getting its tools.", yes: "Remove", danger: true }))
          act(ev.currentTarget, () => post("/api/tools/servers/remove", { name: s.name }), "Removed", () => draw());
      } }, "Remove") : null),
    h("details", {}, h("summary", { class: "small muted" }, "More"), h("p", { class: "small" }, h("code", {}, s.where)),
      s.removable ? null : h("p", { class: "small muted" }, "Set in the harness's settings file, so it's changed there.")),
    out);
}

async function give(btn, s, t, draw) {
  const boxes = (t.jobs || []).map((j) => {
    const box = h("input", { type: "checkbox", value: j.role, checked: (s.roles || []).includes(j.role) });
    return h("label", { class: "row" }, box, j.name || jobName(j.role));
  });
  const ok = await dialog({ title: wt("Which jobs use {name}?", { name: s.name }), text: "Ticked jobs get its tools while they work.",
    yes: "Save", body: h("div", { class: "stack" }, boxes) });
  if (!ok) return;
  const roles = boxes.map((l) => l.querySelector("input")).filter((b) => b.checked).map((b) => b.value);
  await act(btn, () => post("/api/tools/servers/give", { name: s.name, roles }), (r) => r.jobs.length ? wt("Given to {v1}", { v1: r.jobs.join(", ") }) : "No job uses it now", () => draw());
}

async function addOwn(btn, draw) {
  const name = h("input", { placeholder: "A short name, e.g. browser", "aria-label": "Name" });
  const where = h("input", { class: "grow", placeholder: "uvx some-mcp-server  or  http://127.0.0.1:8000/mcp", "aria-label": "Program or address" });
  const ok = await dialog({ title: "Add your own tool server", text: "Its program and what goes after it, or the address it answers at. Keys never go here: add them in Settings → Keys.",
    yes: "Add", wide: true, body: h("div", { class: "stack" }, name, where) });
  if (!ok) return;
  const w = where.value.trim();
  const spec = /^https?:\/\//.test(w) ? { url: w } : { command: w.split(/\s+/)[0], args: w.split(/\s+/).slice(1) };
  await act(btn, () => post("/api/tools/servers/add", { name: name.value.trim(), ...spec }), (r) => wt("{added} added", { added: r.added }), () => draw());
}
