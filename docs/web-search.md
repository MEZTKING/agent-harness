# Web search for builders

Builders can look something up, such as a library's real documentation, instead of guessing. Each
search and each page read shows in Watch ("Searched the web for …", "Read a page: …").

## For the owner

- **Tools → Web search**: one switch, which search to use, today's count, and **Try it**.
- With no key it uses DuckDuckGo's plain page. That works, but it's *best effort*: fewer results, and it
  may refuse at times. For steadier results add a **Brave Search** or **Tavily** key in Settings → Keys.
- What builders read is treated as outside content: they describe it, never obey it.
- A project that keeps to some AI providers (`providers_allowed`) doesn't search unless its own settings
  say `web_search: on`. `web_search: off` turns it off for one project.

## The tools

| Tool | What it does |
|---|---|
| `web_search {query, max_results ≤ 8}` | Title, address and snippet for each hit. |
| `web_read {url, start?}` | One public page as text, in parts of 20,000 characters (`start` reads on). |

- Pages go through `scout.fetch_url`: http and https only, never a private or local address (checked
  after resolving and again on every redirect), 2 MB at most.
- Every answer is wrapped by `scout.untrusted`.
- The query is one line, at most 200 characters, passed through `session.redact`, and any stored key
  is taken out.
- Answers are kept in `.harness/web/` for a day. Asking again is free and doesn't count.
- Counts live in `.harness/web/count.json`: by day, and by task when the caller passes `task=`, so a
  task's caps hold across its attempts.

## Settings

In `harness.yaml`. The app's own choices go in `custom.yaml` on top, so `harness.yaml` is never rewritten.

```yaml
websearch:
  enabled: true
  engine: auto            # auto, brave, tavily, searxng, duckduckgo
  roles: [orchestrator, manager, coder, reviewer, scout, designer]   # ["*"] = every chat role
  max_searches_per_task: 6
  max_reads_per_task: 10
  max_searches_per_day: 100   # per project; 0 = no daily limit
  searxng_url: ""             # your own SearXNG, e.g. http://127.0.0.1:8888
```

`auto` tries Brave (with `BRAVE_API_KEY`), then Tavily (`TAVILY_API_KEY`), then SearXNG (with an
address), then DuckDuckGo. When the chosen engine fails, the next ready one is tried. Keys are read only
with `secrets.get`. They go in a request header, never in the address, a file or a worker's environment.

## API (the PC only)

- `GET /api/websearch`: the settings, the engines and whether each is ready, the active one, today's count.
- `POST /api/websearch`: change the settings (kept in `custom.yaml`).
- `POST /api/websearch/test`: one search now, the first three results.

## Code

`src/roundtable/harness/websearch.py` (`Engine`, `Brave`, `Tavily`, `SearXNG`, `DuckDuckGo`, `search`,
`WebTools`, `add_tools`, `step`), `src/roundtable/ui/websearchapi.py`, `src/roundtable/ui/static/websearch.js`
(`webSearchCard`), `tests/test_websearch.py`. Every engine goes through one injectable
`opener(method, url, headers, data)` and pages through one `reader(url)`, so tests use no network.
