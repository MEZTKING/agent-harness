"""The Look stage of the Orchestrator: directions to choose from, the design file, the restyle task.

A mixin, so ``orchestrator.py`` stays about planning and running. It uses the Orchestrator's
project, config, model calls, git and hub helpers.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.models import utcnow
from ..providers.base import ToolSpec
from . import look as looklib
from . import plandoc
from .tools import READ_ONLY, Tool

LOOK_IDS = "ABCDEFGH"
RESTYLE_TITLE = "Restyle the app in the chosen look"


class LookStage:
    # -- roles -------------------------------------------------------------------------------
    def _design_role(self):
        return self.cfg.roles.get(self.cfg.design_role or "") or self.cfg.roles[self.cfg.planner_role]

    def _coder_role(self) -> str:
        if "coder" in self.cfg.roles and self.cfg.roles["coder"].kind == "chat":
            return "coder"
        busy = {self.cfg.planner_role, self.cfg.reviewer_role, self.cfg.critic_role, self.cfg.design_role}
        return next((r.name for r in self.cfg.roles.values() if r.kind == "chat" and r.name not in busy),
                    self.cfg.planner_role)

    def _look_wanted(self, doc: dict[str, Any]) -> bool:
        return self.cfg.look_stage == "auto" and bool(doc.get("has_ui")) and not (doc.get("look") or {}).get("directions")

    # -- other projects' looks -----------------------------------------------------------------
    def _used_looks(self) -> list[dict[str, Any]]:
        """The looks chosen in the owner's other projects, so a new one isn't the same again."""
        if not self.cfg.lab_dir:
            return []
        try:
            from ..improve.lab import Lab

            dirs = Lab(self.cfg.lab_dir).projects()
        except Exception:
            return []
        out = []
        for p in dirs:
            if p.resolve() == self.project.root:
                continue
            try:
                look = (json.loads((p / ".harness" / "plan.json").read_text(encoding="utf-8")) or {}).get("look") or {}
            except (OSError, ValueError):
                continue
            d = next((x for x in look.get("directions", []) if x.get("id") == look.get("chosen")), None)
            if d:
                out.append({"project": p.name, **looklib.summary(d)})
        return out

    # -- making directions -----------------------------------------------------------------------
    def _design_call(self, job: str, count: int, ids: list[str]) -> list[dict[str, Any]]:
        """One designer call that must end in a valid submit_looks; returns the checked directions."""
        role = self._design_role()
        captured: dict[str, Any] = {}
        errors: list[str] = []

        def submit_looks(args: dict) -> str:
            try:
                captured["looks"] = looklib.validate_looks(args.get("directions"), count, ids)
            except ValueError as e:
                errors.append(str(e))
                raise Exception(f"looks rejected: {e}. Fix it and call submit_looks again.")
            return f"{count} look(s) accepted"

        box = self.ws.toolbox(READ_ONLY)
        box.add(Tool(ToolSpec("submit_looks", "Submit the visual directions. Call once when they are complete.",
                              looklib.submit_schema()), submit_looks, terminal=True))
        prompt = f"{plandoc.context_text(self.project.plan_doc())}\n\n{job}"
        self.emit("look_start", {"model": str(role.models[0]), "count": count})
        res = self._run_with_fallback(role, self.cfg.prompt_text("designer"), prompt, box,
                                      require="submit_looks", done=lambda: "looks" in captured)
        if "looks" not in captured:
            from .orchestrator import HarnessError

            raise HarnessError(f"the designer didn't send usable looks ({'; '.join(errors[-1:]) or res.stop})")
        return captured["looks"]

    def _looks_job(self, brief: str, count: int) -> str:
        used = self._used_looks()
        used_text = "\n".join(f"- {u['project']}: {u['name']} (accents {', '.join(u['accents'])}; display font "
                              f"{u['display_font']})" for u in used)
        return (
            f"# Your job\nDesign {count} clearly different visual directions for this project's app, with ids "
            f"{', '.join(LOOK_IDS[:count])}. For each, a mockup of the app's main screen as one static HTML page.\n"
            + (f"\n# The owner's starting point\n{brief}\n" if brief else "")
            + (f"\n# Looks already used in the owner's other projects\n{used_text}\nDon't reuse these names, accent "
               "colours or display fonts" + (" unless the owner's starting point asks for it" if brief else "") + ".\n"
               if used else "")
            + "\nCall submit_looks with all of them.")

    def _save_mockups(self, looks: list[dict[str, Any]]) -> dict[str, Any]:
        out = self.project.dir / "look"
        out.mkdir(parents=True, exist_ok=True)
        for d in looks:
            (out / f"{d['id']}.html").write_text(d.pop("mockup_html"), encoding="utf-8")
            d["mockup"] = f".harness/look/{d['id']}.html"
        shots = looklib.render_mockups(out, [d["id"] for d in looks])
        self.emit("look_pictures", {"note": shots["note"]})
        return shots

    def look(self, brief: str = "", count: int = 3, publish: bool = True) -> dict[str, Any]:
        """Ask the design role for ``count`` different looks and put them in the plan for the owner to choose."""
        from .orchestrator import HarnessError

        doc = self.project.plan_doc()
        if not doc:
            raise HarnessError("this project has no plan yet: make the plan first")
        count = max(1, min(int(count), len(LOOK_IDS)))
        looks = self._design_call(self._looks_job(brief.strip(), count), count, list(LOOK_IDS[:count]))
        shots = self._save_mockups(looks)
        doc = self.project.plan_doc() or doc
        old = doc.get("look") or {}
        doc["look"] = {"directions": looks, "chosen": None, "note": "", "brief": brief.strip()[:1000],
                       "pictures": shots["pictures"], "render_note": shots["note"], "at": utcnow(),
                       "applied": old.get("applied"), "applied_note": old.get("applied_note", "")}
        self.project.save_plan_doc(doc)
        self.emit("looks", {"looks": [f"{d['id']} {d['name']}" for d in looks], "pictures": len(shots["pictures"])})
        if publish:
            self._publish_plan()
        return {"looks": [{"id": d["id"], "name": d["name"], "mood": d["mood"]} for d in looks],
                "pictures": shots["note"]}

    def _look_stage(self) -> None:
        """After the first plan: offer looks when the project has screens (never fail the plan over it)."""
        from .agent import BudgetExceeded
        from .orchestrator import HarnessError

        doc = self.project.plan_doc()
        if not doc or not self._look_wanted(doc):
            return
        try:
            self.look(publish=False)
        except (HarnessError, BudgetExceeded) as e:
            self.emit("looks", {"error": str(e)[:300]})

    # -- choosing and applying ---------------------------------------------------------------------
    def _choose_look(self, doc: dict[str, Any], kw: dict[str, Any], note) -> None:
        from .orchestrator import HarnessError

        look = doc.get("look") or {}
        iid = str(kw.get("id", "")).strip().upper()
        d = next((x for x in look.get("directions", []) if x["id"] == iid), None)
        if not d:
            raise HarnessError(f"no look {iid!r} in the plan" if look.get("directions") else
                               "there are no looks yet: make them first")
        look["chosen"], look["note"] = iid, str(kw.get("note", "")).strip()[:1000]
        note(f"The owner chose the look {iid} '{d['name']}'" + (f", with this note: {look['note']}" if look["note"] else "")
             + ". Its design file is design/DESIGN.md; style every screen with it.", "look")

    def _look_changed(self, doc: dict[str, Any]) -> bool:
        look = doc.get("look") or {}
        return bool(look.get("chosen")) and (look.get("applied") != look["chosen"]
                                             or look.get("note", "") != look.get("applied_note", ""))

    def _adjust_look(self, d: dict[str, Any], note: str) -> dict[str, Any]:
        """One designer call: the chosen direction changed as the owner's note asks. Keeps the old one on failure."""
        from .agent import BudgetExceeded
        from .orchestrator import HarnessError

        current = {k: v for k, v in d.items() if k not in ("mockup",)}
        html = self.project.dir / "look" / f"{d['id']}.html"
        current["mockup_html"] = html.read_text(encoding="utf-8") if html.is_file() else ""
        job = (f"# Your job\nThe owner chose this direction and wrote: {note}\nChange it as the note asks and keep "
               f"everything else. Send it back as one direction with id {d['id']}, with its updated mockup.\n\n"
               f"# The chosen direction\n{json.dumps(current, ensure_ascii=False)[:30000]}\n\nCall submit_looks.")
        try:
            new = self._design_call(job, 1, [d["id"]])
        except (HarnessError, BudgetExceeded) as e:
            self.emit("looks", {"error": f"couldn't adjust the look: {str(e)[:300]}"})
            return d
        shots = self._save_mockups(new)
        doc = self.project.plan_doc()
        look = doc["look"]
        look["directions"] = [new[0] if x["id"] == d["id"] else x for x in look["directions"]]
        look.setdefault("pictures", {}).update(shots["pictures"])
        self.project.save_plan_doc(doc)
        return new[0]

    def apply_look(self) -> dict[str, Any]:
        """Write the chosen look into the project (design/DESIGN.md, design/tokens.css), commit it, and add
        a restyle task when screens have already been built."""
        from .orchestrator import HarnessError

        doc = self.project.plan_doc() or {}
        look = doc.get("look") or {}
        d = next((x for x in look.get("directions", []) if x["id"] == look.get("chosen")), None)
        if not d:
            raise HarnessError("choose a look first")
        note = look.get("note", "")
        if note and note != look.get("applied_note", ""):
            d = self._adjust_look(d, note)
        design = self.project.root / "design"
        design.mkdir(parents=True, exist_ok=True)
        (design / "DESIGN.md").write_text(looklib.design_markdown(d, note), encoding="utf-8")
        (design / "tokens.css").write_text(looklib.tokens_css(d), encoding="utf-8")
        if self.cfg.git and (self.project.root / ".git").exists():
            self._git_commit(f"Design: the look '{d['name']}'")
        task = self._restyle_task(d)
        doc = self.project.plan_doc()
        doc["look"].update(applied=d["id"], applied_note=note)
        self.project.save_plan_doc(doc)
        self.emit("look_applied", {"look": d["id"], "name": d["name"], "task": task})
        self._publish_plan()
        return {"look": d["id"], "name": d["name"], "files": [looklib.DESIGN_FILE, looklib.TOKENS_FILE], "task": task}

    def _restyle_task(self, d: dict[str, Any]) -> str | None:
        """When work is already done on screens, one task restyles them (an open one is updated instead)."""
        from .orchestrator import Task

        tasks = self.project.tasks()
        if not any(t.status == "done" for t in tasks) or not looklib.ui_files(self.project.root):
            return None
        desc = (f"Restyle the existing app in the chosen look '{d['name']}'. Read design/DESIGN.md first. Link "
                "design/tokens.css on every page (or copy its values into the platform's theme once) and replace "
                "every hard-coded colour, font and corner radius with its token. Add the signature detail: "
                f"{d['signature']} Keep how everything works exactly as it is.")
        acc = ("No colour codes or font names outside design/tokens.css (the design check finds none in the "
               "changed files); every screen uses the look's colours, fonts and corners; the app works as before.")
        open_ = next((t for t in tasks if t.title == RESTYLE_TITLE and t.status in ("pending", "failed")), None)
        if open_:
            open_.description, open_.acceptance, open_.status = desc, acc, "pending"
        else:
            n = 1
            while any(t.id == f"L{n}" for t in tasks):
                n += 1
            open_ = Task(id=f"L{n}", title=RESTYLE_TITLE, role=self._coder_role(), description=desc, acceptance=acc,
                         goal_index=(self.project.plan_doc() or {}).get("goal_index", 0), section="look")
            tasks.append(open_)
        self.project.save_tasks(tasks)
        return open_.id

    # -- what tasks and reviews are told -----------------------------------------------------------
    def _design_context(self) -> str:
        return looklib.design_text(self.project.root)

    def _design_findings(self) -> str:
        if not (self.project.root / looklib.DESIGN_FILE).is_file():
            return ""
        return looklib.findings_text(looklib.check_tokens(self.project.root))

    def _look_pictures(self) -> dict[str, bytes]:
        """The look pictures for the hub: {file name: png bytes} (desktop and phone sizes)."""
        look = (self.project.plan_doc() or {}).get("look") or {}
        out = {}
        for names in (look.get("pictures") or {}).values():
            for name in names:
                p = self.project.dir / "look" / name
                if p.is_file():
                    out[name] = p.read_bytes()
        return out
