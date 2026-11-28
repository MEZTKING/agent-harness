// Run timelines (ui/otelapi.py, otel.py): the Settings card (timelines on or off, the coding helpers' telemetry
// on 127.0.0.1, an outside collector only with the warning ticked) and the timeline behind "More" on Watch.
import { h, fill, get, post, act, q } from "./core.js";
import { t as say } from "./words.js";

const fmt = (ms) => (ms >= 60000 ? `${Math.round(ms / 6000) / 10} min` : ms >= 1000 ? `${Math.round(ms / 100) / 10} s` : `${ms} ms`);
const NAMES = { task: "Task", model: "Model call", tool: "Tool" };

export async function tracesCard() {
  let st;
  try { st = await get("/api/otel"); } catch (e) {
    return h("section", { class: "card" }, h("h2", {}, "Run timelines"), h("p", {}, say("This copy can't keep timelines yet: {e}", { e: e.message })));
  }
  const body = h("div", { "aria-live": "polite" });
  const save = (btn, change, ok) => act(btn, () => post("/api/otel", change), ok, (s) => { st = s; draw(); });
  const draw = () => {
    const r = st.receiver;
    const addr = h("input", { type: "url", class: "grow", value: st.collector, placeholder: "https://collector.example:4318", "aria-label": "The collector's address" });
    const warned = h("input", { type: "checkbox", checked: !!st.collector });
    const helpers = Object.entries(st.helpers).map(([tool, vals]) => h("div", {}, h("b", {}, tool === "codex" ? "Codex" : "Claude Code"),
      h("pre", { class: "code small" }, Object.entries(vals).map(([k, v]) => `${k}=${v}`).join("\n"))));
    fill(body,
      h("p", {}, st.words),
      h("label", { class: "check", title: "How long each task, model call and tool took, kept in a file on this computer" },
        h("input", { type: "checkbox", checked: st.traces, onchange: (ev) => save(null, { traces: ev.target.checked }, ev.target.checked ? "Timelines on" : "Timelines off") }),
        "Keep a timeline of each run"),
      h("details", {}, h("summary", { title: "Your coding helpers' own telemetry, and an outside collector" }, "More"),
        h("label", { class: "check", title: "Claude Code and Codex can report the tokens they use. This listens on this computer only (127.0.0.1)" },
          h("input", { type: "checkbox", checked: r.on, onchange: (ev) => save(null, { receiver: ev.target.checked }, ev.target.checked ? "Listening on this computer" : "Stopped listening") }),
          "Take in my coding helpers' telemetry"),
        r.error ? h("p", { class: "small bad" }, r.error) : r.running ? h("p", { class: "small muted" }, say("Listening at {at}. Their tokens show under What's been used.", { at: r.endpoint })) : null,
        r.on ? h("details", {}, h("summary", { title: "The settings each helper needs to send here. An agent sets them for you" }, "Their settings"), helpers) : null,
        h("h3", {}, "An outside collector"),
        h("p", { class: "small muted" }, "Off unless you type an address. Projects limited to certain services never send."),
        h("div", { class: "row" }, addr),
        h("label", { class: "check" }, warned, st.warning),
        h("div", { class: "row" },
          h("button", { class: "small", type: "button", onclick: (ev) => save(ev.currentTarget, { collector: addr.value, collector_warned: warned.checked }, addr.value ? "Collector saved" : "Collector taken away") }, "Save"),
          st.collector ? h("button", { class: "small", type: "button", onclick: (ev) => save(ev.currentTarget, { collector: "" }, "Nothing is sent now") }, "Stop sending") : null),
        h("p", { class: "small muted" }, st.note)));
  };
  draw();
  return h("section", { class: "card" }, h("h2", {}, "Run timelines"), body);
}

// Behind "More" on Watch: the project's recent runs, and one as a timeline.
export function tracesFold(path) {
  const box = h("div", { "aria-live": "polite" });
  const d = h("details", { ontoggle: () => { if (d.open && !box.firstChild) list(); } },
    h("summary", { title: "How long each task, model call and tool took" }, "Timeline"), box);
  const list = async () => {
    let r;
    try { r = await get(`/api/otel/traces?${q({ path })}`); } catch (e) { fill(box, h("p", { class: "small" }, e.message)); return; }
    fill(box, h("p", { class: "small muted" }, r.words),
      r.traces.length ? h("ul", { class: "small" }, r.traces.map((t) => h("li", {},
        h("button", { class: "link", type: "button", onclick: () => show(t.id) }, `${t.task || t.name} · ${fmt(t.ms)}`),
        t.ok ? "" : h("span", { class: "bad" }, " · something failed")))) : null);
  };
  const show = async (id) => {
    let t;
    try { t = await get(`/api/otel/trace?${q({ id })}`); } catch (e) { fill(box, h("p", { class: "small" }, e.message)); return; }
    const total = Math.max(1, t.ms);
    fill(box,
      h("button", { class: "small", type: "button", onclick: list }, "Back to the runs"),
      h("div", { class: "stack small", role: "list" }, t.spans.map((s) => h("div", { role: "listitem", title: Object.entries(s.attrs).map(([k, v]) => `${k}: ${v}`).join("\n") },
        h("div", { style: `padding-inline-start:${s.depth}em` }, `${NAMES[s.name] || s.name}${s.attrs.tool ? ` · ${s.attrs.tool}` : ""}${s.attrs.model ? ` · ${s.attrs.model}` : ""} · ${fmt(s.ms)}`,
          s.ok ? "" : h("span", { class: "bad" }, ` · ${s.error || "failed"}`)),
        h("div", { style: "block-size:6px;background:var(--color-sunken);border-radius:var(--radius-sm, 3px)" },
          h("div", { style: `margin-inline-start:${(100 * s.offset_ms) / total}%;inline-size:${Math.max(0.5, (100 * s.ms) / total)}%;block-size:6px;background:${s.ok ? "var(--color-accent)" : "var(--color-bad)"};border-radius:var(--radius-sm, 3px)` }))))));
  };
  return d;
}
