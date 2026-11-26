"""Model health probes: a quick regression / boost detector.

Runs a small suite of cheap checks with automatic grading (no LLM judge)
against every model in the config, and compares each model with its own
recent history:

    DOWN        every probe failed with a provider error
    REGRESSION  a probe the model reliably passed now fails, or the score dropped
    BOOST       a probe the model reliably failed now passes, or the score rose
    SLOW/FAST   latency at least 2x / at most 0.5x its usual
    VERBOSE     output tokens at least 2x its usual
    NEW         no history yet: this run becomes the baseline
    OK          nothing unusual

Use it before big changes (``roundtable improve apply/cycle`` run it on the
models involved), after a provider announces a model update, or on a
schedule to catch silent changes.

Add your own probes in ``improve.probes_file`` (YAML list):
    - name: haiku_format
      prompt: "Write a haiku about rain. Output only the three lines."
      expect_regex: "^[^\\n]+\\n[^\\n]+\\n[^\\n]+$"
    - name: capital
      prompt: "What is the capital of Australia? One word."
      expect_contains: "Canberra"
"""

from __future__ import annotations

import json
import re
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.models import new_id, utcnow
from ..harness.agent import Budget, BudgetExceeded, run_agent
from ..harness.config import HarnessConfig, ModelRef
from ..harness.tools import Tool, Toolbox, Workspace, _obj
from ..providers.base import ImageProvider, Provider, ProviderError, ToolSpec

HISTORY_RUNS = 5  # baseline = median of this many previous runs per model
RELIABLE = 0.8  # "reliably passes/fails" = in at least 80% of baseline runs


@dataclass
class ProbeResult:
    model: str
    probe: str
    passed: bool
    seconds: float
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str = ""
    detail: str = ""


@dataclass
class ModelReport:
    model: str
    status: list[str] = field(default_factory=list)
    score: float = 0.0
    passed: int = 0
    total: int = 0
    seconds: float = 0.0
    output_tokens: int = 0
    cost_usd: float = 0.0
    baseline_score: float | None = None
    baseline_seconds: float | None = None
    baseline_tokens: float | None = None
    notes: list[str] = field(default_factory=list)
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def bad(self) -> bool:
        return "DOWN" in self.status or "REGRESSION" in self.status


# -- built-in chat probes ----------------------------------------------------------
def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return (m.group(1) if m else t).strip()


def probe_tool_use(cfg, ref, budget):
    seen: list[dict] = []

    def add(a: dict) -> str:
        seen.append(a)
        return str(int(a["a"]) + int(a["b"]))

    box = Toolbox()
    box.add(Tool(ToolSpec("add", "Add two integers.", _obj({"a": {"type": "integer"}, "b": {"type": "integer"}},
                                                             ["a", "b"])), add))
    res = run_agent(cfg, ref, "You are a precise assistant.",
                    "Use the add tool to compute 1234 + 5678, then reply with only the resulting number.",
                    box, budget, max_steps=4, max_tokens=2000)
    called = any({int(c.get("a", 0)), int(c.get("b", 0))} == {1234, 5678} for c in seen)
    ok = called and "6912" in res.text
    return ok, res, f"tool called={called}, answer={res.text[:60]!r}"


def probe_json(cfg, ref, budget):
    res = run_agent(cfg, ref, "You extract data.",
                    'From this sentence, output ONLY a JSON object with keys "name" (string), "age" (integer) '
                    'and "city" (string): "Last spring, 34-year-old Maria Lopez moved from Lima to Porto."',
                    Toolbox(), budget, max_steps=1, max_tokens=2000)
    try:
        data = json.loads(_strip_fences(res.text))
        ok = data == {"name": "Maria Lopez", "age": 34, "city": "Porto"}
    except json.JSONDecodeError:
        data, ok = None, False
    return ok, res, f"got {str(data)[:80] if data is not None else res.text[:80]!r}"


def probe_instructions(cfg, ref, budget):
    res = run_agent(cfg, ref, "Follow formatting instructions exactly.",
                    "Write exactly three lines and nothing else. Each line is 'OK-' followed by one digit. "
                    "The digits must be strictly increasing.",
                    Toolbox(), budget, max_steps=1, max_tokens=2000)
    lines = res.text.strip().splitlines()
    ok = (len(lines) == 3 and all(re.fullmatch(r"OK-\d", ln.strip()) for ln in lines)
          and int(lines[0].strip()[-1]) < int(lines[1].strip()[-1]) < int(lines[2].strip()[-1]))
    return ok, res, f"got {res.text.strip()[:60]!r}"


def probe_reasoning(cfg, ref, budget):
    res = run_agent(cfg, ref, "Solve carefully.",
                    "Pencils cost $1.20 for a pack of 3, or $0.45 each when bought singly. What is the lowest "
                    "price for exactly 17 pencils? End your reply with a final line 'ANSWER: <dollars>'.",
                    Toolbox(), budget, max_steps=1, max_tokens=4000)
    m = re.search(r"ANSWER:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", res.text)
    ok = bool(m) and abs(float(m.group(1)) - 6.90) < 0.001
    return ok, res, f"answer={m.group(1) if m else None}"


BUGGY = '''def median(values):
    """Return the median of a non-empty list of numbers."""
    s = sorted(values)
    return s[len(s) // 2]
'''
def _grade_median(path: Path) -> tuple[bool, str]:
    """Load the model's stats.py in-process and check median().

    Runs inside this process (not `sys.executable -c ...`): in the packaged desktop
    app sys.executable is the app itself, not a Python interpreter.
    """
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(f"probe_stats_{id(path)}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cases = [([3, 1, 2], 2), ([4, 1, 3, 2], 2.5), ([5], 5), ([1.5, 2.5], 2.0)]
        for values, want in cases:
            got = mod.median(list(values))
            if got != want:
                return False, f"median({values}) returned {got!r}, expected {want!r}"
        return True, "tests pass"
    except Exception as e:  # the model's code can fail in any way
        return False, f"{type(e).__name__}: {e}"[:100]


def probe_code_fix(cfg, ref, budget):
    with tempfile.TemporaryDirectory(prefix="harness-probe-") as d:
        ws = Workspace(d, allow_shell=False)
        (Path(d) / "stats.py").write_text(BUGGY, encoding="utf-8")
        box = ws.toolbox(["read_file", "edit_file", "write_file", "list_files"])
        box.add(Tool(ToolSpec("finish_task", "Call when done.", _obj({"summary": {"type": "string"}}, ["summary"])),
                     lambda a: "ok", terminal=True))
        res = run_agent(cfg, ref, "You are a software engineer. Use your tools to edit files.",
                        "stats.py has a bug: median() is wrong for even-length lists (it must return the mean of the "
                        "two middle values). Fix it in the file, then call finish_task.",
                        box, budget, max_steps=8, max_tokens=4000, require_terminal="finish_task")
        ok, detail = _grade_median(Path(d) / "stats.py")
        return ok, res, detail


BUILTIN: dict[str, Callable] = {
    "tool_use": probe_tool_use,
    "json": probe_json,
    "instructions": probe_instructions,
    "reasoning": probe_reasoning,
    "code_fix": probe_code_fix,
}


def _custom_probe(spec: dict[str, Any]) -> Callable:
    def run(cfg, ref, budget):
        res = run_agent(cfg, ref, spec.get("system", "You are a helpful assistant."), spec["prompt"], Toolbox(),
                        budget, max_steps=1, max_tokens=int(spec.get("max_tokens", 2000)))
        text = res.text.strip()
        if "expect_exact" in spec:
            ok = text == str(spec["expect_exact"]).strip()
        elif "expect_regex" in spec:
            ok = re.search(spec["expect_regex"], text, re.S) is not None
        elif "expect_contains" in spec:
            ok = str(spec["expect_contains"]).lower() in text.lower()
        elif "expect_json" in spec:
            try:
                ok = json.loads(_strip_fences(text)) == spec["expect_json"]
            except json.JSONDecodeError:
                ok = False
        else:
            raise ValueError(f"probe {spec.get('name')!r} needs expect_exact/regex/contains/json")
        return ok, res, f"got {text[:60]!r}"

    return run


def load_probes(cfg: HarnessConfig) -> dict[str, Callable]:
    probes = dict(BUILTIN)
    pf = cfg.improve.get("probes_file")
    if pf:
        path = Path(pf) if Path(pf).is_absolute() else (cfg.path.parent if cfg.path else Path.cwd()) / pf
        for spec in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if "name" not in spec or "prompt" not in spec:
                raise ValueError(f"{path}: each probe needs a name and a prompt")
            probes[spec["name"]] = _custom_probe(spec)
    return probes


# -- image probe ---------------------------------------------------------------------
def _image_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:4] == b"GIF8" and len(data) >= 10:
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    return None


def probe_image(cfg: HarnessConfig, ref: ModelRef, provider: ImageProvider, generate: bool) -> ProbeResult:
    t0 = time.monotonic()
    try:
        if not generate:
            if hasattr(provider, "check_cost"):
                price = provider.check_cost(ref.model, "a small red apple", {"width": 64, "height": 64})
                return ProbeResult(str(ref), "image_api", True, round(time.monotonic() - t0, 2),
                                   detail=f"API reachable (free price check: ${price:.3f}/image)")
            return ProbeResult(str(ref), "image_api", True, 0.0, detail="skipped (no free check; use --images)")
        data, ext, usage = provider.generate(ref.model, "a small red apple, centered", {"width": 64, "height": 64})
        size = _image_size(data)
        cost = cfg.cost(ref, usage) or 0.0
        return ProbeResult(str(ref), "image_generate", size is not None, round(time.monotonic() - t0, 2),
                           cost_usd=cost, detail=f"{ext} {size}")
    except ProviderError as e:
        return ProbeResult(str(ref), "image_generate" if generate else "image_api", False,
                           round(time.monotonic() - t0, 2), error=str(e)[:300])


# -- running and comparing ---------------------------------------------------------------
def models_in_config(cfg: HarnessConfig, roles: list[str] | None = None) -> tuple[list[ModelRef], list[ModelRef]]:
    chat, image, seen = [], [], set()
    for r in cfg.roles.values():
        if roles and r.name not in roles:
            continue
        for m in r.models:
            if str(m) in seen:
                continue
            seen.add(str(m))
            (image if r.kind == "image" else chat).append(m)
    return chat, image


def run_probes(cfg: HarnessConfig, models: list[ModelRef], image_models: list[ModelRef] | None = None,
               only: list[str] | None = None, generate_images: bool = False, max_cost: float = 1.0,
               on_result: Callable[[ProbeResult], None] | None = None) -> list[ProbeResult]:
    probes = load_probes(cfg)
    if only:
        unknown = set(only) - set(probes)
        if unknown:
            raise ValueError(f"unknown probe(s) {sorted(unknown)}; available: {sorted(probes)}")
        probes = {k: v for k, v in probes.items() if k in only}
    budget = Budget(max_cost)
    out: list[ProbeResult] = []
    for ref in models:
        if not isinstance(cfg.provider(ref.provider), Provider):
            continue
        for name, fn in probes.items():
            spent0, t0 = budget.spent_usd, time.monotonic()
            try:
                ok, res, detail = fn(cfg, ref, budget)
                r = ProbeResult(str(ref), name, bool(ok), round(time.monotonic() - t0, 2),
                                res.usage.output_tokens, round(budget.spent_usd - spent0, 6), detail=detail)
            except BudgetExceeded:
                raise
            except ProviderError as e:
                r = ProbeResult(str(ref), name, False, round(time.monotonic() - t0, 2), error=str(e)[:300])
            except Exception as e:  # a probe crashing is a failure, not a harness crash
                r = ProbeResult(str(ref), name, False, round(time.monotonic() - t0, 2), error=f"{type(e).__name__}: {e}"[:300])
            out.append(r)
            if on_result:
                on_result(r)
    for ref in image_models or []:
        provider = cfg.provider(ref.provider)
        if isinstance(provider, ImageProvider):
            r = probe_image(cfg, ref, provider, generate_images)
            out.append(r)
            if on_result:
                on_result(r)
    return out


def _history(lab_root: Path) -> list[dict[str, Any]]:
    p = lab_root / "probes.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def compare(results: list[ProbeResult], history: list[dict[str, Any]]) -> list[ModelReport]:
    reports: dict[str, ModelReport] = {}
    for r in results:
        rep = reports.setdefault(r.model, ModelReport(r.model))
        rep.results.append(r)
        rep.total += 1
        rep.passed += r.passed
        rep.seconds += r.seconds
        rep.output_tokens += r.output_tokens
        rep.cost_usd += r.cost_usd

    for model, rep in reports.items():
        rep.score = rep.passed / rep.total if rep.total else 0.0
        if rep.results and all(r.error for r in rep.results):
            rep.status.append("DOWN")
            rep.notes.append(rep.results[0].error)
            continue
        probe_names = {r.probe for r in rep.results}
        past = [h for h in history if h["model"] == model and h["probe"] in probe_names and not h.get("error")]
        runs: dict[str, list[dict]] = {}
        for h in past:
            runs.setdefault(h["run"], []).append(h)
        recent = sorted(runs.values(), key=lambda rs: rs[0]["at"])[-HISTORY_RUNS:]
        if not recent:
            rep.status.append("NEW")
            continue
        rep.baseline_score = statistics.median(sum(x["passed"] for x in rs) / len(rs) for rs in recent)
        rep.baseline_seconds = statistics.median(sum(x["seconds"] for x in rs) for rs in recent)
        rep.baseline_tokens = statistics.median(sum(x["output_tokens"] for x in rs) for rs in recent)

        for r in rep.results:
            hist = [x["passed"] for rs in recent for x in rs if x["probe"] == r.probe]
            if len(hist) < 2:
                continue
            rate = sum(hist) / len(hist)
            if rate >= RELIABLE and not r.passed:
                rep.notes.append(f"{r.probe}: usually passes ({rate:.0%}), failed now ({r.error or r.detail})")
                if "REGRESSION" not in rep.status:
                    rep.status.append("REGRESSION")
            elif rate <= 1 - RELIABLE and r.passed:
                rep.notes.append(f"{r.probe}: usually fails ({rate:.0%}), passed now")
                if "BOOST" not in rep.status:
                    rep.status.append("BOOST")
        if rep.score <= rep.baseline_score - 0.2 and "REGRESSION" not in rep.status:
            rep.status.append("REGRESSION")
            rep.notes.append(f"score {rep.score:.0%} vs usual {rep.baseline_score:.0%}")
        if rep.score >= rep.baseline_score + 0.2 and "BOOST" not in rep.status:
            rep.status.append("BOOST")
            rep.notes.append(f"score {rep.score:.0%} vs usual {rep.baseline_score:.0%}")
        if rep.baseline_seconds and rep.seconds >= 2 * rep.baseline_seconds and rep.seconds - rep.baseline_seconds > 5:
            rep.status.append("SLOW")
        elif rep.baseline_seconds and rep.seconds <= 0.5 * rep.baseline_seconds and rep.baseline_seconds - rep.seconds > 5:
            rep.status.append("FAST")
        if rep.baseline_tokens and rep.output_tokens >= 2 * rep.baseline_tokens and rep.output_tokens > 200:
            rep.status.append("VERBOSE")
        if not rep.status:
            rep.status.append("OK")
    return list(reports.values())


def record(lab_root: Path, results: list[ProbeResult]) -> str:
    run_id = new_id()
    lab_root.mkdir(parents=True, exist_ok=True)
    at = utcnow()
    with open(lab_root / "probes.jsonl", "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({"run": run_id, "at": at, **asdict(r)}, ensure_ascii=False) + "\n")
    return run_id


def check(cfg: HarnessConfig, lab_root: Path, models: list[ModelRef], image_models: list[ModelRef] | None = None,
          only: list[str] | None = None, generate_images: bool = False, max_cost: float = 1.0, save: bool = True,
          on_result: Callable[[ProbeResult], None] | None = None) -> list[ModelReport]:
    """Run probes, compare with history, then record this run."""
    history = _history(lab_root)
    results = run_probes(cfg, models, image_models, only, generate_images, max_cost, on_result)
    reports = compare(results, history)
    if save:
        record(lab_root, results)
    return reports


def models_for_proposal(cfg: HarnessConfig, proposal) -> list[ModelRef]:
    if proposal.kind == "routing":
        return [ModelRef.parse(m) for m in proposal.change["models"]]
    return list(cfg.roles[proposal.role].models)
