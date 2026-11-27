// "What's new in X": a short card shown once after the app updates (ui/whatsnewapi.py). The few headlines
// first; what each one means folds under "More". "Got it" (or Escape, or a click outside) means never again
// for this version. Loaded once by the shell; does nothing when this copy has no such route.
import { BRAND, h, get, post, has } from "./core.js";

const STYLE = `
.whatsnew .lead { margin: 0; color: var(--color-muted); }
.whatsnew ul.heads { margin: 0; padding-left: 20px; }
.whatsnew ul.heads li { margin: 4px 0; font-weight: 700; }
.whatsnew details ul { margin: 8px 0 0; padding-left: 20px; }
.whatsnew details li { margin: 6px 0; }
.whatsnew details li b { display: block; }
.whatsnew .row { display: flex; justify-content: flex-end; }
`;
const HEADS = 5;
let shown = false;

export function whatsNewCard(data, onDone) {
  const back = h("div", { class: "modal-back" });
  const done = () => {
    back.remove();
    document.removeEventListener("keydown", onKey);
    if (onDone) onDone();
  };
  const onKey = (ev) => { if (ev.key === "Escape") done(); };
  const items = data.items || [];
  const heads = items.slice(0, HEADS);
  const more = items.length > HEADS ? ` ${items.length - HEADS} more under "More".` : "";
  const ok = h("button", { class: "primary", type: "button", onclick: done }, "Got it");
  const box = h("div", { class: "modal whatsnew", role: "dialog", "aria-modal": "true", "aria-labelledby": "whatsnew-title" },
    h("h2", { id: "whatsnew-title" }, data.title || "What's new"),
    h("p", { class: "lead" }, `${BRAND.name} has been updated. The main changes:`),
    h("ul", { class: "heads" }, heads.map((i) => h("li", {}, i.title))),
    more ? h("p", { class: "lead" }, more.trim()) : null,
    h("details", {},
      h("summary", { tip: "What each change means, in a sentence or two" }, "More"),
      h("ul", {}, items.map((i) => h("li", {}, h("b", {}, i.title), i.text || "")))),
    h("div", { class: "row" }, ok));
  back.append(box);
  back.addEventListener("click", (ev) => { if (ev.target === back) done(); });
  document.addEventListener("keydown", onKey);
  document.body.append(back);
  ok.focus();
  return back;
}

export async function startWhatsNew() {
  if (shown) return;
  shown = true;
  if (!(await has("/api/whatsnew"))) return;
  let data;
  try { data = await get("/api/whatsnew"); } catch { return; }
  if (!data || !data.show || !(data.items || []).length) return;
  document.head.append(h("style", {}, STYLE));
  whatsNewCard(data, () => { post("/api/whatsnew/seen", { version: data.version }).catch(() => { /* next start asks again */ }); });
}

startWhatsNew();
