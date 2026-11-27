"""``harness.yaml``: providers, roles, pricing, limits.

Everything that decides *who does what* lives here, so swapping a model,
adding a provider or changing a role is a config edit, not a code change.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import os
import re
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..providers.base import ImageProvider, Provider, ProviderError
from .saver import SaverConfig

# Anthropic list prices (USD per 1M tokens). Anything else: set `pricing:` in harness.yaml.
# DeepSeek's peak hours (UTC) since August 2026, as reported; outside them prices are halved (verify)
DEEPSEEK_PEAK = ["01:00-04:00", "06:00-10:00"]


def in_peak(windows: list[str], now: datetime | None = None) -> bool:
    """True when `now` (UTC) falls in one of the "HH:MM-HH:MM" windows."""
    t = (now or datetime.now(timezone.utc)).strftime("%H:%M")
    return any(a <= t < b for a, b in (w.split("-") for w in windows or []))


def next_offpeak(windows: list[str], now: datetime | None = None) -> datetime:
    """The next moment outside every peak window (now, if already off-peak)."""
    t = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    for _ in range(24 * 60):
        if not in_peak(windows, t):
            return t
        t += timedelta(minutes=1)
    return t


def price_now(price: dict, now: datetime | None = None) -> dict:
    """A price with off-peak rates applied when the provider has them and it's off-peak now."""
    if price.get("offpeak") and price.get("peak_utc") and not in_peak(price["peak_utc"], now):
        return {**price, **price["offpeak"]}
    return price


DEFAULT_PRICING: dict[str, dict] = {
    "claude-fable-5-2": {"input": 8.0, "output": 40.0, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    # DeepSeek direct (official page, checked 26 November 2026): half price outside its peak hours
    "deepseek-flash": {"input": 0.44, "output": 1.32, "cache_read": 0.014,
                       "offpeak": {"input": 0.22, "output": 0.66, "cache_read": 0.007}, "peak_utc": DEEPSEEK_PEAK},
    "deepseek-v4-flash": {"input": 0.44, "output": 1.32, "cache_read": 0.014,
                          "offpeak": {"input": 0.22, "output": 0.66, "cache_read": 0.007}, "peak_utc": DEEPSEEK_PEAK},
    # Openference's names for some of its models (its prices, checked 26 November 2026)
    "DeepSeek-V4.1-Flash-1017": {"input": 0.30, "output": 1.20, "cache_read": 0.01},
    "DeepSeek-V4-Pro": {"input": 1.32, "output": 3.96, "cache_read": 0.13},
    "GLM-5.3": {"input": 1.40, "output": 4.40, "cache_read": 0.26},
    "GLM-5.3-Flash": {"input": 0.15, "output": 0.50, "cache_read": 0.03},
    "Claude Opus 5.5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "Claude Sonnet 5.5": {"input": 2.0, "output": 10.0, "cache_read": 0.10},
    "Claude Haiku 5.5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "GPT-6 Luna": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "GPT-6.1 Terra": {"input": 1.0, "output": 5.0, "cache_read": 0.05},
    "GLM-5.2": {"input": 1.40, "output": 4.40, "cache_read": 0.26},
}

PROVIDER_TYPES = ("anthropic", "openai_compat", "openai_images", "chat_images", "retrodiffusion", "plugin", "scripted",
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
    mcp: list[str] = field(default_factory=list)  # MCP servers (mcp_servers:) whose tools this role gets


FEATURE_SECTIONS = ("breaker", "gate", "notify", "automation", "tools", "compaction", "memory", "workers",
                    "parallel", "rewind", "attachments")


def section(cfg: Any, name: str) -> dict[str, Any]:
    """A feature's own settings from harness.yaml (``breaker:``, ``gate:``…), {} when absent."""
    return dict((getattr(cfg, "sections", None) or {}).get(name) or {})


@dataclass
class Limits:
    max_cost_usd: float = 10.0
    max_steps_per_task: int = 40
    max_attempts_per_task: int = 3
    max_real_usd_per_run: float = 0.0  # pause a run once providers' real balances fell this much (0 = off)
    max_usd_per_day: float = 0.0  # pause a run once today's spend on every project reached this (0 = off)
    split_stuck_tasks: bool = True  # a task that keeps running out of steps is split by the planner, once
    command_timeout: int = 120
    max_parallel: int = 1
    max_scout_steps: int = 30  # steps for reading one reference (scout.py)


@dataclass
class GodotSettings:
    """``godot:`` in harness.yaml: how Roundtable starts a Godot 4 game to check it (harness/godot.py)."""

    path: str | None = None  # the Godot program; empty: $GODOT, then godot / godot4 on PATH
    frames: int = 90  # frames recorded for the pictures (30 a second)
    timeout: int = 120  # seconds each Godot run may take
    enabled: bool = True  # false: never start Godot


def _godot_settings(raw: Any, base: Path) -> GodotSettings:
    if raw is None:
        return GodotSettings()
    if isinstance(raw, bool):
        return GodotSettings(enabled=raw)
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict):
        raise ValueError("godot must be a setting like {path: ..., frames: 90, timeout: 120, enabled: true}")
    path = str(raw.get("path") or "").strip() or None
    if path and ("/" in path or "\\" in path):
        p = Path(path).expanduser()
        path = str(p if p.is_absolute() else (base / p))
    frames, timeout = int(raw.get("frames", 90) or 90), int(raw.get("timeout", 120) or 120)
    if frames < 1 or timeout < 1:
        raise ValueError("godot: frames and timeout must be at least 1")
    return GodotSettings(path=path, frames=frames, timeout=timeout, enabled=bool(raw.get("enabled", True)))


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
    critic_role: str | None = None  # a second model that critiques each new plan (ideally another maker's)
    design_role: str | None = None  # makes the app's looks (default: a chat role "designer", else the planner)
    scout_role: str | None = None  # reads the owner's references (default: a chat role "scout", else the planner)
    look_stage: str = "auto"  # auto: offer looks when the plan is for an app with screens; off: only on request
    show_it: str = "auto"  # auto: pictures of the app's own screens after every approved task; off: never
    prompts_dir: Path | None = None
    hub: dict[str, Any] | None = None
    lab_dir: Path | None = None  # self-improvement lab (proposals, learned settings, versions)
    improve: dict[str, Any] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)  # commands through the hub: {enabled, owners}
    # named sets of models per role ("budget", "balanced", "quality"); a project picks one
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_profile: str | None = None
    learned: dict[str, Any] = field(default_factory=dict)  # the lab's learned overlay, as applied
    # prompt name -> text; learned prompts from the lab win over prompts_dir and built-ins
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    token_saver: SaverConfig = field(default_factory=SaverConfig)  # slims big tool results (saver.py)
    # plugins: {id: {enabled, settings, path, permissions, ...}} from harness.yaml and custom.yaml
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    # sections that a feature module reads for itself (breaker, gate, notify, automation, tools, …):
    # one key per feature, so features added side by side never edit this file
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    # MCP servers: {name: {command, args, env, cwd} or {url, headers}, plus tools, timeout, enabled}
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    godot: GodotSettings = field(default_factory=GodotSettings)  # checking Godot games (harness/godot.py)
    _instances: dict[str, Any] = field(default_factory=dict, repr=False)
    _shared: dict[str, Any] = field(default_factory=dict, repr=False)  # shared by variants (the plugin host)

    def plugin_host(self):
        """The plugins for this config (built once, shared with its profile variants)."""
        if "plugin_host" not in self._shared:
            from ..plugins.host import PluginHost

            self._shared["plugin_host"] = PluginHost.from_config(self)
        return self._shared["plugin_host"]

    def _listed_price(self, ref: ModelRef) -> dict[str, float] | None:
        """A price the provider publishes itself (OpenRouter's model list), when none is configured."""
        spec = self.providers.get(ref.provider) or {}
        if "openrouter.ai" not in str(spec.get("base_url") or ""):
            return None
        from ..providers.prices import openrouter_price

        return openrouter_price(ref.model)

    def for_profile(self, name: str | None) -> "HarnessConfig":
        """This config with a profile's models laid over the roles (unknown or empty name: unchanged)."""
        if not name or name not in self.profiles:
            return self
        c = self.variant()
        apply_overlay(c, self.profiles[name])
        # What was learned still counts inside a profile when it only reorders that profile's own
        # models (e.g. "start on the fallback, it finishes more for less").
        for role, spec in (self.learned.get("roles") or {}).items():
            if role in c.roles and "model" in spec:
                order = [spec["model"]] + list(spec.get("fallback") or [])
                if sorted(order) == sorted(str(m) for m in c.roles[role].models):
                    c.roles[role].models = [ModelRef.parse(m) for m in order]
        return c

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
                                        routing=spec.get("routing"),
                                        **{k: spec[k] for k in CLIENT_OPTS if spec.get(k)})
        elif kind == "chat_images":  # image models answering through a chat endpoint (OpenRouter's)
            from ..providers.chat_images import ChatImagesProvider

            inst = ChatImagesProvider(name, api_key_env=spec.get("api_key_env", "OPENROUTER_API_KEY"),
                                      base_url=spec.get("base_url") or "https://openrouter.ai/api/v1",
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
        from ..plugins.loader import load_object

        target = spec.get("class", "")
        if ":" not in target:
            raise ProviderError(f"provider {name!r}: plugin needs class: 'module_or_file.py:ClassName'")
        clsname = target.rsplit(":", 1)[1]
        plugins_dir = (self.path.parent / "plugins") if self.path else Path.cwd() / "plugins"
        try:
            cls = load_object(target, file_dirs=[plugins_dir], module_alias=f"roundtable_plugin_{name}")
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
        price = (self.pricing.get(str(ref)) or self.pricing.get(ref.model) or DEFAULT_PRICING.get(ref.model)
                 or self._listed_price(ref))
        if not price:
            return None
        price = price_now(price)
        return (
            usage.input_tokens * price.get("input", 0)
            + usage.output_tokens * price.get("output", 0)
            # text the model has seen already: most makers (Anthropic, DeepSeek, OpenAI) bill it at
            # about a tenth of the input price; set cache_read in the pricing when it differs
            + usage.cache_read_tokens * price.get("cache_read", price.get("input", 0) * 0.1)
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
    if custom.get("limits"):
        out["limits"] = {**(raw.get("limits") or {}), **custom["limits"]}
    if custom.get("plugins"):
        out["plugins"] = merge_plugin_state(raw.get("plugins") or {}, custom["plugins"])
    if custom.get("default_profile") and custom["default_profile"] in (raw.get("profiles") or {}):
        out["default_profile"] = custom["default_profile"]  # the profile chosen in the app (shared settings)
    from ..prereq import merge_custom_tools  # tool servers added in the app, and which jobs use them

    out = merge_custom_tools(out, custom)
    return out


def merge_plugin_state(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """plugins: from harness.yaml with custom.yaml's choices on top (settings merged key by key)."""
    out = {k: dict(v or {}) for k, v in base.items()}
    for pid, spec in over.items():
        entry = out.setdefault(pid, {})
        settings = {**(entry.get("settings") or {}), **((spec or {}).get("settings") or {})}
        entry.update(spec or {})
        if settings:
            entry["settings"] = settings
    return out


def _plugin_state(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state = raw.get("plugins") or {}
    if not isinstance(state, dict) or not all(isinstance(v, (dict, type(None))) for v in state.values()):
        raise ValueError("plugins must be a mapping of plugin id to its settings, e.g. cost-log: {enabled: true}")
    return {str(k): dict(v or {}) for k, v in state.items()}


def _token_saver(raw: dict[str, Any], plugins: dict[str, dict[str, Any]]) -> SaverConfig:
    """token_saver: in harness.yaml, then the token-saver plugin's own choices (custom.yaml) on top."""
    base = raw.get("token_saver")
    mine = plugins.get("token-saver") or {}
    if not mine:
        return SaverConfig.parse(base)
    merged = {"enabled": base} if isinstance(base, bool) else dict(base or {}) if isinstance(base, dict) else base
    if not isinstance(merged, dict):
        return SaverConfig.parse(base)  # raises the usual message
    merged.update(mine.get("settings") or {})
    if "enabled" in mine:
        merged["enabled"] = bool(mine["enabled"])
    return SaverConfig.parse(merged)


def find_config(explicit: str | None = None) -> Path:
    for c in (explicit, os.environ.get("HARNESS_CONFIG"), "harness.yaml", "~/.roundtable/harness.yaml", "~/.agent-harness/harness.yaml"):
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    raise FileNotFoundError("No harness config found. Pass --config, set HARNESS_CONFIG, or run `roundtable init`.")


def _str_list(value: Any, what: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, (str, int, float)) for v in value):
        raise ValueError(f"{what} must be a list, e.g. [\"one\", \"two\"]")
    return [str(v) for v in value]


def _str_map(value: Any, what: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a mapping of names to values, e.g. {{NAME: value}}")
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


def _mcp_servers(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """mcp_servers: {name: {command, args, env, cwd} | {url, headers}, tools, timeout, enabled}, checked."""
    servers = raw.get("mcp_servers") or {}
    if not isinstance(servers, dict):
        raise ValueError("mcp_servers must be a mapping of a short name to the server, e.g. "
                         "unreal: {url: \"http://127.0.0.1:8000/mcp\"}")
    out: dict[str, dict[str, Any]] = {}
    for name, spec in servers.items():
        name = str(name)
        where = f"mcp_servers: {name!r}"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise ValueError(f"{where}: a server's name may only have letters, digits, - and _ (at most 40)")
        if not isinstance(spec, dict):
            raise ValueError(f"{where} needs either command: (a program to run) or url: (an address)")
        unknown = set(spec) - {"command", "args", "env", "cwd", "url", "headers", "tools", "timeout", "enabled",
                               "description"}
        if unknown:
            raise ValueError(f"{where}: unknown setting(s) {', '.join(sorted(map(str, unknown)))}; "
                             "use command, args, env, cwd, url, headers, tools, timeout or enabled")
        if ("command" in spec) == ("url" in spec):
            raise ValueError(f"{where} needs exactly one of command: (a program to run) or url: (an address)")
        entry: dict[str, Any] = {"enabled": True, "timeout": 120.0}
        if "command" in spec:
            if not isinstance(spec["command"], str) or not spec["command"].strip():
                raise ValueError(f"{where}: command must be the program to run, e.g. command: uvx")
            entry["command"] = spec["command"]
            entry["args"] = _str_list(spec.get("args") or [], f"{where}: args")
            entry["env"] = _str_map(spec.get("env") or {}, f"{where}: env")
            if spec.get("cwd") is not None:
                entry["cwd"] = str(Path(str(spec["cwd"])).expanduser())
            if "headers" in spec:
                raise ValueError(f"{where}: headers are only for a server with url:")
        else:
            url = spec["url"]
            if not isinstance(url, str) or not re.match(r"https?://", url):
                raise ValueError(f"{where}: url must start with http:// or https://, e.g. http://127.0.0.1:8000/mcp")
            entry["url"] = url
            entry["headers"] = _str_map(spec.get("headers") or {}, f"{where}: headers")
            for key in ("args", "env", "cwd"):
                if key in spec:
                    raise ValueError(f"{where}: {key} is only for a server with command:")
        if spec.get("tools") is not None:
            entry["tools"] = _str_list(spec["tools"], f"{where}: tools")
        try:
            entry["timeout"] = float(spec.get("timeout", 120))
        except (TypeError, ValueError):
            raise ValueError(f"{where}: timeout must be a number of seconds, e.g. timeout: 300") from None
        if entry["timeout"] <= 0:
            raise ValueError(f"{where}: timeout must be more than 0 seconds")
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{where}: enabled must be true or false")
        entry["enabled"] = enabled
        if spec.get("description"):
            entry["description"] = str(spec["description"])
        out[name] = entry
    return out


def parse_config(raw: dict[str, Any], path: Path | None = None) -> HarnessConfig:
    providers = raw.get("providers") or {}
    for name, spec in providers.items():
        if (spec or {}).get("type") not in PROVIDER_TYPES:
            raise ValueError(f"provider {name!r}: type must be one of {PROVIDER_TYPES}")
    mcp_servers = _mcp_servers(raw)

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
        mcp = _str_list(spec.get("mcp") or [], f"role {name!r}: mcp")
        for server in mcp:
            if server not in mcp_servers:
                raise ValueError(f"role {name!r}: mcp lists {server!r}, but there is no such server under "
                                 f"mcp_servers (have: {', '.join(mcp_servers) or 'none'})")
        if mcp and kind != "chat":
            raise ValueError(f"role {name!r}: only chat roles can use MCP servers")
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
            mcp=mcp,
        )

    planner = raw.get("planner_role", "orchestrator")
    reviewer = raw.get("reviewer_role", "reviewer")
    if planner not in roles:
        raise ValueError(f"planner_role {planner!r} is not defined under roles")
    if reviewer and reviewer not in roles:
        reviewer = None
    critic = raw.get("critic_role", "critic" if "critic" in roles else None)
    if critic and critic not in roles:
        critic = None
    design = raw.get("design_role")
    if not (design in roles and roles[design].kind == "chat"):
        design = "designer" if "designer" in roles and roles["designer"].kind == "chat" else planner
    scout = raw.get("scout_role")
    if not (scout in roles and roles[scout].kind == "chat"):
        scout = "scout" if "scout" in roles and roles["scout"].kind == "chat" else planner
    look_stage = raw.get("look_stage", "auto")
    look_stage = {False: "off", True: "auto"}.get(look_stage, str(look_stage).lower())  # YAML reads off as false
    if look_stage not in ("auto", "off"):
        raise ValueError("look_stage must be 'auto' or 'off'")
    show_it = raw.get("show_it", "auto")
    show_it = {False: "off", True: "auto"}.get(show_it, str(show_it).lower())  # YAML reads off as false
    if show_it not in ("auto", "off"):
        raise ValueError("show_it must be 'auto' or 'off'")

    profiles = _profiles(raw, providers, roles)
    default_profile = raw.get("default_profile")
    if default_profile and default_profile not in profiles:
        raise ValueError(f"default_profile {default_profile!r} isn't one of the profiles: {', '.join(profiles) or 'none'}")

    plugins = _plugin_state(raw)
    lim = raw.get("limits") or {}
    base = path.parent if path else Path.cwd()
    prompts_dir = raw.get("prompts_dir")
    ws = raw.get("workspace") or {}
    from ..core import secrets as vault

    # every provider's key name is a secret: workers' commands never get it (safeenv.py)
    vault.remember_name(*[(p or {}).get("api_key_env") for p in providers.values() if isinstance(p, dict)])
    return HarnessConfig(
        path=path,
        providers=providers,
        roles=roles,
        pricing=raw.get("pricing") or {},
        limits=Limits(
            max_cost_usd=float(lim.get("max_cost_usd", 10.0)),
            max_steps_per_task=int(lim.get("max_steps_per_task", 40)),
            max_attempts_per_task=int(lim.get("max_attempts_per_task", 3)),
            split_stuck_tasks=bool(lim.get("split_stuck_tasks", True)),
            max_real_usd_per_run=float(lim.get("max_real_usd_per_run", 0) or 0),
            max_usd_per_day=float(lim.get("max_usd_per_day", 0) or 0),
            command_timeout=int(lim.get("command_timeout", 120)),
            max_scout_steps=int(lim.get("max_scout_steps", 30)),
            max_parallel=max(1, int(lim.get("max_parallel", 1) or 1)),
        ),
        allow_shell=bool(ws.get("allow_shell", True)),
        git=bool(ws.get("git", True)),
        planner_role=planner,
        reviewer_role=reviewer,
        critic_role=critic,
        design_role=design,
        scout_role=scout,
        look_stage=look_stage,
        show_it=show_it,
        prompts_dir=(base / prompts_dir) if prompts_dir else None,
        hub=raw.get("hub"),
        lab_dir=_lab_dir(raw, base, path),
        improve=dict(raw.get("improve") or {}),
        remote=dict(raw.get("remote") or {}),
        profiles=profiles,
        default_profile=default_profile,
        token_saver=_token_saver(raw, plugins),
        plugins=plugins,
        mcp_servers=mcp_servers,
        godot=_godot_settings(raw.get("godot"), base),
        sections={k: dict(v) for k, v in raw.items() if k in FEATURE_SECTIONS and isinstance(v, dict)},
    )


def _profiles(raw: dict[str, Any], providers: dict[str, Any], roles: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """profiles: {name: {description, roles: {role: {model, fallback}}}}, checked against roles and providers."""
    out = {}
    for name, spec in (raw.get("profiles") or {}).items():
        spec = spec or {}
        for role, r in (spec.get("roles") or {}).items():
            if role not in roles:
                raise ValueError(f"profile {name!r}: no role {role!r} in roles")
            for m in [r.get("model")] + list(r.get("fallback") or []):
                if not m:
                    raise ValueError(f"profile {name!r}: role {role!r} needs a model")
                ref = ModelRef.parse(m)
                if providers and ref.provider not in providers:
                    raise ValueError(f"profile {name!r}: unknown provider {ref.provider!r} in {m!r}")
        out[str(name)] = {"description": str(spec.get("description", "")), "roles": dict(spec.get("roles") or {})}
    return out


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
