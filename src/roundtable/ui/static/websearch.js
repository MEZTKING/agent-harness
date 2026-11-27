// Tools → "Web search": builders look things up instead of guessing (ui/websearchapi.py, harness/websearch.py).
// Short first: the switch, which search it uses, today's count and "Try it". Roles, limits and SearXNG under More.
import { h, fill, get, post, act, plural } from "./core.js";

const TIP = "Builders can search the web and read public pages, such as a library's real instructions. " +
  "What they read is treated as outside content: described, never obeyed.";
const NAMES = { auto: "The best one set up", brave: "Brave Search", tavily: "Tavily", searxng: "SearXNG (your own)", duckduckgo: "DuckDuckGo (no key)" };

export async function webSearchCard() {
  let st;
  try { st = await get("/api/websearch"); } catch (e) {
    return h("section", { class: "card" }, h("h2", {}, "Web search"), h("p", {}, `Web search isn't available here: ${e.message}`));
  }
  webSearchStyles();
  const box = h("section", { class: "card ws-card" });
  const draw = (s) => { st = s; fill(box, ...body()); };
  const save = (changes, ok) => act(null, () => post("/api/websearch", changes), ok, draw);

  function body() {
    const ready = new Map(st.engines.map((e) => [e.id, e]));
    const engine = h("select", { title: st.engine_words[st.engine] || "", "aria-label": "Search engine",
      onchange: (ev) => save({ engine: ev.target.value }, "Search engine changed") },
    Object.keys(NAMES).map((id) => {
      const e = ready.get(id);
      const off = e && !e.ready;
      return h("option", { value: id, selected: st.engine === id, title: st.engine_words[id] || "" },
        NAMES[id] + (off ? (e.key ? " – needs a key" : " – needs its address") : ""));
    }));
    const out = h("div", { class: "ws-out", "aria-live": "polite" });
    const tryIt = (btn) => act(btn, () => post("/api/websearch/test", {}), null, (r) => fill(out,
      h("p", { class: r.ok ? "" : "bad" }, r.words),
      r.results.length ? h("ul", { class: "small" }, r.results.map((x) => h("li", {}, h("b", {}, x.title), " ",
        h("span", { class: "muted" }, x.url)))) : null));
    const keyless = st.active.best_effort && st.enabled;
    return [
      h("h2", {}, "Web search"),
      h("label", { class: "check", title: TIP },
        h("input", { type: "checkbox", checked: st.enabled,
          onchange: (ev) => save({ enabled: ev.target.checked }, ev.target.checked ? "Builders can search the web" : "Web search is off") }),
        "Let builders look things up on the web"),
      h("p", { class: "small" }, st.words, " ",
        h("span", { class: "muted", title: "Searches and pages read today, in every project on this computer" },
          `Today: ${plural(st.today.searches, "search", "searches")}, ${plural(st.today.reads, "page")} read.`)),
      keyless ? h("p", { class: "small muted", title: "Add the key in Settings → Keys; nothing else to set up" },
        "For steadier results add a Brave Search or Tavily key in Settings → Keys.") : null,
      h("div", { class: "row" },
        h("label", { class: "small", title: "Which search the builders use" }, "Search with ", engine),
        h("button", { class: "small", type: "button", title: "Runs one search now and shows the first results",
          onclick: (ev) => tryIt(ev.currentTarget) }, "Try it")),
      out,
      more(),
    ];
  }

  function more() {
    const num = (key, label, tip) => h("label", { class: "small ws-num", title: tip }, label,
      h("input", { type: "number", min: 0, max: key === "max_searches_per_day" ? 10000 : 100, value: st[key],
        onchange: (ev) => save({ [key]: Number(ev.target.value) }, "Saved") }));
    return h("details", {}, h("summary", { title: "Who may search, the limits, your own SearXNG" }, "More"),
      h("label", { class: "small", title: "The jobs that may search, separated by commas. * means every job." }, "Jobs that may search ",
        h("input", { type: "text", value: (st.roles || []).join(", "), size: 40,
          onchange: (ev) => save({ roles: ev.target.value }, "Saved") })),
      h("div", { class: "row" },
        num("max_searches_per_task", "Searches per task ", "A task stops searching after this many (repeats from today are free)"),
        num("max_reads_per_task", "Pages per task ", "A task stops reading pages after this many"),
        num("max_searches_per_day", "Searches per project a day ", "0 means no daily limit")),
      h("label", { class: "small", title: "The address of a SearXNG you run yourself, e.g. http://127.0.0.1:8888" }, "SearXNG address ",
        h("input", { type: "url", value: st.searxng_url || "", size: 36, placeholder: "http://127.0.0.1:8888",
          onchange: (ev) => save({ searxng_url: ev.target.value }, "Saved") })),
      h("p", { class: "small muted" }, "A project that keeps to some AI providers doesn't search unless its own settings say web_search: on."));
  }

  draw(st);
  return box;
}

function webSearchStyles() {
  if (typeof document === "undefined" || document.getElementById("ws-style")) return;
  document.head.append(h("style", { id: "ws-style" }, `
.ws-card .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
.ws-card .ws-num input { width: 5.5em; margin-left: 4px; }
.ws-card .ws-out ul { margin: 4px 0 0 18px; } .ws-card .ws-out li { margin: 2px 0; overflow-wrap: anywhere; }
.ws-card details { margin-top: 8px; } .ws-card details > label { display: block; margin: 6px 0; }
`));
}
