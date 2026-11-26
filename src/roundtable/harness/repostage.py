"""Repository mode and the project's own settings, the Orchestrator's side.

A mixin, like the Look stage. When Roundtable starts in a folder that is already a git repository
with at least one commit (one of the owner's apps), it works like a careful contributor:

- ``.harness/`` goes in ``.git/info/exclude``, never in the app's own ``.gitignore``;
- every commit lands on its own branch (``roundtable/<name>``), never on main, master or the branch
  the repository was on, and nothing is ever pushed;
- the repository's own rules (CLAUDE.md, AGENTS.md, the newest devlog entry) go to every model;
- the plan is for changes to an existing app; the Look step and Show it stay off unless it's a web app.

For any project, ``.harness/project.yaml`` (over ``roundtable.yaml``; ``projectsettings.py``) holds its
settings: its checks (``test``, ``env``, ``setup``, ``timeout``), which providers may see it, its
profile and limits. With a ``test`` command a baseline run is kept before the first task, and a
task is only blamed for failures that are new since then.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..core.models import utcnow
from . import checks as checkslib
from . import projectsettings as ps
from . import reporules
from . import showit

PROTECTED = ("main", "master")


class RepoStage:
    # -- settings ------------------------------------------------------------------------------------
    def project_settings(self) -> ps.ProjectSettings:
        return ps.load(self.project.root, list(self.base_cfg.profiles))

    def _settings_or_stop(self) -> ps.ProjectSettings:
        """The settings, or a plain error when the file has a mistake (a run never starts on a wrong guess)."""
        st = self.project_settings()
        if st.errors:
            from .orchestrator import HarnessError

            raise HarnessError("This project's settings have a mistake: " + "; ".join(st.errors)
                               + f". Fix it in {ps.PROJECT_FILE} (or the app's Settings), then run again.")
        for w in st.warnings:
            self.emit("settings_warning", {"warning": w})
        return st

    def _settings_profile(self) -> str | None:
        try:
            chosen = self.project_settings().values.get("profile")
        except Exception:  # never stop the app opening a project over its settings
            return None
        return chosen if chosen in self.base_cfg.profiles else None

    def _remember_profile(self, name: str) -> None:
        """The profile chosen in the app goes in project.yaml too, so the file always says what's used."""
        try:
            ps.update(self.project.root, {"profile": name}, list(self.base_cfg.profiles))
        except (OSError, ValueError) as e:
            self.emit("settings_warning", {"warning": f"profile not saved in project.yaml: {e}"})

    def _settle_cfg(self, cfg):
        """The config with this project's limits and allowed providers laid over it."""
        try:
            st = self.project_settings()
        except Exception:
            return cfg
        limits, allowed = st.values.get("limits") or {}, st.values.get("providers_allowed") or []
        if not limits and not allowed:
            return cfg
        c = cfg.variant()
        for k, v in limits.items():
            if hasattr(c.limits, k):
                setattr(c.limits, k, v)
        if allowed:
            for role in c.roles.values():
                role.models = [m for m in role.models if m.provider in allowed]
        return c

    def _require_models(self, role) -> None:
        """A role left with no model by ``providers_allowed`` stops the run with a message saying what to do."""
        if role.models:
            return
        from .orchestrator import HarnessError

        allowed = ", ".join(self.project_settings().values.get("providers_allowed") or []) or "none"
        raise HarnessError(
            f"This project may only use {allowed} (providers_allowed in its settings), and the role "
            f"'{role.name}' has no model from there. Give it one (roundtable assign {role.name} <provider>/<model>) "
            "or allow its provider in the project's settings, then run again.")

    def _ensure_settings_file(self) -> None:
        try:
            ps.ensure(self.project.root)
        except OSError as e:
            self.emit("settings_warning", {"warning": f"couldn't write {ps.PROJECT_FILE}: {e}"})

    # -- repository mode: detection ---------------------------------------------------------------------
    def _repo(self) -> dict[str, Any] | None:
        return self.project.meta().get("repository") if self.project.exists else None

    def _repo_mode(self) -> bool:
        return bool(self._repo())

    def _git_out(self, *args: str) -> tuple[int, str, str]:
        res = subprocess.run(["git", *args], cwd=self.project.root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        return res.returncode, res.stdout.strip(), res.stderr.strip()

    def _detect_repository(self) -> dict[str, Any] | None:
        """The folder is a git repository with at least one commit: one of the owner's own apps."""
        if not (self.project.root / ".git").exists():
            return None
        try:
            code, head, _ = self._git_out("rev-parse", "--verify", "-q", "HEAD")
        except OSError:
            return None
        if code != 0 or not head:
            return None
        _, branch, _ = self._git_out("symbolic-ref", "--short", "-q", "HEAD")
        _, dirty, _ = self._git_out("status", "--porcelain")
        return {"start_commit": head, "start_branch": branch, "dirty": bool(dirty), "detected_at": utcnow()}

    def _exclude_harness(self) -> None:
        """``.harness/`` in .git/info/exclude: the owner's .gitignore stays as it is."""
        _, rel, _ = self._git_out("rev-parse", "--git-path", "info/exclude")
        p = Path(rel or ".git/info/exclude")
        p = p if p.is_absolute() else self.project.root / p
        p.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        if ".harness/" not in text.splitlines():
            p.write_text(text + ("" if not text or text.endswith("\n") else "\n") + ".harness/\n", encoding="utf-8")

    # -- repository mode: the branch ------------------------------------------------------------------------
    def _branch_name(self, goal: str) -> str:
        from ..asks import slug

        wanted = (self.project_settings().values.get("branch") or "roundtable/").strip()
        name = f"{wanted}{slug(goal)}" if wanted.endswith("/") else wanted
        code, _, _ = self._git_out("check-ref-format", "--branch", name)
        if code != 0 or name in PROTECTED:
            from .orchestrator import HarnessError

            raise HarnessError(f"{name!r} can't be Roundtable's branch: choose another name for `branch` in the "
                               "project's settings (never main or master)")
        return name

    def _begin_repository(self, goal: str, info: dict[str, Any]) -> None:
        """Repository mode starts: note where the app was, then switch to Roundtable's own branch."""
        meta = self.project.meta()
        meta["repository"] = info
        self.project.save_meta(meta)
        if self.cfg.git:
            self._switch_to_branch(self._branch_name(goal))
        self.emit("repository", {"branch": self._repo().get("branch", ""), "from": info.get("start_branch", ""),
                                 "dirty": info.get("dirty", False)})

    def _switch_to_branch(self, name: str) -> None:
        from .orchestrator import HarnessError

        exists = self._git_out("rev-parse", "--verify", "-q", f"refs/heads/{name}")[0] == 0
        code, _, err = self._git_out("checkout", "-q", *([name] if exists else ["-b", name]))
        if code != 0:
            raise HarnessError(f"Couldn't switch the app to Roundtable's branch {name}: {err}. Commit or put away "
                               "your own changes in the app first, then try again.")
        meta = self.project.meta()
        meta["repository"]["branch"] = name
        meta["repository"]["branch_reused"] = exists
        self.project.save_meta(meta)

    def _guard_branch(self) -> None:
        """Before every commit in repository mode: on Roundtable's branch, never main, master or the start branch."""
        repo = self._repo()
        if not repo:
            return
        from .orchestrator import HarnessError

        branch = repo.get("branch")
        if not branch:
            self._switch_to_branch(self._branch_name((self.project.meta().get("goals") or ["work"])[0]))
            branch = self._repo()["branch"]
        _, current, _ = self._git_out("symbolic-ref", "--short", "-q", "HEAD")
        if current != branch:
            self._switch_to_branch(branch)
            _, current, _ = self._git_out("symbolic-ref", "--short", "-q", "HEAD")
        start = repo.get("start_branch") or ""
        protected = set(PROTECTED) | ({start} if start and start != branch else set())
        if current != branch or current in protected:
            raise HarnessError(f"Roundtable won't commit on {current or 'a detached HEAD'}: its work goes on {branch}. "
                               f"Switch the app to {branch} (git checkout {branch}), then run again.")

    def _card_status(self, status: str) -> str:
        repo = self._repo()
        return f"{status} · branch {repo['branch']}" if repo and repo.get("branch") else status

    # -- repository mode: the rules -----------------------------------------------------------------------------
    def _repo_rules_block(self) -> str:
        """The repository's rules and how to work in it; the same text all run long (cache-friendly)."""
        cached = getattr(self, "_rules_cache", None)
        if cached is not None:
            return cached
        repo = self._repo()
        if not repo:
            return ""
        st = self.project_settings().values
        pieces = reporules.read_rules(self.project.root, st.get("rules_files") or [], int(st.get("rules_budget") or 12000))
        branch = repo.get("branch") or "Roundtable's own branch"
        lines = [
            "# The repository's own rules (follow them)",
            f"This is the owner's existing app, in a git repository. Roundtable's work goes on the branch {branch}.",
            "- Work on the branch you're on. Never switch branches, push, open pull requests, tag or release.",
            "- Don't start paid CI or anything that costs money or reaches outside (no workflow runs, no deploys).",
            "- Where the rules below say to keep a devlog (or a changelog or handoff), add the entry for your change.",
            "- Keep changes small and in the app's own style; don't rewrite what works.",
        ]
        for title, text in pieces:
            lines += ["", f"## From {title}", text]
        if not pieces:
            lines += ["", "(The repository has no CLAUDE.md or AGENTS.md: follow the style of the code around you.)"]
        self._rules_cache = "\n".join(lines)
        return self._rules_cache

    def _with_repo_rules(self, system: str) -> str:
        block = self._repo_rules_block()
        return f"{system}\n\n{block}" if block else system

    def _repo_plan_note(self) -> str:
        """For the planner: an existing app, and the owner's notes for this project."""
        out = []
        repo = self._repo()
        if repo:
            out.append("# This is an existing app\nThe project is the owner's existing app in a git repository "
                       f"(Roundtable works on the branch {repo.get('branch') or 'of its own'}). Plan changes to it — "
                       "fixes, speed-ups, tidying — not a new build: read the code first, keep each task small and "
                       "checkable, keep what works, and follow the repository's own rules. Set has_ui only when the "
                       "task changes screens people look at.")
        notes = (self.project_settings().values.get("notes") or "").strip()
        if notes:
            out.append(f"# The owner's notes for this project\n{notes}")
        return "".join(f"{x}\n\n" for x in out)

    def _repo_critic_note(self) -> str:
        if not self._repo():
            return ""
        return ("This plan is for changes to an existing app (fix, speed up, tidy), not a new build: also flag "
                "tasks that rewrite working code, are too big to check, or ignore the repository's own rules.\n\n")

    def _repo_worker_parts(self) -> list[str]:
        parts = []
        st = self.project_settings().values
        test = st.get("test")
        if test:
            env = " ".join(f"{k}={v}" for k, v in (st.get("env") or {}).items())
            base = self.project.meta().get("baseline") or {}
            old = len(base.get("failing") or [])
            parts.append("# The project's checks\nBefore you finish, run the project's test command with run_command: "
                         f"`{test}`" + (f" (with these settings: {env})" if env else "") + ". The task is sent back if "
                         "it makes a test fail that passed before."
                         + (f" {old} test(s) were already failing before the run: not yours to fix unless your task "
                            "says so." if old else ""))
        return parts

    # -- the Look step and Show it --------------------------------------------------------------------------------
    def _is_web_app(self) -> bool:
        return showit.entry_page(self.project.root) is not None or showit.start_command(self.project.root) is not None

    def _look_wanted(self, doc: dict[str, Any]) -> bool:
        choice = self.project_settings().values.get("look", "auto")
        if (doc.get("look") or {}).get("directions") or choice == "off":
            return False
        if choice == "on":
            return True
        if self._repo_mode() and self.project.meta().get("look_step") is None and not self._is_web_app():
            return False
        return super()._look_wanted(doc)

    def _shots_wanted(self) -> bool:
        choice = self.project_settings().values.get("show_it", "auto")
        if choice == "off" or self.cfg.show_it == "off":
            return False
        if self._repo_mode() and choice == "auto":
            from . import godot as godotlib

            return self._is_web_app() or (self.cfg.godot.enabled and godotlib.project_dir(self.project.root) is not None)
        return super()._shots_wanted() or choice == "on"

    # -- the checks ------------------------------------------------------------------------------------------------
    def _prepare_run(self) -> str | None:
        """Before the first task of a run: the settings, the allowed providers, setup once, and the baseline.
        Returns a status to stop with (setup failed), else None."""
        from .orchestrator import HarnessError

        try:
            st = self._settings_or_stop()
            roles = {t.role for t in self.project.tasks() if t.status == "pending"} | {self.cfg.reviewer_role}
            for name in sorted(r for r in roles if r and r in self.cfg.roles):
                self._require_models(self.cfg.roles[name])
        except HarnessError as e:
            self._set_status("blocked", reason=str(e)[:500])
            raise
        meta = self.project.meta()
        values = st.values
        prev = meta.get("setup") or {}
        if values["setup"] and not (prev.get("command") == values["setup"] and prev.get("passed")):
            self.emit("setup_start", {"command": values["setup"]})
            res = checkslib.run(self.project.root, values["setup"], values["env"], values["timeout"])
            ok = res["exit_code"] == 0 and not res["timed_out"]
            meta = self.project.meta()
            meta["setup"] = {"command": values["setup"], "passed": ok, "at": utcnow(), "tail": res["output"][-2000:]}
            self.project.save_meta(meta)
            self.emit("setup", {"command": values["setup"], "passed": ok})
            if not ok:
                self._set_status("blocked")
                why = "took too long" if res["timed_out"] else f"stopped with code {res['exit_code']}"
                self._attention("setup", f"the project's setup command ({values['setup']}) {why}; fix it in the "
                                         f"project's settings or by hand, then run again")
                return "blocked"
            self._resolved("setup", note="setup worked")
        if values["test"] and (meta.get("baseline") or {}).get("command") != values["test"]:
            self._record_baseline(values)
        return None

    def _record_baseline(self, values: dict[str, Any]) -> dict[str, Any]:
        """The test command's result before any task changes anything: failures in it are never a task's fault."""
        self.emit("baseline_start", {"command": values["test"]})
        res = checkslib.run(self.project.root, values["test"], values["env"], values["timeout"])
        base = checkslib.summarise(res, self._head())
        done = [t.id for t in self.project.tasks() if t.status == "done"]
        if done:
            base["after_tasks"] = done  # the command changed after work was done: not a clean start
        meta = self.project.meta()
        meta["baseline"] = base
        self.project.save_meta(meta)
        self.emit("baseline", {"command": values["test"], "passed": base["passed"], "failing": len(base["failing"])})
        return base

    def _task_checks(self, task) -> dict[str, Any] | None:
        """Run the test command after a task; ``blame`` when it broke something that worked before the run."""
        values = self.project_settings().values
        if not values.get("test"):
            return None
        res = checkslib.run(self.project.root, values["test"], values["env"], values["timeout"])
        now = checkslib.summarise(res)
        base = self.project.meta().get("baseline")
        cmp = checkslib.compare(base, now)
        cmd = values["test"]
        verdict = cmp["verdict"]
        tail = checkslib.filtered_tail(now, cmp["old"])
        if verdict == "pass":
            text = f"# The project's checks\n`{cmd}` passed after this task."
        elif verdict == "old_only":
            text = (f"# The project's checks\n`{cmd}` still fails, but only on tests that were already failing "
                    f"before this run started ({len(cmp['old'])} of them). They are not this task's fault: don't "
                    "hold them against it.")
        elif verdict == "unknown":
            text = (f"# The project's checks\n`{cmd}` fails, and it was already failing before this run started; "
                    "its output can't be read test by test. Judge whether this task made it worse. The end of its "
                    f"output:\n```\n{tail}\n```")
        else:
            names = "".join(f"- {n}\n" for n in cmp["new"][:40])
            why = "it took longer than the time allowed" if now["timed_out"] else "it failed"
            text = (f"# The project's checks\n`{cmd}`: {why}, and "
                    + (f"these tests fail now that passed before the run started:\n{names}" if names
                       else "it passed before the run started.\n")
                    + f"The end of its output (failures from before the run left out):\n```\n{tail}\n```")
        self.emit("checks", {"task": task.id, "verdict": verdict, "new": cmp["new"][:20], "old": len(cmp["old"])})
        return {"verdict": verdict, "blame": verdict == "new", "text": text + "\n\n", "new": cmp["new"],
                "feedback": text.replace("# The project's checks\n", "The project's checks found a problem: ")
                + "\nFix this before finishing (run the command yourself to see it)."}
