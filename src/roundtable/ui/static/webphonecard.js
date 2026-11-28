// Settings → Your phone: "The page for an iPhone" (ui/webphoneapi.py, webphone.py). Built switched off: it can only
// be turned on after advice on its certificate warning and the owner's yes. The certificate to compare is shown here.
import { h, fill, get, post, act } from "./core.js";

export async function webPhoneCard() {
  let st;
  try { st = await get("/api/webphone"); } catch { return null; }  // an older PC: nothing shows
  const box = h("div", { "aria-live": "polite" });
  const draw = () => fill(box,
    h("p", {}, st.words),
    h("label", { class: "check", title: st.can_turn_on ? "Serves your projects as a page on this Wi-Fi, to paired iPhones only" : st.why_not },
      h("input", { type: "checkbox", checked: st.enabled, disabled: !st.can_turn_on && !st.enabled,
        onchange: (ev) => act(null, () => post("/api/webphone", { enabled: ev.target.checked }), ev.target.checked ? "The page is on" : "The page is off", (s) => { st = s; draw(); }) }),
      "Open my projects on an iPhone"),
    st.links.length ? h("ul", { class: "small" }, st.links.map((l) => h("li", {}, h("code", { raw: true }, l)))) : null,
    st.enabled ? h("details", {}, h("summary", { title: "What to check in Safari's warning before you pair" }, "More"),
      h("p", { class: "small" }, st.warning),
      st.fingerprint ? h("p", { class: "small" }, "SHA-256: ", h("code", { class: "wp-words", raw: true }, st.fingerprint)) : null,
      st.fingerprint_words.length ? h("p", { class: "small" }, "The same as words: ", h("b", { raw: true }, st.fingerprint_words.join(" "))) : null,
      st.devices.length ? h("p", { class: "small muted" }, "Paired iPhones show in the list of phones above, where each can be removed.") : null) : null);
  draw();
  return h("section", { class: "card" }, h("h2", {}, "The page for an iPhone"), box);
}
