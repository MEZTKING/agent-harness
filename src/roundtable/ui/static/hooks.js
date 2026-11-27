// Work from outside, with no open door (wave 8, p1-reach): the add parts for the three new automation kinds –
// events on GitHub, a change at an address you name, and a program on this computer (a local hook). The local
// hook's secret is made by the app and shown here once; the automation list keeps only its hash.
// The API: ui/reachapi.py (/api/hooks/new, /api/hooks/secret) and ui/automationapi.py.
import { h, post, act, seg, card, dialog, toast } from "./core.js";

const STYLE = `
.hook-secret { font-family: var(--font-mono); background: var(--color-sunken); border: 1px solid var(--color-line);
  border-radius: var(--radius-small); padding: 6px 8px; word-break: break-all; color: var(--color-text); }
.hook-note { color: var(--color-muted); }
`;
let styled = false;
const style = () => { if (!styled) { document.head.append(h("style", {}, STYLE)); styled = true; } };

export const HOOK_KINDS = [["events", "Events on GitHub", "A push, a pull request, a comment or a release starts work"],
  ["poll", "A change at an address", "The harness looks at an address you name; a change starts work"],
  ["local", "A program on this PC", "A program on this computer sends something; only this computer can"]];
const EVENTS = [["push", "A push"], ["pull_request", "A pull request opened"], ["comment", "A comment starting with a word"], ["release", "A release"]];

const input = (val, ph, label, extra = {}) => { const el = h("input", { class: "grow", placeholder: ph, "aria-label": label, ...extra }); el.value = val || ""; return el; };
const labelled = (text, el, tip) => h("label", { class: "stack" }, h("span", { class: "label", title: tip || null }, text), el);

// The parts of the add (or edit) form for one of the three kinds. Returns {nodes, collect()}.
export function hookParts(kind, v, projects) {
  style();
  const hk = v.hook || {};
  let make = v.make || "idea";
  const proj = projects(v.project);
  const makeSeg = h("div", { class: "stack" }, h("span", { class: "label" }, "It becomes"),
    seg([["idea", "A new idea"], ["task", "A task on a project"]], make, (x) => { make = x; proj.hidden = x !== "task"; }, "It becomes"), proj);
  proj.hidden = make !== "task";
  const note = h("p", { class: "small hook-note" }, "What arrives is quoted inside the plan as information, never followed as an instruction. The plan still waits for your OK.");
  if (kind === "events") {
    const repo = input(hk.repo, "owner/name, for example acme/shop", "GitHub repository");
    const branch = input(hk.branch, "any branch", "Branch", { title: "Only events on this branch (leave empty for any)" });
    const word = input(hk.word || "/build", "/build", "Comment word", { title: "A comment counts only when it starts with this word" });
    const picked = new Set(hk.events || ["push"]);
    const boxes = EVENTS.map(([k, l]) => h("label", { class: "row" }, h("input", { type: "checkbox", checked: picked.has(k),
      onchange: (ev) => { if (ev.target.checked) picked.add(k); else picked.delete(k); wordRow.hidden = !picked.has("comment"); } }), l));
    const wordRow = labelled("The word a comment starts with", word);
    wordRow.hidden = !picked.has("comment");
    return { nodes: [labelled("Repository", repo), h("div", { class: "stack" }, h("span", { class: "label" }, "Which events"), boxes), wordRow,
      labelled("Branch (optional)", branch), makeSeg, note,
      h("p", { class: "small hook-note" }, "The harness asks GitHub every few minutes with your GitHub key; nothing on the internet can call in.")],
    collect: () => ({ make, project: proj.value, hook: { repo: repo.value, events: [...picked], branch: branch.value, word: word.value } }) };
  }
  if (kind === "poll") {
    const url = input(hk.url, "https://example.com/status.json", "Address");
    const field = input(hk.field, "status.state (optional)", "JSON field", { title: "Only a change in this field of a JSON answer counts" });
    const every = input(hk.every_minutes || 15, "15", "Minutes", { type: "number", min: "5", step: "5", class: "ap-cap" });
    return { nodes: [labelled("The address to look at", url, "Only public addresses are read: never one on your own network"),
      h("details", { class: "fold" }, h("summary", {}, "More"), labelled("One field of a JSON answer", field), h("span", { class: "row" }, "Look every", every, "minutes")),
      makeSeg, note],
    collect: () => ({ make, project: proj.value, hook: { url: url.value, field: field.value, every_minutes: Number(every.value) || 15 } }) };
  }
  return { nodes: [makeSeg, note, h("p", { class: "small hook-note" }, "Adding it makes a secret, shown once. Only programs on this computer can send to it (127.0.0.1); the internet can't.")],
    collect: () => ({ make, project: proj.value, local: true }) };
}

// After the owner presses Add on a local hook: make it through /api/hooks/new and show the secret once.
export async function addLocalHook(btn, fields, after) {
  return act(btn, () => post("/api/hooks/new", fields), (r) => r.words, (r) => { showSecret(r); if (after) after(); });
}

export function showSecret(r) {
  style();
  const address = `${location.origin}${r.path}`;
  const example = `curl -X POST ${address} -H "Content-Type: application/json" -H "${r.header}: <the secret>" -d "{\\"title\\": \\"Fix the login\\", \\"text\\": \\"...\\"}"`;
  const copy = (text, what) => h("button", { type: "button", class: "small", onclick: async () => {
    try { await navigator.clipboard.writeText(text); toast(`${what} copied.`); } catch { toast("Couldn't copy: select it and copy it by hand.", true); } } }, `Copy ${what.toLowerCase()}`);
  return dialog({ title: "Your hook's secret", wide: true, yes: "I've copied it", no: null, body: h("div", { class: "stack" },
    h("p", {}, r.note),
    h("span", { class: "label" }, "Address"), h("div", { class: "hook-secret" }, address), copy(address, "Address"),
    h("span", { class: "label" }, "Secret"), h("div", { class: "hook-secret" }, r.secret), copy(r.secret, "Secret"),
    h("details", { class: "fold" }, h("summary", {}, "More"),
      h("p", { class: "small" }, `Send at most ${r.max_kb} KB. A JSON body may carry a "title".`),
      h("div", { class: "hook-secret small" }, example))) });
}

// On a local hook's row: its address and New secret.
export function hookRowExtras(a, after) {
  if (a.kind !== "local") return null;
  style();
  return h("div", { class: "row small" }, h("span", { class: "muted grow", title: "Only programs on this computer can send to it" }, `${location.origin}/hooks/${a.id}`),
    h("button", { type: "button", class: "small", onclick: async (ev) => {
      if (!(await dialog({ title: "Make a new secret?", text: "The old secret stops working at once. Programs that use it need the new one.", yes: "New secret" }))) return;
      act(ev.currentTarget, () => post("/api/hooks/secret", { id: a.id }), (r) => r.words, (r) => { showSecret(r); if (after) after(); });
    } }, "New secret"));
}

export const hooksCard = () => card("Work from outside", h("p", {}, "Three ways for work to start from outside, with nothing on this computer open to the internet: events on GitHub, a change at an address you name, and programs on this PC."));
