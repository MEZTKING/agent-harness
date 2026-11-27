// Plug-ins and skills: the list to add from, the owner's skills, and "Make one" from a sentence.
// The API is ui/marketapi.py (GET /api/market, POST /api/market {action}); read loosely so a missing field never breaks it.
// Every install shows what it asks for, in plain words, before anything changes; nothing here deletes.
import { h, fill, get, post, act, toast, dialog, card, empty, money, seg } from "./core.js";

const TABS = [["plugins", "Plug-ins", "Extra tools for the builders"], ["skills", "Skills", "Short know-how a builder reads when its task needs it"],
  ["make", "Make one", "Say what a tool should do; a builder writes it and its tests"]];

export async function marketPage() {
  marketStyles();
  const box = h("div", { class: "mk" });
  const body = h("div", { class: "mk-body" });
  let tab = "plugins";
  let data = null;
  const draw = async (fresh = true) => {
    if (fresh || !data) {
      try { data = await get("/api/market"); } catch (e) { fill(body, empty(`Couldn't read the list: ${e.message}`)); return; }
    }
    fill(body, tab === "plugins" ? pluginsTab(data, draw) : tab === "skills" ? skillsTab(data, draw) : makeTab(draw));
  };
  fill(box, seg(TABS, tab, (v) => { tab = v; draw(false); }, "Plug-ins, skills or make one"), body);
  await draw();
  return box;
}

const perms = (x) => h("p", { class: "small mk-perm", title: "What it may do on this computer" }, "May: ", (x.permission_words || ["Nothing special"]).join(" · "));

function row(x, actions, more) {
  return h("div", { class: "mk-row" },
    h("div", { class: "mk-line" }, h("b", {}, x.name), x.installed ? h("span", { class: "pill " + (x.enabled ? "good" : "") }, x.enabled ? "On" : "Off") : null,
      h("span", { class: "grow" }), ...actions),
    h("p", { class: "muted small" }, x.blurb || x.when || ""),
    more ? h("details", {}, h("summary", { class: "small muted" }, "More"), more) : null);
}

// ---------- plug-ins ----------
function pluginsTab(d, draw) {
  const list = d.plugins || [];
  return [
    h("div", { class: "mk-line" }, h("p", { class: "grow" }, d.words || ""),
      h("button", { class: "small", title: "Reads a newer list from the harness's own repository. Nothing is added or updated by it.",
        onclick: (ev) => act(ev.currentTarget, () => post("/api/market", { action: "refresh" }), (r) => r.words, () => draw()) }, "Look for a newer list")),
    (d.updates || []).length ? card("Newer versions", (d.updates || []).map((u) => h("p", { class: "small" }, `${u.name}: you have ${u.have}, the list has ${u.newer}.`))) : null,
    list.length ? card("Plug-ins to add", list.map((x) => row(x, [
      x.installed ? h("button", { class: "small", title: "Takes it away. Its files are kept aside, not deleted.", onclick: (ev) => remove(ev.currentTarget, x, draw) }, "Take away")
        : h("button", { class: "small primary", title: "Shows what it may do, then adds it once you say yes", onclick: (ev) => install(ev.currentTarget, x, draw) }, "Add"),
    ], h("div", {}, perms(x), h("dl", { class: "small" },
      h("dt", {}, "Version"), h("dd", {}, x.version || "?"), x.checked ? [h("dt", {}, "Checked"), h("dd", {}, x.checked)] : null,
      x.licence ? [h("dt", {}, "Licence"), h("dd", {}, x.licence)] : null, h("dt", {}, "From"), h("dd", {}, h("code", {}, `${x.source}${x.commit ? " @ " + x.commit.slice(0, 10) : ""}`)))))))
      : empty("No outside plug-ins are on the list yet. Make your own under Make one."),
  ];
}

async function install(btn, x, draw) {
  let r = await act(btn, () => post("/api/market", { action: "install", id: x.id }));
  if (!r) return;
  if (r.ok === false && r.needs_ok) {
    const m = r.needs_ok;
    const said = (m.permissions || []).map((p) => p.words);
    if (!(await dialog({ title: `Add ${m.name || x.name}?`, text: `It may: ${said.join(", ") || "nothing special"}.\n\nIt runs in its own box unless you mark it Trusted.`, yes: "Add it" }))) return;
    r = await act(btn, () => post("/api/market", { action: "install", id: x.id, confirmed: (m.permissions || []).map((p) => p.id) }));
    if (!r) return;
  }
  if (r.ok) { toast(`${x.name} added`); draw(); }
}

async function remove(btn, x, draw) {
  if (!(await dialog({ title: `Take ${x.name} away?`, text: "Its files are kept aside, not deleted.", yes: "Take it away" }))) return;
  act(btn, () => post("/api/market", { action: x.kind === "skill" ? "skill_remove" : "remove", id: x.id }), `${x.name} taken away`, () => draw());
}

// ---------- skills ----------
function skillsTab(d, draw) {
  const list = d.skills || [];
  const file = h("input", { type: "file", accept: ".md,text/markdown,text/plain", "aria-label": "Choose a skill file (SKILL.md)",
    onchange: (ev) => addSkill(ev.target, draw) });
  return [
    h("p", { class: "muted" }, "A builder reads up to two skills that fit its task. A skill is only words: it can't run anything."),
    list.length ? card("Skills", list.map((x) => row(x, [
      h("button", { class: "small", title: x.enabled ? "Builders stop getting it" : "Builders get it again when it fits their task",
        onclick: (ev) => act(ev.currentTarget, () => post("/api/market", { action: "skill_switch", id: x.id, on: !x.enabled }), `${x.name} ${x.enabled ? "off" : "on"}`, () => draw()) },
        x.enabled ? "Switch off" : "Switch on"),
      x.own ? h("button", { class: "small", title: "Moves it aside; nothing is deleted", onclick: (ev) => remove(ev.currentTarget, x, draw) }, "Take away") : null,
    ], h("p", { class: "small muted" }, "For tasks about: ", (x.tags || []).join(", ") || "anything")))) : empty("No skills yet."),
    card("Add a skill from a file", h("p", { class: "small" }, "A SKILL.md file on this computer. You read all of it before it is added."), file),
  ];
}

async function addSkill(input, draw) {
  const f = input.files && input.files[0];
  input.value = "";
  if (!f) return;
  const text = await f.text();
  let r;
  try { r = await post("/api/market", { action: "skill_add", text, name: f.name }); } catch (e) { toast(e.message, true); return; }
  if (r.ok === false && r.needs_ok && r.needs_ok.skill) {
    const s = r.needs_ok.skill;
    const body = h("div", {}, h("p", { class: "small" }, `For tasks about: ${(s.tags || []).join(", ")}`), h("pre", { class: "mk-text" }, s.text));
    if (!(await dialog({ title: `Add ${s.name}?`, text: "This is everything it adds. Builders read it when their task fits.", body, yes: "Add it", wide: true }))) return;
    try { r = await post("/api/market", { action: "skill_add", text, name: f.name, digest: r.needs_ok.digest }); } catch (e) { toast(e.message, true); return; }
  }
  if (r.ok) { toast(`${r.added.name} added`); draw(); }
}

// ---------- make one ----------
function makeTab(draw) {
  const idea = h("textarea", { rows: 3, class: "grow", placeholder: "For example: a tool that turns a list of prices into a total with VAT", "aria-label": "What the tool should do" });
  const out = h("div", { class: "mk-out", "aria-live": "polite" });
  const go = h("button", { class: "primary", title: "Shows the price first; nothing is paid until you say yes", onclick: (ev) => make(ev.currentTarget, idea.value, out, draw) }, "Make it");
  return card("Make a plug-in", h("p", { class: "small" }, "Say in a sentence what the tool should do. A builder writes it with tests, the tests run in a box with no internet, and you read it before adding it."),
    h("div", { class: "mk-line" }, idea), h("div", { class: "mk-line" }, h("span", { class: "grow" }), go), out);
}

async function make(btn, idea, out, draw) {
  const p = await act(btn, () => post("/api/market", { action: "make", idea }));
  if (!p || !p.price) return;
  if (!(await dialog({ title: "Make this plug-in?", text: p.price.words, yes: p.price.usd ? `Make it (${money(p.price.usd)})` : "Make it" }))) return;
  const r = await act(btn, () => post("/api/market", { action: "make", idea, go: true }));
  if (!r || !r.job) return;
  btn.disabled = true;
  fill(out, h("p", { class: "muted small" }, "Writing it… this takes a minute or two."));
  let j;
  for (;;) {
    try { j = await get(`/api/jobs/${encodeURIComponent(r.job.id)}`); } catch (e) { toast(e.message, true); break; }
    if (j.status !== "running" || !out.isConnected) break;
    await new Promise((res) => setTimeout(res, 2000));
  }
  if (btn.isConnected) btn.disabled = false;
  if (!j || !out.isConnected) return;
  if (j.status !== "done") { fill(out, h("p", { class: "mk-bad" }, j.error || "It stopped.")); return; }
  fill(out, made(j.result || {}, draw));
}

function made(d, draw) {
  const files = (d.files || []).map((f) => h("details", {}, h("summary", { class: "small" }, f.path), h("pre", { class: "mk-text" }, f.text)));
  const add = d.offered ? h("button", { class: "primary", title: "Adds it, in its own box, asking for nothing", onclick: async (ev) => {
    const b = ev.currentTarget;
    let r = await act(b, () => post("/api/market", { action: "add_made", folder: d.folder }));
    if (r && r.ok === false && r.needs_ok) {
      if (!(await dialog({ title: `Add ${d.name}?`, text: "It may do nothing special: no internet, no programs, no files outside its folder.", yes: "Add it" }))) return;
      r = await act(b, () => post("/api/market", { action: "add_made", folder: d.folder, confirmed: [] }));
    }
    if (r && r.ok) { toast(`${d.name} added`); draw(); }
  } }, "Add it") : null;
  return h("div", { class: "mk-made" },
    h("p", { class: d.offered ? "" : "mk-bad" }, d.words || ""),
    h("p", { class: "small muted" }, `Cost ${money(d.cost_usd)}`),
    add,
    h("details", {}, h("summary", { class: "small muted" }, "More"),
      (d.tools || []).length ? h("p", { class: "small" }, "Tools: ", d.tools.join(", ")) : null,
      (d.problems || []).length ? h("ul", { class: "small" }, d.problems.map((x) => h("li", {}, x))) : null,
      h("p", { class: "small muted" }, d.model ? `Written by ${d.model}` : ""),
      files, d.test_output ? h("details", {}, h("summary", { class: "small" }, "Test output"), h("pre", { class: "mk-text" }, d.test_output)) : null));
}

export function marketStyles() {
  if (typeof document === "undefined" || document.getElementById("mk-style")) return;
  document.head.append(h("style", { id: "mk-style" }, `
.mk { display: flex; flex-direction: column; gap: 12px; }
.mk-body { display: flex; flex-direction: column; gap: 12px; }
.mk-row { padding: 10px 0; border-top: 1px solid var(--color-line); }
.mk-row p { margin: 4px 0 0; }
.mk-line { display: flex; align-items: center; gap: 8px; }
.mk-line .grow, .mk-line textarea { flex: 1; min-width: 0; }
.mk-perm { color: var(--color-muted); }
.mk-text { max-height: 320px; overflow: auto; white-space: pre-wrap; background: var(--color-sunken); border-radius: var(--radius-small); padding: 8px; font-family: var(--font-mono); font-size: 12px; }
.mk-bad { color: var(--color-warn); }
.mk-made { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
`));
}
