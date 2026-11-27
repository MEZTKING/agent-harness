"""Named agents (agents.py, harness/agentstage.py, ui/agentsapi.py): a name, a face, notes and a memory.

Every project and agent here is made up, in tmp_path; the models are scripted (the maker is the provider id)
and faces come from scripted image providers: nothing reaches the network and nothing costs money.
"""

import base64
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from roundtable import agents as ag
from roundtable.harness import projectsettings as ps
from roundtable.harness.agentstage import AgentStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers import chat_images
from roundtable.providers.base import ProviderError, Usage
from roundtable.providers.scripted import ScriptedImages

from .test_harness import Brain
from .test_stage_hooks import ONE, build

SECRET_PROJECT_WORDS = "a made-up tool for counting purple teacups"


class NoKind(Orchestrator):
    def _kind_proof(self):
        return []


class O(*((NoKind,) if issubclass(NoKind, AgentStage) else (AgentStage, NoKind))):
    pass


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def _orch(tmp_path, home, name="proj", allowed=None, level=None):
    orch, events, brain = build(tmp_path / name, cls=O, brain=Brain(plan=ONE))
    orch.agents_home = home
    orch.start(SECRET_PROJECT_WORDS)
    if allowed:
        ps.update(orch.project.root, {"providers_allowed": allowed})
    orch.plan()
    if level:
        meta = orch.project.meta()
        meta["checking"] = level
        orch.project.save_meta(meta)
    return orch, events


def _worker_prompts(orch):
    out = []
    for pid in ("a", "b"):
        for c in orch.cfg.provider(pid).calls:
            if c["tools"] and "finish_task" in {t.name for t in c["tools"]}:
                out.append(c["messages"][0]["content"])
    return out


def _png(side=300):
    from PIL import Image

    im = Image.new("RGB", (side, side * 2 // 3))
    for x in range(im.width):  # some detail, so the picture isn't trivially small
        for y in range(0, im.height, 3):
            im.putpixel((x, y), ((x * 7) % 256, (y * 5) % 256, (x * y) % 256))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


# -- the store ----------------------------------------------------------------------------------------------------
def test_starters_one_hired_per_job_with_initials_until_a_face(home):
    team = ag.load_all(home)
    assert [a.job for a in team] == list(ag.JOBS)
    assert all(a.hired and a.built_in for a in team)
    torvic = ag.hired_for(home, "builder")
    assert torvic.name == "Torvic" and ag.initials("Torvic") == "T" and ag.initials("Ann Ruby Lee") == "AR"
    assert ag.card(home, torvic)["face"].startswith("data:image/")  # the starter face shipped with the app (initials only when none)


def test_one_hired_agent_per_job_and_renaming(home):
    new = ag.save(home, {"name": "Brindle Fox", "job": "builder", "notes": "Prefer small files.", "hire": True})
    assert new.id == "brindle-fox" and ag.hired_for(home, "builder").id == "brindle-fox"
    assert not ag.get(home, "torvic").hired  # stepped back, still on the team
    renamed = ag.save(home, {"id": "brindle-fox", "name": "Brin"})
    assert renamed.id == "brindle-fox" and renamed.name == "Brin" and renamed.notes == "Prefer small files."
    with pytest.raises(ag.AgentError, match="2,000"):
        ag.save(home, {"id": "brindle-fox", "notes": "x" * 2001})
    with pytest.raises(ag.AgentError, match="key"):
        ag.save(home, {"id": "brindle-fox", "notes": "use sk-ant-api03-" + "a" * 40})


def test_removing_an_agent_keeps_its_folder_under_removed(home):
    ag.learn(home, "ondra", "Read the done-when first.")
    r = ag.remove(home, "ondra")
    kept = list((ag.removed_dir(home)).iterdir())
    assert len(kept) == 1 and kept[0].name.startswith("ondra-") and (kept[0] / "memory.md").is_file()
    assert (kept[0] / "agent.yaml").is_file() and "kept" in r["reply"]
    assert "ondra" not in {a.id for a in ag.load_all(home)}  # a removed starter doesn't come back
    assert ag.hired_for(home, "checker") is None


# -- in a run -------------------------------------------------------------------------------------------------------
def test_a_hired_agents_notes_reach_the_workers_prompt(tmp_path, home):
    ag.save(home, {"id": "torvic", "notes": "Always end files with a newline. Name things plainly."})
    orch, events = _orch(tmp_path, home)
    assert orch.run() == "done"
    prompts = _worker_prompts(orch)
    assert prompts and "You are Torvic" in prompts[0] and "Always end files with a newline" in prompts[0]
    t = orch.project.tasks()[0]
    assert t.attempts[-1]["agent"] == "torvic"
    rows = [json.loads(x) for x in (orch.project.root / ".harness/metrics.jsonl").read_text().splitlines()]
    assert rows[-1]["agent"] == "torvic"


def test_memory_reaches_a_second_project_but_not_one_with_an_allowed_list(tmp_path, home):
    first, events = _orch(tmp_path, home, "first")
    task = first.project.tasks()[0]
    first._agent_learn(task, "Run the tests before finishing.")
    assert "Run the tests before finishing." in ag.learned(home, "torvic")
    assert ("agent_learned" in [k for k, _ in events])

    second, _ = _orch(tmp_path, home, "second")
    assert second.run() == "done"
    assert "Run the tests before finishing." in _worker_prompts(second)[0]

    kept, _ = _orch(tmp_path, home, "kept", allowed=["a", "b"])
    assert kept.run() == "done"
    p = _worker_prompts(kept)[0]
    assert "You are Torvic" in p and "Run the tests before finishing." not in p  # notes yes, memory no
    kept._agent_learn(kept.project.tasks()[0], "Something from a private project.")
    assert "private project" not in ag.learned(home, "torvic")  # nor written from it


def test_own_repository_keeps_out_of_memory_unless_turned_on(tmp_path, home, monkeypatch):
    ag.learn(home, "torvic", "A lesson from elsewhere.")
    orch, _ = _orch(tmp_path, home)
    task = orch.project.tasks()[0]
    monkeypatch.setattr(O, "_repo_mode", lambda self: True)
    assert "A lesson from elsewhere." not in orch._agent_worker_part(task)
    real = O.project_settings

    def with_memory(self, value):
        s = real(self)
        return SimpleNamespace(values={**s.values, "agent_memory": value})

    monkeypatch.setattr(O, "project_settings", lambda self: with_memory(self, "on"))
    assert "A lesson from elsewhere." in orch._agent_worker_part(task)
    monkeypatch.setattr(O, "_repo_mode", lambda self: False)
    monkeypatch.setattr(O, "project_settings", lambda self: with_memory(self, "off"))
    assert "A lesson from elsewhere." not in orch._agent_worker_part(task)
    orch.mcp_allowed = False  # a lab replay never reads it
    monkeypatch.setattr(O, "project_settings", real)
    assert "A lesson from elsewhere." not in orch._agent_worker_part(task)


def test_at_lean_the_stage_does_nothing(tmp_path, home):
    ag.save(home, {"id": "torvic", "notes": "A note that must not appear."})
    orch, _ = _orch(tmp_path, home)
    meta = orch.project.meta()
    meta.pop("checking", None)  # a plan made before 1.2.0
    orch.project.save_meta(meta)
    assert orch.run() == "done"
    assert "A note that must not appear." not in _worker_prompts(orch)[0]
    assert "agent" not in orch.project.tasks()[0].attempts[-1]


def test_agents_never_uses_a_model_the_project_does_not_allow(tmp_path, home):
    ag.save(home, {"id": "torvic", "notes": "Be careful."})
    orch, events = _orch(tmp_path, home, allowed=["a"])
    assert orch.run() == "done"
    assert not orch.cfg.provider("b").calls
    models = [a["model"] for t in orch.project.tasks() for a in t.attempts]
    assert models and all(m.startswith("a/") for m in models)
    assert "stage_error" not in [k for k, _ in events]


def test_job_of_maps_roles_to_jobs(tmp_path):
    orch, _, _ = build(tmp_path, cls=O)
    cfg = orch.cfg
    assert ag.job_of(cfg, "orchestrator") == "planner" and ag.job_of(cfg, "reviewer") == "checker"
    assert ag.job_of(cfg, "coder") == "builder" and ag.job_of(cfg, "designer") == "artist"  # an image role here


# -- faces ------------------------------------------------------------------------------------------------------------
def test_make_face_with_scripted_images_saves_a_small_webp_and_its_prompt_holds_no_project_text(tmp_path, home):
    pytest.importorskip("PIL")
    orch, _ = _orch(tmp_path, home)
    a = ag.save(home, {"id": "calla", "name": "Calla", "notes": f"Remember {SECRET_PROJECT_WORDS}",
                       "traits": "Bold, elegant; Acme-Corp 42 secret-sauce-recipe-words"})
    imgs = ScriptedImages("img")
    big = _png()
    imgs.generate = lambda model, prompt, options=None: (imgs.prompts.append((prompt, options)) or (big, "png", Usage(output_tokens=1)))
    orch.cfg.register("img", imgs)
    price = ag.face_price(orch.cfg, home)
    assert price["ok"] and price["usd"] is None and "isn't known" in price["words"]
    r = ag.make_face(orch.cfg, a, home)
    face = ag.folder(home, "calla") / "face.webp"
    assert face.is_file() and face.stat().st_size <= ag.FACE_MAX and face.read_bytes()[8:12] == b"WEBP"
    assert r["bytes"] == face.stat().st_size
    prompt, options = imgs.prompts[0]
    assert options["aspect_ratio"] == "1:1" and options["size"] == "1K"
    assert "purple teacups" not in prompt and "Calla" not in prompt and "acme" not in prompt.lower()
    assert "bold and elegant" in prompt and "No text, no letters" in prompt
    assert ag.card(home, ag.get(home, "calla"))["face"].startswith("data:image/webp;base64,")
    spend = (ag.agents_dir(home) / "spend.jsonl").read_text().splitlines()
    assert json.loads(spend[0])["outcome"] == "face"


def test_face_price_uses_the_pricing_table_and_says_when_there_is_no_picture_job(tmp_path, home):
    orch, _, _ = build(tmp_path, cls=O)
    orch.cfg.pricing["img/pic"] = {"per_image": 0.04}
    assert ag.face_price(orch.cfg, home)["usd"] == 0.04
    bare = SimpleNamespace(roles={})
    assert not ag.face_price(bare, home)["ok"]
    with pytest.raises(ag.AgentError, match="picture job"):
        ag.make_face(bare, ag.get(home, "pell"), home)


def test_the_size_option_reaches_the_request():
    assert chat_images.image_config({}) == {}
    assert chat_images.image_config({"aspect_ratio": "1:1", "size": "2k"}) == {"aspect_ratio": "1:1", "image_size": "2K"}
    assert chat_images.image_config({"size": "largest"}) == {"image_size": "4K"}
    assert chat_images.image_config({"size": "1024 x 1024"}) == {"size": "1024x1024"}
    with pytest.raises(ProviderError):
        chat_images.image_config({"size": "huge"})

    sent = {}
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nx").decode()

    class Completions:
        def create(self, **kw):
            sent.update(kw)
            msg = SimpleNamespace(images=[{"image_url": {"url": "data:image/png;base64," + png}}], model_extra={})
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    p = object.__new__(chat_images.ChatImagesProvider)
    p.name, p.api_key_env = "img", None
    p._openai = SimpleNamespace(**{n: type(n, (Exception,), {}) for n in (
        "AuthenticationError", "NotFoundError", "BadRequestError", "RateLimitError", "APIStatusError",
        "APITimeoutError", "APIConnectionError", "APIError")})
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    p.generate("m", "a square", {"size": "1K", "aspect_ratio": "1:1"})
    assert sent["extra_body"]["image_config"] == {"aspect_ratio": "1:1", "image_size": "1K"}
    sent.clear()
    p.generate("m", "as before", {})
    assert "image_config" not in sent["extra_body"]  # no size asked: the request is as it was


# -- sharing -------------------------------------------------------------------------------------------------------------
def test_export_and_import_round_trip_a_name_notes_and_face(home, tmp_path):
    a = ag.save(home, {"name": "Wick", "job": "checker", "notes": "Quote the broken line.", "traits": "calm"})
    (ag.folder(home, "wick") / "face.webp").write_bytes(b"RIFF\x10\x00\x00\x00WEBPVP8 tiny")
    ag.learn(home, "wick", "Something learned on a private project.")
    data = ag.export(home, a)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert sorted(names) == ["agent.yaml", "face.webp"]  # memory is left out by default
    other = tmp_path / "other-home"
    look = ag.import_file(data, other)
    assert look["ok"] and not look["added"] and look["would"]["notes"] == "Quote the broken line."
    assert not ag.agents_dir(other).exists()  # nothing written before confirm
    done = ag.import_file(data, other, confirm=True)
    b = ag.get(other, done["id"])
    assert (b.name, b.job, b.notes, b.hired) == ("Wick", "checker", "Quote the broken line.", False)
    assert (ag.folder(other, b.id) / "face.webp").read_bytes() == (ag.folder(home, "wick") / "face.webp").read_bytes()
    assert not ag.memory_file(other, b.id).exists()
    again = ag.import_file(data, other, confirm=True)
    assert again["id"] != b.id  # a second copy never replaces the first

    with_mem = ag.export(home, a, with_memory=True)
    assert "memory.md" in zipfile.ZipFile(io.BytesIO(with_mem)).namelist()
    assert "private project" in ag.export_preview(home, a, True)["memory"]
    assert "private project" in ag.import_file(with_mem, tmp_path / "third")["would"]["memory"]


def _zip(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, body in files.items():
            z.writestr(n, body)
    return b.getvalue()


def test_an_import_with_a_script_inside_is_refused_and_model_choices_are_dropped(tmp_path):
    card = "name: Nib\njob: builder\nnotes: hello\n"
    bad = ag.import_file(_zip({"agent.yaml": card, "run.py": "print('hi')"}), tmp_path)
    assert not bad["ok"] and "never code" in bad["problems"][0]
    assert not ag.import_file(_zip({"agent.yaml": card, "face.webp": b"#!/bin/sh"}), tmp_path)["ok"]
    assert not ag.import_file(_zip({"../agent.yaml": card}), tmp_path)["ok"]
    assert not ag.import_file(b"not a zip", tmp_path)["ok"]
    assert not ag.agents_dir(tmp_path).exists()
    sneaky = card + "model: b/expensive\nprovider: b\nfallback: [b/other]\n"
    got = ag.import_file(_zip({"agent.yaml": sneaky}), tmp_path, confirm=True)
    assert got["ok"] and got["would"]["dropped"] == ["fallback", "model", "provider"]
    text = (ag.folder(tmp_path, got["id"]) / "agent.yaml").read_text()
    assert "expensive" not in text and "provider" not in text


# -- the API --------------------------------------------------------------------------------------------------------------
def test_agents_api(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "agentsapi"))
    orch, _, _ = build(tmp_path, cls=O)

    class App:
        def _backup_home(self):
            return tmp_path / "home"

        def need_cfg(self):
            return orch.cfg

    r = server._feature_routes(App())
    listing = r[("GET", "/api/agents")]({})
    assert len(listing["agents"]) == 6 and all(j["hired"] for j in listing["jobs"])
    made = r[("POST", "/api/agents")]({"name": "Sorrel", "job": "designer", "hire": True})
    assert made["agent"]["hired"] and made["reply"] == "Saved Sorrel."
    one = r[("GET", "/api/agents/one")]({"id": ["sorrel"]})
    assert one["notes"] == "" and one["learned"] == ""
    price = r[("POST", "/api/agents/face")]({"id": "sorrel"})
    assert not price["made"] and price["price"]["ok"]
    made_face = r[("POST", "/api/agents/face")]({"id": "sorrel", "confirm": True})
    assert made_face["made"] and (tmp_path / "home/agents/sorrel").glob("face.*")
    ex = r[("GET", "/api/agents/export")]({"id": ["sorrel"]})
    assert ex["name"] == "sorrel.rtagent" and ex["memory"] == ""
    assert "data" not in r[("GET", "/api/agents/export")]({"id": ["sorrel"], "preview": ["1"]})
    look = r[("POST", "/api/agents/import")]({"data": ex["data"]})
    assert look["ok"] and not look["added"]
    assert r[("POST", "/api/agents/remove")]({"id": "sorrel"})["removed"] == "sorrel"
    with pytest.raises(server.ApiError):
        r[("POST", "/api/agents/import")]({"data": "%%%"})
    with pytest.raises(server.ApiError):
        r[("GET", "/api/agents/one")]({"id": ["../etc"]})


def test_the_desktop_module_uses_tokens_only():
    from pathlib import Path

    js = (Path(ag.__file__).parent / "ui" / "static" / "agents.js").read_text(encoding="utf-8")
    assert "export async function agentsTab" in js and "export function agentChip" in js
    assert "Roundtable" not in js and "<svg" not in js


def test_without_pillow_a_paid_for_face_is_kept_as_it_came(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no Pillow here")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100_000
    assert ag.shrink_face(png) == (png, "png")
    assert ag.shrink_face(b"not a picture") is None
