// Autopilot: the header switch, its card and what it did. While you're away it answers with the recommended
// answers, within a spending limit; it never raises a limit or picks anything that asks "Are you sure?".
import { h, fill, get, post, toast, ago, money, seatByPath, projectHref, projectName } from "./core.js";

let AP = null, open = false;
const UNTIL = [
  ["", "Until I'm back", "It stays on until you turn it off yourself."],
  ["1h", "1 hour", "It turns itself off in an hour."],
  ["tonight", "Overnight", "It turns itself off at 8am tomorrow."],
  ["custom", "Until…", "Pick the time it turns itself off."],
];
export async function loadAutopilot(soft = false) {
  try { drawAutopilot(await get("/api/autopilot?limit=40"), soft); } catch { /* the header can do without it */ }
}
export function drawAutopilot(st, soft = false) {
  const box = document.getElementById("autopilot");
  if (!box) return;
  const was = AP && AP.on;
  AP = { ...(AP || {}), ...st };
  if (soft && open && box.querySelector(".ap-card") && was === AP.on) { box.querySelector(".ap-toggle").replaceWith(button()); return; }
  fill(box, button(), open ? panel() : null);
}
function button() {
  const on = AP.on;
  return h("button", { type: "button", class: "ap-toggle" + (on ? " on" : ""), "aria-expanded": String(open), "aria-haspopup": "dialog",
    title: on ? "Autopilot is answering what waits for you with the recommended answers. Click to see what it did, or to turn it off."
      : "Autopilot: while you're away, Roundtable answers what waits for you with the recommended answers. Click to set it up.",
    onclick: () => { open = !open; drawAutopilot({}); if (open) loadAutopilot(); } },
  h("i", { class: "ap-dot", "aria-hidden": "true" }), h("b", {}, "Autopilot"), on ? h("span", { class: "ap-label" }, words(AP)) : null);
}
const words = (a) => (a.until ? `until ${a.until_label}` : "on") + ` · ${money(a.spent_usd)} of ${money(a.spend_cap_usd)}`;
function panel() {
  const close = () => { open = false; drawAutopilot({}); };
  return h("div", { class: "ap-card", role: "dialog", "aria-label": "Autopilot", onkeydown: (ev) => { if (ev.key === "Escape") close(); } },
    h("div", { class: "card-head" }, h("h2", {}, "Autopilot"), h("button", { class: "link-btn", type: "button", onclick: close }, "Close")),
    AP.on ? onPart() : offPart(),
    h("h3", {}, "What autopilot did"), log());
}
function onPart() {
  return [h("p", { class: "ap-now" }, h("b", {}, "On"), ` · ${words(AP)}`),
    h("p", { class: "small muted" }, "It answers with the recommended answer, tries a failed task once more and starts a plan when its cost fits the limit. Money stops and anything that asks “Are you sure?” wait for you."),
    h("div", { class: "row" }, h("button", { class: "primary", type: "button", onclick: async () => {
      try { drawAutopilot(await post("/api/autopilot", { action: "off" })); toast("Autopilot is off"); } catch (e) { toast(e.message, true); }
    } }, "Turn off"))];
}
function offPart() {
  let until = "";
  const custom = h("input", { type: "time", value: "08:00", hidden: true, "aria-label": "Turn off at", title: "The time it turns itself off (this computer's time)" });
  const choices = h("div", { class: "seg", role: "group", "aria-label": "Until" }, UNTIL.map(([v, label, tip]) =>
    h("button", { type: "button", class: v === until ? "on" : "", title: tip, "aria-pressed": String(v === until), onclick: (ev) => {
      until = v; custom.hidden = v !== "custom";
      choices.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b === ev.currentTarget); b.setAttribute("aria-pressed", String(b === ev.currentTarget)); });
    } }, label)));
  const cap = h("input", { type: "number", min: "0.5", max: "1000", step: "0.5", value: Number(AP.spend_cap_usd || 2).toFixed(2), class: "ap-cap",
    "aria-label": "Spending limit in dollars", title: "The most autopilot may spend while it's on, on every project together. When it gets there it turns itself off." });
  const go = h("button", { class: "primary", type: "button", onclick: async () => {
    go.disabled = true;
    try {
      const r = await post("/api/autopilot", { action: "on", until: until === "custom" ? custom.value : until, cap: Number(cap.value) });
      drawAutopilot(r); toast(`Autopilot is on, ${words(r)}`);
    } catch (e) { toast(e.message, true); go.disabled = false; }
  } }, "Turn on");
  return [h("p", { class: "small muted" }, "While you're away, Roundtable answers what waits for you with the recommended answer and writes down every choice. It never raises a limit, never picks anything that asks “Are you sure?”, and never deletes, publishes or releases anything."),
    h("div", { class: "stack" }, h("span", { class: "label" }, "Until"), choices, custom),
    h("div", { class: "stack" }, h("span", { class: "label", title: "The most it may spend while it's on" }, "Spending limit"),
      h("span", { class: "row" }, h("b", {}, "$"), cap, h("span", { class: "small muted" }, "then it stops"))),
    h("div", { class: "row" }, go)];
}
function log() {
  const items = AP.log || [];
  if (!items.length) return h("p", { class: "muted small" }, "Nothing yet. Its choices show up here, newest first.");
  return h("ul", { class: "ap-log" }, items.map((e) => {
    const seat = e.path ? seatByPath(e.path) : null, id = seat ? seat.id : e.project;
    return h("li", { class: "ap-" + e.kind }, h("time", { title: e.at }, ago(e.at)),
      id ? h("a", { href: projectHref(id), onclick: () => { open = false; drawAutopilot({}); } }, projectName(id)) : null,
      h("span", {}, e.text));
  }));
}
document.addEventListener("click", (ev) => {  // a click elsewhere closes the card
  const box = document.getElementById("autopilot");
  if (open && box && !box.contains(ev.target) && ev.target.isConnected) { open = false; drawAutopilot({}); }
});
