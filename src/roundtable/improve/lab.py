"""The lab: where the harness keeps what it has learned.

    <lab>/projects.json          projects the harness has run (data source)
    <lab>/proposals/<id>.json    proposed changes + their test results
    <lab>/learned.yaml           routing/options overlay applied on top of harness.yaml
    <lab>/prompts/<name>.md      learned prompts (override built-ins / prompts_dir)
    <lab>/versions/NNNN/         snapshot of learned.yaml + prompts/ taken BEFORE
                                 each applied change -> exact rollback
    <lab>/history.jsonl          what was applied / rolled back, when, why

harness.yaml itself is never rewritten, so your comments and layout survive
and "what did the system learn" is always one file to read.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.models import new_id, utcnow
from ..harness.config import HarnessConfig, ModelRef, apply_overlay

PROPOSAL_KINDS = ("routing", "options", "prompt")
RISKS = ("low", "medium", "high")
STATUSES = ("proposed", "tested", "applied", "rejected", "rolled_back")


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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Proposal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def summary(self) -> str:
        if self.kind == "routing":
            what = " -> ".join(self.change["models"])
        elif self.kind == "options":
            what = json.dumps(self.change["options"])
        else:
            what = f"new prompt ({len(self.change['prompt_text'])} chars)"
        return f"{self.kind:7} {self.role:12} {what}"

    def validate(self, cfg: HarnessConfig) -> None:
        if self.kind not in PROPOSAL_KINDS:
            raise ValueError(f"unknown kind {self.kind!r}")
        if self.risk not in RISKS:
            raise ValueError(f"unknown risk {self.risk!r}")
        role = cfg.roles.get(self.role)
        if not role:
            raise ValueError(f"unknown role {self.role!r}")
        if self.kind == "routing":
            models = self.change.get("models")
            if not isinstance(models, list) or not models:
                raise ValueError("routing change needs a non-empty 'models' list")
            for m in models:
                ref = ModelRef.parse(m)
                if cfg.providers and ref.provider not in cfg.providers:
                    raise ValueError(f"unknown provider {ref.provider!r} in {m!r}")
        elif self.kind == "options":
            if not isinstance(self.change.get("options"), dict):
                raise ValueError("options change needs an 'options' object")
        elif self.kind == "prompt":
            text = self.change.get("prompt_text")
            if not isinstance(text, str) or len(text.strip()) < 40:
                raise ValueError("prompt change needs a full 'prompt_text'")
            if role.kind != "chat":
                raise ValueError("only chat roles have prompts")


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
        with open(self.root / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": utcnow(), "event": event, **data}, ensure_ascii=False) + "\n")

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
        out = [Proposal.from_dict(json.loads(f.read_text())) for f in sorted(d.glob("*.json"))]
        out.sort(key=lambda p: p.created_at)
        return [p for p in out if status is None or p.status == status]

    def is_duplicate(self, p: Proposal) -> bool:
        """Same change already pending or applied."""
        for q in self.proposals():
            if q.status in ("proposed", "tested", "applied") and q.kind == p.kind and q.role == p.role and q.change == p.change:
                return True
        return False

    # -- learned state -------------------------------------------------------------
    def learned(self) -> tuple[dict[str, Any], dict[str, str]]:
        overlay_path = self.root / "learned.yaml"
        overlay = yaml.safe_load(overlay_path.read_text()) if overlay_path.is_file() else {}
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
        """Mutate overlay/prompts to include proposal ``p``."""
        roles = overlay.setdefault("roles", {})
        entry = roles.setdefault(p.role, {})
        if p.kind == "routing":
            entry["model"] = p.change["models"][0]
            entry["fallback"] = list(p.change["models"][1:])
        elif p.kind == "options":
            entry["options"] = dict(p.change["options"])
        elif p.kind == "prompt":
            prompts[cfg.roles[p.role].prompt] = p.change["prompt_text"]

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
        (vdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    def apply(self, p: Proposal, cfg: HarnessConfig, reason: str = "manual") -> int:
        p.validate(cfg)
        overlay, prompts = self.learned()
        version = (self._versions() or [0])[-1] + 1
        self._snapshot(version, {"proposal": p.id, "at": utcnow(), "summary": p.summary(), "reason": reason})
        self.change_overlay(overlay, prompts, p, cfg)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "learned.yaml").write_text(
            "# Learned by `roundtable improve`. Layered on top of harness.yaml. Roll back with `roundtable improve rollback`.\n"
            + yaml.safe_dump(overlay, sort_keys=True)
        )
        if prompts:
            (self.root / "prompts").mkdir(exist_ok=True)
            for name, text in prompts.items():
                (self.root / "prompts" / f"{name}.md").write_text(text, encoding="utf-8")
        p.status = "applied"
        p.applied_version = version
        self.save_proposal(p)
        self._log("applied", proposal=p.id, version=version, summary=p.summary(), reason=reason)
        return version

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
        for v in undone:
            shutil.rmtree(self.root / "versions" / f"{v:04d}")
        self._log("rolled_back", versions=undone)
        return version

    def history(self) -> list[dict[str, Any]]:
        p = self.root / "history.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
