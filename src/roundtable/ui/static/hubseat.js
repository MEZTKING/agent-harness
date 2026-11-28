// A hub project's seat (wave 9): whether anything is listening where it lives, and Approve sent only once.
//   listeningLine(seat) -> one short line ("Your PC last listened 4 minutes ago.") or null for a seat here
//   approveOnce(seat)   -> sends Approve through the hub once and says whether anything will pick it up
import { h, post, toast } from "./core.js";

export function listeningLine(seat) {
  const l = seat && seat.where === "elsewhere" ? seat.listening : null;
  if (!l) return null;
  return h("p", { class: "small" + (l.stale ? " warn" : " muted"),
    title: "Commands sent from here are done when the app is open on the computer that builds it" }, l.words);
}

export async function approveOnce(seat, action = "approve") {
  try {
    const r = await post("/api/hub/send-once", { agent: seat.hub_agent || seat.id, folder: seat.id, action });
    toast(r.reply, !r.sent && !/^Already/.test(r.reply));
    return r;
  } catch (e) { toast(e.message, true); return null; }
}
