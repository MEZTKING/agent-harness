"""The phone and the PC as one Roundtable (sync.py): two hubs on one made-up git remote stand for the two
machines."""

import json
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

from roundtable import sync
from roundtable.core.config import load_config as load_hub
from roundtable.core.store import GitStore
from roundtable.harness.orchestrator import HarnessError
from roundtable.hub.service import Hub
from roundtable.phone import phone_allowed

from .test_harness import RAW, make

AGENTS = {"me": {"description": "the owner"}, "harness": {"description": "Roundtable's projects"},
          "bakery": {"description": "a made-up shop"}}
RULES = [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def remote(tmp_path):
    """A hub repository with its own hub.yaml (with a comment the owner wrote)."""
    bare = tmp_path / "hub.git"
    _git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    _git("clone", "-q", str(bare), str(seed), cwd=tmp_path)
    text = "# the owner's own note\ndefault_policy: deny\nagents:\n" + "".join(
        f"  {a}:\n    description: {spec['description']}\n" for a, spec in AGENTS.items()) + \
        "rules:\n- from: '*'\n  to: '*'\n  allow: [read_card, message]\n"
    (seed / "hub.yaml").write_text(text, encoding="utf-8")
    _git("add", ".", cwd=seed)
    _git("commit", "-qm", "init", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)
    return bare


def machine_hub(tmp_path, remote, name) -> Path:
    """One machine's hub.yaml: where its clone of the hub repository is."""
    d = tmp_path / name
    d.mkdir()
    cfg = {"storage": {"type": "git", "path": str(d / "hub"), "remote": str(remote), "sync_interval": 0},
           "default_policy": "deny", "agents": {"me": {}}, "rules": RULES}
    (d / "hub.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return d / "hub.yaml"


def hub_for(path: Path) -> Hub:
    return Hub(load_hub(str(path)))


def be(monkeypatch, mid, name=None):
    monkeypatch.setenv(sync.MACHINE_ENV, mid)
    if name:
        monkeypatch.setenv(sync.MACHINE_NAME_ENV, name)
    else:
        monkeypatch.delenv(sync.MACHINE_NAME_ENV, raising=False)


PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}
PHONE = {"id": "phone-1a2b3c", "name": "Phone (OPPO)", "kind": "phone"}


# -- seats ---------------------------------------------------------------------------------------------
def test_the_phone_joins_the_hub_as_its_own_seat(tmp_path, remote):
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    assert sync.register_seat(phone, PHONE["id"], PHONE["name"], "phone") is True
    assert sync.register_seat(phone, PHONE["id"], PHONE["name"], "phone") is False  # idempotent
    text = (sync.hub_root(phone) / "hub.yaml").read_text(encoding="utf-8")
    assert text.startswith("# the owner's own note") and text.count("phone-1a2b3c:") == 1
    # the PC sees it after its next sync, as a machine (not a project)
    pc.store.sync(force=True)
    pc.refresh_config()
    spec = pc.config.agents[PHONE["id"]]
    assert spec.title == "Phone (OPPO)" and spec.role == "machine" and "phone" in spec.tags
    assert set(AGENTS) <= set(pc.config.agents)  # nothing of the owner's was lost
    assert sync.register_seat(pc, PC["id"], PC["name"], "pc") is True
    phone.store.sync(force=True)
    phone.refresh_config()
    assert {PC["id"], PHONE["id"]} <= set(phone.config.agents)


def test_a_hub_without_hub_yaml_starts_from_this_machines_projects(tmp_path):
    bare = tmp_path / "empty.git"
    _git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    hub = hub_for(machine_hub(tmp_path, bare, "pc"))
    assert sync.register_seat(hub, PC["id"], PC["name"])
    raw = yaml.safe_load((sync.hub_root(hub) / "hub.yaml").read_text(encoding="utf-8"))
    assert set(raw["agents"]) == {"me", PC["id"]} and "storage" not in raw


def test_this_machine(monkeypatch):
    monkeypatch.delenv(sync.MACHINE_ENV, raising=False)
    monkeypatch.setattr(sync.socket, "gethostname", lambda: "Desk-01.local")
    assert sync.this_machine() == {"id": "pc-desk-01", "name": "PC (DESK-01)", "kind": "pc"}
    be(monkeypatch, "phone-1a2b3c", "Phone (OPPO)")
    assert sync.this_machine() == PHONE
    assert sync.phone_title("  OPPO  Find ") == "Phone (OPPO Find)" and sync.phone_title("") == "Phone"


# -- which project ----------------------------------------------------------------------------------------
def test_the_same_project_on_two_machines_has_one_key(tmp_path):
    keys = []
    for i, url in enumerate(["https://github.com/someone/shop-app.git", "git@github.com:someone/shop-app",
                             "https://x-access-token:abc@github.com/Someone/shop-app/"]):
        d = tmp_path / f"clone{i}"
        (d / "web").mkdir(parents=True)
        _git("init", "-q", cwd=d)
        _git("remote", "add", "origin", url, cwd=d)
        keys.append(sync.project_key(d / "web", f"harness--web{i}"))
    assert len(set(keys)) == 1 and keys[0].startswith("someone-shop-app-web-")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sync.project_key(plain, "harness--bakery") == "harness-bakery"


# -- claims --------------------------------------------------------------------------------------------
def test_one_machine_builds_a_project_at_a_time(tmp_path, remote):
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    mine = sync.Claim(pc, "harness-bakery", "run1", PC, hub_name="harness--bakery", folder="bakery")
    assert mine.take() == ""
    other = sync.Claim(phone, "harness-bakery", "run2", PHONE, hub_name="harness--bakery", folder="bakery")
    with pytest.raises(sync.ClaimedElsewhere, match=r"being built on PC \(DESK\)"):
        other.take()
    # no heartbeat for over 10 minutes: stale, the phone may take it (and says so)
    rec = mine.record()
    rec["heartbeat"] = "2020-01-01T00:00:00Z"
    pc.store.write_json({mine.path: rec}, "old")
    note = other.take()
    assert note.startswith("Took over from PC (DESK)") and "no news" in note
    pc.store.sync(force=True)
    assert mine.beat() is None and mine.lost  # the PC learns it has been taken over
    pc.store.write_json({other.path: other.released("done")}, "release")
    phone.store.sync(force=True)
    c = phone.store.read_json(other.path)
    assert c["state"] == "released" and c["machine"] == PHONE["id"] and c["status"] == "done"
    assert not sync.claim_fresh(c)
    assert mine.take() == ""  # released: anyone may build it


def test_two_claims_at_once_the_first_one_stays(tmp_path, remote):
    """Both machines claim before seeing each other's: the claim that reached the hub first stays, and the
    pull never stops half-way."""
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    pc.store.sync(force=True)
    phone.store.sync(force=True)
    a = sync.Claim(pc, "k", "run-a", PC, folder="bakery")
    b = sync.Claim(phone, "k", "run-b", PHONE, folder="bakery")
    # the phone writes its claim while offline (committed, not pushed) ...
    root = sync.hub_root(phone)
    (root / "claims").mkdir()
    (root / "claims" / "k.json").write_text(json.dumps(b.record()), encoding="utf-8")
    _git("add", ".", cwd=root)
    _git("commit", "-qm", "phone claims", cwd=root)
    # ... and one of its own files clashes too: there, this machine's newer copy wins
    pc.store.write_json({"state/me.json": {"read": ["from-pc"], "subscriptions": []}}, "pc")
    (root / "state").mkdir(exist_ok=True)
    (root / "state" / "me.json").write_text(json.dumps({"read": ["from-phone"], "subscriptions": []}), encoding="utf-8")
    _git("add", ".", cwd=root)
    _git("commit", "-qm", "phone reads", cwd=root)
    a.take()  # the PC's claim reaches the hub first
    phone.store.sync(force=True)  # the phone's pull settles both clashes by itself
    assert not (root / ".git" / "rebase-merge").exists() and not (root / ".git" / "rebase-apply").exists()
    assert phone.store.read_json("claims/k.json")["machine"] == PC["id"]
    assert phone.store.read_json("state/me.json")["read"] == ["from-phone"]
    with pytest.raises(sync.ClaimedElsewhere):
        b.take()


def test_concurrent_pushes_lose_nothing(tmp_path, remote):
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    errors = []

    def write(hub, who):
        try:
            for i in range(4):
                hub.store.write_json({f"sessions/k/{who}-{i}.jsonl": {"n": i}}, f"{who} {i}")
                sync.write_heartbeat(hub, PC if who == "pc" else PHONE, force=True)
        except Exception as e:  # pragma: no cover - the test fails below
            errors.append(e)

    threads = [threading.Thread(target=write, args=(pc, "pc")), threading.Thread(target=write, args=(phone, "phone"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    check = hub_for(machine_hub(tmp_path, remote, "check"))
    check.store.sync(force=True)
    root = sync.hub_root(check)
    assert len(list((root / "sessions" / "k").glob("*.jsonl"))) == 8
    assert {p.stem for p in (root / "machines").glob("*.json")} == {PC["id"], PHONE["id"]}


# -- a run: claim, live session, release --------------------------------------------------------------
def harness_with_hub(tmp_path, hub_yaml, name="proj"):
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(hub_yaml), "agent": "harness"}
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    orch, *_ = make(d, raw=hraw)
    return orch


def test_a_run_holds_the_project_and_publishes_its_session(tmp_path, remote, monkeypatch):
    be(monkeypatch, PC["id"], PC["name"])
    orch = harness_with_hub(tmp_path, machine_hub(tmp_path, remote, "pc"))
    orch.start("a bakery site")
    assert orch.run() == "done"
    hub = orch._hub()
    hub.store.sync(force=True)
    key = sync.project_key(orch.project.root, orch._hub_name())
    claim = hub.store.read_json(f"claims/{key}.json")
    assert claim["state"] == "released" and claim["machine"] == PC["id"] and claim["status"] == "done"
    # the phone reads the run's lines from its own copy of the hub
    phone = hub_for(machine_hub(tmp_path, remote, "phone"))
    phone.store.sync(force=True)
    out = sync.sessions(phone, orch._hub_name())
    assert out["key"] == key and len(out["runs"]) == 1 and out["live"] is False
    run = out["run"]
    assert run["machine_name"] == "PC (DESK)" and run["status"] == "done" and run["cost_usd"] > 0
    kinds = [ln["kind"] for ln in run["events"]]
    assert kinds[0] == "run_started" and kinds[-1] == "run_done"
    assert {"task_started", "change", "review", "task_done", "cost"} <= set(kinds)
    assert all(ln.get("line") for ln in run["events"])  # every line has its text
    started = next(ln for ln in run["events"] if ln["kind"] == "task_started")
    assert started["task"] == "T1" and started["index"] == 1 and started["total"] == 3
    review = next(ln for ln in run["events"] if ln["kind"] == "review")
    assert review["approved"] and review["verdict"] == "approved"
    assert run["cost_usd"] == round(sum(ln["usd"] for ln in run["events"] if ln["kind"] == "cost"), 6)
    tool = next(ln for ln in run["events"] if ln["kind"] == "change")
    assert tool["path"] == "hello.py" and tool["line"].startswith("● Write hello.py") and tool["line"].endswith("+1 −0") and "print(" not in json.dumps(run["events"])  # no contents
    later = sync.sessions(phone, orch._hub_name(), since=len(run["events"]) - 1)
    assert [ln["kind"] for ln in later["events"]] == ["run_done"]


def test_a_run_refuses_while_another_machine_builds_it(tmp_path, remote, monkeypatch):
    be(monkeypatch, PHONE["id"], PHONE["name"])
    orch = harness_with_hub(tmp_path, machine_hub(tmp_path, remote, "phone"))
    orch.start("a bakery site", require_approval=True)
    orch.approve()
    pc = hub_for(machine_hub(tmp_path, remote, "pc"))
    key = sync.project_key(orch.project.root, orch._hub_name())
    sync.Claim(pc, key, "pc-run", PC, hub_name=orch._hub_name(), folder="proj").take()
    with pytest.raises(HarnessError, match=r"being built on PC \(DESK\)"):
        orch.run()
    assert all(t.status == "pending" for t in orch.project.tasks())  # nothing was spent or changed


def test_a_run_pauses_when_taken_over(tmp_path, remote, monkeypatch):
    be(monkeypatch, PC["id"], PC["name"])
    orch = harness_with_hub(tmp_path, machine_hub(tmp_path, remote, "pc"))
    orch.start("a bakery site")
    real = orch._run_task

    def first_then_taken(task, tasks):
        ok = real(task, tasks)
        orch._live.claim.lost = True  # as if the phone took it over after a stale heartbeat
        return ok

    orch._run_task = first_then_taken
    assert orch.run() == "paused"
    assert orch.project.meta()["pause"] == "elsewhere"
    assert sum(t.status == "done" for t in orch.project.tasks()) == 1


def test_only_the_last_three_runs_are_kept(tmp_path, remote, monkeypatch):
    be(monkeypatch, PC["id"], PC["name"])
    hub = hub_for(machine_hub(tmp_path, remote, "pc"))
    for i in range(5):
        c = sync.Claim(hub, "k", f"2026112{i}T000000Z-pc-desk-0000", PC, hub_name="harness--k", folder="k")
        c.take()
        live = sync.LiveRun(hub, c).start()
        live.add("task_start", {"task": "T1", "title": "t", "role": "coder"})
        live.stop("done")
    runs = sorted(p.stem for p in (sync.hub_root(hub) / "sessions" / "k").glob("*.jsonl"))
    assert len(runs) == 3 and runs[0].startswith("20261122")


def test_session_api_for_the_desktop_and_the_phone(tmp_path, remote, monkeypatch):
    from roundtable.ui.server import UIApp

    be(monkeypatch, PC["id"], PC["name"])
    hub = hub_for(machine_hub(tmp_path, remote, "pc"))
    c = sync.Claim(hub, "harness-bakery", "run1", PC, hub_name="harness--bakery", folder="bakery")
    c.take()
    live = sync.LiveRun(hub, c).start()
    live.add("tool_call", {"tool": "run_command", "args": {"command": "pytest"}, "output": "exit code: 0"})
    live.flush()
    app = UIApp(str(machine_hub(tmp_path, remote, "phone")), "missing.yaml", agent="me")
    out = app.dispatch("GET", "/api/hub/session", {"name": ["harness--bakery"]}, {})
    assert out["live"] is True and out["claim"]["machine_name"] == "PC (DESK)"
    assert out["run"]["events"][-1]["line"].startswith("● Run `pytest`")
    by_folder = app.dispatch("GET", "/api/hub/session", {"name": ["bakery"]}, {})
    assert by_folder["key"] == "harness-bakery"
    none = app.dispatch("GET", "/api/hub/session", {"name": ["nothing"]}, {})
    assert none["runs"] == [] and "No build" in none["message"]
    live.stop("paused")
    for route in [("GET", "/api/hub/session"), ("GET", "/api/machines"), ("GET", "/api/hub/plan"),
                  ("POST", "/api/hub/command"), ("POST", "/api/hub/carry_on"), ("GET", "/api/settings/shared"),
                  ("POST", "/api/settings/shared")]:
        assert phone_allowed(*route), route


def test_session_lines_hide_keys():
    line = sync.session_line("model_turn", {"model": "a/b", "text": "my key is sk-ant-api03-" + "x" * 40, "cost": 0.1})
    assert "sk-ant" not in json.dumps(line)


# -- machines --------------------------------------------------------------------------------------------
def test_machines_say_who_is_on_and_what_it_builds(tmp_path, remote, monkeypatch):
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    sync.register_seat(pc, PC["id"], PC["name"], "pc")
    sync.register_seat(phone, PHONE["id"], PHONE["name"], "phone")
    sync.write_heartbeat(pc, PC, listening=True)
    assert sync.write_heartbeat(pc, PC, listening=True) is False  # nothing new: no commit
    sync.Claim(pc, "harness-bakery", "r", PC, hub_name="harness--bakery", folder="bakery").take()
    phone.store.sync(force=True)
    phone.refresh_config()
    ms = {m["id"]: m for m in sync.machines(phone, PHONE)}
    assert ms[PC["id"]]["online"] and ms[PC["id"]]["listening"]
    assert ms[PC["id"]]["seat"] == PC["id"]
    [c] = sync.claims_list(phone)
    assert c["project"] == "harness--bakery" and c["machine_name"] == "PC (DESK)" and c["heartbeat"]
    assert ms[PC["id"]]["building"][0]["folder"] == "bakery"
    assert ms[PC["id"]]["state"] == "Your PC is building bakery."
    assert ms[PHONE["id"]]["this"] and ms[PHONE["id"]]["state"] == "This phone is on."
    old = pc.store.read_json(f"machines/{PC['id']}.json")
    old["last_seen"] = "2020-01-01T00:00:00Z"
    pc.store.write_json({f"machines/{PC['id']}.json": old}, "long ago")
    phone.store.sync(force=True)
    pc_seat = next(m for m in sync.machines(phone, PHONE) if m["id"] == PC["id"])
    assert pc_seat["online"] is False and pc_seat["state"] == "Your PC is off: it'll pick things up when it's on."


def test_auto_sync_adds_the_seat_and_the_heartbeat(tmp_path, remote, monkeypatch):
    from roundtable.ui.roundtable import AutoSync, build
    from roundtable.ui.server import UIApp

    be(monkeypatch, PC["id"], PC["name"])
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "apphome"))
    app = UIApp(str(machine_hub(tmp_path, remote, "pc")), "missing.yaml", agent="me")
    app.cfg = lambda: None  # no harness on this machine
    AutoSync(app).tick()
    assert PC["id"] in app.hub.config.agents and app.auto_sync_error == ""
    beat = app.hub.store.read_json(f"machines/{PC['id']}.json")
    assert beat["name"] == "PC (DESK)" and beat["listening"] is False  # no harness here: commands can't be done
    table = build(app)
    assert all(s["id"] != PC["id"] for s in table["seats"])  # a machine isn't a project
    assert [m["id"] for m in table["machines"]] == [PC["id"]]
    assert table["agent"] == PC["id"] and table["hub_agent"] == "me" and table["machine"]["name"] == "PC (DESK)"
    out = app.dispatch("GET", "/api/machines", {}, {})
    assert out["this"]["id"] == PC["id"] and out["machines"][0]["this"]


# -- commands for one machine, carrying on ----------------------------------------------------------------
def test_a_command_for_another_machine_is_left_for_it(tmp_path, remote, monkeypatch):
    from roundtable.remote import process

    be(monkeypatch, PC["id"], PC["name"])
    orch = harness_with_hub(tmp_path, machine_hub(tmp_path, remote, "pc"))
    orch.cfg.lab_dir = tmp_path / "lab"
    orch.start("a bakery site", require_approval=True)
    hub = orch._hub()
    hub.send("me", "harness", "roundtable: note", json.dumps({"action": "note", "text": "blue", "machine":
                                                              PHONE["id"], "project_folder": "proj"}), kind="request")
    assert process(orch.cfg, hub, log=lambda s: None) == 0
    hub.send("me", "harness", "roundtable: note", json.dumps({"action": "note", "text": "blue", "machine": PC["id"],
                                                              "project_folder": "proj"}), kind="request")
    assert process(orch.cfg, hub, log=lambda s: None) == 1


def test_carry_on_goes_to_the_machine_that_has_the_files(tmp_path, remote, monkeypatch):
    from roundtable.remote import parse
    from roundtable.ui.server import UIApp

    # the phone built part of it, then paused
    be(monkeypatch, PHONE["id"], PHONE["name"])
    phone_yaml = machine_hub(tmp_path, remote, "phone")
    orch = harness_with_hub(tmp_path, phone_yaml)
    orch.start("a bakery site")
    assert orch.run(max_tasks=1) == "paused"
    sync.register_seat(orch._hub(), PHONE["id"], PHONE["name"], "phone")
    name = orch._hub_name()
    # the PC asks it to carry on: the command is for the phone only
    be(monkeypatch, PC["id"], PC["name"])
    app = UIApp(str(machine_hub(tmp_path, remote, "pc")), "missing.yaml", agent="me")
    r = app.dispatch("POST", "/api/hub/carry_on", {}, {"name": name})
    assert r["sent"] and r["reply"].startswith("It's on your phone: asked it to carry on.")
    assert "off – it'll pick this up when it's on" in r["reply"]  # no heartbeat from the phone yet
    from roundtable.ui.roundtable import build

    seat = next(x for x in build(app)["seats"] if x["id"] == "proj")
    assert seat["machine"] == PHONE["id"] and seat["machine_name"] == "Phone (OPPO)"
    [msg] = app.hub.inbox("harness")
    assert parse(msg) == {"action": "carry_on", "machine": PHONE["id"], "project_folder": "proj"}


# -- shared settings --------------------------------------------------------------------------------------
def harness_files(tmp_path, name):
    d = tmp_path / name / "config"
    d.mkdir(parents=True)
    raw = json.loads(json.dumps(RAW))
    raw["profiles"] = {"budget": {"roles": {"coder": {"model": "b/coder2"}}}, "balanced": {"roles": {}}}
    (d / "harness.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return d / "harness.yaml", tmp_path / name / "home"


def test_shared_settings_match_on_every_machine(tmp_path, remote, monkeypatch):
    from roundtable import autopilot
    from roundtable.harness.config import load_config

    monkeypatch.setenv("ROUNDTABLE_NO_BALANCE", "1")
    pc, phone = hub_for(machine_hub(tmp_path, remote, "pc")), hub_for(machine_hub(tmp_path, remote, "phone"))
    pc_h, pc_home = harness_files(tmp_path, "pcfiles")
    ph_h, ph_home = harness_files(tmp_path, "phonefiles")
    assert sync.sync_shared(pc, pc_h, pc_home, machine=PC) == {"gave": True}  # the first machine gives its own
    # the owner changes them on the PC
    out = sync.change_shared(pc, {"limits": {"max_usd_per_day": 3, "max_real_usd_per_run": 1.5},
                                  "autopilot": {"on": True, "cap": 1.25}, "default_profile": "budget",
                                  "roles": {"coder": {"model": "b/coder2", "fallback": ["a/coder"]}}},
                             pc_h, pc_home, machine=PC)
    assert out["settings"]["changed_by_name"] == "PC (DESK)" and "autopilot on" in out["changed"]
    apps = sync.for_apps(out["settings"], ["balanced", "budget"])
    assert apps["roles"] == {"coder": ["b/coder2", "a/coder"]} and apps["updated_by"] == "PC (DESK)"
    assert apps["autopilot"]["on"] and apps["autopilot"]["cap"] == 1.25 and apps["limits"]["max_usd_per_day"] == 3
    # the phone joins: it takes the hub's
    phone.store.sync(force=True)
    took = sync.sync_shared(phone, ph_h, ph_home, machine=PHONE)
    assert took["from"] == "PC (DESK)"
    cfg = load_config(str(ph_h))
    assert cfg.limits.max_usd_per_day == 3 and cfg.limits.max_real_usd_per_run == 1.5 and cfg.limits.max_cost_usd == 5
    assert cfg.default_profile == "budget" and [str(m) for m in cfg.roles["coder"].models] == ["b/coder2", "a/coder"]
    assert autopilot.load(ph_home)["on"] and autopilot.load(ph_home)["spend_cap_usd"] == 1.25
    assert sync.sync_shared(phone, ph_h, ph_home, machine=PHONE) == {}  # nothing new
    # later the owner turns autopilot off on the phone: the PC follows at its next sync
    autopilot.turn_off("back", home=ph_home)
    assert sync.sync_shared(phone, ph_h, ph_home, machine=PHONE) == {"gave": True}
    pc.store.sync(force=True)
    assert sync.sync_shared(pc, pc_h, pc_home, machine=PC)["took"] == ["autopilot off"]
    assert autopilot.load(pc_home)["on"] is False and "Phone (OPPO)" in autopilot.load(pc_home)["stopped"]
    text = (sync.hub_root(pc) / sync.SHARED_FILE).read_text(encoding="utf-8")
    assert "KEY" not in text and "api_key" not in text


def test_a_shared_profile_this_machine_lacks_is_not_applied(tmp_path, remote):
    from roundtable.harness.config import load_config

    hub = hub_for(machine_hub(tmp_path, remote, "pc"))
    h, home = harness_files(tmp_path, "files")
    sync.apply_shared({"default_profile": "quality", "changed_by": "x"}, h, home)
    assert load_config(str(h)).default_profile is None
    with pytest.raises(ValueError):
        sync.change_shared(hub, {"limits": {"max_cost_usd": -1}}, h, home)


def test_the_daily_limit_pauses_a_run(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["limits"]["max_usd_per_day"] = 0.0001
    orch, *_ = make(tmp_path, raw=raw)
    orch.start("a bakery site")
    assert orch.run() == "paused"
    assert orch.project.meta()["pause"] == "money_day"
    assert not any(t.status == "done" for t in orch.project.tasks())  # the plan alone spent today's money


def test_shared_settings_through_the_hub_and_the_api(tmp_path, remote, monkeypatch):
    from roundtable.remote import process
    from roundtable.ui.server import UIApp

    be(monkeypatch, PC["id"], PC["name"])
    monkeypatch.setenv("ROUNDTABLE_NO_BALANCE", "1")
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "apphome"))
    h, _home = harness_files(tmp_path, "files")
    hub_yaml = machine_hub(tmp_path, remote, "pc")
    raw = yaml.safe_load(h.read_text(encoding="utf-8"))
    raw["hub"] = {"config": str(hub_yaml), "agent": "harness"}
    raw["improve"] = {"lab_dir": str(tmp_path / "lab")}
    h.write_text(yaml.safe_dump(raw), encoding="utf-8")
    from roundtable.harness.config import load_config
    from roundtable.harness.orchestrator import Orchestrator

    cfg = load_config(str(h))
    Orchestrator(cfg, tmp_path / "shop").start("a made-up shop", require_approval=True)
    hub = hub_for(hub_yaml)
    hub.send("me", "harness", "roundtable: shared_settings",
             json.dumps({"action": "shared_settings", "project_folder": "shop",
                         "changes": {"roles": {"coder": "b/coder2"}, "limits": {"max_usd_per_day": 4}}}), kind="request")
    assert process(load_config(str(h)), hub, log=lambda s: None) == 1
    reply = hub.inbox("me", unread_only=False)[-1]["body"]
    assert reply.startswith("Shared settings saved for every machine")
    assert load_config(str(h)).limits.max_usd_per_day == 4
    # the API reads them the way the phone wants them
    app = UIApp(str(machine_hub(tmp_path, remote, "phone")), str(h), agent="me")
    got = app.dispatch("GET", "/api/settings/shared", {}, {})
    assert got["roles"]["coder"] == "b/coder2" and got["limits"]["max_usd_per_day"] == 4
    assert got["updated_by"] == "PC (DESK)" and set(got["profiles"]) == {"budget", "balanced"} and got["shared"]
    changed = app.dispatch("POST", "/api/settings/shared", {}, {"changes": {"autopilot": {"on": True, "cap": 1}}})
    assert changed["autopilot"]["on"] and changed["roles"]["coder"] == "b/coder2"
    machines = app.dispatch("GET", "/api/machines", {}, {})
    assert machines["claims"] == [] and machines["this"]["id"] == PC["id"]
