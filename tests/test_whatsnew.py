"""What's new after an update: the README's notes, shown once per version, for the desktop and the phone."""

import json
from pathlib import Path
from types import SimpleNamespace

from roundtable import __version__, updater
from roundtable.ui import whatsnewapi

README = """# Made-up app

### Install

Some words.

### What's new in 2.1.0

- **Pictures in ideas**: send a photo with your idea; the planner sees it.
- **Faster start** (`startup:` setting): opens in half the time,
  even on an old laptop.
- A plain line with no bold. And a second sentence.

### What's new in 2.0.0

- **A new look**: everything redone.

## Part 1
"""


def test_sections_are_read_as_plain_headlines():
    s = updater.whats_new_sections(README)
    assert list(s) == ["2.1.0", "2.0.0"]
    a, b, c = s["2.1.0"]
    assert a == {"title": "Pictures in ideas", "text": "send a photo with your idea; the planner sees it."}
    assert b == {"title": "Faster start", "text": "opens in half the time, even on an old laptop."}
    assert c["title"] == "A plain line with no bold" and c["text"] == "And a second sentence."
    assert s["2.0.0"] == [{"title": "A new look", "text": "everything redone."}]


def test_whats_new_from_readme_then_bundle_then_release_notes(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    bundle = tmp_path / "whatsnew.md"
    bundle.write_text(updater.whatsnew_bundle(README, keep=1), encoding="utf-8")
    assert "2.0.0" not in bundle.read_text(encoding="utf-8")
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"3.0.0": "## What's Changed\n* Fix the thing by someone\n"
                                          "**Full Changelog**: v2...v3"}), encoding="utf-8")
    assert updater.whats_new("v2.0.0", readme=readme, bundle=bundle, notes_file=notes)["source"] == "readme"
    missing = tmp_path / "none.md"
    got = updater.whats_new("2.1.0", readme=missing, bundle=bundle, notes_file=notes)
    assert got["source"] == "bundle" and len(got["items"]) == 3
    got = updater.whats_new("3.0.0", readme=missing, bundle=bundle, notes_file=notes)
    assert got["source"] == "release" and [i["title"] for i in got["items"]] == ["Fix the thing by someone"]
    assert updater.whats_new("9.9.9", readme=missing, bundle=bundle, notes_file=notes)["items"] == []


def test_the_bundled_copy_matches_the_readme():
    """After editing the README's notes: python -m roundtable.updater --whatsnew-bundle"""
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    bundled = updater.BUNDLE.read_text(encoding="utf-8")
    assert bundled == updater.whatsnew_bundle(readme), "run: python -m roundtable.updater --whatsnew-bundle"
    assert updater.whats_new_sections(bundled).get(__version__), f"no 'What's new in {__version__}' in the README"


def test_release_notes_saved_when_installing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "NOTES_FILE", tmp_path / "release-notes.json")
    updater.save_release_notes("v4.0.0", "- **Big change**: yes")
    got = updater.whats_new("4.0.0", readme=tmp_path / "x", bundle=tmp_path / "y")
    assert got["items"] == [{"title": "Big change", "text": "yes"}]


def app_at(home: Path):
    return SimpleNamespace(_backup_home=lambda: home)


def call(app, method, path, data=None):
    return whatsnewapi.routes(app)[(method, path)](data or {})


def test_new_install_shows_nothing_and_remembers(tmp_path):
    home = tmp_path / "home"
    assert not whatsnewapi.should_show(home, "2.1.0")
    assert json.loads((home / "whatsnew.json").read_text())["seen"] == "2.1.0"
    assert not whatsnewapi.should_show(home, "2.1.0")
    assert whatsnewapi.should_show(home, "2.2.0")  # the next update


def test_updated_from_a_version_without_the_card(tmp_path):
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "app.json").write_text("{}", encoding="utf-8")
    assert whatsnewapi.should_show(home, "2.1.0")


def test_api_shows_once_then_never_again(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "whatsnew.json").write_text(json.dumps({"seen": "0.0.1"}), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    monkeypatch.setattr(whatsnewapi, "_version", lambda: "2.1.0")
    monkeypatch.setattr(updater, "_readme", lambda: readme)
    app = app_at(home)
    got = call(app, "GET", "/api/whatsnew")
    assert got["show"] and got["title"] == "What's new in 2.1.0" and len(got["items"]) == 3
    assert call(app, "GET", "/api/whatsnew")["show"]  # until it is dismissed
    assert call(app, "POST", "/api/whatsnew/seen", {"version": "2.1.0"}) == {"ok": True, "seen": "2.1.0"}
    assert not call(app, "GET", "/api/whatsnew")["show"]
    again = call(app, "GET", "/api/whatsnew", {"all": ["1"]})
    assert not again["show"] and len(again["items"]) == 3  # still readable on request
    call(app, "POST", "/api/whatsnew/seen", {"version": "1.0.0"})  # an older one never moves it back
    assert json.loads((home / "whatsnew.json").read_text())["seen"] == "2.1.0"


def test_a_version_with_no_notes_is_not_asked_about_again(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "whatsnew.json").write_text(json.dumps({"seen": "0.0.1"}), encoding="utf-8")
    monkeypatch.setattr(whatsnewapi, "_version", lambda: "7.7.7")
    monkeypatch.setattr(updater, "_readme", lambda: None)
    monkeypatch.setattr(updater, "BUNDLE", tmp_path / "none.md")
    monkeypatch.setattr(updater, "NOTES_FILE", tmp_path / "none.json")
    got = call(app_at(home), "GET", "/api/whatsnew")
    assert not got["show"] and got["items"] == []
    assert json.loads((home / "whatsnew.json").read_text())["seen"] == "7.7.7"


def test_the_card_script_is_plain_and_safe():
    text = (Path(updater.__file__).parent / "ui" / "static" / "whatsnew.js").read_text(encoding="utf-8")
    assert "innerHTML" not in text and "/api/whatsnew/seen" in text and "Got it" in text and "More" in text
