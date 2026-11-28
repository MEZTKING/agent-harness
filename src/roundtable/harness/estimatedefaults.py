"""The estimate's defaults from real runs (wave 9, w9-gaps).

With no history for a job, the estimate used to guess 60,000 tokens in and 8,000 out for every attempt
(``plandoc.DEFAULT_TOKENS``). Here the guess comes from every finished attempt on this computer instead: each
project's ``.harness/metrics.jsonl``, by job (the role) and by the task's planned size (``.harness/stages.json``
``sizes``), as the median with the spread kept (the quarter and three-quarter marks). Fewer than ``MIN_ROWS``
rows and the fixed figures stand, said as such.

After each run the estimate and the real cost are written side by side (``.harness/estimate-vs-real.jsonl``),
and a drift past a quarter gives one plain line for What it learned (``after_run``).

Nothing here calls a model or the network.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

FALLBACK = (60_000, 8_000)  # plandoc.DEFAULT_TOKENS["chat"]: the figures used below MIN_ROWS
MIN_ROWS = 10
DRIFT = 0.25
COMPARE_FILE = "estimate-vs-real.jsonl"
SKIP_OUTCOMES = {"owner_feedback"}


def _jsonl(p: Path) -> list[dict[str, Any]]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _sizes(metrics_file: Path) -> dict[str, str]:
    """The planned sizes of a project's tasks ({task id: small|medium|large}), next to its metrics file."""
    try:
        data = json.loads((metrics_file.parent / "stages.json").read_text(encoding="utf-8"))
        sizes = data.get("sizes") or {}
        return {str(k): str(v) for k, v in sizes.items()} if isinstance(sizes, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def rows(metric_files: Iterable[Path | str]) -> list[dict[str, Any]]:
    """Every real attempt that used tokens: {role, size, input, output}; pictures and sounds (no tokens) left out."""
    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for f in metric_files:
        p = Path(f)
        try:
            key = p.resolve()
        except OSError:
            continue
        if key in seen or not p.is_file():
            continue
        seen.add(key)
        sizes = _sizes(p)
        for d in _jsonl(p):
            if d.get("outcome") in SKIP_OUTCOMES or not d.get("role"):
                continue
            try:
                i, o = int(d.get("input_tokens") or 0), int(d.get("output_tokens") or 0)
            except (TypeError, ValueError):
                continue
            if i <= 0:
                continue
            out.append({"role": str(d["role"]), "size": sizes.get(str(d.get("task") or ""), ""), "input": i,
                        "output": o})
    return out


def lab_metric_files(project_dir: Path | str | None, lab_dir: Path | str | None) -> list[Path]:
    """This project's metrics and every lab project's on this computer (what ``for_role`` reads)."""
    files: list[Path] = []
    if project_dir:
        files.append(Path(project_dir) / "metrics.jsonl")
    if lab_dir and Path(lab_dir).is_dir():
        for p in sorted(Path(lab_dir).iterdir()):
            if (p / ".harness" / "metrics.jsonl").is_file():
                files.append(p / ".harness" / "metrics.jsonl")
    return files


def _quartiles(xs: list[int]) -> tuple[int, int]:
    if len(xs) < 2:
        return (xs[0], xs[0]) if xs else (0, 0)
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return int(q[0]), int(q[2])


def _summary(rs: list[dict[str, Any]], basis: str) -> dict[str, Any]:
    ins, outs = [r["input"] for r in rs], [r["output"] for r in rs]
    return {"input": int(statistics.median(ins)), "output": int(statistics.median(outs)), "basis": basis,
            "samples": len(rs), "spread": {"input": _quartiles(ins), "output": _quartiles(outs)}}


def for_role(metric_files: Iterable[Path | str] | None, role: str, size: str = "",
             found: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Tokens one attempt of ``role`` is expected to use: {input, output, basis, samples, spread, words}.

    The most specific group with at least MIN_ROWS rows wins: this job at this size, this job, every job; else
    the fixed FALLBACK (basis ``fixed``). ``found``: rows already read (``rows``), so a whole plan reads once."""
    rs = found if found is not None else rows(metric_files or [])
    groups = []
    if size:
        groups.append(([r for r in rs if r["role"] == role and r["size"] == size], f"{role}, {size} tasks"))
    groups.append(([r for r in rs if r["role"] == role], role))
    groups.append((rs, "every job"))
    for group, basis in groups:
        if len(group) >= MIN_ROWS:
            s = _summary(group, basis)
            s["words"] = (f"From {s['samples']} real attempts ({basis}): about {s['input']:,} tokens in and "
                          f"{s['output']:,} out each.")
            return s
    return {"input": FALLBACK[0], "output": FALLBACK[1], "basis": "fixed", "samples": len(rs),
            "spread": None,
            "words": f"Fewer than {MIN_ROWS} real attempts on this computer yet: a guess of {FALLBACK[0]:,} tokens "
                     f"in and {FALLBACK[1]:,} out each."}


def tokens(metric_files: Iterable[Path | str] | None, role: str, size: str = "",
           found: list[dict[str, Any]] | None = None) -> tuple[int, int]:
    """(input, output) for one attempt: what plandoc.estimate reads in place of DEFAULT_TOKENS["chat"]."""
    d = for_role(metric_files, role, size, found)
    return d["input"], d["output"]


# -- after a run: the estimate beside the real cost ------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def drift(estimate_usd: float | None, real_usd: float | None) -> float | None:
    """(real - estimate) / estimate, or None when either is unknown or the estimate was nothing."""
    if estimate_usd is None or real_usd is None or estimate_usd <= 0:
        return None
    return (real_usd - estimate_usd) / estimate_usd


def after_run(project_dir: Path | str, estimate_usd: float | None, real_usd: float | None,
              project: str = "", now: str | None = None) -> dict[str, Any]:
    """Write the estimate and the real cost side by side; {row, line}: ``line`` is one sentence for What it
    learned when the real cost drifted more than a quarter from the estimate, else ''."""
    d = drift(estimate_usd, real_usd)
    row = {"at": now or _now(), "project": project, "estimate_usd": None if estimate_usd is None else round(estimate_usd, 4),
           "real_usd": None if real_usd is None else round(real_usd, 4),
           "drift": None if d is None else round(d, 3)}
    p = Path(project_dir) / COMPARE_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass
    line = ""
    if d is not None and abs(d) > DRIFT:
        name = f"{project}: " if project else ""
        way = "more" if d > 0 else "less"
        line = (f"{name}the run cost ${real_usd:.2f}, {abs(d) * 100:.0f}% {way} than the estimate of "
                f"${estimate_usd:.2f}. Later estimates use the real figures.")
    return {"row": row, "line": line}


def history(project_dir: Path | str) -> list[dict[str, Any]]:
    """Every run's estimate beside its real cost, oldest first."""
    return _jsonl(Path(project_dir) / COMPARE_FILE)
