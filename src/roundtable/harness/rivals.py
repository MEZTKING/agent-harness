"""Best of several (wave 6): on a task the dial marks for it, two or three models from different makers each
build it in a copy of their own, the project's tests and then one checker pick the best, and only that work
goes in. The owner's words: "the maximum possible performance using the combinations of all the api model in
tandem"; PLAN.md: "best-of-several only on hard tasks".

When (``_rivals_run``; None means the usual way):

- the dial gives the task two or more builders (``dial.for_task(...)["rivals"]``; at "lean" it never does);
- the project is kept in git and has a first commit (the copies are git worktrees);
- it is not a picture task, a fix-up task (``merge_of``) or the owner's "try a stronger model" (``stronger``);
- at least two usable models: the routed chain, then the Quality set's models for the role, one per maker
  where possible, each one the project allows (``_may_use``) and whose account is not empty or capped;
- the dial's extra-checking allowance has room for the extra builds (``dial.allow``).

How:

1. The work root (the project's folder, or the task's own worktree when tasks run at once) is committed as it
   stands: that commit is the base.
2. Each rival gets a worktree ``<task>~r<n>`` (branch ``roundtable-task/<task>-r<n>``) from the base, and a
   thread of its own set up as a parallel lane is (``_tl.task``, ``_tl.rival``, ``_tl.root``, ``_tl.ws`` with its
   own Gate, ``_tl.baseline``); the base's own checks baseline is the rival's, since it starts from the same files.
3. Each builds a copy of the task once (``_attempt_loop(copy, tasks, [ref], attempts=1, review=False)``), then
   the project's test command runs in its copy. Its work is committed on its branch, finished or not.

The picking rule, in order:

1. A rival that didn't finish (an error, a refusal, out of steps, no credit) is out.
2. A rival whose work breaks a test that passed before (``_task_checks`` blames it) is out.
3. One left: it wins, with no pick call.
4. Several left: one "pick" call by a checker, from a maker that built none of them when one exists (else the
   first checker the project allows, noted as ``same_maker``). It sees each attempt as A, B or C (its test
   result, summary and changes; no model names) and answers ``pick_best {best, why, problems}``. No clear
   answer: the first of them (the routed first choice) wins.
5. None left: the usual loop has the task's remaining tries (``max_attempts_per_task - 1``) in the work root,
   with what went wrong in each rival as feedback.

The winner's branch is fast-forwarded into the work root, and it gets the normal review (``_review(...,
built_by=winner)``). Rejected: the usual loop carries on from its work with the winner first and then the other
rivals' models. The others: each folder is removed once clean (``Worktrees.remove``'s own rule); the branch stays
with a ``rival_kept`` event saying why, plus a patch in ``.harness/rivals/<task>/<rival>.patch``. Nothing is
deleted and no branch is pushed.

Money: every charge goes through the run's one Budget (it has its own lock). In a one-at-a-time run the budget
is armed for the round as the parallel loop arms it, so a money stop in one rival stops the others at their
next step; the first stop is raised again in the caller once all have stopped, and the task goes back to
waiting. Each rival's spend is counted by a thread-aware tap on ``budget.on_use``; the extra builds (all but the
winner, or all but the first when none won) and the pick call are told to the dial (``dial.spent``).

Records: ``.harness/rivals.json`` (one round per run of a task: base, winner, why, each rival), the attempt keys
``rival`` and ``rivals`` (``_rivals_attempt``), and the metrics: the winner's row carries ``rival`` and
``rivals: n``; each finished loser gets a row with outcome ``rival_lost`` and its cost.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ..core.models import utcnow
from ..providers.base import ToolSpec
from . import checks as checkslib
from . import dial
from . import makers
from .agent import BudgetExceeded, OutOfCredit
from .tools import Tool, Toolbox, _obj
from .worktrees import RunHalted, Worktrees, safe_name

MAX_RIVALS = 3
LETTERS = "ABC"
RECORDS = "rivals.json"
PATCHES = Path(".harness") / "rivals"
PATCH_MAX = 2_000_000  # characters of one losing attempt's patch kept on disk (its branch has all of it)
PICK_SHARE = 0.25  # a pick call, guessed as a share of one build (for the allowance's estimate)
_GIT_LOCK = threading.RLock()  # worktrees are made and removed one at a time, whatever thread asks

PICK_SYSTEM = (
    "You compare several finished attempts at the same software task and choose the best one. Judge them against "
    "the task's own description and acceptance criteria: first whether it does what was asked and nothing is "
    "broken, then whether it is complete, then whether it is simple and tidy. A longer change is not better by "
    "itself. The attempts are labelled with letters only; who made them doesn't matter. Call pick_best once."
)


class RivalsStage:
    """The Orchestrator's side of rival builders (a mixin, like the parallel stage)."""

    # -- the hook --------------------------------------------------------------------------------------------
    def _rivals_run(self, task, tasks) -> bool | None:
        if task.merge_of or task.stronger:
            return None
        role = self.cfg.roles.get(task.role)
        if role is None or role.kind == "image":
            return None
        try:
            want = int(dial.for_task(self, task).get("rivals") or 1)
        except (TypeError, ValueError):
            want = 1
        if want < 2:
            return None
        root = Path(self._work_root())
        if not self._rivals_git_ready(root):
            return None
        models = self._routed(task, role, list(role.models))  # routed once: from here this stage runs the task
        picked = self._rivals_models(task, models, min(want, MAX_RIVALS))
        if len(picked) < 2:
            self.emit("rivals_skipped", {"task": task.id, "why": "fewer than two models this project may use"})
            return self._attempt_loop(task, tasks, models)
        est = self._rivals_estimate(task, len(picked))
        if not dial.allow(self, "rivals", est):
            self.emit("rivals_skipped", {"task": task.id, "why": "the extra checking's share of the money is used"})
            return self._attempt_loop(task, tasks, models)
        return self._rivals_round(task, tasks, models, picked, root)

    # -- the stages' parts of an attempt and a metrics row ----------------------------------------------------
    def _rivals_attempt(self, task, ref) -> dict[str, Any] | None:
        part = getattr(self._tl, "rivals_attempt", None)
        if part:
            return dict(part)
        rival = getattr(self._tl, "rival", None)
        return {"rival": rival} if rival else None

    def _rivals_metric(self, task, ref) -> dict[str, Any] | None:
        part = getattr(self._tl, "rivals_metric", None)
        if part:
            return dict(part)
        rival = getattr(self._tl, "rival", None)
        return {"rival": rival} if rival else None

    # -- who builds -------------------------------------------------------------------------------------------
    def _rivals_git_ready(self, root: Path) -> bool:
        if not self.cfg.git or not (self.project.root / ".git").exists():
            return False
        return bool(self._git("rev-parse", "--verify", "-q", "HEAD", check=False, cwd=root).strip())

    def _rivals_models(self, task, models, n: int) -> list:
        """Up to ``n`` models: the routed chain, then the Quality set's for the role; one per maker first."""
        chain, seen = [], set()
        try:
            stronger = self.stronger_models(task)
        except Exception:  # noqa: BLE001 - the Quality set is a help here
            stronger = []
        for ref in [*models, *stronger]:
            if str(ref) in seen:
                continue
            seen.add(str(ref))
            if self._may_use(ref) and not self._blocked(ref):
                chain.append(ref)
        out = makers.distinct(chain)[:n]
        for ref in chain:  # fewer makers than rivals: the same maker's other models fill in
            if len(out) >= n:
                break
            if ref not in out:
                out.append(ref)
        return out

    def _rivals_estimate(self, task, n: int) -> float | None:
        """The extra builds' likely cost, from this role's past builds (None: nothing to go on)."""
        p = self.project.dir / "metrics.jsonl"
        costs = []
        try:
            for line in p.read_text(encoding="utf-8").splitlines() if p.is_file() else []:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (row.get("role") == task.role and row.get("outcome") in ("approved", "rejected")
                        and "rival" not in row):
                    costs.append(float(row.get("cost_usd") or 0))
        except OSError:
            return None
        if not costs:
            return None
        one = sum(costs[-20:]) / len(costs[-20:])
        return round(one * (n - 1 + PICK_SHARE), 6)

    # -- one round --------------------------------------------------------------------------------------------
    def _rivals_round(self, task, tasks, models, picked, root: Path) -> bool:
        trees = Worktrees(self.project.root)
        base = self._rivals_base(task, root)
        lanes = self._rivals_lanes(task, picked, trees, base)
        try:
            values = self.project_settings().values
        except Exception:  # noqa: BLE001
            values = {}
        baseline = self._checks_baseline()
        main_gate = getattr(self.ws, "gate", None)
        self._rivals_tap()
        armed = "check" not in self.budget.__dict__  # one task at a time: armed for the round, as the loop does
        if armed:
            self._arm_budget()
        self.emit("rivals_start", {"task": task.id, "base": base,
                                   "rivals": [{"id": ln["id"], "model": str(ln["ref"])} for ln in lanes]})
        threads = [threading.Thread(target=self._rival_lane, name=f"roundtable-rival-{ln['id']}",
                                    args=(ln, tasks, baseline, values, main_gate, trees), daemon=True)
                   for ln in lanes]
        try:
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            halted = self._halt
            if armed:  # one task at a time: nothing else reads the halt, so it ends with the round
                self._disarm_budget()
                self._halt = None
        stops = [ln["stop"] for ln in lanes if ln.get("stop") is not None]
        if stops:
            first = next((e for e in stops if not isinstance(e, RunHalted)), None) or (stops[0] if stops else None)
            for ln in lanes:
                self._rivals_keep(task, ln, trees, base, "the run stopped before the attempts could be compared")
            self._rivals_record(task, base, lanes, None, "the run stopped", "", 0.0)
            if isinstance(first, BaseException):
                raise first
            raise RunHalted(halted.get("text") if isinstance(halted, dict) else str(halted))

        winner, why, problems, pick = self._rivals_choose(task, lanes)
        if winner is not None and not self._rivals_bring_in(winner, trees, root):
            why = "its work couldn't be brought into the project, so the task was built the usual way"
            self.emit("stage_error", {"stage": "_rivals_run", "error": why})
            winner = None
        for ln in lanes:
            if ln is winner:
                self._rivals_tidy_winner(task, ln, trees, root)
            else:
                self._rivals_keep(task, ln, trees, base, ln.get("lost") or why)
        normal = winner if winner is not None else lanes[0]
        extra = sum(ln["acc"]["cost"] for ln in lanes if ln is not normal) + pick["cost"]
        dial.spent(self, "rivals", extra, task.id)
        rows = self._rivals_rows(lanes, winner, why)
        self._rivals_record(task, base, lanes, winner, why, problems, pick["cost"], pick.get("model", ""))
        for ln in lanes:  # each finished loser: a row with its cost (unfinished ones wrote their own)
            if ln is not winner and ln.get("finished"):
                self._rivals_row(task, ln, "rival_lost", ln["acc"]["cost"], {"rival": ln["id"]})

        limit = int(self.cfg.limits.max_attempts_per_task or 1)
        if winner is None:
            feedback = [f"Another attempt ({ln['ref']}) {ln.get('lost') or 'was not chosen'}."
                        + (f"\n{ln['checks']['feedback']}" if (ln.get("checks") or {}).get("blame") else "")
                        for ln in lanes]
            self._tl.rivals_attempt = {"rivals": rows}
            try:
                self._add_attempt(task, lanes[0]["ref"], {"model": str(lanes[0]["ref"]), "outcome": "rivals_failed",
                                                          "cost_usd": round(sum(ln["acc"]["cost"] for ln in lanes), 6)})
            finally:
                self._tl.__dict__.pop("rivals_attempt", None)
            self.emit("rivals_none", {"task": task.id, "why": why})
            return self._attempt_loop(task, tasks, models, feedback=feedback, attempts=max(0, limit - 1))

        self.emit("rivals_picked", {"task": task.id, "winner": winner["id"], "model": str(winner["ref"]),
                                    "why": why[:500], "problems": problems[:500],
                                    **({"same_maker": True} if pick.get("same_maker") else {})})
        self._journal("note", self._rivals_words(task, lanes, winner, why))
        task.summary = winner["summary"]
        approved, fb, rev = self._review(task, winner["summary"], built_by=winner["ref"])
        review_cost = rev.cost_usd if rev else 0.0
        outcome = "approved" if approved else "rejected"
        self._tl.rivals_attempt = {"rival": winner["id"], "rivals": rows}
        self._tl.rivals_metric = {"rival": winner["id"], "rivals": len(lanes)}
        try:
            self._add_attempt(task, winner["ref"], {
                "model": str(winner["ref"]), "outcome": outcome, "summary": winner["summary"][:1000],
                "review": fb[:2000], "cost_usd": round(winner["acc"]["cost"] + review_cost, 6)})
            self._rivals_row(task, winner, outcome, winner["acc"]["cost"] + review_cost, {},
                             saved=rev.saved_tokens_est if rev else 0)
        finally:
            self._tl.__dict__.pop("rivals_attempt", None)
            self._tl.__dict__.pop("rivals_metric", None)
        self.emit("review", {"task": task.id, "approved": approved, "feedback": fb[:500]})
        if approved:
            return True
        rest = [winner["ref"], *(ln["ref"] for ln in lanes if ln is not winner)]
        feedback = [f"Attempt 1 ({winner['ref']}) was rejected by the reviewer:\n{fb}"]
        return self._attempt_loop(task, tasks, rest, feedback=feedback, attempts=max(0, limit - 1))

    def _rivals_base(self, task, root: Path) -> str:
        """Commit the work root as it stands; its commit is where every rival starts."""
        if root == self.project.root:
            self._git_commit(f"harness: before {task.id}'s rival attempts")
        else:
            with _GIT_LOCK:
                self._git("add", "-A", check=False, cwd=root)
                if self._git("status", "--porcelain", check=False, cwd=root).strip():
                    self._git("commit", "-q", "--no-verify", "-m", f"harness: before {task.id}'s rival attempts",
                              cwd=root)
        return self._git("rev-parse", "HEAD", cwd=root).strip()

    def _rivals_lanes(self, task, picked, trees: Worktrees, base: str) -> list[dict[str, Any]]:
        """A fresh worktree for each rival, numbered past every earlier round's (no id or branch is reused)."""
        used = [int(r["id"][1:]) for rnd in self.project._read(RECORDS, {}).get(task.id, [])
                for r in rnd.get("rivals", []) if str(r.get("id", "")).startswith("r") and r["id"][1:].isdigit()]
        lanes, n = [], max(used, default=0)
        with _GIT_LOCK:
            for ref in picked:
                n += 1
                while trees.exists(f"{task.id}~r{n}") or trees.has_branch(f"{task.id}~r{n}"):
                    n += 1
                wid = f"{task.id}~r{n}"
                path, _ = trees.add(wid, base)
                copy = type(task).from_dict({**asdict(task), "attempts": [], "summary": ""})
                lanes.append({"id": f"r{n}", "wid": wid, "ref": ref, "path": path, "task": copy, "base": base,
                              "branch": trees.branch(wid), "acc": {"cost": 0.0, "calls": 0, "input": 0, "output": 0},
                              "finished": False, "summary": "", "checks": None, "stop": None, "seconds": 0.0})
        return lanes

    # -- one rival, in its own thread --------------------------------------------------------------------------
    def _rival_lane(self, lane, tasks, baseline, values, main_gate, trees: Worktrees) -> None:
        from .gate import Gate
        from .tools import Workspace

        copy, path = lane["task"], lane["path"]
        tl = self._tl
        tl.task, tl.rival, tl.root, tl.baseline = copy.id, lane["id"], path, baseline
        tl.rival_acc = lane["acc"]
        tl.ws = Workspace(path, allow_shell=self.cfg.allow_shell, command_timeout=self.cfg.limits.command_timeout)
        tl.ws.gate = Gate(self.project.root, self.cfg, on_change=self._publish_plan,
                          context=lambda: {"id": copy.id, "title": copy.title},
                          timeout=getattr(main_gate, "timeout", None))
        t0 = time.monotonic()
        try:
            if values.get("setup"):  # its dependencies aren't in git: set up once, as a new worktree is
                out = checkslib.prepare_worktree(path, {**values, "test": ""}, fresh=True)
                if out.get("setup"):
                    self.emit("worktree_setup", {"command": out["setup"]["command"],
                                                 "passed": out["setup"]["passed"]})
            ok = self._attempt_loop(copy, tasks, [lane["ref"]], attempts=1, review=False)
            lane["finished"], lane["summary"] = bool(ok), copy.summary
            if ok:
                try:
                    lane["checks"] = self._task_checks(copy)
                except Exception as e:  # noqa: BLE001 - the tests couldn't run: not held against it
                    lane["checks"] = {"verdict": "unknown", "blame": False, "text": "", "feedback": str(e)[:300]}
            else:
                last = copy.attempts[-1] if copy.attempts else {}
                lane["lost"] = _unfinished_words(last)
        except OutOfCredit as e:  # that account is empty: this rival is out, the others carry on
            lane["lost"] = f"didn't finish: {e}"
        except BudgetExceeded as e:  # a money stop (or another one's): every rival stops at its next step
            lane["stop"] = e
            if not isinstance(e, RunHalted) and self._halt is None:
                self._halt = e
        except Exception as e:  # noqa: BLE001 - one rival's crash puts only that rival out
            lane["lost"] = f"didn't finish: {str(e)[:200]}"
            self.emit("stage_error", {"stage": "_rivals_run", "error": str(e)[:300]})
        finally:
            lane["seconds"] = round(time.monotonic() - t0, 2)
            try:
                with _GIT_LOCK:
                    trees.commit(lane["wid"], f"[{copy.id}] {copy.title} ({lane['id']}: {lane['ref']})")
            except RuntimeError as e:
                lane["commit_error"] = str(e)[:300]
            for name in ("task", "rival", "root", "ws", "baseline", "rival_acc"):
                tl.__dict__.pop(name, None)

    # -- picking ---------------------------------------------------------------------------------------------
    def _rivals_choose(self, task, lanes) -> tuple[dict | None, str, str, dict[str, Any]]:
        """The winner, why, the problems the checker saw, and the pick call's {cost, model, same_maker}."""
        pick: dict[str, Any] = {"cost": 0.0}
        for ln in lanes:
            ln["tests"] = _tests_word(ln.get("checks")) if ln.get("finished") else ""
            if ln.get("finished") and (ln.get("checks") or {}).get("blame"):
                ln["lost"] = "broke a test that passed before"
        left = [ln for ln in lanes if ln.get("finished") and not ln.get("lost")]
        if not left:
            return None, "no attempt finished with the project's tests still passing", "", pick
        if len(left) == 1:
            others = [ln for ln in lanes if ln is not left[0]]
            why = ("the only attempt that finished with the project's tests still passing" if others
                   else "the only attempt")
            for ln in others:
                ln["lost"] = ln.get("lost") or "was not chosen"
            return left[0], why, "", pick
        winner, why, problems = self._rivals_pick(task, left, pick)
        for ln in lanes:
            if ln is not winner and not ln.get("lost"):
                ln["lost"] = f"another model's attempt was chosen: {why}"
        return winner, why, problems, pick

    def _rivals_pick(self, task, left, pick: dict[str, Any]) -> tuple[dict, str, str]:
        from .orchestrator import HarnessError

        reviewer = self.cfg.roles.get(self.cfg.reviewer_role or "")
        if reviewer is None:
            return left[0], "no checker is set up, so the first model's attempt was kept", ""
        built = {makers.maker(ln["ref"]) for ln in left}
        usable = [m for m in reviewer.models if self._may_use(m) and not self._blocked(m)]
        fresh = [m for m in usable if makers.maker(m) not in built]
        order = fresh + [m for m in usable if m not in fresh]
        if not order:
            return left[0], "no checker this project allows was free, so the first model's attempt was kept", ""
        pick["same_maker"] = not fresh
        choice: dict[str, Any] = {}

        def pick_best(args: dict) -> str:
            choice.update(args)
            return "choice recorded"

        letters = LETTERS[:len(left)]
        box = Toolbox()
        box.add(Tool(ToolSpec("pick_best", "Record which attempt is best.", _obj({
            "best": {"type": "string", "enum": list(letters), "description": "the letter of the best attempt"},
            "why": {"type": "string", "description": "one or two plain sentences: why it is the best"},
            "problems": {"type": "string", "description": "anything wrong you saw in any attempt, by letter"}},
            ["best", "why"])), pick_best, terminal=True))
        role = replace(reviewer, models=order)
        acc = {"cost": 0.0, "calls": 0, "input": 0, "output": 0}
        self._tl.rival_acc = acc
        try:
            res = self._run_with_fallback(role, PICK_SYSTEM, self._rivals_pick_prompt(task, left, letters), box,
                                          require="pick_best", done=lambda: bool(choice), max_steps=4)
            pick["model"] = res.model
        except HarnessError as e:  # every checker failed: the first attempt is kept
            self.emit("stage_error", {"stage": "_rivals_run", "error": str(e)[:300]})
        finally:
            self._tl.__dict__.pop("rival_acc", None)
            pick["cost"] = acc["cost"]
        best = str(choice.get("best") or "").strip().upper()[:1]
        if best and best in letters:
            return (left[letters.index(best)], str(choice.get("why") or "the checker chose it").strip(),
                    str(choice.get("problems") or "").strip())
        return left[0], "the checker gave no clear choice, so the first model's attempt was kept", ""

    def _rivals_pick_prompt(self, task, left, letters: str) -> str:
        from .orchestrator import MAX_DIFF

        each = max(4000, MAX_DIFF // max(1, len(left)))
        parts = [f"# Task [{task.id}] {task.title}\n{task.description}",
                 f"# Acceptance criteria\n{task.acceptance or '(use judgement)'}"]
        for letter, ln in zip(letters, left):
            diff = self._git("diff", ln["base"], ln["branch"], check=False) if ln.get("base") else ""
            if len(diff) > each:
                diff = diff[:each] + f"\n... [{len(diff) - each} more characters not shown]"
            parts.append(f"# Attempt {letter}\nThe project's tests: {ln['tests'] or 'none set'}.\n\n"
                         f"Its summary:\n{ln['summary'] or '(none)'}\n\nIts changes:\n```diff\n"
                         f"{diff or '(no changes)'}\n```")
        parts.append(f"Choose the best of {', '.join(letters)} and call pick_best.")
        return "\n\n".join(parts)

    # -- the winner in, the others kept ------------------------------------------------------------------------
    def _rivals_bring_in(self, lane, trees: Worktrees, root: Path) -> bool:
        """Fast-forward the work root to the winner's branch (it started from the work root's own commit)."""
        with _GIT_LOCK:
            self._git("merge", "--ff-only", "-q", lane["branch"], check=False, cwd=root)
            head = self._git("rev-parse", "HEAD", check=False, cwd=root).strip()
            tip = self._git("rev-parse", lane["branch"], check=False).strip()
        return bool(head) and head == tip

    def _rivals_tidy_winner(self, task, lane, trees: Worktrees, root: Path) -> None:
        with _GIT_LOCK:
            removed, why = trees.remove(lane["wid"])
            if trees.has_branch(lane["wid"]):  # merged into a task's worktree, not the project's branch yet
                self._git("branch", "-d", lane["branch"], check=False, cwd=root)
        lane["branch_kept"] = trees.has_branch(lane["wid"])
        if not removed:
            self.emit("worktree_kept", {"task": task.id, "path": str(lane["path"]), "why": why})

    def _rivals_keep(self, task, lane, trees: Worktrees, base: str, why: str) -> None:
        """A rival not chosen: its patch written, its folder removed once clean, its branch kept with why."""
        patch = ""
        with _GIT_LOCK:
            diff = self._git("diff", base, lane["branch"], check=False) if base else ""
            if diff.strip():
                p = self.project.root / PATCHES / safe_name(task.id) / f"{lane['id']}.patch"
                try:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(diff[:PATCH_MAX], encoding="utf-8")
                    patch = str(p.relative_to(self.project.root)).replace("\\", "/")
                except OSError:
                    patch = ""
            removed, kept_why = trees.remove(lane["wid"])
            lane["branch_kept"] = trees.has_branch(lane["wid"])
        lane["patch"] = patch
        self.emit("rival_kept", {"task": task.id, "rival": lane["id"], "model": str(lane["ref"]),
                                 "branch": lane["branch"] if lane["branch_kept"] else "", "patch": patch,
                                 "why": why[:500]})
        if not removed:
            self.emit("worktree_kept", {"task": task.id, "path": str(lane["path"]), "why": kept_why})

    # -- records ---------------------------------------------------------------------------------------------
    def _rivals_rows(self, lanes, winner, why: str) -> list[dict[str, Any]]:
        return [{"id": ln["id"], "model": str(ln["ref"]), "maker": makers.maker(ln["ref"]),
                 "tests": ln.get("tests", ""), "picked": ln is winner,
                 "why": why if ln is winner else (ln.get("lost") or ""),
                 "branch": ln["branch"] if ln.get("branch_kept") else "",
                 "cost_usd": round(ln["acc"]["cost"], 6)} for ln in lanes]

    def _rivals_record(self, task, base: str, lanes, winner, why: str, problems: str, pick_cost: float,
                       pick_model: str = "") -> None:
        row = {"at": utcnow(), "base": base, "winner": winner["id"] if winner else "", "why": why,
               "problems": problems, "pick_model": pick_model, "pick_cost_usd": round(pick_cost, 6),
               "rivals": [{**r, "patch": ln.get("patch", ""), "seconds": ln.get("seconds", 0)}
                          for r, ln in zip(self._rivals_rows(lanes, winner, why), lanes)]}
        with self._lock:
            records = self.project._read(RECORDS, {})
            records.setdefault(task.id, []).append(row)
            self.project._write(RECORDS, records)

    def _rivals_row(self, task, lane, outcome: str, cost: float, part: dict[str, Any], saved: int = 0) -> None:
        acc = lane["acc"]
        row = {"at": utcnow(), "task": task.id, "role": task.role, "model": str(lane["ref"]), "outcome": outcome,
               "steps": acc["calls"], "seconds": lane.get("seconds", 0), "input_tokens": acc["input"],
               "output_tokens": acc["output"], "cost_usd": round(cost, 6), "saved_tokens_est": saved}
        if part:
            self._tl.rivals_metric = part
        try:
            self.project.append("metrics.jsonl", self._parts(self.METRIC_PARTS, task, lane["ref"], row))
        finally:
            if part:
                self._tl.__dict__.pop("rivals_metric", None)

    def _rivals_words(self, task, lanes, winner, why: str) -> str:
        from ..routing import model_label

        n = {2: "Two", 3: "Three"}.get(len(lanes), str(len(lanes)))
        return (f"[{task.id}] {n} models built it side by side; {model_label(str(winner['ref']))}'s work was "
                f"chosen: {why}")

    # -- each rival's spend ------------------------------------------------------------------------------------
    def _rivals_tap(self) -> None:
        """Count each rival's charges (its thread's ``rival_acc``) on the way to whoever else listens."""
        budget = self.budget
        with self._lock:
            if getattr(budget.on_use, "_rivals_tap", False):
                return
            prev, tl = budget.on_use, self._tl

            def tap(ref, usage, cost, role):
                acc = getattr(tl, "rival_acc", None)
                if acc is not None:
                    acc["cost"] += float(cost or 0.0)
                    acc["calls"] += 1
                    acc["input"] += int(getattr(usage, "input_tokens", 0) or 0)
                    acc["output"] += int(getattr(usage, "output_tokens", 0) or 0)
                if prev:
                    prev(ref, usage, cost, role)

            tap._rivals_tap = True  # type: ignore[attr-defined]
            budget.on_use = tap


def _tests_word(checks: dict[str, Any] | None) -> str:
    if not checks:
        return "none set"
    return {"pass": "passed", "old_only": "only tests that were already failing fail",
            "unknown": "they were failing before and still fail", "new": "broke a test that passed before"}.get(
        checks.get("verdict"), str(checks.get("verdict") or ""))


def _unfinished_words(attempt: dict[str, Any]) -> str:
    outcome = attempt.get("outcome") or ""
    if outcome == "error":
        return f"didn't finish: its service gave an error ({str(attempt.get('error') or '')[:200]})"
    return {"refusal": "didn't finish: the model refused", "max_steps": "didn't finish: it ran out of steps",
            "breaker": "didn't finish: the safety check stopped it"}.get(outcome, "didn't finish")
