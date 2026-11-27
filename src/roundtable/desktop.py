"""Roundtable Hold desktop app (what the Windows installer launches).

* Keeps everything in one app folder (Windows: %APPDATA%\\RoundtableHold):
  config/hub.yaml, config/harness.yaml, hub-data/ (local or a git clone), logs/.
* API keys live in the OS credential store (Windows Credential Manager via
  `keyring`); they are loaded into Roundtable's in-memory vault at start-up
  (`core/secrets.py`, never os.environ), so providers find them and the
  commands AI workers run never inherit them (`harness/safeenv.py`).
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

from .core import secrets as vault
from .brand import NAME, SWITCHED

# Where data and keys live. From 1.0.0 (Darkness Harness) new installs use the new names, and a PC that
# already has Roundtable Hold's folder or keys keeps using them: nothing is ever moved or deleted
# (the hub's git copy, projects.json and git worktrees hold absolute paths into the old folder).
APP_NAME = "DarknessHarness"
LEGACY_APP_NAME = "RoundtableHold"
LINUX_NAME = "darkness-harness"
LEGACY_LINUX_NAME = "roundtable-hold"
KEYRING_SERVICE = "Darkness Harness"          # keys are written here
LEGACY_KEYRING_SERVICE = "Roundtable Hold"    # and read from here when the new place has none
PROJECTS_NAME = "Darkness Projects"
LEGACY_PROJECTS_NAME = "Roundtable Projects"
KNOWN_KEYS = {
    "ANTHROPIC_API_KEY": "Claude (Anthropic)",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "RETRODIFFUSION_API_KEY": "Retro Diffusion (pixel art)",
    "OPENAI_API_KEY": "OpenAI",
    "GEMINI_API_KEY": "Google Gemini",
    "OPENROUTER_API_KEY": "OpenRouter",
    "OPENFERENCE_API_KEY": "Openference",
    "ROUNDTABLE_GITHUB_TOKEN": "GitHub",
    "BRAVE_API_KEY": "Brave Search",  # web search for builders (harness/websearch.py)
    "TAVILY_API_KEY": "Tavily",
}


def key_label(name: str, providers: dict | None = None) -> str:
    """What the owner reads for a key: its maker's name, never the raw variable name."""
    if name in KNOWN_KEYS:
        return KNOWN_KEYS[name]
    users = [pid for pid, spec in (providers or {}).items() if (spec or {}).get("api_key_env") == name]
    if users:
        return " / ".join(users)
    return name.removesuffix("_API_KEY").replace("_", " ").lower() or name


def provider_specs(harness_yaml: Path) -> dict:
    """The providers in harness.yaml and custom.yaml (harness.yaml wins on a name clash)."""
    import yaml

    out: dict = {}
    for f in (harness_yaml.parent / "custom.yaml", harness_yaml):
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            continue
        provs = raw.get("providers") if isinstance(raw, dict) else None
        if isinstance(provs, dict):
            out.update({str(k): v for k, v in provs.items() if isinstance(v, dict)})
    return out


def provider_key_names(paths: "Paths") -> list[str]:
    """The key variables of every provider in harness.yaml and custom.yaml, to load at start-up."""
    names = [spec.get("api_key_env") for spec in provider_specs(paths.harness_yaml).values()]
    return list(dict.fromkeys(n for n in names if isinstance(n, str) and n))


# -- locations --------------------------------------------------------------------------
def _in_use(folder: Path) -> bool:
    """A folder that holds something (an empty one left behind doesn't count)."""
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def pick_home(new: Path, old: Path) -> Path:
    """The new folder if it is in use; else the old one if it exists; else the new one (made later).

    Legacy first: an installed Roundtable Hold keeps its folder for good. Nothing is moved.
    """
    if _in_use(new):
        return new
    if old.is_dir():
        return old
    return new


def app_home() -> Path:
    if os.environ.get("ROUNDTABLE_HOME"):
        return Path(os.environ["ROUNDTABLE_HOME"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return pick_home(base / APP_NAME, base / LEGACY_APP_NAME)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return pick_home(base / APP_NAME, base / LEGACY_APP_NAME)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return pick_home(base / LINUX_NAME, base / LEGACY_LINUX_NAME)


def default_projects_dir() -> Path:
    """Documents\\Darkness Projects for a new install; an existing Roundtable Projects folder stays in use."""
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return pick_home(base / PROJECTS_NAME, base / LEGACY_PROJECTS_NAME)


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
    """API keys in the OS credential store; falls back to a private file if none exists.

    `file_only=True` skips the credential store (a headless Linux, e.g. Roundtable on the phone,
    has no keyring): keys go to `config/keys.json`, readable by this user only.

    Keys are written under KEYRING_SERVICE. A key saved before 1.0.0 (under LEGACY_KEYRING_SERVICE) is
    still read, and copied forward to the new name the first time; the old entry is kept. Only when the
    owner removes a key is it removed under both names, so a removed key can't come back from the old place.
    """

    def __init__(self, paths: Paths, backend=None, file_only: bool = False):
        self.paths = paths
        self.backend = backend
        if self.backend is None and not file_only:
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
                value = self.backend.get_password(KEYRING_SERVICE, name)
            except Exception:
                value = None
            if value:
                return value
            try:
                old = self.backend.get_password(LEGACY_KEYRING_SERVICE, name)
            except Exception:
                return None
            if old:
                try:
                    self.backend.set_password(KEYRING_SERVICE, name, old)  # copied forward, the old one kept
                except Exception:
                    pass
            return old or None
        return self._file_keys().get(name)

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        if self.backend:
            if value:
                self.backend.set_password(KEYRING_SERVICE, name, value)
            else:
                for service in (KEYRING_SERVICE, LEGACY_KEYRING_SERVICE):  # removed means removed everywhere
                    try:
                        self.backend.delete_password(service, name)
                    except Exception:
                        pass
        else:
            keys = self._file_keys()
            if value:
                keys[name] = value
            else:
                keys.pop(name, None)
            self.paths.ensure()
            # created readable by this user only, then replaced in one step (never a half-written file)
            tmp = self.file.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(keys))
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.file)
        # into Roundtable's own memory, never os.environ: a worker's command can't inherit it
        vault.put(name, value)

    def names(self, extra: list[str] | None = None) -> list[str]:
        return list(dict.fromkeys(list(KNOWN_KEYS) + list(extra or [])))

    def load_into_env(self, extra: list[str] | None = None) -> list[str]:
        """Load the saved keys into Roundtable's in-memory vault (``core/secrets.py``), not into
        ``os.environ``: providers read them from there, and workers' commands never see them."""
        loaded = []
        for name in self.names(extra):
            vault.remember_name(name)
            if os.environ.get(name):
                continue  # an explicit environment variable wins
            v = self.get(name)
            if v:
                vault.put(name, v)
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


# sha256 of every harness.yaml template shipped before the recommended split (line endings as "\n"):
# a file still exactly like one of them was never edited, so it is replaced by the new template.
OLD_TEMPLATES = {
    "ea37aae3b2f180de7e712f0b1ffca8e252a39c51ec361c51d762f6e87259cafb",
    "fc97a521104b88e82e9f70c047fa640a3a53fbf033fcb66269d7395d1e1b779e",
    "d2a92f68b8601c12cd2c082f394ea38e9bad9d796b659a1a486d4a289816fec4",
    "63d2ce95ccb62f492d205db80e532e8cfdb9fe202715e513daa7546df958c1d9",
    "51a1337fd55865e544d7a024d4d9e98799f95a53546d4ecf2b0f1ce8cf67a81a",
    "e240d7cd5a157eeaa3541cd2f54de5bc30457094be18f5ef195c8670f71af8a5",
    "6b51d5564c24d2f132b4ac1061d6eecc0459c251bee901c9ab5dd53fc015ee03",
    "3d0b2f7679f0c5d272c755c2d240869696d71771e3a572061c6552c9e101be3e",
    "a3c857f7c1e356f75dae4e018393282ad8f3356ebf2ed086051d265c7591128d",
    "42aa05bf17f80cd831a0187bea3cc47dcdf4da0c5201a8b5f189cbab82328067",
    "127d7b108839bd2121de45ba16aa25523c259875ca335ac7b5b7024c17477dd2",
    "6a09857d0d99bc6b3f0ca71b8175ede7b827d84518742270acd97b9a1b5e2600",
    "91bf48195004fa9978cd95b4b70a7fc0a543eb6692252295836c20c0115039c6",
    "15be1a1687588c8afb95dba1d68785d4a618b3e1adf90a490a9b8953ebd93da0",
}
FLASH = "deepseek/deepseek-v4-flash"
NO_PRO = {"deepseek/deepseek-v4-pro": FLASH, "openference/DeepSeek-V4-Pro": "openference/DeepSeek-V4.1-Flash-1017"}


def _template_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.replace("\r", "").encode("utf-8")).hexdigest()  # line endings ignored (Windows may add \r\r)


def migrate_configs(paths: Paths, today=None) -> list[str]:
    """Bring an older harness.yaml up to date at start-up; returns what was done, in plain words.

    * still exactly an older shipped template: replaced by the new one (the recommended split);
    * uses DeepSeek V4 Pro anywhere: switched to DeepSeek V4 Flash (the owner's rule);
    * otherwise nothing is touched. A backup is kept and the change goes in the hub's journal.
    """
    from datetime import date

    f = paths.harness_yaml
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return []
    done: list[str] = []
    new = text
    if _template_hash(text) in OLD_TEMPLATES:
        new = resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(encoding="utf-8")
        done.append(f"{SWITCHED} the first-run model choices became the recommended setup "
                    "(Claude plans, DeepSeek V4 Flash codes, other makers check). Why: the old settings "
                    "had never been changed, and the owner chose the recommended split.")
    elif any(old in text for old in NO_PRO):
        for old, flash in NO_PRO.items():
            new = new.replace(old, flash)
        done.append(f"{SWITCHED} DeepSeek V4 Pro was replaced with DeepSeek V4 Flash in harness.yaml. "
                    "Why: the owner said no DeepSeek V4 Pro for now.")
    if not done or new == text:
        return []
    stamp = (today or date.today()).isoformat()
    backup = f.with_name(f"{f.name}.before-{stamp}")
    n = 2
    while backup.exists():
        backup = f.with_name(f"{f.name}.before-{stamp}-{n}")
        n += 1
    backup.write_text(text, encoding="utf-8")
    f.write_text(new, encoding="utf-8")
    for line in done:
        _journal_decision(paths, line, f"old file kept as {backup.name}")
    return done


def _journal_decision(paths: Paths, text: str, details: str = "") -> None:
    """A decision line in the hub's journal, like improve.after_each_run writes; skipped without a hub."""
    try:
        import yaml

        from .core.config import load_config
        from .hub.service import Hub

        if not paths.hub_yaml.exists():
            return
        hub = Hub(load_config(str(paths.hub_yaml)))
        harness = yaml.safe_load(paths.harness_yaml.read_text(encoding="utf-8")) or {}
        agents = hub.config.agents
        for agent in ((harness.get("hub") or {}).get("agent"), paths.load_settings().get("agent"), "me"):
            if agent and agent in agents:
                hub.journal.add(agent, "decision", text, details=details, source="harness")
                return
    except Exception:  # the hub is optional; never stop the app starting over it
        pass


def write_local_hub(paths: Paths, agents: dict | None = None) -> None:
    import yaml

    cfg = {
        "storage": {"type": "file", "path": str(paths.hub_data)},
        "default_policy": "deny",
        "agents": agents or {"me": {"description": "My own notes and plans that don't belong to one project"}},
        "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]}],
    }
    paths.hub_yaml.write_text(f"# {NAME} hub (this computer only). Connect GitHub sync in Settings.\n"
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
    paths.hub_yaml.write_text(f"# {NAME} hub, synced with " + url + "\n" + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
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
    app.preview.start()  # the projects' own apps, for their Live tabs
    threading.Thread(target=httpd.serve_forever, daemon=True, name="ui-server").start()
    return httpd, app


def _mcp_client_present() -> bool:
    """The MCP client roles use for tool servers (Unreal's editor and others) made it into the build."""
    try:
        import mcp  # noqa: F401
        import mcp.client.stdio  # noqa: F401
        import mcp.client.streamable_http  # noqa: F401
        import mcp_types  # noqa: F401
        from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: F401
        return True
    except ImportError:
        return False


def self_test(paths: Paths) -> int:
    """Start everything headless and check the UI answers. Used by the installer builds."""
    import urllib.request

    keystore = KeyStore(paths)
    ensure_configs(paths)
    migrate_configs(paths)
    keystore.load_into_env(provider_key_names(paths))
    httpd, app = start_server(paths, keystore)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        ov = json.load(urllib.request.urlopen(base + "/api/overview", timeout=30))
        page = urllib.request.urlopen(base + "/", timeout=30).read()
        setup = json.load(urllib.request.urlopen(base + "/api/setup", timeout=30))
        mcp_ok = _mcp_client_present()
        ok = ov["hub"] and ov["harness"] and b"Roundtable Hold" in page and "keys" in setup and mcp_ok
        result = json.dumps({"ok": bool(ok), "hub": ov["hub"], "harness": ov["harness"], "mcp_client": mcp_ok,
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

    p = argparse.ArgumentParser(prog="roundtable-app", description=f"{NAME} desktop app")
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
    migrate_configs(paths)
    keystore = KeyStore(paths)
    keystore.load_into_env(provider_key_names(paths))
    httpd, app = start_server(paths, keystore, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"{NAME} running at {url} (data: {paths.home})", flush=True)

    if not args.browser:
        try:
            import webview  # pywebview: native window (Edge WebView2 on Windows)

            webview.create_window(NAME, url, width=1280, height=860, min_size=(420, 600))
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
