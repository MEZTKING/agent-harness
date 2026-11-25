"""``harness.yaml``: providers, roles, pricing, limits.

Everything that decides *who does what* lives here, so swapping a model,
adding a provider or changing a role is a config edit, not a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..providers.base import ImageProvider, Provider, ProviderError

# Anthropic list prices (USD per 1M tokens). Anything else: set `pricing:` in harness.yaml.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5-2": {"input": 8.0, "output": 40.0, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
}

PROVIDER_TYPES = ("anthropic", "openai_compat", "openai_images", "scripted", "scripted_images")


@dataclass
class ModelRef:
    provider: str
    model: str

    @classmethod
    def parse(cls, s: str) -> "ModelRef":
        if "/" not in s:
            raise ValueError(f"model {s!r} must be '<provider>/<model>', e.g. 'deepseek/deepseek-v4-pro'")
        p, m = s.split("/", 1)
        return cls(p, m)

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass
class RoleSpec:
    name: str
    models: list[ModelRef]  # primary first, then fallbacks
    kind: str = "chat"  # chat | image
    description: str = ""
    prompt: str = ""  # prompt file name (without .md) or inline text; defaults to role name
    max_tokens: int = 16000
    options: dict[str, Any] = field(default_factory=dict)  # provider-specific (effort, temperature...)
    review: bool = True  # have the reviewer check this role's work
    tools: list[str] | None = None  # restrict workspace tools; None = role default


@dataclass
class Limits:
    max_cost_usd: float = 10.0
    max_steps_per_task: int = 40
    max_attempts_per_task: int = 3
    command_timeout: int = 120
    max_parallel: int = 1


@dataclass
class HarnessConfig:
    path: Path | None
    providers: dict[str, dict[str, Any]]
    roles: dict[str, RoleSpec]
    pricing: dict[str, dict[str, float]]
    limits: Limits
    allow_shell: bool = True
    git: bool = True
    planner_role: str = "orchestrator"
    reviewer_role: str | None = "reviewer"
    prompts_dir: Path | None = None
    hub: dict[str, Any] | None = None
    _instances: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- providers -------------------------------------------------------
    def provider(self, name: str) -> Provider | ImageProvider:
        if name in self._instances:
            return self._instances[name]
        if name not in self.providers:
            raise ProviderError(f"unknown provider {name!r}; configured: {sorted(self.providers)}")
        spec = self.providers[name]
        kind = spec.get("type")
        if kind == "anthropic":
            from ..providers.anthropic_provider import AnthropicProvider

            inst = AnthropicProvider(api_key_env=spec.get("api_key_env", "ANTHROPIC_API_KEY"), base_url=spec.get("base_url"))
        elif kind == "openai_compat":
            from ..providers.openai_compat import OpenAICompatProvider

            inst = OpenAICompatProvider(name, api_key_env=spec.get("api_key_env"), base_url=spec.get("base_url"))
        elif kind == "openai_images":
            from ..providers.openai_compat import OpenAIImagesProvider

            inst = OpenAIImagesProvider(name, api_key_env=spec.get("api_key_env"), base_url=spec.get("base_url"))
        else:
            raise ProviderError(f"provider {name!r}: type {kind!r} cannot be built from config")
        self._instances[name] = inst
        return inst

    def register(self, name: str, instance: Provider | ImageProvider) -> None:
        """Inject a provider instance (tests, custom adapters)."""
        self.providers.setdefault(name, {"type": "scripted"})
        self._instances[name] = instance

    # -- prompts -----------------------------------------------------------
    def prompt_text(self, name: str) -> str:
        if "\n" in name or " " in name.strip():
            return name  # inline prompt text
        if self.prompts_dir:
            p = self.prompts_dir / f"{name}.md"
            if p.is_file():
                return p.read_text(encoding="utf-8")
        res = resources.files("agentharness").joinpath(f"prompts/{name}.md")
        if res.is_file():
            return res.read_text(encoding="utf-8")
        return resources.files("agentharness").joinpath("prompts/worker.md").read_text(encoding="utf-8")

    # -- pricing -----------------------------------------------------------
    def cost(self, ref: ModelRef, usage) -> float | None:
        price = self.pricing.get(str(ref)) or self.pricing.get(ref.model) or DEFAULT_PRICING.get(ref.model)
        if not price:
            return None
        return (
            usage.input_tokens * price.get("input", 0)
            + usage.output_tokens * price.get("output", 0)
            + usage.cache_read_tokens * price.get("cache_read", price.get("input", 0))
            + usage.cache_write_tokens * price.get("cache_write", price.get("input", 0) * 1.25)
        ) / 1_000_000


def find_config(explicit: str | None = None) -> Path:
    for c in (explicit, os.environ.get("HARNESS_CONFIG"), "harness.yaml", "~/.agent-harness/harness.yaml"):
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    raise FileNotFoundError("No harness config found. Pass --config, set HARNESS_CONFIG, or run `harness init`.")


def parse_config(raw: dict[str, Any], path: Path | None = None) -> HarnessConfig:
    providers = raw.get("providers") or {}
    for name, spec in providers.items():
        if (spec or {}).get("type") not in PROVIDER_TYPES:
            raise ValueError(f"provider {name!r}: type must be one of {PROVIDER_TYPES}")

    roles: dict[str, RoleSpec] = {}
    for name, spec in (raw.get("roles") or {}).items():
        spec = spec or {}
        if "model" not in spec:
            raise ValueError(f"role {name!r} needs a model ('<provider>/<model>')")
        models = [ModelRef.parse(spec["model"])] + [ModelRef.parse(m) for m in spec.get("fallback", [])]
        for m in models:
            if providers and m.provider not in providers:
                raise ValueError(f"role {name!r}: unknown provider {m.provider!r}")
        kind = spec.get("kind", "chat")
        if kind not in ("chat", "image"):
            raise ValueError(f"role {name!r}: kind must be 'chat' or 'image'")
        roles[name] = RoleSpec(
            name=name,
            models=models,
            kind=kind,
            description=spec.get("description", ""),
            prompt=spec.get("prompt", name),
            max_tokens=int(spec.get("max_tokens", 16000)),
            options=dict(spec.get("options", {})),
            review=bool(spec.get("review", kind == "chat")),
            tools=spec.get("tools"),
        )

    planner = raw.get("planner_role", "orchestrator")
    reviewer = raw.get("reviewer_role", "reviewer")
    if planner not in roles:
        raise ValueError(f"planner_role {planner!r} is not defined under roles")
    if reviewer and reviewer not in roles:
        reviewer = None

    lim = raw.get("limits") or {}
    base = path.parent if path else Path.cwd()
    prompts_dir = raw.get("prompts_dir")
    ws = raw.get("workspace") or {}
    return HarnessConfig(
        path=path,
        providers=providers,
        roles=roles,
        pricing=raw.get("pricing") or {},
        limits=Limits(
            max_cost_usd=float(lim.get("max_cost_usd", 10.0)),
            max_steps_per_task=int(lim.get("max_steps_per_task", 40)),
            max_attempts_per_task=int(lim.get("max_attempts_per_task", 3)),
            command_timeout=int(lim.get("command_timeout", 120)),
        ),
        allow_shell=bool(ws.get("allow_shell", True)),
        git=bool(ws.get("git", True)),
        planner_role=planner,
        reviewer_role=reviewer,
        prompts_dir=(base / prompts_dir) if prompts_dir else None,
        hub=raw.get("hub"),
    )


def load_config(explicit: str | None = None) -> HarnessConfig:
    path = find_config(explicit)
    return parse_config(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, path)
