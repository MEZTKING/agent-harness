// Settings → Advanced: "What you use most" (ui/countsapi.py, localcounts.py). Counted on this computer only and
// never sent anywhere; the owner sees their own numbers, can stop counting and can clear them.
import { h, fill, get, post, act, dialog } from "./core.js";
import { t } from "./words.js";

const TIP = "A number for each screen you open and each kind of button you press, per day. No project names, no text. It never leaves this computer.";

export async function countsCard() {
  let st;
  try { st = await get("/api/counts"); } catch (e) {
    return h("section", { class: "card" }, h("h2", {}, "What you use most"), h("p", {}, t("This copy can't show it yet: {e}", { e: e.message })));
  }
  const box = h("div", { "aria-live": "polite" });
  const row = (r) => h("li", {}, h("span", {}, r.name), " ", h("b", {}, String(r.count)));
  const draw = (s) => fill(box,
    h("p", {}, s.words),
    s.top.length ? h("ol", { class: "small" }, s.top.slice(0, 5).map(row)) : null,
    s.top.length > 5 || s.buttons.length ? h("details", {}, h("summary", { title: "Every screen and button family counted, and since when" }, "More"),
      h("p", { class: "small muted" }, s.since ? t(s.days === 1 ? "Counted since {since}, on 1 day." : "Counted since {since}, on {n} days.", { since: s.since, n: s.days }) : ""),
      h("h3", {}, "Screens"), h("ul", { class: "small" }, s.screens.map(row)),
      h("h3", {}, "Buttons"), h("ul", { class: "small" }, s.buttons.map(row))) : null,
    h("p", { class: "small muted" }, s.note));
  draw(st);
  const clear = async (btn) => {
    if (!(await dialog({ title: "Clear what you use most?", text: "Every number goes. Counting carries on from now unless you turn it off.", yes: "Clear" }))) return;
    act(btn, () => post("/api/counts", { action: "clear" }), "Cleared", (s) => { st = s; draw(s); });
  };
  return h("section", { class: "card" },
    h("h2", {}, "What you use most"),
    h("label", { class: "check", title: TIP },
      h("input", { type: "checkbox", checked: st.on, onchange: (ev) => act(null, () => post("/api/counts", { action: ev.target.checked ? "on" : "off" }),
        ev.target.checked ? "Counting on this computer" : "Counting stopped", (s) => { st = s; draw(s); }) }),
      "Count what I use (on this computer only)"),
    box,
    h("div", { class: "row" }, h("button", { class: "small", type: "button", title: "Removes every number. Nothing else changes", onclick: (ev) => clear(ev.currentTarget) }, "Clear")));
}
