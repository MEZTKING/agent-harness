"""One list of every service the harness uses (wave 8, MD-83): model makers, picture makers, GitHub, web search,
MCP tool servers and plug-ins that use a saved key (``secrets:<host>``).

Each row says **Ready**, **Needs a key** or **Not answering** (after a Test that failed), who uses it, and where
to fix it. Nothing new is stored: the rows are read from what is already there (harness.yaml and custom.yaml,
the key store through ``core/secrets``, the Tools page's servers, the plug-ins' manifests). Keys go through the
existing key form; **no key, and no key's value, is ever in this list's answer** (only whether one is saved and
the slot's label).

``test(cfg, row_id)`` asks the service something that costs nothing: a maker's model list, GitHub's "who am I",
an MCP server's tool list. Its answer is kept in memory for the session (``_TESTS``), so a failure shows as Not
answering until the next Test.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .core import secrets as vault

GROUPS = ("Models", "Pictures", "GitHub", "Web search", "Tool servers", "Plug-ins")
PICTURE_TYPES = ("chat_images", "openai_images", "retrodiffusion")
DEFAULT_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "chat_images": "OPENROUTER_API_KEY",
                "retrodiffusion": "RETRODIFFUSION_API_KEY"}
_TESTS: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _label(slot: str, providers: dict | None = None) -> str:
    from .desktop import key_label

    return key_label(slot, providers)


def _jobs_using(cfg, provider: str) -> list[str]:
    from .routing import job_name

    out = []
    for r in (getattr(cfg, "roles", None) or {}).values():
        if any(m.provider == provider for m in r.models):
            out.append(job_name(r.name))
    return out


def _row(rid: str, group: str, name: str, state: str, words: str, who: list[str], slot: str = "",
         providers: dict | None = None, where: str = "", can_test: bool = True) -> dict[str, Any]:
    test = _TESTS.get(rid)
    if state == "ready" and test and not test.get("ok"):
        state, words = "not_answering", test.get("words") or "It didn't answer the last test."
    elif state == "ready" and test and test.get("ok"):
        words = test.get("words") or words
    row = {"id": rid, "group": group, "name": name, "state": state, "words": words, "who": who,
           "where": where, "can_test": can_test, "tested_at": (test or {}).get("at")}
    if slot:  # which key slot of the existing key form: its name and label, and whether it is filled
        row["needs"] = {"slot": slot, "label": _label(slot, providers), "saved": vault.has(slot)}
    return row


_STATE_WORDS = {"ready": "Ready", "missing": "Needs a key", "not_answering": "Not answering", "off": "Switched off"}


def listing(cfg, harness_path: str | Path | None = None, servers: dict[str, Any] | None = None,
            plugins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """{rows: [{id, group, name, state, state_words, words, who, where, can_test, tested_at, needs?}], groups,
    counts}. ``servers`` and ``plugins`` default to the Tools page's and the plug-ins' own lists."""
    from .automation import TOKEN_FALLBACKS, TOKEN_KEY

    rows: list[dict[str, Any]] = []
    providers = dict(getattr(cfg, "providers", None) or {}) if cfg else {}
    for name, spec in sorted(providers.items()):
        spec = spec or {}
        kind = str(spec.get("type") or "")
        group = "Pictures" if kind in PICTURE_TYPES else "Models"
        who = _jobs_using(cfg, name)
        if kind == "cli":
            rows.append(_row(f"provider:{name}", group, f"{name} (coding helpers on this computer)", "ready",
                             "Uses your own Claude Code or Codex sign-in; no key here.", who, where="Tools"))
            continue
        if kind == "scripted":
            continue
        slot = spec.get("api_key_env") or DEFAULT_KEYS.get(kind, "")
        if slot and not vault.has(slot):
            rows.append(_row(f"provider:{name}", group, name, "missing",
                             f"Add the {_label(slot, providers)} key in Settings → Keys.", who, slot, providers,
                             where="Settings → Keys"))
        else:
            rows.append(_row(f"provider:{name}", group, name, "ready", "A key is saved.", who, slot, providers,
                             where="Settings → Keys"))
    gh = next((n for n in (TOKEN_KEY, *TOKEN_FALLBACKS) if vault.has(n)), "")
    rows.append(_row("github", "GitHub", "GitHub", "ready" if gh else "missing",
                     "A GitHub key is saved." if gh else "Add your GitHub key on the Automations page.",
                     ["Automations", "Checks on your projects"], TOKEN_KEY, providers, where="Automations"))
    try:
        from .harness import websearch as ws

        s = ws.settings(cfg)
        on = bool(s.get("enabled", True))
        engine = str(s.get("engine") or "auto")
        slot = ws.KEYS.get(engine, "")
        if not on:
            state, words = "off", "Web search for builders is switched off."
        elif slot and not vault.has(slot):
            state, words = "missing", f"Add the {ws.KEY_NAMES.get(slot, slot)} key in Settings → Keys."
        else:
            have = [ws.KEY_NAMES[k] for k in ws.KEY_NAMES if vault.has(k)]
            state, words = "ready", ("Uses " + " and ".join(have) + "." if have else
                                     "Works without a key (a free search engine).")
        rows.append(_row("websearch", "Web search", "Web search", state, words, ["Builders"], slot, providers,
                         where="Settings → Web search", can_test=False))
    except Exception:  # noqa: BLE001 - one part that can't be read never hides the rest
        pass
    if servers is None:
        try:
            from . import prereq

            servers = prereq.servers_view(harness_path)
        except Exception:  # noqa: BLE001 - not set up yet
            servers = {"servers": []}
    for sv in (servers or {}).get("servers") or []:
        on = sv.get("enabled", True) is not False
        rows.append(_row(f"mcp:{sv['name']}", "Tool servers", sv["name"], "ready" if on else "off",
                         "Added. Press Test to start it and see its tools." if on else "Switched off.",
                         list(sv.get("jobs") or []), where="Tools"))
    if plugins is None:
        try:
            from .plugins.manage import list_plugins

            plugins = list_plugins(harness_path)
        except Exception:  # noqa: BLE001
            plugins = []
    for p in plugins or []:
        hosts = [str(x.get("id") if isinstance(x, dict) else x) for x in p.get("permissions") or []]
        hosts = [h.split(":", 1)[1] for h in hosts if h.startswith("secrets:")]
        for host in hosts:
            has = _host_key(cfg, host)
            rows.append(_row(f"plugin:{p.get('id')}:{host}", "Plug-ins", f"{p.get('name') or p.get('id')} → {host}",
                             ("ready" if has else "missing") if p.get("enabled", True) else "off",
                             f"Uses your saved key for {host}." if has else
                             f"Needs a saved key for {host}: add the key of the maker that uses {host}.",
                             [str(p.get("name") or p.get("id"))], where="Plug-ins", can_test=False))
    for r in rows:
        r["state_words"] = _STATE_WORDS.get(r["state"], r["state"])
    counts = {k: sum(1 for r in rows if r["state"] == k) for k in _STATE_WORDS}
    return {"rows": rows, "groups": [g for g in GROUPS if any(r["group"] == g for r in rows)], "counts": counts,
            "words": _summary(counts)}


def _summary(c: dict[str, int]) -> str:
    bits = [f"{c['ready']} ready"]
    if c["missing"]:
        bits.append(f"{c['missing']} need{'s' if c['missing'] == 1 else ''} a key")
    if c["not_answering"]:
        bits.append(f"{c['not_answering']} not answering")
    return ", ".join(bits) + "."


def _host_key(cfg, host: str) -> bool:
    try:
        from .plugins.sandbox import key_for_host

        return key_for_host(cfg, host.lower()) is not None
    except Exception:  # noqa: BLE001
        return False


Tester = Callable[[Any, str], tuple[bool, str]]


def _test_provider(cfg, name: str) -> tuple[bool, str]:
    spec = (cfg.providers or {}).get(name) or {}
    if spec.get("type") == "cli":
        from .prereq import find
        from .providers.cli_engine import ENGINES

        found = [e.name for e in ENGINES.values() if find(e.tool, versions=False).get("state") in ("found", "old")]
        return (bool(found), ("Found: " + ", ".join(found) + ".") if found else
                "Neither Claude Code nor Codex is on this computer. Install one from the Tools page.")
    models = cfg.provider(name).list_models()  # a list of models: no tokens, no charge
    return True, f"It answers: {len(models)} model{'s' if len(models) != 1 else ''} offered."


def _test_github(cfg, _: str) -> tuple[bool, str]:
    from . import automation as au

    token = au.github_token()
    if not token:
        return False, "Add your GitHub key on the Automations page."
    status, _, body = au.http_get(f"{au.API}/user", au.GitHub(token)._headers())
    if status == 401:
        return False, "GitHub didn't accept your GitHub key. Add a new one on the Automations page."
    if status >= 300:
        return False, f"GitHub answered with an error ({status}). Try again in a few minutes."
    return True, "GitHub accepts your key."


def test(cfg, rid: str, harness_path: str | Path | None = None, testers: dict[str, Tester] | None = None
         ) -> dict[str, Any]:
    """Ask one service something free and remember the answer: {id, ok, words, at}."""
    kind, _, name = rid.partition(":")
    testers = testers or {}
    try:
        if kind in testers:
            ok, words = testers[kind](cfg, name)
        elif kind == "provider":
            if name not in (getattr(cfg, "providers", None) or {}):
                raise ValueError("That service isn't in your settings any more. Refresh the page.")
            ok, words = _test_provider(cfg, name)
        elif kind == "github":
            ok, words = _test_github(cfg, name)
        elif kind == "mcp":
            from .prereq import test_server

            r = test_server(harness_path, name)
            ok, words = bool(r["ok"]), r["words"]
        else:
            raise ValueError("That one can't be tested from here.")
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 - not answering is an answer
        ok, words = False, _plain_error(e)
    for v in vault.values():  # never repeat a key, even in an error from a maker
        if len(v) >= 6:
            words = words.replace(v, "***")
    res = {"id": rid, "ok": bool(ok), "words": words[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with _lock:
        _TESTS[rid] = res
    return res


def _plain_error(e: Exception) -> str:
    text = str(e).strip() or type(e).__name__
    return f"It didn't answer: {text[:200]}"


def forget_tests() -> None:
    with _lock:
        _TESTS.clear()
