// Home: the Ring. Every project is a light on a thin ring of light (the art is ring.webp over eclipse.webp; this file only
// places the lights and their cards). A project that is building pulses slowly; the one that needs you flares ember-orange
// and moves to the top of the ring. Past ten projects, or in a narrow window, the ring shrinks into the heading and the
// projects sit in a grid. Beside it the first thing that needs you, answered on the card.
import { h, get, S, onHall, patch, projectHref, money, ago, plural, every, dot, empty, needsCount, BRAND } from "./core.js";
import { gather, needCard } from "./needs.js";
import { whereWords, builtBy, machinesStrip, loadMachines } from "./machines.js";
import { feedLine } from "./activity.js";
import { loadStates, stateWord, orderSeats, orderButtons } from "./board.js";
import { t } from "./words.js";
import { chatView } from "./chat.js";

const RING_MAX = 10;   // lights on the ring; more and the ring becomes a heading over a grid

// the art is optional: the ring's chrome stands in until ring.webp (and the wordmark) are there
const ART = { ring: null, wordmark: null };
function probe(key, src) {
  if (ART[key] !== null) return Promise.resolve(ART[key]);
  return new Promise((done) => { const i = new Image(); i.onload = () => done(ART[key] = true); i.onerror = () => done(ART[key] = false); i.src = src; });
}

const needsYou = (s) => s.status === "waiting" || (s.waiting_for_you || 0) > 0;

function ringCard(s, shown = [], redraw = null) {
  const p = s.progress || { done: 0, total: 0 };
  const waiting = s.waiting_for_you || 0;
  const lit = needsYou(s);
  const by = builtBy(s);
  const state = by || s.state || "";
  const tip = [s.name, state, s.goal ? `Goal: ${s.goal}` : "", whereWords(s), s.last_activity ? `Last news ${ago(s.last_activity)}` : ""].filter(Boolean).join("\n");
  return h("a", { class: `ring-card ${s.status}${lit ? " lit" : ""}`, href: projectHref(s.id), title: tip, "data-project": s.id },
    s.shot ? h("img", { class: "ring-card-shot", src: s.shot.url, alt: "", loading: "lazy" }) : null,
    h("span", { class: "ring-card-name" }, dot(s.id), h("b", {}, s.name)),
    h("span", { class: "ring-card-state" }, h("i", { class: "sdot", "aria-hidden": "true" }), state, " ", stateWord(s)),
    p.total ? h("span", { class: "bar", title: t("{done} of {total} tasks done", { done: p.done, total: p.total }) },
      h("i", { style: `width:${(100 * p.done) / p.total}%` }), s.status === "running" && p.done < p.total ? h("i", { class: "run", style: `width:${100 / p.total}%` }) : null,
      s.failed_task ? h("i", { class: "fail", style: `width:${100 / p.total}%` }) : null) : null,
    h("span", { class: "ring-card-foot" },
      waiting ? h("span", { class: "waits" }, t("{waiting} for you", { waiting })) : h("span", { class: "muted" }, p.total ? t("{v1}% done", { v1: Math.round((100 * p.done) / p.total) }) : s.where === "here" ? "This computer" : ""),
      s.spent_usd ? h("b", { title: "Spent on this project so far" }, money(s.spent_usd)) : null,
      shown.length > 1 ? orderButtons(s, shown, redraw) : null));
}

function ringLight(s) {  // the project's point of light on the ring; its state is also in words on its card
  return h("i", { class: `ring-light ${s.status}${needsYou(s) ? " lit" : ""}`, "aria-hidden": "true" });
}

function placeRing(ring) {  // lights on the ring, cards outside it at the same angle; the first (the one that needs you) at the top
  const cards = [...ring.querySelectorAll(":scope > .ring-card")];
  const lights = [...ring.querySelectorAll(":scope > .ring-light")];
  if (!cards.length) return;
  const H = Math.min(860, Math.max(600, 74 * cards.length));
  ring.style.height = `${H}px`;  // room for every card, taller as the ring fills
  const half = Math.round(H * 0.25);  // the ring's radius: a quarter of the height, or 22% of the width if that is less
  ring.style.setProperty("--disc", `min(44cqw, ${2 * half}px)`);
  cards.forEach((el, i) => {
    const a = (2 * Math.PI * i) / cards.length - Math.PI / 2;
    const [c, s] = [Math.cos(a).toFixed(4), Math.sin(a).toFixed(4)];
    el.style.insetInlineStart = `calc(50% + (50% - 118px) * ${c})`;  // cards stay inside the stage: half a card plus a margin from each edge
    el.style.top = `calc(50% + (50% - 74px) * ${s})`;
    const l = lights[i];
    if (l) { l.style.insetInlineStart = `calc(50% + min(22cqw, ${half}px) * ${c})`; l.style.top = `calc(50% + min(22cqw, ${half}px) * ${s})`; }
  });
}

function ringWords(seats, waiting, small) {  // the middle of the ring: the wordmark (art) or the name, and one sentence
  const line = seats.length ? `${plural(seats.length, "project")}${waiting ? ` · ${waiting} need${waiting === 1 ? "s" : ""} you` : " · nothing needs you"}` : "No projects yet";
  return h("div", { class: "ring-words" },
    // the wordmark is pale art made for the dark themes; Ash (light) shows the typed name instead
    ...(ART.wordmark ? [h("img", { src: "wordmark.webp", alt: BRAND.name }), h("b", { class: "wordmark-typed", "aria-hidden": "true" }, small ? "Home" : BRAND.name)]
      : [h("b", {}, small ? "Home" : BRAND.name)]),
    h("span", {}, line));
}

export async function viewHall() {
  const table = h("div", { class: "home-stage" });
  const side = h("aside", { class: "home-side", "aria-label": "Needs you" });
  const notes = h("div", { class: "home-under" });
  const now = h("section", { class: "card home-now" });
  // Ring or Office: the switch shows only once the office has its pictures (office.js); otherwise the Ring stays
  const office = await import("./office.js");
  const sw = await office.officeSwitch(() => { table._sig = undefined; table._office = false; draw(S.rt); }).catch(() => null);
  const root = h("div", { class: "page home" },
    h("div", { class: "home-main" }, sw, table, notes, now, chatView("hall", { short: true, name: BRAND.short })), side);
  const newIdea = () => h("a", { class: "ring-card new-idea", href: "#/new", title: "A few taps, then the planner makes a plan for you to check. Nothing is built until you approve it." },
    h("i", { class: "unlit", "aria-hidden": "true" }), h("b", {}, "+ New idea"), h("span", {}, "Start a project"));

  let wide = true;
  const ro = new ResizeObserver(() => { const w = table.clientWidth > 760; if (w !== wide) { wide = w; table._sig = undefined; draw(S.rt); } });
  ro.observe(table);

  async function draw(rt) {
    if (!rt) return;
    await Promise.all([loadMachines(), probe("ring", "ring.webp"), probe("wordmark", "wordmark.webp")]);
    const states = await loadStates();  // working, resting, gone quiet, and the owner's order (board.js)
    const seats = orderSeats(rt.seats, needsYou);  // what needs you goes to the top of the ring, then the owner's order
    const redraw = () => { table._sig = undefined; draw(S.rt); };
    const card_ = (s) => ringCard(s, seats, redraw);
    const waiting = seats.filter(needsYou).length;
    const ring = seats.length <= RING_MAX && wide;
    if (sw && office.homeView() === "office") {  // the office follows the Hall by itself once drawn
      if (!table._office) { table._office = true; table._sig = undefined; await office.officeView(table); }
    } else patch(table, JSON.stringify([ring, ART, seats.map((s) => [s.id, s.name, s.state, s.status, s.progress, s.waiting_for_you, s.spent_usd, s.shot && s.shot.url, builtBy(s), s.where]), states]), () => {
      const disc = (small) => h("div", { class: "ring-disc" }, ringWords(seats, waiting, small));
      const art = ART.ring ? " art" : "";
      if (!seats.length) return [h("div", { class: `ring empty-ring${art}` }, disc(false)), empty("No projects yet. Write your first idea and the planner makes a plan for you to check.",
        h("a", { class: "btn primary", href: "#/new" }, "+ New idea"))];
      if (ring) {
        const r = h("div", { class: `ring${art}`, role: "group", "aria-label": "Your projects" }, disc(false), seats.map(ringLight), seats.map(card_), newIdea());
        setTimeout(() => placeRing(r), 0);
        return r;
      }
      return [h("div", { class: `ring ring-band${art}` }, h("div", { class: "ring-disc", "aria-hidden": "true" }), ringWords(seats, waiting, true)), h("div", { class: "rows", role: "list", "aria-label": "Your projects" }, seats.map(card_), newIdea())];
    });
    table.querySelectorAll(".ring:not(.ring-band):not(.empty-ring)").forEach((r) => placeRing(r));

    // beside the ring: the first thing that needs you, answered here
    const items = await gather(rt, false);
    items.sort((a, b) => a.rank - b.rank);
    patch(side, JSON.stringify(items.map((i) => [i.project, i.kind, i.ask && [i.ask.id, i.ask.stamp], i.need && [i.need.text, i.need.id]])), () => {
      if (!items.length) return h("section", { class: "card calm" }, h("h2", {}, "Nothing needs you"),
        h("p", { class: "muted" }, "Every project is either working or waiting for a new idea. Questions, plans to approve and your to-dos show up here."),
        h("a", { class: "btn primary", href: "#/new" }, "+ Start a new project"));
      const [first, ...rest] = items;
      return [h("div", { class: "side-head" }, h("h2", {}, "Needs you"), h("span", { class: "count", title: "Every card waiting, chat messages not counted" }, needsCount(rt) || items.length),
        h("a", { class: "spacer-left", href: "#/needs" }, "See all")),
      needCard(first, null, { compact: true }),
      rest.length ? h("section", { class: "card next-up" }, h("h3", { class: "label" }, "Also waiting"),
        h("ul", { class: "plain" }, rest.slice(0, 8).map((i) => h("li", {}, h("a", { href: `#/needs` }, dot(i.project), h("b", {}, i.name || i.need?.name || S.rt.seats.find((s) => s.id === i.project)?.name || i.project),
          " · ", i.ask ? i.ask.question : i.need ? i.need.text : "")))),
        rest.length > 8 ? h("a", { href: "#/needs" }, t("and {v1} more", { v1: rest.length - 8 })) : null) : null];
    });

    // under the ring: my notes, the computers, the models' health, the hub's sync
    patch(notes, JSON.stringify([rt.notes && [rt.notes.open_todos, rt.notes.unread], rt.health, rt.sync_error, rt.synced_at && ago(rt.synced_at), S.offline]), () => {
      const n = rt.notes;
      const bad = (rt.health || []).filter((x) => x.state === "bad").length, off = (rt.health || []).filter((x) => x.state === "warn").length;
      return [
        n ? h("a", { class: "chip-link", href: projectHref(n.id), title: "Your own notes, to-dos and plans that don't belong to one project" },
          "My notes", n.open_todos ? h("small", {}, t("{open_todos} to do", { open_todos: n.open_todos })) : null, n.unread ? h("small", {}, t("{unread} unread", { unread: n.unread })) : null) : null,
        h("a", { class: "chip-link", href: "#/models/health", title: (rt.health || []).map((x) => `${x.model}: ${x.passed} of ${x.total} checks`).join("\n") || "The models haven't been checked yet" },
          h("i", { class: "hdot " + (bad ? "bad" : off ? "warn" : rt.health && rt.health.length ? "ok" : "") }),
          !(rt.health || []).length ? "Models not checked yet" : bad ? t("{v1} not answering", { v1: plural(bad, "model") }) : off ? t("{v1} a little off", { v1: plural(off, "model") }) : "Models healthy"),
        h("span", { class: "chip-link quiet", title: rt.sync_error || "Projects on other computers report through the hub" },
          h("i", { class: "hdot " + (S.offline ? "bad" : rt.sync_error ? "warn" : "ok") }),
          S.offline ? "The app isn't answering" : rt.sync_error ? "Hub sync has a problem" : rt.synced_at ? t("Hub synced {v1}", { v1: ago(rt.synced_at) }) : "Up to date"),
        machinesStrip()];
    });
  }
  onHall(root, draw);

  // what's happening now: the newest steps across every project
  every(now, async () => {
    const feed = await get("/api/activity?limit=7");
    patch(now, JSON.stringify(feed.map((f) => [f.at, f.text])), () => [
      h("div", { class: "card-head" }, h("h2", {}, "Happening now"), h("a", { href: "#/activity" }, "All activity")),
      feed.length ? h("ul", { class: "feed compact" }, feed.map((f) => feedLine(f))) : h("p", { class: "muted" }, "Nothing has happened yet. Start a project and its steps show up here.")]);
  }, 8000);
  return root;
}
