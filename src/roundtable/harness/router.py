"""The router: each task goes to the model that wins its kind of work, and a few easy tasks try untried models
(wave 6, "every model at once").

How it works:

- Every task has tags (tasktags.py): the planner's work words, its files' languages and the project's kind.
  They go into each metrics row (``_tags_metric``), so the lab learns who wins what.
- Before a task is built, ``_route_models`` scores each model the role could use (its own chain and
  ``router.pool[<role>]``, every one through ``_may_use``) by its smoothed win rate on those tags,
  (approved+1)/(judged+2), over every project the lab knows (numbers only). A model moves to the front only
  with at least ``router.min_samples`` (5) judged tries on those tags and a lead of ``router.margin`` (0.15)
  over the role's usual first model. Ties go to the lower cost per finished task. No model is dropped: the
  usual chain stays behind it.
- Where the dial says so (``dial.for_task(...)["explore"]``) and the task is neither hard nor risky, a pool
  model with too few tries goes first, the usual chain behind it. At most ``router.explore.share`` (0.1) of a
  goal's tasks and ``router.explore.max_usd_per_goal`` ($0.50), one at a time, only a priced model costing no
  more than 1.5 times the usual one, and never an untried maker in a project kept to some services or makers,
  or in one of the owner's own repositories. Which tasks try is decided by a hash of the goal and task id.
- At "lean" (plans made before 1.2.0) nothing here does anything.

Settings (harness.yaml)::

    router:
      pool: {coder: [openrouter/google/gemini-x, ...]}
      min_samples: 5
      margin: 0.15
      explore: {share: 0.1, max_usd_per_goal: 0.5}
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from . import dial, makers, tasktags
from .config import ModelRef, section

STATE = Path(".harness") / "router.json"
DEFAULTS = {"min_samples": 5, "margin": 0.15, "share": 0.1, "max_usd_per_goal": 0.5, "max_price_ratio": 1.5}


def _hash(*parts: Any) -> float:
    """A number in [0, 1) from the parts: the same task in the same goal always gets the same one."""
    raw = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8]
    return int(raw, 16) / 2 ** 32


class Score:
    """A model's record on one task's tags, summed over the tags (so weighted by samples)."""

    def __init__(self) -> None:
        self.approved = 0
        self.judged = 0
        self.cost = 0.0
        self.priced = 0
        self.attempts = 0
        self.best: tuple[int, int, str] = (0, 0, "")  # (judged, approved, tag) of the tag with most tries

    @property
    def value(self) -> float:
        return (self.approved + 1) / (self.judged + 2)

    @property
    def cost_per_success(self) -> float:
        if not self.priced or not self.approved:
            return math.inf
        return self.cost / self.priced * self.attempts / self.approved


class RouterStage:
    """A mixin for the Orchestrator: tags in the plan and the metrics, a model chosen per task, exploring."""

    # -- settings and history ------------------------------------------------------------------------
    def _router_conf(self) -> dict[str, Any]:
        raw = section(self.cfg, "router")
        explore = dict(raw.get("explore") or {})

        def num(v: Any, default: float) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        return {
            "pool": {str(k): [str(m) for m in (v or [])] for k, v in dict(raw.get("pool") or {}).items()},
            "min_samples": int(num(raw.get("min_samples"), DEFAULTS["min_samples"])),
            "margin": num(raw.get("margin"), DEFAULTS["margin"]),
            "share": max(0.0, min(1.0, num(explore.get("share"), DEFAULTS["share"]))),
            "max_usd_per_goal": max(0.0, num(explore.get("max_usd_per_goal"), DEFAULTS["max_usd_per_goal"])),
            "max_price_ratio": num(explore.get("max_price_ratio"), DEFAULTS["max_price_ratio"]),
        }

    def _router_files(self) -> list[Path]:
        """This project's metrics and those of every project the lab knows (numbers only)."""
        files = [self.project.dir / "metrics.jsonl"]
        if getattr(self.cfg, "lab_dir", None):
            try:
                from ..improve.lab import Lab

                files += [p / ".harness" / "metrics.jsonl" for p in Lab(self.cfg.lab_dir).projects()]
            except Exception:  # noqa: BLE001 - history is a help
                pass
        seen, out = set(), []
        for f in files:
            try:
                key = f.resolve()
            except OSError:
                continue
            if key not in seen and f.is_file():
                seen.add(key)
                out.append(f)
        return out

    def _router_history(self) -> dict:
        """(role, model, tag) -> stats, read again only when a metrics file changed."""
        from ..improve.analysis import tag_stats

        files = self._router_files()
        sig = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
        cache = self.__dict__.get("_router_cache")
        if cache and cache[0] == sig:
            return cache[1]
        got = tag_stats(files)
        self.__dict__["_router_cache"] = (sig, got)
        return got

    def _router_score(self, history: dict, role: str, ref: Any, tags: list[str]) -> Score:
        sc = Score()
        for tag in tags:
            s = history.get((role, str(ref), tag))
            if s is None:
                continue
            sc.approved += s.approved
            sc.judged += s.judged
            sc.cost += s.cost
            sc.priced += s.priced_attempts
            sc.attempts += s.attempts
            if s.judged > sc.best[0]:
                sc.best = (s.judged, s.approved, tag)
        return sc

    def _router_state(self) -> dict[str, Any]:
        p = self.project.root / STATE
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def _router_save(self, state: dict[str, Any]) -> None:
        p = self.project.root / STATE
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state, indent=1), encoding="utf-8")
        except OSError:  # bookkeeping: never stops a run
            pass

    def _router_live(self) -> dict[str, Any]:
        live = self.__dict__.get("_router_live_state")
        if live is None:
            live = {"routes": {}, "exploring": {}}
            self.__dict__["_router_live_state"] = live
        return live

    # -- which models may be candidates ----------------------------------------------------------------
    def _router_restricted(self) -> bool:
        """Kept to some services or makers, or one of the owner's own repositories: no untried makers."""
        try:
            values = self.project_settings().values
        except Exception:  # noqa: BLE001 - a settings mistake: the careful answer
            return True
        if makers._names(values, "providers_allowed") or makers._names(values, "makers_allowed"):
            return True
        try:
            return bool(self._repo_mode())
        except Exception:  # noqa: BLE001
            return False

    def _router_own_makers(self) -> set[str]:
        return {makers.maker(m) for r in self.cfg.roles.values() for m in r.models}

    def _router_pool(self, role_name: str, conf: dict[str, Any]) -> list[ModelRef]:
        out = []
        for raw in conf["pool"].get(role_name, []):
            try:
                ref = ModelRef.parse(raw)
            except ValueError:
                continue
            if ref.provider in (self.cfg.providers or {}):
                out.append(ref)
        if out and self._router_restricted():
            own = self._router_own_makers()
            out = [r for r in out if makers.maker(r) in own]
        return out

    def _router_candidates(self, role_name: str, models: list[ModelRef], conf: dict[str, Any]) -> list[ModelRef]:
        seen, out = set(), []
        for ref in list(models) + self._router_pool(role_name, conf):
            if str(ref) in seen:
                continue
            seen.add(str(ref))
            if self._may_use(ref) and not self._blocked(ref):
                out.append(ref)
        return out

    # -- the plan: tags, hard and risky ----------------------------------------------------------------
    def _tags_plan_part(self) -> str:
        return "" if dial.level_for_new_plan(self) == "lean" else tasktags.PLAN_WORDS

    def _tags_trim(self, tasks: list[Any]) -> None:
        """A plan that marks more than a quarter hard keeps the mark on the first quarter (hook-up: in plan(),
        straight after the plan call). The warning goes into the document with ``_tags_doc``."""
        warn = tasktags.trim_hard(tasks)
        if warn:
            self.__dict__["_tags_warning"] = warn

    def _tags_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        """The trimmed-plan warning in ``doc["warnings"]``. When ``_tags_trim`` was not called on the new tasks,
        the goal's saved tasks are trimmed here."""
        warn = self.__dict__.pop("_tags_warning", None)
        if warn is None:
            gi = doc.get("goal_index", 0)
            saved = self.project.tasks()
            mine = [t for t in saved if t.goal_index == gi and t.status == "pending"]
            warn = tasktags.trim_hard(mine)
            if warn:
                self.project.save_tasks(saved)
        kept = [w for w in doc.get("warnings") or [] if not (isinstance(w, dict) and w.get("by") == "tags")]
        if warn:
            kept.append(warn)
        if kept:
            doc["warnings"] = kept
        else:
            doc.pop("warnings", None)

    def _tags_metric(self, task: Any, ref: Any) -> dict[str, Any]:
        if dial.level(self) == "lean":
            return {}
        return {"tags": tasktags.for_task(self, task), "hard": bool(task.hard), "risky": bool(task.risky)}

    # -- choosing the model ------------------------------------------------------------------------------
    def _route_models(self, task: Any, role: Any, models: list[ModelRef]) -> list[ModelRef] | None:
        if dial.level(self) == "lean" or getattr(role, "kind", "chat") != "chat" or not models:
            return None
        conf = self._router_conf()
        tags = tasktags.for_task(self, task)
        candidates = self._router_candidates(role.name, models, conf)
        if not candidates:
            return None
        history = self._router_history() if tags else {}
        first = models[0]
        picked, why = None, ""
        if tags:
            base = self._router_score(history, role.name, first, tags).value
            best: tuple[float, float, Any, Score] | None = None
            for ref in candidates:
                if str(ref) == str(first):
                    continue
                sc = self._router_score(history, role.name, ref, tags)
                if sc.judged < conf["min_samples"] or sc.value < base + conf["margin"] - 1e-9:
                    continue
                key = (round(sc.value, 9), -sc.cost_per_success)
                if best is None or key > (best[0], best[1]):
                    best = (key[0], key[1], ref, sc)
            if best is not None:
                picked, sc = best[2], best[3]
                judged, approved, tag = sc.best
                why = f"wins {approved} of {judged} {tasktags.words(tag)} tasks"
        explore = False
        if picked is None:
            picked = self._router_explore(task, role, models, candidates, history, tags, conf)
            if picked is not None:
                explore, why = True, "trying a newer model on a small task; the usual one stands behind it"
        if picked is None:
            return None
        order = [picked] + [m for m in models if str(m) != str(picked)]
        with self._lock:
            self._router_live()["routes"][task.id] = {"model": str(picked), "from": str(first), "why": why,
                                                     "explore": explore}
        self.emit("routed", {"task": task.id, "model": str(picked), "from": str(first), "why": why,
                             "explore": explore})
        return order

    def _router_attempt(self, task: Any, ref: Any) -> dict[str, Any]:
        r = self._router_live()["routes"].get(task.id)
        if not r or str(ref) != r["model"]:
            return {}
        out = {"from": r["from"], "why": r["why"]}
        if r.get("explore"):
            out["explore"] = True
        return {"routed": out}

    # -- trying untried models -----------------------------------------------------------------------------
    def _router_try_cost(self, ref: Any) -> float | None:
        """One try of a typical task with this model (the estimate's sizes, with its allowance for longer ones)."""
        from ..providers.base import Usage
        from .plandoc import DEFAULT_TOKENS

        try:
            c = self.cfg.cost(ref, Usage(*DEFAULT_TOKENS["chat"]))
        except Exception:  # noqa: BLE001
            return None
        return None if c is None else c * 1.4

    def _router_goal(self, task: Any) -> tuple[int, str, int]:
        """(goal index, goal words, how many tasks the goal has)."""
        gi = int(getattr(task, "goal_index", 0) or 0)
        try:
            goals = self.project.meta().get("goals") or []
        except Exception:  # noqa: BLE001
            goals = []
        text = goals[gi] if 0 <= gi < len(goals) else ""
        n = sum(1 for t in self.project.tasks() if t.goal_index == gi)
        return gi, str(text), max(n, 1)

    def _router_explored(self, gi: int) -> tuple[int, float, set[str]]:
        """This goal's tries so far: (how many, what they cost or were estimated at, their task ids)."""
        rows = [r for r in self._router_state().get("explored") or [] if r.get("goal") == gi]
        live = self._router_live()["exploring"]
        saved = {t.id: t for t in self.project.tasks()}
        usd = 0.0
        for r in rows:
            t = live.get(r.get("task")) or saved.get(r.get("task"))
            real = sum(float(a.get("cost_usd") or 0) for a in (t.attempts if t else [])
                       if a.get("model") == r.get("model"))
            usd += max(float(r.get("est_usd") or 0), real)
        return len(rows), usd, {str(r.get("task")) for r in rows}

    def _router_may_explore(self, task: Any) -> bool:
        if getattr(task, "hard", False) or getattr(task, "risky", False):
            return False
        try:
            return bool(dial.for_task(self, task).get("explore"))
        except Exception:  # noqa: BLE001 - the dial is a help
            return False

    def _router_explore(self, task, role, models, candidates, history, tags, conf) -> ModelRef | None:
        if not self._router_may_explore(task) or conf["share"] <= 0:
            return None
        pool = {str(r) for r in self._router_pool(role.name, conf)}
        usual = self._router_try_cost(models[0])
        if usual is None:
            return None
        fresh = []
        for ref in candidates:
            if str(ref) not in pool or str(ref) in {str(m) for m in models}:
                continue
            if self._router_score(history, role.name, ref, tags).judged >= conf["min_samples"]:
                continue  # tried enough on this kind of work: the strength map decides
            est = self._router_try_cost(ref)
            if est is None or est > usual * conf["max_price_ratio"] + 1e-12:
                continue
            fresh.append((ref, est))
        if not fresh:
            return None
        gi, goal, n = self._router_goal(task)
        if _hash(goal, gi, task.id) >= conf["share"]:
            return None
        with self._lock:
            live = self._router_live()
            for tid, t in list(live["exploring"].items()):
                if getattr(t, "status", "") not in ("running", "pending"):
                    live["exploring"].pop(tid, None)
            if live["exploring"]:
                return None  # one at a time
            count, usd, done = self._router_explored(gi)
            if task.id in done or count + 1 > math.floor(conf["share"] * n + 1e-9):
                return None
            ref, est = fresh[int(_hash("model", goal, gi, task.id) * len(fresh))]
            if usd + est > conf["max_usd_per_goal"] + 1e-12 or not dial.allow(self, "router", est):
                return None
            state = self._router_state()
            state.setdefault("explored", []).append({"goal": gi, "task": task.id, "model": str(ref),
                                                     "est_usd": round(est, 6)})
            self._router_save(state)
            live["exploring"][task.id] = task
        dial.spent(self, "router", est, task.id)
        return ref

    def _router_estimate(self, tasks: list[Any]) -> dict[str, Any] | None:
        """The plan's line for trying newer models: "trying newer models on 2 small tasks: up to about $0.30"."""
        conf = self._router_conf()
        if conf["share"] <= 0:
            return None
        pending = [t for t in tasks if getattr(t, "status", "pending") == "pending"]
        by_goal: dict[int, int] = {}
        for t in tasks:
            by_goal[t.goal_index] = by_goal.get(t.goal_index, 0) + 1
        try:
            goals = self.project.meta().get("goals") or []
        except Exception:  # noqa: BLE001
            goals = []
        picked: dict[int, list[float]] = {}
        for t in pending:
            role = self.cfg.roles.get(t.role)
            if not role or role.kind != "chat" or not role.models or not self._router_may_explore(t):
                continue
            usual = self._router_try_cost(role.models[0])
            if usual is None:
                continue
            ests = [e for r in self._router_pool(role.name, conf)
                    if self._may_use(r) and (e := self._router_try_cost(r)) is not None
                    and e <= usual * conf["max_price_ratio"] + 1e-12]
            if not ests:
                continue
            gi = t.goal_index
            goal = goals[gi] if 0 <= gi < len(goals) else ""
            if _hash(goal, gi, t.id) >= conf["share"]:
                continue
            row = picked.setdefault(gi, [])
            if len(row) < math.floor(conf["share"] * by_goal.get(gi, 1) + 1e-9):
                row.append(max(ests))
        n = sum(len(v) for v in picked.values())
        if not n:
            return None
        usd = sum(min(sum(v), conf["max_usd_per_goal"]) for v in picked.values())
        return {"id": "router", "usd": round(usd, 4), "minutes": 0,
                "words": f"trying newer models on {n} small task{'s' if n != 1 else ''}: up to about ${usd:.2f}"}
