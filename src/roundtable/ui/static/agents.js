// Named agents: one per job, each with a name, a face made by an image model, your notes and what it learned.
// agentsTab() is the Agents tab in Models; agentChip(id) is the small face-and-name used in "who did what".
// (agents.py, ui/agentsapi.py). Until a face is made the agent shows its initials in a ring: chrome, not art.
import { h, fill, get, post, act, card, empty, dialog, toast, has, money } from "./core.js";
import { t } from "./words.js";

let cache = null;  // the last /api/agents answer, shared by every chip on the page

async function team(fresh = false) {
  if (!cache || fresh) cache = get("/api/agents").catch((e) => { cache = null; throw e; });
  return cache;
}

function face(a, size = "") {
  return a.face
    ? h("img", { class: "ag-face " + size, src: a.face, alt: "", title: t("{name}, the {v1}", { name: a.name, v1: a.job_name.toLowerCase() }) })
    : h("span", { class: "ag-face ag-ring " + size, title: t("{name} has no face yet", { name: a.name }), "aria-hidden": "true" }, a.initials);
}

// The small chip: face and name. Empty (removed) when there's no such agent or this copy has no agents.
export function agentChip(id) {
  const chip = h("span", { class: "ag-chip" });
  if (!id) return chip;
  (async () => {
    try {
      if (!(await has("/api/agents"))) { chip.remove(); return; }
      const a = ((await team()).agents || []).find((x) => x.id === id);
      if (!a) { chip.remove(); return; }
      fill(chip, face(a, "ag-small"), h("span", {}, a.name));
      chip.title = `${a.name}, the ${a.job_name.toLowerCase()}, did this`;
    } catch (e) { chip.remove(); }
  })();
  return chip;
}

export async function agentsTab() {
  agentStyles();
  const box = h("div", { class: "ag-tab" });
  const draw = async () => {
    let d;
    try { d = await team(true); } catch (e) { fill(box, empty(t("Couldn't read your team: {message}", { message: e.message }))); return; }
    const byJob = new Map(d.jobs.map((j) => [j.job, []]));
    for (const a of d.agents) (byJob.get(a.job) || []).push(a);
    fill(box,
      h("p", { class: "muted" }, d.words),
      h("div", { class: "ag-row" }, d.jobs.map((j) => {
        const hired = byJob.get(j.job).find((a) => a.hired);
        return hired ? tile(hired, draw) : h("div", { class: "ag-tile ag-empty", title: j.words }, h("b", {}, j.name), h("span", { class: "muted small" }, "Nobody hired"));
      })),
      h("details", { class: "fold" }, h("summary", { title: "Everyone on the team who isn't hired right now, and adding a new agent" }, "More"),
        h("div", { class: "ag-row" }, d.agents.filter((a) => !a.hired).map((a) => tile(a, draw))),
        h("div", { class: "row" },
          h("button", { type: "button", onclick: () => edit(null, d.jobs, draw) }, "New agent"),
          h("label", { class: "ag-file", title: "A .rtagent file someone shared, or one you saved. You see everything in it before anyone joins." },
            "Add from a file ", h("input", { type: "file", accept: ".rtagent", "aria-label": "Choose an agent file", onchange: (ev) => importFile(ev.target, draw) })))));
  };
  await draw();
  return box;
}

function tile(a, redraw) {
  return h("button", { type: "button", class: "ag-tile" + (a.hired ? " ag-hired" : ""), onclick: () => open(a.id, redraw),
    title: a.about || t("{name}, the {v1}", { name: a.name, v1: a.job_name.toLowerCase() }) },
    face(a), h("b", {}, a.name), h("span", { class: "muted small" }, a.job_name));
}

async function open(id, redraw) {
  let a;
  try { a = await get("/api/agents/one?id=" + encodeURIComponent(id)); } catch (e) { toast(e.message, true); return; }
  const jobs = (await team()).jobs;
  const body = h("div", { class: "ag-one" },
    h("div", { class: "row" }, face(a, "ag-big"), h("div", {}, h("p", {}, h("b", {}, a.name), ` · ${a.job_name}`), a.about ? h("p", { class: "muted" }, a.about) : null)),
    h("div", { class: "row" },
      a.hired ? null : h("button", { type: "button", class: "primary", title: t("Give {name} the {v1}'s job; whoever had it steps back", { name: a.name, v1: a.job_name.toLowerCase() }), onclick: (ev) => act(ev.target, () => post("/api/agents", { id: a.id, hire: true }), t("{name} is hired", { name: a.name }), () => { close(); redraw(); }) }, "Hire"),
      h("button", { type: "button", onclick: () => { close(); edit(a, jobs, redraw); } }, "Change"),
      h("button", { type: "button", title: "A picture model makes the face. You see the price first", onclick: (ev) => makeFace(ev.target, a, redraw) }, a.face ? "New face" : "Make a face"),
      h("button", { type: "button", title: "Save this agent as a file to bring in on another computer", onclick: () => share(a) }, "Share"),
      h("button", { type: "button", class: "danger", title: "Takes it off the team. Its folder is kept, nothing is deleted", onclick: (ev) => remove(ev.target, a, () => { close(); redraw(); }) }, "Remove")),
    h("details", { class: "fold" }, h("summary", {}, "More"),
      h("p", { class: "small" }, h("b", {}, "Your notes: "), a.notes || "None yet."),
      h("p", { class: "small" }, h("b", {}, "Face words: "), (a.traits || []).join(", ") || "None"),
      h("p", { class: "small" }, h("b", {}, "What it learned: ")), h("pre", { class: "ag-mem small" }, a.learned || "Nothing yet."),
      a.face_info && a.face_info.model ? h("p", { class: "small muted" }, `Face by ${a.face_info.model}` + (a.face_info.cost_usd != null ? ` for ${money(a.face_info.cost_usd)}` : "")) : null));
  // closing goes through the dialog's own Close button, so it tidies up after itself
  const close = () => { const m = body.closest(".modal"); const b = m && m.querySelector(".row.end button"); if (b) b.click(); };
  await dialog({ title: a.name, body, yes: "Close", no: null, wide: true });
}

async function edit(a, jobs, redraw) {
  const name = h("input", { class: "grow", value: a ? a.name : "", "aria-label": "Name", maxlength: 40 });
  const job = h("select", { "aria-label": "Job" }, jobs.map((j) => h("option", { value: j.job, selected: a && a.job === j.job ? "" : null }, j.name)));
  const about = h("input", { class: "grow", value: a ? a.about : "", "aria-label": "One line about it", maxlength: 200 });
  const traits = h("input", { class: "grow", value: a ? (a.traits || []).join(", ") : "", "aria-label": "Up to three words for its face", title: "Up to three words for how its face looks, like calm, bold, cheerful. Only these words and its job reach the picture model" });
  const notes = h("textarea", { rows: 6, "aria-label": "Your notes for it", maxlength: 2000, title: "Your own words for this agent. They go to the model with every task of its job" });
  notes.value = a ? (a.notes || "") : "";
  const body = h("div", { class: "ag-form" },
    h("label", {}, "Name", name), h("label", {}, "Job", job), h("label", {}, "One line about it", about),
    h("label", {}, "Face words", traits), h("label", {}, "Your notes (up to 2,000 characters)", notes));
  if (!(await dialog({ title: a ? t("Change {name}", { name: a.name }) : "New agent", body, yes: "Save", wide: true }))) return;
  await act(null, () => post("/api/agents", { ...(a ? { id: a.id } : {}), name: name.value, job: job.value, about: about.value, traits: traits.value, notes: notes.value }), (r) => r.reply, redraw);
}

async function makeFace(btn, a, redraw) {
  const p = await act(btn, () => post("/api/agents/face", { id: a.id }));
  if (!p) return;
  if (!p.price.ok) { toast(p.reply, true); return; }
  const words = p.price.usd != null ? `${p.reply} Make it?` : `${p.reply} Make it anyway?`;
  if (!(await dialog({ title: t("A face for {name}", { name: a.name }), text: words, yes: "Make it" }))) return;
  await act(btn, () => post("/api/agents/face", { id: a.id, confirm: true }), (r) => r.reply, () => { cache = null; redraw(); });
}

async function share(a) {
  const tick = h("input", { type: "checkbox", "aria-label": "Include what it learned" });
  const body = h("div", {}, h("p", {}, t("A file with {name}'s name, job, notes and face. It never holds model choices.", { name: a.name })),
    h("label", { title: "What it learned may mention your other projects. You see all of it before saving" }, tick, " Include what it learned"));
  if (!(await dialog({ title: t("Share {name}", { name: a.name }), body, yes: "Next" }))) return;
  const memory = tick.checked ? "1" : "";
  if (memory) {
    let look;
    try { look = await get(`/api/agents/export?id=${encodeURIComponent(a.id)}&memory=1&preview=1`); } catch (e) { toast(e.message, true); return; }
    const ok = await dialog({ title: "This goes in the file", body: h("div", {}, h("p", { class: "small" }, "Files: ", look.files.join(", ")), h("pre", { class: "ag-mem small" }, look.memory || "(nothing learned yet)")), yes: "Save the file", wide: true });
    if (!ok) return;
  }
  await act(null, () => get(`/api/agents/export?id=${encodeURIComponent(a.id)}&memory=${memory}`), null, (r) => {
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const link = h("a", { href: URL.createObjectURL(new Blob([bytes], { type: "application/zip" })), download: r.name });
    document.body.append(link); link.click(); link.remove();
    toast(t("Saved {name}", { name: r.name }));
  });
}

async function remove(btn, a, after) {
  if (!(await dialog({ title: t("Remove {name}?", { name: a.name }), text: "It leaves the team. Its folder, notes and memory are kept in agents/.removed, so nothing is lost.", yes: "Remove", danger: true }))) return;
  await act(btn, () => post("/api/agents/remove", { id: a.id }), (r) => r.reply, after);
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
  try { r = await post("/api/agents/import", { data }); } catch (e) { toast(e.message, true); return; }
  if (!r.ok) { await dialog({ title: "That agent can't join", body: h("ul", {}, r.problems.map((p) => h("li", {}, p))), yes: "OK", no: null }); return; }
  const w = r.would;
  const body = h("div", {},
    h("p", {}, h("b", {}, w.name), ` · ${w.job_name}`), w.about ? h("p", { class: "muted" }, w.about) : null,
    h("p", { class: "small" }, h("b", {}, "Its notes: ")), h("pre", { class: "ag-mem small" }, w.notes || "(none)"),
    w.memory ? h("details", { class: "fold" }, h("summary", {}, "What it learned elsewhere"), h("pre", { class: "ag-mem small" }, w.memory)) : null,
    w.dropped.length ? h("p", { class: "small" }, t("Left out: its model choices ({v1}). Your own Models decide.", { v1: w.dropped.join(", ") })) : null,
    h("p", { class: "small muted" }, "It joins the team but isn't hired until you say so."));
  if (!(await dialog({ title: "Add this agent?", body, yes: "Add it", wide: true }))) return;
  await act(null, () => post("/api/agents/import", { data, confirm: true }), (x) => x.reply, after);
}

export function agentStyles() {
  if (typeof document === "undefined" || document.getElementById("ag-style")) return;
  document.head.append(h("style", { id: "ag-style" }, `
.ag-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 10px 0; }
.ag-tile { display: flex; flex-direction: column; align-items: center; gap: 4px; width: 112px; padding: 10px 6px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-surface); color: var(--color-text); font: inherit; cursor: pointer; text-align: center; }
.ag-tile.ag-hired { border-color: var(--color-accent); }
.ag-tile.ag-empty { cursor: default; opacity: .7; justify-content: center; min-height: 112px; }
.ag-face { width: 64px; height: 64px; border-radius: 50%; object-fit: cover; flex: none; }
.ag-face.ag-small { width: 20px; height: 20px; font-size: 9px; }
.ag-face.ag-big { width: 96px; height: 96px; font-size: 28px; }
.ag-ring { display: inline-grid; place-items: center; border: 2px solid var(--color-accent); background: var(--color-sunken); color: var(--color-accent); font-family: var(--font-display); font-weight: 700; font-size: 20px; }
.ag-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; }
.ag-one .row { gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.ag-form { display: grid; gap: 8px; } .ag-form label { display: grid; gap: 3px; }
.ag-mem { white-space: pre-wrap; max-height: 240px; overflow: auto; background: var(--color-sunken); border-radius: var(--radius-small); padding: 6px 8px; margin: 4px 0; }
.ag-file input { margin-inline-start: 6px; }
`));
}
