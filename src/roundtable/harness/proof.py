"""Proof: before and after, shown with every finished task ("Every task must be easy to see").

* ``before``: the pictures of the project as it was when the task started. They are kept by commit in
  ``.harness/shots/by-commit/<sha>/``, so tasks that start from the same commit share them, and the
  newest pictures already taken at that commit are reused: there is usually no extra render.
* ``pairs`` / ``difference``: each picture before and after, with how much changed (0 to 1, with
  Pillow when it is there; otherwise a file hash says "looks the same" or "changed").
* ``tests_part`` / ``counts``: the project's test command before the run (the baseline) and after the
  task, as counts and the last lines of output.
* ``judge``: one call to a model that can see (the ``proof`` role, else the reviewer's models), with at
  most four pictures and the tool ``submit_proof``. Capped at ``max_usd_per_task`` and charged to the
  run's budget. Its verdict is advice for the reviewer; it never rejects work by itself unless
  ``proof.strict`` is set (and then only by telling the reviewer so).
* ``write`` / ``read`` / ``history``: ``proof.json`` beside the task's ``shots.json``, with ``words``
  such as "A model that can see checked: the menu is there. Tests: 41 pass, 3 new."
* ``plan_for`` / ``lines``: a kind's proof list (``[{id, how, words, optional?, status?}]``) as a plan,
  and which of its items a proof record shows passed.

Settings, ``proof:`` in harness.yaml: ``enabled`` (true), ``judge`` (true), ``max_usd_per_task``
(0.05), ``strict`` (false), ``max_pictures`` (4), ``role`` ("proof").

Proof is a help, never a reason to fail a task: every problem is written down instead.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import showit

PROOF_FILE = "proof.json"
BY_COMMIT = "by-commit"
VERDICTS = ("shows_it", "does_not", "cant_tell")
NOBODY = "Nobody looked at the pictures"
TAIL_LINES = 12
# a picture's rough size for a model, in tokens (most makers count about this for a 1280×800 picture)
PICTURE_TOKENS = 1600
JUDGE_MAX_TOKENS = 700
PREFERRED = ("desktop", "phone", "dark", "start", "middle")


@dataclass
class Settings:
    enabled: bool = True
    judge: bool = True
    max_usd_per_task: float = 0.05
    strict: bool = False
    max_pictures: int = 4
    role: str = "proof"

    @classmethod
    def from_config(cls, cfg: Any) -> "Settings":
        from .config import section

        s = cls()
        raw = section(cfg, "proof") if cfg is not None else {}
        for k, v in raw.items():
            if not hasattr(s, k) or v is None:
                continue
            cur = getattr(s, k)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
                setattr(s, k, type(cur)(v))
            except (TypeError, ValueError):
                continue
        s.max_pictures = max(1, min(8, s.max_pictures))
        s.max_usd_per_task = max(0.0, s.max_usd_per_task)
        return s


# -- before ------------------------------------------------------------------------------------
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _safe_sha(sha: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", sha or "")[:64]


def by_commit_dir(project_root: Path, sha: str) -> Path:
    return showit.shots_root(project_root) / BY_COMMIT / _safe_sha(sha)


def _load(p: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def pictures_dir(project_root: Path, record: dict[str, Any]) -> Path:
    return showit.shots_root(project_root) / str(record.get("dir") or showit._safe_task(str(record.get("task", ""))))


def keep_by_commit(project_root: Path, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy a set of pictures to ``by-commit/<its commit>/`` so later tasks starting there reuse it."""
    if not record or not record.get("commit") or not record.get("pictures"):
        return None
    src = pictures_dir(project_root, record)
    dest = by_commit_dir(project_root, record["commit"])
    if src.resolve() == dest.resolve():
        return record
    dest.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.*"):
        if f.suffix in (".png", ".jpg") and f.is_file():
            shutil.copy2(f, dest / f.name)
    kept = {**record, "dir": f"{BY_COMMIT}/{dest.name}", "from_task": record.get("task", "")}
    (dest / "shots.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return kept


def find_before(project_root: Path, sha: str) -> dict[str, Any] | None:
    """Pictures already taken at commit ``sha``: the by-commit set, else the newest task's at that commit."""
    if not _safe_sha(sha):
        return None
    rec = _load(by_commit_dir(project_root, sha) / "shots.json")
    if rec and rec.get("pictures"):
        return rec
    for r in showit.history(project_root, limit=200):
        if r.get("commit") == sha and r.get("pictures"):
            return keep_by_commit(project_root, r)
    return None


def before(project_root: Path, task: Any, work_root: Path | None = None, render: Callable | None = None,
           godot: Any = None) -> dict[str, Any]:
    """The pictures of the project as the task found it. Never raises.

    Reused when pictures at the task's ``base_commit`` exist; taken fresh of ``work_root`` (the
    folder the task works in, still at that commit) only when there are none."""
    root = Path(project_root)
    work = Path(work_root or root)
    sha = getattr(task, "base_commit", None) or showit.commit_of(work)
    if not _safe_sha(sha):
        return {"commit": "", "pictures": {}, "reused": False,
                "note": "there's no saved version to compare with, so there are no pictures from before"}
    with _lock(f"{root.resolve()}:{sha}"):  # two tasks starting together share one set
        found = find_before(root, sha)
        if found:
            return {**found, "reused": True}
        try:
            rec = showit.take_shots(work, getattr(task, "id", "before"), render=render, godot=godot,
                                    out_dir=by_commit_dir(root, sha), latest=False, commit=sha)
        except Exception as e:  # take_shots writes its problems down; this is for the unexpected
            rec = {"commit": sha, "pictures": {}, "failed": str(e)[:300]}
        return {**rec, "reused": False}


# -- what changed --------------------------------------------------------------------------------
def _file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def difference(a: Path, b: Path) -> tuple[float | None, bool]:
    """How much of picture ``b`` differs from ``a``: (0..1, measured). With Pillow, the share of the
    picture that changed noticeably; without it, 0 or 1 from the files' hashes (measured False)."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(a) as ia, Image.open(b) as ib:
                size = (160, 100)
                x = ia.convert("RGB").resize(size)
                y = ib.convert("RGB").resize(size)
            diff = ImageChops.difference(x, y).convert("L")
            changed = sum(diff.histogram()[25:])  # pixels that differ noticeably
            return round(changed / (size[0] * size[1]), 4), True
        except Exception:  # not a picture Pillow reads: fall back to the files
            pass
    try:
        return (0.0 if _file_hash(a) == _file_hash(b) else 1.0), False
    except OSError:
        return None, False


def change_words(change: float | None, measured: bool = True) -> str:
    if change is None:
        return "can't compare"
    if not measured:
        return "looks the same" if change == 0 else "changed"
    if change == 0:
        return "looks the same"
    if change < 0.02:
        return "barely changed"
    return f"changed (about {max(1, round(change * 100))}%)"


def _pic(d: Path, kind: str) -> Path | None:
    for ext in (".png", ".jpg"):
        p = d / f"{kind}{ext}"
        if p.is_file():
            return p
    return None


def pairs(project_root: Path, before_rec: dict[str, Any] | None, after_rec: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Each picture after the task beside the same picture before it (``before`` None when it is new)."""
    if not after_rec:
        return []
    bdir = pictures_dir(project_root, before_rec) if before_rec and before_rec.get("pictures") else None
    adir = pictures_dir(project_root, after_rec)
    kinds = sorted(after_rec.get("pictures") or {}, key=lambda k: PREFERRED.index(k) if k in PREFERRED else 99)
    out = []
    for kind in kinds:
        pa = _pic(adir, kind)
        if pa is None:
            continue
        pb = _pic(bdir, kind) if bdir is not None and kind in (before_rec.get("pictures") or {}) else None
        if pb is None:
            out.append({"kind": kind, "before": None, "after": pa.name, "change": None, "measured": False,
                        "words": "new"})
            continue
        change, measured = difference(pb, pa)
        out.append({"kind": kind, "before": pb.name, "after": pa.name, "change": change, "measured": measured,
                    "words": change_words(change, measured)})
    return out


# -- the tests ---------------------------------------------------------------------------------
_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|pass|fail)\b", re.I)


def counts(tail: str) -> dict[str, int] | None:
    """Passed and failed counts from a test run's last lines (pytest, unittest, Jest, node, cargo, go)."""
    text = tail or ""
    passed = failed = None
    # pytest's last line "== 41 passed, 3 failed in 1.2s ==", cargo's "test result: ok. 41 passed; 0 failed"
    for line in reversed(text.splitlines()):
        found = _COUNT.findall(line)
        if found and (re.search(r"passed|failed", line, re.I) or line.strip().startswith(("#", "ℹ"))):
            p = f = 0
            for n, word in found:
                w = word.lower()
                if w in ("passed", "pass", "xpassed"):
                    p += int(n)
                elif w in ("failed", "fail", "error", "errors"):
                    f += int(n)
            passed, failed = p, f
            break
    if passed is None:  # node --test: "# pass 41" and "# fail 3" on lines of their own
        mp = re.findall(r"^#\s*pass\s+(\d+)", text, re.M)
        mf = re.findall(r"^#\s*fail\s+(\d+)", text, re.M)
        if mp:
            passed, failed = int(mp[-1]), int(mf[-1]) if mf else 0
    if passed is None:  # Jest: "Tests:       3 failed, 41 passed, 44 total"
        m = re.search(r"^Tests:\s+(.*)$", text, re.M)
        if m:
            passed = sum(int(n) for n in re.findall(r"(\d+) passed", m.group(1)))
            failed = sum(int(n) for n in re.findall(r"(\d+) failed", m.group(1)))
    if passed is None:  # unittest: "Ran 44 tests" then "OK" or "FAILED (failures=2, errors=1)"
        m = re.search(r"^Ran (\d+) tests?", text, re.M)
        if m:
            total = int(m.group(1))
            bad = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", text))
            passed, failed = total - bad, bad
    if passed is None:
        return None
    return {"passed": passed, "failed": failed or 0}


def _tail(text: str, n: int = TAIL_LINES) -> str:
    return "\n".join((text or "").rstrip().splitlines()[-n:])


def _side(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    c = counts(summary.get("tail", ""))
    return {"ok": bool(summary.get("passed")), "passed": c["passed"] if c else None,
            "failed": c["failed"] if c else (len(summary.get("failing") or []) or None),
            "tail": _tail(summary.get("tail", ""))}


def tests_part(baseline: dict[str, Any] | None, checks: dict[str, Any] | None) -> dict[str, Any] | None:
    """The tests before (the baseline) and after the task, as counts and words. ``checks`` is what the
    review's checks found (``verdict``, ``new``, and ``now``, the run's summary, when it is there)."""
    if not checks and not baseline:
        return None
    before_side = _side(baseline)
    now = (checks or {}).get("now")
    after_side = _side(now)
    verdict = (checks or {}).get("verdict")
    if after_side is None and verdict:
        after_side = {"ok": verdict == "pass", "passed": None, "failed": None, "tail": ""}
    out: dict[str, Any] = {"command": (now or baseline or {}).get("command", ""), "before": before_side,
                           "after": after_side, "verdict": verdict, "broke": list((checks or {}).get("new") or [])[:20]}
    out["words"] = tests_words(out)
    return out


def tests_words(t: dict[str, Any] | None) -> str:
    if not t or not t.get("after"):
        return "Tests: not run for this task." if t else ""
    a, b = t["after"], t.get("before") or {}
    broke = len(t.get("broke") or [])
    if a.get("passed") is not None:
        parts = [f"{a['passed']} pass"]
        if b.get("passed") is not None and a["passed"] > b["passed"]:
            parts.append(f"{a['passed'] - b['passed']} new")
        if broke:
            parts.append(f"{broke} broke")
        elif a.get("failed"):
            parts.append(f"{a['failed']} fail" + (" (as before)" if t.get("verdict") == "old_only" else ""))
        return "Tests: " + ", ".join(parts) + "."
    v = t.get("verdict")
    return {"pass": "Tests: they pass.", "old_only": "Tests: only the ones failing before still fail.",
            "unknown": "Tests: failing before and after; can't tell test by test.",
            "new": f"Tests: {broke or 'some'} broke."}.get(v or "", "Tests: not run for this task.")


# -- the judge ---------------------------------------------------------------------------------
JUDGE_SYSTEM = ("You check whether a change to an app shows in its pictures. You see pictures of the app before "
                "and after one task. Look carefully, then call submit_proof once. Be honest: say cant_tell when the "
                "pictures don't show enough, and never guess.")


def _seeing_ref(cfg: Any, settings: Settings) -> Any:
    from .. import attachments
    from ..providers.base import Provider

    roles = getattr(cfg, "roles", {}) or {}
    role = roles.get(settings.role) or roles.get(getattr(cfg, "reviewer_role", None) or "")
    for ref in (getattr(role, "models", None) or []) if role else []:
        try:
            if attachments.can_see(cfg, str(ref)) and isinstance(cfg.provider(ref.provider), Provider):
                return ref
        except Exception:  # an unknown provider: try the next one
            continue
    return None


def _picture_files(project_root: Path, before_rec: dict[str, Any] | None, after_rec: dict[str, Any] | None,
                   prs: list[dict[str, Any]], limit: int) -> list[tuple[str, Path]]:
    """At most ``limit`` pictures: the most changed pair first, before then after."""
    adir = pictures_dir(project_root, after_rec or {})
    bdir = pictures_dir(project_root, before_rec) if before_rec and before_rec.get("pictures") else None
    ranked = sorted(prs, key=lambda p: (-(p["change"] if p["change"] is not None else 1.0),
                                        PREFERRED.index(p["kind"]) if p["kind"] in PREFERRED else 99))
    out: list[tuple[str, Path]] = []
    for p in ranked:
        small = lambda d, name: (d / (Path(name).stem + ".jpg")) if (d / (Path(name).stem + ".jpg")).is_file() else d / name
        if p["before"] and bdir is not None and len(out) < limit:
            out.append((f"{p['kind']}, before the task", small(bdir, p["before"])))
        if len(out) < limit:
            out.append((f"{p['kind']}, after the task", small(adir, p["after"])))
        if len(out) >= limit:
            break
    return out


def _mime(p: Path) -> str:
    return "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"


def judge(cfg: Any, task: Any, prs: list[dict[str, Any]], tests: dict[str, Any] | None, budget: Any,
          project_root: Path | None = None, before_rec: dict[str, Any] | None = None,
          after_rec: dict[str, Any] | None = None, spent: float = 0.0,
          settings: Settings | None = None) -> dict[str, Any]:
    """One call to a model that can see. Returns {looked, verdict, what_changed, problems, model, cost_usd,
    words, why?}. Never raises; money it would spend past the cap (``max_usd_per_task`` less ``spent``,
    what earlier tries of this task already cost) means it doesn't look."""
    from .. import attachments
    from ..providers.base import ToolSpec, Usage

    s = settings or Settings.from_config(cfg)
    out: dict[str, Any] = {"looked": False, "verdict": None, "what_changed": "", "problems": [], "model": "",
                           "cost_usd": 0.0}
    if not s.judge:
        return {**out, "why": "off", "words": NOBODY + " (the check is off)"}
    if not prs:
        return {**out, "why": "no_pictures", "words": NOBODY + " (there were none)"}
    ref = _seeing_ref(cfg, s)
    if ref is None:
        return {**out, "why": "no_model", "words": NOBODY + " (none of the models can see)"}
    root = Path(project_root or ".")
    cap = s.max_usd_per_task - (spent or 0.0)
    task_text = (f"# Task [{getattr(task, 'id', '')}] {getattr(task, 'title', '')}\n{getattr(task, 'description', '')}\n\n"
                 f"# Acceptance criteria\n{getattr(task, 'acceptance', '') or '(use judgement)'}\n\n")
    changes = "".join(f"- {p['kind']}: {p['words']}\n" for p in prs)
    prompt = (task_text + f"# What the harness measured\n{changes}"
              + (f"{tests['words']}\n" if tests and tests.get("words") else "")
              + "\nDo these pictures show what the task asked for? Call submit_proof with: verdict (shows_it, "
                "does_not or cant_tell), what_changed (one short plain sentence a non-programmer understands, such "
                "as 'the menu is there'), and problems (short plain lines; empty when there are none).")
    files = _picture_files(root, before_rec, after_rec, prs, s.max_pictures)
    while True:  # fewer pictures when all of them would cost more than the cap
        est = cfg.cost(ref, Usage(input_tokens=PICTURE_TOKENS * len(files) + len(prompt) // 3 + 300,
                                  output_tokens=JUDGE_MAX_TOKENS))
        if est is None or est <= cap or len(files) <= 1:
            break
        files = files[:-1]
    if cap <= 0 or (est is not None and est > cap):
        return {**out, "why": "too_dear", "words": NOBODY + f" (looking would cost more than the ${s.max_usd_per_task:.2f} "
                                                              "allowed for each task)"}
    try:
        budget.check()
    except Exception:  # the run's own money limit is reached: don't spend more
        return {**out, "why": "budget", "words": NOBODY + " (the run's money limit is reached)"}
    ptype = attachments.provider_type(cfg, str(ref))
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for label, p in files:
        try:
            content.append({"type": "text", "text": f"Picture: {label}"})
            content.append(attachments.picture_block(ptype, _mime(p), p.read_bytes(), p.name))
        except OSError:
            continue
    spec = ToolSpec("submit_proof", "Record whether the pictures show what the task asked for.", {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "what_changed": {"type": "string", "description": "one short plain sentence"},
            "problems": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["verdict", "what_changed", "problems"],
    })
    try:
        resp = cfg.provider(ref.provider).chat(ref.model, JUDGE_SYSTEM, [{"role": "user", "content": content}],
                                               tools=[spec], max_tokens=JUDGE_MAX_TOKENS, options={})
    except Exception as e:  # the model is away or refused: say so, never fail the task
        return {**out, "model": str(ref), "why": "error", "error": str(e)[:300],
                "words": NOBODY + " (the model that can see didn't answer)"}
    cost = cfg.cost(ref, resp.usage)
    try:
        budget.charge(cost)
    except Exception:  # noqa: BLE001 - charging is bookkeeping
        pass
    out.update(model=str(ref), cost_usd=round(cost or 0.0, 6), pictures=len(files))
    call = next((c for c in resp.tool_calls if c.name == "submit_proof"), None)
    if call is None:
        return {**out, "why": "no_verdict", "words": NOBODY + " (the model gave no verdict)"}
    args = call.arguments or {}
    verdict = str(args.get("verdict") or "").strip()
    out.update(looked=True, verdict=verdict if verdict in VERDICTS else "cant_tell",
               what_changed=str(args.get("what_changed") or "").strip()[:300],
               problems=[str(x).strip()[:300] for x in (args.get("problems") or []) if str(x).strip()][:8])
    out["words"] = judge_words(out)
    return out


def judge_words(j: dict[str, Any] | None) -> str:
    if not j:
        return NOBODY
    if not j.get("looked"):
        return j.get("words") or NOBODY
    what = (j.get("what_changed") or "").rstrip(".")
    if j["verdict"] == "shows_it":
        return "A model that can see checked: " + (what or "it shows what the task asked for")
    if j["verdict"] == "does_not":
        why = (j.get("problems") or [what or "it doesn't show what the task asked for"])[0].rstrip(".")
        return "A model that can see doesn't think it shows: " + why
    return "A model that can see couldn't tell from the pictures"


# -- the record --------------------------------------------------------------------------------
def words_of(record: dict[str, Any]) -> str:
    """The one line the owner reads: what the pictures show, then the tests."""
    parts = []
    if record.get("pairs") or record.get("judge"):
        parts.append(judge_words(record.get("judge")).rstrip(".") + ".")
    t = tests_words(record.get("tests"))
    if t:
        parts.append(t)
    if not parts:
        return "No pictures or tests to show for this task."
    return " ".join(parts)


def _brief(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rec:
        return None
    return {k: rec.get(k) for k in ("task", "dir", "commit", "pictures", "reused", "note", "failed", "errors", "title")
            if k in rec}


def build(project_root: Path, task: Any, before_rec: dict[str, Any] | None, after_rec: dict[str, Any] | None,
          tests: dict[str, Any] | None, judged: dict[str, Any] | None, prs: list[dict[str, Any]] | None = None,
          plan: list[dict[str, Any]] | None = None, ok: bool | None = None) -> dict[str, Any]:
    from ..core.models import utcnow

    rec: dict[str, Any] = {
        "task": getattr(task, "id", str(task)), "title": getattr(task, "title", ""), "at": utcnow(), "ok": ok,
        "before": _brief(before_rec), "after": _brief(after_rec),
        "pairs": prs if prs is not None else pairs(project_root, before_rec, after_rec),
        "tests": tests, "judge": judged,
    }
    rec["words"] = words_of(rec)
    if plan:
        rec["lines"] = lines(plan, rec)
    return rec


def path_for(project_root: Path, task_id: str) -> Path:
    return showit.shots_root(project_root) / showit._safe_task(task_id) / PROOF_FILE


def write(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    p = path_for(project_root, record["task"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def read(project_root: Path, task_id: str) -> dict[str, Any] | None:
    return _load(path_for(project_root, task_id))


def history(project_root: Path, limit: int = 60) -> list[dict[str, Any]]:
    """Every task's proof, newest first."""
    out = []
    for p in showit.shots_root(project_root).glob(f"*/{PROOF_FILE}"):
        rec = _load(p)
        if rec:
            out.append(rec)
    return sorted(out, key=lambda r: r.get("at", ""), reverse=True)[:limit]


def summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The short form for lists, the hub and the phone's Hub mode."""
    if not record:
        return None
    j = record.get("judge") or {}
    return {"task": record.get("task", ""), "at": record.get("at", ""), "words": record.get("words", ""),
            "verdict": j.get("verdict") if j.get("looked") else None,
            "tests": (record.get("tests") or {}).get("words", ""),
            "changed": [{"kind": p["kind"], "words": p["words"]} for p in record.get("pairs") or []],
            "lines": record.get("lines") or []}


def _data_url(p: Path, limit: int = 600_000) -> str | None:
    if not p.is_file() or p.stat().st_size > limit:
        return None
    return f"data:{_mime(p)};base64," + base64.b64encode(p.read_bytes()).decode()


def inline_pictures(project_root: Path, record: dict[str, Any]) -> dict[str, dict[str, str]]:
    """{"before": {kind: data address}, "after": {...}}: the small jpgs where there are some."""
    out: dict[str, dict[str, str]] = {"before": {}, "after": {}}
    for side in ("before", "after"):
        rec = record.get(side) or {}
        if not rec.get("pictures"):
            continue
        d = pictures_dir(project_root, rec)
        for kind in rec["pictures"]:
            url = _data_url(d / f"{kind}.jpg") or _data_url(d / f"{kind}.png")
            if url:
                out[side][kind] = url
    return out


def review_text(record: dict[str, Any] | None, strict: bool = False) -> str:
    """The part of the review prompt: advice, never a verdict of its own (unless ``strict``)."""
    if not record:
        return ""
    lines_ = ["# Proof: the app before and after this task (advice for you)"]
    for p in record.get("pairs") or []:
        lines_.append(f"- {p['kind']} picture: {p['words']}")
    j = record.get("judge") or {}
    if j.get("looked"):
        lines_.append(f"- A model that can see looked at {j.get('pictures', 'the')} picture(s) and says: "
                      f"{j['verdict']}" + (f" – {j['what_changed']}" if j.get("what_changed") else ""))
        for prob in j.get("problems") or []:
            lines_.append(f"  - problem it saw: {prob}")
    elif record.get("pairs"):
        lines_.append(f"- {judge_words(j)}.")
    if (record.get("tests") or {}).get("words"):
        lines_.append(f"- {record['tests']['words']}")
    if strict and j.get("looked") and j.get("verdict") == "does_not":
        lines_.append("The owner has asked for strict proof: don't approve while the pictures don't show the task.")
    else:
        lines_.append("This is advice: check it yourself. Don't reject only because of it.")
    return "\n".join(lines_) + "\n\n"


def estimate_usd(cfg: Any, tasks_with_screens: int) -> float:
    """What the judge may cost at most for this many tasks (for the estimate shown before approving)."""
    s = Settings.from_config(cfg)
    if not s.enabled or not s.judge:
        return 0.0
    return round(s.max_usd_per_task * max(0, int(tasks_with_screens)), 4)


# -- a kind's proof list -----------------------------------------------------------------------
# what Roundtable can check now, for each ``how``; anything else is shown as "not checked yet"
HOWS = {
    "page_opens": "The app opens and its pages show no errors",
    "pictures": "A model that can see checks the pictures show the task",
    "looks": "A model that can see checks the pictures show the task",
    "command": "The project's test command passes",
    "tests": "The project's test command passes",
    "play": "A model that can see plays it for a minute",  # the play results (playtest.py, the done list)
}


def plan_for(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """A kind's proof list as a plan: each item {id, how, words, optional, status, checkable, ...}.

    An item Roundtable can't check yet (an unknown ``how``, or ``status: not_yet``) stays in the plan, so
    the owner sees it, as "not checked yet"; it never counts as passed."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        iid = re.sub(r"[^a-z0-9_-]+", "-", str(raw.get("id") or "").strip().lower()).strip("-")
        how = str(raw.get("how") or "").strip().lower()
        if not iid or iid in seen:
            continue
        seen.add(iid)
        status = str(raw.get("status") or "").strip().lower() or "on"
        item = {"id": iid, "how": how, "words": str(raw.get("words") or HOWS.get(how) or iid)[:200],
                "optional": bool(raw.get("optional")), "status": status,
                "checkable": how in HOWS and status != "not_yet"}
        for k in ("command", "seconds"):
            if k in raw:
                item[k] = raw[k]
        out.append(item)
    return out


def _passed(item: dict[str, Any], record: dict[str, Any]) -> bool | None:
    if not item.get("checkable"):
        return None
    how = item["how"]
    if how == "page_opens":
        after = record.get("after") or {}
        if not after.get("pictures"):
            return None if not after else False
        return not (after.get("errors") or after.get("failed"))
    if how in ("pictures", "looks"):
        j = record.get("judge") or {}
        return None if not j.get("looked") or j.get("verdict") == "cant_tell" else j["verdict"] == "shows_it"
    if how in ("command", "tests"):
        t = record.get("tests") or {}
        if not t.get("after"):
            return None
        if item.get("command") and t.get("command") and str(item["command"]).strip() != str(t["command"]).strip():
            return None  # a different command than the project's own: not checked here
        return t.get("verdict") in ("pass", "old_only") if t.get("verdict") else bool(t["after"].get("ok"))
    return None


def lines(plan: list[dict[str, Any]] | None, record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Proof lines {id, passed (True, False or None: not checked), words, optional} for a record."""
    rec = record or {}
    return [{"id": it["id"], "passed": _passed(it, rec), "words": it["words"], "optional": it.get("optional", False),
             "checkable": bool(it.get("checkable"))} for it in plan or []]


def all_passed(proof_lines: list[dict[str, Any]]) -> bool:
    """Every item Roundtable can check that isn't optional passed (what makes a kind "proven"). Items it
    can't check yet (``status: not_yet``, an unknown ``how``) don't count either way."""
    must = [ln for ln in proof_lines if not ln.get("optional") and ln.get("checkable", True)]
    return bool(must) and all(ln.get("passed") is True for ln in must)


def lines_text(proof_lines: list[dict[str, Any]]) -> str:
    """"Opens with no errors ✓ · Tests pass ✓ · Played for a minute – not checked yet"."""
    marks = {True: " ✓", False: " ✗"}
    return " · ".join(ln["words"] + marks.get(ln.get("passed"), " – not checked yet") for ln in proof_lines)


def _play_passed(project_root: Path, item: dict[str, Any]) -> bool | None:
    """A ``play`` check's answer: the done list's record for it (``kind_id``), else the newest play.json
    written for it (harness/playtest.py). None: it wasn't played, or the play couldn't say."""
    try:
        from . import donelist

        for i in donelist.read(project_root)["items"]:
            if i.get("kind_id") == item["id"] and i.get("state") in ("passed", "failed"):
                return i["state"] == "passed"
        recs = sorted(Path(project_root, ".harness", "play").glob(f"*/{item['id']}/play.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for p in recs:
            got = json.loads(p.read_text(encoding="utf-8")).get("passed")
            if got is not None:
                return bool(got)
    except Exception:  # noqa: BLE001 - unreadable: not checked
        return None
    return None


def results_for(project_root: Path, items: list[dict[str, Any]] | None, tasks: list[Any]) -> list[dict[str, Any]] | None:
    """A kind's proof list checked against the proof of a goal's tasks (the Gallery's proof lines).

    Each item takes the newest task's answer that isn't "not checked". None when none of the tasks has a
    proof record, so the caller falls back to what it can see itself."""
    plan = plan_for(items)
    ids = {getattr(t, "id", t) for t in tasks or []}
    records = [r for r in history(project_root, limit=500) if r.get("task") in ids]
    if not plan or not records:
        return None
    out = []
    for it in plan:
        passed = _play_passed(project_root, it) if it.get("how") == "play" and it.get("checkable") else None
        for rec in records if passed is None else []:  # newest first
            got = _passed(it, rec)
            if got is not None:
                passed = got
                break
        out.append({"id": it["id"], "words": it["words"], "passed": passed, "optional": it.get("optional", False),
                    "status": it.get("status", "on"), "checkable": bool(it.get("checkable"))})
    return out
