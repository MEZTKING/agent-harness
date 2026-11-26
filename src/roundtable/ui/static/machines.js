// Your computers and phone: which machine builds which project, and a session from another machine.
// Kept apart so the shared-settings work can align field names in one place. Every request here is only made when
// this copy of the app has the route (core.has), so nothing fails while those parts aren't installed.
//
// The shapes (ui/syncapi.py, read loosely so a missing field never breaks a page):
//   GET /api/roundtable  seats carry machine, machine_name and building_on {machine, name, since}
//   GET /api/machines -> {this, machines: [{seat, id, name, kind: "pc"|"phone", this, online, listening, last_seen, version,
//                         building: [{key, hub_name, folder, since, run_id}], state}], claims: [{project, hub_name, folder,
//                         machine, machine_name, since, heartbeat, state, run_id, fresh}]}
//   GET /api/hub/session?name=&run=&since= -> {name, live, runs, run, events: [{at, kind, line, ...}], claim}
import { h, get, has, ago, every, fill, q } from "./core.js";

export const M = { list: null, claims: [], at: 0 };

export async function loadMachines(force = false) {
  if (!(await has("/api/machines"))) return null;
  if (!force && M.list && Date.now() - M.at < 10000) return M.list;
  try {
    const r = await get("/api/machines");
    M.list = Array.isArray(r) ? r : r.machines || [];
    M.claims = (r && r.claims) || [];
    if (r && r.this && !M.list.some((m) => m.id === r.this.id)) M.list.unshift({ ...r.this, this: true, online: true, listening: true });
    M.at = Date.now();
  } catch { M.list = M.list || []; }
  return M.list;
}

const building = (m) => {
  const b = m.building;
  if (!b) return [];
  return (Array.isArray(b) ? b : [b]).map((x) => (typeof x === "string" ? { project: x } : x || {}));
};
const machineWords = (m) => (m.this ? "this computer" : m.kind === "phone" ? "your phone" : m.name ? `your ${m.name}` : "another computer");

// "Building T3 of 7 on your phone", or null when nobody else is building it
export function builtBy(seat) {
  const claim = (M.claims || []).find((c) => c.fresh !== false && ((seat.hub_name && c.hub_name === seat.hub_name) || c.folder === seat.id));
  const on = seat.building_on || (claim ? { machine: claim.machine, name: claim.machine_name } : null);
  if (!on) {
    for (const m of M.list || []) {  // older shape: a machine's own list of what it builds
      const b = building(m).find((x) => x.project === seat.id || x.folder === seat.id || (seat.hub_name && x.hub_name === seat.hub_name));
      if (b) return `Building on ${machineWords(m)}`;
    }
    return null;
  }
  const m = (M.list || []).find((x) => x.id === on.machine) || { name: on.name, kind: String(on.machine || "").startsWith("phone-") ? "phone" : "pc" };
  if (m.this) return null;  // this computer's own work shows in its state already
  if (claim && claim.state && /\bon\b/.test(claim.state)) return claim.state;
  const task = seat.progress && seat.progress.total ? ` (${seat.progress.done} of ${seat.progress.total} done)` : "";
  return `Building on ${machineWords(m)}${task}`;
}
export function whereWords(seat) {
  const by = builtBy(seat);
  if (by) return by;
  if (seat.where === "here" || seat.path) return "On this computer";
  if (seat.machine_name) {
    const m = (M.list || []).find((x) => x.id === seat.machine) || { name: seat.machine_name, kind: String(seat.machine || "").startsWith("phone-") ? "phone" : "pc" };
    return `On ${machineWords(m)}`;
  }
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
        const tip = m.state || [machineWords(m), seen ? `last heard from ${ago(seen)}` : "not heard from yet", m.listening ? "ready for new work" : "not taking new work",
          busy ? `building ${busy} project${busy > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
        return h("span", { class: "machine" + (m.online !== false && m.listening ? " on" : "") + (m.online === false ? " off" : ""), title: tip },
          h("i", { class: "mdot", "aria-hidden": "true" }), m.this ? "This PC" : m.kind === "phone" ? "Phone" : m.name || "Computer",
          h("small", {}, seen ? ago(seen) : "never"));
      }));
  }, 15000);
}

// the Session view of a build running on another machine (null when the app can't show one)
export async function hubSession(seat, run, since = 0) {
  if (!seat.hub_name || !(await has("/api/hub/session"))) return null;
  try { return await get(`/api/hub/session?${q({ name: seat.hub_name, run, since })}`); } catch { return null; }
}
