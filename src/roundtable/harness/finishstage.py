"""Start it, use it, fix what breaks: the end step that proves the finished thing works.

A mixin for the Orchestrator (``FinishStage``). When every task is done, ``_finish_step`` starts the product
(each part of it from its own folder: ``doc["parts"]``), walks the done list as a person would, and writes each
answer with ``donelist.record``:

* ``page_opens`` and ``journey``: the steps in a real browser (journeys.py) on the running app;
* ``command``: the item's command through the workspace (the gate, the clean environment, the live log);
* ``file_exists``: the item's path, a glob in its part's folder;
* ``look``: fresh pictures shown to a model that can see (``proof.judge``, inside the proof's own cap);
* ``play``: whoever can play it (``_play_check``, d2-play's); unchecked when nobody can;
* ``owner``: left for the owner.

What fails becomes fix tasks: one planner call with the evidence (the step that failed, the page's errors, the
command's last lines) must answer with them, added through ``add_tasks(by="finish")``, and the run goes round
again. It stops trying after ``finish.rounds`` fix rounds (2), ``finish.max_fix_tasks`` (6) or once
``finish.max_usd`` ($0.50: its checks, its planner calls and the fix tasks' own cost) is spent; the done gate
then shows the one card. Rounds are counted per goal in ``.harness/finish.json`` (``clear_rounds`` starts
them again when the owner says "Try fixing again").

Everything here is a help: a failure inside it is written down, never raised (money excepted).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import appserver, donelist, journeys, showit
from .agent import BudgetExceeded

STATE = "finish.json"  # under .harness/
JOURNEYS_DIR = "journeys"  # under .harness/: the journeys' pictures (rebuildable, like shots/)
CHECKED_STATES = ("open", "failed", "unchecked")
FIX_STEPS = 12  # the planner's steps for working out the fixes (read-only tools)
FIX_PLAN_TOKENS = (20_000, 2_500)  # a planner call that writes fix tasks, for the estimate
_lock = threading.RLock()


@dataclass
class Settings:
    enabled: bool = True
    rounds: int = 2
    max_fix_tasks: int = 6
    max_usd: float = 0.50
    start_seconds: float = 60.0
    command_seconds: int = 300

    @classmethod
    def from_config(cls, cfg: Any) -> "Settings":
        from .config import section

        s = cls()
        raw = section(cfg, "finish") if cfg is not None else {}
        for k, v in (raw or {}).items():
            if not hasattr(s, k) or v is None:
                continue
            cur = getattr(s, k)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
                setattr(s, k, type(cur)(v))
            except (TypeError, ValueError):
                continue
        s.rounds = max(0, min(5, s.rounds))
        s.max_fix_tasks = max(0, min(20, s.max_fix_tasks))
        s.max_usd = max(0.0, s.max_usd)
        s.start_seconds = max(5.0, min(600.0, s.start_seconds))
        return s


# -- the round counter --------------------------------------------------------------------------------------
def state_path(root) -> Path:
    return Path(root) / ".harness" / STATE


def read_state(root) -> dict[str, Any]:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    return data if isinstance(data, dict) and isinstance(data.get("goals"), dict) else {"goals": {}}


def goal_state(root, goal_index: int) -> dict[str, Any]:
    g = read_state(root)["goals"].get(str(goal_index)) or {}
    return {"rounds": int(g.get("rounds") or 0), "spent": float(g.get("spent") or 0.0),
            "fix_tasks": int(g.get("fix_tasks") or 0), "checks": int(g.get("checks") or 0),
            "last": g.get("last") or {}}


def _save_goal(root, goal_index: int, g: dict[str, Any]) -> None:
    with _lock:
        data = read_state(root)
        data["goals"][str(goal_index)] = g
        p = state_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".finish.json.tmp")
        tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)


def clear_rounds(root, goal_index: int | None = None) -> None:
    """Start the fix rounds again (the owner chose "Try fixing again"): for one goal, or every goal."""
    with _lock:
        data = read_state(root)
        for k in list(data["goals"]):
            if goal_index is None or k == str(goal_index):
                g = data["goals"][k]
                g["rounds"], g["spent"], g["fix_tasks"] = 0, 0.0, 0
        if data["goals"]:
            p = state_path(root)
            p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def journeys_root(root) -> Path:
    return Path(root) / ".harness" / JOURNEYS_DIR


def _inside(root: Path, rel: str) -> Path:
    """A part's folder inside the project (anything that climbs out is the project's own folder)."""
    base = Path(root).resolve()
    rel = str(rel or "").strip().replace("\\", "/").strip("/")
    if not rel or rel == ".":
        return base
    full = (base / rel).resolve()
    return full if full == base or base in full.parents else base


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip(".-") or "main"


def _exit_code(out: str) -> int | None:
    m = re.match(r"exit code: (-?\d+)", out or "")
    return int(m.group(1)) if m else None


def _tail(text: str, n: int = 25) -> str:
    return "\n".join(str(text or "").strip().splitlines()[-n:])[-3000:]


FIX_SYSTEM = ("You lead a software project that is built but doesn't work yet. The harness started the finished "
              "thing and used it as a person would; some checks failed. Work out what is wrong from the evidence "
              "and the files, then call submit_fixes once with small fix tasks that make the failed checks pass. "
              "Fix only what the evidence shows; don't add new features.")


class FinishStage:
    """The end step "start it, use it, fix what breaks" (hook: ``_finish_step``), its estimate
    (``_finish_estimate``) and the checks themselves (``finish_check``). ``journey_walker`` (like
    ``shot_renderer``) replaces the browser in tests."""

    journey_walker = None

    # -- settings and where things are ------------------------------------------------------------------
    def _finish_settings(self) -> Settings:
        return Settings.from_config(self.cfg)

    def _finish_goal(self) -> int:
        doc = self.project.plan_doc() or {}
        if "goal_index" in doc:
            try:
                return int(doc["goal_index"])
            except (TypeError, ValueError):
                pass
        goals = self.project.meta().get("goals") or [""]
        return len(goals) - 1

    def _finish_kind_start(self) -> tuple[Any, str]:
        """The kind's ``start:`` recipe and where the kind came from (builtin, own or project)."""
        get = getattr(self, "_kind", None)
        try:
            k = get() if callable(get) else None
        except Exception:  # a kind is a help
            k = None
        if k is None:
            return None, ""
        return (k.spec or {}).get("start"), str(getattr(k, "source", "") or "")

    def _finish_ask(self, source: str):
        """How a start command is asked about. A recipe from an own or imported kind always waits for the owner's
        "Allow" the first time in each project, showing the exact command (``_forced_ask``, d2-ship's, when there;
        else the gate made to ask). Everything else goes through the gate as any command does (None)."""
        if not source or source == "builtin":
            return None
        forced = getattr(self, "_forced_ask", None)
        if callable(forced):
            return forced
        root = self.project.root
        gate = getattr(self.ws, "gate", None)

        def ask(command: str) -> str | None:
            data = read_state(root)
            if command in (data.get("allowed") or []):
                return None
            from .gate import Gate

            class _Always(Gate):
                def mode(self) -> str:  # this one always asks, whatever the project's setting
                    return "all"

                def _covered(self, f, whole, patterns) -> bool:  # nor does an earlier "Always allow" cover it
                    return False

            asker = _Always(root, getattr(gate, "cfg", self.cfg), on_change=getattr(gate, "on_change", None))
            refused = asker.check(command)
            if refused is None:
                with _lock:
                    data = read_state(root)
                    data["allowed"] = list(dict.fromkeys([*(data.get("allowed") or []), command]))
                    p = state_path(root)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            return refused

        return ask

    def _finish_parts(self) -> list[dict[str, Any]]:
        """[{id, name, folder (Path), main}] for each part (``doc["parts"]``), or the project as one part."""
        doc = self.project.plan_doc() or {}
        root = self.project.root
        out: list[dict[str, Any]] = []
        for p in doc.get("parts") or []:
            if not isinstance(p, dict) or not str(p.get("id") or "").strip():
                continue
            folder = _inside(root, str(p.get("folder") or ""))
            out.append({"id": str(p["id"]).strip(), "name": str(p.get("name") or p["id"]), "folder": folder,
                        "main": False})
        if not out:
            return [{"id": "", "name": "", "folder": Path(root).resolve(), "main": True}]
        mains = [p for p in out if p["folder"] == Path(root).resolve()]
        (mains or out)[0]["main"] = True
        return out

    # -- the step -----------------------------------------------------------------------------------------
    def _finish_step(self, tasks: list) -> str | None:
        s = self._finish_settings()
        if not s.enabled:
            return None
        root = self.project.root
        items = [i for i in donelist.read(root)["items"]
                 if i.get("state") in CHECKED_STATES and i.get("how") != "owner" and not str(i["id"]).startswith("ship:")]
        if not items:
            return None
        gi = self._finish_goal()
        g = goal_state(root, gi)
        spent0 = float(self.budget.spent_usd)
        self.emit("finish_start", {"items": [i["id"] for i in items], "round": g["rounds"]})
        try:
            results = self.finish_check(items)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - checking is a help
            self.emit("stage_error", {"stage": "_finish_step", "error": f"checking failed: {str(e)[:300]}"})
            return None
        for item in items:
            r = results.get(item["id"]) or {"passed": None, "words": "Not checked.", "evidence": {}}
            try:
                donelist.record(root, item["id"], r.get("passed"), r.get("words", ""), r.get("evidence") or {},
                                by="finish")
            except KeyError:
                continue
        failed = [i for i in items if (results.get(i["id"]) or {}).get("passed") is False]
        passed = [i for i in items if (results.get(i["id"]) or {}).get("passed") is True]
        unchecked = [i for i in items if (results.get(i["id"]) or {}).get("passed") is None]
        g["checks"] += 1
        g["spent"] += max(0.0, float(self.budget.spent_usd) - spent0)
        g["last"] = {"passed": len(passed), "failed": len(failed), "unchecked": len(unchecked)}
        self.emit("finish_checked", {"passed": [i["id"] for i in passed], "failed": [i["id"] for i in failed],
                                     "unchecked": [i["id"] for i in unchecked]})
        words = (f"Tried the finished thing: {len(passed)} worked, {len(failed)} didn't"
                 + (f", {len(unchecked)} couldn't be checked here" if unchecked else ""))
        if not failed:
            _save_goal(root, gi, g)
            self._journal("note", words + ".")
            return None
        why_not = self._finish_why_not(g, s, tasks)
        if why_not:
            _save_goal(root, gi, g)
            self._journal("note", f"{words}. Not trying to fix it again: {why_not}.")
            self.emit("finish_gave_up", {"why": why_not, "failed": [i["id"] for i in failed]})
            return None
        spent1 = float(self.budget.spent_usd)
        try:
            raw = self._finish_fix_plan(failed, results, s.max_fix_tasks - g["fix_tasks"])
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - the planner failing leaves it to the done gate
            raw = []
            self.emit("stage_error", {"stage": "_finish_step", "error": f"no fixes were planned: {str(e)[:300]}"})
        g["spent"] += max(0.0, float(self.budget.spent_usd) - spent1)
        added = self._finish_add(raw, failed, tasks)
        if not added:
            _save_goal(root, gi, g)
            self._journal("note", f"{words}. No fix tasks could be added, so it waits for you.")
            return None
        g["rounds"] += 1
        g["fix_tasks"] += len(added)
        _save_goal(root, gi, g)
        self._journal("note", f"{words}. Fix round {g['rounds']} of {s.rounds}: "
                              f"{len(added)} fix task{'s' * (len(added) != 1)} added.")
        return "again"

    def _finish_why_not(self, g: dict[str, Any], s: Settings, tasks: list) -> str:
        if g["rounds"] >= s.rounds:
            return f"the {s.rounds} fix round{'s' * (s.rounds != 1)} allowed are used"
        if g["fix_tasks"] >= s.max_fix_tasks:
            return f"the {s.max_fix_tasks} fix tasks allowed are used"
        fixes = sum(float(a.get("cost_usd") or 0) for t in tasks if getattr(t, "added_by", "") == "finish"
                    for a in t.attempts)
        if g["spent"] + fixes >= s.max_usd:
            return f"the ${s.max_usd:.2f} allowed for checking and fixing is spent"
        if self.project.meta().get("no_auto_tasks"):
            return "you chose to finish with what's there"
        return ""

    def _finish_add(self, raw: list[dict[str, Any]], failed: list[dict[str, Any]], tasks: list) -> list:
        """Add the planner's fix tasks, grouped by the item each fixes. Refusals (the cap) are written down."""
        from .orchestrator import HarnessError

        if not raw:
            return []
        known = {t.id for t in self.project.tasks()}
        ids = {i["id"] for i in failed}
        n = 1
        groups: dict[str, list[dict[str, Any]]] = {}
        for t in raw:
            while f"F{n}" in known:
                n += 1
            tid = f"F{n}"
            known.add(tid)
            fixes = str(t.get("fixes") or "").strip()
            fixes = fixes if fixes in ids else failed[0]["id"]
            task = {"id": tid, "title": str(t.get("title") or "Fix")[:120],
                    "role": str(t.get("role") or ""), "description": str(t.get("description") or ""),
                    "acceptance": str(t.get("acceptance") or "") or f"The check passes: {fixes}",
                    "depends_on": []}
            for k in ("files", "part", "stage"):
                if t.get(k):
                    task[k] = t[k]
            groups.setdefault(fixes, []).append(task)
        added = []
        for fixes, group in groups.items():
            text = next((i["text"] for i in failed if i["id"] == fixes), fixes)
            try:
                added += self.add_tasks(group, by="finish", why=f"it didn't work when tried: {text}", fix_of=fixes)
            except HarnessError as e:
                self.emit("finish_refused", {"item": fixes, "why": str(e)[:300]})
        return added

    def _finish_fix_plan(self, failed: list[dict[str, Any]], results: dict[str, dict[str, Any]],
                         room: int) -> list[dict[str, Any]]:
        """One planner call with the evidence; it must answer with fix tasks (at most ``room``)."""
        from ..providers.base import ToolSpec
        from .tools import READ_ONLY, Tool

        if room <= 0:
            return []
        role = self.cfg.roles[self.cfg.planner_role]
        roles = [r for r, spec in self.cfg.roles.items() if spec.kind == "chat" and r != self.cfg.planner_role] \
            or [self.cfg.planner_role]
        captured: dict[str, Any] = {}

        def submit(args: dict) -> str:
            got = [t for t in (args.get("tasks") or []) if isinstance(t, dict)]
            bad = [t for t in got if t.get("role") not in self.cfg.roles or not str(t.get("description") or "").strip()]
            if not got or bad:
                raise Exception("each fix task needs a known role and a description; available roles: "
                                + ", ".join(sorted(self.cfg.roles)))
            captured["tasks"] = got[:room]
            return f"{len(captured['tasks'])} fix tasks accepted"

        lines = []
        for item in failed:
            r = results.get(item["id"]) or {}
            ev = r.get("evidence") or {}
            lines.append(f"## {item['id']}: {item['text']}\nHow it was checked: {item.get('how')}\n"
                         f"What happened: {r.get('words', '')}")
            if item.get("steps"):
                lines.append("Steps: " + json.dumps(item["steps"], ensure_ascii=False)[:800])
            if ev.get("errors"):
                lines.append("Errors on the page:\n" + "\n".join(f"- {e}" for e in ev["errors"][:10]))
            if ev.get("tail"):
                lines.append("Last lines of the output:\n```\n" + ev["tail"][-2000:] + "\n```")
            if ev.get("app_output"):
                lines.append("The app's own output:\n```\n" + ev["app_output"][-1500:] + "\n```")
        schema = {"type": "object", "properties": {"tasks": {"type": "array", "items": {
            "type": "object", "properties": {
                "title": {"type": "string"}, "role": {"type": "string", "enum": sorted(self.cfg.roles)},
                "description": {"type": "string", "description": "what to change, in which files, and why"},
                "acceptance": {"type": "string"}, "fixes": {"type": "string", "description": "the check's id, like D2"},
                "files": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "role", "description", "fixes"]}}}, "required": ["tasks"]}
        box = self.ws.toolbox(READ_ONLY)
        box.add(Tool(ToolSpec("submit_fixes", "Submit the fix tasks. Call exactly once.", schema), submit,
                     terminal=True))
        prompt = (f"{self._project_context(self.project.tasks())}\n\n# What failed when the finished thing was tried\n"
                  + "\n\n".join(lines)
                  + f"\n\n# Your job\nRead the files you need, then call submit_fixes with 1 to {min(room, 3)} small "
                    f"fix tasks (roles you can use: {', '.join(roles)}). Each names the check it fixes (`fixes`).")
        self.emit("finish_planning", {"failed": [i["id"] for i in failed]})
        self._run_with_fallback(role, FIX_SYSTEM, prompt, box, require="submit_fixes",
                                done=lambda: "tasks" in captured, max_steps=FIX_STEPS)
        return captured.get("tasks") or []

    # -- checking --------------------------------------------------------------------------------------------
    def finish_check(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Check each item it can; {item id: {passed: True/False/None, words, evidence}}. Each part is started
        once, from its own folder, for the items that need it open."""
        parts = self._finish_parts()
        by_id = {p["id"]: p for p in parts}
        main = next(p for p in parts if p["main"])
        out: dict[str, dict[str, Any]] = {}
        gi = self._finish_goal()
        for part in parts:
            mine = [i for i in items if (by_id.get(str(i.get("part") or "")) or main) is part]
            if not mine:
                continue
            opened = [i for i in mine if i.get("how") in ("page_opens", "journey")]
            if opened:
                out.update(self._finish_open_and_walk(part, opened, gi))
            for item in mine:
                how = item.get("how")
                if how in ("page_opens", "journey"):
                    continue
                try:
                    if how == "command":
                        out[item["id"]] = self._finish_command(part, item)
                    elif how == "file_exists":
                        out[item["id"]] = self._finish_file(part, item)
                    elif how == "look":
                        out[item["id"]] = self._finish_look(part, item, gi)
                    elif how == "play":
                        got = self._hook("_play_check", item)
                        out[item["id"]] = got if isinstance(got, dict) and "passed" in got else {
                            "passed": None, "words": "Nobody could play it here yet.", "evidence": {}}
                    else:
                        out[item["id"]] = {"passed": None, "words": "Not something the harness can check.",
                                           "evidence": {}}
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001 - one check failing to run is "couldn't check", not a fail
                    out[item["id"]] = {"passed": None, "words": f"Couldn't be checked: {str(e)[:200]}", "evidence": {}}
        return out

    def _finish_open_and_walk(self, part: dict[str, Any], items: list[dict[str, Any]],
                              gi: int) -> dict[str, dict[str, Any]]:
        folder: Path = part["folder"]
        s = self._finish_settings()
        start, source = self._finish_kind_start() if part["main"] else (None, "")
        recipe = appserver.start_recipe(folder, start)
        entry = showit.entry_page(folder)
        out_dir = journeys_root(self.project.root) / f"g{gi}" / _safe(part["id"] or "main")
        rel_dir = out_dir.relative_to(self.project.root).as_posix()

        def answer(res: dict[str, dict[str, Any]], app_output: str = "", started: str = "") -> dict[str, dict[str, Any]]:
            got = {}
            for item in items:
                r = res.get(item["id"]) or {"passed": None, "words": "Couldn't be walked."}
                ev = {k: r.get(k) for k in ("failed_step", "step", "why", "errors") if r.get(k) not in (None, "", [])}
                if r.get("picture"):
                    ev["picture"] = f"{rel_dir}/{r['picture']}"
                if app_output and r.get("passed") is False:
                    ev["app_output"] = _tail(app_output, 20)
                if started:
                    ev["started"] = started
                if part["id"]:
                    ev["part"] = part["id"]
                got[item["id"]] = {"passed": r.get("passed"), "words": r.get("words", ""), "evidence": ev}
            return got

        def none(words: str) -> dict[str, dict[str, Any]]:
            return {i["id"]: {"passed": None, "words": words, "evidence": {"part": part["id"]} if part["id"] else {}}
                    for i in items}

        walker = getattr(self, "journey_walker", None)
        if recipe and (appserver.needs_start(folder, recipe) or not entry):
            live = (self.project.root, "finish")
            with appserver.Running(folder, recipe["command"], ws=self.ws, port=recipe.get("port"),
                                   ready=recipe.get("ready", ""), seconds=s.start_seconds, live=live,
                                   ask=self._finish_ask(source if recipe.get("from") == "kind" else "")) as app:
                self.emit("finish_app", {"part": part["id"], "command": recipe["command"], "ok": app.ok,
                                         "url": app.url, "error": app.error[:300]})
                if not app.ok:
                    if app.refused:  # the gate said no, or commands are off: couldn't check, not a fail
                        return none(f"Couldn't be started here: {app.error}")
                    # an app that won't start fails the items that needed it open: that's what a person would find
                    return {i["id"]: {"passed": False, "words": f"It didn't start: {app.error}"[:400],
                                      "evidence": {"started": recipe["command"], "why": app.error[:300],
                                                   "app_output": _tail(app.output(), 20),
                                                   **({"part": part["id"]} if part["id"] else {})}}
                            for i in items}
                res = journeys.walk(app.url, app.url, items, out_dir, walker=walker)
                return answer(res, app.output(), recipe["command"])
        if entry:
            with showit.StaticServer(folder) as srv:
                url = srv.url + entry.replace("index.html", "") if entry.endswith("index.html") else srv.url + entry
                res = journeys.walk(url, srv.url, items, out_dir, walker=walker)
            return answer(res)
        return none("There's nothing to open yet: no page and no start command.")

    def _finish_command(self, part: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        from .tools import ToolError, Workspace

        cmd = str(item.get("command") or "").strip()
        if not cmd:
            return {"passed": None, "words": "It has no command to run.", "evidence": {}}
        s = self._finish_settings()
        ws = self.ws
        if Path(part["folder"]) != Path(ws.root).resolve():  # a part: its own folder, the same gate and rules
            sub = Workspace(part["folder"], allow_shell=ws.allow_shell, command_timeout=ws.command_timeout)
            sub.gate = ws.gate
            ws = sub
        ws.live = (self.project.root, "finish")
        try:
            out = ws.run_command({"command": cmd, "timeout": s.command_seconds})
        except ToolError as e:
            return {"passed": None, "words": f"Couldn't be run: {str(e)[:200]}", "evidence": {"command": cmd}}
        code = _exit_code(out)
        tail = _tail(out)
        if code == 0:
            return {"passed": True, "words": f"Ran “{cmd[:80]}”: it worked.", "evidence": {"command": cmd, "tail": tail}}
        return {"passed": False, "words": f"Ran “{cmd[:80]}”: it failed (exit code {code}).",
                "evidence": {"command": cmd, "tail": tail, "exit_code": code}}

    def _finish_file(self, part: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        pattern = str(item.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not pattern or ".." in pattern.split("/"):
            return {"passed": None, "words": "It names no file to look for.", "evidence": {}}
        folder = Path(part["folder"])
        found = [p for p in folder.glob(pattern) if p.is_file() and ".harness" not in p.relative_to(folder).parts][:5]
        if found:
            return {"passed": True, "words": f"Found {found[0].relative_to(folder).as_posix()}.",
                    "evidence": {"files": [p.relative_to(folder).as_posix() for p in found]}}
        return {"passed": False, "words": f"No file matches {pattern}.", "evidence": {"path": pattern}}

    def _finish_look(self, part: dict[str, Any], item: dict[str, Any], gi: int) -> dict[str, Any]:
        """Fresh pictures shown to a model that can see, with the item's words as what to look for."""
        from types import SimpleNamespace

        from . import proof as prooflib

        root = self.project.root
        name = f"finish-g{gi}-{_safe(part['id'] or 'main')}"
        start, _ = self._finish_kind_start() if part["main"] else (None, "")
        rec = showit.take_shots(part["folder"], name, render=getattr(self, "shot_renderer", None),
                                godot=self.cfg.godot, out_dir=showit.shots_root(root) / name, latest=False,
                                ws=self.ws, kind_start=start, start_seconds=self._finish_settings().start_seconds)
        prs = prooflib.pairs(root, None, rec)
        if not prs:
            return {"passed": None, "words": "No pictures to look at: " + (rec.get("note") or rec.get("failed") or
                                                                           "nothing showed"), "evidence": {}}
        task = SimpleNamespace(id=item["id"], title=item["text"], description=f"The finished thing: {item['text']}",
                               acceptance=item["text"])
        j = prooflib.judge(self.cfg, task, prs, None, self.budget, project_root=root, after_rec=rec, spent=0.0,
                           settings=prooflib.Settings.from_config(self.cfg))  # inside the proof's own cap
        ev = {"pictures": [f".harness/shots/{name}/{p['after']}" for p in prs if p.get("after")][:3],
              "verdict": j.get("verdict"), "problems": j.get("problems") or []}
        if j.get("looked") and j.get("verdict") == "shows_it":
            return {"passed": True, "words": j.get("what_changed") or "A model that can see says it shows.", "evidence": ev}
        if j.get("looked") and j.get("verdict") == "does_not":
            return {"passed": False, "words": "A model that can see says it doesn't show: "
                                              + "; ".join(j.get("problems") or [j.get("what_changed") or ""])[:300],
                    "evidence": ev}
        return {"passed": None, "words": j.get("words") or "Nobody could look.", "evidence": ev}

    # -- the estimate ---------------------------------------------------------------------------------------
    def _finish_estimate(self, tasks: list) -> dict[str, Any] | None:
        """One round of checks plus a share of fix work: "checking it works and fixing what breaks: about $X"."""
        from ..providers.base import Usage
        from . import plandoc

        s = self._finish_settings()
        if not s.enabled:
            return None
        planner = self.cfg.roles.get(self.cfg.planner_role)
        plan_cost = (self.cfg.cost(planner.models[0], Usage(*FIX_PLAN_TOKENS)) if planner and planner.models else 0) or 0.0
        coder = next((self.cfg.roles[t.role] for t in tasks if t.role in self.cfg.roles
                      and self.cfg.roles[t.role].kind == "chat"), None)
        task_cost = 0.0
        if coder and coder.models:
            i, o = plandoc.DEFAULT_TOKENS["chat"]
            task_cost = (self.cfg.cost(coder.models[0], Usage(i, o)) or 0.0) * 1.4
        usd = min(s.max_usd, plan_cost + task_cost) if s.rounds and s.max_fix_tasks else 0.0
        minutes = 2.0 + (plandoc.DEFAULT_MINUTES.get("chat", 4.0) if usd else 0.0)
        return {"id": "finish", "usd": round(usd, 4), "minutes": minutes,
                "words": f"checking it works and fixing what breaks: about ${usd:.2f}"}
