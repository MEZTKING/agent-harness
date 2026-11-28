// A running app's frame, view only (ui/appframeapi.py): the page the App tab's Start runs on the PC, relayed as
// one piece of HTML with a strict content policy. Shown in a sandboxed frame where nothing of the app runs (a
// frame written from this page keeps this page's own policy, so its scripts are blocked: a still view, honest
// about it); a tap on a link is caught here and asks the relay for that page. Nothing is ever sent to the app.
import { h, fill, get, q } from "./core.js";

export function appFrame(path) {
  const words = h("p", { class: "small muted", "aria-live": "polite" }, "Looking at the app on the PC…");
  const frame = h("iframe", { class: "app-frame", sandbox: "allow-same-origin", referrerpolicy: "no-referrer", title: "Your app, as it runs on the PC" });
  const back = h("button", { class: "small", type: "button", disabled: true, onclick: () => { history.pop(); load(history.pop() || "/"); } }, "Back");
  const again = h("button", { class: "small", type: "button", title: "Look at the page again", onclick: () => load(current, false) }, "Refresh");
  const history = [];
  let current = "/";
  const load = async (page, remember = true) => {
    fill(words, "Looking at the app on the PC…");
    let r;
    try { r = await get(`/api/app/frame?${q({ path, page })}`); } catch (e) { fill(words, e.message); frame.removeAttribute("srcdoc"); return; }
    current = r.page;
    if (remember) history.push(r.page);
    back.disabled = history.length < 2;
    fill(words, r.title ? `${r.title} · ${r.words}` : r.words);
    if (r.html) frame.srcdoc = r.html; else frame.removeAttribute("srcdoc");
  };
  // no script runs in the frame, so its links are caught from here (the relay marked them data-relay)
  frame.addEventListener("load", () => {
    const doc = frame.contentDocument;
    if (!doc) return;
    doc.addEventListener("click", (ev) => {
      const a = ev.target.closest && ev.target.closest("[data-relay]");
      if (!a) return;
      ev.preventDefault();
      const to = a.getAttribute("data-relay") || "";
      if (to.startsWith("/") && !to.startsWith("//")) load(to);
    }, true);
  });
  const onMessage = (ev) => {  // a frame shown where scripts may run (the Android app's view) asks this way
    if (!frame.isConnected) { window.removeEventListener("message", onMessage); return; }
    if (ev.source !== frame.contentWindow || !ev.data || typeof ev.data.relay !== "string") return;
    if (ev.data.relay.startsWith("/") && !ev.data.relay.startsWith("//")) load(ev.data.relay);
  };
  window.addEventListener("message", onMessage);
  load("/");
  return h("div", { class: "stack" }, h("div", { class: "row" }, back, again), words, frame);
}
