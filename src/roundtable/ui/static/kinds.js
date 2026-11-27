// Kinds (ui/kindsapi.py): the first card on a plan ("This looks like a website… Right?") and the Gallery's
// "What Roundtable can make" tab. Short first; the recipe's details fold behind "More".
import { h, fill, get, post, act, card, empty, dialog, toast } from "./core.js";

const STATUS_TIP = {
  proven: "Something built with this passed every check that counts.",
  trial: "It can be used, but nothing built with it has passed its checks yet.",
  not_yet: "Not ready: Roundtable can't build or check this sort of thing so far.",
};

export function statusPill(status, words) {
  return h("span", { class: "pill kd-st kd-" + status, title: STATUS_TIP[status] || "" }, words);
}

// The plan's first card. `kind` is the plan document's `kind`; `path` the project's folder.
export function kindCard(kind, path, after) {
  if (!kind) return null;
  kindStyles();
  const box = h("article", { class: "ask kd-plan" });
  const choose = (btn, id) => act(btn, () => post("/api/kinds/set", { path, id }), (r) => r.reply, (r) => after && after(r));
  const extras = (kind.extras || []).map((e) => e.name).join(", ");
  fill(box,
    h("div", { class: "ask-head" }, h("span", { class: "chip", title: "What sort of thing this project makes. It shapes the plan, the builders' advice and the checks." }, "Kind"),
      statusPill(kind.status, kind.status_words)),
    h("h3", { class: "ask-q" }, kind.question),
    extras && !kind.confirmed ? h("p", { class: "ask-detail" }, `Also packed as: ${extras}.`) : null,
    kind.fixed ? h("p", { class: "small muted", title: "Fixed once the plan was approved, so the work doesn't change under the builders" },
      "Fixed for this plan. To make it as something else, use Try another way or start a new goal.")
      : h("div", { class: "ask-opts" },
        (kind.choices || []).map((c) => h("button", { type: "button", class: "ask-opt" + (c.recommended ? " rec" : ""),
          title: c.recommended ? (kind.confirmed ? "Keep it" : "Yes, that's right") : kind.change_words,
          onclick: (ev) => choose(ev.currentTarget, c.id) }, c.recommended && !kind.confirmed ? `Yes, a ${c.name.toLowerCase()}` : c.name))),
    !kind.fixed && kind.change_words ? h("p", { class: "small muted" }, kind.change_words) : null,
    kind.fixed && kind.frozen ? h("details", { class: "fold" }, h("summary", {}, "More"),
      h("p", { class: "small" }, "This project keeps the recipe it was approved with, even if the kind changes later."),
      h("button", { type: "button", class: "small", title: "Use the kind as it is now, from the next task on",
        onclick: (ev) => act(ev.currentTarget, () => post("/api/kinds/newest", { path }), (r) => r.reply, after) }, "Use the newest recipe")) : null);
  return box;
}

// One kind's card in the gallery's "What Roundtable can make".
export function kindTile(k, onStart) {
  const needs = k.missing.length ? h("p", { class: "small kd-miss", title: "Roundtable can install these for you on the Tools page" },
    `Needs ${k.missing.join(" and ")} on this computer. `, h("a", { href: "#/tools" }, "Install")) : null;
  return h("article", { class: "kd-tile" + (k.usable ? "" : " kd-off") },
    h("div", { class: "kd-head" }, h("b", {}, k.name), statusPill(k.status, k.status_words)),
    h("p", { class: "small" }, k.blurb),
    k.typical ? h("p", { class: "small muted", title: k.typical_tip }, `Usually ${k.typical}`) : null,
    needs,
    k.usable && k.examples.length ? h("div", { class: "kd-ideas" }, k.examples.map((ex) =>
      h("button", { type: "button", class: "chip-link quiet small", title: "Start a new project with this idea", onclick: () => onStart(k, ex) }, ex))) : null,
    h("div", { class: "row" },
      k.usable ? h("button", { type: "button", class: "primary small", onclick: () => onStart(k, "") }, "Start one") : null,
      h("button", { type: "button", class: "small", title: "Save this kind as a file to give to someone or keep", onclick: (ev) => share(ev.currentTarget, k) }, "Share")),
    h("details", { class: "fold" }, h("summary", {}, "More"),
      h("ul", { class: "small plain" },
        k.proof.length ? h("li", {}, "Checked by: ", k.proof.map((p) => p.words + (p.not_yet ? " (not checked yet)" : p.optional ? " (when there are tests)" : "")).join(" · ")) : null,
        k.more.spec_sections.length ? h("li", {}, "The plan covers: ", k.more.spec_sections.join(", ")) : null,
        k.more.roles_added.length ? h("li", {}, "Adds: ", k.more.roles_added.join(", ")) : null,
        k.extras_allowed.length ? h("li", {}, "Can also be packed as: ", k.extras_allowed.join(", ")) : null,
        k.source !== "builtin" ? h("li", {}, "One of your own kinds") : null),
      k.more.card ? h("p", { class: "small muted" }, k.more.card) : null));
}

async function share(btn, k) {
  await act(btn, () => get(`/api/kinds/export?id=${encodeURIComponent(k.id)}`), null, (r) => {
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const a = h("a", { href: URL.createObjectURL(new Blob([bytes], { type: "application/zip" })), download: r.name });
    document.body.append(a); a.click(); a.remove();
    toast(`Saved ${r.name}`);
  });
}

// "Make another like this" and "Start one": the wizard, filled in (projects.js reads rt-wizard-prefill)
export function startWizard(prefill) {
  try { sessionStorage.setItem("rt-wizard-prefill", JSON.stringify(prefill)); } catch (e) { /* private window: the wizard starts empty */ }
  location.hash = "#/new";
}

export async function kindsTab() {
  kindStyles();
  const box = h("div", { class: "kd-make" });
  const draw = async () => {
    let d;
    try { d = await get("/api/kinds"); } catch (e) { fill(box, empty(`Couldn't read the kinds: ${e.message}`)); return; }
    const start = (k, idea) => startWizard({ kind: { chosen: [k.id] }, ...(idea ? { idea: { other: idea } } : {}) });
    fill(box,
      h("p", { class: "muted" }, d.words),
      d.groups.map((g) => h("section", { class: "kd-group" }, h("h2", {}, g.group), h("div", { class: "kd-grid" }, g.kinds.map((k) => kindTile(k, start))))),
      d.problems.length ? h("details", { class: "fold" }, h("summary", { title: "Kinds whose file has a mistake: they aren't offered until it's fixed" },
        `${d.problems.length} kind${d.problems.length > 1 ? "s" : ""} couldn't be read`),
        h("ul", { class: "small" }, d.problems.map((p) => h("li", {}, `${p.where}: ${p.problems.join("; ")}`)))) : null,
      card("Add a kind from a file", h("p", { class: "small" }, "A .rtkind file someone shared, or one you saved. You see what it would switch on before anything changes."),
        h("input", { type: "file", accept: ".rtkind", "aria-label": "Choose a kind file", onchange: (ev) => importFile(ev.target, draw) })));
  };
  await draw();
  return box;
}

async function importFile(input, after) {
  const f = input.files && input.files[0];
  if (!f) return;
  const bytes = new Uint8Array(await f.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  const data = btoa(bin);
  input.value = "";
  let r;
  try { r = await post("/api/kinds/import", { data }); } catch (e) { toast(e.message, true); return; }
  if (!r.ok) { await dialog({ title: "That kind can't be added", body: h("ul", {}, r.problems.map((p) => h("li", {}, p))), yes: "OK", no: null }); return; }
  const w = r.would;
  const body = h("div", {}, h("p", {}, `${w.name}${w.is_extra ? " (an extra)" : ""} would add:`),
    h("ul", { class: "small" },
      w.needs.length ? h("li", {}, "Tools it needs: ", w.needs.join(", ")) : null,
      w.plugins.length ? h("li", {}, "Plug-ins: ", w.plugins.join(", ")) : null,
      w.roles_added.length ? h("li", {}, "New helpers: ", w.roles_added.join(", ")) : null,
      w.prompts_for.length ? h("li", {}, "Advice for: ", w.prompts_for.join(", ")) : null,
      w.commands.length ? h("li", {}, "Commands its checks run: ", w.commands.join(" · ")) : null,
      h("li", {}, "It starts On trial.")),
    w.replaces ? h("p", { class: "small kd-miss" }, `It replaces ${w.replaces}.`) : null);
  if (!(await dialog({ title: "Add this kind?", body, yes: "Add it" }))) return;
  try { toast((await post("/api/kinds/import", { data, confirm: true })).reply); after(); } catch (e) { toast(e.message, true); }
}

export function kindStyles() {
  if (typeof document === "undefined" || document.getElementById("kd-style")) return;
  document.head.append(h("style", { id: "kd-style" }, `
.kd-st.kd-proven { background: var(--color-ok-soft, #e3efd9); color: var(--color-ok, #3f6b2a); }
.kd-st.kd-trial { background: var(--color-accent-soft); color: var(--color-accent); }
.kd-st.kd-not_yet { background: var(--color-sunken); color: var(--color-muted); }
.kd-group h2 { margin: 18px 0 8px; font-size: 16px; }
.kd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.kd-tile { border: 1px solid var(--color-oak-line); border-radius: var(--radius-small); padding: 12px 14px; background: var(--color-surface); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.kd-tile p { margin: 0; } .kd-off { opacity: .6; }
.kd-head { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.kd-ideas { display: flex; flex-wrap: wrap; gap: 6px; } .kd-ideas .chip-link { padding: 3px 10px; font-size: 12.5px; }
.kd-miss { color: var(--color-warn); }
.kd-plan .ask-head { display: flex; gap: 8px; align-items: center; }
`));
}
