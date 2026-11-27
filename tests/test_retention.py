"""Retention: the one sweep that deletes old data, only from the folders it is meant to tidy."""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from roundtable import retention
from roundtable.core.config import parse_config
from roundtable.core.store import FileStore
from roundtable.harness import eventlog
from roundtable.hub.service import Hub

DAY = 86400


def old(p: Path, days: float) -> Path:
    t = time.time() - days * DAY
    os.utime(p, (t, t))
    return p


def write(p: Path, text: str = "x", days: float = 0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return old(p, days) if days else p


def make_project(tmp_path: Path, status: str = "done") -> Path:
    root = tmp_path / "proj"
    write(root / "src" / "main.py", "print('mine')", days=400)  # the owner's own files
    write(root / "notes.txt", "keep", days=400)
    write(root / ".harness" / "project.json", json.dumps({"status": status}), days=10)
    write(root / ".harness" / "tasks.json", "[]", days=400)
    write(root / ".harness" / "spend.jsonl", "{}\n", days=400)
    return root


def cfg_with(**limits):
    return SimpleNamespace(sections={"retention": limits}, lab_dir=None)


def test_settings_defaults_and_overrides():
    s = retention.settings(None)
    assert s == retention.DEFAULTS
    s = retention.settings(cfg_with(spill_days="3", shots_keep=0, enabled="off", bogus=1, logs_days="x"))
    assert s["spill_days"] == 3 and s["shots_keep"] == 1 and s["enabled"] is False
    assert "bogus" not in s and s["logs_days"] == 30


def test_old_spill_and_shots_go_project_files_and_attachments_stay(tmp_path):
    root = make_project(tmp_path)
    h = root / ".harness"
    write(h / "spill" / "a.txt", "old" * 100, days=20)
    write(h / "spill" / "b.txt", "new", days=1)
    for i in range(5):
        write(h / "shots" / f"t{i}" / "desktop.png", "png", days=10 - i)
        old(h / "shots" / f"t{i}", 10 - i)
    write(h / "shots" / "latest.json", json.dumps({"dir": "t0"}))
    write(h / "attachments" / "photo.jpg", "jpg", days=400)  # what the owner sent: never removed
    res = retention.tidy(cfg_with(shots_keep=2), home=tmp_path / "home", projects=[root])
    gone = {Path(r.path).relative_to(root).as_posix() for r in res.removed}
    assert gone == {".harness/spill/a.txt", ".harness/shots/t1", ".harness/shots/t2"}
    assert (h / "shots" / "t0").is_dir()  # the latest one stays even though it is old
    assert (h / "spill" / "b.txt").is_file() and (h / "attachments" / "photo.jpg").is_file()
    for keep in ("src/main.py", "notes.txt", ".harness/tasks.json", ".harness/spend.jsonl", ".harness/project.json"):
        assert (root / keep).is_file()
    assert res.freed > 0 and "Tidied up: 3 old things" in res.message()


def test_dry_run_removes_nothing_but_logs_what_it_would(tmp_path):
    root = make_project(tmp_path)
    f = write(root / ".harness" / "spill" / "a.txt", "old", days=20)
    home = tmp_path / "home"
    res = retention.tidy(None, home=home, projects=[root], dry_run=True)
    assert f.is_file() and [r.what for r in res.removed] == ["spill"]
    assert res.message().startswith("Would remove 1 old thing")
    [entry] = retention.entries(home)
    assert entry["dry_run"] is True and entry["groups"]["spill"]["count"] == 1


def test_running_and_paused_projects_are_left_alone(tmp_path):
    for status in ("running", "paused"):
        root = make_project(tmp_path, status=status)
        s = write(root / ".harness" / "spill" / "b.txt", "old", days=90)
        res = retention.tidy(None, home=tmp_path / "home", projects=[root])
        assert s.is_file() and any(status in x for x in res.skipped)


def test_never_follows_a_link_out_of_the_tidied_folder(tmp_path):
    root = make_project(tmp_path)
    outside = write(tmp_path / "precious" / "keep.txt", "mine", days=400)
    spill = root / ".harness" / "spill"
    spill.mkdir(parents=True)
    link = spill / "link"
    try:
        link.symlink_to(outside.parent, target_is_directory=True)
    except OSError:  # Windows without the right: nothing to check
        return
    if os.utime not in os.supports_follow_symlinks:  # Windows: a link's own date can't be set
        return
    os.utime(link, (time.time() - 90 * DAY,) * 2, follow_symlinks=False)
    retention.tidy(None, home=tmp_path / "home", projects=[root])
    assert outside.is_file()
    assert not link.is_symlink()  # the link itself went, not what it points to


def test_remove_refuses_paths_outside_the_allowed_folder(tmp_path):
    sweep = retention.Sweep(retention.settings(None))
    f = write(tmp_path / "proj" / "main.py", "x", days=400)
    assert not sweep.remove("spill", f, tmp_path / "proj" / ".harness" / "spill")
    assert f.is_file() and sweep.result.skipped


def test_events_archived_not_cut_and_app_log_shortened(tmp_path):
    root = make_project(tmp_path)
    ev = root / ".harness" / "events.jsonl"
    lines = [json.dumps({"n": i, "pad": "x" * 100}) for i in range(30000)]
    write(ev, "\n".join(lines) + "\n", days=1)
    home = tmp_path / "home"
    log = write(home / "logs" / "app.log", "line\n" * 2_000_000)
    oldlog = write(home / "logs" / "self-test.json", "{}", days=60)
    res = retention.tidy(cfg_with(events_mb=1, app_log_mb=1), home=home, projects=[root])
    kept = ev.read_text(encoding="utf-8").splitlines()
    assert len(kept) < 30000 and json.loads(kept[-1])["n"] == 29999 and ev.stat().st_size <= 512 * 1024
    [archive] = eventlog.archives(root)
    assert archive.name.startswith("events-") and archive.name.endswith(".jsonl.gz")
    whole = eventlog.read_events(root)
    assert [r["n"] for r in whole] == list(range(30000))  # nothing of the history lost, in order
    assert [r["n"] for r in eventlog.read_events(root, include_archives=False)] == [json.loads(x)["n"] for x in kept]
    assert log.stat().st_size <= 512 * 1024 and not oldlog.exists()
    assert (home / "logs" / retention.LOG_NAME).is_file()
    assert {r.what for r in res.removed} == {"events", "app_log", "logs"}


def test_events_dry_run_and_a_fresh_log_are_left(tmp_path):
    root = make_project(tmp_path)
    ev = write(root / ".harness" / "events.jsonl", ("{}\n" * 400_000), days=1)
    size = ev.stat().st_size
    res = retention.tidy(cfg_with(events_mb=1), home=tmp_path / "h", projects=[root], dry_run=True)
    assert ev.stat().st_size == size and not eventlog.archives(root) and [r.what for r in res.removed] == ["events"]
    ev.touch()  # written just now: a run may still be adding to it
    retention.tidy(cfg_with(events_mb=1), home=tmp_path / "h", projects=[root])
    assert ev.stat().st_size == size and not eventlog.archives(root)


def test_archive_is_undone_when_the_log_changes_meanwhile(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    ev = write(root / ".harness" / "events.jsonl", "{}\n" * 100_000, days=1)
    real = eventlog.gzip.compress

    def compress_and_write(data):
        with open(ev, "a", encoding="utf-8") as f:  # a run appends while the archive is being made
            f.write('{"late": true}\n')
        return real(data)

    monkeypatch.setattr(eventlog.gzip, "compress", compress_and_write)
    try:
        eventlog.archive_older_half(root, 1000)
    except OSError:
        pass
    assert not eventlog.archives(root) and ev.read_text(encoding="utf-8").endswith('{"late": true}\n')
    assert not [p for p in (root / ".harness").iterdir() if p.name.startswith(".events-")]


def test_recent_files_are_never_touched(tmp_path):
    root = make_project(tmp_path)
    f = write(root / ".harness" / "spill" / "a.txt", "old", days=20)
    res = retention.tidy(cfg_with(spill_days=0, min_age_minutes=60), home=tmp_path / "h", projects=[root],
                         now=f.stat().st_mtime + 60)
    assert f.is_file() and not res.removed


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    *args], cwd=cwd, check=True, capture_output=True)


def test_only_done_merged_clean_worktrees_go(tmp_path):
    root = make_project(tmp_path)
    write(root / ".gitignore", ".harness/\nnode_modules/\n*.env\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "start")
    from roundtable.harness.worktrees import Worktrees

    trees = Worktrees(root)
    ids = ("t-1", "t-2", "t-3", "t-4")
    for t in ids:
        p, _ = trees.add(t, "HEAD")
        write(p / f"{t}.txt", t)
        trees.commit(t, f"work {t}")
        if t != "t-2":
            trees.merge_into_project(t, f"merge {t}")
    write(trees.path("t-1") / "node_modules" / "pkg" / "index.js", "cache")  # a build cache doesn't count
    write(trees.path("t-3") / "local.env", "mine")  # an ignored file that matters
    tasks = [{"id": "t-1", "status": "done"}, {"id": "t-2", "status": "done"}, {"id": "t-3", "status": "done"},
             {"id": "t-4", "status": "failed"}]
    write(root / ".harness" / "tasks.json", json.dumps(tasks))
    write(root / ".harness" / "worktrees.json", json.dumps({t: {"baseline": None} for t in ids}))
    later = time.time() + 2 * 3600
    res = retention.tidy(None, home=tmp_path / "h", projects=[root], now=later, dry_run=True)
    assert [Path(r.path).name for r in res.removed] == ["t-1"] and trees.path("t-1").is_dir()
    res = retention.tidy(None, home=tmp_path / "h", projects=[root], now=later)
    assert not trees.path("t-1").exists()
    assert all(trees.path(t).is_dir() for t in ("t-2", "t-3", "t-4"))  # not merged, an ignored file, not done
    assert [r.what for r in res.removed] == ["worktrees"]
    assert any("files git ignores" in x for x in res.skipped)
    assert set(json.loads((root / ".harness" / "worktrees.json").read_text())) == {"t-2", "t-3", "t-4"}
    last = json.loads((root / ".harness" / "events.jsonl").read_text().splitlines()[-1])
    assert last["event"] == "worktree_removed" and last["task"] == "t-1"
    res = retention.tidy(cfg_with(worktrees_merged=False), home=tmp_path / "h", projects=[root], now=later)
    assert not res.removed


def test_old_runs_in_the_hub_beyond_the_kept_ones(tmp_path):
    raw = {"storage": {"type": "file", "path": "data"}, "agents": {"demo": {"repo": "me/demo"}}}
    hub = Hub(parse_config(raw, tmp_path / "hub.yaml"), store=FileStore(tmp_path / "data"))
    d = tmp_path / "data" / "sessions" / "demo"
    for i in range(6):
        write(d / f"2026010{i}T000000Z-pc-ab.jsonl", "{}\n", days=5)
    write(d / "about.json", "{}", days=5)
    res = retention.tidy(cfg_with(hub_sessions_keep=4), home=tmp_path / "h", projects=[], hub=hub)
    left = sorted(f.name for f in d.iterdir())
    assert left == ["20260102T000000Z-pc-ab.jsonl", "20260103T000000Z-pc-ab.jsonl", "20260104T000000Z-pc-ab.jsonl",
                    "20260105T000000Z-pc-ab.jsonl", "about.json"]
    assert [r.path for r in res.removed] == ["sessions/demo/20260101T000000Z-pc-ab.jsonl",
                                             "sessions/demo/20260100T000000Z-pc-ab.jsonl"]


def test_run_daily_once_a_day_and_not_while_busy(tmp_path):
    home = tmp_path / "home"
    day = datetime(2026, 11, 27, 9)
    assert retention.run_daily(None, home=home, busy=True, now=day) is None
    assert retention.run_daily(None, home=home, now=day) is not None
    assert retention.run_daily(None, home=home, now=day) is None
    assert retention.run_daily(None, home=home, now=datetime(2026, 11, 28, 9)) is not None


def test_the_owners_switch_stops_the_daily_sweep(tmp_path):
    home = tmp_path / "home"
    assert retention.auto_on(home)
    retention.set_auto(home, False)
    assert retention.run_daily(None, home=home, now=datetime(2026, 11, 27, 9)) is None
    retention.set_auto(home, True)
    assert retention.run_daily(None, home=home, now=datetime(2026, 11, 27, 9)) is not None


def test_activity_line_only_when_something_went(tmp_path):
    root = make_project(tmp_path)
    home = tmp_path / "home"
    retention.tidy(None, home=home, projects=[root])  # nothing old
    retention.tidy(None, home=home, projects=[root], dry_run=True)
    assert retention.activity_items(home) == []
    write(root / ".harness" / "spill" / "a.txt", "old", days=90)
    retention.tidy(None, home=home, projects=[root])
    [item] = retention.activity_items(home)
    assert item["kind"] == "tidy" and item["text"].startswith("Tidied up: 1 old thing")
    assert item["details"] == ["Spill files: 1 (3 bytes)"] and item["at"].endswith("Z")


def test_tidy_api(tmp_path):
    from roundtable.ui import tidyapi

    home = tmp_path / "home"
    root = make_project(tmp_path)
    f = write(root / ".harness" / "spill" / "a.txt", "old", days=90)
    app = SimpleNamespace(_backup_home=lambda: home, cfg=lambda: None, hub=None, hub_lock=None)
    r = tidyapi.routes(app)
    assert r[("GET", "/api/tidy")]({}) == {"auto": True, "last": None}
    assert r[("POST", "/api/tidy")]({"auto": False})["auto"] is False and not retention.auto_on(home)
    monkey = retention.tidy

    def with_project(cfg, **kw):
        return monkey(cfg, projects=[root], **kw)

    retention_tidy = tidyapi.retention.tidy
    tidyapi.retention.tidy = with_project
    try:
        prev = r[("POST", "/api/tidy/preview")]({})
    finally:
        tidyapi.retention.tidy = retention_tidy
    assert f.is_file() and prev["message"].startswith("Would remove 1 old thing")
    assert prev["details"] == ["Spill files: 1 (3 bytes)"] and prev["items"][0]["what"] == "Spill files"
    assert r[("GET", "/api/tidy")]({})["last"] is None  # a preview isn't a tidy-up


def test_off_means_off(tmp_path):
    root = make_project(tmp_path)
    f = write(root / ".harness" / "spill" / "a.txt", "old", days=90)
    res = retention.tidy(cfg_with(enabled=False), home=tmp_path / "h", projects=[root])
    assert f.is_file() and not res.removed


def test_cli_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HARNESS_CONFIG", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("HUB_CONFIG", str(tmp_path / "missing-hub.yaml"))
    write(tmp_path / "home" / "logs" / "old.log", "x", days=90)
    retention.main(["--dry-run", "--no-hub"])
    out = capsys.readouterr().out
    assert "would remove" in out and (tmp_path / "home" / "logs" / "old.log").is_file()


def test_old_plugin_drafts_go_unless_a_plugin_points_at_them(tmp_path):
    """Wave 7: drafts from "Make one" that were never added are tidied after a fortnight; one in use stays."""
    import os
    import time
    from types import SimpleNamespace

    from roundtable import retention

    home = tmp_path / "home"
    old, used, new = (home / "plugin-drafts" / n for n in ("old-tool-1", "used-tool-2", "new-tool-3"))
    for d in (old, used, new):
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text("id = 'x'\n", encoding="utf-8")
    month = time.time() - 30 * 86400
    for d in (old, used):
        for f in (d, d / "plugin.toml"):
            os.utime(f, (month, month))
    harness = tmp_path / "cfg" / "harness.yaml"
    harness.parent.mkdir()
    harness.write_text("roles: {}\n", encoding="utf-8")
    (harness.parent / "custom.yaml").write_text(f"plugins:\n  used: {{path: {used}}}\n", encoding="utf-8")
    res = retention.tidy(SimpleNamespace(path=str(harness), retention={}), home=home, projects=[])
    assert not old.exists() and used.is_dir() and new.is_dir()
    assert any(r.what == "plugin_drafts" for r in res.removed)
