// The Hall: every project as a seat at a carved round table; the seat that needs you lit by a candle. Beside it the
// first thing that needs you, answered on the card. More seats than fit around the table: they sit in rows below it.
import { h, get, S, onHall, patch, projectHref, money, ago, plural, every, dot, empty, needsCount } from "./core.js";
import { gather, needCard } from "./needs.js";
import { whereWords, builtBy, machinesStrip, loadMachines } from "./machines.js";
import { feedLine } from "./activity.js";

const RING_MAX = 10;   // seats around the table; more sit in rows

function seat(s) {
  const p = s.progress || { done: 0, total: 0 };
  const waiting = s.waiting_for_you || 0;
  const lit = s.status === "waiting" || waiting > 0;
  const by = builtBy(s);
  const state = by || s.state || "";
  const tip = [s.name, state, s.goal ? `Goal: ${s.goal}` : "", whereWords(s), s.last_activity ? `Last news ${ago(s.last_activity)}` : ""].filter(Boolean).join("\n");
  return h("a", { class: `seat ${s.status}${lit ? " lit" : ""}`, href: projectHref(s.id), title: tip, "data-seat": s.id },
    s.shot ? h("img", { class: "seat-shot", src: s.shot.url, alt: "", loading: "lazy" }) : null,
    h("span", { class: "seat-name" }, dot(s.id), h("b", {}, s.name)),
    h("span", { class: "seat-state" }, h("i", { class: "sdot", "aria-hidden": "true" }), state),
    p.total ? h("span", { class: "bar", title: `${p.done} of ${p.total} tasks done` },
      h("i", { style: `width:${(100 * p.done) / p.total}%` }), s.status === "running" && p.done < p.total ? h("i", { class: "run", style: `width:${100 / p.total}%` }) : null,
      s.failed_task ? h("i", { class: "fail", style: `width:${100 / p.total}%` }) : null) : null,
    h("span", { class: "seat-foot" },
      waiting ? h("span", { class: "waits" }, `${waiting} for you`) : h("span", { class: "muted" }, p.total ? `${Math.round((100 * p.done) / p.total)}% done` : s.where === "here" ? "This computer" : ""),
      s.spent_usd ? h("b", { title: "Spent on this project so far" }, money(s.spent_usd)) : null));
}

function placeRing(ring, n) {  // the seats on an ellipse around the table, the empty chair last
  const items = [...ring.querySelectorAll(":scope > .seat")];
  if (!items.length) return;
  ring.style.height = `${Math.min(860, Math.max(600, 74 * items.length))}px`;  // room for every seat, taller as the table fills
  items.forEach((el, i) => {
    const a = (2 * Math.PI * i) / items.length - Math.PI / 2;
    el.style.left = `${50 + 41 * Math.cos(a)}%`;
    el.style.top = `${50 + 42 * Math.sin(a)}%`;
  });
  ring.dataset.n = n;
}

export async function viewHall() {
  const table = h("div", { class: "hall-table" });
  const side = h("aside", { class: "hall-side", "aria-label": "Needs you" });
  const notes = h("div", { class: "hall-under" });
  const now = h("section", { class: "card hall-now" });
  const root = h("div", { class: "page hall" },
    h("div", { class: "hall-main" }, table, notes, now), side);
  const chair = () => h("a", { class: "seat chair", href: "#/new", title: "A few taps, then the planner makes a plan for you to check. Nothing is built until you approve it." },
    h("b", {}, "+ Pull up a chair"), h("span", {}, "Start a new idea"));

  let wide = true;
  const ro = new ResizeObserver(() => { const w = table.clientWidth > 760; if (w !== wide) { wide = w; table._sig = undefined; draw(S.rt); } });
  ro.observe(table);

  async function draw(rt) {
    if (!rt) return;
    await loadMachines();
    const seats = rt.seats;
    const waiting = seats.filter((s) => s.status === "waiting" || s.waiting_for_you).length;
    const ring = seats.length <= RING_MAX && wide;
    patch(table, JSON.stringify([ring, seats.map((s) => [s.id, s.name, s.state, s.status, s.progress, s.waiting_for_you, s.spent_usd, s.shot && s.shot.url, builtBy(s), s.where])]), () => {
      const centre = h("div", { class: "table-top", "aria-hidden": "true" }, h("i", { class: "flame" }), h("b", {}, "The Hall"),
        h("span", {}, `${plural(seats.length, "seat")}${waiting ? ` · ${waiting} need${waiting === 1 ? "s" : ""} you` : ""}`));
      if (!seats.length) return [h("div", { class: "ring empty-hall" }, centre), empty("No projects at the table yet. Write your first idea and the planner makes a plan for you to check.",
        h("a", { class: "btn primary", href: "#/new" }, "+ Start a new project"))];
      if (ring) {
        const r = h("div", { class: "ring", role: "list", "aria-label": "Projects at the table" }, centre, seats.map(seat), chair());
        r.querySelectorAll(".seat").forEach((x) => x.setAttribute("role", "listitem"));
        setTimeout(() => placeRing(r, seats.length), 0);
        return r;
      }
      return [h("div", { class: "table-band" }, centre), h("div", { class: "rows", role: "list", "aria-label": "Projects at the table" }, seats.map(seat), chair())];
    });
    table.querySelectorAll(".ring").forEach((r) => placeRing(r, seats.length));

    // beside the table: the first thing that needs you, answered here
    const items = await gather(rt, false);
    items.sort((a, b) => a.rank - b.rank);
    patch(side, JSON.stringify(items.map((i) => [i.project, i.kind, i.ask && [i.ask.id, i.ask.stamp], i.need && [i.need.text, i.need.id]])), () => {
      if (!items.length) return h("section", { class: "card calm" }, h("h2", {}, "Nothing needs you"),
        h("p", { class: "muted" }, "Every project is either working or waiting for a new idea. Questions, plans to approve and your to-dos show up here."),
        h("a", { class: "btn primary", href: "#/new" }, "+ Start a new project"));
      const [first, ...rest] = items;
      return [h("div", { class: "side-head" }, h("h2", {}, "Needs you"), h("span", { class: "count", title: "Every card waiting, letters not counted" }, needsCount(rt) || items.length),
        h("a", { class: "spacer-left", href: "#/needs" }, "See all")),
      needCard(first, null, { compact: true }),
      rest.length ? h("section", { class: "card next-up" }, h("h3", { class: "label" }, "Also waiting"),
        h("ul", { class: "plain" }, rest.slice(0, 8).map((i) => h("li", {}, h("a", { href: `#/needs` }, dot(i.project), h("b", {}, S.rt.seats.find((s) => s.id === i.project)?.name || i.project),
          " · ", i.ask ? i.ask.question : i.need ? i.need.text : "")))),
        rest.length > 8 ? h("a", { href: "#/needs" }, `and ${rest.length - 8} more`) : null) : null];
    });

    // under the table: my notes, the computers, the models' health, the hub's sync
    patch(notes, JSON.stringify([rt.notes && [rt.notes.open_todos, rt.notes.unread], rt.health, rt.sync_error, rt.synced_at && ago(rt.synced_at), S.offline]), () => {
      const n = rt.notes;
      const bad = (rt.health || []).filter((x) => x.state === "bad").length, off = (rt.health || []).filter((x) => x.state === "warn").length;
      return [
        n ? h("a", { class: "chip-link", href: projectHref(n.id), title: "Your own notes, to-dos and plans that don't belong to one project" },
          "My notes", n.open_todos ? h("small", {}, `${n.open_todos} to do`) : null, n.unread ? h("small", {}, `${n.unread} unread`) : null) : null,
        h("a", { class: "chip-link", href: "#/models/health", title: (rt.health || []).map((x) => `${x.model}: ${x.passed} of ${x.total} checks`).join("\n") || "The models haven't been checked yet" },
          h("i", { class: "hdot " + (bad ? "bad" : off ? "warn" : rt.health && rt.health.length ? "ok" : "") }),
          !(rt.health || []).length ? "Models not checked yet" : bad ? `${plural(bad, "model")} not answering` : off ? `${plural(off, "model")} a little off` : "Models healthy"),
        h("span", { class: "chip-link quiet", title: rt.sync_error || "Projects on other computers report through the hub" },
          h("i", { class: "hdot " + (S.offline ? "bad" : rt.sync_error ? "warn" : "ok") }),
          S.offline ? "The app isn't answering" : rt.sync_error ? "Hub sync has a problem" : rt.synced_at ? `Hub synced ${ago(rt.synced_at)}` : "Up to date"),
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
