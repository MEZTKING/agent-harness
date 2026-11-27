// CI shown (wave 8, p1-reach): one chip on a project – "Checks passing", "1 check failing: open" – with the
// details behind "More". The API: ui/reachapi.py (/api/ci?path=), read through the owner's GitHub key and kept
// for a minute.
import { h, fill, get, q, ago } from "./core.js";

const STYLE = `
.ci-chip { display: inline-flex; gap: 6px; align-items: center; }
.ci-runs { margin: 4px 0 0; padding-left: 18px; color: var(--color-muted); font-size: 12.5px; }
`;
let styled = false;
const PILL = { passing: "good", failing: "bad", running: "info", none: "", not_github: "", no_key: "warn", error: "warn" };

export function ciChip(path) {
  if (!styled) { document.head.append(h("style", {}, STYLE)); styled = true; }
  const box = h("span", { class: "ci-chip" });
  (async () => {
    let d;
    try { d = await get("/api/ci?" + q({ path })); } catch { return; }
    if (d.state === "not_github") return;  // nothing to show for a project that isn't on GitHub
    const pill = h("span", { class: `pill ${PILL[d.state] || ""}`, title: d.detail || `${d.repo} · ${d.branch}` }, d.words);
    const open = d.failing && d.failing.length ? h("a", { href: d.failing[0].url, target: "_blank", rel: "noopener", class: "small" }, "open") : null;
    const more = (d.runs || []).length ? h("details", {}, h("summary", { class: "small" }, "More"),
      h("ul", { class: "ci-runs" }, d.runs.map((r) => h("li", {}, h("a", { href: r.url, target: "_blank", rel: "noopener" }, r.name), ": ",
        r.status === "completed" ? (r.conclusion || "done") : "running", r.at ? ` · ${ago(r.at)}` : "", r.sha ? ` · ${r.sha}` : ""))),
      d.link ? h("a", { href: d.link, target: "_blank", rel: "noopener", class: "small" }, "All checks on GitHub") : null) : null;
    fill(box, pill, open, more);
  })();
  return box;
}
