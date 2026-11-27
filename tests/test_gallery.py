"""The Gallery: one record per finished goal (written once, kept across a re-run), hiding never deletes,
"Make another like this", the earned status, the API, and the scripted bakery site from wizard to gallery."""

import json

import pytest

from roundtable import kinds as K
from roundtable.asks import wizard_project
from roundtable.harness.config import parse_config
from roundtable.kinds import gallery as G
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW
from .test_kinds import KOrch
from .test_show_it import PNG, WebBrain, fake_renderer, hub_raw


def entry(project="cake-shop", goal="goal-1", kind="website", passed=True, **kw):
    return {"project": project, "goal": goal, "title": "Cake shop", "summary": "A made-up cake shop's page.",
            "kind": {"id": kind, "name": kind.title()}, "extras": [], "finished_at": "2026-11-26T10:00:00Z",
            "tasks": 4, "minutes": 41.2, "cost": {"counted_usd": 3.45, "real_usd": None}, "profile": "balanced",
            "models": [{"task": "T1", "role": "coder", "model": "a/coder"}],
            "proof": [{"id": "starts", "words": "It opens with no errors", "passed": passed},
                      {"id": "tests", "words": "Its tests pass", "passed": None, "optional": True},
                      {"id": "plays", "words": "Played for a minute", "passed": None, "status": "not_yet"}],
            "outputs": [{"kind": "page", "path": "index.html"}], "commit": "abc123", **kw}


def test_record_written_once_and_kept_across_a_rerun(tmp_path):
    pic = tmp_path / "desktop.png"
    pic.write_bytes(PNG)
    first = G.record(tmp_path, entry(), [pic])
    assert first["written"] and first["entry"]["pictures"] == ["desktop.png"]
    assert first["entry"]["cover"].startswith("data:image/") and not first["entry"]["hidden"]
    G.star(tmp_path, "cake-shop", "goal-1")
    again = G.record(tmp_path, entry(title="Something else"), [pic])
    assert not again["written"] and again["entry"]["title"] == "Cake shop" and again["entry"]["starred"]
    assert len(list((tmp_path / "gallery").glob("*/*/entry.json"))) == 1


def test_big_pictures_are_left_out_or_made_small(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + b"\x01" * (G.PICTURE_MAX + 10))  # not a real picture: it can't be shrunk
    rec = G.record(tmp_path, entry(), [big])["entry"]
    assert rec["pictures"] == [] and rec["cover"] == ""
    pytest.importorskip("PIL")
    from PIL import Image

    real = tmp_path / "real.png"
    Image.effect_noise((1600, 1000), 90).convert("RGB").save(real)
    assert real.stat().st_size > G.PICTURE_MAX
    rec = G.record(tmp_path, entry(goal="goal-2"), [real] * 6)["entry"]
    folder = tmp_path / "gallery" / "cake-shop" / "goal-2"
    assert rec["pictures"] == ["real.jpg", "real-2.jpg", "real-3.jpg", "real-4.jpg"]  # four at most
    assert all((folder / n).stat().st_size <= G.PICTURE_MAX for n in rec["pictures"])
    assert len(rec["cover"]) < G.COVER_MAX * 4 / 3 + 64


def test_hiding_never_deletes_and_again_copies_no_files(tmp_path):
    G.record(tmp_path, entry())
    assert G.hide(tmp_path, "cake-shop", "goal-1")["hidden"]
    assert G.entries(tmp_path) == [] and len(G.entries(tmp_path, hidden=True)) == 1
    assert (tmp_path / "gallery" / "cake-shop" / "goal-1" / "entry.json").is_file()
    assert not G.hide(tmp_path, "cake-shop", "goal-1", hidden=False)["hidden"]
    a = G.again(tmp_path, "cake-shop", "goal-1")
    assert a["wizard"] == {"kind": {"chosen": ["website"]}, "extras": [], "profile": {"chosen": ["balanced"]}}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gallery", "kinds"]
    with pytest.raises(G.GalleryError):
        G.one(tmp_path, "../etc", "goal-1")
    assert not hasattr(G, "delete") and not hasattr(G, "remove")


def test_words_the_owner_reads(tmp_path):
    e = entry()
    assert G.line(e) == "26 Nov · $3.45 · 41 min"
    assert G.proof_words(e) == ("It opens with no errors ✓ · Its tests pass – not checked yet · "
                                "Played for a minute – not checked yet")


def test_proven_is_earned_not_written(tmp_path):
    k = K.resolve("website")
    assert K.status_words(k, K.read_state(tmp_path)) == "On trial"
    G.record(tmp_path, entry(passed=False))
    assert K.status_words(k, K.read_state(tmp_path)) == "On trial"
    G.record(tmp_path, entry(goal="goal-2", passed=None))  # not checked isn't passed
    assert K.status_words(k, K.read_state(tmp_path)) == "On trial"
    G.record(tmp_path, entry(goal="goal-3", passed=True))
    state = K.read_state(tmp_path)
    assert K.status_words(k, state) == "Proven (3 built)"
    card = K.card(k, state)
    assert card["typical"] == "about $3.45 · about 41.2 min" and not card["guess"]
    G.hide(tmp_path, "cake-shop", "goal-3")
    assert K.status_words(k, K.read_state(tmp_path)) == "Proven (3 built)"  # hiding isn't unbuilding
    assert K.status_words(K.Kind(id="later", name="Later", status="not_yet"), state) == "Not yet"


def test_gallery_api(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "kindsapi"))

    class App:
        def _backup_home(self):
            return tmp_path

    r = server._feature_routes(App())
    assert r[("GET", "/api/gallery")]({})["entries"] == []
    pic = tmp_path / "p.png"
    pic.write_bytes(PNG)
    G.record(tmp_path, entry(), [pic])
    rows = r[("GET", "/api/gallery")]({})["entries"]
    assert rows[0]["line"] == "26 Nov · $3.45 · 41 min" and rows[0]["kind"] == "website" and rows[0]["proven"]
    one = r[("GET", "/api/gallery/one")]({"project": ["cake-shop"], "goal": ["goal-1"]})
    assert one["pictures"][0]["src"].startswith("data:image/png;base64,")
    assert one["more"]["models"][0]["model"] == "a/coder" and "It opens with no errors ✓" in one["proof_words"]
    assert r[("POST", "/api/gallery/hide")]({"project": "cake-shop", "goal": "goal-1"})["hidden"]
    assert r[("GET", "/api/gallery")]({})["entries"] == []
    assert len(r[("GET", "/api/gallery")]({"hidden": ["1"]})["entries"]) == 1
    assert r[("POST", "/api/gallery/star")]({"project": "cake-shop", "goal": "goal-1"})["starred"]
    assert r[("POST", "/api/gallery/again")]({"project": "cake-shop", "goal": "goal-1"})["wizard"]["kind"]
    with pytest.raises(server.ApiError):
        r[("GET", "/api/gallery/one")]({"project": ["nope"], "goal": ["goal-1"]})


# -- the exit: a scripted bakery site from the wizard to the gallery ------------------------------------------------------
def _clean_renderer():
    def render(jobs):
        for j in jobs:
            open(j["png"], "wb").write(PNG)
            open(j["jpg"], "wb").write(b"\xff\xd8\xff")
        return [{"kind": j["kind"], "errors": [], "title": "Crumbs"} for j in jobs]
    return render


def _bakery(tmp_path, render, raw=RAW, name="projects"):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = WebBrain()
    for p in ("a", "b"):
        cfg.register(p, ScriptedProvider(p, brain))
    cfg.register("img", ScriptedImages())
    answers = {"kind": {"chosen": ["website"]}, "idea": {"other": "a bakery site with opening hours and a menu"},
               "look": {"chosen": ["no"]}}
    w = wizard_project(answers, tmp_path / name)
    chose = K.from_wizard("website", idea=answers["idea"]["other"])
    orch = KOrch(cfg, w["dir"])
    orch.shot_renderer = render
    seen = []
    orch.emit = (lambda emit: lambda k, d: (seen.append((k, d)), emit(k, d)))(orch.emit)
    orch.start(w["goal"], require_approval=True)
    orch.set_kind(chose["kind"], chose["extras"], by="owner")  # the wizard's answer (asks.py hook-up)
    assert orch.run() == "awaiting_approval"
    return orch, seen


def test_scripted_bakery_site_from_wizard_to_gallery(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    raw = hub_raw(tmp_path)
    orch, seen = _bakery(tmp_path, fake_renderer(), raw=raw)
    doc = orch.project.plan_doc()
    assert doc["kind"]["id"] == "website" and doc["kind"]["confirmed"]
    assert doc["kind"]["question"] == "This is a Website." and doc["kind"]["status_words"] == "On trial"
    assert "The spec has these sections, in this order: Stack, Pages, Words and pictures" in orch.planner_jobs[0]
    orch.approve()
    assert orch.run() == "done"
    rows = G.entries(home)
    assert len(rows) == 1
    e = rows[0]
    assert e["kind"] == {"id": "website", "name": "Website"} and e["tasks"] == 2 and e["pictures"]
    assert e["cover"].startswith("data:image/") and e["commit"]
    assert {o["path"] for o in e["outputs"]} == {"index.html"}
    lines = {p["id"]: p["passed"] for p in e["proof"]}
    assert lines == {"starts": False, "tests": None}  # the made-up page shows an error on the phone
    assert K.status_words(K.resolve("website"), K.read_state(home)) == "On trial"
    assert ("gallery", {"project": e["project"], "goal": "goal-1", "title": e["title"]}) in seen
    hub = json.loads(next((tmp_path / "hubdata").rglob("plans/gallery/*/goal-1/entry.json")).read_text(encoding="utf-8"))
    assert hub["kind"]["id"] == "website" and "pictures" not in hub
    # the builders were told what they're making
    work = [m for m in orch.project.tasks()]
    assert all(t.status == "done" for t in work)
    told = orch._worker_prompt(work[0], work, [])
    assert "# What this project is: Website" in told and "No made-up facts about a real place" in told
    # a re-run of the same finished goal writes nothing new
    orch._gallery_record(orch.project.tasks())
    assert len(G.entries(home, hidden=True)) == 1


def test_a_clean_build_earns_proven(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch, _ = _bakery(tmp_path, _clean_renderer())
    orch.approve()
    assert orch.run() == "done"
    e = G.entries(home)[0]
    assert {p["id"]: p["passed"] for p in e["proof"]} == {"starts": True, "tests": None}
    assert K.status_words(K.resolve("website"), K.read_state(home)) == "Proven (1 built)"
    assert K.status_words(K.resolve("web-app"), K.read_state(home)) == "On trial"  # earned per kind
