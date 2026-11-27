"""Learning shared between machines (improve/share.py): two made-up machines and one made-up hub (a plain
folder) converge on one learned state, an undo anywhere wins, a change the other machine can't use or the
charter refuses is kept aside, and nothing of a project's reaches the hub."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roundtable.core.store import FileStore
from roundtable.improve import canary, charter, ledger, share, wallet
from roundtable.improve.lab import Lab, Proposal

from .test_improve import GOOD_PROMPT, make_cfg

SECRET = "Moonbakery Deluxe"
TASK_TITLE = "Bake the croissant screen"
REVIEW = "the reviewer said the buttons look ugly"
A = {"id": "pc-alpha", "name": "PC (ALPHA)", "kind": "pc"}
B = {"id": "phone-beta", "name": "Phone (Beta)", "kind": "phone"}


class Machine:
    def __init__(self, tmp_path: Path, me: dict, hub, monkeypatch, raw=None):
        self.me, self.hub, self.mp = me, hub, monkeypatch
        kw = {"raw": raw} if raw else {}
        self.cfg, self.lab = make_cfg(tmp_path / me["id"], **kw)
        self.home = tmp_path / me["id"] / "home"

    def __enter__(self):
        self.mp.setenv("ROUNDTABLE_MACHINE", self.me["id"])
        self.mp.setenv("ROUNDTABLE_MACHINE_NAME", self.me["name"])
        return self

    def __exit__(self, *a):
        return False

    def apply(self, kind, change, at, role="coder"):
        with self:
            p = self.lab.add_proposal(Proposal(
                id="", kind=kind, role=role, change=change, risk="low",
                rationale=f"In {SECRET}, '{TASK_TITLE}' failed: {REVIEW}.",
                test={"tasks_compared": 4, "passed": True,
                      "current": {"approved": 2, "cost_usd": 0.4, "runs": [{"task": "T7", "title": TASK_TITLE}]},
                      "candidate": {"approved": 4, "cost_usd": 0.3, "runs": [{"task": "T7", "feedback": REVIEW}]}}))
            self.lab.apply(p, self.cfg)
            p = self.lab.proposal(p.id)
            p.applied_at = at  # a fixed time, so the order between machines is known
            self.lab.save_proposal(p)
            return p

    def tick(self):
        with self:
            return share.share_round(self.hub, self.lab, self.cfg, self.me, home=self.home)


@pytest.fixture
def hub(tmp_path):
    return SimpleNamespace(store=FileStore(tmp_path / "hub"))


def _both(tmp_path, hub, monkeypatch, raw_b=None):
    return Machine(tmp_path, A, hub, monkeypatch), Machine(tmp_path, B, hub, monkeypatch, raw=raw_b)


def _round(*machines):
    for _ in range(2):
        for m in machines:
            m.tick()


def test_two_machines_converge_after_applies_in_different_orders(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:05Z")
    b.apply("prompt", {"prompt_text": GOOD_PROMPT}, "2026-11-27T10:00:01Z")
    b.apply("routing", {"models": ["a/coder", "b/coder2"]}, "2026-11-27T10:00:03Z")
    a.apply("options", {"options": {"effort": "high"}}, "2026-11-27T10:00:09Z")
    _round(a, b)
    assert a.lab.state_id() == b.lab.state_id()
    overlay, prompts = a.lab.learned()
    assert overlay["roles"]["coder"]["model"] == "b/coder2"  # A's routing came last: it wins on both
    assert overlay["roles"]["coder"]["options"] == {"effort": "high"} and prompts
    with b:
        lines = ledger.view(b.cfg, b.lab, B)["lines"]
    assert {x["by"] for x in lines} == {"you", "PC (ALPHA)"}


def test_an_undo_on_one_machine_reaches_the_other(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    pa = a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:01Z")
    b.apply("options", {"options": {"effort": "low"}}, "2026-11-27T10:00:02Z")
    _round(a, b)
    pulled = next(p for p in b.lab.proposals() if p.origin)
    with b:  # undone on the phone: a change it pulled from the PC
        ledger.act(b.cfg, b.lab, {"action": "undo", "id": pulled.id}, via="phone")
    _round(b, a)
    assert a.lab.proposal(pa.id).status == "undone"
    assert a.lab.state_id() == b.lab.state_id()
    assert "model" not in (a.lab.learned()[0]["roles"]["coder"])
    with a:
        line = next(x for x in ledger.view(a.cfg, a.lab, A)["lines"] if x["id"] == pa.id)
    assert line["state"] == "undone" and line["why"] == "undone on Phone (Beta)"
    # putting it back on the PC makes a new change, which reaches the phone too
    with a:
        ledger.act(a.cfg, a.lab, {"action": "put_back", "id": pa.id})
    _round(a, b)
    assert b.lab.learned()[0]["roles"]["coder"]["model"] == "b/coder2"
    assert a.lab.state_id() == b.lab.state_id()


def test_an_undo_of_the_makers_own_change_is_shared_and_never_written_back(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    pa = a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:01Z")
    _round(a, b)
    with a:
        ledger.act(a.cfg, a.lab, {"action": "undo", "id": pa.id})
    _round(a, b)
    docs = [json.loads(f.read_text()) for f in (tmp_path / "hub" / "learning" / "changes").glob("*.json")]
    assert [d["state"] for d in docs] == ["undone"] and docs[0]["undone_by"] == "pc-alpha"
    assert a.lab.state_id() == b.lab.state_id()
    assert all(p.status != "applied" for p in b.lab.proposals())


def test_a_change_with_a_model_the_other_machine_lacks_doesnt_break_its_config(tmp_path, hub, monkeypatch):
    raw_a = json.loads(json.dumps(__import__("tests.test_harness", fromlist=["RAW"]).RAW))
    raw_a["providers"]["c"] = {"type": "scripted"}
    a = Machine(tmp_path, A, hub, monkeypatch, raw=raw_a)
    b = Machine(tmp_path, B, hub, monkeypatch)
    from roundtable.providers.scripted import ScriptedProvider

    a.cfg.register("c", ScriptedProvider("c", lambda *x: None))
    a.apply("routing", {"models": ["c/fancy", "a/coder"]}, "2026-11-27T10:00:01Z")
    _round(a, b)
    assert not any(p.origin for p in b.lab.proposals())
    assert "c/fancy" not in (b.lab.root / "learned.yaml").read_text() if (b.lab.root / "learned.yaml").exists() else True
    b.lab.apply_learned(b.cfg)  # the learned overlay still lays on this machine's settings
    assert [str(m) for m in b.cfg.roles["coder"].models][0] == "a/coder"
    with b:
        v = ledger.view(b.cfg, b.lab, B)
    assert len(v["not_here"]) == 1 and "model this machine doesn't have" in v["not_here"][0]["why"]


def test_a_pulled_change_that_breaks_the_charter_is_not_applied(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:01Z")
    a.tick()
    asked = []

    def check(cfg, proposal, lab=None, by_owner=False):
        asked.append(proposal.origin)
        raise charter.CharterError("It would change a protected part.")

    monkeypatch.setattr(charter, "check", check)
    before = b.lab.state_id()
    report = b.tick()
    assert asked and report["refused"] and not report["pulled"]
    assert b.lab.state_id() == before and not any(p.status == "applied" for p in b.lab.proposals())


def test_a_pulled_change_the_charter_wants_a_tap_for_waits_and_is_watched_once_used(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("prompt", {"prompt_text": GOOD_PROMPT}, "2026-11-27T10:00:01Z", role="reviewer")
    a.tick()

    def check(cfg, proposal, lab=None, by_owner=False):
        if proposal.role == "reviewer" and not by_owner:
            e = charter.CharterError("The checker's instructions change only with your yes.")
            e.needs_owner = True
            raise e

    monkeypatch.setattr(charter, "check", check)
    watched = []
    monkeypatch.setattr(canary, "start", lambda lab, p, v: watched.append(p.id))
    b.tick()
    with b:
        v = ledger.view(b.cfg, b.lab, B)
        assert len(v["waiting"]) == 1 and v["waiting"][0]["from"] == "PC (ALPHA)"
        ledger.act(b.cfg, b.lab, {"action": "apply", "id": v["waiting"][0]["id"]})
    assert watched == [v["waiting"][0]["id"]]


def test_a_pulled_change_is_watched_here(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("options", {"options": {"effort": "high"}}, "2026-11-27T10:00:01Z")
    a.tick()
    watched = []
    monkeypatch.setattr(canary, "start", lambda lab, p, v: watched.append((p.id, v)))
    report = b.tick()
    assert [w[0] for w in watched] == report["pulled"] and watched[0][1] >= 1


def test_the_hub_holds_no_project_name_title_or_review_text(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:01Z")
    a.apply("prompt", {"prompt_text": GOOD_PROMPT}, "2026-11-27T10:00:02Z")
    a.apply("prompt", {"prompt_text": GOOD_PROMPT + f" Remember the {SECRET} colours."}, "2026-11-27T10:00:03Z",
            role="reviewer")
    monkeypatch.setattr(charter, "scrub", lambda text, lab=None: text.replace(SECRET, "a project"))
    monkeypatch.setattr(wallet, "spent_week", lambda lab: 0.12, raising=False)
    agents = a.home / "agents" / "ada"
    agents.mkdir(parents=True)
    (agents / "agent.yaml").write_text("name: Ada\njob: builder\n", encoding="utf-8")
    (agents / "memory.md").write_text(f"- learned on {SECRET}: {REVIEW}\n", encoding="utf-8")
    _round(a, b)
    written = "".join(f.read_text(encoding="utf-8", errors="replace")
                      for f in (tmp_path / "hub").rglob("*") if f.is_file())
    for secret in (SECRET, TASK_TITLE, REVIEW, "T7", "croissant", "rationale", "feedback"):
        assert secret not in written, secret
    assert not list((tmp_path / "hub").rglob("memory.md"))
    assert (tmp_path / "hub" / "learning" / "agents" / "ada" / "agent.yaml").is_file()
    assert (b.home / "agents" / "ada" / "agent.yaml").is_file() and not (b.home / "agents" / "ada" / "memory.md").exists()
    # the prompt the scrub would change stayed on the PC
    docs = [json.loads(f.read_text()) for f in (tmp_path / "hub" / "learning" / "changes").glob("*.json")]
    assert sorted(d["kind"] for d in docs) == ["prompt", "routing"]
    assert share.others_spent(hub, share.week(), me="phone-beta") == 0.12
    assert share.others_spent(hub, "2001-W01", me="pc-alpha") == 0.0  # another week counts nothing


def test_tools_travel_as_waiting_items_only(tmp_path, hub, monkeypatch):
    from roundtable.improve.lab import KindSpec, register_kind, KINDS

    register_kind(KindSpec("tool", lambda p, c: None, lambda p: "a tool", lambda o, pr, p, c: None, needs_role=False))
    try:
        a, b = _both(tmp_path, hub, monkeypatch)
        with a:
            a.lab.add_proposal(Proposal(id="", kind="tool", role="", change={"code": "import os\nos.system('x')"},
                                        rationale=SECRET, risk="medium"))
            a.tick()
        b.tick()
        written = "".join(f.read_text() for f in (tmp_path / "hub").rglob("*.json"))
        assert "os.system" not in written and SECRET not in written
        with b:
            v = ledger.view(b.cfg, b.lab, B)
        assert len(v["waiting"]) == 1 and not v["waiting"][0]["can_apply"]
        assert not b.lab.proposals()
    finally:
        KINDS.pop("tool", None)


def test_tick_respects_the_setting_and_never_fails_the_sync(tmp_path, hub, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    app = SimpleNamespace(hub=hub, hub_lock=None, cfg=lambda: cfg, _backup_home=lambda: tmp_path / "home")
    assert share.tick(SimpleNamespace(hub=None)) == {}
    out = share.tick(app)
    assert "state" in out
    cfg.sections = {**(getattr(cfg, "sections", None) or {}), "learning": {"share": False}}
    assert share.tick(app) == {"off": True}
    cfg.sections["learning"] = {}
    monkeypatch.setattr(share, "share_round", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert share.tick(app)["error"].startswith("learning: boom")


def test_share_never_changes_what_the_charter_protects(tmp_path, hub, monkeypatch):
    a, b = _both(tmp_path, hub, monkeypatch)
    a.apply("routing", {"models": ["b/coder2", "a/coder"]}, "2026-11-27T10:00:01Z")
    _round(a, b)
    for m in (a, b):
        files = {p.name for p in m.lab.root.parent.rglob("*") if p.is_file()}
        assert "harness.yaml" not in files and "custom.yaml" not in files
    import inspect

    src = inspect.getsource(share)
    for word in ("save_custom", "makers_allowed", "providers_allowed", "write_text(yaml"):
        assert word not in src
    assert "charter.check(" in src
