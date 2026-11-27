"""Two more kinds of learned change (wave 7, d4-tools): a new tool, and a small tweak to a project kind.

Neither is ever applied without the owner's tap: both are risk "high" (no ``auto_apply`` policy reaches them),
``charter.may_auto`` is False for them, and a drafted one is saved as ``needs_owner``, so the lab's cycle never
tests or applies it by itself.

**"tool"**: ``change = {idea, folder, tools: [names]}``. ``propose_tool`` drafts it with the learning allowance only
(``wallet.budget(cfg, lab, "tool")``; with nothing left it does nothing paid), throws away a draft whose tests
failed or that broke a rule (plugins/make.py), and tries it on the yardstick with and without it
(``candidate_for`` gives the candidate its own plugin host, because variants share one). ``on_apply`` installs it
with ``manage.add_plugin`` asking for nothing (boxed: plug-ins run in their own box unless the owner marks one
Trusted); ``on_undo`` switches it off and keeps every file. ``lay`` does nothing: the tool lives in custom.yaml's
``plugins:``, not in learned.yaml.

**"kind"**: ``change = {kind_id, extra: {...}}``, limited to plan "don't" lines (``plan.dont``), a task note
(``task``) and proof lines that aren't commands (``proof``: how is page_opens, play, picture or file_exists, and
no ``command``). Checked with ``kinds.model.validate(raw, is_extra=True)`` and written as an extra in the owner's
own kinds folder (``<app home>/kinds/_extras/learned-<kind>/extra.yaml``), holding every applied tweak for that
kind. Never a built-in file, never a command, a start recipe or a ship recipe. ``resolve_with_tweaks`` is
``kinds.model.resolve`` with the learned extra stacked on.
"""

from __future__ import annotations

import copy
import dataclasses
import shutil
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.models import utcnow
from .lab import KINDS, KindSpec, Lab, Proposal, register_kind

LEARNED_EXTRA = "learned-"
TWEAK_KEYS = {"plan", "task", "proof"}
TWEAK_PROOF_HOW = ("page_opens", "play", "picture", "file_exists")
MAX_TWEAK_LINES = 8

Emit = Callable[[str, dict[str, Any]], None]


def _home() -> Path:
    from ..desktop import app_home

    return app_home()


# -- "tool" ------------------------------------------------------------------------------------------------------
def _validate_tool(p: Proposal, cfg: Any) -> None:
    from ..plugins import make

    c = p.change or {}
    if not isinstance(c.get("idea"), str) or not c["idea"].strip():
        raise ValueError("a tool change needs the 'idea' it was made for")
    tools = c.get("tools")
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t for t in tools):
        raise ValueError("a tool change needs the names of its 'tools'")
    folder = Path(str(c.get("folder") or ""))
    if not folder.is_dir():
        raise ValueError("the tool's folder is gone, so it can't be added")
    probs = make.check(folder)
    if probs:
        raise ValueError("the tool can't be added: " + " ".join(probs[:3]))
    if sorted(make.tool_names(folder)) != sorted(tools):
        raise ValueError("the tool's folder no longer gives the tools it was tested with")


def _tool_summary(p: Proposal) -> str:
    return "new tool " + ", ".join((p.change or {}).get("tools") or [])


def _no_lay(overlay: dict, prompts: dict, p: Proposal, cfg: Any) -> None:
    return None  # the change lives in custom.yaml (tool) or the owner's kinds folder (kind), not learned.yaml


def _harness_path(cfg: Any) -> Any:
    return getattr(cfg, "path", None)


def _tool_apply(lab: Lab, p: Proposal, cfg: Any) -> None:
    from ..plugins import manage

    folder = str(p.change["folder"])
    added = manage.add_plugin(_harness_path(cfg), folder, confirm=lambda m: not m.permissions)
    p.evidence = {**(p.evidence or {}), "installed": {"id": added["id"], "path": added.get("path", ""),
                                                     "harness": str(_harness_path(cfg) or ""), "at": utcnow()}}
    try:
        cfg._shared.pop("plugin_host", None)  # the next run loads the plugins afresh
    except AttributeError:
        pass


def _tool_undo(lab: Lab, p: Proposal) -> None:
    from ..plugins import manage

    inst = (p.evidence or {}).get("installed") or {}
    if not inst.get("id"):
        return
    manage.set_enabled(inst.get("harness") or None, inst["id"], False)  # off; its files stay


def candidate_config(lab: Lab, cfg: Any, p: Proposal) -> Any:
    """A copy of ``cfg`` with the drafted tool switched on in its own plugin host (nothing written)."""
    from ..plugins.manifest import find_manifest

    variant = lab.candidate_config(cfg, p)
    m = find_manifest(Path(p.change["folder"]))
    plugins = copy.deepcopy(getattr(cfg, "plugins", None) or {})
    plugins[m.id] = {"enabled": True, "path": str(p.change["folder"]), "permissions": [], "version": m.version,
                     "source": "learned (on trial)"}
    return dataclasses.replace(variant, plugins=plugins, _shared={})


def candidate_for(lab: Lab, cfg: Any, p: Proposal) -> Any:
    """The candidate config for any kind: a tool gets its own plugin host; the others are ``lab.candidate_config``.
    (The yardstick builds its candidate with this.)"""
    spec = KINDS.get(p.kind)
    fn = getattr(spec, "candidate", None)
    return fn(lab, cfg, p) if fn else lab.candidate_config(cfg, p)


def propose_tool(cfg: Any, lab: Lab, idea: str, on_event: Emit | None = None,
                 most: float | None = None) -> Proposal | None:
    """Draft a tool for ``idea`` with the learning allowance, test it, and save it to wait for the owner.

    None when nothing was offered (the draft's tests failed or it broke a rule; written in the lab's history).
    Raises ``wallet.AllowanceUsed`` when learning has no money (nothing is drafted)."""
    from ..plugins import make
    from . import wallet, yardstick

    emit = on_event or (lambda *_: None)
    idea = " ".join(str(idea or "").split())
    if any(q.kind == "tool" and (q.change or {}).get("idea") == idea and q.status != "rejected"
           for q in lab.proposals()):
        return None  # already drafted (waiting, applied or undone): never paid for twice
    budget = wallet.budget(cfg, lab, "tool", most=most)  # unattended money comes only from the wallet
    draft = make.draft(cfg, idea, budget, on_event=on_event)
    if not draft["offered"]:
        lab._log("tool_not_offered", idea=idea[:200], why=draft["words"][:300], cost_usd=draft["cost_usd"])
        emit("tool_not_offered", {"idea": idea, "why": draft["words"]})
        return None
    p = Proposal(id="", kind="tool", role="", change={"idea": draft["idea"], "folder": draft["folder"],
                                                       "tools": sorted(draft["tools"])},
                 rationale=f"A tool for: {draft['idea']}", risk="high", source="llm",
                 evidence={"made": {"cost_usd": draft["cost_usd"], "model": draft["model"],
                                    "tests_passed": True, "summary": draft["summary"][:500]}})
    if lab.is_duplicate(p):
        return None
    lab.add_proposal(p)
    try:
        if yardstick.available(cfg, make.builder(cfg)[0]):
            res = yardstick.run(cfg, lab, p, budget, on_event=on_event)
            if res is not None:
                p.test = res
    except Exception as e:  # noqa: BLE001 - a tool that couldn't be measured still waits for the owner, said so
        p.test = {"verdict": "not measured", "passed": False, "why": str(e)[:300]}
    if p.test is None:
        p.test = {"verdict": "not measured", "passed": False,
                  "why": "There were no practice tasks to try it on, so only its own tests were run."}
    p.status = "needs_owner"  # never tested or applied by the cycle: the owner taps
    lab.save_proposal(p)
    lab._log("proposed", proposal=p.id, summary=p.summary(), kind="tool")
    emit("tool_proposed", {"id": p.id, "tools": p.change["tools"]})
    return p


# -- "kind" (a kind tweak) ----------------------------------------------------------------------------------------
def tweak_extra(change: dict[str, Any]) -> dict[str, Any]:
    """The extra a kind tweak would write (its own lines only); ValueError in plain words when it isn't allowed."""
    from ..kinds import model as kmodel

    if not isinstance(change, dict):
        raise ValueError("a kind tweak needs {kind_id, extra}")
    kid = str(change.get("kind_id") or "")
    if not kmodel.ID_RE.match(kid) or len(LEARNED_EXTRA + kid) > 40:
        raise ValueError("a kind tweak needs the kind's id")
    extra = change.get("extra")
    if not isinstance(extra, dict) or not extra:
        raise ValueError("a kind tweak needs the lines it adds ('extra')")
    bad = sorted(set(extra) - TWEAK_KEYS)
    if bad:
        raise ValueError(f"a kind tweak may only add plan don't lines, a task note and proof lines (not {', '.join(bad)})")
    plan = extra.get("plan")
    if plan is not None and (not isinstance(plan, dict) or set(plan) - {"dont"}):
        raise ValueError("a kind tweak's plan may only add don't lines")
    lines = len((plan or {}).get("dont") or []) + len(extra.get("proof") or []) + (1 if extra.get("task") else 0)
    if lines > MAX_TWEAK_LINES:
        raise ValueError(f"a kind tweak adds at most {MAX_TWEAK_LINES} lines")
    for i, item in enumerate(extra.get("proof") or []):
        if not isinstance(item, dict):
            raise ValueError("each proof line is a list of settings")
        if "command" in item or item.get("how") not in TWEAK_PROOF_HOW:
            raise ValueError("a kind tweak's proof line can't run a command: use page_opens, play, picture or "
                             "file_exists")
    raw = {"schema": kmodel.EXTRA_SCHEMA, "id": LEARNED_EXTRA + kid, "name": "What the harness learned",
           "status": "trial", **copy.deepcopy(extra)}
    data, probs = kmodel.validate(raw, is_extra=True)
    if data is None:
        raise ValueError("the kind tweak isn't right: " + "; ".join(probs[:3]))
    return data


def _validate_kind(p: Proposal, cfg: Any) -> None:
    tweak_extra(p.change)
    from .. import kinds as kindlib

    kid = p.change["kind_id"]
    if kid not in kindlib.load_all(_home()).kinds:
        raise ValueError(f"there's no kind called {kid!r}")


def _kind_summary(p: Proposal) -> str:
    e = (p.change or {}).get("extra") or {}
    n = len((e.get("plan") or {}).get("dont") or []) + len(e.get("proof") or []) + (1 if e.get("task") else 0)
    return f"{n} line{'s' if n != 1 else ''} for {p.change.get('kind_id')}"


def extra_dir(kind_id: str, home: Path | None = None) -> Path:
    return Path(home or _home()) / "kinds" / "_extras" / f"{LEARNED_EXTRA}{kind_id}"


def _merge_tweaks(tweaks: list[Proposal]) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for q in tweaks:
        e = tweak_extra(q.change)
        for d in (e.get("plan") or {}).get("dont") or []:
            dont = merged.setdefault("plan", {}).setdefault("dont", [])
            if d["text"] not in {x["text"] for x in dont}:
                dont.append(d)
        if e.get("task"):
            merged["task"] = "\n".join(x for x in (merged.get("task"), e["task"]) if x)
        for pr in e.get("proof") or []:
            proof = merged.setdefault("proof", [])
            proof[:] = [x for x in proof if x["id"] != pr["id"]] + [pr]
    return merged or None


def write_tweaks(lab: Lab, kind_id: str, skip: str = "", include: Proposal | None = None,
                 home: Path | None = None) -> Path | None:
    """Write the learned extra for ``kind_id`` from every applied tweak (but ``skip``, and with ``include``, the one
    being applied now, last). With none left, the extra is moved aside (``<app home>/kinds/.learned-aside``),
    never deleted."""
    tweaks = [q for q in lab.proposals("applied") if q.kind == "kind" and q.id not in (skip, getattr(include, "id", None))
              and (q.change or {}).get("kind_id") == kind_id]
    tweaks.sort(key=lambda q: q.applied_version or 0)
    if include is not None:
        tweaks.append(include)
    folder = extra_dir(kind_id, home)
    merged = _merge_tweaks(tweaks)
    if merged is None:
        if folder.exists():
            aside = Path(home or _home()) / "kinds" / ".learned-aside" / \
                f"{folder.name}-{utcnow().replace(':', '').replace('-', '')[:15]}"
            aside.parent.mkdir(parents=True, exist_ok=True)
            n = 1
            while aside.exists():
                aside = aside.with_name(f"{aside.name}-{n}")
                n += 1
            shutil.move(str(folder), str(aside))
        return None
    data = tweak_extra({"kind_id": kind_id, "extra": merged})
    data["blurb"] = f"Lines the harness learned for this kind ({', '.join(q.id for q in tweaks)})."
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "extra.yaml").write_text("# Written by the lab (learned kind tweaks). Undo them from What I learned.\n"
                                       + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return folder


def _kind_apply(lab: Lab, p: Proposal, cfg: Any) -> None:
    write_tweaks(lab, p.change["kind_id"], include=p)  # not "applied" yet while on_apply runs


def _kind_undo(lab: Lab, p: Proposal) -> None:
    write_tweaks(lab, p.change["kind_id"], skip=p.id)


def resolve_with_tweaks(kind_id: str, extras: list[str] | None = None, home: Path | str | None = None,
                        catalog: Any = None) -> Any:
    """``kinds.model.resolve`` with the kind's learned extra (if any) stacked on after the chosen ones."""
    from ..kinds import model as kmodel

    cat = catalog or kmodel.load_all(home if home is not None else _home())
    eid = LEARNED_EXTRA + kind_id
    chosen = [e for e in (extras or []) if e != eid]
    if eid in cat.extras and kind_id in cat.kinds:
        cat = copy.copy(cat)
        cat.kinds = dict(cat.kinds)
        k = copy.copy(cat.kinds[kind_id])
        k.spec = {**k.spec, "extras_allowed": [*(k.spec.get("extras_allowed") or []), eid]}
        cat.kinds[kind_id] = k
        chosen.append(eid)
    return kmodel.resolve(kind_id, chosen, catalog=cat)


# -- the registry -------------------------------------------------------------------------------------------------
TOOL = KindSpec("tool", _validate_tool, _tool_summary, _no_lay, on_apply=_tool_apply, on_undo=_tool_undo,
                needs_role=False)
TOOL.candidate = candidate_config  # type: ignore[attr-defined]  (read by candidate_for)
KIND = KindSpec("kind", _validate_kind, _kind_summary, _no_lay, on_apply=_kind_apply, on_undo=_kind_undo,
                needs_role=False)
register_kind(TOOL)
register_kind(KIND)
