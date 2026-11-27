"""The lab: where the harness keeps what it has learned.

    <lab>/projects.json          projects the harness has run (data source)
    <lab>/proposals/<id>.json    proposed changes + their test results
    <lab>/learned.yaml           routing/options overlay applied on top of harness.yaml
    <lab>/prompts/<name>.md      learned prompts (override built-ins / prompts_dir)
    <lab>/versions/NNNN/         snapshot of learned.yaml + prompts/ taken BEFORE
                                 each applied change -> exact rollback
    <lab>/history.jsonl          what was applied / undone / rolled back, when, why
                                 (each row has its own ``id`` and the ``machine`` it happened on)

harness.yaml itself is never rewritten, so your comments and layout survive
and "what did the system learn" is always one file to read.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.models import new_id, utcnow
from ..harness.config import HarnessConfig, ModelRef, apply_overlay

PROPOSAL_KINDS = ("routing", "options", "prompt")  # the analyst's own enum (analysis.py); KINDS may hold more
RISKS = ("low", "medium", "high")
STATUSES = ("proposed", "tested", "applied", "rejected", "rolled_back")
STATUSES += ("undone", "needs_owner")  # undone: by the watch (canary.py); needs_owner: the charter wants a tap
LEARNED_HEADER = ("# Learned by `roundtable improve`. Layered on top of harness.yaml. "
                  "Roll back with `roundtable improve rollback`.\n")


@dataclass
class Proposal:
    id: str
    kind: str  # routing | options | prompt
    role: str
    change: dict[str, Any]  # routing: {"models": [...]}, options: {"options": {...}}, prompt: {"prompt_text": "..."}
    rationale: str
    risk: str = "medium"
    source: str = "rules"  # rules | llm
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"
    created_at: str = ""
    test: dict[str, Any] | None = None  # replay results
    applied_version: int | None = None
    applied_at: str = ""  # when it was last applied
    machine: str = ""  # the machine it was applied on (sync.this_machine()["id"])
    watch: dict[str, Any] | None = None  # what the watch (canary.py) keeps about it after it is applied
    undone_why: str = ""  # why it was undone by itself (or by the owner), in plain words
    origin: str = ""  # the id it had on the machine that made it (sharing between machines)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Proposal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def summary(self) -> str:
        spec = KINDS.get(self.kind)
        what = spec.summary(self) if spec else json.dumps(self.change, sort_keys=True)
        return f"{self.kind:7} {self.role:12} {what}"

    def validate(self, cfg: HarnessConfig) -> None:
        spec = KINDS.get(self.kind)
        if spec is None:
            raise ValueError(f"unknown kind {self.kind!r}")
        if self.risk not in RISKS:
            raise ValueError(f"unknown risk {self.risk!r}")
        if spec.needs_role and not cfg.roles.get(self.role):
            raise ValueError(f"unknown role {self.role!r}")
        spec.validate(self, cfg)


# -- the kinds of change the lab knows ----------------------------------------------------------------
@dataclass
class KindSpec:
    """One kind of learned change. ``lay`` changes the overlay and prompts in place (it may do nothing,
    e.g. a kind whose change lives elsewhere and is switched on by ``on_apply``)."""

    name: str
    validate: Callable[[Proposal, HarnessConfig], None]
    summary: Callable[[Proposal], str]
    lay: Callable[[dict, dict, Proposal, HarnessConfig], None]
    on_apply: Callable[["Lab", Proposal, HarnessConfig], None] | None = None  # e.g. switch a plugin on
    on_undo: Callable[["Lab", Proposal], None] | None = None
    needs_role: bool = True


KINDS: dict[str, KindSpec] = {}


def register_kind(spec: KindSpec) -> None:
    """Add (or replace) a kind. Later kinds ("tool", "kind") register themselves when their module loads."""
    KINDS[spec.name] = spec


def _role_entry(overlay: dict[str, Any], role: str) -> dict[str, Any]:
    return overlay.setdefault("roles", {}).setdefault(role, {})


def _validate_routing(p: Proposal, cfg: HarnessConfig) -> None:
    models = p.change.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("routing change needs a non-empty 'models' list")
    for m in models:
        ref = ModelRef.parse(m)
        if cfg.providers and ref.provider not in cfg.providers:
            raise ValueError(f"unknown provider {ref.provider!r} in {m!r}")


def _lay_routing(overlay: dict, prompts: dict, p: Proposal, cfg: HarnessConfig) -> None:
    entry = _role_entry(overlay, p.role)
    entry["model"] = p.change["models"][0]
    entry["fallback"] = list(p.change["models"][1:])


def _validate_options(p: Proposal, cfg: HarnessConfig) -> None:
    if not isinstance(p.change.get("options"), dict):
        raise ValueError("options change needs an 'options' object")


def _lay_options(overlay: dict, prompts: dict, p: Proposal, cfg: HarnessConfig) -> None:
    _role_entry(overlay, p.role)["options"] = dict(p.change["options"])


def _validate_prompt(p: Proposal, cfg: HarnessConfig) -> None:
    text = p.change.get("prompt_text")
    if not isinstance(text, str) or len(text.strip()) < 40:
        raise ValueError("prompt change needs a full 'prompt_text'")
    if cfg.roles[p.role].kind != "chat":
        raise ValueError("only chat roles have prompts")


def _lay_prompt(overlay: dict, prompts: dict, p: Proposal, cfg: HarnessConfig) -> None:
    _role_entry(overlay, p.role)  # as before: the role gets an (empty) entry in learned.yaml
    prompts[cfg.roles[p.role].prompt] = p.change["prompt_text"]


register_kind(KindSpec("routing", _validate_routing, lambda p: " -> ".join(p.change["models"]), _lay_routing))
register_kind(KindSpec("options", _validate_options, lambda p: json.dumps(p.change["options"]), _lay_options))
register_kind(KindSpec("prompt", _validate_prompt,
                       lambda p: f"new prompt ({len(p.change['prompt_text'])} chars)", _lay_prompt))


def _machine() -> str:
    from ..sync import this_machine

    try:
        return this_machine()["id"]
    except Exception:  # noqa: BLE001 - a name for the row, never a reason to fail
        return ""


class Lab:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # -- basic io --------------------------------------------------------------
    def _json(self, rel: str, default):
        p = self.root / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default

    def _write_json(self, rel: str, data) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _log(self, event: str, **data) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        row = {"at": utcnow(), "id": f"H{new_id()[-8:]}", "machine": _machine(), "event": event, **data}
        with open(self.root / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # -- projects ----------------------------------------------------------------
    def register_project(self, path: str | Path) -> None:
        projects = self._json("projects.json", [])
        p = str(Path(path).resolve())
        if p not in projects:
            projects.append(p)
            self._write_json("projects.json", projects)

    def projects(self) -> list[Path]:
        return [Path(p) for p in self._json("projects.json", []) if (Path(p) / ".harness/project.json").is_file()]

    # -- proposals -----------------------------------------------------------------
    def add_proposal(self, p: Proposal) -> Proposal:
        p.id = p.id or f"P{new_id()[-6:]}"
        p.created_at = p.created_at or utcnow()
        self.save_proposal(p)
        return p

    def save_proposal(self, p: Proposal) -> None:
        self._write_json(f"proposals/{p.id}.json", asdict(p))

    def proposal(self, pid: str) -> Proposal:
        data = self._json(f"proposals/{pid}.json", None)
        if data is None:
            raise KeyError(f"no proposal {pid!r}")
        return Proposal.from_dict(data)

    def proposals(self, status: str | None = None) -> list[Proposal]:
        d = self.root / "proposals"
        if not d.is_dir():
            return []
        out = [Proposal.from_dict(json.loads(f.read_text(encoding="utf-8"))) for f in sorted(d.glob("*.json"))]
        out.sort(key=lambda p: p.created_at)
        return [p for p in out if status is None or p.status == status]

    def is_duplicate(self, p: Proposal) -> bool:
        """Same change already pending or applied, or undone (an undone change is not offered again)."""
        for q in self.proposals():
            if q.status in ("proposed", "tested", "applied", "undone") and q.kind == p.kind and q.role == p.role and q.change == p.change:
                return True
        return False

    # -- learned state -------------------------------------------------------------
    def learned(self) -> tuple[dict[str, Any], dict[str, str]]:
        overlay_path = self.root / "learned.yaml"
        overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) if overlay_path.is_file() else {}
        prompts = {}
        pdir = self.root / "prompts"
        if pdir.is_dir():
            prompts = {f.stem: f.read_text(encoding="utf-8") for f in pdir.glob("*.md")}
        return overlay or {}, prompts

    def apply_learned(self, cfg: HarnessConfig) -> None:
        overlay, prompts = self.learned()
        apply_overlay(cfg, overlay, prompts)
        cfg.learned = overlay  # kept, so a profile chosen later can still use the learned order

    @staticmethod
    def change_overlay(overlay: dict[str, Any], prompts: dict[str, str], p: Proposal, cfg: HarnessConfig) -> None:
        """Mutate overlay/prompts to include proposal ``p`` (its kind's ``lay``)."""
        KINDS[p.kind].lay(overlay, prompts, p, cfg)

    def candidate_config(self, cfg: HarnessConfig, p: Proposal) -> HarnessConfig:
        """A copy of ``cfg`` with proposal ``p`` applied (nothing written to disk)."""
        variant = cfg.variant()
        overlay: dict[str, Any] = {}
        prompts: dict[str, str] = {}
        self.change_overlay(overlay, prompts, p, cfg)
        apply_overlay(variant, overlay, prompts)
        return variant

    # -- versions ----------------------------------------------------------------------
    def _versions(self) -> list[int]:
        d = self.root / "versions"
        return sorted(int(x.name) for x in d.iterdir() if x.name.isdigit()) if d.is_dir() else []

    def _snapshot(self, version: int, meta: dict[str, Any]) -> None:
        vdir = self.root / "versions" / f"{version:04d}"
        vdir.mkdir(parents=True, exist_ok=True)
        if (self.root / "learned.yaml").is_file():
            shutil.copy2(self.root / "learned.yaml", vdir / "learned.yaml")
        if (self.root / "prompts").is_dir():
            shutil.copytree(self.root / "prompts", vdir / "prompts", dirs_exist_ok=True)
        (vdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    def _write_state(self, overlay: dict[str, Any], prompts: dict[str, str], replace: bool = False) -> None:
        """Write learned.yaml and the prompts. ``replace``: prompts not in ``prompts`` are removed."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "learned.yaml").write_text(LEARNED_HEADER + yaml.safe_dump(overlay, sort_keys=True),
                                                encoding="utf-8")
        pdir = self.root / "prompts"
        if replace and pdir.is_dir():
            shutil.rmtree(pdir)
        if prompts:
            pdir.mkdir(exist_ok=True)
            for name, text in prompts.items():
                (pdir / f"{name}.md").write_text(text, encoding="utf-8")

    def apply(self, p: Proposal, cfg: HarnessConfig, reason: str = "manual", by_owner: bool = False) -> int:
        from . import canary, charter

        p.validate(cfg)
        try:
            charter.check(cfg, p, self, by_owner=by_owner)
        except charter.CharterError as e:
            if getattr(e, "needs_owner", False) and not by_owner:
                p.status = "needs_owner"
                self.save_proposal(p)
                self._log("needs_owner", proposal=p.id, summary=p.summary(), why=str(e)[:300])
            raise
        overlay, prompts = self.learned()
        version = (self._versions() or [0])[-1] + 1
        self._snapshot(version, {"proposal": p.id, "at": utcnow(), "summary": p.summary(), "reason": reason})
        self.change_overlay(overlay, prompts, p, cfg)
        self._write_state(overlay, prompts)
        spec = KINDS[p.kind]
        if spec.on_apply:
            spec.on_apply(self, p, cfg)
        p.status = "applied"
        p.applied_version = version
        p.applied_at = utcnow()
        p.machine = _machine()
        p.undone_why = ""
        self.save_proposal(p)
        self._log("applied", proposal=p.id, version=version, summary=p.summary(), reason=reason)
        canary.start(self, p, version)
        return version

    @staticmethod
    def _lay_all(overlay: dict[str, Any], prompts: dict[str, str], changes: list[Proposal],
                 cfg: HarnessConfig) -> None:
        for q in changes:
            if q.kind in KINDS:
                KINDS[q.kind].lay(overlay, prompts, q, cfg)

    def rebuild(self, changes: list[Proposal], cfg: HarnessConfig) -> None:
        """The learned state as a pure function of an ordered list of changes: learned.yaml and the prompts
        become exactly what laying them in order on nothing gives (used by undo and by sharing)."""
        overlay: dict[str, Any] = {}
        prompts: dict[str, str] = {}
        self._lay_all(overlay, prompts, changes, cfg)
        self._write_state(overlay, prompts, replace=True)

    def _read_snapshot(self, version: int) -> tuple[dict[str, Any], dict[str, str]]:
        vdir = self.root / "versions" / f"{version:04d}"
        overlay = {}
        if (vdir / "learned.yaml").is_file():
            overlay = yaml.safe_load((vdir / "learned.yaml").read_text(encoding="utf-8")) or {}
        prompts = {}
        if (vdir / "prompts").is_dir():
            prompts = {f.stem: f.read_text(encoding="utf-8") for f in (vdir / "prompts").glob("*.md")}
        return overlay, prompts

    def undo(self, pid: str, why: str = "", by: str = "owner", cfg: HarnessConfig | None = None) -> int:
        """Undo one applied change by itself; every other change stays. Returns the new version (a snapshot
        of the state before the undo, so ``rollback`` of it puts the change back).

        The state is rebuilt from the snapshot taken before the earliest change that is no longer in force
        (this one, or one undone earlier whose snapshot is still kept), with every still-applied change
        from then on laid again in order. ``cfg`` is needed for prompt changes (which prompt file a role
        uses); without it the harness's config is loaded."""
        p = self.proposal(pid)
        if p.status != "applied" or p.applied_version is None:
            raise ValueError(f"{pid} is not applied, so there is nothing to undo")
        versions = self._versions()
        if p.applied_version not in versions:
            raise ValueError(f"{pid}'s snapshot is gone (it was rolled back); nothing to undo")
        if cfg is None:
            from ..harness.config import load_config

            try:
                cfg = load_config()
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"Couldn't read the harness settings to undo {pid}: {e}") from e
        out = [q for q in self.proposals() if q.status in ("undone", "rolled_back") and q.applied_version in versions]
        base = min([p.applied_version, *(q.applied_version for q in out if q.applied_version is not None)])
        keep = sorted((q for q in self.proposals("applied") if q.id != p.id and (q.applied_version or 0) >= base),
                      key=lambda q: q.applied_version or 0)
        version = versions[-1] + 1
        self._snapshot(version, {"undo": p.id, "at": utcnow(), "summary": f"undo {p.summary()}", "reason": why or by})
        overlay, prompts = self._read_snapshot(base)
        self._lay_all(overlay, prompts, keep, cfg)
        self._write_state(overlay, prompts, replace=True)
        spec = KINDS.get(p.kind)
        if spec and spec.on_undo:
            spec.on_undo(self, p)
        p.status = "rolled_back" if by == "owner" else "undone"
        p.undone_why = why
        self.save_proposal(p)
        self._log("undone", proposal=p.id, version=version, summary=p.summary(), by=by, why=why)
        return version

    def state_id(self) -> str:
        """A short fingerprint of what has been learned (learned.yaml's settings and the prompts): two labs
        with the same learned state give the same id, whatever the file's comments."""
        overlay, prompts = self.learned()
        blob = json.dumps({"overlay": overlay, "prompts": dict(sorted(prompts.items()))}, sort_keys=True,
                          ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def rollback(self, version: int | None = None) -> int:
        """Restore the state from before ``version`` (default: the latest applied change).
        Changes applied after it are undone too."""
        versions = self._versions()
        if not versions:
            raise ValueError("nothing to roll back")
        version = version or versions[-1]
        if version not in versions:
            raise ValueError(f"no version {version}; have {versions}")
        vdir = self.root / "versions" / f"{version:04d}"
        learned = self.root / "learned.yaml"
        if (vdir / "learned.yaml").is_file():
            shutil.copy2(vdir / "learned.yaml", learned)
        elif learned.exists():
            learned.unlink()
        if (self.root / "prompts").is_dir():
            shutil.rmtree(self.root / "prompts")
        if (vdir / "prompts").is_dir():
            shutil.copytree(vdir / "prompts", self.root / "prompts")
        undone = [v for v in versions if v >= version]
        for p in self.proposals("applied"):
            if p.applied_version in undone:
                p.status = "rolled_back"
                self.save_proposal(p)
                spec = KINDS.get(p.kind)
                if spec and spec.on_undo:  # e.g. a tool rolled past is switched off too (its files are kept)
                    try:
                        spec.on_undo(self, p)
                    except Exception as e:  # noqa: BLE001 - the state is already restored; say what was left on
                        self._log("undo_hook_failed", proposal=p.id, error=str(e)[:300])
        for v in undone:  # an undo rolled back: the change it took out is in force again
            meta = self._json(f"versions/{v:04d}/meta.json", {})
            if meta.get("undo"):
                try:
                    q = self.proposal(meta["undo"])
                except KeyError:
                    continue
                if q.status in ("undone", "rolled_back") and (q.applied_version or 0) < version:
                    q.status, q.undone_why = "applied", ""
                    self.save_proposal(q)
        for v in undone:
            shutil.rmtree(self.root / "versions" / f"{v:04d}")
        self._log("rolled_back", versions=undone)
        return version

    def history(self) -> list[dict[str, Any]]:
        p = self.root / "history.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []
