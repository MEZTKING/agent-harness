// Settings → How agents write: the owner's house style (GET/POST /api/style, ui/styleapi.py).
// A text box, Reset, one line of help. Only the owner changes it: learning never does.
import { h, get, post, has, toast } from "./core.js";

export async function houseStyleBox() {
  if (!(await has("/api/style"))) return null;
  let s;
  try { s = await get("/api/style"); } catch { return null; }
  const words = h("p", { class: "muted small" }, s.words || "");
  const count = h("span", { class: "muted small" }, "");
  const text = h("textarea", { rows: "4", maxlength: String(s.max_chars || 1200), "aria-label": "Your house style",
    title: "Added to every agent's instructions under “How to write for the owner”", style: "width: 100%" });
  text.value = s.text || "";
  const on = h("input", { type: "checkbox", "aria-label": "Use my house style" });
  on.checked = !!s.on;
  const showCount = () => { count.textContent = `${text.value.length} of ${s.max_chars || 1200} characters`; };
  showCount();
  const apply = (out) => { s = out; text.value = out.text || ""; on.checked = !!out.on; words.textContent = out.words || ""; showCount(); };
  const save = async (body) => {
    try { apply(await post("/api/style", body)); toast("Saved"); }
    catch (e) { toast(String(e.message || e), true); }
  };
  text.addEventListener("input", showCount);
  text.addEventListener("change", () => save({ text: text.value }));
  on.addEventListener("change", () => save({ on: on.checked }));
  const reset = h("button", { class: "btn", type: "button", title: "Put back the short default: " + (s.default_text || "") }, "Reset");
  reset.addEventListener("click", () => save({ reset: true }));
  return h("div", { class: "house-style" },
    h("h3", {}, "How agents write"),
    h("p", { class: "small" }, "How every agent writes to you: plans, summaries and questions."),
    h("label", { class: "small row" }, on, " Use my house style"),
    text,
    h("div", { class: "row" }, reset, count),
    words);
}
