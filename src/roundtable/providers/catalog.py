"""Built-in catalog of AI providers you can add with one click.

Each preset is just a provider block for harness.yaml/custom.yaml. Nearly every
vendor now offers an OpenAI-compatible endpoint, so most presets use the
`openai_compat` adapter; models are discovered live from the provider's own
/models endpoint, so this list never needs model names.

Anything not listed: use the "custom" preset (any OpenAI-compatible URL, with
custom auth header / extra headers / query parameters), or a `plugin` provider
(your own Python class) for APIs that aren't OpenAI-compatible at all.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    # -- frontier labs ---------------------------------------------------------------------
    "anthropic": {"name": "Anthropic (Claude)", "type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY",
                  "category": "chat", "docs": "https://console.anthropic.com/settings/keys"},
    "openai": {"name": "OpenAI", "type": "openai_compat", "base_url": "https://api.openai.com/v1",
               "api_key_env": "OPENAI_API_KEY", "category": "chat", "docs": "https://platform.openai.com/api-keys"},
    "gemini": {"name": "Google Gemini", "type": "openai_compat",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "api_key_env": "GEMINI_API_KEY", "category": "chat", "docs": "https://aistudio.google.com/apikey"},
    "xai": {"name": "xAI (Grok)", "type": "openai_compat", "base_url": "https://api.x.ai/v1",
            "api_key_env": "XAI_API_KEY", "category": "chat", "docs": "https://console.x.ai"},
    "mistral": {"name": "Mistral", "type": "openai_compat", "base_url": "https://api.mistral.ai/v1",
                "api_key_env": "MISTRAL_API_KEY", "category": "chat", "docs": "https://console.mistral.ai"},
    "deepseek": {"name": "DeepSeek", "type": "openai_compat", "base_url": "https://api.deepseek.com",
                 "api_key_env": "DEEPSEEK_API_KEY", "category": "chat", "docs": "https://platform.deepseek.com"},
    "cohere": {"name": "Cohere", "type": "openai_compat", "base_url": "https://api.cohere.ai/compatibility/v1",
               "api_key_env": "COHERE_API_KEY", "category": "chat", "docs": "https://dashboard.cohere.com/api-keys"},
    "moonshot": {"name": "Moonshot (Kimi)", "type": "openai_compat", "base_url": "https://api.moonshot.ai/v1",
                 "api_key_env": "MOONSHOT_API_KEY", "category": "chat", "docs": "https://platform.moonshot.ai"},
    "qwen": {"name": "Alibaba Qwen (DashScope, international)", "type": "openai_compat",
             "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             "api_key_env": "DASHSCOPE_API_KEY", "category": "chat", "docs": "https://dashscope.console.aliyun.com"},
    "perplexity": {"name": "Perplexity", "type": "openai_compat", "base_url": "https://api.perplexity.ai",
                   "api_key_env": "PERPLEXITY_API_KEY", "category": "chat", "docs": "https://www.perplexity.ai/settings/api"},
    "openference": {"name": "Openference (55 models from 15 makers, one key: Claude, GPT, Gemini, GLM, Kimi, Qwen, DeepSeek)",
                    "type": "openai_compat", "base_url": "https://api.openference.com/v1",
                    "api_key_env": "OPENFERENCE_API_KEY", "category": "chat", "docs": "https://docs.openference.com"},
    # -- hosts for open models ---------------------------------------------------------------
    "openrouter": {"name": "OpenRouter (hundreds of models, one key)", "type": "openai_compat",
                   "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                   "category": "chat", "docs": "https://openrouter.ai/keys"},
    "groq": {"name": "Groq", "type": "openai_compat", "base_url": "https://api.groq.com/openai/v1",
             "api_key_env": "GROQ_API_KEY", "category": "chat", "docs": "https://console.groq.com/keys"},
    "together": {"name": "Together AI", "type": "openai_compat", "base_url": "https://api.together.xyz/v1",
                 "api_key_env": "TOGETHER_API_KEY", "category": "chat", "docs": "https://api.together.ai"},
    "fireworks": {"name": "Fireworks AI", "type": "openai_compat", "base_url": "https://api.fireworks.ai/inference/v1",
                  "api_key_env": "FIREWORKS_API_KEY", "category": "chat", "docs": "https://fireworks.ai/account/api-keys"},
    "cerebras": {"name": "Cerebras", "type": "openai_compat", "base_url": "https://api.cerebras.ai/v1",
                 "api_key_env": "CEREBRAS_API_KEY", "category": "chat", "docs": "https://cloud.cerebras.ai"},
    # -- on your own computer (no key needed) ---------------------------------------------------
    "ollama": {"name": "Ollama (local)", "type": "openai_compat", "base_url": "http://localhost:11434/v1",
               "api_key_env": "", "category": "chat", "local": True, "docs": "https://ollama.com"},
    "lmstudio": {"name": "LM Studio (local)", "type": "openai_compat", "base_url": "http://localhost:1234/v1",
                 "api_key_env": "", "category": "chat", "local": True, "docs": "https://lmstudio.ai"},
    # -- images ----------------------------------------------------------------------------------
    "openai_images": {"name": "OpenAI images", "type": "openai_images", "base_url": "https://api.openai.com/v1",
                      "api_key_env": "OPENAI_API_KEY", "category": "image", "docs": "https://platform.openai.com/api-keys"},
    "retrodiffusion": {"name": "Retro Diffusion (pixel art)", "type": "retrodiffusion",
                       "api_key_env": "RETRODIFFUSION_API_KEY", "category": "image",
                       "docs": "https://www.retrodiffusion.ai/app/devtools"},
    # -- anything else ---------------------------------------------------------------------------
    "custom": {"name": "Custom OpenAI-compatible API (any URL: Azure, vLLM, your own server...)",
               "type": "openai_compat", "base_url": "", "api_key_env": "", "category": "chat", "custom": True,
               "docs": "https://github.com/MEZTKING/agent-harness#adding-any-provider"},
}

PROVIDER_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def valid_provider_id(pid: str) -> bool:
    return bool(pid) and pid[0].isalpha() and set(pid) <= PROVIDER_ID_CHARS and len(pid) <= 40


def preset_block(preset: str, **overrides) -> dict:
    """The provider block to store for a preset (catalog-only keys removed)."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose one of: {', '.join(sorted(PRESETS))}")
    spec = {k: v for k, v in PRESETS[preset].items() if k in ("type", "base_url", "api_key_env")}
    spec.update({k: v for k, v in overrides.items() if v not in (None, "")})
    if not spec.get("base_url"):
        spec.pop("base_url", None)
        if spec["type"] == "openai_compat":
            raise ValueError("this provider needs a base URL (the address of its OpenAI-compatible API)")
    if not spec.get("api_key_env"):
        spec.pop("api_key_env", None)
    spec["preset"] = preset
    return spec
