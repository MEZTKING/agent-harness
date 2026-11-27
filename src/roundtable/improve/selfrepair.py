"""Fixes to the harness's own code, as a draft pull request it never lands itself (wave 7, plans/self-repair.md).

1. ``note(where, error)``: a fault inside the harness (a stage hook that failed, through the orchestrator's
   ``_hook_fault``) is kept in ``<app home>/faults.jsonl``: one row per fault and version,
   ``{sig, where, hook, type, shape, count, first, last, version}``. ``where`` is a module, function and line
   inside the harness only; the message is kept as its shape (no paths, no quoted text, no numbers).
2. ``ask(app)``: at three of the same fault on the version in use, one card for the owner: "The harness found
   a fault in itself. Try a fix for up to $1.50?" (``selfrepair.max_usd``). Nothing runs without a yes; a
   ``selfrepair: {on: false}`` in harness.yaml, or "Don't ask again", stops the cards.
3. ``answer(app, ask_id, chosen)``: on yes, ``attempt`` runs as a job. The harness works on a copy of its own
   repository under ``<app home>/self/<sig>``, in repository mode on the branch ``selfrepair/<sig>``, as a normal
   project (plan, build, review) with the fault as its goal and the price as its limit.
4. Then three checks, each of which stops it: every changed path passes ``charter.may_touch``; a test was
   added; the whole test suite passes.
5. Only then the branch reaches GitHub as one commit and a draft pull request is opened with the owner's GitHub
   key, through ``Writer`` (GitHub's API; the key stays in a request header, never in a git command). Its
   report names the kind of fault and where in the harness, never anything from the owner's projects. A card
   gives the link.

The pull request is the end: this module has no call that lands one (a test reads its source).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FAULTS = "faults.jsonl"
STATE = "selfrepair.json"
SELF_DIR = "self"
ASK_AT = 3
DEFAULT_MAX_USD = 1.50
BRANCH = "selfrepair/"
REPO = "MEZTKING/agent-harness"
SOURCE = f"https://github.com/{REPO}.git"
TEST_TIMEOUT_S = 1800
PKG = Path(__file__).resolve().parent.parent  # src/roundtable
_IDENT = ("-c", "user.name=Darkness Harness", "-c", "user.email=harness@localhost")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _home(home: str | Path | None = None) -> Path:
    if home:
        return Path(home)
    from ..desktop import app_home

    return app_home()


def _version() -> str:
    from .. import __version__

    return __version__


# -- 1. faults -------------------------------------------------------------------------------------------------
def shape(message: str) -> str:
    """A message without anything that could be a project's: quoted text, paths, numbers and long words go."""
    s = str(message or "")[:400]
    s = re.sub(r"(['\"`]).*?\1", "'…'", s)
    s = re.sub(r"(?:[A-Za-z]:)?[\\/][^\s,;:)]+", "<path>", s)
    s = re.sub(r"\b[\w.-]+\.(?:py|js|json|yaml|yml|md|txt|toml|kt)\b", "<file>", s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b|\b\d+(?:\.\d+)?\b", "N", s)
    s = re.sub(r"\b[A-Za-z0-9_]{25,}\b", "<id>", s)
    return " ".join(s.split())[:160]


def where_in_harness(error: BaseException) -> dict[str, Any] | None:
    """The deepest frame of ``error`` inside the harness's own package: {module, function, line}."""
    found = None
    for fr in traceback.extract_tb(error.__traceback__) if error.__traceback__ else []:
        try:
            rel = Path(fr.filename).resolve().relative_to(PKG)
        except (ValueError, OSError):
            continue
        mod = ".".join(("roundtable", *rel.with_suffix("").parts))
        found = {"module": mod, "function": fr.name, "line": int(fr.lineno or 0)}
    return found


def _read_faults(home: Path) -> list[dict[str, Any]]:
    p = home / FAULTS
    rows = []
    if p.is_file():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("sig"):
                rows.append(r)
    return rows


def _write_faults(home: Path, rows: list[dict[str, Any]]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / (FAULTS + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-500:]), encoding="utf-8")
    tmp.replace(home / FAULTS)


def note(where: str, error: BaseException, home: str | Path | None = None, version: str | None = None) -> dict | None:
    """Keep one fault. Never raises: a fault in keeping faults is no reason to stop a run."""
    try:
        loc = where_in_harness(error)
        if loc is None:
            return None  # not in the harness's own code (a plugin's, a provider library's): not ours to fix
        etype = type(error).__name__
        form = shape(str(error))
        key = f"{etype}|{loc['module']}|{loc['function']}|{form}"
        sig = hashlib.sha256(key.encode()).hexdigest()[:10]
        h, v, now = _home(home), version or _version(), _now()
        rows = _read_faults(h)
        for r in rows:
            if r["sig"] == sig and r.get("version") == v:
                r["count"] = int(r.get("count") or 0) + 1
                r["last"] = now
                r["where"] = f"{loc['module']}.{loc['function']}:{loc['line']}"
                break
        else:
            r = {"sig": sig, "where": f"{loc['module']}.{loc['function']}:{loc['line']}",
                 "hook": re.sub(r"[^\w]", "", str(where or ""))[:60], "type": etype, "shape": form, "count": 1,
                 "first": now, "last": now, "version": v}
            rows.append(r)
        _write_faults(h, rows)
        return r
    except Exception:  # noqa: BLE001
        return None


# -- 2. the card ------------------------------------------------------------------------------------------------
def _state(home: Path) -> dict[str, Any]:
    p = home / STATE
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("answers", {})
    d.setdefault("results", {})
    return d


def _save_state(home: Path, st: dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / STATE).write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def settings(cfg: Any) -> dict[str, Any]:
    from ..harness.config import section

    s = section(cfg, "selfrepair") if cfg is not None else {}
    try:
        cap = float(s.get("max_usd") if s.get("max_usd") is not None else DEFAULT_MAX_USD)
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_USD
    return {"on": s.get("on") is not False, "max_usd": max(0.0, cap), "repo": str(s.get("repo") or REPO)}


def due(home: Path, version: str | None = None) -> list[dict[str, Any]]:
    """Faults seen at least three times on the version in use that the owner hasn't answered."""
    v = version or _version()
    st = _state(home)
    out = [r for r in _read_faults(home) if r.get("version") == v and int(r.get("count") or 0) >= ASK_AT
           and f"{r['sig']}@{v}" not in st["answers"]]
    return sorted(out, key=lambda r: (-int(r.get("count") or 0), r.get("first") or ""))


def _plain_where(r: dict[str, Any]) -> str:
    mod = str(r.get("where") or "").split(":", 1)[0].removeprefix("roundtable.")
    return mod or "the harness"


def ask(app: Any, home: str | Path | None = None, version: str | None = None) -> list[dict[str, Any]]:
    """The cards for the owner: one fault to fix (at most one at a time), and each fix ready to look at."""
    h = _home(home or _app_home(app))
    cfg = _cfg(app)
    s = settings(cfg)
    st = _state(h)
    cards: list[dict[str, Any]] = []
    for sig, res in sorted(st["results"].items()):
        if res.get("pr_url") and not res.get("seen"):
            cards.append({"id": f"selfrepair-done-{sig}", "kind": "selfrepair_done", "project": None,
                          "header": "Own fix", "question": "The harness's fix to itself is ready for you to look at.",
                          "detail": "It's a draft pull request on GitHub: nothing changes until you take it.",
                          "link": res["pr_url"], "options": [{"id": "seen", "label": "Got it", "description": ""}],
                          "recommended": "seen", "multi": False, "allow_other": False, "answer": None,
                          "source": {"selfrepair": sig}})
    if not s["on"] or st.get("never") or any(r.get("running") for r in st["results"].values()):
        return cards
    todo = due(h, version)
    if not todo:
        return cards
    r = todo[0]
    price = f"${s['max_usd']:.2f}"
    cards.append({
        "id": f"selfrepair-{r['sig']}", "kind": "selfrepair", "project": None, "header": "Fix itself",
        "question": f"The harness found a fault in itself. Try a fix for up to {price}?",
        "detail": (f"It went wrong {r['count']} times in {_plain_where(r)} ({r['type']}). The harness would work on "
                   "a copy of its own code and, if every test passes, open a draft pull request for you to look at. "
                   "It never takes the change in by itself."),
        "options": [{"id": "yes", "label": "Try a fix", "description": f"Up to {price} of your credit",
                     "confirm": f"This spends up to {price}. Go ahead?"},
                    {"id": "no", "label": "Not now", "description": "Asks again if it happens on the next version"},
                    {"id": "never", "label": "Don't ask again", "description": "No more of these cards"}],
        "recommended": "no", "multi": False, "allow_other": False, "answer": None, "price_usd": s["max_usd"],
        "source": {"selfrepair": r["sig"], "version": r.get("version")}})
    return cards


def _app_home(app: Any) -> Path | None:
    try:
        return app._backup_home()
    except Exception:  # noqa: BLE001
        return None


def _cfg(app: Any):
    try:
        return app.cfg()
    except Exception:  # noqa: BLE001
        return None


def answer(app: Any, ask_id: str, chosen: str | list[str] | None, home: str | Path | None = None,
           start: Callable[..., Any] | None = None, **attempt_kw: Any) -> dict[str, Any]:
    """The owner's answer. "yes" starts ``attempt`` as a job (``start``: the app's jobs by default)."""
    h = _home(home or _app_home(app))
    pick = (chosen[0] if isinstance(chosen, list) and chosen else chosen) or ""
    st = _state(h)
    if ask_id.startswith("selfrepair-done-"):
        sig = ask_id.removeprefix("selfrepair-done-")
        if sig in st["results"]:
            st["results"][sig]["seen"] = True
            _save_state(h, st)
        return {"ok": True}
    sig = ask_id.removeprefix("selfrepair-")
    rows = [r for r in _read_faults(h) if r["sig"] == sig]
    if not rows:
        raise ValueError("That fault isn't on the list any more.")
    r = rows[-1]
    st["answers"][f"{sig}@{r.get('version')}"] = {"answer": pick, "at": _now()}
    if pick == "never":
        st["never"] = True
    _save_state(h, st)
    if pick != "yes":
        return {"ok": True, "started": False}
    st["said_yes"] = True
    st["results"][sig] = {"running": True, "at": _now()}
    _save_state(h, st)
    cfg = _cfg(app)

    def run(job=None):
        line = (lambda t: job.line(t)) if job is not None and hasattr(job, "line") else (lambda t: None)
        try:
            res = attempt(cfg, h, r, say=line, **attempt_kw)
        except Exception as e:  # noqa: BLE001 - the card says what happened
            res = {"ok": False, "stage": "error", "why": f"It stopped: {shape(str(e))}"}
        st2 = _state(h)
        st2["results"][sig] = {**res, "running": False, "at": _now()}
        _save_state(h, st2)
        return res

    if start is None and getattr(app, "jobs", None) is not None:
        return {"ok": True, "started": True,
                "job": app.jobs.start("selfrepair", "fix a fault in itself", run, target="selfrepair").view()}
    if start is not None:
        return {"ok": True, "started": True, "job": start(run)}
    return {"ok": True, "started": True, "result": run()}


# -- 3. the work -------------------------------------------------------------------------------------------------
def goal_for(r: dict[str, Any]) -> str:
    """The project's goal, from the fault's row only."""
    return (f"Fix a fault in this app's own code (the harness itself). {r.get('type')} in {r.get('where')}, seen "
            f"{r.get('count')} times on version {r.get('version')}. The error read: {r.get('shape') or 'no message'}. "
            "Find the cause and fix it there, with the smallest change that does. Add a test under tests/ that "
            "fails without the fix and passes with it, and keep every other test passing. Never change the gate, "
            "key handling, money limits, makers, the charter, the plugin sandbox or the release files.")


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    from ..harness.safeenv import clean_env

    res = subprocess.run(["git", *_IDENT, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=clean_env(), timeout=600)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {args[0]} didn't work: {shape(res.stderr.strip()[-300:])}")
    return res.stdout.strip()


def prepare(home: Path, sig: str, source: str = SOURCE) -> tuple[Path, str, str]:
    """A fresh copy of the harness's repository on its own branch: (folder, start commit, start branch).
    An older copy is moved aside, never deleted."""
    root = home / SELF_DIR
    work = root / sig
    if work.exists():
        aside = root / ".old" / f"{sig}-{_now().replace(':', '')}"
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work), str(aside))
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "clone", "-q", "--depth", "50", source, str(work))
    base = _git(work, "rev-parse", "HEAD")
    start = _git(work, "symbolic-ref", "--short", "-q", "HEAD", check=False) or "main"
    _git(work, "checkout", "-q", "-b", BRANCH + sig)
    return work, base, start


def default_build(cfg: Any, work: Path, goal: str, max_usd: float, branch: str, say: Callable[[str], None]) -> dict:
    """The harness at work on itself, as a normal project in repository mode (plan, approve, build, review)."""
    from ..harness import projectsettings as ps
    from ..harness.orchestrator import Orchestrator

    ps.update(work, {"branch": branch, "test": f"{sys.executable} -m pytest tests -q -x",
                     "limits": {"max_cost_usd": max_usd, "max_real_usd_per_run": max_usd}})
    variant = cfg.variant()
    variant.limits.max_cost_usd = min(float(variant.limits.max_cost_usd), max_usd)
    orch = Orchestrator(variant, work, on_event=lambda k, d: say(k) if k in ("task_start", "task_done") else None)
    orch.start(goal)
    orch.plan()
    orch.approve()
    status = orch.run()
    return {"status": status, "spent_usd": round(orch.budget.spent_usd, 4)}


def default_tests(work: Path) -> tuple[bool, str]:
    from ..harness.safeenv import clean_env

    env = clean_env({"PYTHONPATH": str(work / "src")})
    try:
        from ..pyexec import python_command  # the app's own Python when frozen (pytest is bundled)

        res = subprocess.run([*python_command(), "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], cwd=work,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                             timeout=TEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "The tests took too long."
    tail = "\n".join((res.stdout or "").strip().splitlines()[-3:])
    return res.returncode == 0, tail


def changes(work: Path, base: str) -> list[tuple[str, str]]:
    """(status, path) for every path the work changed since the start commit (its own commits and anything left)."""
    if _git(work, "status", "--porcelain", "--untracked-files=all", check=False):
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", "harness: the rest of the fix")
    out = []
    for ln in _git(work, "diff", "--name-status", "--no-renames", f"{base}..HEAD").splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2:
            out.append((parts[0][:1], parts[-1]))
    return out


def test_added(work: Path, base: str, changed: list[tuple[str, str]]) -> bool:
    tests = [p for st, p in changed if st in ("A", "M") and p.startswith("tests/") and p.endswith(".py")]
    if not tests:
        return False
    diff = _git(work, "diff", f"{base}..HEAD", "--", *tests)
    return bool(re.search(r"^\+\s*(?:async\s+)?def test_\w*", diff, re.M))


def attempt(cfg: Any, home: Path, fault: dict[str, Any], *, source: str = SOURCE, writer: "Writer | None" = None,
            build: Callable[..., dict] | None = None, run_tests: Callable[[Path], tuple[bool, str]] | None = None,
            say: Callable[[str], None] = lambda t: None) -> dict[str, Any]:
    """One try at a fix. Returns {ok, stage, why, pr_url?, changed, spent_usd}; ``stage`` is where it stopped."""
    from . import charter

    s = settings(cfg)
    sig = str(fault["sig"])
    branch = BRANCH + sig
    say("Making a copy of the harness's own code")
    work, base, start = prepare(Path(home), sig, source)
    say("Working on the fix")
    built = (build or default_build)(cfg, work, goal_for(fault), s["max_usd"], branch, say)
    spent = float((built or {}).get("spent_usd") or 0)
    changed = changes(work, base)
    out = {"ok": False, "sig": sig, "branch": branch, "changed": [p for _, p in changed], "spent_usd": spent}
    if not changed:
        return {**out, "stage": "build", "why": "The work changed nothing, so there's nothing to look at."}
    refused = [p for _, p in changed if not charter.may_touch(p)]
    if refused:
        return {**out, "stage": "charter", "refused": refused,
                "why": "The fix touched parts the harness may never change by itself, so nothing was opened."}
    if not test_added(work, base, changed):
        return {**out, "stage": "test_added", "why": "The fix came without a new test, so nothing was opened."}
    say("Running every test")
    ok, tail = (run_tests or default_tests)(work)
    if not ok:
        return {**out, "stage": "tests", "why": "Some tests failed with the fix, so nothing was opened.",
                "tests": shape(tail)}
    w = writer or Writer.from_vault()
    files = {}
    for st, p in changed:
        f = work / p
        files[p] = None if st == "D" or not f.is_file() else f.read_bytes()
    say("Opening a draft pull request")
    url = w.open_draft(s["repo"], branch=branch, base_sha=base, base_branch=start, files=files,
                       title=f"Fix itself: {fault.get('type')} in {_plain_where(fault)}",
                       body=report(fault, [p for _, p in changed], spent))
    return {**out, "ok": True, "stage": "opened", "pr_url": url, "why": "A draft pull request is ready to look at."}


def report(fault: dict[str, Any], changed: list[str], spent: float) -> str:
    """The pull request's words: the kind of fault and where in the harness, the checks; nothing of a project's."""
    files = "\n".join(f"- `{p}`" for p in changed[:60])
    return (f"The harness found a fault in itself and tried a fix.\n\n"
            f"- **Fault:** {fault.get('type')} in `{fault.get('where')}` ({fault.get('count')} times on "
            f"{fault.get('version')})\n- **Message, as its shape:** {fault.get('shape') or '–'}\n"
            f"- **Cost of the try:** ${spent:.2f}\n\n"
            f"**Checks:** every changed file is one the harness may change; a test was added; every test passed.\n\n"
            f"**Changed:**\n{files}\n\n"
            "This is a draft. The harness never takes it in by itself: look at it, and take it only if you want it.")


# -- 4. GitHub ---------------------------------------------------------------------------------------------------
Post = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, str], bytes]]


def http_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(4_000_000)
    except urllib.error.HTTPError as e:
        return e.code, {}, e.read() if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Couldn't reach GitHub ({getattr(e, 'reason', e)}). Try again later.") from None


class Writer:
    """The few GitHub calls a draft pull request needs, beside ``automation.GitHub.get`` (its key and headers).
    Only POSTs to blobs, trees, commits, refs and pulls: nothing here can land a pull request."""

    ALLOWED = ("/git/blobs", "/git/trees", "/git/commits", "/git/refs", "/pulls")

    def __init__(self, gh: Any, post: Post | None = None):
        self.gh, self.http_post = gh, post or http_post

    @classmethod
    def from_vault(cls) -> "Writer":
        from ..automation import GitHub, github_token

        token = github_token()
        if not token:
            raise RuntimeError("There's no GitHub key yet. Add one on the Automations page, then try again.")
        return cls(GitHub(token))

    def post(self, repo: str, path: str, payload: dict[str, Any]) -> Any:
        if path not in self.ALLOWED:
            raise ValueError(f"not a call the self-repair makes: {path}")
        from ..automation import API

        status, _, body = self.http_post(f"{API}/repos/{repo}{path}", self.gh._headers(),
                                         json.dumps(payload).encode())
        self.gh._check(status, body, repo)
        return json.loads(body or b"null")

    def open_draft(self, repo: str, *, branch: str, base_sha: str, base_branch: str, files: dict[str, bytes | None],
                   title: str, body: str) -> str:
        commit = self.gh.get(repo, f"/git/commits/{base_sha}")
        tree = []
        for path, data in sorted(files.items()):
            if data is None:
                tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = self.post(repo, "/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = self.post(repo, "/git/trees", {"base_tree": commit["tree"]["sha"], "tree": tree})
        new_commit = self.post(repo, "/git/commits", {"message": title, "tree": new_tree["sha"], "parents": [base_sha]})
        self.post(repo, "/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
        pr = self.post(repo, "/pulls", {"title": title, "head": branch, "base": base_branch, "body": body,
                                        "draft": True})
        return str(pr.get("html_url") or "")
