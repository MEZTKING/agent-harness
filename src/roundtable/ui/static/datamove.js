// Move my data (wave 8, p1-reach): the hub or the projects folder to a new place. Copied, checked file by file,
// then switched; the old copy is kept and never deleted, and Switch back undoes it.
// The API: ui/reachapi.py (/api/datamove).
import { h, fill, get, post, act, card, dialog, ago, fileSize } from "./core.js";

export function dataMoveCard() {
  const box = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  const load = async () => {
    let d;
    try { d = await get("/api/datamove"); } catch (e) { fill(box, h("p", { class: "muted small" }, e.message)); return; }
    const last = (d.moves || []).find((m) => !m.switched_back);
    fill(box,
      h("p", {}, "Move your hub or your projects to another folder or drive. Everything is copied and checked first; the old copy stays."),
      d.busy ? h("p", { class: "banner" }, "Something is building. Moving waits until it has finished.") : null,
      place("hub", "Your hub", d.hub.folder, d.busy, load),
      place("projects", "Your projects", d.projects.folder, d.busy, load),
      last ? h("div", { class: "row" }, h("span", { class: "grow small" }, `Last move ${ago(last.at)}: ${last.files} files (${fileSize(last.bytes)}) to ${last.to}. The old copy is still in ${last.from}.`),
        h("button", { type: "button", title: "Point everything at the old place again. Both copies stay.", onclick: async (ev) => {
          if (await dialog({ title: "Switch back?", text: `Everything points at ${last.from} again. The copy in ${last.to} is kept.`, yes: "Switch back" }))
            act(ev.currentTarget, () => post("/api/datamove", { action: "back", id: last.id }), (r) => r.words, load);
        } }, "Switch back")) : null);
  };
  load();
  return card("Move my data", box);
}

function place(what, label, folder, busy, load) {
  const to = h("input", { class: "grow", placeholder: "The new folder, for example D:\\Darkness", "aria-label": `New folder for ${label.toLowerCase()}` });
  return h("div", { class: "stack" }, h("span", { class: "label" }, label), h("span", { class: "small muted" }, folder || "Not set up yet"),
    folder ? h("div", { class: "row" }, to, h("button", { type: "button", disabled: busy, onclick: async (ev) => {
      if (!to.value.trim()) return;
      if (!(await dialog({ title: `Move ${label.toLowerCase()}?`, text: `Copied to ${to.value}, checked file by file, then used from there. The old copy stays in ${folder}.`, yes: "Move" }))) return;
      act(ev.currentTarget, () => post("/api/datamove", { action: "move", what, to: to.value.trim() }), "Moving: it shows in Activity → Background work.", () => setTimeout(load, 3000));
    } }, "Move")) : null);
}
