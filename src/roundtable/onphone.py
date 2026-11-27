"""Roundtable on the phone itself: `roundtable phone serve --local`.

Roundtable Mobile unpacks a small Debian (Python, git, Node) and runs Roundtable inside it with
proot, the way DSH Mobile runs its harness (runtime/README.md). The app starts:

    /opt/roundtable/venv/bin/roundtable phone serve --local --port PORT --home /root/.roundtable

with ROUNDTABLE_LAUNCH_TOKEN (new at every start) and ROUNDTABLE_HOME in the environment. This
module is that server:

* 127.0.0.1 only, plain HTTP (the phone app is the only client; nothing leaves the phone);
* every request carries `Authorization: Bearer <launch token>` (compared in constant time),
  except `GET /api/health`; the token is never logged or written down;
* the paired phone server's routes (phone.PHONE_ROUTES, the same handler), plus `/api/keys`
  (API keys into the key store, a private file: no keyring on a phone) and `/api/hub`
  (a hub repository, cloned with git, for keeping the phone in step with the PC);
* the first start writes a ready configuration: every role on DeepSeek V4 Flash, the token
  saver on, a real-money limit per run, a local hub (or the hub repository once connected).
"""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core import secrets as vault
from .desktop import KNOWN_KEYS, KeyStore, Paths

MODEL = "deepseek/deepseek-v4-flash"  # the owner's rule: Flash on the phone, never V4 Pro
ROLES = ("orchestrator", "manager", "coder", "critic", "scout", "reviewer", "designer")
MAX_REAL_USD_PER_RUN = 1.0
MAX_COST_USD = 5.0
HUB_TOKEN = "ROUNDTABLE_HUB_TOKEN"  # the hub repository's token, in the key store like an API key
READY = "Roundtable is ready on"  # the line the app waits for (manifest runtime.readinessPrefix)
MIN_TOKEN = 16

# provider (as the phone app names it) -> the environment variable Roundtable's providers read
PROVIDER_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY", "retrodiffusion": "RETRODIFFUSION_API_KEY",
    "openrouter": "OPENROUTER_API_KEY", "openference": "OPENFERENCE_API_KEY",
}


# -- the first start ----------------------------------------------------------------------------
def workspaces_dir(home: Path) -> Path:
    return Path(os.environ.get("ROUNDTABLE_WORKSPACES") or Path(home) / "projects").expanduser()


def seat_id(paths: Paths) -> str:
    """This phone's seat on the hub: $ROUNDTABLE_SEAT, else the one chosen at the first start."""
    if os.environ.get("ROUNDTABLE_SEAT"):
        return os.environ["ROUNDTABLE_SEAT"].strip()
    settings = paths.load_settings()
    if not settings.get("agent"):
        settings["agent"] = f"phone-{secrets.token_hex(3)}"
        paths.save_settings(settings)
    return settings["agent"]


def harness_config(hub_yaml: Path, seat: str) -> dict[str, Any]:
    roles: dict[str, Any] = {r: {"model": MODEL} for r in ROLES}
    # the owner's choice: Claude Opus 5.5 codes (with an Anthropic key), DeepSeek Flash backs it up
    roles["coder"] = {"model": "anthropic/claude-opus-5-5", "fallback": [MODEL], "options": {"effort": "medium"},
                      "description": "writes and tests code"}
    return {
        "providers": {"deepseek": {"type": "openai_compat", "base_url": "https://api.deepseek.com",
                                   "api_key_env": "DEEPSEEK_API_KEY"},
                      "anthropic": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}},
        "roles": roles,
        "planner_role": "orchestrator", "reviewer_role": "reviewer", "critic_role": "critic",
        "design_role": "designer", "scout_role": "scout",
        "look_stage": "off",  # pictures of screens need a browser the phone's Linux doesn't have
        "show_it": "off",
        "limits": {"max_cost_usd": MAX_COST_USD, "max_real_usd_per_run": MAX_REAL_USD_PER_RUN,
                   "max_steps_per_task": 40, "max_attempts_per_task": 3, "command_timeout": 300},
        "workspace": {"allow_shell": True, "git": True},
        "token_saver": True,
        "hub": {"config": str(hub_yaml), "agent": seat},
        "improve": {"auto_apply": "none"},
    }


def machine_env(paths: Paths, seat: str) -> None:
    """This phone as a machine of the hub (sync.py): its seat and its friendly name, "Phone (OPPO)"."""
    from .sync import MACHINE_ENV, MACHINE_NAME_ENV, phone_title

    os.environ[MACHINE_ENV] = seat
    os.environ[MACHINE_NAME_ENV] = phone_title(paths.load_settings().get("device_name"))


def write_local_hub(paths: Paths, seat: str) -> None:
    from .desktop import write_local_hub as write

    write(paths, agents={seat: {"description": "Roundtable on this phone"},
                         "me": {"description": "My own notes and plans that don't belong to one project"}})


def ensure_phone_setup(paths: Paths) -> dict[str, Any]:
    """Write what a first start needs (never overwrites the owner's own changes)."""
    import yaml

    paths.ensure()
    seat = seat_id(paths)
    if not paths.hub_yaml.exists():
        write_local_hub(paths, seat)
    if not paths.harness_yaml.exists():
        paths.harness_yaml.write_text(
            "# Roundtable on this phone: every role on DeepSeek V4 Flash. Change it in the app.\n"
            + yaml.safe_dump(harness_config(paths.hub_yaml, seat), sort_keys=False), encoding="utf-8")
    projects = workspaces_dir(paths.home)
    projects.mkdir(parents=True, exist_ok=True)
    settings = paths.load_settings()
    if settings.get("projects_dir") != str(projects):
        settings["projects_dir"] = str(projects)
        paths.save_settings(settings)
    return {"seat": seat, "projects": projects}


# -- the hub repository (keeps the phone in step with the PC) --------------------------------------
def git_auth_env(url: str, token: str) -> dict[str, str]:
    """git settings that send the token to the hub repository's host only, through the environment
    (never a command line, where `ps` shows it, nor a file)."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("the hub repository must be an https:// address, e.g. https://github.com/you/agent-hub-data")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.https://{u.hostname}/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}", "GIT_TERMINAL_PROMPT": "0"}


def use_hub_token(paths: Paths, keys: KeyStore) -> bool:
    """Give the hub's own git calls the hub token (``core/secrets.set_git_env``), so its sync can pull
    and push. Never os.environ: a worker's command must not inherit it."""
    token = keys.get(HUB_TOKEN)
    url = paths.load_settings().get("hub_url") or ""
    if not (token and url):
        return False
    vault.set_git_env(git_auth_env(url, token))
    return True


def connect_hub(paths: Paths, keys: KeyStore, url: str, token: str, seat: str, log=print) -> dict[str, Any]:
    """Clone the hub repository into the home and point hub.yaml at it (the local hub is kept)."""
    import yaml

    url = (url or "").strip()
    env = git_auth_env(url, token) if token else {"GIT_TERMINAL_PROMPT": "0"}
    if not token and urlparse(url).scheme != "https":
        raise ValueError("the hub repository must be an https:// address")
    target = paths.home / "hub-repo"
    run_env = {**os.environ, **env}
    if (target / ".git").exists():
        res = subprocess.run(["git", "-C", str(target), "pull", "--ff-only"], capture_output=True, text=True,
                             timeout=300, env=run_env)
    else:
        log("cloning the hub repository...")
        res = subprocess.run(["git", "clone", "--", url, str(target)], capture_output=True, text=True,
                             timeout=900, env=run_env)
    if res.returncode != 0:
        err = res.stderr.replace(token, "***") if token else res.stderr
        raise RuntimeError("couldn't get the hub repository: " + err.strip()[-300:]
                           + " Check the address and that the token can read and write it.")
    repo_yaml = target / "hub.yaml"
    cfg = (yaml.safe_load(repo_yaml.read_text(encoding="utf-8")) or {}) if repo_yaml.exists() else {
        "default_policy": "deny", "agents": {"me": {"description": "My own notes and plans"}},
        "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]}
    cfg["storage"] = {"type": "git", "path": str(target), "branch": (cfg.get("storage") or {}).get("branch", "main")}
    cfg.setdefault("agents", {}).setdefault(seat, {"description": "Roundtable on this phone"})
    paths.hub_yaml.write_text("# Roundtable on this phone: the hub repository, kept in step with git\n"
                              + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    if token:
        keys.set(HUB_TOKEN, token)
        vault.set_git_env(env)
    settings = paths.load_settings()
    settings["hub_url"] = url
    paths.save_settings(settings)
    return {"mode": "git", "url": url}


# -- the server ---------------------------------------------------------------------------------
class LocalAccess:
    """Stands in for phone.PhoneAccess: one client (the app that started us), one launch token."""

    local = True
    unauthorized = "missing or wrong launch token: close Roundtable in the app and start it again"

    def __init__(self, app, paths: Paths, keys: KeyStore, token: str):
        self.app, self.paths, self.keys = app, paths, keys
        self._token = token
        self.name = "this phone"

    def device_for(self, token: str) -> dict[str, Any] | None:
        if token and secrets.compare_digest(token.encode(), self._token.encode()):
            return {"id": "local", "name": "this phone"}
        return None

    def health(self) -> dict[str, Any]:
        from . import __version__

        return {"ok": True, "version": __version__}

    # -- keys ---------------------------------------------------------------------------------
    def _key_names(self) -> dict[str, str]:
        names = dict(PROVIDER_KEYS)
        cfg = self.app.cfg()
        for pid, p in (cfg.providers.items() if cfg else []):
            if p.get("api_key_env"):
                names.setdefault(pid, p["api_key_env"])
        return names

    def keys_list(self) -> dict[str, Any]:
        out = [{"provider": pid, "name": env, "label": KNOWN_KEYS.get(env, pid),
                "set": bool(vault.get(env) or self.keys.get(env))} for pid, env in self._key_names().items()]
        return {"keys": out}

    def keys_save(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = str(body.get("provider") or "").strip()
        env = self._key_names().get(provider.lower())
        if not env:
            raise ValueError(f"unknown provider {provider!r}: use one of {', '.join(self._key_names())}")
        key = body.get("key")
        if key is not None and not isinstance(key, str):
            raise ValueError("key must be text (an empty one removes it)")
        self.keys.set(env, (key or "").strip())
        return self.keys_list()

    def hub_status(self) -> dict[str, Any]:
        from .sync import this_machine

        st = self.app.hub.config.storage if self.app.hub else {}
        return {"mode": st.get("type", "none"), "url": self.paths.load_settings().get("hub_url", ""),
                "seat": self.app.agent, "error": self.app.hub_error, "token": bool(self.keys.get(HUB_TOKEN)),
                "machine": this_machine(), "seat_error": getattr(self, "seat_error", "")}

    def join_hub(self) -> None:
        """This phone as its own seat in the shared hub.yaml (the PC sees it after its next sync)."""
        from .sync import register_seat, this_machine

        self.seat_error = ""
        if not self.app.hub:
            return
        me = this_machine()
        try:
            with self.app.hub_lock:
                register_seat(self.app.hub, me["id"], me["name"], me["kind"], "Roundtable on this phone")
        except Exception as e:  # offline: the next sync adds it
            self.seat_error = f"The phone isn't in the hub's list yet ({e}); it tries again at the next sync."[:300]

    def local_api(self, method: str, path: str, q: dict, body: dict) -> tuple[bool, Any]:
        if (method, path) == ("GET", "/api/keys"):
            return True, self.keys_list()
        if (method, path) == ("POST", "/api/keys"):
            return True, self.keys_save(body)
        if (method, path) == ("GET", "/api/hub"):
            return True, self.hub_status()
        if (method, path) == ("POST", "/api/hub"):
            device = " ".join(str(body.get("device_name") or "").split())[:40]
            if device:
                settings = self.paths.load_settings()
                settings["device_name"] = device
                self.paths.save_settings(settings)
            machine_env(self.paths, self.app.agent or seat_id(self.paths))
            connect_hub(self.paths, self.keys, str(body.get("url") or ""), str(body.get("token") or ""),
                        self.app.agent or seat_id(self.paths), log=lambda _t: None)
            self.app.reload_hub()
            if self.app.hub_error:
                raise RuntimeError(self.app.hub_error)
            self.join_hub()
            return True, self.hub_status()
        return False, None


def make_local_server(home: Path, port: int, token: str):
    """Everything `phone serve --local` starts, without serving yet (tests drive it directly)."""
    from http.server import ThreadingHTTPServer

    from .phone import make_phone_handler
    from .ui.server import UIApp

    if not token or len(token) < MIN_TOKEN:
        raise ValueError(f"ROUNDTABLE_LAUNCH_TOKEN must be set (at least {MIN_TOKEN} characters)")
    home = Path(home).expanduser()
    os.environ["ROUNDTABLE_HOME"] = str(home)
    paths = Paths(home)
    setup = ensure_phone_setup(paths)
    keys = KeyStore(paths, file_only=True)
    keys.load_into_env(list(PROVIDER_KEYS.values()))
    use_hub_token(paths, keys)
    machine_env(paths, setup["seat"])
    os.environ["HUB_CONFIG"] = str(paths.hub_yaml)
    os.environ["HARNESS_CONFIG"] = str(paths.harness_yaml)
    app = UIApp(str(paths.hub_yaml), str(paths.harness_yaml), agent=setup["seat"], projects_dir=str(setup["projects"]))
    app.desktop = {"paths": paths, "keys": keys}
    app.phone = LocalAccess(app, paths, keys, token)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_phone_handler(app.phone))
    httpd.daemon_threads = True
    return httpd, app


def serve_local(home: Path, port: int) -> int:
    token = os.environ.pop("ROUNDTABLE_LAUNCH_TOKEN", "")  # out of the environment: commands never see it
    try:
        httpd, app = make_local_server(home, port, token)
    except (ValueError, OSError) as e:
        print(f"roundtable phone serve: {e}", file=sys.stderr, flush=True)
        return 2
    app.start_auto_sync()
    app.preview.start()
    print(f"{READY} http://127.0.0.1:{httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="roundtable phone", description=(
        "Roundtable on the phone itself (Roundtable Mobile starts this inside its own Linux)."))
    p.add_argument("what", choices=["serve"])
    p.add_argument("--local", action="store_true", help="127.0.0.1 only, plain HTTP, the app's launch token")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--home", help="where settings, keys and the hub live (default $ROUNDTABLE_HOME)")
    args = p.parse_args(argv)
    if not args.local:
        print("roundtable phone serve: only --local is supported here. On a PC, turn on phone access in the "
              "app's Settings instead.", file=sys.stderr)
        return 2
    home = args.home or os.environ.get("ROUNDTABLE_HOME") or str(Path.home() / ".roundtable")
    return serve_local(Path(home), args.port)
