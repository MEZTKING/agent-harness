"""Search by meaning on this computer, asking with quotes, and look_up for the agents (recall.py, recallstage.py).

Every project here is made up, in tmp_path; the models are scripted; nothing touches the network.
"""

import json
import os
import time

from roundtable import documents as docs
from roundtable import memory, recall
from roundtable import search as plain
from roundtable.harness import projectsettings as ps
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.recallstage import RecallStage
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW, Brain
from .test_stage_hooks import Seam


def project(root, name="Made-up notes app", decisions=(), memory_lines=(), tasks=()):
    h = root / ".harness"
    h.mkdir(parents=True, exist_ok=True)
    (h / "project.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (h / "plan.json").write_text(json.dumps({"title": name, "decisions": list(decisions), "questions": []}),
                                 encoding="utf-8")
    (h / "tasks.json").write_text(json.dumps(list(tasks)), encoding="utf-8")
    if memory_lines:
        (h / "memory.md").write_text("# Memory\n\n## Recent\n" + "".join(f"- {x}\n" for x in memory_lines),
                                     encoding="utf-8")
    return root


SIGN_IN = {"id": "C1", "question": "How should people sign in?", "chosen": "o2", "why": "Fewer passwords to forget.",
           "options": [{"id": "o1", "label": "Email and a password"}, {"id": "o2", "label": "Google accounts"}]}


# -- the words ----------------------------------------------------------------------------------------------------
def test_stems_and_related_words():
    assert {recall.stem(w) for w in ("decide", "decided", "deciding", "decision")} == {"decid"}
    assert recall.tokens("What did we decide about signing in?") == ["decid", "signin"]
    assert "login" in recall.related("signin")
    assert recall.likeness("synced", "syncing") > recall.likeness("synced", "screen")


def test_a_decision_is_found_by_other_words_and_ranks_above_a_shared_word(tmp_path):
    home = tmp_path / "home"
    p = project(tmp_path / "notes", decisions=[SIGN_IN])
    docs.add_file(home, "screens.md", b"Screen sizes: the game runs on a 16:9 screen, and the screen scales.")
    got = recall.find("What did we decide about the log-in screen?", [p], home)
    assert got["pieces"][0]["kind"] == "decision" and "Google accounts" in got["pieces"][0]["text"]
    assert any(x["kind"] == "document" for x in got["pieces"])  # the file is there, below
    assert got["name"] == "Search by meaning (on this computer)"


def test_meaning_finds_what_plain_word_search_misses(tmp_path):
    home = tmp_path / "home"
    p = project(tmp_path / "notes", memory_lines=["2026-11-01 · The login page uses big buttons."])
    assert plain.search("sign-in", projects=[p], home=home)["total"] == 0
    got = recall.find("sign-in", [p], home)
    assert got["pieces"] and "login page" in got["pieces"][0]["text"]


def test_the_index_refreshes_after_a_file_changes(tmp_path):
    home = tmp_path / "home"
    p = project(tmp_path / "notes", memory_lines=["The menu music is a harp."])
    assert recall.find("harp", [p], home)["pieces"]
    mem = memory.project_path(p)
    time.sleep(0.01)
    mem.write_text("# Memory\n\n## Recent\n- The menu music is a cello.\n", encoding="utf-8")
    os.utime(mem, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert not recall.find("harp", [p], home)["pieces"]
    assert recall.find("cello", [p], home)["pieces"]
    # a project no longer registered is forgotten
    recall.find("cello", [], home)
    assert not recall.find("cello", [], home)["pieces"]


def test_a_private_document_is_in_the_owners_search_and_never_given_to_a_model(tmp_path):
    home = tmp_path / "home"
    p = project(tmp_path / "notes")
    docs.add_file(home, "secret-recipe.txt", b"The secret sauce is smoked paprika.", private=True)
    assert recall.find("secret sauce", [p], home)["pieces"][0]["private"] is True
    assert recall.for_project(p, "secret sauce", home) == []
    seen = []

    def brain(model, system, messages, tools):
        seen.append(json.dumps(messages) + system)
        return reply(calls=[("submit_answer", {"answer": "x", "quotes": []})])

    cfg = _cfg(brain)
    out = recall.ask(cfg, "What is the secret sauce?", [p], home, confirm=True)
    assert out["held"] == 1 and not seen and "as they are" in out["words"]


# -- asking ---------------------------------------------------------------------------------------------------------
def _cfg(brain):
    raw = {"providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}},
           "roles": {"orchestrator": {"model": "a/planner"}, "coder": {"model": "a/coder"},
                     "reviewer": {"model": "b/reviewer"}},
           "pricing": {"a/planner": {"input": 5, "output": 5}, "a/coder": {"input": 3, "output": 3},
                       "b/reviewer": {"input": 1, "output": 1}}}
    cfg = parse_config(raw)
    for n in ("a", "b"):
        cfg.register(n, ScriptedProvider(n, brain))
    return cfg


def test_ask_shows_the_price_first_then_quotes_its_sources(tmp_path):
    home = tmp_path / "home"
    p = project(tmp_path / "notes", decisions=[SIGN_IN])
    calls = []

    def brain(model, system, messages, tools):
        calls.append(model)
        if messages[-1]["role"] == "tool":
            return reply("done")
        return reply(calls=[("submit_answer", {"answer": "You chose Google accounts.",
                                               "quotes": [{"piece": 1, "text": "Google accounts"}]})])

    cfg = _cfg(brain)
    first = recall.ask(cfg, "What did we decide about signing in?", [p], home)
    assert not calls and first["price_usd"] > 0 and first["model"] == "b/reviewer"  # the cheapest
    assert first["words"].startswith("About $")
    out = recall.ask(cfg, "What did we decide about signing in?", [p], home, confirm=True)
    assert calls == ["reviewer"] and out["answer"] == "You chose Google accounts."
    q = out["quotes"][0]
    assert q["found"] and q["source"] == "Made-up notes app · Plan" and q["open"]["tab"] == "plan"
    assert out["cost_usd"] > 0


def test_ask_sends_nothing_from_a_project_that_does_not_allow_the_maker(tmp_path):
    home = tmp_path / "home"
    open_ = project(tmp_path / "open", "Open app", memory_lines=["The dragon boss has three lives."])
    shut = project(tmp_path / "shut", "Shut app", memory_lines=["The dragon boss breathes ice."])
    ps.update(shut, {"makers_allowed": ["anthropic"]})
    prompts = []

    def brain(model, system, messages, tools):
        prompts.append(json.dumps(messages))
        return reply(calls=[("submit_answer", {"answer": "Three lives.", "quotes": [{"piece": 1, "text": "three"}]})])

    cfg = _cfg(brain)
    out = recall.ask(cfg, "dragon boss", [open_, shut], home, confirm=True)
    assert out["held"] == 1 and len(out["pieces"]) == 2
    assert "three lives" in prompts[0] and "ice" not in prompts[0]


def test_with_no_model_allowed_the_pieces_are_shown_as_they_are(tmp_path):
    home = tmp_path / "home"
    shut = project(tmp_path / "shut", memory_lines=["The castle has four towers."])
    ps.update(shut, {"makers_allowed": ["anthropic"]})
    cfg = _cfg(lambda *a: reply("never"))
    out = recall.ask(cfg, "castle towers", [shut], home, confirm=True)
    assert out["answer"] == "" and out["pieces"] and out["held"] == 1


# -- look_up for the agents -----------------------------------------------------------------------------------------
class O(RecallStage, Seam):
    pass


def build(tmp_path, cls=O, raw=RAW, brain=None):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = brain or Brain()
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    orch = cls(cfg, tmp_path / "proj")
    return orch, brain


def test_look_up_returns_only_what_this_project_may_use(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch, _ = build(tmp_path)
    orch.start("a made-up bakery app")
    root = orch.project.root
    memory.add_note(memory.project_path(root), "The bakery opens at seven.")
    other = project(tmp_path / "other", "Other app", memory_lines=["The bakery in the other app opens at nine."])
    recall.find("bakery", [root, other], home)  # the owner's search has both in the index
    mine = recall.pid_of(root)
    docs.add_file(home, "hours.md", b"Bakery hours: weekends from eight.", projects=[mine])
    docs.add_file(home, "elsewhere.md", b"Bakery hours elsewhere: never.", projects=["0" * 12])
    docs.add_file(home, "private.md", b"Bakery takings: private.", private=True)
    tool = orch._recall_tools(orch.cfg.roles["coder"])[0]
    text = tool.fn({"query": "bakery hours"})
    assert "seven" in text and "weekends from eight" in text
    assert "nine" not in text and "never" not in text and "takings" not in text
    assert len(text) < recall.LOOKUP_CHARS + 600
    assert orch._recall_attempt(type("T", (), {"id": "T1", "role": "coder"})(), None)["looked_up"] >= 2
    row = json.loads((root / ".harness" / recall.LOG).read_text().splitlines()[-1])
    assert row["task"] == "T1" and len(row["docs"]) == 1
    assert "Hours" in orch._docs_plan_part() and "look_up before guessing" in orch._docs_plan_part()


def test_a_documents_setting_of_none_gives_no_documents(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch, _ = build(tmp_path)
    orch.start("a made-up bakery app")
    docs.add_file(home, "hours.md", b"Bakery hours: weekends from eight.")
    monkeypatch.setattr(O, "_recall_documents_setting", lambda self: "none")
    assert orch._docs_plan_part() == "" and orch._recall_tools(orch.cfg.roles["coder"]) == []


class Recording(Brain):
    def __init__(self):
        super().__init__()
        self.seen = []

    def __call__(self, model, system, messages, tools):
        self.seen.append((model, system, json.dumps(messages, sort_keys=True), sorted(t.name for t in tools)))
        return super().__call__(model, system, messages, tools)


def _run(tmp_path, cls):
    raw = {**json.loads(json.dumps(RAW)), "memory": {"enabled": False}}
    brain = Recording()
    orch, _ = build(tmp_path, cls, raw, brain)
    orch.start("a made-up bakery app")
    orch.plan()
    assert orch.run() == "done"
    attempts = [a for t in orch.project.tasks() for a in t.attempts]
    return brain.seen, attempts


def test_with_memory_off_and_no_documents_the_prompts_are_byte_for_byte_as_before(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    before, a1 = _run(tmp_path / "one", Seam)
    after, a2 = _run(tmp_path / "two", O)

    def norm(seen):
        return [(m, s, j.replace(str(tmp_path / "two"), "X").replace(str(tmp_path / "one"), "X"), t)
                for m, s, j, t in seen]

    assert norm(before) == norm(after)
    assert not any("looked_up" in a for a in a2) and len(a1) == len(a2)


def test_the_full_orchestrator_has_the_recall_stage_or_the_hook_up_is_pending():
    # the coordinator adds RecallStage to the Orchestrator's bases; until then the seam has no hooks of its own
    assert issubclass(Orchestrator, RecallStage) or not callable(getattr(Orchestrator, "_recall_tools", None))


def test_d4_memory_never_changes_what_the_charter_protects(tmp_path, monkeypatch):
    """Recall and documents only read; they write their own index, documents folder and recall.jsonl."""
    home = tmp_path / "home"
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "harness.yaml").write_text("roles: {}\n", encoding="utf-8")
    (lab / "custom.yaml").write_text("limits: {max_cost_usd: 1}\n", encoding="utf-8")
    before = {f: f.read_bytes() for f in lab.iterdir()}
    p = project(tmp_path / "notes", decisions=[SIGN_IN])
    docs.add_file(home, "a.md", b"sign-in notes")
    recall.find("sign-in", [p], home)
    recall.graph([p], home)
    assert {f: f.read_bytes() for f in lab.iterdir()} == before
    assert sorted(x.name for x in home.iterdir()) == ["documents", "recall"]
