"""Local web UI for the hub (journal, cards, messages) and the harness
(projects, runs, models, probes, self-improvement).

Run:  roundtable ui   (or: roundtable ui)   ->  http://127.0.0.1:8765

Same code paths as the terminal commands, so the UI and CLI always agree.
Long actions (harness runs, probes, replay tests, analysis) run as background
jobs with live logs.

Safety: binds to 127.0.0.1 by default. State-changing requests must carry the
X-Agent-Hub header (blocks cross-site form posts) and a localhost Host header
(blocks DNS rebinding). Binding to another interface requires the access token
printed at start-up. The UI is an owner tool: it can act as any agent.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import secrets
import threading
import time
import traceback
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..core.models import utcnow
from ..core import secrets as vault
from ..brand import NAME

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _lines(raw) -> list[str]:
    """References from the form: a list, or text with one per line."""
    items = raw if isinstance(raw, list) else str(raw or "").splitlines()
    return [str(x).strip() for x in items if str(x).strip()][:20]


# Feature API modules under roundtable.ui: each has routes(app) -> {(method, path): fn}. A feature added
# side by side with others appends its module name here (one line each), nothing else in this file.
FEATURE_APIS: tuple[str, ...] = ("toolsapi", "automationapi", "notifyapi", "filesapi", "whatsnewapi", "tidyapi",
                                "searchapi", "attachapi", "rewindapi", "proofapi", "terminalapi", "moneyapi",
                                "websearchapi", "kindsapi", "doneapi", "stagesapi", "appapi", "councilapi",
                                "usageapi", "strengthsapi", "agentsapi", "tandemapi",
                                # wave 7: the learning wallet, the house style and charter, plug-ins and skills,
                                # what it learned, search by meaning and the owner's documents
                                "walletapi", "styleapi", "marketapi", "learnedapi", "recallapi",
                                # wave 8: change a file, git history, richer previews, the Browser; words as they
                                # are written, / commands, follow-ups, the queue; what each job may do; the board;
                                # work that starts from outside, one list of services, CI, moving the data
                                "editapi", "chatapi", "permsapi", "boardapi", "reachapi")


def _feature_routes(app) -> dict:
    import importlib

    out: dict = {}
    for name in FEATURE_APIS:
        out.update(importlib.import_module(f"roundtable.ui.{name}").routes(app))
    return out


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# -- background jobs ---------------------------------------------------------------
class Job:
    def __init__(self, jid: str, kind: str, title: str, target: str = ""):
        self.id, self.kind, self.title, self.target = jid, kind, title, target
        self.status = "running"
        self.log: list[str] = []
        self.result: Any = None
        self.error = ""
        self.started = utcnow()
        self.ended = ""

    def line(self, text: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {text}")
        del self.log[:-2000]

    def view(self, since: int = 0) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title, "target": self.target,
                "status": self.status, "started": self.started, "ended": self.ended, "error": self.error,
                "result": self.result, "log": self.log[since:], "log_size": len(self.log)}


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.busy: set[str] = set()  # targets with a running job (one run per project)
        self.lock = threading.Lock()

    def start(self, kind: str, title: str, fn: Callable[[Job], Any], target: str = "") -> Job:
        with self.lock:
            if target and target in self.busy:
                raise ApiError("Something is already running for this project. Wait for it to finish (Activity → Background work), then try again.", 409)
            job = Job(secrets.token_hex(4), kind, title, target)
            self.jobs[job.id] = job
            if target:
                self.busy.add(target)

        def run():
            final = "done"
            try:
                job.result = fn(job)
            except Exception as e:  # report, don't crash the server
                final = "failed"
                job.error = f"{type(e).__name__}: {e}"
                job.line(f"ERROR {job.error}")
                job.line(traceback.format_exc(limit=3).strip().splitlines()[-1])
            finally:
                with self.lock:  # free the slot and publish the outcome atomically
                    self.busy.discard(target)
                    job.ended = utcnow()
                    job.status = final

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job

    def list(self) -> list[dict[str, Any]]:
        out = [j.view(len(j.log)) | {"log_size": len(j.log)} for j in self.jobs.values()]
        return sorted(out, key=lambda j: j["started"], reverse=True)[:50]


def harness_event_line(kind: str, d: dict[str, Any]) -> str | None:
    if kind == "task_start":
        return f"▶ [{d['task']}] {d['title']} ({d['role']})"
    if kind == "attempt":
        return f"   attempt {d['attempt']} on {d['model']}"
    if kind == "tool_call":
        return f"      {'!' if d['error'] else '-'} {d['tool']} {json.dumps(d['args'])[:140]}"
    if kind == "model_turn" and d.get("text"):
        return f"      > {d['text'][:160]}"
    if kind == "review":
        return f"   review: {'approved' if d['approved'] else 'REJECTED'} - {d['feedback'][:240]}"
    if kind == "task_end":
        return f"{'✓' if d['status'] == 'done' else '✗'} [{d['task']}] {d['status']}: {d['summary'][:240]}"
    if kind == "plan":
        return "Plan:\n" + "\n".join(f"   {t}" for t in d["tasks"])
    if kind == "planning":
        return f"Planning with {d['model']}..."
    if kind == "look_start":
        return f"Designing {d['count']} look(s) with {d['model']}..."
    if kind == "looks":
        return f"Looks: {d['error']}" if d.get("error") else "Looks ready: " + ", ".join(d["looks"])
    if kind == "look_pictures":
        return f"   {d['note']}"
    if kind == "look_applied":
        return f"Look applied: {d['name']}" + (f" (restyle task {d['task']} added)" if d.get("task") else "")
    if kind == "shots":
        n = len(d.get("pictures") or [])
        return f"   pictures of the app: {n} taken" + (f", {d['errors']} page error(s)" if d.get("errors") else "") \
            + (f" ({d['note']})" if d.get("note") else "")
    if kind == "repository":
        return f"Working on your app on its own branch, {d['branch']} (from {d['from'] or 'a detached HEAD'}; never pushed)"
    if kind == "baseline":
        return (f"Checks before any change: {d['command']} " + ("passed" if d["passed"] else
                f"already fails ({d['failing']} test(s)); those won't be blamed on the tasks"))
    if kind == "checks":
        return f"   checks: {d['verdict']}" + (f" (new failures: {', '.join(d['new'][:5])})" if d.get("new") else "")
    if kind == "setup":
        return f"Set-up command {'worked' if d['passed'] else 'FAILED'}: {d['command']}"
    if kind == "settings_warning":
        return f"   settings: {d['warning']}"
    if kind == "provider_error":
        return f"   provider error ({d['model']}): {d['error'][:240]}"
    if kind == "status":
        return f"[status: {d['status']}]"
    if kind == "replay":
        return f"   replaying {d['project']}:{d['task']} with {d['variant']} setup"
    return None


# -- the application -----------------------------------------------------------------
class UIApp:
    def __init__(self, hub_config: str | None = None, harness_config: str | None = None,
                 agent: str | None = None, projects_dir: str | None = None):
        self.hub = None
        self.hub_error = ""
        self.hub_config_path = hub_config
        self.desktop: dict | None = None  # set by the desktop app: {"paths": Paths, "keys": KeyStore}
        self.harness_config_path = harness_config
        self.harness_error = ""
        self.hub_lock = threading.RLock()
        self.jobs = Jobs()
        self.reload_hub()
        self.agent = agent
        if self.hub and (not agent or agent not in self.hub.config.agents):
            agents = self.hub.config.agents
            self.agent = "me" if "me" in agents else next(iter(agents), None)
        self.projects_dir = Path(projects_dir or ".").expanduser().resolve()
        self.last_auto_sync = ""
        self.auto_sync_error = ""
        from ..desktop import app_home
        from ..phone import PhoneAccess

        self.phone = PhoneAccess(self, app_home())
        from .live import LivePreview

        self.preview = LivePreview(self._lab_projects)  # the apps themselves, on a port of their own
        self.cfg()  # validate early so the UI can show config errors

    def start_auto_sync(self, every_s: float = 60.0):
        from .roundtable import AutoSync

        self.auto_sync = AutoSync(self, every_s).start()
        return self.auto_sync

    def reload_hub(self) -> None:
        try:
            from ..core.config import load_config
            from ..hub.service import Hub

            with self.hub_lock:
                self.hub = Hub(load_config(self.hub_config_path))
                self.hub_error = ""
        except Exception as e:
            self.hub, self.hub_error = None, str(e)

    # -- shared helpers ----------------------------------------------------------------
    def cfg(self):
        """Fresh harness config each call, so edits and learned changes show immediately."""
        try:
            from ..harness.config import load_config

            cfg = load_config(self.harness_config_path)
            self.harness_error = ""
            return cfg
        except Exception as e:
            self.harness_error = str(e)
            return None

    def need_hub(self):
        if not self.hub:
            raise ApiError("The hub isn't set up on this computer yet. Connect it in Settings, then try again."
                           + (f" (What went wrong: {self.hub_error})" if self.hub_error else ""), 503)
        return self.hub

    def need_cfg(self):
        cfg = self.cfg()
        if not cfg:
            raise ApiError("The harness can't build projects on this computer yet: its settings file is missing or has a "
                           "problem. Open Settings to fix it."
                           + (f" (What went wrong: {self.harness_error})" if self.harness_error else ""), 503)
        return cfg

    def lab(self, cfg):
        from ..improve.lab import Lab

        if not cfg.lab_dir:
            raise ApiError("There's no folder for the harness's own records yet. Run the set-up again from Settings → "
                           "Advanced.", 503)
        return Lab(cfg.lab_dir)

    def _lab_projects(self) -> list[Path]:
        cfg = self.cfg()
        try:
            return [p.resolve() for p in self.lab(cfg).projects()] if cfg else []
        except ApiError:
            return []

    def project(self, cfg, path: str):
        """Only registered harness projects can be addressed (no arbitrary paths)."""
        from ..harness.orchestrator import Project

        p = Path(path or "").expanduser().resolve()
        if p not in [x.resolve() for x in self.lab(cfg).projects()]:
            raise ApiError("That project isn't on this computer (it may run on another one). Go back to the Hall and "
                           "refresh.", 404)
        return Project(p)

    # -- overview -------------------------------------------------------------------------
    def overview(self, q) -> dict[str, Any]:
        cfg = self.cfg()
        out: dict[str, Any] = {
            "hub": bool(self.hub), "hub_error": self.hub_error, "agent": self.agent,
            "harness": bool(cfg), "harness_error": self.harness_error,
            "projects_dir": str(self.projects_dir),
            "running_jobs": sum(j.status == "running" for j in self.jobs.jobs.values()),
        }
        if self.hub:
            out["hub_path"] = str(self.hub.config.path)
            from .hall import NOTES_NAME, friendly

            out["agents"] = [{"id": a, "repo": s.repo, "description": s.description, "role": s.role,
                              "name": NOTES_NAME if a == self.agent and not s.repo else friendly(a, s)}
                             for a, s in self.hub.config.agents.items()]
        if cfg:
            out["harness_path"] = str(cfg.path) if cfg.path else ""
        return out

    # -- journal ----------------------------------------------------------------------------
    def where(self, q) -> list[dict[str, Any]]:
        hub = self.need_hub()
        with self.hub_lock:
            hub.store.sync()
            briefs = [hub.journal.brief(a, a) for a in hub.config.agents]
        briefs.sort(key=lambda b: (b["last_activity"] or "", b["last_ts"]), reverse=True)
        return briefs

    def journal(self, q, agent: str) -> list[dict[str, Any]]:
        hub = self.need_hub()
        kinds = q.get("kind") or None
        with self.hub_lock:
            return hub.journal.entries(agent, agent, kinds=kinds, status=(q.get("status") or [None])[0])

    def journal_add(self, body, agent: str):
        hub = self.need_hub()
        with self.hub_lock:
            if body.get("kind") == "session":
                return hub.journal.session_end(agent, body.get("text", ""), body.get("next") or [], source="ui")
            return hub.journal.add(agent, body.get("kind", "note"), body.get("text", ""),
                                   priority=body.get("priority", "normal"), details=body.get("details", ""),
                                   source="ui")

    def journal_close(self, body, agent: str, entry_id: str):
        hub = self.need_hub()
        with self.hub_lock:
            return hub.journal.close(agent, entry_id, dropped=bool(body.get("dropped")), note=body.get("note", ""))

    # -- cards & messages -------------------------------------------------------------------
    def cards(self, q):
        hub = self.need_hub()
        with self.hub_lock:
            hub.store.sync()
            return [hub.get_card(a, a) for a in hub.config.agents]

    def card_update(self, body, agent: str):
        hub = self.need_hub()
        fields = {k: v for k, v in body.items() if k in ("summary", "goal", "status", "interfaces", "notes",
                                                         "repo", "depends_on") and v is not None}
        with self.hub_lock:
            return hub.update_card(agent, change_note=body.get("change_note") or None, **fields)

    def inbox(self, q, agent: str):
        hub = self.need_hub()
        with self.hub_lock:
            return hub.inbox(agent, unread_only=(q.get("all") or ["0"])[0] != "1", limit=200)

    def mark_read(self, body, agent: str):
        hub = self.need_hub()
        with self.hub_lock:
            return {"marked": hub.mark_read(agent, list(body.get("ids") or []))}

    def send(self, body):
        hub = self.need_hub()
        to = body.get("to") or []
        with self.hub_lock:
            return hub.send(body.get("from") or self.agent, to if isinstance(to, list) else [to],
                            body.get("subject", ""), body.get("body", ""), kind=body.get("kind", "ask"))

    def reply(self, body):
        hub = self.need_hub()
        with self.hub_lock:
            return hub.reply(body["as"], body["message_id"], body.get("body", ""))

    def thread(self, q):
        hub = self.need_hub()
        actor, tid = q["as"][0], q["thread"][0]
        with self.hub_lock:
            return hub.thread(actor, tid)

    # -- harness: roles & projects -------------------------------------------------------------
    def roles(self, q):
        cfg = self.need_cfg()
        learned = set()
        if cfg.lab_dir:
            overlay, _ = self.lab(cfg).learned()
            learned = set((overlay.get("roles") or {}).keys())
        return {
            "roles": [{"name": r.name, "kind": r.kind, "models": [str(m) for m in r.models], "description": r.description,
                       "options": r.options, "planner": r.name == cfg.planner_role,
                       "reviewer": r.name == cfg.reviewer_role, "learned": r.name in learned}
                      for r in cfg.roles.values()],
            "providers": {k: v.get("type") for k, v in cfg.providers.items()},
            "limits": asdict(cfg.limits), "improve": cfg.improve,
        }

    def projects(self, q):
        cfg = self.need_cfg()
        out = []
        for p in self.lab(cfg).projects():
            meta = json.loads((p / ".harness/project.json").read_text(encoding="utf-8"))
            tasks = json.loads((p / ".harness/tasks.json").read_text(encoding="utf-8") or "[]")
            counts: dict[str, int] = {}
            for t in tasks:
                counts[t["status"]] = counts.get(t["status"], 0) + 1
            running = any(j.target == str(p) and j.status == "running" for j in self.jobs.jobs.values())
            out.append({"path": str(p), "name": p.name, "status": meta.get("status"), "goals": meta.get("goals", []),
                        "spent_usd": meta.get("spent_usd", 0), "unpriced_calls": meta.get("unpriced_calls", 0),
                        "updated_at": meta.get("updated_at") or meta.get("created_at", ""), "tasks": counts,
                        "job_running": running})
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def project_detail(self, q):
        cfg = self.need_cfg()
        proj = self.project(cfg, q.get("path", [""])[0])
        events = []
        ev = proj.dir / "events.jsonl"
        if ev.is_file():
            for line in ev.read_text(encoding="utf-8").splitlines()[-300:]:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = harness_event_line(d.get("event", ""), d)
                if text:
                    events.append({"at": d.get("at", ""), "text": text})
        summary = proj.dir / "summary.md"
        from collections import defaultdict

        agg: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "approved": 0, "cost": 0.0})
        mp = proj.dir / "metrics.jsonl"
        if mp.is_file():
            for line in mp.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("outcome") == "owner_feedback":
                    continue
                a = agg[f"{r['role']} · {r['model']}"]
                a["attempts"] += 1
                a["approved"] += r["outcome"] == "approved"
                a["cost"] += r.get("cost_usd") or 0
        return {"path": str(proj.root), "name": proj.root.name, "meta": proj.meta(),
                "tasks": [asdict(t) for t in proj.tasks()], "events": events[-150:],
                "summary": summary.read_text(encoding="utf-8") if summary.is_file() else "",
                "metrics": [{"key": k, **v} for k, v in sorted(agg.items())],
                "files": self._files(proj.root)}

    def project_live(self, q):
        """The Live tab: the app's address on the preview server, its newest pictures and earlier ones."""
        from .live import live

        proj = self.project(self.need_cfg(), q.get("path", [""])[0])
        return live(proj.root, self.preview, inline=(q.get("inline") or ["0"])[0] == "1")

    def project_session(self, q):
        """The Session tab: each task's steps; ``since`` (the last cursor) answers 'nothing new' cheaply."""
        from .live import session_view

        cfg = self.need_cfg()
        proj = self.project(cfg, q.get("path", [""])[0])
        if (q.get("compact") or ["0"])[0] == "1":  # the phone: the latest task's steps as short lines
            from ..harness.session import hub_session

            return hub_session(proj.root, proj.root.name, cfg.reviewer_role)
        since = int((q.get("since") or ["0"])[0] or 0)
        return session_view(proj.root, cfg.reviewer_role, since)

    def project_settings_get(self, q):
        """The project's own settings (.harness/project.yaml over roundtable.yaml): each with its value, where it
        came from, what it does, its type and choices."""
        from ..harness import projectsettings as ps

        cfg = self.need_cfg()
        proj = self.project(cfg, (q.get("project") or q.get("path") or [""])[0])
        return {"path": str(proj.root), **ps.view(proj.root, list(cfg.profiles))}

    def project_settings_post(self, body):
        """Change settings: {project, changes: {key: value}}; a value of null or "" removes it from project.yaml."""
        from ..harness import projectsettings as ps

        cfg = self.need_cfg()
        proj = self.project(cfg, body.get("project") or body.get("path") or "")
        changes = body.get("changes")
        if not isinstance(changes, dict) or not changes:
            raise ApiError("send the settings to change as changes: {name: value}")
        try:
            out = ps.update(proj.root, changes, list(cfg.profiles))
        except ValueError as e:
            raise ApiError(str(e)) from None
        return {"path": str(proj.root), **out}

    def raw(self, kind: str, q) -> tuple[bytes, str, dict[str, str]]:
        """A project's picture or made file, for the page (/raw/shot, /raw/file)."""
        from .live import raw

        if kind == "hubshot":  # a picture a project on another computer published to the hub
            from . import hall

            try:
                p = hall.hub_shot_file(self.need_hub(), (q.get("name") or [""])[0], (q.get("file") or [""])[0])
            except ValueError as e:
                raise ApiError(str(e), 404) from None
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return p.read_bytes(), ctype, {"Cache-Control": "no-cache"}
        if kind == "officepdf":  # a Word, Excel or PowerPoint file made into a PDF (editapi.py)
            from .editapi import raw_office_pdf

            return raw_office_pdf(self, q)
        if kind == "pfile":  # any file of a project, for the Files tab (filesapi.py)
            from .filesapi import raw_file

            return raw_file(self, q)
        proj = self.project(self.need_cfg(), q.get("path", [""])[0])
        return raw(proj.root, kind, (q.get("name") or [""])[0], (q.get("task") or [""])[0])

    @staticmethod
    def _files(root: Path, limit: int = 200) -> list[str]:
        import os

        from ..harness.tools import SKIP_DIRS

        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for f in sorted(filenames):
                out.append(os.path.relpath(os.path.join(dirpath, f), root))
                if len(out) >= limit:
                    return out
        return out

    def _orch(self, cfg, path: Path, job: Job):
        from ..harness.orchestrator import Orchestrator

        def on_event(kind, d):
            text = harness_event_line(kind, d)
            if text:
                for ln in text.splitlines():
                    job.line(ln)

        return Orchestrator(cfg, path, on_event=on_event)

    def project_new(self, body):
        cfg = self.need_cfg()
        goal = (body.get("goal") or "").strip()
        name = (body.get("dir") or "").strip()
        if not goal or not name:
            raise ApiError("Give the project a folder name and say what to build, then start it.")
        path = Path(name).expanduser()
        path = (path if path.is_absolute() else self.projects_dir / path).resolve()
        if (path / ".harness/project.json").exists():
            raise ApiError(f"{path} already has a project. Open it and add a new goal there instead.")
        refs = _lines(body.get("references"))

        def run(job: Job):
            orch = self._orch(cfg, path, job)
            orch.start(goal, require_approval=bool(body.get("approve")), references=refs)
            return {"status": orch.run(max_tasks=body.get("max_tasks")), "path": str(path)}

        return self.jobs.start("run", f"new project {path.name}", run, target=str(path)).view()

    def project_action(self, body):
        cfg = self.need_cfg()
        proj = self.project(cfg, body.get("path", ""))
        action = body.get("action")
        if action == "raise_budget":
            from ..providers.manage import set_budget

            spent = proj.meta().get("spent_usd", 0)
            new = set_budget(cfg.path, body.get("max_cost_usd") or max(cfg.limits.max_cost_usd * 2, spent + 5))
            cfg = self.need_cfg()
            action = "run"  # and continue the paused run
            body = {**body, "action": "run"}

            def run(job: Job):
                orch = self._orch(cfg, proj.root, job)
                job.line(f"budget raised to ${new:.2f}; resuming")
                return {"status": orch.run(), "max_cost_usd": new}

            return self.jobs.start("run", f"resume {proj.root.name} (budget ${new:.2f})", run,
                                   target=str(proj.root)).view()
        if action in ("run", "extend"):
            if action == "extend" and not (body.get("goal") or "").strip():
                raise ApiError("Say what to build next first.")

            def run(job: Job):
                orch = self._orch(cfg, proj.root, job)
                if action == "extend":
                    orch.extend(body["goal"].strip())
                return {"status": orch.run(max_tasks=body.get("max_tasks"))}

            return self.jobs.start("run", f"{action} {proj.root.name}", run, target=str(proj.root)).view()
        if action == "show_it":  # "Take pictures now": the app as it is, after its newest finished task
            def shots(job: Job):
                return self._orch(cfg, proj.root, job).show_it_now()

            return self.jobs.start("shots", f"pictures of {proj.root.name}", shots, target=str(proj.root)).view()
        if any(j.target == str(proj.root) and j.status == "running" for j in self.jobs.jobs.values()):
            raise ApiError("Wait for the job running on this project to finish (Activity → Background work), then try again.", 409)
        from ..harness.orchestrator import Orchestrator

        orch = Orchestrator(cfg, proj.root)
        if action == "approve":
            orch.approve()
        elif action in ("retry", "skip"):
            getattr(orch, action)(body.get("task", ""))
        elif action == "feedback":
            tasks = {t.id: t for t in proj.tasks()}
            t = tasks.get(body.get("task", ""))
            if not t:
                raise ApiError("That task isn't in the plan any more. Refresh and try again.", 404)
            model = next((a["model"] for a in reversed(t.attempts) if a.get("outcome") == "approved"),
                         t.attempts[-1]["model"] if t.attempts else "?")
            proj.append("metrics.jsonl", {"at": utcnow(), "task": t.id, "role": t.role, "model": model,
                                          "outcome": "owner_feedback", "rating": body.get("rating", "good"),
                                          "note": body.get("note", "")})
        else:
            raise ApiError(f"unknown action {action!r}")
        return {"ok": True}

    # -- the living plan ------------------------------------------------------------------------
    def plan_get(self, q):
        from ..harness import plandoc

        cfg = self.need_cfg()
        proj = self.project(cfg, q.get("path", [""])[0])
        doc = proj.plan_doc()
        meta = proj.meta()
        tasks = proj.tasks()
        gi = doc["goal_index"] if doc else len(meta.get("goals", [])) - 1
        busy = any(j.target == str(proj.root) and j.status == "running" for j in self.jobs.jobs.values())
        words = {"title": plandoc.plan_title(doc), "state": plandoc.state_sentence(doc, tasks, meta),
                 "estimate": plandoc.estimate_line(doc.get("estimate"), meta.get("agreed")) if doc.get("estimate") else ""} if doc else {}
        return {"path": str(proj.root), "name": proj.root.name, "doc": doc, "status": meta.get("status"), "words": words,
                "approved": bool(meta.get("plan_approved")), "busy": busy,
                "tasks": [asdict(t) for t in tasks if t.goal_index == gi],
                "open": plandoc.open_items(doc), "line": plandoc.summary_line(doc) if doc else ""}

    def start_run_job(self, cfg, root, why: str = ""):
        """Start a project's run as a background job (used when a waiting run's time comes)."""
        root = Path(root)
        if any(j.target == str(root) and j.status == "running" for j in self.jobs.jobs.values()):
            return None

        def run(job: Job):
            return {"status": self._orch(cfg, root, job).run()}

        return self.jobs.start("run", f"run {root.name}" + (f" ({why})" if why else ""), run, target=str(root))

    def plan_post(self, body):
        from ..harness.orchestrator import HarnessError, Orchestrator

        cfg = self.need_cfg()
        proj = self.project(cfg, body.get("path", ""))
        action = body.get("action", "")
        if any(j.target == str(proj.root) and j.status == "running" for j in self.jobs.jobs.values()):
            raise ApiError("Wait for the job running on this project to finish (Activity → Background work), then try again.", 409)
        if action == "revise":
            def run(job: Job):
                orch = self._orch(cfg, proj.root, job)
                return orch.revise_plan(body.get("text", ""), critique_again=bool(body.get("critique")))

            return self.jobs.start("plan", f"update the plan of {proj.root.name}", run, target=str(proj.root)).view()
        if action == "looks":
            def run(job: Job):
                return self._orch(cfg, proj.root, job).look(body.get("text", ""))

            return self.jobs.start("plan", f"new looks for {proj.root.name}", run, target=str(proj.root)).view()
        if action == "approve":
            Orchestrator(cfg, proj.root).approve()

            def run(job: Job):
                return {"status": self._orch(cfg, proj.root, job).run()}

            return self.jobs.start("run", f"run {proj.root.name}", run, target=str(proj.root)).view()
        try:
            if action == "profile":
                return Orchestrator(cfg, proj.root).set_profile(str(body.get("name", "")))
            kw = {k: v for k, v in body.items() if k not in ("path", "action")}
            return Orchestrator(cfg, proj.root).plan_update(action, **kw)
        except HarnessError as e:
            raise ApiError(str(e))

    # -- questions to tap (asks.py) ------------------------------------------------------------
    def _busy(self, path: Path) -> bool:
        return any(j.target == str(path) and j.status == "running" for j in self.jobs.jobs.values())

    def asks_get(self, q):
        """What waits for the owner as cards: one project's (?path=), every project's, or the new-project
        wizard's (?wizard=1)."""
        from ..asks import open_asks, wizard_asks
        from ..harness.orchestrator import Orchestrator

        cfg = self.need_cfg()
        if q.get("wizard"):
            return {"asks": wizard_asks(cfg), "projects_dir": str(self.projects_dir)}
        path = q.get("path", [""])[0]
        roots = [self.project(cfg, path).root] if path else self.lab(cfg).projects()
        out = []
        for root in roots:
            try:
                asks = open_asks(Orchestrator(cfg, root), answered=bool(q.get("answered")))
            except (OSError, ValueError):
                continue
            busy = self._busy(root)
            out += [{**a, "busy": busy} for a in asks]
        if not path:  # the harness's own cards (a fault in its own code, a fix ready to look at)
            from ..asks import app_asks

            out += app_asks(self)
        return {"asks": out}

    def asks_post(self, body):
        """Answer a card: {path, id, chosen, other, confirmed, stamp, skip}; or start a project from the
        wizard's answers: {wizard: {kind, idea, like, profile, look}} (each {chosen, other})."""
        from .. import asktimer
        from ..harness.orchestrator import HarnessError, Orchestrator

        cfg = self.need_cfg()
        if isinstance(body.get("wizard"), dict):
            return self._wizard_start(cfg, body["wizard"])
        from ..asks import answer_app_ask, is_app_ask

        if is_app_ask(str(body.get("id", ""))):
            try:
                return answer_app_ask(self, str(body["id"]), body.get("chosen"))
            except ValueError as e:
                raise ApiError(str(e))
        proj = self.project(cfg, body.get("path", ""))
        if self._busy(proj.root) and not str(body.get("id", "")).startswith(("command:", "quiet")):  # these wait on their own run
            raise ApiError("Wait for the job running on this project to finish (Activity → Background work), then try again.", 409)
        try:
            r = asktimer.answer(Orchestrator(cfg, proj.root), str(body.get("id", "")), body.get("chosen"),
                                str(body.get("other") or ""), confirmed=bool(body.get("confirmed")),
                                stamp_seen=body.get("stamp") or None, skip=bool(body.get("skip")))
        except HarnessError as e:
            raise ApiError(str(e))
        if not r.get("then"):
            return {"reply": r["reply"]}
        return {"reply": r["reply"], "job": self.start_answer_job(cfg, proj.root, r).view()}

    def start_answer_job(self, cfg, root: Path, r: dict[str, Any], why: str = "") -> Job:
        """The long step an answer started (a run, a plan update, new looks) as a background job."""
        from ..asks import finish

        kind = "run" if r["then"] == "run" else "plan"
        title = {"run": "run", "revise": "update the plan of", "looks": "new looks for",
                 "emulator": "make a test phone for"}[r["then"]]

        def run(job: Job):
            job.line(r["reply"])
            return {"reply": finish(self._orch(cfg, root, job), r)}

        return self.jobs.start(kind, f"{title} {root.name}" + (f" ({why})" if why else ""), run, target=str(root))

    # -- autopilot (autopilot.py) ---------------------------------------------------------------------
    def autopilot_get(self, q=None):
        """Autopilot's switch and what it did lately (newest first)."""
        from .. import autopilot

        home = self._backup_home()
        limit = int(((q or {}).get("limit") or ["40"])[0])
        return {**autopilot.status(home), "log": autopilot.entries(home, limit)}

    def autopilot_post(self, body):
        """{action: "on", until, cap} | {action: "off"} | {action: "never", project, never}."""
        from .. import autopilot

        home, action = self._backup_home(), body.get("action")
        try:
            if action == "on":
                autopilot.turn_on(body.get("until"), body.get("cap"), home, self.cfg())
            elif action == "off":
                autopilot.turn_off("you turned it off.", home, self.cfg())
            elif action == "never":
                autopilot.set_never(str(body.get("project") or ""), bool(body.get("never", True)), home)
            else:
                raise ApiError("Say on, off or never.")
        except ValueError as e:
            raise ApiError(str(e))
        return self.autopilot_get()

    def autopilot_tick(self) -> list[dict[str, Any]]:
        """One autopilot pass (the auto-sync's tick): long steps start as jobs, busy projects are left alone."""
        from .. import autopilot

        cfg = self.cfg()
        if not cfg:
            return []
        return autopilot.tick(cfg, home=self._backup_home(), busy=self._busy,
                              start=lambda c, root, r: self.start_answer_job(c, root, r, why="autopilot"))

    def _wizard_start(self, cfg, answers: dict[str, Any]):
        from ..asks import apply_wizard_kind, wizard_project
        from ..harness.orchestrator import HarnessError

        try:
            w = wizard_project(answers, self.projects_dir)
            if w["profile"] and w["profile"] not in cfg.profiles:
                raise HarnessError(f"there's no {w['profile']} setting; choose another")
        except HarnessError as e:
            raise ApiError(str(e))
        path = Path(w["dir"]).resolve()

        def run(job: Job):
            orch = self._orch(cfg, path, job)
            orch.start(w["goal"], require_approval=True, references=w["references"])
            apply_wizard_kind(orch, w)  # the wizard's "What do you want to make?" (kinds)
            if w["profile"]:
                orch.set_profile(w["profile"])
            if w["look"] is not None:
                meta = orch.project.meta()
                meta.update(look_step=w["look"], look_brief=w["look_note"])
                orch.project.save_meta(meta)
            return {"status": orch.run(), "path": str(path)}

        job = self.jobs.start("run", f"new project {path.name}", run, target=str(path)).view()
        return {"reply": f"Started {path.name}: the planner is drawing up the plan.", "job": job, "path": str(path)}

    def plan_looks(self, q):
        """The look pictures of a project's plan as data addresses (the page's pictures may only be those)."""
        import base64

        cfg = self.need_cfg()
        proj = self.project(cfg, q.get("path", [""])[0])
        look = (proj.plan_doc() or {}).get("look") or {}
        out: dict[str, dict[str, str]] = {}
        for iid, names in (look.get("pictures") or {}).items():
            for name in names:
                p = proj.dir / "look" / name
                if p.is_file():
                    kind = "phone" if name.endswith("-phone.png") else "desktop"
                    out.setdefault(iid, {})[kind] = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
        return {"pictures": out}

    # -- models & probes ------------------------------------------------------------------------
    def probes(self, q):
        cfg = self.need_cfg()
        path = cfg.lab_dir / "probes.jsonl" if cfg.lab_dir else None
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path and path.is_file() else []
        runs: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = f"{r['run']}|{r['model']}"
            run = runs.setdefault(key, {"run": r["run"], "at": r["at"], "model": r["model"], "passed": 0, "total": 0,
                                        "seconds": 0.0, "results": []})
            run["passed"] += bool(r["passed"])
            run["total"] += 1
            run["seconds"] += r.get("seconds") or 0
            run["results"].append({k: r.get(k) for k in ("probe", "passed", "seconds", "error", "detail")})
        by_model: dict[str, list] = {}
        for run in sorted(runs.values(), key=lambda x: x["at"]):
            by_model.setdefault(run["model"], []).append(run)
        return {"models": [{"model": m, "runs": rs[-20:]} for m, rs in sorted(by_model.items())]}

    def probe_run(self, body):
        cfg = self.need_cfg()
        from ..harness.config import ModelRef
        from ..improve.probe import check, models_in_config

        if body.get("models"):
            refs = [ModelRef.parse(m) for m in body["models"]]
            image_kinds = {str(m) for r in cfg.roles.values() if r.kind == "image" for m in r.models}
            chat = [m for m in refs if str(m) not in image_kinds]
            image = [m for m in refs if str(m) in image_kinds]
        else:
            chat, image = models_in_config(cfg, body.get("roles") or None)

        def run(job: Job):
            job.line(f"probing {len(chat)} chat and {len(image)} image model(s)")
            reports = check(cfg, cfg.lab_dir, chat, image, generate_images=bool(body.get("images")),
                            max_cost=float(body.get("max_cost") or 1.0),
                            on_result=lambda r: job.line(f"{'pass' if r.passed else 'FAIL'}  {r.model}  {r.probe}  "
                                                         f"{r.seconds:.1f}s  {(r.error or r.detail)[:100]}"))
            out = []
            for r in reports:
                d = asdict(r)
                d["bad"] = r.bad
                d.pop("results", None)
                out.append(d)
                job.line(f"{r.model}: {r.passed}/{r.total}  {' '.join(r.status)}  {'; '.join(r.notes)[:200]}")
            return out

        return self.jobs.start("probe", "model health probe", run, target="probe").view()

    # -- improve -------------------------------------------------------------------------------------
    def proposals(self, q):
        cfg = self.need_cfg()
        lab = self.lab(cfg)
        overlay, prompts = lab.learned()
        return {"proposals": [asdict(p) | {"summary": p.summary()} for p in reversed(lab.proposals())],
                "learned": overlay, "learned_prompts": sorted(prompts), "history": lab.history()[-50:],
                "policy": cfg.improve.get("auto_apply", "none")}

    def improve_action(self, body):
        cfg = self.need_cfg()
        lab = self.lab(cfg)
        action = body.get("action")
        if action == "analyze":
            from ..improve.analysis import analyze, stats_table

            def run(job: Job):
                ds, new, cost = analyze(cfg, lab, use_llm=bool(body.get("llm")), max_cost=float(body.get("max_cost") or 2))
                for ln in stats_table(ds).splitlines():
                    job.line(ln)
                job.line(f"{len(new)} new proposal(s)" + (f", analyst cost ${cost:.4f}" if cost else ""))
                return {"new": [p.id for p in new]}

            return self.jobs.start("improve", "analyze history", run, target="improve").view()
        if action == "propose":
            from ..improve.lab import Proposal

            kind = body.get("kind")
            change = {"routing": {"models": body.get("models") or []}, "options": {"options": body.get("options") or {}},
                      "prompt": {"prompt_text": body.get("prompt_text") or ""}}.get(kind, {})
            p = Proposal(id="", kind=kind, role=body.get("role", ""), change=change,
                         rationale=body.get("why") or "owner suggestion", risk=body.get("risk", "medium"), source="owner")
            p.validate(cfg)
            return asdict(lab.add_proposal(p))
        if action == "rollback":
            return {"rolled_back_to_before": lab.rollback(body.get("version") or None)}
        p = lab.proposal(body.get("id", ""))
        if action == "reject":
            p.status = "rejected"
            lab.save_proposal(p)
            return {"ok": True}
        if action == "test":
            from ..improve.evaluate import evaluate

            def run(job: Job):
                res = evaluate(cfg, lab, p, samples=int(body.get("samples") or 3), max_cost=float(body.get("max_cost") or 2), yard=True,
                               on_event=lambda k, d: job.line(harness_event_line(k, d) or "") if harness_event_line(k, d) else None)
                job.line(f"verdict: {res['verdict']} ({'passed' if res['passed'] else 'not passed'}) on "
                         f"{res['tasks_compared']} task(s)")
                return {"verdict": res["verdict"], "passed": res["passed"]}

            return self.jobs.start("improve", f"replay test {p.id}", run, target="improve").view()
        if action == "apply":
            def run(job: Job):
                if not body.get("skip_probe") and cfg.improve.get("probe_before_apply", True) \
                        and cfg.roles[p.role].kind == "chat":
                    from ..improve.probe import check, models_for_proposal

                    models = models_for_proposal(cfg, p)
                    job.line(f"health-checking {', '.join(map(str, models))}")
                    reports = check(cfg, lab.root, models)
                    for r in reports:
                        job.line(f"{r.model}: {r.passed}/{r.total} {' '.join(r.status)}")
                    bad = [r.model for r in reports if r.bad]
                    if bad and not body.get("force"):
                        raise RuntimeError(f"not applied: {', '.join(bad)} acting up right now")
                if not body.get("force") and not (p.test and p.test.get("passed")) \
                        and not (p.source == "rules" and p.kind == "routing"):
                    raise RuntimeError("not applied: no passed replay test (test it first, or force)")
                version = lab.apply(p, cfg, reason="ui", by_owner=True)  # the owner's own tap
                job.line(f"applied {p.id} as version {version}: {p.summary()}")
                return {"version": version}

            return self.jobs.start("improve", f"apply {p.id}", run, target="improve").view()
        raise ApiError(f"unknown action {action!r}")

    # -- setup & settings (desktop app first-run, and config editing) --------------------------------
    def _config_paths(self) -> dict[str, Path | None]:
        from ..core.config import find_config as find_hub
        from ..harness.config import find_config as find_harness

        out: dict[str, Path | None] = {}
        for which, finder, explicit in (("hub", find_hub, self.hub_config_path),
                                        ("harness", find_harness, self.harness_config_path)):
            try:
                out[which] = finder(explicit)
            except FileNotFoundError:
                out[which] = Path(explicit).expanduser() if explicit else None
        return out

    def setup(self, q=None):
        from .. import __version__

        d = self.desktop
        paths = self._config_paths()
        hub_mode, hub_detail = "none", ""
        if self.hub:
            st = self.hub.config.storage
            hub_mode = st.get("type", "file")
            hub_detail = str(self.hub.store.root)
        out: dict[str, Any] = {
            "desktop": bool(d), "version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
            "hub": {"mode": hub_mode, "where": hub_detail, "error": self.hub_error},
            "config_paths": {k: str(v) if v else "" for k, v in paths.items()},
            "config_exists": {k: bool(v and v.exists()) for k, v in paths.items()},
            "projects_dir": str(self.projects_dir), "agent": self.agent,
            "agents": list(self.hub.config.agents) if self.hub else [],
        }
        if d:
            from ..desktop import git_version, key_label, provider_specs

            ks = d["keys"]
            specs = provider_specs(d["paths"].harness_yaml)
            cfg = self.cfg()
            if cfg:
                specs = {**cfg.providers, **specs}
            extra = [v.get("api_key_env") for v in specs.values() if v.get("api_key_env")]
            out["keys"] = [{"name": n, "label": key_label(n, specs), "set": bool(vault.get(n) or ks.get(n)),
                            "providers": [p for p, v in specs.items() if (v or {}).get("api_key_env") == n]}
                           for n in ks.names(extra)]
            out["secure_keys"] = ks.secure
            out["git"] = git_version()
            out["home"] = str(d["paths"].home)
            out["setup_done"] = bool(d["paths"].load_settings().get("setup_done"))
        else:
            from ..desktop import KNOWN_KEYS

            cfg = self.cfg()
            specs = dict(cfg.providers) if cfg else {}
            out["keys"] = [{"name": n, "label": label, "set": vault.has(n),
                            "providers": [p for p, v in specs.items() if (v or {}).get("api_key_env") == n]}
                           for n, label in KNOWN_KEYS.items()]
            out["secure_keys"] = False
            out["setup_done"] = True
        return out

    def setup_keys(self, body):
        if not self.desktop:
            raise ApiError(f"This copy reads keys from the computer's own settings. Open the {NAME} app to save keys here.")
        ks = self.desktop["keys"]
        for name, value in (body.get("keys") or {}).items():
            if not isinstance(name, str) or not name.replace("_", "").isalnum() or not name.isupper():
                raise ApiError(f"invalid key name {name!r}")
            if value is not None:
                ks.set(name, str(value))
        return self.setup()

    def recommended(self, q=None):
        from ..recommended import preview

        path = self._config_paths().get("harness")
        if not path or not path.exists():
            raise ApiError("The harness's settings are missing. Run the set-up again from Settings → Advanced.", 404)
        return preview(path)

    def recommended_apply(self, body):
        from ..recommended import apply

        path = self._config_paths().get("harness")
        if not path or not path.exists():
            raise ApiError("The harness's settings are missing. Run the set-up again from Settings → Advanced.", 404)
        try:
            done = apply(path)
        except ValueError as e:
            raise ApiError(f"Nothing was changed: the recommended setup didn't fit your settings ({e}). "
                           "Choose the jobs yourself in Models, or ask for help.")
        return {**done, **self.recommended()}

    def setup_hub(self, body):
        if not self.desktop:
            raise ApiError(f"This copy was started with its own hub settings. Open the {NAME} app to connect a hub here.")
        from ..desktop import connect_github_hub, write_local_hub

        paths = self.desktop["paths"]
        if body.get("mode") == "local":
            write_local_hub(paths)
            self.reload_hub()
            return self.setup()

        def run(job: Job):
            connect_github_hub(paths, body.get("url", ""), log=job.line)
            self.reload_hub()
            if self.hub_error:
                raise RuntimeError(self.hub_error)
            job.line(f"hub ready: {len(self.hub.config.agents)} project(s)")
            return {"agents": list(self.hub.config.agents)}

        return self.jobs.start("setup", "connect hub", run, target="setup").view()

    def setup_done(self, body):
        if self.desktop:
            paths = self.desktop["paths"]
            settings = paths.load_settings()
            settings["setup_done"] = True
            if body.get("agent"):
                settings["agent"] = self.agent = body["agent"]
            if body.get("projects_dir"):
                settings["projects_dir"] = body["projects_dir"]
                self.projects_dir = Path(body["projects_dir"]).expanduser().resolve()
                self.projects_dir.mkdir(parents=True, exist_ok=True)
            paths.save_settings(settings)
        return self.setup()

    def config_get(self, q):
        which = (q.get("which") or ["harness"])[0]
        path = self._config_paths().get(which)
        if not path:
            raise ApiError("That settings file isn't there yet. Run the set-up again from Settings → Advanced.", 404)
        return {"which": which, "path": str(path), "text": path.read_text(encoding="utf-8") if path.exists() else ""}

    def config_save(self, body):
        import yaml

        which, text = body.get("which"), body.get("text", "")
        path = self._config_paths().get(which)
        if which not in ("hub", "harness") or not path:
            raise ApiError("unknown config")
        try:
            raw = yaml.safe_load(text) or {}
            if which == "harness":
                from ..harness.config import parse_config

                parse_config(raw, path)
            else:
                from ..core.config import parse_config

                parse_config(raw, path)
        except (yaml.YAMLError, ValueError) as e:
            raise ApiError(f"not saved - {which}.yaml has a problem: {e}")
        backup = path.with_suffix(".yaml.bak")
        if path.exists():
            backup.write_text(path.read_text(encoding="utf-8"))
        path.write_text(text, encoding="utf-8")
        if which == "hub":
            self.reload_hub()
        return {"saved": str(path), "backup": str(backup)}

    # -- providers & role models (any AI API) ---------------------------------------------------------
    def providers(self, q):
        from ..providers.catalog import PRESETS
        from ..providers.manage import list_providers

        cfg = self.need_cfg()
        roles = [{"name": r.name, "kind": r.kind, "models": [str(m) for m in r.models], "description": r.description}
                 for r in cfg.roles.values()]
        return {"presets": PRESETS, "providers": list_providers(cfg.path), "roles": roles, "desktop": bool(self.desktop)}

    def providers_action(self, body):
        from ..providers import manage

        cfg = self.need_cfg()
        action, pid = body.get("action"), (body.get("id") or "").strip()
        if action == "add":
            block = manage.add_provider(cfg.path, body.get("preset", ""), pid=pid or None,
                                        base_url=body.get("base_url"), api_key_env=body.get("api_key_env"),
                                        auth_header=body.get("auth_header"), auth_prefix=body.get("auth_prefix", ""),
                                        headers=body.get("headers") or None, query=body.get("query") or None,
                                        **{"class": body.get("class")})
            key = (body.get("key") or "").strip()
            if key and block.get("api_key_env"):
                if not self.desktop:
                    raise ApiError(f"provider added; set {block['api_key_env']} in your environment for the key")
                self.desktop["keys"].set(block["api_key_env"], key)
            cfg = self.need_cfg()
            return {"added": block, "test": manage.test_provider(cfg, block["id"])}
        if action == "remove":
            manage.remove_provider(cfg.path, pid)
            return {"removed": pid}
        if action == "test":
            return manage.test_provider(cfg, pid)
        if action == "models":
            return {"id": pid, "models": manage.provider_models(cfg, pid)}
        raise ApiError(f"unknown action {action!r}")

    def assign(self, body):
        from ..providers.manage import set_role_models

        cfg = self.need_cfg()
        models = body.get("models") or []
        if isinstance(models, str):
            models = [m.strip() for m in models.replace("\n", ",").split(",")]
        return set_role_models(cfg.path, body.get("role", ""), models, kind=body.get("kind"),
                               description=body.get("description"))

    def features(self, q):
        """Which routes this copy has, so the page asks only for what's there (no failed requests)."""
        return {"routes": sorted({path for _, path in self.routes()} | {"/api/plugins", "/api/journal",
                                                                         "/api/inbox", "/api/jobs"})}

    # -- who does which job (Models): plain names, every set of models, changed from the app -----------
    def routing_get(self, q):
        from ..routing import view

        cfg = self.need_cfg()
        return {**view(cfg), "can_change": bool(cfg.path)}

    def routing_post(self, body):
        """{role, models: [ref, ...], set?: profile, effort?} or {default_set: profile}."""
        from .. import routing

        cfg = self.need_cfg()
        if not cfg.path:
            raise ApiError("The harness has no settings file to save this in. Run the setup again from Settings.")
        try:
            if "default_set" in body:
                routing.set_default(cfg.path, str(body.get("default_set") or ""))
            else:
                role = str(body.get("role") or "")
                if role not in cfg.roles:
                    raise ApiError("That job isn't there any more. Refresh the page and try again.", 404)
                routing.set_job(cfg.path, role, list(body.get("models") or []), str(body.get("set") or "") or None,
                                effort=body.get("effort"))
        except ValueError as e:
            raise ApiError(f"Nothing was changed: {e}") from None
        return self.routing_get({})

    # -- Roundtable main screen ----------------------------------------------------------------------
    def roundtable(self, q):
        from .roundtable import build

        data = build(self)
        data["sync_error"] = self.auto_sync_error
        return data

    # -- projects that run elsewhere: their plan and questions in the hub, answered through the hub ----------
    HUB_ACTIONS = ("approve", "answer", "run", "retry", "skip", "todo_done", "shared_settings", "carry_on", "show_it")

    def hub_plan(self, q):
        """A plan another computer published (plans/<name>.md) with its open questions."""
        from . import hall

        hub = self.need_hub()
        name = (q.get("name") or [""])[0]
        with self.hub_lock:
            plans = hall.hub_plans(hub)
        p = plans.get(name)
        if not p:
            raise ApiError("That plan isn't in the hub any more. Go back to the Hall and refresh.", 404)
        root = hall.hub_root(hub)
        md = (root / "plans" / f"{name}.md").read_text(encoding="utf-8")
        spec = hub.config.agents.get(p["folder"])
        return {**p, "title": hall.friendly(p["folder"], spec), "markdown": md,
                "here": p["folder"] in {x.name for x in self._lab_projects()}}

    def hub_live(self, q):
        """The newest pictures and steps a project on another computer published to the hub."""
        from . import hall

        hub = self.need_hub()
        try:
            with self.hub_lock:
                return hall.hub_live(hub, (q.get("name") or [""])[0])
        except ValueError:
            raise ApiError("That project isn't in the hub. Go back to the Hall and refresh.", 404)

    def notes_list(self, q):
        """The owner's saved documents in the hub (notes/*.md): name and title, nothing else until one is opened."""
        from . import hall

        hub = self.need_hub()
        with self.hub_lock:
            return {"notes": hall.hub_notes(hub)}

    def note_get(self, q):
        from . import hall

        hub = self.need_hub()
        try:
            with self.hub_lock:
                return hall.hub_note(hub, (q.get("name") or [""])[0])
        except ValueError:
            raise ApiError("That document isn't in the hub any more. Go back to My notes and refresh.", 404)

    def hub_command(self, body):
        """Send a command to a project another computer runs: {agent, folder, action, ...fields}.

        It goes to the project's hub inbox as the owner's request (remote.py); the computer that runs the
        project does it the next time it checks the hub, and replies in the owner's letters."""
        from ..remote import FOLDER, PREFIX

        hub = self.need_hub()
        agent, action = str(body.get("agent") or ""), str(body.get("action") or "")
        if agent not in hub.config.agents:
            raise ApiError("That project isn't in the hub. Refresh the Hall and try again.", 404)
        if action not in self.HUB_ACTIONS:
            raise ApiError(f"Can't send {action!r} through the hub.")
        if not self.agent:
            raise ApiError("This computer has no name in the hub yet. Connect the hub in Settings first.")
        cmd = {"action": action, **{k: v for k, v in (body.get("fields") or {}).items() if k not in ("action", FOLDER)}}
        if body.get("folder") and body["folder"] != agent:
            cmd[FOLDER] = str(body["folder"])
        if body.get("machine"):  # only that machine does it (sync.py)
            cmd["machine"] = str(body["machine"])
        try:
            with self.hub_lock:
                hub.send(self.agent, [agent], f"{PREFIX} {action}", json.dumps(cmd), kind="request")
        except (PermissionError, ValueError) as e:
            raise ApiError(f"The hub didn't take it: {e}. Check the hub's rules let you message this project.") from None
        return {"reply": "Sent: it starts when that computer next checks the hub. Its answer comes back in "
                         "Letters."}

    def activity(self, q):
        from .roundtable import activity

        return activity(self, limit=int((q.get("limit") or ["120"])[0]))

    def chat_get(self, q):
        cfg = self.need_cfg()
        from ..harness.orchestrator import Orchestrator

        proj = self.project(cfg, q.get("path", [""])[0])
        return Orchestrator(cfg, proj.root).chat_history()

    def chat_post(self, body):
        cfg = self.need_cfg()
        from ..harness.orchestrator import Orchestrator

        proj = self.project(cfg, body.get("path", ""))
        orch = Orchestrator(cfg, proj.root)
        if body.get("steer"):
            return orch.steer(body.get("message", ""))
        return orch.ask(body.get("message", ""))

    # -- updater -----------------------------------------------------------------------------------
    def update_status(self, q):
        from ..updater import status_dict

        return status_dict()

    def update_run(self, body):
        from ..updater import update

        def run(job: Job):
            st = update(force=bool(body.get("force")), log=job.line)
            return {"message": st.message, "changes": st.changes}

        return self.jobs.start("update", f"update {NAME}", run, target="update").view()

    # -- backups (Settings → Backups) ------------------------------------------------------------------
    def _backup_home(self) -> Path:
        from ..desktop import app_home

        return self.desktop["paths"].home if self.desktop else app_home()

    def _backup_sources(self):
        from ..backup import find_sources

        return find_sources(self.harness_config_path, self.hub_config_path, self._backup_home())

    def _project_job_running(self) -> bool:
        return any(j.status == "running" and j.kind in ("run", "plan") for j in self.jobs.jobs.values())

    def backup_status(self, q=None):
        from .. import backup as bk

        home = self._backup_home()
        settings = bk.load_settings(home)
        dest = bk.resolve_destination(settings, home=home)
        state = bk.load_state(home)
        return {"settings": settings, "found": [str(p) for p in bk.find_drive_folders()],
                "destination": str(dest) if dest else "", "no_drive": bk.NO_DRIVE, "host": bk.host_name(),
                "last": {k: state.get(k) for k in ("last_at", "last_file", "last_size", "last_error")},
                "log": (state.get("log") or [])[:5], "backups": bk.list_backups(dest)[:20] if dest else [],
                "passphrase_remembered": bool(bk.remembered_passphrase())}

    def _backup_file(self, name: str) -> Path:
        from .. import backup as bk

        name = (name or "").strip()
        if not name.endswith((".zip", ".zip.enc")):
            raise ApiError("Choose a backup file (it ends .zip or .zip.enc).")
        path = Path(name).expanduser()
        if not path.is_absolute():
            dest = bk.resolve_destination(home=self._backup_home())
            path = (dest / name) if dest else path
        if not path.is_file():
            raise ApiError(f"Can't find {path}. Check the name, or that Google Drive has finished syncing it.", 404)
        return path

    def backup_action(self, body):
        from .. import backup as bk

        home, action = self._backup_home(), body.get("action")
        phrase = (body.get("passphrase") or "").strip() or None
        try:
            if action == "settings":
                bk.save_settings(home, **{k: body.get(k) for k in ("to", "keep", "daily", "encrypt")})
                return self.backup_status()
            if action == "passphrase":
                bk.remember_passphrase(phrase if body.get("remember", True) else None)
                return self.backup_status()
            if action == "inspect":
                opened = bk.open_backup(self._backup_file(body.get("file")), phrase)
                return {"lines": bk.summary(opened, bk.restore_plan(opened, home)),
                        "refused": opened.manifest.get("refused", []), "notes": opened.manifest.get("notes", [])}
        except bk.BackupError as e:
            raise ApiError(str(e)) from None
        if action == "now":
            if body.get("remember") and phrase:
                bk.remember_passphrase(phrase)

            def run(job: Job):
                res = bk.backup_now(with_code=bool(body.get("with_code")), passphrase=phrase,
                                    sources=self._backup_sources(), home=home)
                job.line(res.message())
                return {"file": str(res.path), "size": res.size, "refused": res.refused, "message": res.message()}

            return self.jobs.start("backup", "back up settings and plans", run, target="backup").view()
        if action == "restore":
            if body.get("confirm") is not True:
                raise ApiError("Confirm the restore first.")
            if self._project_job_running():
                raise ApiError("Wait for the running project job to finish, then restore.", 409)
            path = self._backup_file(body.get("file"))

            def run(job: Job):
                done = bk.restore(path, phrase, yes=True, home=home, sources=self._backup_sources(), log=job.line)
                job.line(f"Restored {done.written} files. What was here before is in {done.safety}.")
                for n in done.notes:
                    job.line(n)
                self.reload_hub()
                return {"written": done.written, "safety": str(done.safety), "notes": done.notes}

            return self.jobs.start("backup", f"restore {path.name}", run, target="backup").view()
        raise ApiError(f"unknown action {action!r}")

    # -- routing table ------------------------------------------------------------------------------
    def phone_status(self, q=None):
        st = self.phone.status()
        if st.get("pairing"):
            import io

            import segno

            buf = io.BytesIO()
            segno.make(st["pairing"]["uri"], error="m").save(buf, kind="svg", scale=5, border=2, dark="#1a1410",
                                                              light="#f3e7c9")
            import base64

            st["pairing"]["qr"] = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
        return st

    def phone_action(self, body):
        self.phone.api(body)
        return self.phone_status()

    def routes(self):
        from . import syncapi

        R = self
        return {
            ("GET", "/api/overview"): R.overview,
            ("GET", "/api/where"): R.where,
            ("GET", "/api/cards"): R.cards,
            ("POST", "/api/send"): R.send,
            ("POST", "/api/reply"): R.reply,
            ("GET", "/api/thread"): R.thread,
            ("GET", "/api/roles"): R.roles,
            ("GET", "/api/projects"): R.projects,
            ("GET", "/api/project"): R.project_detail,
            ("GET", "/api/project/live"): R.project_live,
            ("GET", "/api/project/session"): R.project_session,
            ("GET", "/api/project/settings"): R.project_settings_get,
            ("POST", "/api/project/settings"): R.project_settings_post,
            ("POST", "/api/projects"): R.project_new,
            ("POST", "/api/project"): R.project_action,
            ("GET", "/api/probes"): R.probes,
            ("POST", "/api/probes"): R.probe_run,
            ("GET", "/api/proposals"): R.proposals,
            ("POST", "/api/improve"): R.improve_action,
            ("GET", "/api/jobs"): lambda q: R.jobs.list(),
            ("GET", "/api/update"): R.update_status,
            ("GET", "/api/roundtable"): R.roundtable,
            ("GET", "/api/activity"): R.activity,
            ("GET", "/api/hub/plan"): R.hub_plan,
            ("GET", "/api/hub/live"): R.hub_live,
            ("GET", "/api/notes"): R.notes_list,
            ("GET", "/api/note"): R.note_get,
            ("POST", "/api/hub/command"): R.hub_command,
            ("GET", "/api/chat"): R.chat_get,
            ("POST", "/api/chat"): R.chat_post,
            ("GET", "/api/setup"): R.setup,
            ("POST", "/api/setup/keys"): R.setup_keys,
            ("POST", "/api/setup/hub"): R.setup_hub,
            ("POST", "/api/setup/done"): R.setup_done,
            ("GET", "/api/setup/recommended"): R.recommended,
            ("POST", "/api/setup/recommended"): R.recommended_apply,
            ("GET", "/api/config"): R.config_get,
            ("GET", "/api/providers"): R.providers,
            ("POST", "/api/providers"): R.providers_action,
            ("POST", "/api/assign"): R.assign,
            ("GET", "/api/routing"): R.routing_get,
            ("GET", "/api/features"): R.features,
            ("POST", "/api/routing"): R.routing_post,
            ("POST", "/api/config"): R.config_save,
            ("POST", "/api/update"): R.update_run,
            ("GET", "/api/plan"): R.plan_get,
            ("POST", "/api/plan"): R.plan_post,
            ("GET", "/api/plan/looks"): R.plan_looks,
            ("GET", "/api/asks"): R.asks_get,
            ("POST", "/api/asks"): R.asks_post,
            ("GET", "/api/autopilot"): R.autopilot_get,
            ("POST", "/api/autopilot"): R.autopilot_post,
            ("GET", "/api/phone"): R.phone_status,
            ("POST", "/api/phone"): R.phone_action,
            ("GET", "/api/backup"): R.backup_status,
            ("POST", "/api/backup"): R.backup_action,
            **syncapi.routes(R),  # the phone and the PC as one Roundtable (sync.py)
            **_feature_routes(R),  # features that bring their own API module (FEATURE_APIS)
        }

    def dispatch(self, method: str, path: str, q: dict, body: dict) -> Any:
        fn = self.routes().get((method, path))
        if fn:
            return fn(body if method == "POST" else q)
        parts = path.strip("/").split("/")  # parametrised routes
        if parts[:2] == ["api", "journal"] and len(parts) == 3:
            return self.journal_add(body, parts[2]) if method == "POST" else self.journal(q, parts[2])
        if parts[:2] == ["api", "journal"] and len(parts) == 5 and parts[4] == "close" and method == "POST":
            return self.journal_close(body, parts[2], parts[3])
        if parts[:2] == ["api", "cards"] and len(parts) == 3 and method == "POST":
            return self.card_update(body, parts[2])
        if parts[:2] == ["api", "inbox"] and len(parts) == 3 and method == "GET":
            return self.inbox(q, parts[2])
        if parts[:2] == ["api", "inbox"] and len(parts) == 4 and parts[3] == "read" and method == "POST":
            return self.mark_read(body, parts[2])
        if parts[:2] == ["api", "jobs"] and len(parts) == 3 and method == "GET":
            job = self.jobs.jobs.get(parts[2])
            if not job:
                raise ApiError("That job has gone (the app was restarted). Look in Activity → Background work for the current ones.", 404)
            return job.view(int((q.get("since") or ["0"])[0]))
        if parts[:2] == ["api", "plugins"]:
            from ..plugins.manage import api as plugins_api

            status, data = plugins_api(method, "/".join(parts[2:]), q, body,
                                       harness_path=self.harness_config_path, cfg=self.cfg())
            if status >= 400:
                raise ApiError(data.get("error", "plugin error"), status)
            return data
        raise ApiError(f"no route {method} {path}", 404)


# -- HTTP layer ------------------------------------------------------------------------------------
# the look's fonts and pictures: some Pythons (and Windows' registry) don't know these types
# (and .js: the page's scripts are modules, which browsers only run with a JavaScript type)
for _ext, _type in ((".woff2", "font/woff2"), (".webp", "image/webp"), (".js", "text/javascript")):
    mimetypes.add_type(_type, _ext)
def make_handler(app: UIApp, token: str | None, allow_remote: bool):
    static = resources.files("roundtable").joinpath("ui/static")

    class Handler(BaseHTTPRequestHandler):
        server_version = "roundtable-ui"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            extra = dict(extra or {})
            self.send_header("X-Frame-Options", extra.pop("X-Frame-Options", "DENY"))  # a project's PDF: SAMEORIGIN
            from . import appapi  # an app started with a command shows in a frame on its own port

            frames = f"; frame-src 'self' {app.preview.origin + ' ' if app.preview.origin else ''}{appapi.FRAME_SRC}"
            self.send_header("Content-Security-Policy", extra.pop("Content-Security-Policy", None) or
                             "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self'" + frames)
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: Any):
            self._send(status, json.dumps(data, default=str).encode(), "application/json")

        def _authorized(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if not allow_remote and host not in LOOPBACK:
                return False  # DNS-rebinding guard
            if token:
                cookie = self.headers.get("Cookie") or ""
                supplied = self.headers.get("X-Token") or next(
                    (c.split("=", 1)[1] for c in cookie.split("; ") if c.startswith("ahtoken=")), "")
                if not secrets.compare_digest(supplied, token):
                    return False
            return True

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if token and q.get("token") == [token]:  # one-time login link sets a cookie
                self._send(302, b"", "text/plain", {"Location": "/", "Set-Cookie":
                                                    f"ahtoken={token}; HttpOnly; SameSite=Strict; Path=/"})
                return
            if not self._authorized():
                self._send(403, b"forbidden: open the URL printed by `roundtable ui`", "text/plain")
                return
            if url.path.startswith("/api/"):
                return self._api("GET", url.path, q, {})
            if url.path in ("/raw/shot", "/raw/file", "/raw/hubshot", "/raw/pfile", "/raw/officepdf"):
                return self._raw(url.path[5:], q)
            name = "index.html" if url.path in ("/", "/index.html") else url.path.lstrip("/")
            if "/" in name or name.startswith("."):
                return self._send(404, b"not found", "text/plain")
            f = static.joinpath(name)
            if not f.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))

        def do_POST(self):
            url = urlparse(self.path)
            if url.path.startswith("/hooks/"):  # a program on this computer starting work (reach.py, "local")
                from .. import reach

                # the socket's own address, never a forwarded header: only this computer may send
                status, data = reach.receive_for_app(app, url.path, self.client_address[0], self.headers, self.rfile)
                return self._json(status, data)
            if not self._authorized() or self.headers.get("X-Agent-Hub") != "1":
                return self._send(403, b"forbidden", "text/plain")
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._send(415, b"json only", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            if length > 2_000_000:
                return self._send(413, b"too large", "text/plain")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid JSON"})
            self._api("POST", url.path, {}, body if isinstance(body, dict) else {})

        def _raw(self, kind, q):
            q = {**q, "_range": [self.headers.get("Range") or ""]}  # a video wound on asks for part of the file
            try:
                body, ctype, headers = app.raw(kind, q)
            except (ApiError, FileNotFoundError, ValueError) as e:
                return self._send(404, str(e).encode(), "text/plain; charset=utf-8")
            headers = dict(headers or {})
            self._send(int(headers.pop("_status", 200)), body, ctype, headers)

        def _api(self, method, path, q, body):
            try:
                self._json(200, app.dispatch(method, path, q, body))
            except ApiError as e:
                self._json(e.status, {"error": str(e)})
            except (ValueError, KeyError, PermissionError, RuntimeError, FileNotFoundError) as e:
                self._json(400, {"error": str(e).strip("'\"")})
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def serve(hub_config: str | None = None, harness_config: str | None = None, agent: str | None = None,
          host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, projects_dir: str | None = None) -> None:
    app = UIApp(hub_config, harness_config, agent, projects_dir)
    remote = host not in LOOPBACK
    app.local_only = not remote  # the command line works only while the app is open to this PC alone
    token = secrets.token_urlsafe(16) if remote else None
    app.start_auto_sync()
    app.phone.start()
    app.preview.start()
    httpd = ThreadingHTTPServer((host, port), make_handler(app, token, allow_remote=remote))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{httpd.server_address[1]}/"
    if token:
        url += f"?token={token}"
    print(f"{NAME} UI: {url}")
    print(f"  hub:     {app.hub.config.path if app.hub else 'not configured (' + app.hub_error + ')'}")
    cfg = app.cfg()
    print(f"  harness: {cfg.path if cfg else 'not configured (' + app.harness_error + ')'}")
    if remote:
        print("  WARNING: listening beyond localhost. Anyone with the link can run models and shell commands.")
    print("Ctrl-C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        stop_apps()


def stop_apps() -> None:
    """At exit: every app the App tab started is stopped (appapi.py); never fails the exit."""
    try:
        from . import appapi

        appapi.stop_all()
    except Exception:  # noqa: BLE001
        pass
