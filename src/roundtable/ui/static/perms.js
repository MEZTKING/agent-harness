// What each job may do (GET/POST /api/perms, ui/permsapi.py; the presets are harness/perms.py).
// permsCell(job): one small chooser for a job's row in Who does what (this computer's choice).
// permsDefaultBox(): this computer's default, for Settings. projectPermsBox(path): a project's own choices.
// Free asks "Are you sure?" first; Read only cuts the job's tools to reading.
import { h, get, post, has, toast, dialog, q } from "./core.js";

let shared = null; // one GET per page for every row
function load(path) {
  if (path) return get(`/api/perms?${q({ path })}`);
  if (!shared) shared = get("/api/perms").catch((e) => { shared = null; throw e; });
  return shared;
}

async function choose(body, after) {
  try {
    let out = await post("/api/perms", body);
    if (out && out.needs_sure) {
      const yes = await dialog({ title: "Let it run freely?", text: out.words, yes: "Yes, Free", danger: true });
      if (!yes) return null;
      out = await post("/api/perms", { ...body, sure: true });
    }
    if (!body.path) shared = Promise.resolve(out);
    toast("Saved");
    if (after) after(out);
    return out;
  } catch (e) { toast(String(e.message || e), true); return null; }
}

function picker(st, value, label, inherit, onpick) {
  const sel = h("select", { "aria-label": label, title: label, class: "perms-pick" },
    h("option", { value: "" }, inherit),
    st.presets.map((p) => h("option", { value: p.id, title: p.words }, p.title)));
  sel.value = value || "";
  const prev = sel.value;
  sel.addEventListener("change", async () => {
    const out = await onpick(sel.value);
    if (out === null) sel.value = prev; // not saved (Free not confirmed, or an error): show what's really there
  });
  return sel;
}

export async function permsCell(job) {
  if (!(await has("/api/perms"))) return null;
  let st;
  try { st = await load(); } catch { return null; }
  const row = (st.jobs || []).find((j) => j.job === job);
  if (!row) return null;
  const words = h("span", { class: "muted small perms-now", title: `Comes from ${row.source}` }, row.title);
  const sel = picker(st, row.computer, `What the ${job} job may do on this computer`, "As this computer's default",
    (v) => choose({ job, preset: v }, (out) => {
      const r = (out.jobs || []).find((j) => j.job === job);
      if (r) { words.textContent = r.title; words.title = `Comes from ${r.source}`; }
    }));
  permsStyles();
  return h("span", { class: "perms-cell", title: "What this job may do: Ask every time, Careful, Free or Read only" }, sel, words);
}

export async function permsDefaultBox() {
  if (!(await has("/api/perms"))) return null;
  let st;
  try { st = await load(); } catch { return null; }
  const now = (st.presets.find((p) => p.id === (st.default || "careful")) || {}).words || "";
  const words = h("p", { class: "muted small" }, now);
  const sel = picker(st, st.default, "What jobs may do on this computer", "Careful (the default)",
    (v) => choose({ preset: v }, (out) => {
      words.textContent = (out.presets.find((p) => p.id === (out.default || "careful")) || {}).words || "";
    }));
  permsStyles();
  return h("div", { class: "perms-box" },
    h("h3", {}, "What jobs may do"),
    h("p", { class: "small" }, "Before a job runs a command or changes a file, does it wait for your tap?"),
    h("label", { class: "small row" }, "Every job: ", sel),
    words,
    h("details", {}, h("summary", { title: "Each preset, and the box for commands" }, "More"),
      h("ul", { class: "small" }, st.presets.map((p) => h("li", {}, h("b", {}, p.title), ": ", p.words))),
      h("p", { class: "muted small" }, st.box.words),
      h("p", { class: "muted small" }, "A job's own choice is on Models → Who does what; a project's on its Settings. Learning never loosens one.")));
}

export async function projectPermsBox(path) {
  if (!path || !(await has("/api/perms"))) return null;
  let st;
  try { st = await load(path); } catch { return null; }
  const box = h("div", { class: "perms-box" });
  const draw = (s) => {
    const rows = (s.jobs || []).map((j) => h("div", { class: "row perms-row" },
      h("span", { class: "perms-job" }, j.job),
      picker(s, j.project, `What the ${j.job} job may do on this project`, "As this computer says",
        (v) => choose({ job: j.job, preset: v, path }, draw)),
      h("span", { class: "muted small", title: `Comes from ${j.source}` }, j.title)));
    const kept = s.allowed || {};
    const always = [["hosts", "Websites"], ["mcp", "Tools"], ["paths", "Files"], ["tools", "Deleting with"]]
      .flatMap(([k, label]) => (kept[k] || []).map((v) => h("li", {}, `${label}: ${v} `,
        h("button", { class: "btn small", type: "button", title: "Ask again next time",
          onclick: async () => { try { draw(await post("/api/perms/forget", { path, kind: k, value: v })); } catch (e) { toast(String(e.message || e), true); } } }, "Ask again"))));
    box.replaceChildren(
      h("h3", {}, "What each job may do here"),
      h("p", { class: "small" }, "This project's own choice wins over this computer's."),
      ...rows,
      always.length ? h("details", {}, h("summary", { title: "What you said to always allow in this project" }, "More"),
        h("ul", { class: "small" }, always)) : null);
  };
  permsStyles();
  draw(st);
  return box;
}

function permsStyles() {
  if (typeof document === "undefined" || document.getElementById("perms-style")) return;
  document.head.append(h("style", { id: "perms-style" }, `
.perms-cell { display: inline-flex; gap: 6px; align-items: center; }
.perms-pick { font: inherit; color: var(--color-text); background: var(--color-surface); border: 1px solid var(--color-line-strong); border-radius: var(--radius-small); padding: 2px 6px; }
.perms-box .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
.perms-box .perms-job { min-width: 8em; font-family: var(--font-mono); }
.perms-box details { margin-top: 8px; } .perms-box li { margin: 3px 0; overflow-wrap: anywhere; }
`));
}
