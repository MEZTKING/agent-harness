"""``harness.yaml``: providers, roles, pricing, limits.

Everything that decides *who does what* lives here, so swapping a model,
adding a provider or changing a role is a config edit, not a code change.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field, replace
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

PROVIDER_TYPES = ("anthropic", "openai_compat", "openai_images", "retrodiffusion", "plugin", "scripted",
                  "scripted_images")
CLIENT_OPTS = ("auth_header", "auth_prefix", "headers", "query")  # extra openai_compat settings


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
    lab_dir: Path | None = None  # self-improvement lab (proposals, learned settings, versions)
    improve: dict[str, Any] = field(default_factory=dict)
    # prompt name -> text; learned prompts from the lab win over prompts_dir and built-ins
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    _instances: dict[str, Any] = field(default_factory=dict, repr=False)

    def variant(self) -> "HarnessConfig":
        """Independent copy of roles/prompts/limits that shares provider clients."""
        return replace(
            self,
            roles=copy.deepcopy(self.roles),
            prompt_overrides=dict(self.prompt_overrides),
            limits=copy.deepcopy(self.limits),
            _instances=self._instances,
        )

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

            inst = OpenAICompatProvider(name, api_key_env=spec.get("api_key_env"), base_url=spec.get("base_url"),
                                        **{k: spec[k] for k in CLIENT_OPTS if spec.get(k)})
        elif kind == "openai_images":
            from ..providers.openai_compat import OpenAIImagesProvider

            inst = OpenAIImagesProvider(name, api_key_env=spec.get("api_key_env"), base_url=spec.get("base_url"),
                                        **{k: spec[k] for k in CLIENT_OPTS if spec.get(k)})
        elif kind == "plugin":
            inst = self._load_plugin(name, spec)
        elif kind == "retrodiffusion":
            from ..providers.retrodiffusion import RetroDiffusionProvider

            inst = RetroDiffusionProvider(name, api_key_env=spec.get("api_key_env", "RETRODIFFUSION_API_KEY"),
                                          base_url=spec.get("base_url"))
        else:
            raise ProviderError(f"provider {name!r}: type {kind!r} cannot be built from config")
        self._instances[name] = inst
        return inst

    def _load_plugin(self, name: str, spec: dict[str, Any]):
        """type: plugin  ->  class: "module_or_file.py:ClassName", options: {...} passed to the constructor.

        Files are looked up in the plugins folder next to the config (plugins/), then on the
        Python path. The class must implement Provider.chat (and list_models) or
        ImageProvider.generate. Plugins are your own code and run with full access.
        """
        import importlib
        import importlib.util
        import sys

        target = spec.get("class", "")
        if ":" not in target:
            raise ProviderError(f"provider {name!r}: plugin needs class: 'module_or_file.py:ClassName'")
        modname, clsname = target.rsplit(":", 1)
        plugins_dir = (self.path.parent / "plugins") if self.path else Path.cwd() / "plugins"
        try:
            candidate = plugins_dir / modname if modname.endswith(".py") else plugins_dir / f"{modname}.py"
            if candidate.is_file():
                mod_spec = importlib.util.spec_from_file_location(f"roundtable_plugin_{name}", candidate)
                module = importlib.util.module_from_spec(mod_spec)
                sys.modules[mod_spec.name] = module
                mod_spec.loader.exec_module(module)
            else:
                module = importlib.import_module(modname.removesuffix(".py"))
            cls = getattr(module, clsname)
        except Exception as e:
            raise ProviderError(f"provider {name!r}: could not load plugin {target!r} ({type(e).__name__}: {e})") from e
        if not (isinstance(cls, type) and issubclass(cls, (Provider, ImageProvider))):
            raise ProviderError(f"provider {name!r}: {clsname} must subclass roundtable.providers.base.Provider "
                                "or ImageProvider")
        try:
            inst = cls(name, **(spec.get("options") or {}))
        except Exception as e:
            raise ProviderError(f"provider {name!r}: plugin {clsname} failed to start ({type(e).__name__}: {e})") from e
        if not isinstance(inst, (Provider, ImageProvider)):
            raise ProviderError(f"provider {name!r}: {clsname} must subclass roundtable.providers.base.Provider "
                                "or ImageProvider")
        inst.name = name
        return inst

    def register(self, name: str, instance: Provider | ImageProvider) -> None:
        """Inject a provider instance (tests, custom adapters)."""
        self.providers.setdefault(name, {"type": "scripted"})
        self._instances[name] = instance

    # -- prompts -----------------------------------------------------------
    def prompt_text(self, name: str) -> str:
        if "\n" in name or " " in name.strip():
            return name  # inline prompt text
        if name in self.prompt_overrides:
            return self.prompt_overrides[name]
        if self.prompts_dir:
            p = self.prompts_dir / f"{name}.md"
            if p.is_file():
                return p.read_text(encoding="utf-8")
        res = resources.files("roundtable").joinpath(f"prompts/{name}.md")
        if res.is_file():
            return res.read_text(encoding="utf-8")
        return resources.files("roundtable").joinpath("prompts/worker.md").read_text(encoding="utf-8")

    # -- pricing -----------------------------------------------------------
    def cost(self, ref: ModelRef, usage) -> float | None:
        if getattr(usage, "cost_usd", None) is not None:
            return usage.cost_usd  # provider reported the exact charge
        price = self.pricing.get(str(ref)) or self.pricing.get(ref.model) or DEFAULT_PRICING.get(ref.model)
        if not price:
            return None
        return (
            usage.input_tokens * price.get("input", 0)
            + usage.output_tokens * price.get("output", 0)
            + usage.cache_read_tokens * price.get("cache_read", price.get("input", 0))
            + usage.cache_write_tokens * price.get("cache_write", price.get("input", 0) * 1.25)
        ) / 1_000_000


def apply_overlay(cfg: HarnessConfig, overlay: dict[str, Any], prompts: dict[str, str] | None = None) -> None:
    """Layer learned settings on top of a config (in place).

    overlay = {"roles": {role: {"model": "...", "fallback": [...], "options": {...}}}}
    prompts = {prompt name: text}
    """
    for name, spec in (overlay.get("roles") or {}).items():
        role = cfg.roles.get(name)
        if not role:
            continue  # role was removed from harness.yaml; ignore stale learning
        if "model" in spec:
            models = [ModelRef.parse(spec["model"])] + [ModelRef.parse(m) for m in spec.get("fallback", [])]
            for m in models:
                if cfg.providers and m.provider not in cfg.providers:
                    raise ValueError(f"learned routing for {name!r} uses unknown provider {m.provider!r}")
            role.models = models
        if "options" in spec:
            role.options = dict(spec["options"])
    cfg.prompt_overrides.update(prompts or {})


# -- custom.yaml: providers and model choices made in the app / CLI ---------------------------------
def custom_path(harness_path: Path) -> Path:
    return harness_path.parent / "custom.yaml"


def load_custom(harness_path: Path | None) -> dict[str, Any]:
    if not harness_path:
        return {}
    p = custom_path(harness_path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}


def save_custom(harness_path: Path, data: dict[str, Any]) -> None:
    custom_path(harness_path).write_text(
        "# Providers and model choices added from the Roundtable Hold app or `roundtable providers`.\n"
        "# Merged on top of harness.yaml (which is never rewritten). Safe to edit by hand.\n"
        + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def merge_custom(raw: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    """custom.yaml adds providers (harness.yaml wins on a name clash) and overrides role models."""
    if not custom:
        return raw
    out = dict(raw)
    providers = dict(custom.get("providers") or {})
    providers.update(raw.get("providers") or {})
    out["providers"] = providers
    roles = {k: dict(v or {}) for k, v in (raw.get("roles") or {}).items()}
    for role, spec in (custom.get("roles") or {}).items():
        if role in roles:
            roles[role].update({k: v for k, v in spec.items() if k in ("model", "fallback")})
        elif spec.get("model"):
            roles[role] = dict(spec)  # a brand-new role defined in the app
    out["roles"] = roles
    return out


def find_config(explicit: str | None = None) -> Path:
    for c in (explicit, os.environ.get("HARNESS_CONFIG"), "harness.yaml", "~/.roundtable/harness.yaml", "~/.agent-harness/harness.yaml"):
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    raise FileNotFoundError("No harness config found. Pass --config, set HARNESS_CONFIG, or run `roundtable init`.")


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
        lab_dir=_lab_dir(raw, base, path),
        improve=dict(raw.get("improve") or {}),
    )


def _lab_dir(raw: dict[str, Any], base: Path, path: Path | None) -> Path | None:
    imp = raw.get("improve") or {}
    if imp.get("lab_dir"):
        return (base / Path(imp["lab_dir"]).expanduser()).resolve()
    return (base / ".harness-lab") if path else None


def load_config(explicit: str | None = None) -> HarnessConfig:
    path = find_config(explicit)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = merge_custom(raw, load_custom(path))
    cfg = parse_config(raw, path)
    if cfg.lab_dir and cfg.lab_dir.is_dir():
        from ..improve.lab import Lab

        Lab(cfg.lab_dir).apply_learned(cfg)
    return cfg
