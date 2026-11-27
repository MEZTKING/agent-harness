"""Ship it: at the end the installer, APK or mod is really built, checked and started once.

A mixin, like the other stages (hooked up as a base of ``Orchestrator``). The recipes are data on the kind
and its extras (``ship:``, checked by kinds/model.py; read by harness/ship.py):

* ``_ship_plan_part()`` tells the planner exactly what this machine can build, and why not for the rest
  ("No Windows here: the EXE can't be built on this machine").
* ``_ship_estimate(tasks)`` adds the build time, and money only for the one fix task a failed build may need.
* ``_ship_step(tasks)`` (an end step) builds each target once, checks the file (there, not empty, the right
  first bytes), starts it once (an EXE must stay up 10 seconds and is then ended with everything it started;
  an APK is checked with the SDK's own tools and installed only on an emulator that is already running; a mod
  jar must hold its mod file) and records ``ship:<target>`` in the done list. A failed build becomes one fix
  task per target (``add_tasks(by="ship")``, then "again"); after that it is a failed done item for the gate.
  A target this machine can't build is ``unchecked`` with a plain reason, never dropped, and not a must
  (so it never stops the project being called done).

Whose commands run: a built-in recipe runs under the project's own "Ask me first" rules. A recipe from the
owner's own or an imported kind always waits for the owner's "Allow" the first time in each project, with the
exact command shown, even when the project never asks. Every command goes through ``Workspace.run_command``
(the gate, the environment with no keys, live output). Never: signing with a real key, installing on a
plugged-in phone, uploading or publishing.

``.harness/ship.json`` keeps what happened: {"fixes": {"<goal>:<target>": [task ids]}, "allowed": [commands],
"results": {target: {state, words, path, at}}}.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .. import prereq
from ..core.models import utcnow
from . import donelist, ship
from .gate import Finding, Gate, normalise
from .tools import ToolError

STATE_FILE = "ship.json"
BUILD_MINUTES = {"apk": 6.0, "exe": 5.0, "jar": 4.0}
ASK_REASON = "it comes from a kind you added, not one built into the harness (asked once in each project)"


class _AskEveryTime(Gate):
    """The project's gate, but this one command always asks (a recipe from a kind that isn't built in)."""

    def needs(self, command: str, mode: str | None = None) -> list[Finding]:
        whole = normalise(command)
        return [Finding(ASK_REASON, whole, True, whole)]


class _AlreadyAllowed:
    """The owner allowed this exact command a moment ago: the run itself doesn't ask again."""

    waited = 0.0

    def check(self, command: str) -> str | None:
        return None


class ShipStage:
    ship_system: prereq.System | None = None  # tests: a made-up computer (None: this one)
    ship_smoke_seconds: float = ship.SMOKE_SECONDS

    # -- what's here ------------------------------------------------------------------------------------
    def _ship_recipes(self) -> list[dict[str, Any]]:
        kind = self._kind() if callable(getattr(self, "_kind", None)) else None
        return ship.recipes(kind)

    def _ship_machine(self) -> tuple[str, list[dict[str, Any]]]:
        """This machine's system ("windows", "mac", "linux") and its tools (prereq.status rows)."""
        s = self.ship_system
        rows = prereq.status(s) if s is not None else prereq.status()
        return (s.os if s is not None else prereq._os_name()), rows

    def _ship_shell_os(self) -> str:
        """The system whose shell runs the commands (always this computer's, even with a made-up one)."""
        return prereq._os_name()

    def _ship_state_path(self) -> Path:
        return self.project.root / ".harness" / STATE_FILE

    def _ship_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self._ship_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        for k, empty in (("fixes", {}), ("allowed", []), ("results", {})):
            if not isinstance(data.get(k), type(empty)):
                data[k] = copy.copy(empty)
        return data

    def _ship_save(self, data: dict[str, Any]) -> None:
        p = self._ship_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".ship.json.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)

    # -- the planner -----------------------------------------------------------------------------------
    def _ship_plan_part(self) -> str:
        recipes = self._ship_recipes()
        if not recipes:
            return ""
        os_name, rows = self._ship_machine()
        names = {r["id"]: r["name"] for r in rows}
        out = ["", "# How it ships, on this machine", f"This machine runs {ship.OS_WORDS.get(os_name, os_name)}."]
        for r in recipes:
            ok, why = ship.can_build(r, rows, os_name)
            if ok:
                tools = ", ".join(names.get(n, n) for n in r["needs"]) or "nothing extra"
                out.append(f"- {r['name']}: it can be built here ({tools} found). At the end the harness runs "
                           f"`{ship.for_os(r['build'], os_name)}` and checks `{r['artefact']}`, so plan the last "
                           f"task to make exactly that work.")
            else:
                missing = ship.missing_tools(r, rows)
                offer = (f" The owner is offered {' and '.join(names.get(n, n) for n in missing)} to install."
                         if missing else "")
                out.append(f"- {r['name']}: {why} Still plan it so it builds where it can; it is marked "
                           f"not checked, never dropped.{offer}")
        out.append("- Never plan signing with a real key, installing on a plugged-in phone, uploading or publishing.")
        return "\n".join(out) + "\n"

    # -- the estimate ------------------------------------------------------------------------------------
    def _ship_estimate(self, tasks: list) -> dict[str, Any] | None:
        recipes = self._ship_recipes()
        if not recipes:
            return None
        os_name, rows = self._ship_machine()
        here = [r for r in recipes if ship.can_build(r, rows, os_name)[0]]
        minutes = sum(BUILD_MINUTES.get(r["target"], 4.0) for r in here)
        usd = self._ship_fix_usd() * len(here)
        words = (f"Building {' and '.join(r['name'] for r in here)} and starting it once"
                 + (f"; if a build breaks, one fix task each (up to about ${usd:.2f})" if usd else "")
                 if here else "Nothing can be built on this machine: marked not checked")
        return {"id": "ship", "usd": round(usd, 4), "minutes": minutes, "words": words}

    def _ship_fix_role(self) -> str:
        roles = self.cfg.roles
        if "coder" in roles:
            return "coder"
        for name, r in roles.items():
            if r.kind == "chat" and name not in (self.cfg.reviewer_role, "orchestrator"):
                return name
        return next(iter(roles))

    def _ship_fix_usd(self) -> float:
        from ..providers.base import Usage
        from .plandoc import DEFAULT_TOKENS

        try:
            role = self.cfg.roles[self._ship_fix_role()]
            cost = self.cfg.cost(role.models[0], Usage(*DEFAULT_TOKENS["chat"]))
        except Exception:  # noqa: BLE001 - an unpriced model: no money line
            return 0.0
        return float(cost or 0.0) * 1.4

    # -- running one command -----------------------------------------------------------------------------
    def _ship_run(self, command: str, timeout: float, recipe: dict[str, Any]) -> dict[str, Any]:
        """{code, text, timed_out, refused}: one command through the workspace's run_command."""
        ws = copy.copy(self.ws)
        ws.command_timeout = max(int(getattr(ws, "command_timeout", 120) or 120), int(timeout))
        ws.live = (self.project.root, "ship")
        if ship.asks_first(recipe):
            st = self._ship_state()
            if command not in st["allowed"]:
                base = getattr(self.ws, "gate", None)
                g = _AskEveryTime(self.project.root, getattr(base, "cfg", self.cfg),
                                  on_change=getattr(base, "on_change", None), context=getattr(base, "context", None),
                                  poll=getattr(base, "poll", 0.5), timeout=getattr(base, "timeout", None))
                refused = g.check(command)
                if base is not None:
                    base.waited = getattr(base, "waited", 0.0) + g.waited
                if refused:
                    return {"code": None, "text": "", "timed_out": False, "refused": refused}
                st = self._ship_state()
                st["allowed"] = [*st["allowed"], command]
                self._ship_save(st)
            ws.gate = _AlreadyAllowed()
        try:
            text = ws.run_command({"command": command, "timeout": max(1, int(timeout))})
        except ToolError as e:
            msg = str(e)
            timed = "timed out" in msg
            refused = "" if timed else msg  # the owner said no or pressed Stop: not a broken build
            return {"code": None, "text": msg, "timed_out": timed, "refused": refused}
        return {"code": ship.exit_code(text), "text": text, "timed_out": False, "refused": ""}

    # -- the end step -----------------------------------------------------------------------------------------
    def _ship_step(self, tasks: list) -> str | None:
        recipes = self._ship_recipes()
        if not recipes:
            return None
        os_name, rows = self._ship_machine()
        root = self.project.root
        goal = self._ship_goal()
        again = False
        for r in recipes:
            item_id = f"ship:{r['target']}"
            have = next((i for i in donelist.read(root)["items"] if i["id"] == item_id), None)
            if have and have.get("state") == "passed":
                continue
            ok, why = ship.can_build(r, rows, os_name)
            # a target this machine can't build never traps the project: it is shown as not checked, with
            # the reason, and isn't a must until the machine can build it (unchecked items never block)
            if have is None or bool(have.get("must", True)) != ok:
                donelist.add_item(root, {"id": item_id, "text": f"The {r['name']} is built and starts",
                                         "how": "command", "must": ok, "by": "kind",
                                         "command": r["build"], "path": r["artefact"]})
            for same in self._ship_same_file(r):  # an extra's own "The EXE was built" follows the same rule
                if bool(same.get("must", True)) != ok and same.get("by") != "owner":
                    donelist.add_item(root, {k: v for k, v in same.items()
                                             if k not in ("state", "words", "evidence", "checked_by", "checked_at")}
                                      | {"must": ok})
            if not ok:
                self._ship_result(r, None, why, {"reason": "machine"})
                continue
            got = self._ship_one(r, os_name, rows)
            if got["passed"]:
                self._ship_result(r, True, got["words"], got["evidence"])
                continue
            if got.get("refused"):
                self._ship_result(r, None, got["words"], got["evidence"])
                continue
            self._ship_result(r, False, got["words"], got["evidence"])
            if self._ship_fix(r, goal, got):
                again = True
        return "again" if again else None

    def _ship_goal(self) -> int:
        try:
            doc = self.project.plan_doc() or {}
            goals = self.project.meta().get("goals") or [""]
            return int(doc.get("goal_index", len(goals) - 1))
        except Exception:  # noqa: BLE001
            return 0

    def _ship_same_file(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        """Other done-list items that only ask for the file this recipe builds (an extra's proof line)."""
        return [i for i in donelist.read(self.project.root)["items"]
                if i.get("how") == "file_exists" and i.get("path") == r["artefact"] and i["id"] != f"ship:{r['target']}"]

    def _ship_result(self, r: dict[str, Any], passed: bool | None, words: str, evidence: dict[str, Any]) -> None:
        item_id = f"ship:{r['target']}"
        donelist.record(self.project.root, item_id, passed, words, evidence, by="ship")
        for same in self._ship_same_file(r):
            donelist.record(self.project.root, same["id"], passed, words, evidence, by="ship")
        st = self._ship_state()
        st["results"][r["target"]] = {"state": "unchecked" if passed is None else ("passed" if passed else "failed"),
                                      "words": words, "path": evidence.get("path", ""), "at": utcnow()}
        self._ship_save(st)
        self.emit("ship", {"target": r["target"], "name": r["name"], "passed": passed, "words": words})

    def _ship_one(self, r: dict[str, Any], os_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Build, check the file, start it once: {passed, words, evidence, refused?, output?}."""
        root = self.project.root
        cmd = ship.for_os(r["build"], self._ship_shell_os())
        b = self._ship_run(cmd, r["timeout"], r)
        if b["refused"] and b["code"] is None and not b["timed_out"]:
            return {"passed": False, "refused": True, "evidence": {"command": cmd},
                    "words": f"Not built: its build command didn't run ({b['refused'][:200]})."}
        if b["timed_out"]:
            return {"passed": False, "evidence": {"command": cmd}, "output": b["text"],
                    "words": f"The build took longer than {r['timeout'] // 60} minutes and was stopped."}
        if b["code"] != 0:
            return {"passed": False, "evidence": {"command": cmd, "exit": b["code"]}, "output": b["text"],
                    "words": f"The build failed (exit code {b['code']})."}
        a = ship.check_artefact(root, r)
        ev = {"command": cmd, "path": a["path"], "size": a["size"]}
        if not a["ok"]:
            return {"passed": False, "evidence": ev, "output": b["text"], "words": a["words"]}
        s = self._ship_smoke(r, root / a["path"], os_name, rows)
        ev["smoke"] = s["words"]
        if s.get("refused"):
            return {"passed": False, "refused": True, "evidence": ev, "words": f"{a['words']} {s['words']}"}
        return {"passed": s["ok"], "evidence": ev, "output": s.get("output", ""),
                "words": f"{a['words']} {s['words']}".strip()}

    def _ship_smoke(self, r: dict[str, Any], path: Path, os_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        how = r.get("smoke") or "none"
        secs = float(self.ship_smoke_seconds)
        if how == "none":
            return {"ok": True, "words": "Nothing more to start."}
        if how == "mod":
            return ship.mod_check(path)
        if how == "apk":
            return self._ship_apk(r, path, os_name, rows)
        # start /wait: cmd waits for a windowed program too, so the 10 seconds are the program's own
        cmd = (f'start "" /wait "{path}"' if self._ship_shell_os() == "windows" else f'"{path}"') \
            if how == "start" else how
        got = self._ship_run(cmd, secs, r)
        if got["refused"]:
            return {"ok": False, "refused": True, "words": f"It wasn't started: {got['refused'][:200]}"}
        if got["timed_out"]:
            return {"ok": True, "words": f"It started and was still running after {secs:g} seconds; "
                                         "then it was closed, with everything it started."}
        if how != "start" and got["code"] == 0:
            return {"ok": True, "words": "Its start check passed."}
        return {"ok": False, "output": got["text"],
                "words": f"It closed by itself straight after starting (exit code {got['code']})." if how == "start"
                else f"Its start check failed (exit code {got['code']})."}

    def _ship_apk(self, r: dict[str, Any], path: Path, os_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        first = ship.apk_check(path)
        if not first["ok"]:
            return first
        words = [first["words"]]
        sdk_row = next((x for x in rows if x.get("id") == "android" and x.get("state") == "found"), None)
        sdk = Path(sdk_row["where"]) if sdk_row and sdk_row.get("where") else None
        aapt = ship.sdk_tool(sdk, "aapt2", os_name)
        if aapt:
            got = self._ship_run(f'"{aapt}" dump badging "{path}"', 120, r)
            if got["code"] != 0:
                return {"ok": False, "output": got["text"],
                        "words": "The Android SDK's own check (aapt2) refused the APK."}
            words.append("The Android SDK's own check passed.")
        adb = ship.sdk_tool(sdk, "adb", os_name)
        if adb:
            dev = self._ship_run(f'"{adb}" devices', 60, r)
            emus = ship.emulators(dev["text"]) if dev["code"] == 0 else []
            if emus:  # only an emulator already running: never a plugged-in phone
                inst = self._ship_run(f'"{adb}" -s {emus[0]} install -r "{path}"', 300, r)
                if inst["code"] != 0:
                    return {"ok": False, "output": inst["text"],
                            "words": "It didn't install on the emulator that was running."}
                words.append(f"It installed on the running emulator ({emus[0]}).")
            else:
                words.append("No emulator was running, so it wasn't installed anywhere.")
        return {"ok": True, "words": " ".join(words)}

    def _ship_fix(self, r: dict[str, Any], goal: int, got: dict[str, Any]) -> bool:
        """One fix task per target and goal; after that the failed item waits for the done gate."""
        st = self._ship_state()
        key = f"{goal}:{r['target']}"
        if key in st["fixes"]:
            return False
        existing = {t.id for t in self.project.tasks()}
        n, tid = 1, f"SHIP-{r['target']}"
        while tid in existing:
            n += 1
            tid = f"SHIP-{r['target']}-{n}"
        output = ship.tail(got.get("output") or "")
        desc = (f"The harness tried to build the {r['name']} with `{got['evidence'].get('command') or r['build']}` "
                f"and check `{r['artefact']}`. It went wrong: {got['words']}\n\n"
                + (f"The end of what it printed:\n```\n{output}\n```\n\n" if output else "")
                + "Fix the project so that exact command builds it and the file lands there. Don't sign it with a "
                  "real key, upload or publish anything.")
        raw = [{"id": tid, "title": f"Make the {r['name']} build", "role": self._ship_fix_role(),
                "description": desc, "acceptance": f"`{r['build']}` finishes with exit code 0 and makes {r['artefact']}",
                "depends_on": []}]
        try:
            new = self.add_tasks(raw, by="ship", why=f"the {r['name']} didn't build: {got['words'][:150]}",
                                 fix_of=f"ship:{r['target']}")
        except Exception as e:  # noqa: BLE001 - past the cap, or the owner said no more: the gate decides
            self.emit("stage_error", {"stage": "_ship_step", "error": str(e)[:300]})
            st["fixes"][key] = []
            self._ship_save(st)
            return False
        st = self._ship_state()
        st["fixes"][key] = [t.id for t in new]
        self._ship_save(st)
        return True

    # -- for the app -------------------------------------------------------------------------------------------
    def ship_status(self) -> dict[str, Any]:
        """What happened to each target, short first: [{target, name, state, words}]."""
        st = self._ship_state()
        out = []
        for r in self._ship_recipes():
            res = st["results"].get(r["target"]) or {}
            out.append({"target": r["target"], "name": r["name"], "state": res.get("state", "open"),
                        "words": res.get("words", "Not built yet."), "path": res.get("path", "")})
        return {"targets": out}
