// Projects: every project in one list (on this computer and elsewhere), and a new project from an idea.
import { h, fill, get, post, S, onHall, patch, refreshHall, projectHref, money, ago, plural, page, empty, dot, toast, seg, card, has } from "./core.js";
import { composer } from "./compose.js";
import { askCard } from "./asks.js";
import { whereWords, loadMachines } from "./machines.js";

const FILTERS = [["all", "All", "Every project"], ["needs", "Needs you", "Projects with something waiting for you"],
  ["building", "Building", "Projects being built now"], ["done", "Finished", "Projects that are finished"],
  ["elsewhere", "Elsewhere", "Projects another computer or session works on"]];
let filter = "all";
try { filter = sessionStorage.getItem("rt-projects") || "all"; } catch { /* storage unavailable */ }

export async function viewProjects() {
  const list = h("div", { class: "project-list" });
  const count = h("span", { class: "muted" });
  let extra = {};
  if (S.ov && S.ov.harness) {
    try { for (const p of await get("/api/projects")) extra[p.name] = p; } catch { extra = {}; }
  }
  const draw = async (rt) => {
    await loadMachines();
    const seats = rt.seats.filter((s) => filter === "all" || (filter === "needs" && (s.status === "waiting" || s.waiting_for_you))
      || (filter === "building" && s.status === "running") || (filter === "done" && s.status === "done") || (filter === "elsewhere" && s.where !== "here"));
    count.textContent = plural(rt.seats.length, "project");
    patch(list, JSON.stringify([filter, seats.map((s) => [s.id, s.state, s.status, s.progress, s.spent_usd, s.waiting_for_you, s.last_activity && ago(s.last_activity)])]), () =>
      seats.length ? seats.map((s) => row(s, extra[s.id])) : empty(filter === "all" ? "No projects yet. Write your first idea: the planner makes a plan for you to check before anything is built."
        : "No projects like that right now.", filter === "all" ? h("a", { class: "btn primary", href: "#/new" }, "+ New project") : h("button", { onclick: () => pick("all") }, "Show every project")));
  };
  const pick = (v) => { filter = v; try { sessionStorage.setItem("rt-projects", v); } catch { /* storage unavailable */ } list._sig = undefined; draw(S.rt); };
  const root = page("Projects", null,
    h("div", { class: "toolbar" }, seg(FILTERS, filter, pick, "Show"), count, h("span", { class: "spacer" }),
      h("a", { class: "btn primary", href: "#/new", title: "A few taps, then the planner makes a plan for you to check" }, "+ New project")),
    list);
  onHall(root, draw);
  return root;
}

function row(s, x) {
  const p = s.progress || { done: 0, total: 0 };
  const unpriced = x && x.unpriced_calls;
  return h("a", { class: "project-row " + s.status + (s.waiting_for_you ? " lit" : ""), href: projectHref(s.id) },
    s.shot ? h("img", { class: "thumb", src: s.shot.url, alt: "", loading: "lazy" }) : h("span", { class: "thumb blank " + "tg-bg", "aria-hidden": "true" }, dot(s.id), s.name.slice(0, 1)),
    h("span", { class: "pr-main" },
      h("b", { class: "pr-name" }, s.name),
      h("span", { class: "pr-state" }, h("i", { class: "sdot" }), s.state || "No news yet"),
      s.goal || s.description ? h("span", { class: "pr-goal" }, s.goal || s.description) : null),
    h("span", { class: "pr-meta" },
      p.total ? h("span", { title: `${p.done} of ${p.total} tasks done` }, `${p.done} of ${p.total} tasks`) : null,
      s.waiting_for_you ? h("span", { class: "waits" }, `${s.waiting_for_you} for you`) : null,
      s.spent_usd ? h("span", { title: unpriced ? `Spent so far. ${plural(unpriced, "call")} to models with no price yet aren't counted: add their price in Settings.` : "Spent so far" },
        money(s.spent_usd), unpriced ? h("small", {}, " + some not priced") : null) : null,
      h("span", { class: "muted" }, whereWords(s)),
      s.last_activity ? h("span", { class: "muted" }, ago(s.last_activity)) : null));
}

// ---------- a new project: a few cards to tap ----------
export async function viewNew() {
  if (!S.ov.harness) return page("New project", null, card("The harness can't build on this computer yet",
    h("p", {}, "Its settings are missing or have a problem. Open Settings to set it up, then come back."), h("a", { class: "btn primary", href: "#/settings" }, "Open Settings")));
  const w = await get("/api/asks?wizard=1");
  const withFiles = await has("/api/attach/start");  // the message box (compose.js): pictures and files with the idea
  const pictures = withFiles ? composer({ key: "new-idea", textless: true, label: "Pictures or files for your idea" }) : null;
  const answers = {};
  // "Make another like this" and "Start one" (kinds.js startWizard): the answers they fill in, once
  try {
    const pre = JSON.parse(sessionStorage.getItem("rt-wizard-prefill") || "null");
    sessionStorage.removeItem("rt-wizard-prefill");
    if (pre) for (const [k, v] of Object.entries(pre)) if (k === "extras" || w.asks.some((a) => a.id === k)) answers[k] = v;
  } catch { /* storage unavailable: the wizard starts empty */ }
  let step = Math.max(0, w.asks.findIndex((a) => !answers[a.id]));
  const root = h("div", { class: "wizard" });
  const said = (a) => {
    const ans = answers[a.id] || {};
    return [...(ans.chosen || []).map((c) => (a.options.find((o) => o.id === c) || {}).label || c), ans.other].filter(Boolean).join(" · ");
  };
  const summary = (a, i) => h("div", { class: "wizard-row" },
    h("span", { class: "chip" }, a.header), h("span", { class: "grow" }, h("span", { class: "muted small" }, a.question), h("br"), h("b", {}, said(a))),
    h("button", { class: "small", title: "Change this answer", onclick: () => { step = i; draw(); } }, "Change"));
  const next = () => { step = w.asks.findIndex((a) => !answers[a.id]); if (step < 0) step = w.asks.length; };
  const start = () => h("article", { class: "ask ready" },
    h("div", { class: "ask-head" }, h("span", { class: "chip" }, "Ready")),
    h("h3", { class: "ask-q" }, "Make the plan?"),
    h("p", { class: "ask-detail" }, "The planner writes a plan, with its own questions for you. Nothing is built until you approve it. Making the plan costs a little, usually a few cents."),
    pictures ? h("div", { class: "stack", title: "A sketch, a photo of a drawing, a screenshot of something you like, a list: the planner looks at them with your idea." },
      h("span", { class: "muted small" }, "Pictures or files to go with it (you don't need any)"), pictures) : null,
    h("div", { class: "ask-opts" },
      h("button", { class: "ask-opt rec", type: "button", onclick: async (ev) => {
        ev.currentTarget.disabled = true;
        try {
          const r = withFiles ? await post("/api/attach/start", { key: "new-idea", wizard: answers }) : await post("/api/asks", { wizard: answers });
          toast(r.reply);
          await refreshHall();
          location.hash = projectHref(String(r.path || "").split(/[\\/]/).pop(), "plan");
        } catch (e) { toast(e.message, true); ev.currentTarget.disabled = false; }
      } }, h("b", {}, h("kbd", {}, 1), h("span", { class: "grow" }, "Make the plan"), h("span", { class: "rec-mark" }, "Recommended")), h("span", {}, "You'll see it, with its questions, in a minute or two.")),
      h("button", { class: "ask-opt", type: "button", onclick: () => { step = 0; draw(); } }, h("b", {}, h("kbd", {}, 2), "Go back"), h("span", {}, "Look at your answers again."))));
  function draw() {
    const kids = w.asks.map((a, i) => {
      if (i === step) return askCard(a, async (ans) => {
        if (a.required && !ans.other) throw new Error("Write your idea in a few words first.");
        answers[a.id] = ans; next(); draw();
      }, { sendLabel: "Next", hint: false });
      return answers[a.id] ? summary(a, i) : null;
    });
    if (step >= w.asks.length) kids.push(start());
    fill(root, kids);
    const live = root.querySelector(".ask:not(.answered)");
    if (live) setTimeout(() => { const t = live.querySelector(".ask-other:not([hidden]) textarea"); (t || live).focus(); }, 0);
  }
  draw();
  return page("New project", "Tap an answer, or choose Other… to type your own. Number keys pick, Enter sends.",
    h("a", { class: "back", href: "#/projects" }, "← Projects"), root, typeIt(w.projects_dir, withFiles));
}

// the same, typed: a folder name, the goal, what it should be like
function typeIt(dir, withFiles) {
  const name = h("input", { class: "grow", required: true, placeholder: "A short name, e.g. bakery-site", "aria-label": "Project name",
    title: `A folder with this name is made in your projects folder (${dir})` });
  const box = withFiles ? composer({ key: "new-idea-typed", rows: 4, label: "What to build",
    placeholder: "What should be built? Who is it for, what must it do, anything to avoid… Attach a sketch or a photo if you like." }) : null;
  const goal = box || h("textarea", { rows: 4, required: true, placeholder: "What should be built? Who is it for, what must it do, anything to avoid…", "aria-label": "What to build" });
  const refs = h("textarea", { rows: 2, placeholder: "Links, projects or a description, one a line (optional)", "aria-label": "Make it like this",
    title: "The harness reads each one first and makes something similar: the ideas, how it works and its style, never its name, art, music or text." });
  const approve = h("input", { type: "checkbox", checked: true });
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    try {
      const j = box ? await post("/api/attach/start", { key: "new-idea-typed", dir: name.value.trim(), goal: box.composer.text(), approve: approve.checked, references: refs.value })
        : await post("/api/projects", { dir: name.value.trim(), goal: goal.value, approve: approve.checked, references: refs.value });
      if (box) box.composer.clear();
      toast("Started: the planner is making the plan");
      await refreshHall();
      location.hash = projectHref(String(j.target || name.value).split(/[\\/]/).pop(), "plan");
    } catch (e) { toast(e.message, true); }
  } },
  h("label", { class: "field" }, h("span", { class: "label" }, "Name"), name),
  box ? h("div", { class: "field" }, h("span", { class: "label" }, "What to build"), goal) : h("label", { class: "field" }, h("span", { class: "label" }, "What to build"), goal),
  h("label", { class: "field" }, h("span", { class: "label" }, "Make it like this"), refs),
  h("label", { class: "check", title: "Recommended: you see the plan and its cost before anything is built" }, approve, "Let me approve the plan first"),
  h("div", { class: "row" }, h("button", { class: "primary" }, "Start")));
  return h("details", { class: "card fold" }, h("summary", {}, "Or write it all in one go"), form);
}
