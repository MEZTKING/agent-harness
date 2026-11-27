// Settings → Builders: how the builders work (GET/POST /api/builders, ui/permsapi.py). The existing settings,
// kept in custom.yaml: tasks at once, steps per task, web search, commands, summing up long tasks, the safety
// check's limits. Short first: the switches and "Tasks at once"; the other numbers behind "More".
import { h, get, post, has, toast, card } from "./core.js";

export async function buildersCard() {
  if (!(await has("/api/builders"))) return null;
  let st;
  try { st = await get("/api/builders"); } catch { return null; }
  const box = h("div", { class: "builders" });
  const note = h("p", { class: "muted small", role: "status" }, "");

  const save = async (key, value) => {
    try {
      const out = await post("/api/builders", { [key]: value });
      draw(out);
      if (out.not_applied && out.not_applied.length) {
        note.textContent = `Saved, but this version still takes ${out.not_applied.join(", ")} from harness.yaml.`;
      } else { note.textContent = ""; toast("Saved"); }
    } catch (e) { toast(String(e.message || e), true); draw(st); }
  };

  const line = (f) => {
    const v = st.values[f.key];
    let input;
    if (f.kind === "switch") {
      input = h("input", { type: "checkbox", "aria-label": f.label });
      input.checked = !!v;
      input.addEventListener("change", () => save(f.key, input.checked));
      return h("label", { class: "row small", title: f.tip }, input, " ", f.label);
    }
    input = h("input", { type: "number", min: String(f.min), max: String(f.max), class: "narrow", "aria-label": f.label, value: String(v ?? "") });
    input.addEventListener("change", () => {
      const n = Number(input.value);
      if (input.value === "" || Number.isNaN(n)) { input.value = String(v ?? ""); return; }
      save(f.key, n);
    });
    return h("label", { class: "row small", title: f.tip }, f.label, " ", input);
  };

  const draw = (s) => {
    st = s;
    const first = s.fields.filter((f) => !f.more).map(line);
    const more = s.fields.filter((f) => f.more).map(line);
    box.replaceChildren(
      h("p", { class: "small" }, s.words || "How the builders work."),
      ...first,
      more.length ? h("details", {}, h("summary", { title: "Steps, summing up and the safety check's limits" }, "More"), ...more) : null,
      note);
  };
  buildersStyles();
  draw(st);
  return card("Builders", box);
}

function buildersStyles() {
  if (typeof document === "undefined" || document.getElementById("builders-style")) return;
  document.head.append(h("style", { id: "builders-style" }, `
.builders .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
.builders input[type=number] { width: 7em; }
.builders details { margin-top: 8px; }
`));
}
