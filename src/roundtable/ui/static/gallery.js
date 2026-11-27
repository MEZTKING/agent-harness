// The Gallery (ui/kindsapi.py): everything finished, and what Roundtable can make. Hiding never deletes;
// the Gallery has no delete at all. Model ids and the commit fold behind "More".
import { h, fill, get, post, act, page, tabs, empty, picture, seatByPath, projectHref, money } from "./core.js";
import { kindsTab, kindStyles, startWizard } from "./kinds.js";

const TABS = [["finished", "Finished", "Everything Roundtable has finished for you"],
  ["make", "What Roundtable can make", "The kinds of thing Roundtable knows how to build and check"]];

export async function viewGallery(tab = "finished", project, goal) {
  galleryStyles(); kindStyles();
  const head = tabs(TABS, tab, (k) => `#/gallery/${k}`, "Parts of the Gallery");
  if (tab === "make") return page("Gallery", "What Roundtable can make, and how sure it is of each.", head, await kindsTab());
  if (project && goal) return page("Gallery", null, head, await entryView(project, goal));
  const box = h("div", {});
  let hidden = false;
  const draw = async () => {
    const d = await get(`/api/gallery${hidden ? "?hidden=1" : ""}`);
    fill(box,
      d.entries.length ? h("div", { class: "gl-grid" }, d.entries.map(tile)) : empty(d.words, h("a", { class: "btn primary", href: "#/new" }, "+ New project")),
      h("label", { class: "check small muted", title: "Hidden ones are kept: nothing is ever deleted here" },
        h("input", { type: "checkbox", checked: hidden, onchange: (ev) => { hidden = ev.target.checked; draw(); } }), "Show hidden ones too"));
  };
  await draw();
  return page("Gallery", "Everything finished, newest first.", head, box);
}

function tile(e) {
  return h("a", { class: "gl-tile" + (e.hidden ? " gl-hidden" : ""), href: `#/gallery/finished/${encodeURIComponent(e.project)}/${encodeURIComponent(e.goal)}` },
    e.cover ? h("img", { src: e.cover, alt: "", loading: "lazy" }) : h("div", { class: "gl-nocover", "aria-hidden": "true" }, "No picture"),
    h("div", { class: "gl-cap" },
      h("b", {}, e.starred ? "★ " : "", e.title),
      h("div", { class: "gl-line" }, e.kind_name ? h("span", { class: "chip" }, e.kind_name) : null, h("span", { class: "small muted" }, e.line))));
}

async function entryView(project, goal) {
  let e;
  try { e = await get(`/api/gallery/one?project=${encodeURIComponent(project)}&goal=${encodeURIComponent(goal)}`); }
  catch (err) { return empty(`Couldn't open it: ${err.message}`, h("a", { href: "#/gallery" }, "Back to the Gallery")); }
  const seat = seatByPath(e.path);
  const seatId = seat ? seat.id : project;
  const box = h("article", { class: "card gl-one" });
  const flag = (btn, what, value) => act(btn, () => post(`/api/gallery/${what}`, { project, goal, [what === "hide" ? "hidden" : "starred"]: value }),
    what === "hide" ? (value ? "Hidden. It's kept: tick \"Show hidden ones too\" to see it." : "Shown again") : null,
    () => { location.hash = what === "hide" && value ? "#/gallery" : location.hash; if (!(what === "hide" && value)) entryView(project, goal).then((n) => box.replaceWith(n)); });
  const again = (btn) => act(btn, () => post("/api/gallery/again", { project, goal }), (r) => r.reply, (r) => startWizard(r.wizard));
  const m = e.more || {};
  fill(box,
    h("div", { class: "gl-onehead" }, h("h2", {}, e.title), e.kind_name ? h("span", { class: "chip" }, e.kind_name) : null),
    h("p", { class: "muted" }, e.line),
    e.summary ? h("p", {}, e.summary) : null,
    e.pictures.length ? h("div", { class: "strip" }, e.pictures.map((p) => picture(p.src, `${e.title}: ${p.name}`))) : null,
    e.proof_words ? h("p", { class: "gl-proof", title: "What Roundtable checked. \"Not checked yet\" means it couldn't check that by itself." }, e.proof_words) : null,
    h("div", { class: "row" },
      h("a", { class: "btn primary", href: projectHref(seatId, "live"), title: e.outputs.length ? e.outputs.map((o) => o.path).join(", ") : "See it working" }, "Open it"),
      h("a", { class: "btn", href: projectHref(seatId) }, "Open the project"),
      h("button", { type: "button", title: "A new project of the same kind, with the same models. No files are copied.", onclick: (ev) => again(ev.currentTarget) }, "Make another like this"),
      h("button", { type: "button", class: "quiet", title: e.starred ? "Take the star off" : "Keep it at the front", onclick: (ev) => flag(ev.currentTarget, "star", !e.starred) }, e.starred ? "Unstar" : "Star"),
      h("button", { type: "button", class: "quiet", title: e.hidden ? "Show it in the Gallery again" : "Hide it from the Gallery. Nothing is deleted.", onclick: (ev) => flag(ev.currentTarget, "hide", !e.hidden) }, e.hidden ? "Show again" : "Hide")),
    h("details", { class: "fold" }, h("summary", {}, "More"),
      h("ul", { class: "small plain" },
        h("li", {}, `${e.tasks} tasks · ${money(e.cost.counted_usd)} counted` + (e.cost.real_usd != null ? ` · ${money(e.cost.real_usd)} real` : "")),
        e.extras.length ? h("li", {}, "Also packed as: ", e.extras.map((x) => x.name).join(", ")) : null,
        e.outputs.length ? h("li", {}, "Made: ", e.outputs.map((o) => o.path).join(", ")) : null,
        m.commit ? h("li", { class: "muted" }, `Version ${String(m.commit).slice(0, 10)}`) : null,
        (m.models || []).length ? h("li", {}, "Who did each job: ", m.models.map((x) => `${x.task} ${x.role}: ${x.model}`).join(" · ")) : null)),
    h("p", {}, h("a", { href: "#/gallery" }, "Back to the Gallery")));
  return box;
}

function galleryStyles() {
  if (typeof document === "undefined" || document.getElementById("gl-style")) return;
  document.head.append(h("style", { id: "gl-style" }, `
.gl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-bottom: 12px; }
.gl-tile { display: flex; flex-direction: column; border: 1px solid var(--color-oak-line); border-radius: var(--radius-small); overflow: hidden; background: var(--color-surface); color: inherit; text-decoration: none; }
.gl-tile:hover, .gl-tile:focus-visible { border-color: var(--color-accent); }
.gl-tile img, .gl-nocover { width: 100%; aspect-ratio: 16 / 10; object-fit: cover; background: var(--color-sunken); }
.gl-nocover { display: grid; place-items: center; color: var(--color-muted); font-size: 12px; }
.gl-cap { padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.gl-cap b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gl-line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.gl-hidden { opacity: .55; }
.gl-onehead { display: flex; gap: 10px; align-items: center; } .gl-onehead h2 { margin: 0; }
.gl-proof { font-weight: 600; }
`));
}
