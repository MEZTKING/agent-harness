// The App tab's Start: an app that starts with a command (a server, a dev build) is started on this PC and
// shown in a frame. Only in the app's own window on this computer; the phone keeps getting pictures.
// (harness/appserver.py, ui/appapi.py)
import { h, fill, get, post, q, has, act } from "./core.js";

appStartStyles();

// The card for one project's App tab, or null when this copy has no App start or there's nothing to start.
export async function appStartCard(seat) {
  if (!seat || !seat.path || !(await has("/api/app"))) return null;
  let a;
  try { a = await get("/api/app?" + q({ path: seat.path })); } catch (e) { return null; }
  if (!a.command) return null;
  const box = h("section", { class: "card as" });
  let timer = null, sig = "";
  const show = (x) => {
    const s = JSON.stringify([x.state, x.url, x.error]);
    if (s === sig) return;
    sig = s;
    fill(box, ...body(seat, x, refresh));
  };
  const refresh = async () => {
    try { show(await get("/api/app?" + q({ path: seat.path }))); } catch (e) { /* the next look tries again */ }
  };
  show(a);
  // follow it while it starts and while it runs (each look keeps it from stopping as idle)
  timer = setInterval(() => { if (!box.isConnected) { clearInterval(timer); return; } refresh(); }, 4000);
  return box;
}

function body(seat, a, refresh) {
  const head = h("div", { class: "card-head" }, h("h2", {}, "Use it here"),
    h("span", { class: "as-state as-" + a.state, title: STATE_TIP[a.state] || "" }, STATE[a.state] || a.state));
  const words = h("p", { class: a.state === "failed" ? "as-bad" : "muted" }, a.words || "");
  const cmd = h("details", { class: "as-more" }, h("summary", { title: "The exact command the harness runs to start it" }, "More"),
    h("p", { class: "muted small" }, "Command: ", h("code", {}, a.command || ""),
      a.from === "kind" ? " (from this kind of project)" : " (from the app's package.json)"));
  const row = h("div", { class: "row" });
  if (a.state === "running" || a.state === "starting") {
    row.append(h("button", { title: "Ends the app and everything it started",
      onclick: (ev) => act(ev.currentTarget, () => post("/api/app/stop", { path: seat.path }), "Stopped", refresh) }, "Stop it"));
    if (a.url) row.append(h("a", { class: "button", href: a.url, target: "_blank", rel: "noopener", title: "Opens it in your own browser on this PC" }, "Open in browser"));
  } else {
    row.append(h("button", { class: "primary", title: "Starts the app on this PC with its own command (no AI, no cost). It stops by itself after 30 minutes nobody looks",
      onclick: (ev) => act(ev.currentTarget, () => post("/api/app/start", { path: seat.path }), "Starting it: give it a moment", refresh) },
      a.state === "failed" ? "Try again" : "Start it"));
  }
  const out = [head, words, row];
  if (a.state === "running" && a.url) {
    out.push(h("iframe", { class: "as-frame", src: a.url, title: "The app, running on this PC", sandbox: "allow-scripts allow-forms allow-same-origin allow-modals allow-popups" }));
  }
  out.push(cmd);
  return out;
}

const STATE = { off: "Not running", starting: "Starting…", running: "Running", failed: "Didn't start" };
const STATE_TIP = {
  off: "The app isn't running now",
  starting: "The harness has started its command and is waiting for it to answer",
  running: "The app is running on this PC; only this computer can open it",
  failed: "The command ended or didn't answer in time: the reason is below",
};

function appStartStyles() {
  if (typeof document === "undefined" || document.getElementById("as-style")) return;
  document.head.append(h("style", { id: "as-style" }, `
.as .card-head { display: flex; align-items: center; gap: 8px; }
.as-state { font-size: 12px; padding: 2px 8px; border-radius: var(--radius-small); background: var(--color-sunken); }
.as-running { color: var(--color-good); background: var(--color-good-soft); }
.as-starting { color: var(--color-warn); background: var(--color-warn-soft); }
.as-failed { color: var(--color-bad); background: var(--color-bad-soft); }
.as-bad { color: var(--color-bad); }
.as-frame { display: block; width: 100%; height: 520px; margin-top: 10px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-surface); }
.as-more > summary { cursor: pointer; font-size: 12px; color: var(--color-muted); }
.as-more code { font-family: var(--font-mono); }
`));
}
