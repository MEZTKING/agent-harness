"""Roundtable Hold desktop app (what the Windows installer launches).

* Keeps everything in one app folder (Windows: %APPDATA%\\RoundtableHold):
  config/hub.yaml, config/harness.yaml, hub-data/ (local or a git clone), logs/.
* API keys live in the OS credential store (Windows Credential Manager via
  `keyring`); they are loaded into the environment at start-up, so every
  provider finds them exactly as on the command line.
* Starts the web UI on a free localhost port and shows it in a native window
  (pywebview / Edge WebView2), or the default browser if that isn't available.

Run from source:  roundtable app        (or: python -m roundtable.desktop)
Self-test:        roundtable-app --self-test   (used by the installer builds)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from importlib import resources
from pathlib import Path

APP_NAME = "RoundtableHold"
KEYRING_SERVICE = "Roundtable Hold"
KNOWN_KEYS = {
    "ANTHROPIC_API_KEY": "Claude (Anthropic)",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "RETRODIFFUSION_API_KEY": "Retro Diffusion (pixel art)",
    "OPENAI_API_KEY": "OpenAI",
    "GEMINI_API_KEY": "Google Gemini",
}


# -- locations --------------------------------------------------------------------------
def app_home() -> Path:
    if os.environ.get("ROUNDTABLE_HOME"):
        return Path(os.environ["ROUNDTABLE_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "roundtable-hold"


def default_projects_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Roundtable Projects"


class Paths:
    def __init__(self, home: Path | None = None):
        self.home = home or app_home()
        self.config = self.home / "config"
        self.hub_yaml = self.config / "hub.yaml"
        self.harness_yaml = self.config / "harness.yaml"
        self.hub_data = self.home / "hub-data"
        self.logs = self.home / "logs"
        self.settings = self.config / "app.json"

    def ensure(self) -> None:
        for d in (self.config, self.logs):
            d.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> dict:
        try:
            return json.loads(self.settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_settings(self, data: dict) -> None:
        self.ensure()
        self.settings.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- API keys --------------------------------------------------------------------------------
class KeyStore:
    """API keys in the OS credential store; falls back to a private file if none exists."""

    def __init__(self, paths: Paths, backend=None):
        self.paths = paths
        self.backend = backend
        if self.backend is None:
            try:
                import keyring
                from keyring.backends import fail

                kr = keyring.get_keyring()
                self.backend = None if isinstance(kr, fail.Keyring) or "fail" in type(kr).__module__ else keyring
            except Exception:
                self.backend = None
        self.file = paths.config / "keys.json"

    @property
    def secure(self) -> bool:
        return self.backend is not None

    def _file_keys(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, name: str) -> str | None:
        if self.backend:
            try:
                return self.backend.get_password(KEYRING_SERVICE, name)
            except Exception:
                return None
        return self._file_keys().get(name)

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        if self.backend:
            if value:
                self.backend.set_password(KEYRING_SERVICE, name, value)
            else:
                try:
                    self.backend.delete_password(KEYRING_SERVICE, name)
                except Exception:
                    pass
        else:
            keys = self._file_keys()
            if value:
                keys[name] = value
            else:
                keys.pop(name, None)
            self.paths.ensure()
            self.file.write_text(json.dumps(keys), encoding="utf-8")
            try:
                os.chmod(self.file, 0o600)
            except OSError:
                pass
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)

    def names(self, extra: list[str] | None = None) -> list[str]:
        return list(dict.fromkeys(list(KNOWN_KEYS) + list(extra or [])))

    def load_into_env(self, extra: list[str] | None = None) -> list[str]:
        loaded = []
        for name in self.names(extra):
            if os.environ.get(name):
                continue  # an explicit environment variable wins
            v = self.get(name)
            if v:
                os.environ[name] = v
                loaded.append(name)
        return loaded


# -- first-run config -------------------------------------------------------------------------
def ensure_configs(paths: Paths) -> None:
    """Create a working harness.yaml and a local-only hub.yaml the first time."""
    paths.ensure()
    if not paths.harness_yaml.exists():
        text = resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(encoding="utf-8")
        paths.harness_yaml.write_text(text, encoding="utf-8")
    if not paths.hub_yaml.exists():
        write_local_hub(paths)


def write_local_hub(paths: Paths, agents: dict | None = None) -> None:
    import yaml

    cfg = {
        "storage": {"type": "file", "path": str(paths.hub_data)},
        "default_policy": "deny",
        "agents": agents or {"me": {"description": "My own notes and plans that don't belong to one project"}},
        "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]}],
    }
    paths.hub_yaml.write_text("# Roundtable Hold hub (this computer only). Connect GitHub sync in Settings.\n"
                              + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def git_version() -> str | None:
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10)
        return res.stdout.strip() if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def connect_github_hub(paths: Paths, url: str, log=print) -> None:
    """Clone a hub data repo (e.g. your agent-hub-data) and point hub.yaml at it."""
    import yaml

    url = url.strip()
    if not url.startswith(("https://", "git@")):
        raise ValueError("enter the repository URL, e.g. https://github.com/you/agent-hub-data")
    if not git_version():
        raise RuntimeError("Git is not installed. Install Git for Windows from https://git-scm.com/download/win, "
                           "then try again.")
    target = paths.home / "hub-repo"
    if (target / ".git").exists():
        log(f"using existing clone in {target}")
        subprocess.run(["git", "-C", str(target), "pull", "--ff-only"], capture_output=True, text=True, timeout=300)
    else:
        log(f"cloning {url} (a GitHub sign-in window may open)...")
        res = subprocess.run(["git", "clone", url, str(target)], capture_output=True, text=True, timeout=900)
        if res.returncode != 0:
            raise RuntimeError(f"git clone failed: {res.stderr.strip()[-400:]}")
    repo_yaml = target / "hub.yaml"
    if repo_yaml.exists():
        cfg = yaml.safe_load(repo_yaml.read_text(encoding="utf-8")) or {}
        log("found hub.yaml in the repository")
    else:
        cfg = {"default_policy": "deny", "agents": {"me": {"description": "My own notes and plans"}},
               "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]}
        log("repository has no hub.yaml yet; starting a new hub in it")
    cfg["storage"] = {"type": "git", "path": str(target), "branch": (cfg.get("storage") or {}).get("branch", "main")}
    paths.hub_yaml.write_text("# Roundtable Hold hub, synced with " + url + "\n" + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    log("hub connected")


# -- process plumbing --------------------------------------------------------------------------
def hide_console_windows() -> None:
    """On Windows, stop every git/shell subprocess from flashing a console window."""
    if sys.platform != "win32":
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original = subprocess.Popen.__init__

    def patched(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | flag
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched


def redirect_output(paths: Paths) -> None:
    """A windowed app has no console: send prints to a log file instead of crashing."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        paths.logs.mkdir(parents=True, exist_ok=True)
        log = open(paths.logs / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = log


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(paths: Paths, keystore: KeyStore, port: int | None = None):
    from http.server import ThreadingHTTPServer

    from .ui.server import UIApp, make_handler

    os.environ["HUB_CONFIG"] = str(paths.hub_yaml)
    os.environ["HARNESS_CONFIG"] = str(paths.harness_yaml)
    settings = paths.load_settings()
    projects = Path(settings.get("projects_dir") or default_projects_dir())
    projects.mkdir(parents=True, exist_ok=True)
    app = UIApp(str(paths.hub_yaml), str(paths.harness_yaml), agent=settings.get("agent") or "me",
                projects_dir=str(projects))
    app.desktop = {"paths": paths, "keys": keystore}
    from .phone import PhoneAccess

    app.phone = PhoneAccess(app, paths.home)
    app.start_auto_sync()
    httpd = ThreadingHTTPServer(("127.0.0.1", port or free_port()), make_handler(app, token=None, allow_remote=False))
    app.phone.start()  # phone access, if it was turned on in Settings
    threading.Thread(target=httpd.serve_forever, daemon=True, name="ui-server").start()
    return httpd, app


def self_test(paths: Paths) -> int:
    """Start everything headless and check the UI answers. Used by the installer builds."""
    import urllib.request

    keystore = KeyStore(paths)
    ensure_configs(paths)
    keystore.load_into_env()
    httpd, app = start_server(paths, keystore)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        ov = json.load(urllib.request.urlopen(base + "/api/overview", timeout=30))
        page = urllib.request.urlopen(base + "/", timeout=30).read()
        setup = json.load(urllib.request.urlopen(base + "/api/setup", timeout=30))
        ok = ov["hub"] and ov["harness"] and b"Roundtable Hold" in page and "keys" in setup
        result = json.dumps({"ok": bool(ok), "hub": ov["hub"], "harness": ov["harness"],
                             "hub_error": ov.get("hub_error"), "harness_error": ov.get("harness_error"),
                             "secure_keys": setup.get("secure_keys"), "home": str(paths.home)})
        paths.logs.mkdir(parents=True, exist_ok=True)
        (paths.logs / "self-test.json").write_text(result, encoding="utf-8")  # windowed builds have no console
        if sys.stdout is not None:
            print(result)
        return 0 if ok else 1
    finally:
        httpd.shutdown()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="roundtable-app", description="Roundtable Hold desktop app")
    p.add_argument("--self-test", action="store_true", help="start headless, check the UI answers, exit")
    p.add_argument("--browser", action="store_true", help="open in the default browser instead of an app window")
    p.add_argument("--port", type=int)
    args = p.parse_args(argv)

    paths = Paths()
    if args.self_test:
        return self_test(paths)
    redirect_output(paths)
    hide_console_windows()
    ensure_configs(paths)
    keystore = KeyStore(paths)
    keystore.load_into_env()
    httpd, app = start_server(paths, keystore, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Roundtable Hold running at {url} (data: {paths.home})", flush=True)

    if not args.browser:
        try:
            import webview  # pywebview: native window (Edge WebView2 on Windows)

            webview.create_window("Roundtable Hold", url, width=1280, height=860, min_size=(420, 600))
            webview.start()  # blocks until the window is closed
            httpd.shutdown()
            return 0
        except Exception as e:  # no GUI toolkit: fall back to the browser
            print(f"native window unavailable ({e}); opening the browser", flush=True)
    import webbrowser

    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
