// Settings → Advanced: "Tidy up old files automatically" and "Show what would be removed" (ui/tidyapi.py,
// retention.py). No numbers to tune here: the limits stay in the settings file.
import { h, fill, get, post, act, dialog } from "./core.js";

const TIP = "Old logs, pictures and finished tasks' working copies. Never your project's files or anything you sent.";

export async function tidyCard() {
  let st;
  try { st = await get("/api/tidy"); } catch (e) {
    return h("section", { class: "card" }, h("h2", {}, "Tidying up"), h("p", {}, `This copy can't tidy up yet: ${e.message}`));
  }
  const last = h("p", { class: "small muted", "aria-live": "polite" });
  const drawLast = (s) => fill(last, s.last ? `Last time: ${s.last.message}` : "Nothing has been tidied up yet.");
  drawLast(st);
  const out = h("div", { "aria-live": "polite" });
  const preview = (btn) => act(btn, () => post("/api/tidy/preview", {}), null, (r) => fill(out,
    h("p", {}, r.message),
    r.details.length ? h("ul", { class: "small" }, r.details.map((d) => h("li", {}, d))) : null,
    r.items.length ? h("details", {}, h("summary", { title: "Every file and folder, one per line" }, "More"),
      h("ul", { class: "small muted" }, r.items.map((i) => h("li", {}, `${i.what} · ${i.size} · ${i.path}`)))) : null));
  return h("section", { class: "card" },
    h("h2", {}, "Tidying up"),
    h("label", { class: "check", title: TIP },
      h("input", { type: "checkbox", checked: st.auto, onchange: (ev) => act(null, () => post("/api/tidy", { auto: ev.target.checked }),
        ev.target.checked ? "Old files will be tidied up once a day" : "Old files are kept", drawLast) }),
      "Tidy up old files automatically"),
    last,
    h("div", { class: "row" }, h("button", { class: "small", type: "button", title: "Nothing is removed: it only shows what would go",
      onclick: (ev) => preview(ev.currentTarget) }, "Show what would be removed")),
    out, notChosen());
}

// Attempts other models built side by side that weren't chosen (harness/rivals.py): kept as a branch and a small
// patch until the owner clears them. Never cleared automatically.
function notChosen() {
  const box = h("div", { class: "stack", "aria-live": "polite" });
  const draw = (r) => {
    const items = r.items || [];
    const byProject = {};
    items.forEach((it) => (byProject[it.path] = byProject[it.path] || []).push(it));
    const clear = (path, task, label) => async (ev) => {
      const btn = ev.currentTarget;
      if (!(await dialog({ title: "Clear attempts not chosen?", text: `${label} The chosen work stays in the project; only the other attempts' branches and patches go.`, yes: "Clear" }))) return;
      act(btn, () => post("/api/tidy/not-chosen/clear", { path, task }), null, (x) => { draw(x); });
    };
    fill(box, h("h3", { title: "When two or three models built a task side by side, the attempts not chosen are kept so you can look at them" }, "Attempts not chosen"),
      h("p", { class: "small muted" }, r.words || ""),
      items.length ? h("details", {}, h("summary", { title: "Each attempt, the project, why another was chosen, and its size" }, "More"),
        Object.entries(byProject).map(([path, its]) => h("div", {},
          h("div", { class: "row" }, h("b", {}, its[0].project), h("button", { class: "small", type: "button", title: "Removes these attempts' branches and patches. Only when you press it",
            onclick: clear(path, "", `${its.length} attempt${its.length === 1 ? "" : "s"} in ${its[0].project}.`) }, "Clear")),
          h("ul", { class: "small" }, its.map((it) => h("li", {}, `${it.task} (${it.rival})`, it.why ? ` · another was chosen: ${it.why}` : "",
            it.patch ? ` · patch ${it.size}` : "", it.branch ? h("span", { class: "muted" }, ` · branch ${it.branch}`) : null)))))) : null);
  };
  get("/api/tidy/not-chosen").then(draw).catch(() => box.remove());  // an older PC: nothing shows
  return box;
}
