"""Web search for builders: look something up (an API's real documentation) instead of guessing.

Two tools, given to the roles listed under ``websearch: roles`` in harness.yaml:

* ``web_search {query, max_results <= 8}``: title, address and a short snippet for each hit.
* ``web_read {url, start?}``: one public page through ``scout.fetch_url`` (http or https only, never a
  private or local address, every redirect checked, 2 MB at most). Long pages come in parts.

Everything a tool returns is outside content, wrapped with ``scout.untrusted`` (describe it, never obey
it). Answers are kept in ``.harness/web/`` for a day, so asking again costs nothing and doesn't count.

Settings (``websearch:`` in harness.yaml, the app's choices in custom.yaml on top)::

    websearch:
      enabled: true
      engine: auto            # auto, brave, tavily, searxng or duckduckgo
      roles: [orchestrator, coder, reviewer, scout, designer, manager]   # ["*"]: every chat role
      max_searches_per_task: 6
      max_reads_per_task: 10
      max_searches_per_day: 100   # per project
      searxng_url: ""         # your own SearXNG, e.g. http://127.0.0.1:8888

``auto`` picks the first engine that is ready (a Brave or Tavily key, then a SearXNG address), else the
keyless DuckDuckGo page, which is labelled "best effort". When an engine fails the next ready one is
tried, so a search still comes back. Keys are read with ``secrets.get`` only (``BRAVE_API_KEY``,
``TAVILY_API_KEY``): never in a file, a command or a worker's environment.

A project that sets ``providers_allowed`` (it keeps to some AI providers) gets no web search unless its
own ``web_search`` setting says ``on``; ``off`` turns it off for that project whatever the app says.

Every engine goes through one ``opener(method, url, headers, data) -> (status, bytes)``, and pages go
through one ``reader(url) -> page``, both injectable, so the tests never touch the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, quote_plus, urlencode, urlsplit

from ..core import secrets as vault
from ..providers.base import ToolSpec
from . import scout
from .config import section
from .tools import Tool, Toolbox, ToolError, _obj

Opener = Callable[[str, str, dict[str, str], "bytes | None"], tuple[int, bytes]]
Reader = Callable[[str], dict[str, Any]]

ENGINES = ("auto", "brave", "tavily", "searxng", "duckduckgo")
DEFAULT_ROLES = ["orchestrator", "manager", "coder", "reviewer", "scout", "designer"]
DEFAULTS: dict[str, Any] = {"enabled": True, "engine": "auto", "roles": list(DEFAULT_ROLES),
                            "max_searches_per_task": 6, "max_reads_per_task": 10, "max_searches_per_day": 100,
                            "searxng_url": ""}
KEYS = {"brave": "BRAVE_API_KEY", "tavily": "TAVILY_API_KEY"}
KEY_NAMES = {"BRAVE_API_KEY": "Brave Search", "TAVILY_API_KEY": "Tavily"}
MAX_RESULTS = 8
MAX_QUERY = 200
PART_CHARS = 20_000  # what one web_read shows the model; the rest comes with start=
CACHE_S = 24 * 3600
TIMEOUT = 20
MAX_ANSWER = 2_000_000
USER_AGENT = "RoundtableHold/1 (looks something up for a builder)"
STEP_WORDS = {"web_search": "Searched the web", "web_read": "Read a page"}
WEB_DIR = ".harness/web"

vault.remember_name(*KEYS.values())  # a worker's commands never see these (safeenv.py)


class SearchError(Exception):
    """A search couldn't be done; the message is plain and says why."""


# -- settings ---------------------------------------------------------------------------------------
def _int(v: Any, default: int, lo: int = 0, hi: int = 1000) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def clean_settings(raw: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """``raw`` over ``base`` (default DEFAULTS), each value checked; ValueError in plain words."""
    out = dict(base or DEFAULTS)
    for k, v in (raw or {}).items():
        if k not in DEFAULTS:
            continue
        if k == "enabled":
            out[k] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
        elif k == "engine":
            v = str(v or "auto").strip().lower()
            if v not in ENGINES:
                raise ValueError(f"the search engine should be one of {', '.join(ENGINES)}, not {v!r}")
            out[k] = v
        elif k == "roles":
            if isinstance(v, str):
                v = re.split(r"[,\s]+", v.strip().strip("[]"))
            out[k] = [str(x).strip() for x in (v or []) if str(x).strip()]
        elif k == "searxng_url":
            v = str(v or "").strip().rstrip("/")
            if v and urlsplit(v).scheme not in ("http", "https"):
                raise ValueError("the SearXNG address should start with http:// or https://")
            out[k] = v
        elif k == "max_searches_per_day":
            out[k] = _int(v, DEFAULTS[k], 0, 10_000)
        else:
            out[k] = _int(v, DEFAULTS[k], 0, 100)
    return out


def settings(cfg: Any) -> dict[str, Any]:
    """The web search settings: defaults, harness.yaml's ``websearch:``, then the app's (custom.yaml)."""
    out = clean_settings(section(cfg, "websearch")) if cfg is not None else dict(DEFAULTS)
    path = getattr(cfg, "path", None)
    if path:
        from .config import load_custom

        try:
            mine = load_custom(Path(path)).get("websearch")
        except Exception:  # an unreadable custom.yaml is reported elsewhere
            mine = None
        if isinstance(mine, dict):
            try:
                out = clean_settings(mine, out)
            except ValueError:
                pass
    return out


def project_choice(root: Path | str | None) -> tuple[str, bool]:
    """(the project's ``web_search``: "", "on" or "off"; whether it keeps to some providers)."""
    if not root:
        return "", False
    from . import projectsettings as ps

    st = ps.load(root)
    choice = st.values.get("web_search")
    if choice is None:  # read before the setting is listed: roundtable.yaml, then .harness/project.yaml
        for name in (ps.REPO_FILE, ps.PROJECT_FILE):
            raw, _ = ps._read_raw(Path(root) / name)
            if "web_search" in raw:
                v = raw["web_search"]
                choice = "on" if v is True else "off" if v is False else str(v or "").strip().lower()
    choice = choice if choice in ("on", "off") else ""
    return choice, bool(st.values.get("providers_allowed"))


def allowed(cfg: Any, role: Any, root: Path | str | None = None, s: dict[str, Any] | None = None) -> bool:
    """Does this role, in this project, get the web tools?"""
    s = s or settings(cfg)
    if getattr(role, "kind", "chat") != "chat":
        return False
    choice, keeps_to = project_choice(root)
    if choice == "off":
        return False
    if choice != "on" and (not s["enabled"] or keeps_to):
        return False
    roles = s["roles"]
    return "*" in roles or getattr(role, "name", role) in roles


# -- the query guard -------------------------------------------------------------------------------
def guard_query(text: Any) -> str:
    """One line, at most 200 characters, nothing shaped like a key and none of the owner's keys."""
    from .session import HIDDEN, redact

    q = redact(str(text or ""))
    for v in vault.values():
        if len(v) >= 6:
            q = q.replace(v, HIDDEN)
    q = " ".join(q.split())[:MAX_QUERY].strip()
    if not q or not q.replace(HIDDEN, "").strip():
        raise ToolError("give a few words to search for (no keys or passwords)")
    return q


# -- talking to the engines ------------------------------------------------------------------------
def default_opener(method: str, url: str, headers: dict[str, str], data: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(MAX_ANSWER)
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_ANSWER) if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        raise SearchError(f"couldn't reach {urlsplit(url).hostname}: {getattr(e, 'reason', e)}") from None


def _json(status: int, body: bytes, who: str) -> Any:
    if status in (401, 403):
        raise SearchError(f"{who} didn't accept the key (HTTP {status}); check it in Settings → Keys")
    if status == 429:
        raise SearchError(f"{who} says too many searches for now (HTTP 429); try again later")
    if status >= 400:
        raise SearchError(f"{who} said no (HTTP {status})")
    try:
        return json.loads(body.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        raise SearchError(f"{who} sent an answer Roundtable couldn't read") from None


def _hit(title: Any, url: Any, snippet: Any) -> dict[str, str] | None:
    url = str(url or "").strip()
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    tidy = lambda s: " ".join(scout.html_to_text(str(s or "")).split())  # noqa: E731
    return {"title": tidy(title)[:200] or url, "url": url, "snippet": tidy(snippet)[:400]}


def _hits(rows: Any, t: str, u: str, s: str) -> list[dict[str, str]]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            h = _hit(r.get(t), r.get(u), r.get(s))
            if h and all(h["url"] != x["url"] for x in out):
                out.append(h)
    return out


def parse_brave(data: Any) -> list[dict[str, str]]:
    return _hits(((data or {}).get("web") or {}).get("results"), "title", "url", "description")


def parse_tavily(data: Any) -> list[dict[str, str]]:
    return _hits((data or {}).get("results"), "title", "url", "content")


def parse_searxng(data: Any) -> list[dict[str, str]]:
    return _hits((data or {}).get("results"), "title", "url", "content")


class _DDG(HTMLParser):
    """The results of DuckDuckGo's plain HTML page: ``a.result__a`` (title, link), ``.result__snippet``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._in: str | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if self._in:
            self._depth += 1
            return
        if tag == "a" and "result__a" in cls:
            self.rows.append({"title": "", "url": _ddg_link(a.get("href") or ""), "snippet": ""})
            self._in, self._depth = "title", 0
        elif "result__snippet" in cls and self.rows:
            self._in, self._depth = "snippet", 0

    def handle_endtag(self, tag):
        if self._in:
            if self._depth:
                self._depth -= 1
            else:
                self._in = None

    def handle_data(self, data):
        if self._in and self.rows:
            self.rows[-1][self._in] += data


def _ddg_link(href: str) -> str:
    """DuckDuckGo's own redirect (``//duckduckgo.com/l/?uddg=<the real address>``) -> the real address."""
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com"):
        if parts.path.startswith("/y.js"):
            return ""  # an advert
        real = parse_qs(parts.query).get("uddg")
        return real[0] if real else ""
    return href


def parse_duckduckgo(html: str) -> list[dict[str, str]]:
    p = _DDG()
    p.feed(html or "")
    return _hits(p.rows, "title", "url", "snippet")


class Engine(Protocol):
    id: str
    name: str
    key: str | None  # the key's name in the key store, or None
    best_effort: bool

    def ready(self, s: dict[str, Any]) -> bool: ...

    def search(self, query: str, n: int, opener: Opener, s: dict[str, Any]) -> list[dict[str, str]]: ...


@dataclass
class Brave:
    id: str = "brave"
    name: str = "Brave Search"
    key: str | None = "BRAVE_API_KEY"
    best_effort: bool = False

    def ready(self, s):
        return vault.has(self.key)

    def search(self, query, n, opener, s):
        url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": query, "count": n})
        st, body = opener("GET", url, {"Accept": "application/json", "X-Subscription-Token": vault.get(self.key) or ""},
                          None)
        return parse_brave(_json(st, body, self.name))


@dataclass
class Tavily:
    id: str = "tavily"
    name: str = "Tavily"
    key: str | None = "TAVILY_API_KEY"
    best_effort: bool = False

    def ready(self, s):
        return vault.has(self.key)

    def search(self, query, n, opener, s):
        body = json.dumps({"query": query, "max_results": n, "search_depth": "basic"}).encode()
        st, raw = opener("POST", "https://api.tavily.com/search",
                         {"Content-Type": "application/json", "Authorization": f"Bearer {vault.get(self.key) or ''}"},
                         body)
        return parse_tavily(_json(st, raw, self.name))


@dataclass
class SearXNG:
    id: str = "searxng"
    name: str = "SearXNG"
    key: str | None = None
    best_effort: bool = False

    def ready(self, s):
        return bool(s.get("searxng_url"))

    def search(self, query, n, opener, s):
        if not s.get("searxng_url"):
            raise SearchError("no SearXNG address is set (websearch: searxng_url)")
        url = s["searxng_url"] + "/search?" + urlencode({"q": query, "format": "json"})
        st, body = opener("GET", url, {"Accept": "application/json"}, None)
        return parse_searxng(_json(st, body, self.name))[:n]


@dataclass
class DuckDuckGo:
    id: str = "duckduckgo"
    name: str = "DuckDuckGo"
    key: str | None = None
    best_effort: bool = True  # a page for people, read without a key: it may change or refuse

    def ready(self, s):
        return True

    def search(self, query, n, opener, s):
        st, body = opener("GET", "https://html.duckduckgo.com/html/?q=" + quote_plus(query), {"Accept": "text/html"},
                          None)
        if st >= 400:
            raise SearchError(f"DuckDuckGo said no (HTTP {st}); add a Brave or Tavily key for steadier searches")
        return parse_duckduckgo(body.decode("utf-8", errors="replace"))[:n]


ALL: dict[str, Engine] = {e.id: e for e in (Brave(), Tavily(), SearXNG(), DuckDuckGo())}


def order(s: dict[str, Any]) -> list[Engine]:
    """The engines to try, best first: the chosen one, then (for a failure) the other ready ones."""
    ready = [e for e in ALL.values() if e.ready(s)]
    if s["engine"] != "auto":
        first = ALL[s["engine"]]
        return [first] + [e for e in ready if e is not first]
    return ready


def active(s: dict[str, Any]) -> Engine:
    return order(s)[0]


def search(query: str, n: int, s: dict[str, Any], opener: Opener | None = None) -> tuple[Engine, list[dict[str, str]],
                                                                                         list[str]]:
    """(the engine that answered, its hits, what went wrong on the way). Raises SearchError if none did."""
    tried: list[str] = []
    for engine in order(s):
        if not engine.ready(s):
            tried.append(f"{engine.name}: not set up (no key or address)")
            continue
        try:
            return engine, engine.search(query, n, opener or default_opener, s), tried
        except SearchError as e:
            tried.append(f"{engine.name}: {e}")
    raise SearchError("; ".join(tried) or "no search engine is set up")


# -- the cache and the counts ----------------------------------------------------------------------
_count_lock = threading.Lock()


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def _cache_get(folder: Path, name: str) -> Any:
    p = folder / f"{name}.json"
    try:
        if time.time() - p.stat().st_mtime > CACHE_S:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cache_put(folder: Path, name: str, value: Any) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{name}.json.tmp"
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(folder / f"{name}.json")
    except OSError:  # a cache is a help, never a failure
        pass


def today_counts(root: Path | str) -> dict[str, Any]:
    """{day, searches, reads, tasks: {task: {searches, reads}}} for today, in this project."""
    p = Path(root) / WEB_DIR / "count.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get("day") != date.today().isoformat():
        data = {"day": date.today().isoformat(), "searches": 0, "reads": 0, "tasks": {}}
    data.setdefault("tasks", {})
    return data


def _bump(root: Path, kind: str, task: str) -> dict[str, Any]:
    with _count_lock:
        data = today_counts(root)
        data[kind] = int(data.get(kind) or 0) + 1
        if task:
            t = data["tasks"].setdefault(task, {"searches": 0, "reads": 0})
            t[kind] = int(t.get(kind) or 0) + 1
        _cache_put(Path(root) / WEB_DIR, "count", data)
        return data


# -- the tools -------------------------------------------------------------------------------------
@dataclass
class WebTools:
    """web_search and web_read for one task (or one planning call), with its own caps."""

    root: Path
    s: dict[str, Any]
    emit: Callable[[str, dict[str, Any]], None] | None = None
    task: str = ""  # with a task id, the caps hold across its attempts (counted in .harness/web/count.json)
    opener: Opener | None = None
    reader: Reader | None = None
    searches: int = 0
    reads: int = 0
    seen: dict[str, str] = field(default_factory=dict)  # url -> cached page name

    @property
    def folder(self) -> Path:
        return Path(self.root) / WEB_DIR

    def _used(self, kind: str) -> int:
        mine = self.searches if kind == "searches" else self.reads
        if not self.task:
            return mine
        t = today_counts(self.root)["tasks"].get(self.task) or {}
        return max(mine, int(t.get(kind) or 0))

    def _note(self, kind: str, data: dict[str, Any]) -> None:
        if self.emit:
            try:
                self.emit(kind, data)
            except Exception:  # the log is a help
                pass

    def web_search(self, a: dict[str, Any]) -> str:
        query = guard_query(a.get("query"))
        n = _int(a.get("max_results"), 5, 1, MAX_RESULTS)
        engines = order(self.s)
        name = _key("search", engines[0].id if engines else "", query.lower(), n)
        cached = _cache_get(self.folder, f"search-{name}")
        if cached is None:
            cap = self.s["max_searches_per_task"]
            if self._used("searches") >= cap:
                self._note("websearch_limit", {"what": "searches", "limit": cap})
                raise ToolError(f"that's the {cap} web searches this task may make; work from what you found")
            day_cap = self.s["max_searches_per_day"]
            if day_cap and today_counts(self.root)["searches"] >= day_cap:
                self._note("websearch_limit", {"what": "searches today", "limit": day_cap})
                raise ToolError(f"this project has made its {day_cap} web searches for today; work from what you know")
            try:
                engine, hits, tried = search(query, n, self.s, self.opener)
            except SearchError as e:
                raise ToolError(f"Couldn't search the web: {e}. Work from what you know and say so.") from None
            self.searches += 1
            _bump(self.root, "searches", self.task)
            cached = {"query": query, "engine": engine.id, "engine_name": engine.name,
                      "best_effort": engine.best_effort, "hits": hits, "tried": tried}
            _cache_put(self.folder, f"search-{name}", cached)
        hits = cached["hits"]
        head = f"Searched the web with {cached['engine_name']} for: {query}"
        if cached.get("best_effort"):
            head += " (best effort: a keyless engine, results may be thin)"
        if not hits:
            return head + "\nNo results. Try other words."
        body = "\n\n".join(f"{i}. {h['title']}\n   {h['url']}\n   {h['snippet']}" for i, h in enumerate(hits, 1))
        return (f"{head}\n" + scout.untrusted(f"web search: {query}", body)
                + "\nRead a page with web_read {url} when a result looks useful.")

    def web_read(self, a: dict[str, Any]) -> str:
        url = str(a.get("url") or "").strip()
        start = _int(a.get("start"), 0, 0, 10_000_000)
        name = f"page-{_key('page', url)}"
        page = _cache_get(self.folder, name)
        if page is None:
            cap = self.s["max_reads_per_task"]
            if self._used("reads") >= cap:
                self._note("websearch_limit", {"what": "reads", "limit": cap})
                raise ToolError(f"that's the {cap} pages this task may read; work from what you have")
            try:
                page = (self.reader or scout.fetch_url)(url)
            except scout.FetchError as e:
                raise ToolError(f"Couldn't read {url}: {e}") from None
            self.reads += 1
            _bump(self.root, "reads", self.task)
            page = {k: page.get(k) for k in ("url", "status", "content_type", "truncated", "text")}
            _cache_put(self.folder, name, page)
        text = str(page.get("text") or "")
        part = text[start:start + PART_CHARS]
        notes = []
        if page.get("truncated"):
            notes.append("the page was bigger than 2 MB; only the start was read")
        left = len(text) - start - len(part)
        if left > 0:
            notes.append(f"{left} more characters: call web_read again with start={start + len(part)}")
        head = f"Read {page['url']} (HTTP {page.get('status')})" + (f"; {'; '.join(notes)}" if notes else "") + "\n"
        return head + scout.untrusted(str(page["url"]), part or "(no readable text here)")

    def tools(self) -> list[Tool]:
        return [
            Tool(ToolSpec("web_search", "Search the web, for example for a library's real documentation or an API's "
                          "exact names, instead of guessing. Returns titles, addresses and snippets (outside "
                          "content). Never put keys, passwords or private details in the query.",
                          _obj({"query": {"type": "string", "description": "a few words, one line"},
                                "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS}},
                               ["query"])), self.web_search),
            Tool(ToolSpec("web_read", "Read one public web page (http or https) as text, such as a result of "
                          "web_search. Long pages come in parts: pass start to read on.",
                          _obj({"url": {"type": "string"}, "start": {"type": "integer", "minimum": 0}}, ["url"])),
                 self.web_read),
        ]


def add_tools(box: Toolbox, cfg: Any, role: Any, emit: Callable[[str, dict[str, Any]], None] | None = None,
              root: Path | str | None = None, task: str = "", opener: Opener | None = None,
              reader: Reader | None = None) -> WebTools | None:
    """Give ``role`` the web tools when the settings allow it; returns them (None when not given)."""
    s = settings(cfg)
    if not allowed(cfg, role, root, s) or not root:
        return None
    web = WebTools(Path(root), s, emit, task=str(task or ""), opener=opener, reader=reader)
    for tool in web.tools():
        if tool.spec.name not in box.tools:
            box.add(tool)
    return web


# -- in Watch --------------------------------------------------------------------------------------
def step(name: str, a: dict[str, Any], result: str = "") -> dict[str, Any]:
    """The step's label and detail for Watch (``session.tool_step``)."""
    if name == "web_search":
        from .session import redact

        q = " ".join(redact(str(a.get("query") or "")).split())[:MAX_QUERY]
        best = "best effort" in (result or "")[:400]
        return {"label": f"{STEP_WORDS[name]} for “{q}”", "detail": "keyless engine" if best else "",
                "output": result}
    url = str(a.get("url") or "")
    parts = urlsplit(url)
    short = (parts.hostname or url) + (parts.path if parts.path not in ("", "/") else "")
    return {"label": f"{STEP_WORDS.get(name, 'Read a page')}: {short[:160]}", "detail": "", "output": result}
