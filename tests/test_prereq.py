"""The Tools page (prereq.py, ui/toolsapi.py): tools found or missing on made-up computers, versions, the install
command for each system (never run for real), Needs-you cards, and MCP servers added, tested and given to jobs.
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

from roundtable import prereq
from roundtable.prereq import System

FAKE_MCP = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


def prog(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("made up", encoding="utf-8")
    p.chmod(0o755)
    return p


def runner(answers: dict[str, tuple[int | None, str]]):
    """A made-up runner: the answer by program file name (no program is started)."""
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        name = Path(argv[0]).name.lower()
        for key, ans in answers.items():
            if name.startswith(key):
                return ans
        return 127, "not a program"

    run.calls = calls
    return run


def windows(tmp_path, answers=None, path=()):
    env = {"ProgramFiles": str(tmp_path / "Program Files"), "ProgramFiles(x86)": str(tmp_path / "Program Files (x86)"),
           "LOCALAPPDATA": str(tmp_path / "Local"), "APPDATA": str(tmp_path / "Roaming"),
           "ProgramData": str(tmp_path / "ProgramData"), "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
    return System("windows", [Path(p) for p in path], env, tmp_path / "home", root=tmp_path / "root",
                  run=runner(answers or {}))


def posix(tmp_path, os_name="linux", answers=None, path=(), env=None):
    return System(os_name, [Path(p) for p in path], dict(env or {}), tmp_path / "home", root=tmp_path / "root",
                  run=runner(answers or {}))


# -- versions ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, want", [
    ("git version 2.47.1.windows.1", "2.47.1"),
    ("v22.11.0", "22.11.0"),
    ("Python 3.13.1", "3.13.1"),
    ("uv 0.5.11 (c4d0caaee 2024-12-19)", "0.5.11"),
    ('openjdk version "17.0.13" 2024-10-15\nOpenJDK Runtime Environment Temurin', "17.0.13"),
    ('java version "1.8.0_421"', "8.0"),
    ("4.7.stable.official.4a2b6e1", "4.7"),
    ("Blender 4.5.1 LTS\n\tbuild date: 2026-01-01", "4.5.1"),
    ("2.1.3 (Claude Code)", "2.1.3"),
    ("codex-cli 0.58.0", "0.58.0"),
    ("nothing here", ""),
])
def test_version_parsing(text, want):
    assert prereq.parse_version(text) == want


def test_version_compare():
    assert prereq.at_least("4.7", "4.4") and not prereq.at_least("4.3.2", "4.4")
    assert prereq.at_least("17.0.13", "17") and not prereq.at_least("11.0.2", "17")
    assert prereq.at_least("", "5.8")  # unknown version: not called too old


# -- found or missing ----------------------------------------------------------------------------------
def test_windows_layout_found_in_usual_folders_and_on_path(tmp_path):
    pf = tmp_path / "Program Files"
    prog(pf / "Git" / "cmd" / "git.exe")
    bin_dir = tmp_path / "bin"
    prog(bin_dir / "node.exe")
    prog(bin_dir / "npm.cmd")
    prog(tmp_path / "Local" / "Programs" / "Python" / "Python313" / "python.exe")
    s = windows(tmp_path, {"git": (0, "git version 2.47.1.windows.1"), "node": (0, "v22.11.0"),
                           "python": (0, "Python 3.13.1")}, path=[bin_dir])
    git = prereq.find("git", s)
    assert git["state"] == "found" and git["version"] == "2.47.1" and git["where"].endswith("git.exe")
    node = prereq.find("node", s)
    assert node["state"] == "found" and node["version"] == "22.11.0"
    assert node["extras"] == {"npm": True, "npx": False} and "npx not found" in node["detail"]
    assert prereq.find("python", s)["version"] == "3.13.1"
    assert prereq.find("codex", s)["state"] == "missing"


def test_store_python_stub_is_not_python(tmp_path):
    apps = tmp_path / "Local" / "Microsoft" / "WindowsApps"
    prog(apps / "python.exe")
    s = windows(tmp_path, {"python": (9009, "Python was not found; run without arguments to install from the "
                                            "Microsoft Store")}, path=[apps])
    assert prereq.find("python", s)["state"] == "broken"
    assert prereq.find("python", s, versions=False)["state"] == "missing"


def test_posix_layout_and_mac_folders(tmp_path):
    home_bin = tmp_path / "home" / ".local" / "bin"
    prog(home_bin / "uv")
    prog(home_bin / "uvx")
    prog(home_bin / "claude")
    s = posix(tmp_path, "mac", {"uv": (0, "uv 0.5.11 (abc 2024-12-19)"), "claude": (0, "2.1.3 (Claude Code)"),
                                "blender": (0, "Blender 4.5.1"), "godot": (0, "4.3.stable.official")})
    prog(s.at("/Applications/Blender.app/Contents/MacOS/Blender"))
    prog(s.at("/Applications/Godot.app/Contents/MacOS/Godot"))
    uv = prereq.find("uv", s)
    assert uv["state"] == "found" and uv["version"] == "0.5.11" and uv["extras"] == {"uvx": True}
    assert prereq.find("claude", s)["version"] == "2.1.3"
    assert prereq.find("blender", s)["version"] == "4.5.1"
    godot = prereq.find("godot", s)
    assert godot["state"] == "old" and godot["version"] == "4.3"


def test_godot_setting_comes_first(tmp_path):
    mine = prog(tmp_path / "mine" / "Godot_v4.7-stable_linux.x86_64")
    s = posix(tmp_path, answers={"godot": (0, "4.7.stable.official")})
    got = prereq.find("godot", s, godot_path=str(mine))
    assert got["state"] == "found" and got["where"] == str(mine)
    assert prereq.find("godot", s)["state"] == "missing"


def test_godot_windows_usual_place(tmp_path):
    exe = prog(tmp_path / "home" / "Godot" / "Godot_v4.7-stable_win64_console.exe")
    s = windows(tmp_path, {"godot": (0, "4.7.stable.official")})
    assert prereq.find("godot", s)["where"] == str(exe)


def test_android_sdk_and_java(tmp_path):
    sdk = tmp_path / "Local" / "Android" / "Sdk"
    (sdk / "platform-tools").mkdir(parents=True)
    (sdk / "build-tools" / "34.0.0").mkdir(parents=True)
    (sdk / "build-tools" / "35.0.0").mkdir(parents=True)
    (sdk / "platforms" / "android-35").mkdir(parents=True)
    prog(tmp_path / "Program Files" / "Eclipse Adoptium" / "jdk-17.0.13.11-hotspot" / "bin" / "java.exe")
    s = windows(tmp_path, {"java": (0, 'openjdk version "17.0.13" 2024-10-15')})
    a = prereq.find("android", s)
    assert a["state"] == "found" and a["version"] == "35.0.0" and "Android 35" in a["detail"]
    assert prereq.find("java", s)["version"] == "17.0.13"
    s2 = posix(tmp_path, env={"ANDROID_HOME": str(tmp_path / "nowhere")})
    assert prereq.find("android", s2)["state"] == "missing"


def test_old_java_is_too_old(tmp_path):
    jh = tmp_path / "jdk11"
    prog(jh / "bin" / "java")
    s = posix(tmp_path, answers={"java": (1, 'openjdk version "11.0.2"')}, env={"JAVA_HOME": str(jh)})
    assert prereq.find("java", s)["state"] == "old"


def test_unreal_from_the_launchers_list_and_folders(tmp_path):
    a = tmp_path / "Program Files" / "Epic Games" / "UE_5.8"
    (a / "Engine" / "Build").mkdir(parents=True)
    (a / "Engine" / "Build" / "Build.version").write_text(json.dumps({"MajorVersion": 5, "MinorVersion": 8,
                                                                      "PatchVersion": 1}))
    prog(a / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe")
    b = tmp_path / "D" / "Epic" / "UE_5.6"
    (b / "Engine").mkdir(parents=True)
    dat = tmp_path / "ProgramData" / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    dat.parent.mkdir(parents=True)
    dat.write_text(json.dumps({"InstallationList": [{"AppName": "UE_5.6", "InstallLocation": str(b)},
                                                    {"AppName": "Fortnite", "InstallLocation": str(tmp_path)}]}))
    got = prereq.find("unreal", windows(tmp_path))
    assert got["state"] == "found" and got["version"] == "5.8.1" and got["where"].endswith("UnrealEditor.exe")
    assert got["also"] == [f"5.6 in {b}"]
    mac = posix(tmp_path, "mac")
    (mac.at("/Users/Shared/Epic Games/UE_5.7/Engine")).mkdir(parents=True)
    assert prereq.find("unreal", mac)["state"] == "old"


def test_playwright_browser(tmp_path):
    s = posix(tmp_path)
    assert prereq.find("playwright", s)["state"] == "missing"
    (tmp_path / "home" / ".cache" / "ms-playwright" / "chromium-1148").mkdir(parents=True)
    got = prereq.find("playwright", s)
    assert got["state"] == "found" and "1148" in got["detail"]
    w = windows(tmp_path)
    (tmp_path / "Local" / "ms-playwright" / "chromium_headless_shell-1150").mkdir(parents=True)
    assert prereq.find("playwright", w)["state"] == "found"


def test_status_lists_everything_with_words_and_blocks(tmp_path):
    rows = prereq.status(posix(tmp_path))
    ids = [r["id"] for r in rows]
    assert ids == ["git", "node", "python", "uv", "playwright", "java", "android", "godot", "unreal", "blender",
                   "claude", "codex"]
    by = {r["id"]: r for r in rows}
    assert all(r["state"] == "missing" and r["words"] == "Not found" for r in rows)
    assert by["claude"]["install"]["blocked"] == "Install Node.js first."
    assert by["git"]["install"]["can"] is False and by["git"]["install"]["text"] == "sudo apt install git"
    assert set(r["group"] for r in rows) <= set(prereq.GROUPS)


# -- install commands (never run for real) --------------------------------------------------------------
def test_install_command_per_system():
    w = prereq.install_plan("git", "windows")
    assert w["command"] == ["winget", "install", "--id", "Git.Git", "-e", "--silent", "--accept-package-agreements",
                            "--accept-source-agreements"]
    assert w["admin"] is True and w["can"]
    assert prereq.install_plan("uv", "windows")["admin"] is False
    ids = {t: prereq.install_plan(t, "windows")["command"][3] for t in
           ("node", "python", "uv", "java", "android", "godot", "unreal", "blender")}
    assert ids == {"node": "OpenJS.NodeJS.LTS", "python": "Python.Python.3.13", "uv": "astral-sh.uv",
                   "java": "EclipseAdoptium.Temurin.17.JDK", "android": "Google.AndroidStudio",
                   "godot": "GodotEngine.GodotEngine", "unreal": "EpicGames.EpicGamesLauncher",
                   "blender": "BlenderFoundation.Blender"}
    assert prereq.install_plan("blender", "mac")["command"] == ["brew", "install", "--cask", "blender"]
    assert prereq.install_plan("git", "mac")["command"] == ["brew", "install", "git"]
    lin = prereq.install_plan("godot", "linux")
    assert lin["can"] is False and "flatpak" in lin["text"]
    for os_name in ("windows", "mac", "linux"):
        assert prereq.install_plan("claude", os_name)["command"] == ["npm", "install", "-g", "@anthropic-ai/claude-code"]
        assert prereq.install_plan("codex", os_name)["command"] == ["npm", "install", "-g", "@openai/codex"]
        assert prereq.install_plan("playwright", os_name)["command"][:2] == ["npx", "-y"]
    assert "Windows will ask" in prereq.confirm_words("unreal", "windows") and "60 GB" in prereq.confirm_words("unreal", "windows")
    assert prereq.confirm_words("uv", "windows") == ""


def test_run_install_streams_then_checks_again(tmp_path):
    prog(tmp_path / "Local" / "Microsoft" / "WinGet" / "Links" / "winget.exe")
    s = windows(tmp_path, {"uv": (0, "uv 0.6.0")})
    ran = []

    def stream(argv, timeout, line):
        ran.append(argv)
        line("Found uv [astral-sh.uv]")
        prog(tmp_path / "home" / ".local" / "bin" / "uv.exe")  # what the installer would leave
        return 0

    lines = []
    out = prereq.run_install("uv", lines.append, s=s, stream=stream, recheck=lambda: s)
    assert ran[0][0].endswith("winget.exe") and ran[0][1:4] == ["install", "--id", "astral-sh.uv"]
    assert out["ok"] and out["words"] == "uv 0.6.0 is ready."
    assert lines[0].startswith("Installing uv: winget install --id astral-sh.uv") and lines[-1] == out["words"]


def test_run_install_says_what_to_do(tmp_path):
    s = windows(tmp_path)
    with pytest.raises(ValueError, match="winget"):
        prereq.run_install("uv", print, s=s, stream=lambda *a: 0)
    with pytest.raises(ValueError, match="Install Node.js first"):
        prereq.run_install("claude", print, s=s, stream=lambda *a: 0)
    with pytest.raises(ValueError, match="apt"):
        prereq.run_install("git", print, s=posix(tmp_path), stream=lambda *a: 0)
    prog(tmp_path / "bin" / "winget.exe")
    s2 = windows(tmp_path, path=[tmp_path / "bin"])
    out = prereq.run_install("blender", lambda _: None, s=s2, stream=lambda *a: 1, recheck=lambda: s2)
    assert not out["ok"] and "code 1" in out["words"]
    out = prereq.run_install("blender", lambda _: None, s=s2, stream=lambda *a: -1978335189, recheck=lambda: s2)
    assert "Close Roundtable Hold and open it again" in out["words"]


# -- Needs you ------------------------------------------------------------------------------------------
def test_needs_cards_for_projects_missing_a_tool(tmp_path):
    game = tmp_path / "space-game"
    (game / "game").mkdir(parents=True)
    (game / "game" / "project.godot").write_text('config/name="Space"')
    (game / "art").mkdir()
    (game / "art" / "ship.blend").write_text("x")
    app = tmp_path / "phone-app"
    (app / "app").mkdir(parents=True)
    (app / "app" / "build.gradle.kts").write_text('plugins { id("com.android.application") }')
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    assert prereq.project_needs(game) == ["godot", "blender"]
    assert prereq.project_needs(app) == ["java", "android"]
    rows = prereq.status(posix(tmp_path))
    for r in rows:
        if r["id"] == "node":
            r["state"] = "found"
    cards = prereq.needs_cards([game, app, web], rows)
    assert [(c["project"], c["tool"]) for c in cards] == [("space-game", "godot"), ("space-game", "blender"),
                                                          ("phone-app", "java"), ("phone-app", "android")]
    c = cards[0]
    assert c["kind"] == "tool" and c["text"].startswith("This project needs Godot, which isn't on this computer.")
    assert c["actions"] == ["tools"]  # Linux: no Install button, so it points at the Tools page's words
    win_rows = prereq.status(windows(tmp_path))
    assert prereq.needs_cards([game], win_rows)[0]["actions"] == ["install"]


# -- MCP servers -----------------------------------------------------------------------------------------
@pytest.fixture
def lab(tmp_path):
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump({
        "providers": {"a": {"type": "scripted"}},
        "roles": {"orchestrator": {"model": "a/planner"}, "coder": {"model": "a/coder"},
                  "reviewer": {"model": "a/reviewer"}, "artist": {"model": "a/pic", "kind": "image"}},
        "mcp_servers": {"unreal": {"url": "http://127.0.0.1:8000/mcp"}},
    }))
    return path


def test_known_servers_have_the_documented_commands():
    win = {k["id"]: k for k in prereq.known_servers("windows")}
    assert win["unreal"]["spec"]["url"] == "http://127.0.0.1:8000/mcp"
    assert win["godot"]["spec"]["command"] == "cmd" and win["godot"]["spec"]["args"] == ["/c", "npx", "-y", "godot-mcp-server"]
    assert win["blender"]["spec"] == {"command": "uvx", "args": ["mcp-for-blender"], "env": {"DISABLE_TELEMETRY": "true"},
                                      "timeout": 300}
    mac = {k["id"]: k for k in prereq.known_servers("mac")}
    assert mac["godot"]["spec"]["command"] == "npx"


def test_add_test_give_round_trip_with_the_fake_server(lab):
    out = prereq.add_server(lab, name="editor", spec={"command": sys.executable, "args": [FAKE_MCP], "timeout": 60})
    assert out["name"] == "editor"
    custom = yaml.safe_load((lab.parent / "custom.yaml").read_text())
    assert custom["mcp_servers"]["editor"]["command"] == sys.executable
    assert "editor" not in yaml.safe_load(lab.read_text()).get("mcp_servers", {})  # harness.yaml untouched
    v = prereq.servers_view(lab)
    rows = {r["name"]: r for r in v["servers"]}
    assert rows["editor"]["removable"] and not rows["unreal"]["removable"] and rows["unreal"]["from"] == "settings file"
    assert {j["role"] for j in v["jobs"]} == {"orchestrator", "coder", "reviewer"}  # the picture job can't use one

    t = prereq.test_server(lab, "editor")
    assert t["ok"] and "spawn_actor" in t["tools"] and t["words"].startswith("It answers: ")

    g = prereq.give_server(lab, "editor", ["coder", "reviewer"])
    assert g["jobs"] == ["Coder", "Reviewer"]
    cfg = prereq._parsed(lab, *prereq._load(lab))
    assert cfg.roles["coder"].mcp == ["editor"] and cfg.roles["orchestrator"].mcp == []
    prereq.give_server(lab, "unreal", ["coder"])
    prereq.give_server(lab, "editor", ["reviewer"])
    cfg = prereq._parsed(lab, *prereq._load(lab))
    assert cfg.roles["coder"].mcp == ["unreal"] and cfg.roles["reviewer"].mcp == ["editor"]
    with pytest.raises(ValueError, match="makes pictures"):
        prereq.give_server(lab, "editor", ["artist"])

    prereq.remove_server(lab, "editor")
    cfg = prereq._parsed(lab, *prereq._load(lab))
    assert "editor" not in cfg.mcp_servers and cfg.roles["reviewer"].mcp == []
    with pytest.raises(ValueError, match="settings file"):
        prereq.remove_server(lab, "unreal")


def test_a_server_that_fails_says_what_to_do(lab):
    prereq.add_server(lab, name="gone", spec={"command": sys.executable, "args": [str(lab.parent / "missing.py")],
                                              "timeout": 20})
    t = prereq.test_server(lab, "gone")
    assert not t["ok"] and "couldn't be started" in t["words"] and "try again" in t["words"]


def test_add_refuses_clashes_bad_names_and_keys(lab):
    prereq.add_server(lab, known="blender", os_name="windows")
    assert yaml.safe_load((lab.parent / "custom.yaml").read_text())["mcp_servers"]["blender"]["command"] == "uvx"
    with pytest.raises(ValueError, match="already a server"):
        prereq.add_server(lab, known="blender", os_name="windows")
    with pytest.raises(ValueError, match="already a server"):
        prereq.add_server(lab, known="unreal")
    with pytest.raises(ValueError, match="short name"):
        prereq.add_server(lab, name="no spaces", spec={"command": "uvx"})
    with pytest.raises(ValueError, match="Settings → Keys"):
        prereq.add_server(lab, name="x", spec={"command": "uvx", "env": {"SOME_API_KEY": "abc"}})
    with pytest.raises(ValueError, match="Settings → Keys"):
        prereq.add_server(lab, name="y", spec={"url": "http://127.0.0.1:1/mcp", "headers": {"Authorization": "x"}})
    with pytest.raises(ValueError, match="either the program"):
        prereq.add_server(lab, name="z", spec={})


def test_merge_custom_tools_never_breaks_on_stale_names():
    raw = {"roles": {"coder": {"model": "a/b", "mcp": ["unreal"]}}, "mcp_servers": {"unreal": {"url": "http://x/mcp"}}}
    custom = {"mcp_servers": {"unreal": {"command": "evil"}, "mine": {"command": "uvx"}},
              "mcp_roles": {"coder": ["mine", "deleted"], "gone_job": ["mine"]}}
    out = prereq.merge_custom_tools(raw, custom)
    assert out["mcp_servers"]["unreal"] == {"url": "http://x/mcp"}  # harness.yaml wins
    assert out["roles"]["coder"]["mcp"] == ["mine"] and "gone_job" not in out["roles"]
    assert prereq.merge_custom_tools(out, custom) == out  # twice is the same
    assert prereq.merge_custom_tools(raw, {}) is raw


def _config_merges_tools() -> bool:
    from roundtable.harness.config import merge_custom

    return "mine" in (merge_custom({}, {"mcp_servers": {"mine": {"command": "uvx"}}}).get("mcp_servers") or {})


@pytest.mark.skipif(not _config_merges_tools(), reason="config.merge_custom doesn't call prereq.merge_custom_tools yet")
def test_runs_see_the_apps_servers(lab):
    from roundtable.harness.config import load_config

    prereq.add_server(lab, name="editor", spec={"command": "uvx", "args": ["x"]})
    prereq.give_server(lab, "editor", ["coder"])
    assert load_config(str(lab)).roles["coder"].mcp == ["editor"]


# -- the API ---------------------------------------------------------------------------------------------
class FakeJobs:
    def __init__(self):
        self.started = []

    def start(self, kind, title, fn, target=""):
        self.started.append((kind, title, target))

        class J:
            def view(self):
                return {"id": "j1", "kind": kind, "title": title}
        return J()


class FakeApp:
    def __init__(self, harness, projects=()):
        self.harness_config_path = str(harness) if harness else None
        self.jobs = FakeJobs()
        self._projects = list(projects)

    def cfg(self):
        return None

    def _lab_projects(self):
        return self._projects


@pytest.fixture
def made_up_computer(tmp_path, monkeypatch):
    s = posix(tmp_path, "windows")
    s.os = "windows"
    s.env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    monkeypatch.setattr(prereq.System, "here", classmethod(lambda cls: s))
    prereq.forget_cache()
    yield s
    prereq.forget_cache()


def test_api_shapes(lab, made_up_computer):
    from roundtable.ui import toolsapi

    app = FakeApp(lab)
    r = toolsapi.routes(app)
    assert set(r) >= {("GET", "/api/tools"), ("POST", "/api/tools/install"), ("POST", "/api/tools/servers/add"),
                      ("POST", "/api/tools/servers/test"), ("POST", "/api/tools/servers/give"),
                      ("POST", "/api/tools/servers/remove"), ("POST", "/api/tools/check")}
    v = r[("GET", "/api/tools")]({})
    assert v["os"] == "windows" and len(v["tools"]) == len(prereq.CATALOG) and v["groups"] == prereq.GROUPS
    t0 = v["tools"][0]
    assert {"id", "name", "group", "why", "state", "words", "version", "where", "install"} <= set(t0)
    assert {"can", "shown", "admin", "blocked", "text"} <= set(t0["install"])
    assert [s["name"] for s in v["servers"]] == ["unreal"] and v["servers_error"] == ""
    assert {k["id"] for k in v["known"]} == {"unreal", "godot", "blender"}
    assert next(k for k in v["known"] if k["id"] == "unreal")["added"] is True
    assert all("spec" not in k for k in v["known"])

    # an install that needs permission asks first; nothing starts until the owner says yes
    first = r[("POST", "/api/tools/install")]({"tool": "git"})
    assert "Windows will ask" in first["confirm"] and app.jobs.started == []
    job = r[("POST", "/api/tools/install")]({"tool": "git", "confirm": True})
    assert job["kind"] == "install" and app.jobs.started == [("install", "install Git", "install:git")]
    r[("POST", "/api/tools/install")]({"tool": "uv"})  # no permission needed: starts at once
    assert app.jobs.started[-1][2] == "install:uv"

    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError):
        r[("POST", "/api/tools/install")]({"tool": "nope"})
    added = r[("POST", "/api/tools/servers/add")]({"known": "godot"})
    assert added["added"] == "godot" and added["command"] == "cmd"
    with pytest.raises(ApiError, match="already"):
        r[("POST", "/api/tools/servers/add")]({"known": "godot"})
    given = r[("POST", "/api/tools/servers/give")]({"name": "godot", "roles": ["coder"]})
    assert given["jobs"] == ["Coder"]
    assert r[("POST", "/api/tools/servers/remove")]({"name": "godot"}) == {"removed": "godot"}


def test_api_without_settings_and_needs(tmp_path, made_up_computer):
    from roundtable.ui import toolsapi

    game = tmp_path / "game"
    game.mkdir()
    (game / "project.godot").write_text("")
    app = FakeApp(tmp_path / "missing.yaml", projects=[game])
    v = toolsapi.view(app)
    assert v["servers"] == [] and "set-up" in v["servers_error"]
    cards = toolsapi.needs(app)
    assert [c["tool"] for c in cards] == ["godot"] and cards[0]["actions"] == ["install"]
