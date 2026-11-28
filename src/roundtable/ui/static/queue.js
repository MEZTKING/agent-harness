// The messages waiting for the next task (GET/POST /api/queue): listed above the message box, each with
// Send now (to the task working now), Change and Remove. Once a task has read a message it leaves the list.
import { h, fill, get, post, q, toast, every, patch, clock } from "./core.js";
import { t } from "./words.js";

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "queue" }, `
.qu { display: flex; flex-direction: column; gap: 6px; }
.qu-head { font-size: 12.5px; color: var(--color-muted); font-weight: 700; }
.qu-item { display: flex; gap: 8px; align-items: flex-start; flex-wrap: wrap; padding: 6px 8px; border: 1px dashed var(--color-line-strong);
  border-radius: var(--radius-small); background: var(--color-sunken); font-size: 13px; }
.qu-item .t { flex: 1; min-width: 160px; white-space: pre-wrap; overflow-wrap: anywhere; }
.qu-item textarea { flex: 1; min-width: 160px; }
.qu-item .acts { display: flex; gap: 4px; }
`));
}

// The list for one project; empty (and hidden) when nothing waits. Asked for every few seconds while shown.
export function queueList(path) {
  style();
  const node = h("div", { class: "qu", hidden: true, "aria-live": "polite" });
  let editing = null;
  const act = async (btn, body, after) => {
    btn.disabled = true;
    try { const r = await post("/api/queue", { path, ...body }); toast(r.reply || "Done"); draw(r); if (after) after(); }
    catch (e) { toast(e.message, true); load(); }
    finally { if (btn.isConnected) btn.disabled = false; }
  };
  function item(x, running) {
    if (editing === x.id) {
      const field = h("textarea", { rows: 2, "aria-label": "The message, changed" });
      field.value = x.text;
      setTimeout(() => field.focus(), 0);
      return h("div", { class: "qu-item" }, field, h("span", { class: "acts" },
        h("button", { type: "button", class: "small primary", onclick: (ev) => act(ev.currentTarget, { action: "change", id: x.id, text: field.value }, () => { editing = null; }) }, "Save"),
        h("button", { type: "button", class: "small", onclick: () => { editing = null; load(true); } }, "Cancel")));
    }
    return h("div", { class: "qu-item" }, h("span", { class: "t", title: x.at ? t("Written at {v1}", { v1: clock(x.at) }) : "" }, x.text), h("span", { class: "acts" },
      running ? h("button", { type: "button", class: "small", title: "Give it to the task working now, at its next step", onclick: (ev) => act(ev.currentTarget, { action: "send_now", id: x.id }) }, "Send now") : null,
      h("button", { type: "button", class: "small", title: "Change the words before a task reads them", onclick: () => { editing = x.id; load(true); } }, "Change"),
      h("button", { type: "button", class: "small", title: "Take it back: no task will read it", onclick: (ev) => act(ev.currentTarget, { action: "remove", id: x.id }) }, "Remove")));
  }
  function draw(r, force = false) {
    const items = r.items || [];
    node.hidden = !items.length;
    const build = () => [h("div", { class: "qu-head", title: "Instructions you gave that no task has read yet" },
      items.length === 1 ? "Waiting for the next task" : t("{length} messages waiting for the next task", { length: items.length })), items.map((x) => item(x, r.running))];
    if (force) { node._sig = undefined; fill(node, build()); node._sig = JSON.stringify([items, r.running, editing]); }
    else patch(node, JSON.stringify([items, r.running, editing]), build);
  }
  async function load(force = false) {
    try { draw(await get("/api/queue?" + q({ path })), force); } catch { /* an older app: no queue */ }
  }
  node.refresh = () => load(true);
  every(node, () => (editing ? undefined : load()), 4000);
  return node;
}
