"""Backups: what goes in, what never does, locking, pruning, Drive detection, restore, daily."""

import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from roundtable import backup as bk
from roundtable.desktop import Paths

PROJECT_FILES = {
    "project.json": '{"goal": "a bakery site"}',
    "plan.json": '{"steps": ["menu", "contact page"]}',
    "plan.md": "# Plan\n\n1. Menu\n",
    "tasks.json": '[{"id": "T1", "status": "done"}]',
    "metrics.jsonl": '{"task": "T1", "cost": 0.01}\n',
    "events.jsonl": '{"event": "task_start", "task": "T1"}\n',
    "spend.jsonl": '{"usd": 0.01}\n',
    "split.json": "{}",
}


@pytest.fixture
def world(tmp_path):
    """A made-up app folder, lab and two projects."""
    home = Path(os.environ["ROUNDTABLE_HOME"])
    cfg = home / "config"
    cfg.mkdir(parents=True)
    (cfg / "harness.yaml").write_text(yaml.safe_dump({"providers": {"ds": {"type": "openai_compat",
                                                                           "api_key_env": "DEEPSEEK_API_KEY"}}}), encoding="utf-8")
    (cfg / "custom.yaml").write_text("roles:\n  coder:\n    model: ds/chat\n", encoding="utf-8")
    (cfg / "hub.yaml").write_text(yaml.safe_dump({"storage": {"type": "file", "path": str(home / "hub-data")}}), encoding="utf-8")
    (cfg / "app.json").write_text(json.dumps({"setup_done": True}), encoding="utf-8")
    (cfg / "keys.json").write_text(json.dumps({"DEEPSEEK_API_KEY": "not-a-real-key"}), encoding="utf-8")
    (home / "hub-path").write_text(str(cfg / "hub.yaml"), encoding="utf-8")
    (home / "phone.json").write_text(json.dumps({"devices": [{"id": "d1", "name": "Pixel", "token_sha256": "ab" * 32}]}), encoding="utf-8")
    (home / "phone-key.pem").write_text("-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    (home / "hub-data" / "journal").mkdir(parents=True)
    (home / "hub-data" / "journal" / "me.jsonl").write_text('{"text": "remember the logo"}\n', encoding="utf-8")
    lab = cfg / ".harness-lab"
    (lab / "proposals").mkdir(parents=True)
    (lab / "versions" / "0001").mkdir(parents=True)
    (lab / "learned.yaml").write_text("roles:\n  coder:\n    model: ds/chat\n", encoding="utf-8")
    (lab / "proposals" / "P1.json").write_text('{"id": "P1"}', encoding="utf-8")
    (lab / "versions" / "0001" / "meta.json").write_text('{"v": 1}', encoding="utf-8")
    (lab / "probes.jsonl").write_text('{"model": "ds/chat", "passed": 3}\n', encoding="utf-8")
    with open(lab / "huge.bin", "wb") as f:  # big and rebuildable: left out
        f.truncate(bk.MAX_FILE + 1)
    projects = []
    for name in ("bakery", "garden"):
        root = tmp_path / "projects" / name
        hdir = root / ".harness"
        for sub in ("spill", "scratch", "references", "look"):
            (hdir / sub).mkdir(parents=True)
        for fname, text in PROJECT_FILES.items():
            (hdir / fname).write_text(text.replace("bakery", name), encoding="utf-8")
        (hdir / "spill" / "out.txt").write_text("long output", encoding="utf-8")
        (hdir / "scratch" / "smoke.mjs").write_text("// throwaway", encoding="utf-8")
        (hdir / "references" / "theirs.html").write_text("<p>someone else's</p>", encoding="utf-8")
        (hdir / "look" / "a.png").write_bytes(b"\x89PNG fake picture")
        (root / "index.html").write_text(f"<h1>{name}</h1>", encoding="utf-8")
        projects.append(root)
    (lab / "projects.json").write_text(json.dumps([str(p.resolve()) for p in projects]), encoding="utf-8")
    src = bk.find_sources(str(cfg / "harness.yaml"), str(cfg / "hub.yaml"), home)
    return SimpleNamespace(home=home, lab=lab, projects=projects, src=src, dest=tmp_path / "My Drive" / bk.FOLDER_NAME)


def _names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_finds_what_to_back_up(world):
    assert world.src.lab == world.lab.resolve() or world.src.lab == world.lab
    assert [p.name for p in world.src.projects] == ["bakery", "garden"]
    assert world.src.hub_data == world.home / "hub-data"


def test_backup_and_restore_round_trip(world):
    res = bk.make_backup(world.dest, world.src)
    assert bk.re.match(bk.BACKUP_RE.format(host=bk.host_name()), res.path.name)
    names = _names(res.path)
    assert {"manifest.json", "app/config/app.json", "app/config/harness.yaml", "app/config/custom.yaml",
            "app/hub-path", "app/phone.json", "lab/learned.yaml", "lab/proposals/P1.json", "lab/probes.jsonl",
            "lab/versions/0001/meta.json", "hub-data/journal/me.jsonl",
            "project-1/.harness/plan.json", "project-2/.harness/look/a.png"} <= names
    assert not any(x in n for n in names for x in ("spill", "scratch", "references", "keys.json", "phone-key",
                                                    "huge.bin", "index.html"))
    manifest = json.loads(zipfile.ZipFile(res.path).read("manifest.json"))
    assert any(s["path"] == "lab/huge.bin" and "20 MB" in s["reason"] for s in manifest["skipped"])
    assert all(len(f["sha256"]) == 64 and f["size"] >= 0 for f in manifest["files"])
    assert bk.PHONE_NOTE in manifest["notes"]

    before = {p.name: _snapshot(p / ".harness") for p in world.projects}
    lab_before = _snapshot(world.lab)
    shutil.rmtree(world.projects[0])  # a project folder lost
    (world.projects[1] / ".harness" / "tasks.json").write_text("[]", encoding="utf-8")  # another one changed
    (world.lab / "learned.yaml").write_text("broken", encoding="utf-8")

    done = bk.restore(res.path, yes=True, home=world.home, sources=bk.find_sources(
        str(world.home / "config" / "harness.yaml"), str(world.home / "config" / "hub.yaml"), world.home),
        log=lambda s: None)
    assert done.safety and done.safety.name.endswith("-before-restore.zip") and done.safety.parent == world.dest
    for p in world.projects:
        after = _snapshot(p / ".harness")
        kept = {k: v for k, v in before[p.name].items() if not k.startswith(("spill/", "scratch/", "references/"))}
        if p == world.projects[0]:
            assert after == kept  # recreated: plans, tasks, metrics and pictures; nothing rebuildable
        else:
            assert after == before[p.name]  # put back; its own spill/scratch untouched
    lab_after = _snapshot(world.lab)
    assert lab_after["learned.yaml"] == lab_before["learned.yaml"]
    assert bk.KEYS_NOTE in done.notes and bk.PHONE_NOTE in done.notes


def test_code_goes_in_only_with_code(world, tmp_path):
    root = world.projects[0]
    for cmd in (["init", "-q", "-b", "main"], ["add", "index.html"],
                ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "start"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)
    plain = bk.make_backup(world.dest, world.src)
    assert not any(n.startswith("code/") for n in _names(plain.path))
    full = bk.make_backup(world.dest, world.src, with_code=True)
    assert "code/project-1.bundle" in _names(full.path)
    from roundtable.core.files import remove_tree

    remove_tree(root)  # git's objects are read-only on Windows
    bk.restore(full.path, yes=True, home=world.home, sources=world.src, log=lambda s: None)
    assert (root / "index.html").read_text(encoding="utf-8") == "<h1>bakery</h1>" and (root / ".git").is_dir()
    assert (root / ".harness" / "plan.json").is_file()


def test_a_file_with_a_key_is_refused_and_named(world):
    leak = world.lab / "notes.txt"
    leak.write_text("use sk-abcdefghijklmnopqrstuvwxyz0123456789 for now", encoding="utf-8")
    (world.lab / ".env").write_text("X=1", encoding="utf-8")
    res = bk.make_backup(world.dest, world.src)
    names = _names(res.path)
    assert "lab/notes.txt" not in names and "lab/.env" not in names
    refused = {Path(r["path"]).name: r["reason"] for r in res.refused}
    assert "API key" in refused["notes.txt"] and ".env" in refused[".env"]
    assert "notes.txt" in res.message()


@pytest.mark.parametrize("name,text,bad", [
    ("harness.yaml", "api_key_env: DEEPSEEK_API_KEY\n", False),
    ("harness.yaml", "api_key: proxy-injected\n", False),
    ("harness.yaml", "api_key: ${DEEPSEEK_API_KEY}\n", False),
    ("harness.yaml", "api_key: 9f8e7d6c5b4a39281706\n", True),
    ("app.json", '{"password": "hunter2hunter2hunter2"}', True),
    ("events.jsonl", '{"tokens": 1200, "max_tokens": 4000}', False),
    ("notes.md", "AKIAABCDEFGHIJKLMNOP", True),
    ("notes.md", "ghp_" + "a" * 36, True),
    ("notes.md", "github_pat_" + "a" * 30, True),
    ("notes.md", "xoxb-1234567890-abc", True),
    ("notes.md", "sk-or-v1-" + "0" * 40, True),
    ("key.txt", "-----BEGIN OPENSSH PRIVATE KEY-----", True),
    ("plan.md", "Ask the user for their password on the login screen.", False),
])
def test_secret_check(name, text, bad):
    assert bool(bk.secret_reason(Path(name), text.encode())) is bad


def test_locked_backup_round_trip_and_wrong_passphrase(world):
    res = bk.make_backup(world.dest, world.src, passphrase="correct horse")
    assert res.path.name.endswith(".zip.enc")
    blob = res.path.read_bytes()
    assert blob.startswith(bk.MAGIC) and b"plan.json" not in blob
    with pytest.raises(bk.BackupError, match="locked with a passphrase"):
        bk.open_backup(res.path)
    with pytest.raises(bk.BackupError, match="passphrase doesn't open"):
        bk.open_backup(res.path, "wrong horse")
    opened = bk.open_backup(res.path, "correct horse")
    assert opened.manifest["encrypted"] and "project-1/.harness/tasks.json" in opened.zf.namelist()


def test_keep_n_only_touches_this_computers_backups(tmp_path):
    host = bk.host_name()
    dest = tmp_path / "d"
    dest.mkdir()
    mine = []
    for i in range(5):
        p = dest / f"roundtable-backup-{host}-2026-11-2{i}-0900.zip"
        p.write_text("x", encoding="utf-8")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
        mine.append(p)
    others = [dest / "roundtable-backup-otherpc-2026-11-01-0900.zip", dest / "holiday.jpg",
              dest / f"roundtable-backup-{host}-2026-11-01-0900-before-restore.zip"]
    for p in others:
        p.write_text("keep me", encoding="utf-8")
    removed = bk.prune(dest, keep=2)
    assert sorted(removed) == sorted(mine[:3])
    assert all(p.exists() for p in mine[3:] + others)


def test_finds_google_drive_folders(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for letter in "EG":
        (tmp_path / letter).mkdir()
    (tmp_path / "G" / "My Drive").mkdir()
    monkeypatch.setattr(bk, "_windows_roots", lambda: [tmp_path / "E", tmp_path / "G"])
    assert bk.find_drive_folders(home, "win32") == [tmp_path / "G" / "My Drive"]
    assert bk.find_drive_folders(home, "linux") == []  # drive letters only on Windows
    mac = home / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com" / "My Drive"
    mac.mkdir(parents=True)
    assert bk.find_drive_folders(home, "darwin") == [mac]
    old = home / "Google Drive"
    old.mkdir()
    assert bk.find_drive_folders(home, "linux") == [old]
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [mac])
    assert bk.resolve_destination({"to": "auto"}) == mac / bk.FOLDER_NAME
    assert bk.resolve_destination({"to": str(tmp_path / "usb")}) == tmp_path / "usb"
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    assert bk.resolve_destination({"to": "auto"}) is None
    with pytest.raises(bk.BackupError, match="Google Drive for desktop"):
        bk.backup_now(home=tmp_path / "apphome", sources=bk.Sources(home=tmp_path / "apphome"))


def test_restore_asks_first_and_saves_a_safety_backup(world):
    res = bk.make_backup(world.dest, world.src)
    (world.lab / "learned.yaml").write_text("changed since", encoding="utf-8")
    asked = []
    out = bk.restore(res.path, confirm=lambda lines: asked.append(lines) or False, home=world.home,
                     sources=world.src, log=lambda s: None)
    assert out.cancelled and asked and any("replace" in line for line in asked[0])
    assert (world.lab / "learned.yaml").read_text(encoding="utf-8") == "changed since"
    assert [b["name"] for b in bk.list_backups(world.dest)] == [res.path.name]  # no safety backup either
    out = bk.restore(res.path, confirm=lambda lines: True, home=world.home, sources=world.src, log=lambda s: None)
    safety = bk.open_backup(out.safety)
    assert safety.zf.read("lab/learned.yaml") == b"changed since"  # what was here first is kept
    assert (world.lab / "learned.yaml").read_text(encoding="utf-8") != "changed since"


def test_damaged_backup_is_refused(world):
    res = bk.make_backup(world.dest, world.src)
    raw = res.path.read_bytes()
    res.path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(bk.BackupError, match="damaged"):
        bk.restore(res.path, yes=True, home=world.home, sources=world.src)


def test_daily_backup_once_a_day_and_not_during_a_job(world):
    bk.save_settings(world.home, to=str(world.dest), keep=5)
    day = datetime(2026, 11, 26, 10, 0)
    assert bk.run_daily(world.home, busy=True, sources=lambda: world.src, now=day) is None
    assert not bk.list_backups(world.dest)
    msg = bk.run_daily(world.home, sources=lambda: world.src, now=day)
    assert msg and msg.startswith("Backed up")
    assert bk.run_daily(world.home, sources=lambda: world.src, now=day + timedelta(hours=3)) is None
    assert len(bk.list_backups(world.dest)) == 1
    assert bk.run_daily(world.home, sources=lambda: world.src, now=day + timedelta(days=1))
    assert len(bk.list_backups(world.dest)) == 2
    bk.save_settings(world.home, daily=False)
    assert bk.run_daily(world.home, sources=lambda: world.src, now=day + timedelta(days=2)) is None
    assert bk.feed_items(world.home)[0]["kind"] == "backup"


def test_daily_backup_skips_when_locked_and_no_passphrase(world):
    bk.save_settings(world.home, to=str(world.dest), encrypt=True)
    bk.remember_passphrase(None)
    msg = bk.run_daily(world.home, sources=lambda: world.src, now=datetime(2026, 11, 26, 9))
    assert "passphrase" in msg and not bk.list_backups(world.dest)
    assert "passphrase" in bk.load_state(world.home)["last_error"]
    bk.remember_passphrase("in memory only")
    try:
        assert bk.run_daily(world.home, sources=lambda: world.src, now=datetime(2026, 11, 27, 9))
        assert bk.list_backups(world.dest)[0]["locked"]
        assert "in memory only" not in (world.home / "config" / "app.json").read_text(encoding="utf-8")
    finally:
        bk.remember_passphrase(None)


def test_app_tick_runs_the_daily_backup_but_not_during_a_project_job(world):
    from roundtable.ui.roundtable import AutoSync
    from roundtable.ui.server import Job, Jobs

    bk.save_settings(world.home, to=str(world.dest))
    app = SimpleNamespace(hub=None, desktop={"paths": Paths(world.home)}, jobs=Jobs(),
                          harness_config_path=str(world.home / "config" / "harness.yaml"),
                          hub_config_path=str(world.home / "config" / "hub.yaml"))
    job = Job("j1", "run", "run bakery", target="bakery")
    app.jobs.jobs["j1"] = job
    AutoSync(app).tick()
    assert not bk.list_backups(world.dest)
    job.status = "done"
    AutoSync(app).tick()
    assert len(bk.list_backups(world.dest)) == 1 and app.backup_message.startswith("Backed up")


def test_a_failing_daily_backup_never_raises(world, monkeypatch):
    bk.save_settings(world.home, to=str(world.dest))

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(bk, "make_backup", boom)
    msg = bk.run_daily(world.home, sources=lambda: world.src, now=datetime(2026, 11, 26, 9))
    assert "disk full" in msg and "disk full" in bk.load_state(world.home)["last_error"]


def test_updater_backs_up_before_installing(monkeypatch):
    from roundtable import updater
    from roundtable.updater import InstallInfo, update

    from .test_updater import FakeRunner

    calls = []
    monkeypatch.setattr(bk, "before_update", lambda: calls.append("backup") or "Before updating: backed up.")
    lines = []
    update(info=InstallInfo("git", url="https://github.com/x/y", ref="main", commit="old1234"),
           runner=FakeRunner("new5678"), log=lines.append)
    assert calls == ["backup"] and "Before updating: backed up." in lines
    update(info=InstallInfo("git", url="u", ref="main", commit="same999"), runner=FakeRunner("same999"),
           log=lines.append)
    assert calls == ["backup"]  # nothing to install, no backup

    def broken():
        raise RuntimeError("no disk")

    monkeypatch.setattr(bk, "before_update", broken)
    st = update(info=InstallInfo("git", url="u", ref="main", commit="old1234"), runner=FakeRunner("new5678"),
                log=lines.append)
    assert st.latest == "new5678" and any("updating anyway" in x for x in lines)
    assert updater.backup_first  # the hook the app's updater uses


def test_before_update_falls_back_to_the_app_folder(world, monkeypatch):
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    monkeypatch.setattr(bk, "find_sources", lambda *a, **k: world.src)
    msg = bk.before_update(world.home)
    assert msg.startswith("Before updating") and bk.list_backups(world.home / "backups")


def test_settings_page_routes(world, monkeypatch):
    from roundtable.ui.server import UIApp

    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    app = UIApp(str(world.home / "config" / "hub.yaml"), str(world.home / "config" / "harness.yaml"))
    app.desktop = {"paths": Paths(world.home), "keys": None}
    st = app.dispatch("GET", "/api/backup", {}, {})
    assert st["destination"] == "" and "Google Drive for desktop" in st["no_drive"]
    st = app.dispatch("POST", "/api/backup", {}, {"action": "settings", "to": str(world.dest), "keep": 3, "daily": False})
    assert st["destination"] == str(world.dest) and st["settings"]["keep"] == 3 and not st["settings"]["daily"]
    job = app.dispatch("POST", "/api/backup", {}, {"action": "now", "passphrase": "Lantern-Quill-4821", "remember": False})
    for _ in range(200):
        j = app.dispatch("GET", f"/api/jobs/{job['id']}", {}, {})
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", j
    st = app.dispatch("GET", "/api/backup", {}, {})
    name = st["backups"][0]["name"]
    assert name.endswith(".zip.enc") and not st["passphrase_remembered"]
    assert "Lantern-Quill-4821" not in json.dumps(json.loads((world.home / "config" / "app.json").read_text(encoding="utf-8")))
    info = app.dispatch("POST", "/api/backup", {}, {"action": "inspect", "file": name, "passphrase": "Lantern-Quill-4821"})
    assert any("files:" in line for line in info["lines"])
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="Confirm"):
        app.dispatch("POST", "/api/backup", {}, {"action": "restore", "file": name, "passphrase": "Lantern-Quill-4821"})
    with pytest.raises(ApiError, match="passphrase doesn't open"):
        app.dispatch("POST", "/api/backup", {}, {"action": "inspect", "file": name, "passphrase": "nope"})


def test_command_line_where_and_settings(capsys, monkeypatch, tmp_path):
    from roundtable.main import main

    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    main(["backup", "where"])
    assert "Google Drive for desktop" in capsys.readouterr().out
    main(["backup", "settings", "--keep", "4", "--daily", "off"])
    assert bk.load_settings() == {**bk.DEFAULTS, "keep": 4, "daily": False}
    with pytest.raises(SystemExit, match="Google Drive"):
        main(["backup", "list"])


# -- wave 9: the folder picker and backups in one tap ---------------------------------------------------------
def test_browse_uses_the_windows_own_folder_dialog_and_says_so_without_one(tmp_path):
    asked = []

    class Window:
        def create_file_dialog(self, kind, directory="", allow_multiple=False):
            asked.append((kind, directory, allow_multiple))
            return (str(tmp_path / "USB"),)

    assert bk.pick_folder(str(tmp_path), window=Window()) == str(tmp_path / "USB")
    assert asked == [("folder", str(tmp_path), False)]

    class Cancelled:
        def create_file_dialog(self, *a, **k):
            return None

    assert bk.pick_folder(window=Cancelled()) is None
    with pytest.raises(bk.BackupError, match="only opens in the desktop app's own window"):
        bk.pick_folder()  # no pywebview window in the tests: it says so, and what to do instead


def test_backups_turned_on_in_one_tap(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    got = bk.turn_on(home)
    assert not got["ok"] and "Browse" in got["words"]
    assert bk.load_settings(home)["to"] == "auto"  # nothing changed
    drive = tmp_path / "My Drive"
    drive.mkdir()
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [drive])
    got = bk.turn_on(home)
    assert got["ok"] and got["destination"] == str(drive / bk.FOLDER_NAME)
    assert bk.load_settings(home)["daily"] is True
    got = bk.turn_on(home, str(tmp_path / "USB"))
    assert got["ok"] and bk.load_settings(home)["to"] == str(tmp_path / "USB")
