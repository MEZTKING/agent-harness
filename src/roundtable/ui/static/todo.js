// A to-do's own button (wave 9): the owner never leaves the app. The server picks what the button does
// (todoactions.py); this only shows it, asks "Are you sure?" where the server says so, and opens in-app pages.
//   todoButton(need, done)  -> a button, or null when the to-do has only Done
//   backupsBrowse(input)    -> a Browse button that fills a folder box from the desktop window's own dialog
import { h, post, toast, dialog } from "./core.js";
import { t } from "./words.js";

export function todoButton(n, done) {
  const a = n && n.action;
  if (!a) return null;
  const go = async (btn) => {
    if (a.route.startsWith("#/")) { location.hash = a.route; return; }
    btn.disabled = true;
    try {
      let r = await post("/api/todo/act", { agent: n.agent || n.project, id: n.id });
      if (r && r.open) { location.hash = r.open; return; }
      if (r && r.confirm) {
        const yes = await dialog({ title: t(a.label), text: r.confirm, yes: t(a.label) });
        if (!yes) return;
        r = await post("/api/todo/act", { agent: n.agent || n.project, id: n.id, confirm: true });
      }
      if (r) toast(r.reply || t("Done."), r.ok === false);
      if (done) await done(r);
    } catch (e) { toast(e.message, true); }
    finally { if (btn.isConnected) btn.disabled = false; }
  };
  return h("button", { class: "primary", title: a.tip || a.label, onclick: (ev) => go(ev.currentTarget) }, a.label);
}

// The backups folder: Browse opens the desktop window's folder dialog; in a browser it says to type it instead.
export function backupsBrowse(input) {
  return h("button", { type: "button", title: "Choose the folder with your computer's own folder window",
    onclick: async (ev) => {
      const btn = ev.currentTarget; btn.disabled = true;
      try {
        const r = await post("/api/backup/browse", { start: input.value || "" });
        if (r && r.folder) { input.value = r.folder; input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); }
      } catch (e) { toast(e.message, true); }
      finally { if (btn.isConnected) btn.disabled = false; }
    } }, "Browse…");
}
