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

Pictures (wave 8). While an EXE's smoke start runs, its window is found and pictured (``winshot``: Windows
only; elsewhere "not checked", never a failure); a window that stays one plain colour is "the window was
empty", which fails the item and makes its one fix task. An APK, when no emulator is running and this machine
can (``emulator.ready``), goes on an emulator the harness starts itself (no saved state, one at a time, never a
plugged-in phone), is opened, pictured with ``screencap`` and the emulator is stopped. Both pictures join the
proof like a page's: ``.harness/shots/ship-<target>/`` with its ``shots.json``. ``emulator: {start: false}`` in
harness.yaml leaves the emulator alone; ``winshot: {off: true}`` skips the window picture.

``.harness/ship.json`` keeps what happened: {"fixes": {"<goal>:<target>": [task ids]}, "allowed": [commands],
"results": {target: {state, words, path, at}}}.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any

from .. import prereq
from ..core.models import utcnow
from . import donelist, emulator, livecmd, ship, winshot
from .config import section
from .gate import Finding, Gate, normalise
from .tools import ToolError

STATE_FILE = "ship.json"
SHIP_OFFER_FILE = "ship-offer.json"  # a test phone offered and not yet answered (its card in asks.py)
BUILD_MINUTES = {"apk": 6.0, "exe": 5.0, "jar": 4.0}
EMULATOR_MINUTES = 4.0  # starting an emulator, installing, opening and picturing the app, stopping it
WINDOW_WAIT = 8.0  # seconds a started program's window is waited for
OPEN_SECONDS = 6.0  # seconds an app opened on the emulator gets before its picture
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
    ship_window_picture = None  # tests: a stand-in for winshot.window_picture(pid, out, wait=...)
    ship_emulator_ready = None  # tests: a stand-in for emulator.ready(rows, os_name)
    ship_emulator_start = None  # tests: a stand-in for emulator.start(avd, sdk, timeout=...)
    ship_open_seconds: float = OPEN_SECONDS

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
        if any(r.get("smoke") == "apk" for r in here) and self._ship_emulator_check(os_name, rows).get("can"):
            minutes += EMULATOR_MINUTES
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
        if (s.get("picture") or {}).get("file"):
            ev["picture"] = s["picture"]["file"]
        if s.get("refused"):
            return {"passed": False, "refused": True, "evidence": ev, "words": f"{a['words']} {s['words']}"}
        return {"passed": s["ok"], "evidence": ev, "output": s.get("output", ""), "empty": bool(s.get("empty")),
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
        shot: dict[str, Any] = {}
        watcher = None
        if how == "start" and r.get("target") == "exe" and not section(self.cfg, "winshot").get("off"):
            before = set(self._ship_live_pids())
            watcher = threading.Thread(target=self._ship_window, args=(r, before, min(WINDOW_WAIT, secs), shot),
                                       daemon=True, name="ship-window")
            watcher.start()
        got = self._ship_run(cmd, secs, r)
        if watcher is not None:
            watcher.join(timeout=WINDOW_WAIT + 10)
        if got["refused"]:
            return {"ok": False, "refused": True, "words": f"It wasn't started: {got['refused'][:200]}"}
        if got["timed_out"]:
            words = (f"It started and was still running after {secs:g} seconds; "
                     "then it was closed, with everything it started.")
            pic = shot.get("got") or {}
            if pic.get("state") == "empty":
                return {"ok": False, "empty": True, "picture": pic, "words": f"{words} {pic['why']}"}
            if pic:
                words += f" {pic.get('why', '')}"
            return {"ok": True, "picture": pic, "words": words.strip()}
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
                return self._ship_on_emulator(r, path, os_name, rows, adb, aapt, words)
        return {"ok": True, "words": " ".join(words)}

    # -- an emulator the harness starts itself ------------------------------------------------------------------
    def _ship_keep_offer(self, target: str, ready: dict[str, Any], os_name: str) -> None:
        """Keep the offer of a test phone for its one-tap card (asks.ship_offer_ask), until it is answered."""
        try:
            p = self.project.root / ".harness" / SHIP_OFFER_FILE
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"target": target, "offer": ready["offer"], "sdk": ready.get("sdk", ""),
                                     "os": os_name}, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    def _ship_emulator_check(self, os_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if section(self.cfg, "emulator").get("start") is False:
            return {"can": False, "why": "Starting an emulator is switched off in the settings.", "avds": []}
        try:
            return (self.ship_emulator_ready or emulator.ready)(rows, os_name)
        except Exception as e:  # noqa: BLE001 - a help, never a reason to fail
            return {"can": False, "why": f"Whether an emulator can start couldn't be checked ({str(e)[:200]}).",
                    "avds": []}

    def _ship_on_emulator(self, r: dict[str, Any], path: Path, os_name: str, rows: list[dict[str, Any]],
                          adb: Path, aapt: Path | None, words: list[str]) -> dict[str, Any]:
        """No emulator running: start one (if this machine can), install, open, picture, stop."""
        ready = self._ship_emulator_check(os_name, rows)
        if not ready.get("can"):
            words.append(f"No emulator was running, so it wasn't installed anywhere. {ready.get('why', '')}".strip())
            if ready.get("offer"):
                self.emit("ship_offer", {"target": r["target"], "offer": ready["offer"]})
                self._ship_keep_offer(r["target"], ready, os_name)
            return {"ok": True, "words": " ".join(words)}
        boot = float(section(self.cfg, "emulator").get("boot_seconds") or 240)
        try:
            emu = (self.ship_emulator_start or emulator.start)(ready["avd"], Path(ready["sdk"]), timeout=boot)
        except emulator.EmulatorError as e:
            words.append(f"An emulator was started to try it on, but: {e}")
            return {"ok": True, "words": " ".join(words)}  # the APK itself passed; the emulator is a help
        try:
            got = self._ship_emulator_steps(r, path, adb, aapt, words, emu, ready)
        finally:
            emu.stop()
        got["words"] = f"{got['words']} The emulator was stopped afterwards."
        return got

    def _ship_emulator_steps(self, r: dict[str, Any], path: Path, adb: Path, aapt: Path | None, words: list[str],
                             emu, ready: dict[str, Any]) -> dict[str, Any]:
        serial = emu.serial
        if not str(serial).startswith("emulator-"):  # never a plugged-in phone, whatever was handed back
            words.append("The emulator gave a serial that isn't an emulator's, so nothing was installed.")
            return {"ok": True, "words": " ".join(words)}
        inst = self._ship_run(f'"{adb}" -s {serial} install -r "{path}"', 300, r)
        if inst["code"] != 0:
            return {"ok": False, "output": inst["text"],
                    "words": " ".join([*words, "It didn't install on the emulator the harness started."])}
        words.append(f"It installed on an emulator the harness started ({ready['avd']}).")
        pkg = ""
        if aapt:
            b = self._ship_run(f'"{aapt}" dump badging "{path}"', 120, r)
            pkg = ship.package_name(b["text"]) if b["code"] == 0 else ""
        if not pkg:
            words.append("Its name couldn't be read, so it wasn't opened.")
            return {"ok": True, "words": " ".join(words)}
        op = self._ship_run(f'"{adb}" -s {serial} shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1',
                            60, r)
        if op["code"] != 0 or "No activities found" in op["text"] or "monkey aborted" in op["text"].lower():
            return {"ok": False, "output": op["text"],
                    "words": " ".join([*words, "It installed but wouldn't open."])}
        words.append("It opened.")
        time.sleep(max(0.0, float(self.ship_open_seconds)))
        pic = self._ship_phone_picture(r, adb, serial)
        if pic:
            words.append(pic)
        return {"ok": True, "words": " ".join(words)}

    def _ship_phone_picture(self, r: dict[str, Any], adb: Path, serial: str) -> str:
        out_dir = self._ship_shots_dir(r)
        out = out_dir / "phone.png"
        on_phone = "/sdcard/darkness-ship.png"
        cap = self._ship_run(f'"{adb}" -s {serial} shell screencap -p {on_phone}', 60, r)
        pull = self._ship_run(f'"{adb}" -s {serial} pull {on_phone} "{out}"', 60, r) if cap["code"] == 0 else cap
        if pull["code"] != 0 or not out.is_file():
            return "Its screen couldn't be pictured."
        empty = False
        try:
            from PIL import Image

            with Image.open(out) as im:
                empty = winshot.is_empty(im)
        except Exception:  # noqa: BLE001 - kept as it came
            pass
        self._ship_shots_record(r, out_dir, "phone", "Opened on an emulator the harness started")
        return ("Its screen was pictured, but it was one plain colour (it may still have been starting)." if empty
                else "Its screen was pictured.")

    # -- a program's window --------------------------------------------------------------------------------------
    def _ship_live_pids(self) -> list[int]:
        """The commands of this project's "ship" slot running now, newest last (livecmd's own list)."""
        root = str(self.project.root)
        with livecmd._lock:
            mine = [(r.get("n", 0), pid) for pid, r in livecmd._running.items()
                    if str(r.get("root")) == root and r.get("task") == "ship" and not r.get("stopped")]
        return [pid for _, pid in sorted(mine)]

    def _ship_window(self, r: dict[str, Any], before: set[int], wait: float, into: dict[str, Any]) -> None:
        """Wait for the smoke command to start, then picture its window (it runs while the command does)."""
        try:
            pid = 0
            end = time.monotonic() + 5.0
            while time.monotonic() < end:
                new = [p for p in self._ship_live_pids() if p not in before]
                if new:
                    pid = new[-1]
                    break
                time.sleep(0.05)
            out_dir = self._ship_shots_dir(r)
            if not pid:
                into["got"] = {"ok": False, "file": None, "state": "missing",
                               "why": "Its window wasn't pictured: the started program couldn't be found."}
                return
            got = (self.ship_window_picture or winshot.window_picture)(pid, out_dir / "window.png", wait=wait)
            into["got"] = got
            if got.get("file") and got.get("state") in ("passed", "empty"):
                self._ship_shots_record(r, out_dir, "window",
                                        "The window was empty" if got["state"] == "empty" else got.get("title", ""))
        except Exception as e:  # noqa: BLE001 - a picture is a help, never a reason for the start to fail
            into["got"] = {"ok": False, "file": None, "state": "failed",
                           "why": f"Its window couldn't be pictured ({str(e)[:200]})."}

    def _ship_shots_dir(self, r: dict[str, Any]) -> Path:
        from . import showit

        d = showit.shots_root(self.project.root) / f"ship-{r['target']}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ship_shots_record(self, r: dict[str, Any], out_dir: Path, kind: str, title: str) -> None:
        """The picture joins the proof like a page's: a ``shots.json`` beside it (not the Live tab's latest)."""
        from . import showit

        try:
            commit = showit.commit_of(self.project.root)
        except Exception:  # noqa: BLE001
            commit = ""
        record = {"task": f"ship:{r['target']}", "dir": out_dir.name, "at": utcnow(),
                  "seq": showit._next_seq(self.project.root), "commit": commit, "entry": None,
                  "title": str(title or r["name"])[:200], "pictures": {kind: f"{kind}.png"}, "errors": [],
                  "note": "", "ship": r["target"]}
        showit._write_record(out_dir, record, latest=False)
        self.emit("shots", {"task": record["task"], "dir": record["dir"], "pictures": [kind]})

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
        if got.get("empty"):
            raw = [{"id": tid, "title": f"Make the {r['name']} show its window", "role": self._ship_fix_role(),
                    "description": (f"The harness built the {r['name']} and started it. It ran, but its window stayed "
                                    f"one plain colour: {got['words']}\n\nFind out why nothing is drawn (a blank "
                                    "first screen, a page that doesn't load, drawing that fails) and fix it so the "
                                    "window shows the app straight after it starts."),
                    "acceptance": f"Started, the {r['name']} shows its first screen within a few seconds",
                    "depends_on": []}]
            return self._ship_fix_add(r, key, raw, got)
        desc = (f"The harness tried to build the {r['name']} with `{got['evidence'].get('command') or r['build']}` "
                f"and check `{r['artefact']}`. It went wrong: {got['words']}\n\n"
                + (f"The end of what it printed:\n```\n{output}\n```\n\n" if output else "")
                + "Fix the project so that exact command builds it and the file lands there. Don't sign it with a "
                  "real key, upload or publish anything.")
        raw = [{"id": tid, "title": f"Make the {r['name']} build", "role": self._ship_fix_role(),
                "description": desc, "acceptance": f"`{r['build']}` finishes with exit code 0 and makes {r['artefact']}",
                "depends_on": []}]
        return self._ship_fix_add(r, key, raw, got)

    def _ship_fix_add(self, r: dict[str, Any], key: str, raw: list[dict[str, Any]], got: dict[str, Any]) -> bool:
        st = self._ship_state()
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
