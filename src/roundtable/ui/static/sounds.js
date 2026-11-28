// Sound and music (wave 9; ui/soundapi.py). Two cards:
//   soundServiceCard()  Settings → Services → "Sound and music": pick the service (ElevenLabs or Stable Audio),
//                       each with its price, licence line and what $2 buys; the key through the existing key form;
//                       Test (priced first).
//   soundsCard(path)    a project's sounds: one line ("$0.42 of $2 used"), each sound with Play, who made it and
//                       what it cost behind More, Make it again (priced first, inside the cap).
// Short first, details behind More. Nothing shows on an older PC that hasn't the routes.
import { h, fill, get, post, has, act, dialog, q } from "./core.js";
import { t } from "./words.js";

const STYLE = `
.snd-cards { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); margin: 6px 0; }
.snd-svc { border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-surface);
  padding: 10px 12px; text-align: start; }
.snd-svc.on { border-color: var(--color-accent); }
.snd-svc h3 { margin: 0 0 4px; font-family: var(--font-display); font-size: 15px; color: var(--color-text); }
.snd-svc p { margin: 3px 0; }
.snd-acts { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0 2px; }
.snd-list { display: grid; gap: 6px; margin: 6px 0; }
.snd-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 6px 10px; border: 1px solid var(--color-line);
  border-radius: var(--radius-small); background: var(--color-surface); }
.snd-row .grow { flex: 1 1 160px; min-width: 0; }
.snd-row audio { inline-size: 220px; max-inline-size: 100%; }
.snd-more { margin-top: 6px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); padding: 4px 10px; }
.snd-more > summary { cursor: pointer; padding: 2px 0; }
`;
let styled = false;
const style = () => { if (!styled && typeof document !== "undefined") { document.head.append(h("style", { id: "snd-style" }, STYLE)); styled = true; } };
const dollars = (x) => `$${Number(x || 0).toFixed(2)}`;
const cap = (x) => (Number.isInteger(Number(x)) ? `$${Number(x)}` : dollars(x));

// -- Settings → Services → Sound and music ---------------------------------------------------------------------
export function soundServiceCard() {
  style();
  const box = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { title: "Which service makes your games' sound effects and music. Each sound is priced before it's made." }, t("Sound and music"))));
  const body = h("div", {}, h("p", { class: "muted small" }, t("Looking…")));
  box.append(body);
  const load = async () => {
    if (!(await has("/api/sounds/service"))) { box.remove(); return; }
    try { fill(body, ...serviceParts(await get("/api/sounds/service"), load)); }
    catch (e) { fill(body, h("p", { class: "muted" }, t("Couldn't read the sound settings. Open this page again to retry."))); }
  };
  load();
  return box;
}

function serviceParts(v, reload) {
  const picked = (v.cards || []).find((c) => c.id === v.service);
  const head = picked
    ? h("p", {}, t("{name} makes your sounds. A project spends at most {cap} on sound.", { name: picked.name, cap: cap(v.owner_cap) }))
    : h("p", {}, t("No service picked: sounds are made in code."));
  const cards = h("div", { class: "snd-cards" }, (v.cards || []).map((c) => serviceCard(c, c.id === v.service, reload)));
  const off = picked ? h("button", { class: "btn small", title: t("New sounds are made in code; bought ones stay") }, t("Stop buying sounds")) : null;
  if (off) off.addEventListener("click", () => choose("", off, reload));
  return [head, cards, off ? h("div", { class: "snd-acts" }, off) : null];
}

function serviceCard(c, on, reload) {
  const pick = h("button", { class: on ? "btn small" : "btn", disabled: on, title: t("Use {name} for game sounds", { name: c.name }) },
    on ? t("Chosen") : t("Choose"));
  pick.addEventListener("click", () => choose(c.id, pick, reload));
  const key = c.has_key ? h("span", { class: "pill good", title: t("The key is saved") }, t("key saved"))
    : h("a", { class: "pill warn", href: "#/settings/keys", title: t("Add its key under Keys") }, t("no key yet"));
  const test = h("button", { class: "btn small", title: t("Make one 1-second sound to check the key works. Priced first.") }, t("Test"));
  test.addEventListener("click", () => tryIt(c, test));
  const more = h("details", { class: "snd-more" }, h("summary", { title: t("What it costs and what you may do with what it makes") }, t("More")),
    h("p", { class: "small" }, c.price), h("p", { class: "small" }, c.licence));
  return h("div", { class: "snd-svc" + (on ? " on" : "") },
    h("h3", {}, c.name), h("p", { class: "small" }, c.buys), more,
    h("div", { class: "snd-acts" }, pick, key, on && c.has_key ? test : null));
}

async function choose(id, btn, reload) {
  await act(btn, async () => {
    const ask = await post("/api/sounds/service", { service: id });
    if (ask && ask.confirm && !(await dialog({ title: t("Sound and music"), text: ask.question, yes: id ? t("Yes, use it") : t("Stop buying") }))) return;
    await post("/api/sounds/service", { service: id, confirm: true });
    await reload();
  });
}

async function tryIt(c, btn) {
  await act(btn, async () => {
    const ask = await post("/api/sounds/test", { service: c.id });
    if (ask && ask.confirm && !(await dialog({ title: t("Test {name}", { name: c.name }), text: ask.question, yes: t("Make it") }))) return;
    const r = await post("/api/sounds/test", { service: c.id, confirm: true });
    if (!r.ok) throw new Error(t("The test didn't work: {why}", { why: r.why || t("no sound came back") }));
    const player = h("audio", { controls: true, src: r.audio, class: "pv-audio" });
    await dialog({ title: t("It works"), text: t("{name} made a test sound for {usd}.", { name: c.name, usd: dollars(r.usd) }), body: player, yes: t("Done"), no: null });
  });
}

// -- a project's sounds ------------------------------------------------------------------------------------------
export function soundsCard(path) {
  style();
  const box = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { title: t("The sound effects and music for this project: bought ones and ones made in code") }, t("Sounds"))));
  const body = h("div", {}, h("p", { class: "muted small" }, t("Looking…")));
  box.append(body);
  const load = async () => {
    if (!(await has("/api/sounds"))) { box.remove(); return; }
    try {
      const v = await get(`/api/sounds?${q({ path })}`);
      if (!v.sounds.length && !v.service) { box.remove(); return; }
      fill(body, ...soundParts(path, v, load));
    } catch (e) { fill(body, h("p", { class: "muted" }, t("Couldn't read this project's sounds. Open it again to retry."))); }
  };
  load();
  return box;
}

function soundParts(path, v, reload) {
  const rows = (v.sounds || []).map((s) => soundRow(path, s, reload));
  const more = h("details", { class: "snd-more" }, h("summary", { title: t("This project's sound money and its settings") }, t("More")),
    h("p", { class: "small" }, t("Spent {spent} of {cap} (your figure for every project: {top}).", { spent: dollars(v.spent), cap: cap(v.cap), top: cap(v.owner_cap) })),
    projectActs(path, v, reload));
  return [h("p", {}, v.words), rows.length ? h("div", { class: "snd-list" }, rows) : null, more];
}

function soundRow(path, s, reload) {
  const src = s.file ? "/raw/pfile?" + q({ path, file: s.file }) : "";
  const who = s.made === "bought"
    ? t("Made by {service} for {usd}", { service: s.service || t("a sound service"), usd: dollars(s.usd) })
    : t("Made in code");
  const again = h("button", { class: "btn small", title: t("Make this sound again with the sound service. Priced first, inside this project's sound money.") }, t("Make it again"));
  again.addEventListener("click", () => remake(path, s, again, reload));
  const more = h("details", { class: "snd-more" }, h("summary", { title: t("Where it came from, the licence and the words it was made from") }, t("More")),
    h("p", { class: "small" }, who + (s.seconds ? t(", about {n} seconds", { n: Number(s.seconds) }) : "") + "."),
    s.why ? h("p", { class: "small" }, t("Why in code: {why}", { why: s.why })) : null,
    s.licence && s.licence.words ? h("p", { class: "small" }, t("Licence (read {day}): {words}", { day: s.licence.read_on || "", words: s.licence.words })) : null,
    s.prompt ? h("p", { class: "small muted" }, s.prompt) : null);
  return h("div", { class: "snd-row" },
    h("div", { class: "grow" }, h("div", {}, s.title || s.task), h("span", { class: "muted small" }, who)),
    src ? h("audio", { controls: true, preload: "none", src, title: s.title || s.file, class: "pv-audio" }) : null,
    again, more);
}

async function remake(path, s, btn, reload) {
  await act(btn, async () => {
    const ask = await post("/api/sounds/again", { path, task: s.task });
    if (ask && ask.confirm && !(await dialog({ title: t("Make it again"), text: ask.question, yes: t("Make it") }))) return;
    await post("/api/sounds/again", { path, task: s.task, confirm: true });
    await reload();
  }, t("Made again."));
}

function projectActs(path, v, reload) {
  const money = h("button", { class: "btn small", title: t("How much this project may spend on sound, at most your own figure") }, t("Change the sound money"));
  money.addEventListener("click", async () => {
    const got = await dialog({ title: t("Sound money for this project"), text: t("At most {top}.", { top: cap(v.owner_cap) }),
      yes: t("Save"), input: { label: t("Dollars"), placeholder: String(v.owner_cap), value: String(v.cap) } });
    if (got === null || got === false) return;
    await act(money, () => post("/api/sounds/project", { path, max_usd: Number(String(got).replace(/[^0-9.]/g, "")) || 0 }), t("Saved."), reload);
  });
  const mine = h("label", { class: "small", title: t("A game only you will play: sound services whose free plan doesn't allow selling may be used") },
    h("input", { type: "checkbox", checked: !!v.just_for_me }), " ", t("Just for me (not for sale)"));
  mine.querySelector("input").addEventListener("change", (e) =>
    act(null, () => post("/api/sounds/project", { path, just_for_me: e.target.checked }), t("Saved."), reload));
  return h("div", { class: "snd-acts" }, money, mine);
}
