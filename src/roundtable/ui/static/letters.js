// Letters became the chat in 1.5.0 (chat.js). This file only sends old addresses on: #/letters and #/messages open
// the Hall's chat, #/letters/<project> that project's chat. letterRow stays for Needs you until it shows "wrote to
// you" cards (chat.js wroteCard); the coordinator deletes this file once nothing imports it.
import { get } from "./core.js";
import { HALL, chatHref, chatIdOf, viewChat, wroteCard } from "./chat.js";

/** Where an old letters address goes: the project's chat when there is one, else the Hall's. */
export async function chatForLetters(agent) {
  if (!agent) return HALL;
  const id = chatIdOf(agent);
  try {
    const chats = (await get("/api/chats")).chats || [];
    const hit = chats.find((c) => c.id === id || c.id === agent || String(c.name || "").toLowerCase() === String(agent).toLowerCase());
    return hit ? hit.id : HALL;
  } catch { return HALL; }
}

export async function viewLetters(asAgent) {
  const id = await chatForLetters(asAgent ? decodeURIComponent(asAgent) : "");
  history.replaceState(null, "", chatHref(id));
  return viewChat(id);
}

/** A letter in Needs you, as one line that opens the chat it now belongs to. */
export function letterRow(m) {
  return wroteCard({ project: m.sender, text: m.subject && !/^roundtable:/i.test(m.subject) ? m.subject : "" });
}

