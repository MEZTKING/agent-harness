// Your computers and phone: which machine builds which project, and a session from another machine.
// Kept apart so the shared-settings work can align field names in one place. Every request here is only made when
// this copy of the app has the route (core.has), so nothing fails while those parts aren't installed.
//
// Expected (and read loosely):
//   GET /api/machines -> {machines: [{id, name, kind: "pc"|"phone", this: bool, last_sync | last_seen, listening: bool,
//                                     building: [{project, state | text, task, of}] | "project id"}]}
//   GET /api/hub/session?name=&run= -> the same shape as /api/project/session (tasks with steps, outputs)
import { h, get, has, ago, every, fill, q } from "./core.js";

export const M = { list: null, at: 0 };

export async function loadMachines(force = false) {
  if (!(await has("/api/machines"))) return null;
  if (!force && M.list && Date.now() - M.at < 10000) return M.list;
  try {
    const r = await get("/api/machines");
    M.list = Array.isArray(r) ? r : r.machines || [];
    M.at = Date.now();
  } catch { M.list = M.list || []; }
  return M.list;
}

const building = (m) => {
  const b = m.building;
  if (!b) return [];
  return (Array.isArray(b) ? b : [b]).map((x) => (typeof x === "string" ? { project: x } : x || {}));
};
const machineWords = (m) => (m.this ? "this computer" : m.kind === "phone" ? (m.name ? `your phone (${m.name})` : "your phone") : m.name || "another computer");

// "Building T3 of 7 on your phone", or null when no machine says it builds this project
export function builtBy(seat) {
  for (const m of M.list || []) {
    const b = building(m).find((x) => x.project === seat.id || x.project === seat.hub_name || x.name === seat.id);
    if (!b) continue;
    const what = b.text || b.state || (b.task ? `Building ${b.task}${b.of ? ` of ${b.of}` : ""}` : "Building");
    return `${what} on ${machineWords(m)}`;
  }
  return null;
}
export function whereWords(seat) {
  const by = builtBy(seat);
  if (by) return by;
  if (seat.where === "here" || seat.path) return "On this computer";
  return seat.hub_name ? "On another computer" : "In its own sessions";
}

// a small line of chips: this PC, the phone, others; hidden when the app can't tell
export function machinesStrip() {
  const box = h("div", { class: "machines", hidden: true, "aria-label": "Your computers" });
  return every(box, async () => {
    const list = await loadMachines();
    if (!list || !list.length) { box.hidden = true; return; }
    box.hidden = false;
    fill(box, h("span", { class: "label", title: "The computers and phones that share your projects" }, "Your computers"),
      list.map((m) => {
        const seen = m.last_sync || m.last_seen || "";
        const busy = building(m).length;
        const tip = [machineWords(m), seen ? `last synced ${ago(seen)}` : "not synced yet", m.listening ? "ready for new work" : "not taking new work",
          busy ? `building ${busy} project${busy > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
        return h("span", { class: "machine" + (m.listening ? " on" : ""), title: tip },
          h("i", { class: "mdot", "aria-hidden": "true" }), m.this ? "This PC" : m.kind === "phone" ? "Phone" : m.name || "Computer",
          h("small", {}, seen ? ago(seen) : "never"));
      }));
  }, 15000);
}

// the Session view of a build running on another machine (null when the app can't show one)
export async function hubSession(seat, run) {
  if (!seat.hub_name || !(await has("/api/hub/session"))) return null;
  try { return await get(`/api/hub/session?${q({ name: seat.hub_name, run })}`); } catch { return null; }
}
