// Letters: what projects and agents wrote to you, as sentences; reply in place; read ones folded away. Write to any
// project. (The hub's messages.)
import { h, fill, get, post, S, act, card, page, ago, empty, seg, toast, refreshHall, projectName, projectHref, dot, plural, q } from "./core.js";
import { composer } from "./compose.js";
import { t as wt } from "./words.js";

const KIND_VERB = { ask: "asks", notify: "lets you know", request: "asks you to do something" };
const KINDS = [["ask", "A question", "They should answer"], ["notify", "Just so you know", "No answer needed"], ["request", "Please do this", "A job for them"]];

export function letterRow(m, me, done, compact = false) {
  // the reply box (compose.js, words only: its draft is kept, Speak where this browser can), made when first opened
  const replyBox = h("div", { class: "reply", hidden: true });
  const openReply = () => {
    if (!replyBox.firstChild) replyBox.append(composer({ key: `reply:${m.id}`, noFiles: true, rows: 2, label: "Your reply",
      placeholder: wt("Reply to {v1}…", { v1: projectName(m.sender) }), onSend: async ({ text }) => {
        await post("/api/reply", { as: me, message_id: m.id, body: text });
        toast("Reply sent");
        if (!m.read) await post(`/api/inbox/${encodeURIComponent(me)}/read`, { ids: [m.id] }).catch(() => null);
        if (done) await done();
      } }));
    replyBox.hidden = !replyBox.hidden;
    if (!replyBox.hidden) replyBox.firstChild.composer.focus();
  };
  const thread = h("div", { class: "thread" });
  const subj = String(m.subject || "").replace(/^roundtable:\s*/i, "");
  const line = h("p", { class: "letter-line" }, h("a", { href: projectHref(m.sender), title: "Open this project" }, dot(m.sender), h("b", {}, projectName(m.sender))), ` ${KIND_VERB[m.kind] || "writes"}: `,
      h("b", {}, subj), h("span", { class: "muted small" }, ` · ${ago(m.created_at)}`));
  const rest = [m.body && m.body !== m.subject ? h("p", { class: "letter-body pre-line" }, compact && m.body.length > 280 ? m.body.slice(0, 280) + "…" : m.body) : null,
    h("div", { class: "row" },
      h("button", { class: "small", onclick: openReply }, "Reply"),
      !m.read ? h("button", { class: "small", title: "Fold it away with the read letters", onclick: (ev) => act(ev.currentTarget, () => post(`/api/inbox/${encodeURIComponent(me)}/read`, { ids: [m.id] }), null, done) }, "Mark read") : null,
      compact ? null : h("button", { class: "small link-btn", title: "The letters before and after this one", onclick: async () => {
        try {
          const t = await get(`/api/thread?${q({ as: me, thread: m.thread_id })}`);
          fill(thread, t.length > 1 ? t.map((x) => h("p", { class: "small" }, h("b", {}, projectName(x.sender)), wt(" to {v1}, {v2}: ", { v1: projectName(x.recipient), v2: ago(x.created_at) }), x.body)) : h("p", { class: "muted small" }, "Just this one."));
        } catch (e) { toast(e.message, true); }
      } }, "The whole conversation")),
    replyBox, thread];
  // short first: one line a letter on the Letters page; it opens with a click (Needs you shows it whole)
  if (compact) return h("article", { class: "letter" + (m.read ? "" : " unread") + " compact" }, line, rest);
  return h("details", { class: "letter fold-letter" + (m.read ? "" : " unread") }, h("summary", { title: "Open the letter" }, line), rest);
}

export async function viewLetters(asAgent) {
  if (!S.ov.hub) {
    return page("Letters", null, card("Letters need the hub", h("p", {}, "Projects write to you through the hub. Connect it in Settings and your letters show up here."),
      h("a", { class: "btn primary", href: "#/settings/hub" }, "Connect the hub")));
  }
  const agents = S.ov.agents || [];
  const me = asAgent || S.ov.agent || (agents[0] || {}).id;
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const box = h("div", { class: "stack" });
  const reload = async () => {
    const msgs = (await get(`/api/inbox/${encodeURIComponent(me)}?all=1`)).slice().reverse();
    const unread = msgs.filter((m) => !m.read), read = msgs.filter((m) => m.read);
    fill(box,
      unread.length ? h("div", { class: "row" }, h("h2", { class: "section-title grow" }, plural(unread.length, "new letter")),
        h("button", { onclick: (ev) => act(ev.currentTarget, () => post(`/api/inbox/${encodeURIComponent(me)}/read`, { ids: unread.map((m) => m.id) }), "All marked read", done) }, "Mark all read")) : null,
      unread.length ? unread.map((m) => letterRow(m, me, done)) : empty("No new letters. When a project or an agent writes to you, it shows up here, and in Needs you."),
      read.length ? h("details", { class: "card fold" }, h("summary", {}, wt("Read letters ({length})", { length: read.length })), read.slice(0, 100).map((m) => letterRow(m, me, done))) : null);
  };
  const done = async () => { await reload(); await refreshHall(); };
  await reload();
  const others = agents.filter((a) => a.id !== me);
  return page(me === S.ov.agent ? "Letters" : wt("Letters to {v1}", { v1: projectName(me) }), null, box, compose(me, others, params.get("to")),
    h("details", { class: "card fold" }, h("summary", { title: "Read the letters another project received" }, "Read another project's letters"),
      h("div", { class: "row" }, h("select", { "aria-label": "Whose letters", onchange: (ev) => { location.hash = `#/letters/${encodeURIComponent(ev.target.value)}`; } },
        agents.map((a) => h("option", { value: a.id, selected: a.id === me }, a.name || a.id))))));
}

function compose(me, others, to) {
  let kind = "ask";
  const picks = h("div", { class: "to-list" }, others.map((a) => h("label", { class: "check" }, h("input", { type: "checkbox", value: a.id, checked: a.id === to }), a.name || projectName(a.id))));
  const subject = h("input", { class: "grow", placeholder: "In a few words", "aria-label": "Subject" });
  const body = composer({ key: "letter:new", noFiles: true, rows: 4, label: "Your letter", placeholder: "Your letter" });
  const form = h("form", { class: "stack", onsubmit: async (ev) => {
    ev.preventDefault();
    const tos = [...picks.querySelectorAll("input:checked")].map((x) => x.value);
    if (!tos.length) return toast("Tick who it's for.", true);
    const text = body.composer.text().trim();
    if (!subject.value.trim() || !text) return toast("Write a few words and the letter first.", true);
    await act(form.querySelector("button.primary"), () => post("/api/send", { from: me, to: tos, kind, subject: subject.value.trim(), body: text }), "Sent", () => {
      subject.value = ""; body.composer.clear(); picks.querySelectorAll("input").forEach((x) => (x.checked = false));
    });
  } },
  h("div", { class: "field" }, h("span", { class: "label" }, "To"), others.length ? picks : h("p", { class: "muted" }, "No projects in the hub yet.")),
  h("div", { class: "field" }, h("span", { class: "label" }, "Kind"), seg(KINDS, kind, (v) => { kind = v; }, "Kind of letter")),
  h("label", { class: "field" }, h("span", { class: "label" }, "About"), subject),
  body, h("div", { class: "row" }, h("button", { class: "primary" }, "Send")));
  const d = h("details", { class: "card fold", open: !!to }, h("summary", {}, "Write a letter"), form);
  return d;
}
