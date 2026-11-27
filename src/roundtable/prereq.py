"""What this computer has for building things (the Tools page), and the MCP tool servers given to jobs.

* ``CATALOG``: Git, Node.js (npm, npx), Python, uv, Playwright's browser, Java and the Android SDK, Godot,
  Unreal Engine, Blender, Claude Code and Codex: each with where it is usually found, how its version is
  read and how it is installed on each system;
* ``status`` / ``find``: each tool found (version, where) or missing, on a ``System`` (the real computer,
  or a made-up one in the tests: PATH folders, environment, home and a root for fixed folders);
* ``install_plan`` / ``run_install``: the install command for this system (Windows: winget with the exact
  package id; macOS: Homebrew; npm/npx for the Node tools; Linux: the words of what to install). Only
  ever run when the owner presses Install, as a background job with a plain log; then it checks again;
* ``needs_cards``: a project that needs a tool that isn't here (a Godot game with no Godot) as a Needs-you
  card;
* MCP servers: ``servers_view``, ``add_server``, ``remove_server``, ``give_server``, ``test_server``. The
  app's choices go into custom.yaml like the Models page's (``mcp_servers:`` for the servers, and
  ``mcp_roles: {job: [servers]}`` for which jobs use them), merged by ``merge_custom_tools``.

The catalog's shape (a row per tool with what it's for and an install line per system, and "found" meaning
the name resolved to a real file) follows Munder Difflin's prerequisites panel (src/shared/toolCatalog.ts,
src/main/toolsStatus.ts; MIT, Copyright (c) 2026 Chaitanya Giri); the code is Roundtable's own.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Runner = Callable[[list[str], float], tuple[int | None, str]]  # (argv, timeout) -> (exit code, output)
Line = Callable[[str], None]

VERSION_TIMEOUT = 20.0
INSTALL_TIMEOUT = 45 * 60.0
WINGET_FLAGS = ["-e", "--silent", "--accept-package-agreements", "--accept-source-agreements"]
WINGET_ALREADY = {-1978335189, 0x8A15002B, -1978335135, 0x8A150061}  # nothing newer / already installed


# -- the computer -------------------------------------------------------------------------------------
def _os_name() -> str:
    if os.name == "nt":
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def _real_runner(argv: list[str], timeout: float) -> tuple[int | None, str]:
    from .harness.safeenv import clean_env

    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, env=clean_env(), stdin=subprocess.DEVNULL,
                           text=True, encoding="utf-8", errors="replace", **kw)
    except subprocess.TimeoutExpired:
        return None, ""
    except (OSError, ValueError) as e:
        return 127, str(e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _windows_saved_path() -> list[str]:
    """PATH as Windows has it saved now (machine, then user): an installer's new folder shows without a restart."""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return []
    out: list[str] = []
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, sub) as k:
                value, _ = winreg.QueryValueEx(k, "Path")
            out += [os.path.expandvars(p) for p in str(value).split(";") if p]
        except OSError:
            continue
    return out


@dataclass
class System:
    """Where to look: the real computer (``System.here()``) or a made-up one in the tests."""

    os: str  # "windows", "mac" or "linux"
    path: list[Path]  # PATH, as folders
    env: dict[str, str]
    home: Path
    root: Path | None = None  # tests: fixed folders (/Applications, C:\\ProgramData...) live under here
    run: Runner = _real_runner

    @classmethod
    def here(cls) -> System:
        name = _os_name()
        dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
        if name == "windows":
            dirs += [p for p in _windows_saved_path() if p not in dirs]
        return cls(os=name, path=[Path(p) for p in dirs], env=dict(os.environ), home=Path.home())

    def at(self, fixed: str) -> Path:
        """A fixed folder such as /Applications (under ``root`` in the tests)."""
        if self.root is None:
            return Path(fixed)
        return self.root / fixed.replace(":", "").lstrip("/\\")

    def env_dir(self, name: str) -> Path | None:
        v = self.env.get(name)
        return Path(v) if v else None

    def exts(self) -> list[str]:
        if self.os != "windows":
            return [""]
        return [e.lower() for e in (self.env.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e] + [""]

    def is_program(self, p: Path) -> bool:
        try:
            if not p.is_file():
                return False
        except OSError:
            return False
        return self.os == "windows" or os.access(p, os.X_OK)

    def extra_dirs(self) -> list[Path]:
        """Where installers put programs that a window opened from the Start menu or Finder may not have on PATH."""
        h = self.home
        if self.os == "windows":
            out = [d / "Microsoft" / "WinGet" / "Links" for d in [self.env_dir("LOCALAPPDATA")] if d]
            out += [d / "npm" for d in [self.env_dir("APPDATA")] if d]
            return out + [h / ".local" / "bin", h / ".cargo" / "bin"]
        if self.os == "mac":
            return [self.at("/opt/homebrew/bin"), self.at("/usr/local/bin"), h / ".local" / "bin", h / ".cargo" / "bin"]
        return [h / ".local" / "bin", h / ".cargo" / "bin", self.at("/snap/bin"), self.at("/usr/local/bin")]

    def which(self, name: str) -> Path | None:
        """The program called ``name`` on PATH (then the usual extra folders), or None."""
        seen: set[str] = set()
        for d in [*self.path, *self.extra_dirs()]:
            key = str(d).lower()
            if key in seen:
                continue
            seen.add(key)
            for ext in self.exts():
                p = d / (name + ext)
                if self.is_program(p):
                    return p
        return None


# -- versions -----------------------------------------------------------------------------------------
_VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?)")


def parse_version(text: str) -> str:
    """The first version number in a program's answer: 'git version 2.47.1.windows.1' -> '2.47.1'."""
    text = text or ""
    m = re.search(r'version "(\d+(?:\.\d+)*)', text)  # java -version: openjdk version "17.0.13" 2024-10-15
    if m:
        v = m.group(1)
        return v[2:] if v.startswith("1.") and v.count(".") >= 1 and v.split(".")[1] in "5678" else v
    m = _VERSION.search(text)
    return m.group(1) if m else ""


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def at_least(v: str, minimum: str) -> bool:
    return not minimum or not v or version_tuple(v) >= version_tuple(minimum)


# -- the catalog --------------------------------------------------------------------------------------
@dataclass
class Tool:
    id: str
    name: str
    group: str
    why: str  # one plain line: what it's for
    names: tuple[str, ...] = ()  # programs to look for on PATH
    version_args: tuple[str, ...] = ("--version",)
    min_version: str = ""
    winget: str = ""  # the exact winget package id
    brew: tuple[str, ...] = ()  # what goes after `brew install`
    any_os: tuple[str, ...] = ()  # the same command on every system (npm, npx)
    linux: str = ""  # the words for Linux: what to install
    needs: tuple[str, ...] = ()  # tools that must be here first
    admin: bool = False  # Windows asks permission (the installer is for every user)
    reboot: bool = False
    note: str = ""  # after the install, what else there is
    size: str = ""
    places: Callable[[System], list[Path]] = field(default=lambda s: [])
    finder: Callable[[System, Tool], dict[str, Any] | None] | None = None
    extras: tuple[str, ...] = ()  # programs that come with it (npm, npx, uvx)


def _glob(base: Path | None, *patterns: str) -> list[Path]:
    if not base:
        return []
    out: list[Path] = []
    for pat in patterns:
        try:
            out += sorted(base.glob(pat), key=lambda p: version_tuple(p.as_posix()), reverse=True)
        except (OSError, ValueError):
            continue
    return out


def _pf(s: System) -> list[Path]:
    return [d for d in (s.env_dir("ProgramFiles"), s.env_dir("ProgramFiles(x86)")) if d]


def _git_places(s: System) -> list[Path]:
    if s.os == "windows":
        return [d / "Git" / "cmd" / "git.exe" for d in _pf(s)]
    return [s.at("/usr/bin/git")] if s.os == "linux" else []


def _node_places(s: System) -> list[Path]:
    return [d / "nodejs" / "node.exe" for d in _pf(s)] if s.os == "windows" else []


def _python_places(s: System) -> list[Path]:
    if s.os == "windows":
        return _glob(s.env_dir("LOCALAPPDATA"), "Programs/Python/Python3*/python.exe") + \
            [p for d in _pf(s) for p in _glob(d, "Python3*/python.exe")]
    return []


def _java_places(s: System) -> list[Path]:
    exe = "java.exe" if s.os == "windows" else "java"
    out = [d / "bin" / exe for d in [s.env_dir("JAVA_HOME")] if d]
    if s.os == "windows":
        for d in _pf(s):
            out += _glob(d, "Eclipse Adoptium/jdk-*/bin/java.exe", "Microsoft/jdk-*/bin/java.exe",
                         "Java/jdk-*/bin/java.exe")
            out.append(d / "Android" / "Android Studio" / "jbr" / "bin" / "java.exe")
    elif s.os == "mac":
        out += _glob(s.at("/Library/Java/JavaVirtualMachines"), "*/Contents/Home/bin/java")
        out.append(s.at("/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java"))
    else:
        out += _glob(s.at("/usr/lib/jvm"), "*/bin/java")
    return out


def _godot_places(s: System) -> list[Path]:
    """Where Godot is usually unpacked (the same places as harness/godot.py, for any system)."""
    if s.os == "mac":
        return [s.at("/Applications/Godot.app/Contents/MacOS/Godot"),
                s.home / "Applications" / "Godot.app" / "Contents" / "MacOS" / "Godot"]
    if s.os != "windows":
        return []
    dirs = [d for d in (s.env_dir("ProgramFiles"), s.env_dir("ProgramFiles(x86)"), s.env_dir("LOCALAPPDATA")) if d]
    dirs += [s.home / "Godot", s.home / "Desktop", s.home / "Downloads"]
    out: list[Path] = []
    for d in dirs:
        out += _glob(d, "Godot*/Godot_v4*console.exe", "Godot_v4*console.exe", "Godot*/Godot_v4*.exe", "Godot_v4*.exe",
                     "Godot*/Godot*.exe", "Programs/Godot*/Godot*.exe",
                     "Microsoft/WinGet/Packages/GodotEngine.GodotEngine*/Godot_v4*console.exe",
                     "Microsoft/WinGet/Packages/GodotEngine.GodotEngine*/Godot_v4*.exe")
    return out


def _blender_places(s: System) -> list[Path]:
    if s.os == "windows":
        return [p for d in _pf(s) for p in _glob(d, "Blender Foundation/Blender*/blender.exe")]
    if s.os == "mac":
        return [s.at("/Applications/Blender.app/Contents/MacOS/Blender")]
    return [s.at("/snap/bin/blender")]


def _uv_places(s: System) -> list[Path]:
    exe = "uv.exe" if s.os == "windows" else "uv"
    return [s.home / ".local" / "bin" / exe, s.home / ".cargo" / "bin" / exe]


def _claude_places(s: System) -> list[Path]:
    exe = "claude.exe" if s.os == "windows" else "claude"
    return [s.home / ".local" / "bin" / exe, s.home / ".claude" / "local" / exe]


def _sdk_dirs(s: System) -> list[Path]:
    out = [d for d in (s.env_dir("ANDROID_HOME"), s.env_dir("ANDROID_SDK_ROOT")) if d]
    if s.os == "windows":
        out += [d / "Android" / "Sdk" for d in [s.env_dir("LOCALAPPDATA")] if d]
    elif s.os == "mac":
        out.append(s.home / "Library" / "Android" / "sdk")
    else:
        out += [s.home / "Android" / "Sdk", s.at("/opt/android-sdk"), s.at("/usr/lib/android-sdk")]
    return out


def _find_android(s: System, tool: Tool) -> dict[str, Any] | None:
    for d in _sdk_dirs(s):
        parts = [x for x in ("platform-tools", "cmdline-tools", "build-tools", "platforms") if (d / x).is_dir()]
        if not parts:
            continue
        builds = sorted((p.name for p in _safe_dirs(d / "build-tools")), key=version_tuple, reverse=True)
        plats = sorted((p.name for p in _safe_dirs(d / "platforms")), key=version_tuple, reverse=True)
        detail = ", ".join(x for x in (f"Android {plats[0].removeprefix('android-')} platform" if plats else "",
                                       f"build tools {builds[0]}" if builds else "") if x)
        return {"where": str(d), "version": builds[0] if builds else "", "detail": detail or "the SDK folder"}
    return None


def _safe_dirs(d: Path) -> list[Path]:
    try:
        return [p for p in d.iterdir() if p.is_dir()]
    except OSError:
        return []


def _unreal_installs(s: System) -> list[tuple[str, Path]]:
    """Every Unreal Engine the Epic launcher installed: (version, folder), the newest first."""
    found: dict[str, Path] = {}
    if s.os == "windows":
        dat = (s.env_dir("ProgramData") or s.at("C:/ProgramData")) / "Epic" / "UnrealEngineLauncher" / \
            "LauncherInstalled.dat"
        try:
            listed = json.loads(dat.read_text(encoding="utf-8")).get("InstallationList") or []
        except (OSError, ValueError, AttributeError):
            listed = []
        for item in listed:
            if str(item.get("AppName", "")).startswith("UE_") and item.get("InstallLocation"):
                found[str(Path(item["InstallLocation"]))] = Path(item["InstallLocation"])
        bases = [d / "Epic Games" for d in _pf(s)]
    elif s.os == "mac":
        bases = [s.at("/Users/Shared/Epic Games")]
    else:
        bases = []
    for b in bases:
        for p in _glob(b, "UE_*"):
            found.setdefault(str(p), p)
    out = []
    for p in found.values():
        if not (p / "Engine").is_dir():
            continue
        out.append((_unreal_version(p), p))
    return sorted(out, key=lambda x: version_tuple(x[0]), reverse=True)


def _unreal_version(p: Path) -> str:
    try:
        b = json.loads((p / "Engine" / "Build" / "Build.version").read_text(encoding="utf-8"))
        return f"{b['MajorVersion']}.{b['MinorVersion']}.{b.get('PatchVersion', 0)}"
    except (OSError, ValueError, KeyError, TypeError):
        m = re.search(r"UE_(\d+\.\d+)", p.name)
        return m.group(1) if m else ""


def _find_unreal(s: System, tool: Tool) -> dict[str, Any] | None:
    installs = _unreal_installs(s)
    if not installs:
        return None
    v, p = installs[0]
    editor = p / "Engine" / "Binaries" / ("Win64/UnrealEditor.exe" if s.os == "windows" else "Mac/UnrealEditor.app")
    return {"where": str(editor if editor.exists() else p), "version": v,
            "also": [f"{ver or '?'} in {path}" for ver, path in installs[1:]]}


def _playwright_dirs(s: System) -> list[Path]:
    own = s.env.get("PLAYWRIGHT_BROWSERS_PATH")
    if own and own != "0":
        return [Path(own)]
    if s.os == "windows":
        return [d / "ms-playwright" for d in [s.env_dir("LOCALAPPDATA")] if d]
    if s.os == "mac":
        return [s.home / "Library" / "Caches" / "ms-playwright"]
    return [s.home / ".cache" / "ms-playwright"]


def _find_playwright(s: System, tool: Tool) -> dict[str, Any] | None:
    for d in _playwright_dirs(s):
        browsers = sorted((p for p in _safe_dirs(d) if re.fullmatch(r"chromium(_headless_shell)?-\d+", p.name)),
                          key=lambda p: version_tuple(p.name), reverse=True)
        if browsers:
            build = browsers[0].name.rsplit("-", 1)[1]
            return {"where": str(browsers[0]), "version": "", "detail": f"Chromium, Playwright's build {build}"}
    return None


CATALOG: list[Tool] = [
    Tool("git", "Git", "Basics", "Keeps every project's history, so any change can be undone.",
         names=("git",), winget="Git.Git", brew=("git",), linux="sudo apt install git", admin=True,
         places=_git_places),
    Tool("node", "Node.js", "Basics", "Runs web apps and the helpers for Godot, Claude Code and Codex (with npm and npx).",
         names=("node",), winget="OpenJS.NodeJS.LTS", brew=("node",), linux="sudo apt install nodejs npm",
         admin=True, places=_node_places, extras=("npm", "npx")),
    Tool("python", "Python", "Basics", "Runs Python apps and their tests.",
         names=("python3", "python", "py"), winget="Python.Python.3.13", brew=("python@3.13",),
         linux="sudo apt install python3 python3-venv", places=_python_places),
    Tool("uv", "uv", "Basics", "Starts Python helpers such as MCP for Blender (with uvx).",
         names=("uv",), winget="astral-sh.uv", brew=("uv",),
         linux="curl -LsSf https://astral.sh/uv/install.sh | sh", places=_uv_places, extras=("uvx",)),
    Tool("playwright", "Playwright's browser", "Basics", "Takes the pictures of your apps that you see in Live.",
         any_os=("npx", "-y", "playwright", "install", "chromium"), needs=("node",), finder=_find_playwright,
         version_args=(), size="about 150 MB"),
    Tool("java", "Java (JDK 17 or newer)", "Phone apps", "Builds Android apps (APKs).",
         names=("java",), version_args=("-version",), min_version="17", winget="EclipseAdoptium.Temurin.17.JDK",
         brew=("--cask", "temurin@17"), linux="sudo apt install openjdk-17-jdk", admin=True, places=_java_places),
    Tool("android", "Android SDK", "Phone apps", "Builds and installs Android apps (APKs).",
         winget="Google.AndroidStudio", brew=("--cask", "android-studio"),
         linux="Install Android Studio from developer.android.com, or the command-line tools into ~/Android/Sdk",
         admin=True, finder=_find_android, version_args=(), size="about 3 GB",
         note="Open Android Studio once after it installs: it downloads the SDK the first time."),
    Tool("godot", "Godot", "Games and 3D", "Makes 2D and 3D games; Roundtable starts the game itself to check it.",
         names=("godot", "godot4", "Godot"), min_version="4.4", winget="GodotEngine.GodotEngine",
         brew=("--cask", "godot"), linux="flatpak install flathub org.godotengine.Godot (or download it from godotengine.org)",
         places=_godot_places),
    Tool("unreal", "Unreal Engine", "Games and 3D", "Makes big 3D games; its MCP server lets helpers work in the editor.",
         min_version="5.8", winget="EpicGames.EpicGamesLauncher", brew=("--cask", "epic-games"),
         linux="Unreal Engine isn't offered for Linux through the Epic launcher.", admin=True,
         finder=_find_unreal, version_args=(), size="about 60 GB",
         note="This installs the Epic Games Launcher. Then sign in there and add Unreal Engine 5.8 "
              "(Unreal Engine → Library → +)."),
    Tool("blender", "Blender", "Games and 3D", "Makes the 3D models for your games.",
         names=("blender",), winget="BlenderFoundation.Blender", brew=("--cask", "blender"),
         linux="sudo snap install blender --classic", admin=True, places=_blender_places),
    Tool("claude", "Claude Code", "AI helpers", "Anthropic's coding helper, run in a terminal.",
         names=("claude",), any_os=("npm", "install", "-g", "@anthropic-ai/claude-code"), needs=("node",),
         places=_claude_places),
    Tool("codex", "Codex", "AI helpers", "OpenAI's coding helper, run in a terminal.",
         names=("codex",), any_os=("npm", "install", "-g", "@openai/codex"), needs=("node",)),
]
BY_ID = {t.id: t for t in CATALOG}
GROUPS = ["Basics", "Games and 3D", "Phone apps", "AI helpers"]


# -- finding ------------------------------------------------------------------------------------------
def _candidates(s: System, tool: Tool, godot_path: str | None) -> list[Path]:
    out: list[Path] = []
    if tool.id == "godot":
        for v in (godot_path, s.env.get("GODOT")):
            if v:
                p = Path(v).expanduser()
                out.append(p if p.is_file() else (s.which(v) or p))
    for n in tool.names:
        p = s.which(n)
        if p:
            out.append(p)
    out += tool.places(s)
    seen: set[str] = set()
    uniq = []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _store_stub(p: Path) -> bool:
    """Windows' 'python' that only opens the Microsoft Store."""
    return "windowsapps" in str(p).lower() and p.name.lower().startswith(("python", "py"))


def find(tool: Tool | str, s: System | None = None, versions: bool = True,
         godot_path: str | None = None) -> dict[str, Any]:
    """One tool on this computer: {state: found | missing | old | broken, version, where, detail, also}."""
    tool = BY_ID[tool] if isinstance(tool, str) else tool
    s = s or System.here()
    got: dict[str, Any] | None = None
    broken = ""
    if tool.finder:
        got = tool.finder(s, tool)
    else:
        for p in _candidates(s, tool, godot_path):
            if not s.is_program(p):
                continue
            if not versions or not tool.version_args:
                if _store_stub(p):
                    continue
                got = {"where": str(p), "version": ""}
                break
            code, out = s.run([str(p), *tool.version_args], VERSION_TIMEOUT)
            v = parse_version(out)
            if code == 0 and v or (v and tool.id == "java"):
                got = {"where": str(p), "version": v}
                break
            broken = broken or str(p)
    row: dict[str, Any] = {"state": "missing", "version": "", "where": "", "detail": "", "also": []}
    if got:
        row.update({k: v for k, v in got.items() if v is not None})
        row["state"] = "old" if not at_least(row["version"], tool.min_version) else "found"
        if tool.extras:
            row["extras"] = {e: bool(s.which(e) or (Path(row["where"]).parent / e).exists()) for e in tool.extras}
            missing = [e for e, ok in row["extras"].items() if not ok]
            if missing:
                row["detail"] = (row["detail"] + "; " if row["detail"] else "") + f"{' and '.join(missing)} not found"
    elif broken:
        row.update(state="broken", where=broken)
    return row


def install_plan(tool: Tool | str, os_name: str) -> dict[str, Any]:
    """How the Install button installs it here: {can, command (argv), shown, text, admin, reboot, needs, note}."""
    tool = BY_ID[tool] if isinstance(tool, str) else tool
    argv: list[str] = []
    via = ""
    if tool.any_os:
        argv, via = list(tool.any_os), tool.any_os[0]
    elif os_name == "windows" and tool.winget:
        argv, via = ["winget", "install", "--id", tool.winget, *WINGET_FLAGS], "winget"
    elif os_name == "mac" and tool.brew:
        argv, via = ["brew", "install", *tool.brew], "brew"
    plan: dict[str, Any] = {
        "can": bool(argv), "via": via, "command": argv, "shown": " ".join(_quote(a) for a in argv),
        "text": "" if argv else (tool.linux if os_name == "linux" else "There's no automatic install for this here."),
        "admin": bool(argv) and via == "winget" and tool.admin, "reboot": tool.reboot,
        "needs": list(tool.needs), "note": tool.note, "size": tool.size,
    }
    return plan


def _quote(a: str) -> str:
    return f'"{a}"' if " " in a else a


def confirm_words(tool: Tool | str, os_name: str) -> str:
    """What the owner is told before an install that needs permission, a restart or a big download; '' if none."""
    tool = BY_ID[tool] if isinstance(tool, str) else tool
    plan = install_plan(tool, os_name)
    parts = []
    if plan["admin"]:
        parts.append("Windows will ask whether to allow it: press Yes.")
    if plan["reboot"]:
        parts.append("The computer needs a restart afterwards.")
    if plan["size"]:
        parts.append(f"It's a big download ({plan['size']}).")
    if plan["note"]:
        parts.append(plan["note"])
    return " ".join(parts)


_cache: dict[str, Any] = {"at": 0.0, "rows": None, "key": None}
_cache_lock = threading.Lock()
CACHE_SECONDS = 120.0


def status(s: System | None = None, versions: bool = True, godot_path: str | None = None,
           fresh: bool = False) -> list[dict[str, Any]]:
    """Every tool in the catalog: found or missing, how to install it, in the page's order."""
    real = s is None
    s = s or System.here()
    key = (versions, godot_path)
    if real and not fresh:
        with _cache_lock:
            if _cache["rows"] is not None and _cache["key"] == key and time.monotonic() - _cache["at"] < CACHE_SECONDS:
                return [dict(r) for r in _cache["rows"]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(lambda t: find(t, s, versions, godot_path), CATALOG))
    rows = []
    for tool, row in zip(CATALOG, found):
        plan = install_plan(tool, s.os)
        rows.append({"id": tool.id, "name": tool.name, "group": tool.group, "why": tool.why,
                     "min_version": tool.min_version, **row, "install": plan})
    have = {r["id"]: r["state"] in ("found", "old") for r in rows}
    for r in rows:
        waiting = [BY_ID[n].name for n in r["install"]["needs"] if not have.get(n)]
        r["install"]["blocked"] = f"Install {' and '.join(waiting)} first." if waiting else ""
        r["words"] = _row_words(r)
    if real:
        with _cache_lock:
            _cache.update(at=time.monotonic(), rows=[dict(r) for r in rows], key=key)
    return rows


def forget_cache() -> None:
    with _cache_lock:
        _cache.update(at=0.0, rows=None)


def _row_words(r: dict[str, Any]) -> str:
    if r["state"] == "found":
        return f"Found{' · ' + r['version'] if r['version'] else ''}"
    if r["state"] == "old":
        return f"Too old ({r['version']}; needs {r['min_version']} or newer)"
    if r["state"] == "broken":
        return "There, but it didn't start"
    return "Not found"


# -- installing ---------------------------------------------------------------------------------------
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]|\x1b\[[0-9;?]*[A-Za-z]")


def _stream(argv: list[str], timeout: float, line: Line) -> int | None:
    """Run an installer, passing on its output a line at a time (progress bars and spinners trimmed)."""
    from .harness.safeenv import clean_env

    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=clean_env(), text=True, encoding="utf-8", errors="replace", **kw)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    last = ""
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            for piece in raw.split("\r"):
                text = _CONTROL.sub("", piece).strip()
                if len(text) > 2 and text != last and not re.fullmatch(r"[\s\-\\|/█▒░■#=.%0-9KMGBkib]*", text):
                    last = text
                    line(text[:300])
        return proc.wait()
    finally:
        timed_out = not timer.is_alive()
        timer.cancel()
        if timed_out:
            line("It took too long and was stopped.")


def run_install(tool_id: str, line: Line, s: System | None = None,
                stream: Callable[[list[str], float, Line], int | None] = _stream,
                recheck: Callable[[], System] | None = None) -> dict[str, Any]:
    """Install one tool (the owner pressed Install), then look for it again. Returns what the job shows."""
    tool = BY_ID.get(tool_id)
    if not tool:
        raise ValueError("Roundtable doesn't know that tool. Refresh the page and try again.")
    s = s or System.here()
    plan = install_plan(tool, s.os)
    if not plan["can"]:
        raise ValueError(f"{tool.name} can't be installed from the app here. {plan['text']}".strip())
    have = {t: find(t, s, versions=False)["state"] != "missing" for t in plan["needs"]}
    waiting = [BY_ID[t].name for t, ok in have.items() if not ok]
    if waiting:
        raise ValueError(f"Install {' and '.join(waiting)} first, then {tool.name}.")
    program = s.which(plan["command"][0])
    if not program:
        raise ValueError(_no_installer(plan["via"]))
    argv = [str(program), *plan["command"][1:]]
    line(f"Installing {tool.name}: {plan['shown']}")
    code = stream(argv, INSTALL_TIMEOUT, line)
    forget_cache()
    again = find(tool, recheck() if recheck else System.here() if s.root is None else s)
    ok_code = code == 0 or (plan["via"] == "winget" and code in WINGET_ALREADY)
    if again["state"] == "found":
        words = f"{tool.name}{' ' + again['version'] if again['version'] else ''} is ready."
        if plan["note"]:
            words += " " + plan["note"]
    elif ok_code:
        words = (f"It finished, but {tool.name} still isn't found. Close Roundtable Hold and open it again so it "
                 "sees the new program, then press Check again.")
    else:
        words = (f"{tool.name} didn't install (the installer stopped with code {code}). The log above says why; "
                 "press Install to try again.")
    line(words)
    if plan["reboot"] and ok_code:
        line("Restart the computer to finish.")
    return {"tool": tool.id, "ok": again["state"] == "found", "code": code, "words": words, "row": again}


def _no_installer(via: str) -> str:
    return {
        "winget": "Windows' installer (winget) isn't on this PC. Update “App Installer” from the Microsoft Store, "
                  "then try again.",
        "brew": "Homebrew isn't on this Mac. Install it from brew.sh, then try again.",
        "npm": "npm isn't found: install Node.js first (it comes with npm), then try again.",
        "npx": "npx isn't found: install Node.js first (it comes with npx), then try again.",
    }.get(via, "The installer isn't on this computer.")


# -- what projects need -------------------------------------------------------------------------------
def project_needs(root: Path) -> list[str]:
    """The tools a project's files show it needs: a Godot game, an Unreal project, Blender files, an Android app,
    a Node app."""
    from .harness.godot import project_dir

    root = Path(root)
    out: list[str] = []
    if project_dir(root):
        out.append("godot")
    top = _shallow(root, 2)
    if any(p.suffix == ".uproject" for p in top):
        out.append("unreal")
    if any(p.suffix == ".blend" for p in top):
        out.append("blender")
    gradles = [p for p in top if p.name in ("build.gradle", "build.gradle.kts")]
    if any("com.android" in _head(p) for p in gradles):
        out += ["java", "android"]
    if (root / "package.json").is_file():
        out.append("node")
    return out


_SKIP = {".git", ".harness", "node_modules", ".godot", "build", "dist", ".venv", "venv", "__pycache__"}


def _shallow(root: Path, depth: int) -> list[Path]:
    out: list[Path] = []
    try:
        items = list(root.iterdir())
    except OSError:
        return out
    for p in items:
        if p.name in _SKIP:
            continue
        out.append(p)
        if depth > 1 and p.is_dir() and not p.name.startswith("."):
            out += _shallow(p, depth - 1)
    return out


def _head(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return ""


def needs_cards(projects: list[Path], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Needs-you cards: a project needs a tool this computer doesn't have (one card per tool and project)."""
    by_id = {r["id"]: r for r in rows}
    cards = []
    for root in projects:
        root = Path(root)
        for tid in project_needs(root):
            r = by_id.get(tid)
            if not r or r["state"] == "found":
                continue
            what = "is too old" if r["state"] == "old" else "isn't on this computer"
            can = r["install"]["can"] and not r["install"].get("blocked")
            cards.append({"kind": "tool", "project": root.name, "name": root.name, "path": str(root),
                          "tool": tid, "tool_name": r["name"],
                          "text": f"This project needs {r['name']}, which {what}. "
                                  + ("Press Install to add it." if can else
                                     r["install"].get("blocked") or r["install"]["text"]),
                          "actions": ["install"] if can else ["tools"], "at": ""})
    return cards


# -- MCP tool servers ---------------------------------------------------------------------------------
def known_servers(os_name: str) -> list[dict[str, Any]]:
    """The servers offered under Add, with their exact settings (docs/mcp.md, docs/godot.md, docs/unreal.md)."""
    godot = ({"command": "cmd", "args": ["/c", "npx", "-y", "godot-mcp-server"]} if os_name == "windows"
             else {"command": "npx", "args": ["-y", "godot-mcp-server"]})
    return [
        {"id": "unreal", "name": "Unreal MCP", "about": "Lets helpers work inside the open Unreal editor (5.8 or newer).",
         "spec": {"url": "http://127.0.0.1:8000/mcp", "timeout": 300}, "needs": ["unreal"],
         "steps": "In Unreal: Edit → Plugins, tick Unreal MCP and All Toolsets, restart the editor and keep it open. "
                  "If you changed its port, change the address here to match."},
        {"id": "godot", "name": "Godot MCP (Godlink)", "about": "Lets helpers work inside the open Godot editor.",
         "spec": {**godot, "timeout": 180}, "needs": ["node", "godot"],
         "steps": "In Godot: Asset Store, search Godlink, install Godlink MCP, then Project → Project Settings → "
                  "Plugins and tick Godot MCP. Keep the editor open."},
        {"id": "blender", "name": "MCP for Blender", "about": "Lets helpers make and change 3D models in Blender.",
         "spec": {"command": "uvx", "args": ["mcp-for-blender"], "env": {"DISABLE_TELEMETRY": "true"}, "timeout": 300},
         "needs": ["uv", "blender"], "prepare": ["uvx", "mcp-for-blender", "install-addon"],
         "steps": "Press Put it in Blender once. Then in Blender: Edit → Preferences → Add-ons, tick MCP for Blender; "
                  "in the 3D view press N, open the MCP for Blender tab and press Start MCP Server. Save your work "
                  "first: it can run anything inside Blender."},
    ]


def _paths(harness_path: str | Path | None) -> Path:
    from .harness.config import find_config

    try:  # the app's own settings file when it names one, else where the command line looks
        p = Path(harness_path).expanduser() if harness_path else find_config(None)
    except FileNotFoundError:
        p = Path("harness.yaml")
    if not p.is_file():
        raise FileNotFoundError("Roundtable's settings aren't set up on this computer yet. Run the set-up in "
                                "Settings first.")
    return p


def merge_custom_tools(raw: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    """custom.yaml's tool servers on top of harness.yaml: ``mcp_servers`` added (harness.yaml wins on a name
    clash), and ``mcp_roles: {job: [servers]}`` sets which servers each job uses. Names that no longer exist are
    dropped, so a removed server or job never stops Roundtable from starting. Safe to apply twice."""
    if not custom or not (custom.get("mcp_servers") or custom.get("mcp_roles")):
        return raw
    out = dict(raw)
    servers = {**dict(custom.get("mcp_servers") or {}), **dict(raw.get("mcp_servers") or {})}
    if servers:
        out["mcp_servers"] = servers
    picks = custom.get("mcp_roles") or {}
    if isinstance(picks, dict) and picks:
        roles = {k: dict(v or {}) for k, v in (out.get("roles") or {}).items()}
        for role, names in picks.items():
            if role in roles and isinstance(names, list):
                roles[role]["mcp"] = [str(n) for n in names if str(n) in servers]
        out["roles"] = roles
    return out


def _load(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    import yaml

    from .harness.config import load_custom

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, load_custom(path)


def _parsed(path: Path, raw: dict[str, Any], custom: dict[str, Any]):
    from .harness.config import merge_custom, parse_config

    return parse_config(merge_custom_tools(merge_custom(raw, custom), custom), path)


def servers_view(harness_path: str | Path | None) -> dict[str, Any]:
    """The configured servers (with who uses each) and the jobs that can be given one."""
    from .routing import job_name

    path = _paths(harness_path)
    raw, custom = _load(path)
    cfg = _parsed(path, raw, custom)
    mine = set((custom.get("mcp_servers") or {})) - set(raw.get("mcp_servers") or {})
    rows = []
    for name, spec in cfg.mcp_servers.items():
        users = [r.name for r in cfg.roles.values() if name in r.mcp]
        rows.append({"name": name, "where": spec.get("url") or " ".join([spec.get("command", "")] +
                                                                         list(spec.get("args") or [])),
                     "enabled": spec.get("enabled", True), "timeout": spec.get("timeout"),
                     "from": "app" if name in mine else "settings file", "removable": name in mine,
                     "roles": users, "jobs": [job_name(r) for r in users]})
    jobs = [{"role": r.name, "name": job_name(r.name), "servers": list(r.mcp)}
            for r in cfg.roles.values() if r.kind == "chat"]
    return {"servers": rows, "jobs": jobs}


_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _clean_spec(spec: dict[str, Any]) -> dict[str, Any]:
    from .harness.safeenv import is_secret_name

    allowed = ("command", "args", "env", "cwd", "url", "headers", "tools", "timeout", "enabled", "description")
    out = {k: v for k, v in (spec or {}).items() if k in allowed and v not in (None, "", [], {})}
    for key in ("env", "headers"):
        for k in (out.get(key) or {}):
            if is_secret_name(str(k)) or str(k).lower() == "authorization":
                raise ValueError("Keys and passwords can't go in a tool server's settings. Add the key in "
                                 "Settings → Keys, then try again.")
    if isinstance(out.get("args"), str):
        out["args"] = out["args"].split()
    return out


def add_server(harness_path: str | Path | None, name: str = "", spec: dict[str, Any] | None = None,
               known: str = "", os_name: str | None = None) -> dict[str, Any]:
    """Add a tool server (one from the short list, or your own) to custom.yaml, checked first."""
    from .harness.config import save_custom

    path = _paths(harness_path)
    raw, custom = _load(path)
    if known:
        k = next((x for x in known_servers(os_name or System.here().os) if x["id"] == known), None)
        if not k:
            raise ValueError("That isn't one of the servers on the list. Refresh the page and try again.")
        name = name or k["id"]
        spec = {**k["spec"], **(spec or {})}
    name = str(name or "").strip()
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("Give the server a short name: letters, digits, - and _ only (for example blender).")
    if name in (raw.get("mcp_servers") or {}) or name in (custom.get("mcp_servers") or {}):
        raise ValueError(f"There's already a server called {name}. Choose another name, or remove that one first.")
    spec = _clean_spec(spec or {})
    if ("command" in spec) == ("url" in spec):
        raise ValueError("Give either the program to start (for example uvx) or the address it answers at "
                         "(for example http://127.0.0.1:8000/mcp).")
    servers = dict(custom.get("mcp_servers") or {})
    servers[name] = spec
    custom["mcp_servers"] = servers
    try:
        _parsed(path, raw, custom)
    except ValueError as e:
        raise ValueError(f"Nothing was added: {e}.") from None
    save_custom(path, custom)
    return {"name": name, **spec}


def remove_server(harness_path: str | Path | None, name: str) -> dict[str, Any]:
    from .harness.config import save_custom

    path = _paths(harness_path)
    raw, custom = _load(path)
    if name in (raw.get("mcp_servers") or {}):
        raise ValueError(f"{name} is in the settings file (harness.yaml), so it can't be removed here.")
    servers = dict(custom.get("mcp_servers") or {})
    if name not in servers:
        raise ValueError("That server has already gone. Refresh the page.")
    del servers[name]
    custom["mcp_servers"] = servers
    picks = {r: [s for s in v if s != name] for r, v in (custom.get("mcp_roles") or {}).items()}
    if picks:
        custom["mcp_roles"] = picks
    _parsed(path, raw, custom)
    save_custom(path, custom)
    return {"removed": name}


def give_server(harness_path: str | Path | None, name: str, roles: list[str]) -> dict[str, Any]:
    """Which jobs use this server: exactly these (the others stop using it)."""
    from .harness.config import save_custom
    from .routing import job_name

    path = _paths(harness_path)
    raw, custom = _load(path)
    cfg = _parsed(path, raw, custom)
    if name not in cfg.mcp_servers:
        raise ValueError("That server isn't there any more. Refresh the page.")
    roles = [str(r) for r in roles or []]
    for r in roles:
        if r not in cfg.roles:
            raise ValueError(f"There's no {job_name(r)} job. Refresh the page and try again.")
        if cfg.roles[r].kind != "chat":
            raise ValueError(f"{job_name(r)} makes pictures, so it can't use a tool server.")
    picks = dict(custom.get("mcp_roles") or {})
    for r, spec in cfg.roles.items():
        current = list(spec.mcp)
        want = r in roles
        if (name in current) == want:
            continue
        picks[r] = [s for s in current if s != name] + ([name] if want else [])
    custom["mcp_roles"] = picks
    _parsed(path, raw, custom)
    save_custom(path, custom)
    return {"name": name, "roles": roles, "jobs": [job_name(r) for r in roles]}


def test_server(harness_path: str | Path | None, name: str,
                check: Callable[[dict[str, dict[str, Any]]], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Start (or reach) one server and list its tools: {ok, words, tools, error}."""
    from .harness.mcp_tools import check_servers

    path = _paths(harness_path)
    raw, custom = _load(path)
    cfg = _parsed(path, raw, custom)
    spec = cfg.mcp_servers.get(name)
    if not spec:
        raise ValueError("That server isn't there any more. Refresh the page.")
    row = (check or check_servers)({name: {**spec, "enabled": True}})[0]
    tools = [t.split("__", 2)[-1] for t in row.get("tools") or []]
    if row.get("ok"):
        words = f"It answers: {len(tools)} tool{'s' if len(tools) != 1 else ''}."
    else:
        words = row.get("error") or "It didn't answer. Open the program it belongs to, then try again."
    return {"name": name, "ok": bool(row.get("ok")), "words": words, "tools": tools, "error": row.get("error") or ""}


def prepare_server(known: str, line: Line, s: System | None = None,
                   stream: Callable[[list[str], float, Line], int | None] = _stream) -> dict[str, Any]:
    """The one-off step a known server needs on this computer (MCP for Blender: put its add-on into Blender)."""
    s = s or System.here()
    k = next((x for x in known_servers(s.os) if x["id"] == known), None)
    if not k or not k.get("prepare"):
        raise ValueError("That server needs nothing put in place first.")
    program = s.which(k["prepare"][0])
    if not program:
        raise ValueError(f"{k['prepare'][0]} isn't found: install {BY_ID['uv'].name} first, then try again.")
    line("Running: " + " ".join(k["prepare"]))
    code = stream([str(program), *k["prepare"][1:]], 600.0, line)
    words = ("Done. Now open Blender and turn it on (the steps are on the page)." if code == 0 else
             f"It didn't work (code {code}). The log above says why; press it again to retry.")
    line(words)
    return {"ok": code == 0, "code": code, "words": words}
