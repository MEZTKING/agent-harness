// The project's git history in the Files tab (MD-70): the newest changes first (each task's, your own edits,
// put-backs), open one to see the files it changed with lines added and removed, open a file to see its change
// line by line. Branches: compare two, or switch to another (only with nothing unsaved and nothing running; what
// will change is shown first and where it was is kept). Reading only, apart from that switch. API: ui/editapi.py.
import { h, fill, get, post, q, act, ago, dialog, plural } from "./core.js";
import { highlight, highlightStyles, langName } from "./highlight.js";
import { t } from "./words.js";

const KIND = { task: "A task", hand: "Your edit", put_back: "Put back", undo: "Undone", merge: "Joined in", other: "" };
const CHANGE = { added: "new", changed: "changed", removed: "removed", renamed: "renamed", copied: "copied" };
const EXT_LANG = (f) => langName((f.match(/\.([\w]+)$/) || [])[1] || "");

export function historyView(path) {
  gitStyles();
  highlightStyles();
  const box = h("div", { class: "gl" });
  const list = h("div", { class: "gl-list" });
  const detail = h("div", { class: "gl-detail" }, h("p", { class: "muted" }, "Pick a change to see what it did."));
  let branch = "", skip = 0, rows = [];
  const head = h("div", { class: "row gl-head" });

  const load = async (more) => {
    if (!more) { skip = 0; rows = []; }
    let d;
    try { d = await get(`/api/git/log?${q({ path, branch, skip, limit: 40 })}`); }
    catch (e) { fill(list, h("p", { class: "muted" }, e.message)); return; }
    rows = rows.concat(d.commits);
    skip = rows.length;
    fill(list,
      rows.length ? h("ul", { class: "gl-commits" }, rows.map((c) => h("li", {},
        h("button", { type: "button", class: "gl-row", title: `${c.subject}\n${c.author}, ${new Date(c.at).toLocaleString()}`,
          onclick: (ev) => { for (const b of list.querySelectorAll(".gl-row")) b.removeAttribute("aria-current"); ev.currentTarget.setAttribute("aria-current", "true"); openCommit(c.sha); } },
          h("span", { class: "gl-subject" }, c.subject),
          h("span", { class: "muted small" }, [KIND[c.kind] || "", ago(c.at), c.short].filter(Boolean).join(" · ")))))) : h("p", { class: "muted" }, "No changes yet."),
      d.more ? h("button", { type: "button", onclick: (ev) => act(ev.currentTarget, () => load(true)) }, "Show older") : null);
  };

  const openCommit = async (sha) => {
    fill(detail, h("p", { class: "muted" }, "Opening…"));
    let c;
    try { c = await get(`/api/git/commit?${q({ path, sha })}`); } catch (e) { fill(detail, h("p", { class: "bad" }, e.message)); return; }
    const diffBox = h("div", { class: "gl-diff" });
    fill(detail,
      h("h3", {}, c.subject),
      h("p", { class: "muted small" }, `${c.author} · ${new Date(c.at).toLocaleString()} · ${c.short}`),
      c.body ? h("details", {}, h("summary", { class: "small" }, "More"), h("pre", { class: "log short" }, c.body)) : null,
      h("p", {}, t("{v1} changed", { v1: plural(c.files.length, "file") }), h("span", { class: "gl-add" }, ` +${c.added}`), h("span", { class: "gl-del" }, ` −${c.removed}`)),
      h("ul", { class: "gl-files" }, c.files.map((f) => h("li", {},
        f.private ? h("span", { class: "muted", title: "Kept private: keys, passwords and the harness's own records are never shown" }, f.path, " (private)")
          : h("button", { type: "button", class: "gl-file", onclick: () => openDiff(c.sha, f.path, diffBox) },
            h("span", { class: "grow mono" }, f.path), h("span", { class: "muted small" }, CHANGE[f.change] || f.change),
            f.binary ? h("span", { class: "muted small" }, " picture or other file") : [h("span", { class: "gl-add small" }, ` +${f.added}`), h("span", { class: "gl-del small" }, ` −${f.removed}`)])))),
      diffBox);
    const first = c.files.find((f) => !f.private);
    if (first && c.files.length <= 3) openDiff(c.sha, first.path, diffBox);
  };

  const openDiff = async (sha, file, box) => {
    fill(box, h("p", { class: "muted" }, "Opening…"));
    let d;
    try { d = await get(`/api/git/diff?${q({ path, sha, file })}`); } catch (e) { fill(box, h("p", { class: "bad" }, e.message)); return; }
    fill(box, diffView(d));
  };

  const branches = async () => {
    let b;
    try { b = await get(`/api/git/branches?${q({ path })}`); } catch (e) { fill(head, h("p", { class: "muted" }, e.message)); return false; }
    const names = b.branches.map((x) => x.name);
    const pick = h("select", { "aria-label": "Which branch's history to show", title: "Which branch's history to show" },
      names.map((n) => h("option", { value: n, selected: n === (branch || b.current) || null }, n + (n === b.current ? " (where it is now)" : ""))));
    pick.addEventListener("change", () => { branch = pick.value === b.current ? "" : pick.value; load(false); });
    fill(head, h("span", { class: "small" }, "Branch "), pick,
      names.length > 1 ? h("button", { type: "button", title: "See how two branches differ", onclick: () => compare(names, b.current) }, "Compare") : null,
      names.length > 1 ? h("button", { type: "button", title: "Move the project's files to another branch. What changes is shown first.", onclick: () => switchTo(names.filter((n) => n !== b.current)) }, "Switch branch…") : null);
    return true;
  };

  const compare = (names, current) => {
    const a = h("select", { "aria-label": "First branch" }, names.map((n) => h("option", { value: n, selected: n === current || null }, n)));
    const bsel = h("select", { "aria-label": "Second branch" }, names.map((n, i) => h("option", { value: n, selected: (n !== current && i === names.findIndex((x) => x !== current)) || null }, n)));
    const out = h("div");
    const go = async () => {
      try {
        const d = await get(`/api/git/compare?${q({ path, a: a.value, b: bsel.value })}`);
        fill(out, h("p", {}, t("{b} has {v1} that {a} hasn't; {a} has {v2} that {b} hasn't. {v3} differ.", { b: d.b, v1: plural(d.only_b, "change"), a: d.a, v2: plural(d.only_a, "change"), v3: plural(d.files.length, "file") })),
          h("ul", { class: "gl-files" }, d.files.map((f) => h("li", { class: "small" }, h("span", { class: "mono" }, f.path), " ", h("span", { class: "muted" }, CHANGE[f.change] || f.change),
            f.private ? h("span", { class: "muted" }, " (private)") : [h("span", { class: "gl-add" }, ` +${f.added}`), h("span", { class: "gl-del" }, ` −${f.removed}`)]))));
      } catch (e) { fill(out, h("p", { class: "bad" }, e.message)); }
    };
    a.addEventListener("change", go);
    bsel.addEventListener("change", go);
    fill(detail, h("h3", {}, "Compare branches"), h("div", { class: "row" }, a, h("span", {}, " and "), bsel), out);
    go();
  };

  const switchTo = async (others) => {
    const pick = h("select", { "aria-label": "Branch to switch to" }, others.map((n) => h("option", { value: n }, n)));
    const out = h("div");
    let pv = null;
    const look = async () => {
      try { pv = await get(`/api/git/checkout?${q({ path, branch: pick.value })}`); } catch (e) { fill(out, h("p", { class: "bad" }, e.message)); pv = null; return; }
      fill(out, h("p", { class: pv.blocked ? "bad" : "" }, pv.words),
        pv.files.length ? h("ul", { class: "gl-files" }, pv.files.slice(0, 200).map((f) => h("li", { class: "small mono" }, f.path, " ", h("span", { class: "muted" }, CHANGE[f.change] || f.change)))) : null,
        h("button", { type: "button", class: "primary", disabled: pv.blocked || !pv.stamp || null, title: pv.blocked || "Switch the project's files to this branch",
          onclick: (ev) => act(ev.currentTarget, async () => {
            if (!(await dialog({ title: t("Switch to {branch}?", { branch: pv.branch }), text: pv.words, yes: "Switch" }))) return null;
            return post("/api/git/checkout", { path, branch: pv.branch, stamp: pv.stamp });
          }, (r) => (r ? r.words : ""), async (r) => { if (r) { branch = ""; await branches(); load(false); fill(detail); } }) }, "Switch"));
    };
    pick.addEventListener("change", look);
    fill(detail, h("h3", {}, "Switch branch"), h("div", { class: "row" }, h("span", {}, "To "), pick), out);
    look();
  };

  (async () => { if (await branches()) load(false); })();
  fill(box, head, h("div", { class: "files-split" }, list, detail));
  return box;
}

export function diffView(d) {
  gitStyles();
  if (d.binary) return h("p", { class: "muted" }, "This file isn't text (a picture or similar), so its change can't be shown line by line.");
  const lang = EXT_LANG(d.file);
  return h("div", {},
    h("h4", { class: "mono" }, d.file),
    d.too_big ? h("p", { class: "muted small" }, "This change is very long: only the start is shown.") : null,
    h("div", { class: "gl-lines mono", role: "table", "aria-label": t("What changed in {file}", { file: d.file }) },
      d.lines.map((l) => l.kind === "hunk"
        ? h("div", { class: "gl-hunk", role: "row" }, h("span", { class: "muted" }, l.text))
        : h("div", { class: "gl-line gl-" + l.kind, role: "row" },
          h("span", { class: "gl-no", "aria-hidden": "true" }, l.kind === "add" ? "" : l.old ?? ""),
          h("span", { class: "gl-no", "aria-hidden": "true" }, l.kind === "del" ? "" : l.new ?? ""),
          h("span", { class: "gl-sign", title: l.kind === "add" ? "Added" : l.kind === "del" ? "Taken out" : "" }, l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "),
          h("span", { class: "gl-text" }, highlight(l.text, lang))))));
}

export function gitStyles() {
  if (typeof document === "undefined" || document.getElementById("gl-style")) return;
  document.head.append(h("style", { id: "gl-style" }, `
.gl { display: flex; flex-direction: column; gap: 10px; }
.gl-head { gap: 8px; align-items: center; flex-wrap: wrap; }
.gl-list { min-width: 0; }
.gl-commits { list-style: none; margin: 0; padding: 0; max-height: 62vh; overflow: auto; }
.gl-row { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: start; background: none; border: 0; border-radius: var(--radius-small); padding: 6px 8px; color: var(--color-text); }
.gl-row:hover, .gl-row[aria-current="true"] { background: var(--color-raised); }
.gl-subject { overflow-wrap: anywhere; }
.gl-detail { min-width: 0; }
.gl-files { list-style: none; margin: 6px 0; padding: 0; display: flex; flex-direction: column; gap: 2px; max-height: 30vh; overflow: auto; }
.gl-file { display: flex; gap: 8px; width: 100%; text-align: start; background: none; border: 0; padding: 4px 6px; border-radius: var(--radius-small); color: var(--color-text); }
.gl-file:hover { background: var(--color-raised); }
.gl-add { color: var(--color-good); }
.gl-del { color: var(--color-bad); }
.gl-lines { font-size: 12px; max-height: 60vh; overflow: auto; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); }
.gl-line { display: grid; grid-template-columns: 3.5em 3.5em 1.5em 1fr; white-space: pre; }
.gl-no { color: var(--color-muted); text-align: end; padding-inline-end: 6px; user-select: none; }
.gl-add.gl-line, .gl-line.gl-add { background: var(--color-good-soft); color: var(--color-text); }
.gl-line.gl-del { background: var(--color-bad-soft); color: var(--color-text); }
.gl-hunk { background: var(--color-accent-soft); padding: 2px 8px; }
.gl-text { padding-inline-end: 8px; }
`));
}
