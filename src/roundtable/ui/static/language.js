// Settings → Language (languageCard) and "Read in <language>" under what models write (readIn). Wave 9.
// The words of these two pieces pass through the table like every other page's (h and fill call words.auto);
// sentences with values use t(). Choosing a language reloads the page so every room is drawn in it at once.
import { h, fill, get, post, act, has, dialog, money } from "./core.js";
import * as words from "./words.js";
import { t } from "./words.js";

const TIP_LABEL = "A model made this translation, not a person. If a word reads wrong, change it here and your wording is kept.";

/** The Settings card: the language, the label for a model's translation, fixing a word, adding a language and
 *  the switch for reasons translated by themselves. */
export function languageCard() {
  const box = h("section", { class: "card lang-card" },
    h("div", { class: "card-head" }, h("h2", { title: "The language the app is written in" }, "Language")));
  const body = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  box.append(body);
  const load = async () => {
    if (!(await has("/api/words"))) { box.remove(); return; }
    try { fill(body, ...parts(await get("/api/words"), load)); }
    catch { fill(body, h("p", { class: "muted" }, "Couldn't read the languages. Open this page again to try again.")); }
  };
  load();
  return box;
}

function parts(v, reload) {
  const pick = h("select", { "aria-label": "Language", title: "The language the app is written in",
    onchange: (ev) => act(ev.currentTarget, () => post("/api/words/language", { lang: ev.target.value }), null, () => location.reload()) },
  v.langs.map((l) => h("option", { raw: true, value: l.code, selected: l.code === v.lang ? true : null },
    l.own_name === l.name ? l.name : `${l.own_name} – ${l.name}`)));
  const out = [h("div", { class: "row" }, pick)];
  if (v.label) out.push(h("p", { class: "muted small", title: TIP_LABEL }, v.label));
  const more = h("details", { class: "fold" }, h("summary", { title: "Fix a word, add a language, translate reasons by themselves" }, "More"));
  if (v.lang !== "en-GB") more.append(fixPart(v, reload));
  more.append(addPart(), autoPart(v, reload));
  out.push(more);
  return out;
}

function fixPart(v, reload) {
  const from = h("input", { class: "grow", placeholder: "The English, as the app shows it", "aria-label": "The English sentence" });
  const to = h("input", { class: "grow", placeholder: "Your wording", "aria-label": "Your wording" });
  from.addEventListener("change", () => { const was = v.table[from.value.trim()]; if (typeof was === "string") to.value = was; });
  return h("div", { class: "lang-part" },
    h("h3", {}, "Fix a word"),
    h("p", { class: "muted small" }, v.fixes ? t("{n} of your own fixes are kept.", { n: v.fixes }) : "Your fixes are kept and win over the model's."),
    h("div", { class: "row" }, from), h("div", { class: "row" }, to),
    h("div", { class: "row" }, h("button", { class: "small", type: "button", title: "Leave your wording empty to put the model's back",
      onclick: (ev) => act(ev.currentTarget, () => post("/api/words/fix", { english: from.value.trim(), text: to.value }), "Kept. It shows next time the page opens.", reload) }, "Keep my wording")));
}

function addPart() {
  const name = h("input", { class: "grow", placeholder: "Welsh, Italian…", "aria-label": "The language to add" });
  const said = h("p", { class: "muted small", "aria-live": "polite" });
  const go = async (btn) => {
    const asked = await act(btn, () => post("/api/words/add", { name: name.value.trim() }));
    if (!asked) return;
    const yes = await dialog({ title: "Add a language", text: `${asked.words}\n${t("A model translates it; some words may be off.")}`, yes: "Translate it" });
    if (!yes) return;
    const r = await act(btn, () => post("/api/words/add", { name: name.value.trim(), confirm: true }), "Translating. It's in Activity → Background work.");
    if (r) fill(said, t("Translating into {name}. Choose it here once it's done.", { name: name.value.trim() }));
  };
  return h("div", { class: "lang-part" }, h("h3", {}, "Add a language"),
    h("p", { class: "muted small" }, "The price is shown first. Nothing is spent until you say yes."),
    h("div", { class: "row" }, name, h("button", { class: "small", type: "button", onclick: (ev) => go(ev.currentTarget) }, "See the price")), said);
}

function autoPart(v, reload) {
  return h("div", { class: "lang-part" }, h("h3", {}, "Reasons, translated by themselves"),
    h("label", { class: "check", title: "A card's reason is translated as it arrives, up to a small amount a day. Off: tap Read in your language instead." },
      h("input", { type: "checkbox", checked: v.auto_reasons, onchange: (ev) => act(null, () => post("/api/words/settings", { auto_reasons: ev.target.checked }), null, reload) }),
      "Always translate cards' reasons"),
    h("p", { class: "muted small" }, t("Up to {usd} a day; {spent} spent today.", { usd: money(v.allowance_usd), spent: money(v.spent_today || 0) })));
}

/** "Read in <language>" under a task's thinking, a card's reason, a review or the stand-up line: the price
 *  first, then the translation in place (kept, so reading it again is free). Nothing shows in British English. */
export function readIn(node, text, why, path) {
  const info = words.info();
  if (!node || !text || words.lang() === "en-GB" || !info) return node;
  const name = ((info.langs || []).find((l) => l.code === info.lang) || {}).own_name || info.lang;
  const out = h("div", { class: "read-in", "aria-live": "polite" });
  const link = h("button", { class: "linkish small read-in-link", type: "button", title: "A model translates it; the price is shown first" },
    t("Read in {name}", { name }));
  link.addEventListener("click", async () => {
    const first = await act(link, () => post("/api/translate", { path, text, why }));
    if (!first) return;
    let got = first;
    if (!first.cached && !first.text) {
      if (!(await dialog({ title: t("Read in {name}", { name }), text: first.words, yes: "Translate it" }))) return;
      got = await act(link, () => post("/api/translate", { path, text, why, confirm: true }));
      if (!got) return;
    }
    link.remove();
    fill(out, h("p", { raw: true, class: "read-in-text", lang: info.lang, dir: info.dir }, got.text),
      h("p", { class: "muted small", title: TIP_LABEL }, got.cached ? "Read before; free." : "Translated by a model; some words may be off."));
  });
  node.append(link, out);
  return node;
}

