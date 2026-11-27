// Settings → Advanced: "Tidy up old files automatically" and "Show what would be removed" (ui/tidyapi.py,
// retention.py). No numbers to tune here: the limits stay in the settings file.
import { h, fill, get, post, act } from "./core.js";

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
    out);
}
