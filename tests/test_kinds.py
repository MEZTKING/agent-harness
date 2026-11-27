"""Kinds: loading, extends and extras, refusing a bad card, proposing, the overlay, freezing at approval,
sharing a kind (export and import), and the API. Made-up projects only, no network, no keys."""

import base64
import io
import json
import os
import zipfile

import pytest

from roundtable import kinds as K
from roundtable.harness.config import parse_config
from roundtable.harness.kindstage import KindStage
from roundtable.harness.orchestrator import HarnessError, Orchestrator
from roundtable.kinds import model as M
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW
from .test_plan import PlanBrain


# -- the stand-in for the coordinator's hook-up lines (orchestrator.py) -------------------------------------------
class KOrch(KindStage, Orchestrator):
    """Orchestrator with the kind hooks wired in as the hook-up lines say."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cfg = self._kind_cfg(self.cfg)

    def start(self, goal, **kw):
        super().start(goal, **kw)
        self._kind_propose(goal)

    def _plan_call(self, job, reserved):  # plan() and revise_plan(): + self._kind_plan_part()
        self.planner_jobs = getattr(self, "planner_jobs", []) + [job + self._kind_plan_part()]
        return super()._plan_call(job + self._kind_plan_part(), reserved)

    def plan(self):
        new = super().plan()
        doc = self.project.plan_doc()
        if doc is not None:
            doc["kind"] = self._kind_doc()
            self.project.save_plan_doc(doc)
        return new

    def approve(self):
        super().approve()
        self._kind_freeze()

    def _worker_prompt(self, task, tasks, feedback):
        part = self._kind_worker_part(task.role)
        return super()._worker_prompt(task, tasks, feedback) + (f"\n\n{part}" if part else "")

    def _finish(self, tasks):
        super()._finish(tasks)
        self._gallery_record(tasks)


def make_k(tmp_path, brain=None, raw=RAW):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = brain or PlanBrain()
    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    cfg.register("img", ScriptedImages())
    return KOrch(cfg, tmp_path / "proj"), cfg


def own_kind(home, kid, text, files=None):
    d = home / "kinds" / kid
    d.mkdir(parents=True, exist_ok=True)
    (d / "kind.yaml").write_text(text, encoding="utf-8")
    for name, body in (files or {}).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")
    return d


# -- loading, extends, extras ---------------------------------------------------------------------------------------
def test_builtin_kinds_load_and_none_says_proven():
    cat = K.load_all(None)
    assert cat.problems == []
    assert {"other", "web-app", "website", "browser-game", "java-mod"} <= set(cat.kinds)
    assert set(cat.extras) == {"apk", "exe"}
    assert all(k.status in ("trial", "not_yet") for k in [*cat.kinds.values(), *cat.extras.values()])
    assert cat.kinds["java-mod"].usable is False and cat.kinds["web-app"].usable


def test_extends_shares_pieces_and_extras_stack():
    cat = K.load_all(None)
    site = K.resolve("website", catalog=cat)
    assert site.spec["needs"] == ["node", "playwright"]  # from web-app, written once
    assert site.plan["spec_sections"][1] == "Pages"  # its own sections win
    assert "web app" in site.prompts["coder"] and "website people read" in site.prompts["coder"]  # appended
    assert {d["text"] for d in site.plan["dont"]} >= {"No build step the owner has to run by hand",
                                                     "No made-up facts about a real place"}
    both = K.resolve("web-app", ["apk", "exe"], catalog=cat)
    assert [e["id"] for e in both.extras] == ["apk", "exe"]
    assert {"java", "android", "node"} <= set(both.spec["needs"]) and {"web", "apk", "exe"} <= set(both.spec["targets"])
    ids = [p["id"] for p in K.proof_plan(both)]
    assert ids[:2] == ["starts", "tests"] and {"apk_built", "exe_built"} <= set(ids)
    assert next(p for p in K.proof_plan(both) if p["id"] == "apk_built")["from"] == "apk"
    assert any("Play Store" in d["text"] for d in both.plan["dont"])
    with pytest.raises(K.KindError):
        K.resolve("website", ["nope"], catalog=cat)
    with pytest.raises(K.KindError):
        K.resolve("other", ["apk"], catalog=cat)  # not allowed for that kind


def test_extends_in_a_circle_is_refused(tmp_path):
    for a, b in (("ring-a", "ring-b"), ("ring-b", "ring-a")):
        own_kind(tmp_path, a, f"schema: kind@1\nid: {a}\nname: {a}\nextends: {b}\n")
    with pytest.raises(K.KindError, match="circle"):
        K.resolve("ring-a", home=tmp_path)


def test_a_bad_card_is_refused_with_the_line_named(tmp_path):
    own_kind(tmp_path, "boasting", "schema: kind@1\nid: boasting\nname: Boasting\nblurb: Says it works.\n"
                                   "status: proven\nlook: sideways\nneeds: [node, warp-drive]\nsurprise: 1\n")
    cat = K.load_all(tmp_path)
    assert "boasting" not in cat.kinds
    probs = next(p["problems"] for p in cat.problems if p["where"] == "own: boasting")
    assert any(p.startswith("line 5:") and "proven" in p for p in probs)
    assert any(p.startswith("line 6:") and "look" in p for p in probs)
    assert any(p.startswith("line 7:") and "warp-drive" in p for p in probs)
    assert any(p.startswith("line 8:") and "surprise" in p for p in probs)
    data, probs = M.parse_text("schema: kind@1\nid: x\nname: X\nproof:\n  - {id: a, how: dance, words: hi}\n")
    assert data is None and probs == ["line 5: how must be one of page_opens, command, play, picture, file_exists "
                                      "(it says 'dance')"]
    data, probs = M.parse_text("schema: kind@1\nid: x\nname: [unclosed\n")
    assert data is None and probs[0].startswith("line ")


def test_own_kind_wins_and_a_missing_prompt_file_is_named(tmp_path):
    own_kind(tmp_path, "website", "schema: kind@1\nid: website\nname: My website\nextends: web-app\n")
    own_kind(tmp_path, "noprompt", "schema: kind@1\nid: noprompt\nname: N\nroles:\n  prompts: {coder: prompts/c.md}\n")
    cat = K.load_all(tmp_path)
    assert cat.kinds["website"].name == "My website" and cat.kinds["website"].source == "own"
    probs = next(p["problems"] for p in cat.problems if p["where"] == "own: noprompt")
    assert probs == ["line 5: the prompt file prompts/c.md isn't there"]


# -- proposing ------------------------------------------------------------------------------------------------------
IDEAS = [
    ("a bakery site with opening hours and a menu", "website", []),
    ("a portfolio for my drawings", "website", []),
    ("a landing page for my band", "website", []),
    ("a snake game with a high score", "browser-game", []),
    ("a card-matching puzzle", "browser-game", []),
    ("a tiny platformer with three levels", "browser-game", []),
    ("a music player for the songs on my computer", "web-app", []),
    ("a budget tracker that works offline", "web-app", []),
    ("a timer app for my android phone", "web-app", ["apk"]),
    ("a notes app as a windows exe", "web-app", ["exe"]),
    ("a script that renames my photos by date", "other", []),
    ("a minecraft mod with copper lanterns", "other", []),  # the mod kind isn't ready: never proposed
]


@pytest.mark.parametrize("idea,kind,extras", IDEAS)
def test_propose_on_twelve_made_up_ideas(idea, kind, extras):
    cat = K.load_all(None)
    got = K.propose(idea, cat)
    assert got[0][0] == kind, got
    assert got[-1][0] == "other" and "java-mod" not in [g[0] for g in got]
    if kind != "other":
        assert got[0][2].startswith("because you said “")
    assert K.propose_extras(idea, got[0][0], cat) == extras


def test_wizard_options_and_answers():
    opts = K.wizard_options()
    ids = [o["id"] for o in opts]
    assert ids[-1] == "other" and opts[-1]["label"] == "Something else"
    mod = next(o for o in opts if o["id"] == "java-mod")
    assert mod["disabled"] and mod["group"] == "Coming" and mod["tip"]
    assert ids.index("java-mod") > max(ids.index(i) for i in ("website", "web-app", "browser-game"))
    assert K.from_wizard("android")["kind"] == "web-app" and K.from_wizard("android")["extras"] == ["apk"]
    assert K.from_wizard("game")["kind"] == "browser-game"
    w = K.from_wizard("other", other="a little shop window site", idea="bakery")
    assert w["kind"] == "website" and w["by"] == "roundtable"
    assert K.from_wizard("java-mod", idea="a mod")["kind"] == "other"  # not ready: proposed instead


# -- the overlay --------------------------------------------------------------------------------------------------------
def test_overlay_changes_roles_and_prompts_and_nothing_else():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    before = {"coder": cfg.prompt_text("coder"), "limits": vars(cfg.limits).copy(), "pricing": dict(cfg.pricing),
              "providers": json.dumps(cfg.providers, sort_keys=True),
              "models": {n: [str(m) for m in r.models] for n, r in cfg.roles.items()}}
    k = K.resolve("browser-game")
    ov = K.overlay(k)
    assert ov["roles"] == {} and set(ov) == {"roles", "prompts", "add_roles"}
    c = K.apply_to_config(cfg, k)
    assert c.prompt_text("coder").startswith(before["coder"].rstrip())  # appended, never replaced
    assert "# What this project is: Browser game" in c.prompt_text("coder")
    assert "browser game" in c.prompt_text("reviewer") and "game played in the browser" in c.prompt_text("orchestrator")
    assert c.roles["artist"].kind == "image" and [str(m) for m in c.roles["artist"].models] == ["img/pic"]
    assert {n: [str(m) for m in r.models] for n, r in c.roles.items() if n != "artist"} == before["models"]
    assert vars(c.limits) == before["limits"] and c.pricing == before["pricing"]
    assert json.dumps(c.providers, sort_keys=True) == before["providers"]
    # the original is untouched
    assert cfg.prompt_text("coder") == before["coder"] and "artist" not in cfg.roles


# -- choosing, confirming, freezing ---------------------------------------------------------------------------------------
def test_kind_is_proposed_confirmed_and_frozen_at_approval(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch, cfg = make_k(tmp_path)
    orch.start("a bakery site with opening hours", require_approval=True)
    meta = orch.project.meta()
    assert meta["kind"]["id"] == "website" and meta["kind"]["by"] == "roundtable" and not meta["kind"]["confirmed"]
    assert meta["parts"] == [{"id": "main", "name": "Website", "kind": "website", "extras": [], "folder": "."}]
    assert "website people read" in orch.cfg.prompt_text("coder")
    assert orch.run() == "awaiting_approval"
    doc = orch.project.plan_doc()
    assert doc["kind"]["question"].startswith("This looks like a Website, because you said “site”")
    assert doc["kind"]["choices"][0] == {"id": "website", "name": "Website", "recommended": True}
    assert doc["kind"]["choices"][-1]["id"] == "other" and doc["kind"]["change_words"]
    assert orch._kind_ask()["recommended"] == "website"
    assert "Stack, Pages, Words and pictures, How to run it" in orch.planner_jobs[0]
    # the owner changes it before approval: it re-plans with the new kind
    r = orch.set_kind("web-app")
    assert r["replanned"] and orch.project.plan_doc()["kind"]["id"] == "web-app"
    assert "Stack, Screens, Data, How to run it" in orch.planner_jobs[-1] and "Web app" in orch.planner_jobs[-1]
    assert orch._kind_ask() is None  # confirmed: no question left
    with pytest.raises(HarnessError):
        orch.set_kind("java-mod")  # not ready yet
    orch.approve()
    frozen = json.loads((orch.project.dir / "kind.json").read_text(encoding="utf-8"))
    assert frozen["kind"]["id"] == "web-app"
    # editing the kind later never changes a project already being built
    own_kind(home, "web-app", "schema: kind@1\nid: web-app\nname: Changed app\nblurb: changed\n")
    again = KOrch(cfg, orch.project.root)
    assert again._kind().name == "Web app"
    with pytest.raises(HarnessError, match="fixed"):
        again.set_kind("website")
    assert again.kind_use_newest()["ok"] and KOrch(cfg, orch.project.root)._kind().name == "Changed app"


def test_without_a_kind_nothing_changes(tmp_path):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    orch = Orchestrator(cfg, tmp_path / "plain")
    assert not hasattr(orch, "_kind")  # the plain orchestrator until the coordinator hooks it up
    k = KOrch(cfg, tmp_path / "plain2")
    assert k._kind() is None and k._kind_plan_part() == "" and k._kind_proof() == [] and k._kind_cfg(cfg) is cfg


def test_proof_plan_reaches_the_proof_stage_when_it_is_there(tmp_path, monkeypatch):
    import sys
    import types

    orch, _ = make_k(tmp_path)
    orch.start("a snake game")
    fake = types.ModuleType("roundtable.harness.proof")
    fake.plan_for = lambda items: [i["id"] for i in items]
    monkeypatch.setitem(sys.modules, "roundtable.harness.proof", fake)
    import roundtable.harness as pkg

    monkeypatch.setattr(pkg, "proof", fake, raising=False)
    assert orch._kind_proof_plan() == ["starts", "tests", "plays"]
    assert next(i for i in orch._kind_proof() if i["id"] == "plays")["status"] == "not_yet"


# -- sharing a kind ---------------------------------------------------------------------------------------------------------
def _zip(files, link=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = 0o120777 << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


GOOD = "schema: kind@1\nid: tiny-site\nname: Tiny site\nblurb: A one-page site.\nneeds: [node]\n" \
       "roles:\n  prompts: {coder: prompts/coder.md}\nproof:\n  - {id: starts, how: page_opens, words: It opens}\n"


def test_export_and_import_round_trip(tmp_path):
    home = tmp_path / "home"
    data = K.export(K.load_all(None).kinds["browser-game"])
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "kind.yaml" in names and "prompts/coder.md" in names and "card.md" in names
    look = K.import_file(data, home)
    assert look["ok"] and not look["installed"] and not (home / "kinds").exists()  # nothing switched on
    assert look["would"]["roles_added"] == ["artist"] and look["would"]["commands"] == ["npm test"]
    assert look["would"]["replaces"].startswith("the built-in one")
    done = K.import_file(data, home, confirm=True)
    assert done["installed"] and "On trial" in done["reply"]
    k = K.load_all(home).kinds["browser-game"]
    assert k.source == "own" and k.prompts == K.load_all(None).kinds["browser-game"].prompts
    extra = K.import_file(K.export(K.load_all(None).extras["apk"]), home, confirm=True)
    assert extra["installed"] and K.load_all(home).extras["apk"].source == "own"


@pytest.mark.parametrize("files,link,words", [
    ({"kind.yaml": GOOD, "prompts/coder.md": "hi", "template/app.js": "alert(1)"}, None, "never code"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "hi", "run.py": "import os"}, None, "never code"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "hi"}, "prompts/evil.md", "link"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "hi", "../outside.md": "x"}, None, "outside"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "hi", "/abs.md": "x"}, None, "outside"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "x" * (5 * 1024 * 1024 + 1)}, None, "over 5 MB"),
    ({"kind.yaml": GOOD, "prompts/coder.md": "use sk-" + "abcdefghijklmnopqrstuvwxyz0123"}, None, "shaped like a key"),
    ({"kind.yaml": GOOD.replace("status", "x")}, None, "isn't in the file"),
    ({"card.md": "no kind"}, None, "no kind.yaml"),
])
def test_import_refuses_what_isnt_safe(tmp_path, files, link, words):
    res = K.import_file(_zip(files, link), tmp_path, confirm=True)
    assert not res["ok"] and any(words in p for p in res["problems"]), res
    assert not (tmp_path / "kinds").exists()


def test_import_refuses_a_bad_card_and_rubbish(tmp_path):
    bad = K.import_file(_zip({"kind.yaml": GOOD.replace("name: Tiny site", "status: proven\nname: T"),
                              "prompts/coder.md": "hi"}), tmp_path, confirm=True)
    assert not bad["ok"] and bad["problems"][0].startswith("kind.yaml, line 3:")
    assert K.import_file(b"not a zip", tmp_path)["problems"] == ["This isn't a kind file (.rtkind)."]
    ok = K.import_file(_zip({"kind.yaml": GOOD, "prompts/coder.md": "Keep it small."}), tmp_path, confirm=True)
    assert ok["installed"] and K.load_all(tmp_path).kinds["tiny-site"].prompts == {"coder": "Keep it small."}


def test_export_refuses_key_shaped_text(tmp_path):
    d = own_kind(tmp_path, "leaky", "schema: kind@1\nid: leaky\nname: Leaky\n",
                 {"card.md": "token sk-" + "abcdefghijklmnopqrstuvwxyz0123"})
    with pytest.raises(K.KindError, match="shaped like a key"):
        K.export(K.load_all(tmp_path).kinds["leaky"])
    assert d.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need rights on Windows")
def test_export_leaves_out_links_and_code(tmp_path):
    d = own_kind(tmp_path, "linky", "schema: kind@1\nid: linky\nname: Linky\n", {"template/app.js": "x"})
    (d / "card.md").symlink_to(tmp_path / "elsewhere.md")
    (tmp_path / "elsewhere.md").write_text("private", encoding="utf-8")
    names = zipfile.ZipFile(io.BytesIO(K.export(K.load_all(tmp_path).kinds["linky"]))).namelist()
    assert names == ["kind.yaml"]


# -- the API ------------------------------------------------------------------------------------------------------------------
def test_kinds_api(tmp_path, monkeypatch):
    from roundtable.ui import kindsapi, server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "kindsapi"))
    monkeypatch.setattr(kindsapi, "tools", lambda: ({"node": "Node.js", "playwright": "Playwright's browser"},
                                                   {"playwright"}))

    class App:
        def _backup_home(self):
            return tmp_path / "home"

    r = server._feature_routes(App())
    cat = r[("GET", "/api/kinds")]({})
    groups = {g["group"]: g["kinds"] for g in cat["groups"]}
    game = groups["Browser games"][0]
    assert game["status_words"] == "On trial" and game["typical"].endswith("(a guess)")
    assert game["missing"] == ["Playwright's browser"] and game["needs"][0] == {"id": "node", "name": "Node.js",
                                                                                 "missing": False}
    assert groups["Mods and add-ons"][0]["status_words"] == "Not yet"
    assert {e["id"] for e in cat["extras"]} == {"apk", "exe"}
    one = r[("GET", "/api/kinds/one")]({"id": ["web-app"], "extras": ["apk"]})
    assert one["extras"] == [{"id": "apk", "name": "Android app (APK)"}] and "music player" in one["more"]["card"]
    p = r[("POST", "/api/kinds/propose")]({"goal": "a quiz game"})
    assert p["choices"][0]["id"] == "browser-game" and p["choices"][-1]["name"] == "Something else"
    ex = r[("GET", "/api/kinds/export")]({"id": ["website"]})
    assert ex["name"] == "website.rtkind"
    look = r[("POST", "/api/kinds/import")]({"data": ex["data"]})
    assert look["ok"] and not look["installed"]
    assert r[("POST", "/api/kinds/import")]({"data": ex["data"], "confirm": True})["installed"]
    with pytest.raises(server.ApiError):
        r[("POST", "/api/kinds/import")]({"data": "%%%"})
    assert base64.b64decode(ex["data"])[:2] == b"PK"
