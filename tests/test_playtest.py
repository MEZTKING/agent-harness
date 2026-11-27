"""Play-testing (harness/playtest.py): a fake browser, a scripted chooser and the fake Godot; no network, no keys."""

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from roundtable import kinds as K
from roundtable.harness import godot as godotlib
from roundtable.harness import playtest as P
from roundtable.harness.agent import Budget
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.scripted import ScriptedProvider, reply

from .test_godot import fake_godot, game
from .test_harness import RAW, tool_names


# -- a fake browser game ---------------------------------------------------------------------------------------
class FakeGame:
    """Moves a box each time an input goes in; after ``freeze_after`` inputs it stops moving (a planted freeze)."""

    def __init__(self, freeze_after=None, error_at=None, blocked=None):
        self.freeze_after, self.error_at = freeze_after, error_at
        self.moves = self.inputs = 0
        self.opened = None
        self.applied = []
        self.pending = []
        self.blocked = list(blocked or [])
        self.closed = False

    def open(self, url, base):
        self.opened = (url, base)

    def shot(self, path):
        img = Image.new("RGB", (160, 100), (20, 20, 30))
        x = (self.moves * 23) % 140
        ImageDraw.Draw(img).rectangle([x, 30, x + 20, 70], fill=(230, 200, 40))
        img.save(path)

    def apply(self, action, wait_ms):
        self.applied.append(action)
        if action["do"] != "wait":
            self.inputs += 1
            if self.freeze_after is None or self.inputs <= self.freeze_after:
                self.moves += 1
            if self.error_at == self.inputs:
                self.pending.append("Uncaught TypeError: player is undefined")

    def take_errors(self):
        got, self.pending = self.pending, []
        return got

    def close(self):
        self.closed = True


class Scripted:
    """Presses keys in turn, then reports what it was told to (or never reports)."""

    def __init__(self, report=None, report_at=None, never=False):
        self.report = report if report is not None else {"worked": True, "summary": "the box moves", "findings": []}
        self.report_at, self.never = report_at, never
        self.states = []

    def __call__(self, state):
        self.states.append(state)
        if not self.never and (state["final"] or state["turn"] == self.report_at):
            return {"report": self.report}
        return {"do": {"do": "tap", "key": ["ArrowRight", "Space", "ArrowLeft"][state["turn"] % 3]}}


def test_a_good_play_passes_with_its_pictures_saved(tmp_path):
    g, ch = FakeGame(), Scripted(report={"worked": True, "summary": "the box moves", "findings": [
        {"what": "a sound when it jumps would help", "severity": "idea", "when": "turn 3"}]})
    got = P.play_browser("http://127.0.0.1:1/index.html", "http://127.0.0.1:1/", 12, 6, ch, tmp_path, driver=g)
    assert got["passed"] is True and got["frozen"] is None and got["errors"] == []
    assert got["pictures"] == [f"turn-{i:02d}.png" for i in range(1, 7)]
    assert all((tmp_path / p).is_file() for p in got["pictures"])
    assert g.opened == ("http://127.0.0.1:1/index.html", "http://127.0.0.1:1/") and g.closed
    assert len(g.applied) == 5 and ch.states[-1]["final"] and "turn 1: tapped Space" in ch.states[-1]["history"]
    assert got["words"] == "Played for 12 seconds: it worked – the box moves (1 idea for you)"


def test_a_game_whose_screen_never_changes_is_reported_frozen(tmp_path):
    ch = Scripted()  # the model even says it worked: the harness's own eyes still catch the freeze
    got = P.play_browser("http://x/", "http://x/", 30, 10, ch, tmp_path, driver=FakeGame(freeze_after=3))
    assert got["passed"] is False and got["frozen"] == 5
    broken = [f for f in got["findings"] if f["severity"] == "broken"]
    assert broken[0]["what"].startswith("The screen stopped changing at turn 5") and broken[0]["by"] != "model"
    assert got["words"].startswith("Played for 30 seconds: The screen stopped changing")
    # waiting on one screen isn't a freeze: only turns where an input went in count
    assert P.frozen_at([None, 0.0, 0.0, 0.0, 0.0], [False, False, False, False, False]) is None
    assert P.frozen_at([None, 0.2, 0.0, 0.0, 0.0], [False, True, True, True, True]) == 3


def test_a_console_error_fails_the_play(tmp_path):
    got = P.play_browser("http://x/", "http://x/", 12, 6, Scripted(), tmp_path, driver=FakeGame(error_at=2))
    assert got["passed"] is False and got["errors"] == ["Uncaught TypeError: player is undefined"]
    assert "The console showed an error: Uncaught TypeError" in got["words"]


def test_the_model_saying_it_didnt_work_fails_it_even_without_a_finding(tmp_path):
    ch = Scripted(report={"worked": False, "summary": "the jump key does nothing", "findings": []})
    got = P.play_browser("http://x/", "http://x/", 12, 4, ch, tmp_path, driver=FakeGame())
    assert got["passed"] is False and got["findings"][0] == {"what": "the jump key does nothing", "severity": "broken",
                                                               "when": "", "by": "model"}


def test_outside_addresses_are_listed_not_counted_as_the_games_errors(tmp_path):
    got = P.play_browser("http://x/", "http://x/", 12, 4, Scripted(), tmp_path,
                         driver=FakeGame(blocked=["https://tracker.example/pixel.gif"]))
    assert got["passed"] is True and got["blocked"] == ["https://tracker.example/pixel.gif"]
    assert [f["severity"] for f in got["findings"]] == ["rough"]


def test_the_turn_cap_holds_and_no_report_is_never_a_pass(tmp_path):
    ch = Scripted(never=True)
    got = P.play_browser("http://x/", "http://x/", 600, 99, ch, tmp_path, driver=FakeGame())
    assert len(ch.states) == P.MAX_TURNS and got["passed"] is None and got["why"] == "no_report"
    assert got["words"] == "Not played: the model that played it gave no report"


def test_without_playwright_it_stays_unchecked(tmp_path, monkeypatch):
    def none():
        raise P.NoDriver("Playwright for Python isn't installed")

    monkeypatch.setattr(P, "PlaywrightDriver", none)
    got = P.play_browser("http://x/", "http://x/", 12, 4, Scripted(), tmp_path)
    assert got["passed"] is None and got["why"] == "no_playwright" and "Playwright" in got["words"]


def test_actions_and_reports_are_cleaned():
    assert P.clean_action({"do": "hold", "key": "Space", "ms": 99999}) == {"do": "hold", "key": "Space", "ms": 3000}
    assert P.clean_action({"do": "tap", "key": "rm -rf"}) == {"do": "wait", "ms": 0}
    assert P.clean_action({"do": "click", "x": -5, "y": 9000}) == {"do": "click", "ms": 0, "x": 0, "y": 799}
    assert P.clean_action("nonsense") == {"do": "wait", "ms": 0}
    r = P.clean_report({"worked": "yes", "summary": "ok", "findings": [{"what": "x", "severity": "awful"}, {"what": ""}]})
    assert r["worked"] is True and r["findings"] == [{"what": "x", "severity": "rough", "when": "", "by": "model"}]


def test_settings_and_a_shorter_play():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    s = P.Settings.from_config(cfg)
    assert (s.enabled, s.seconds, s.turns, s.max_usd) == ("auto", 60, 12, 0.30)
    assert s.for_seconds(20) == (20, 4, 0.1) and s.for_seconds(600) == (60, 12, 0.3)
    raw = {**json.loads(json.dumps(RAW)), "playtest": {"enabled": False, "turns": 500, "max_usd": 0.1}}
    s2 = P.Settings.from_config(parse_config(raw))
    assert not s2.on and s2.turns == P.MAX_TURNS and s2.max_usd == 0.1


# -- the seeing model as the chooser ------------------------------------------------------------------------------
def seeing(raw=None, plan=None):
    cfg = parse_config(json.loads(json.dumps(raw or RAW)))
    seen = []
    plan = list(plan or [])

    def brain(model, system, messages, tools):
        names = tool_names(tools)
        seen.append({"model": model, "tools": names, "messages": messages})
        if names == {"report_play"}:
            return reply(calls=[("report_play", {"worked": True, "summary": "it plays", "findings": []})])
        return reply(calls=[plan.pop(0) if plan else ("play_input", {"do": "tap", "key": "ArrowRight"})])

    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    return cfg, seen


def test_the_model_chooser_plays_then_reports_and_charges_the_run(tmp_path):
    cfg, seen = seeing()
    budget = Budget(5.0)
    ch = P.ModelChooser(cfg, cfg.roles["reviewer"].models[0], budget, 0.30, goal="a box that moves")
    got = P.play_browser("http://x/", "http://x/", 12, 4, ch, tmp_path, driver=FakeGame())
    assert got["passed"] is True and ch.calls == 4
    assert [s["tools"] for s in seen] == [{"play_input", "report_play"}] * 3 + [{"report_play"}]
    images = [c for c in seen[0]["messages"][0]["content"] if c["type"] == "image"]
    assert len(images) == 1 and "a box that moves" in seen[0]["messages"][0]["content"][0]["text"]
    assert budget.spent_usd == pytest.approx(ch.spent) and 0 < ch.spent <= 0.30


def test_the_money_cap_holds_and_keeps_enough_for_the_report(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["pricing"]["a/reviewer"] = {"input": 10, "output": 10}  # about two cents a turn
    cfg, seen = seeing(raw)
    ch = P.ModelChooser(cfg, cfg.roles["reviewer"].models[0], Budget(5.0), 0.06)
    got = P.play_browser("http://x/", "http://x/", 60, 12, ch, tmp_path, driver=FakeGame())
    assert ch.spent <= 0.06 and ch.calls < 12 and got["passed"] is True  # it reported early, within the cap
    assert seen[-1]["tools"] == {"report_play"}
    # too dear for even one look: nothing is spent and nothing passes
    cfg2, seen2 = seeing(raw)
    ch2 = P.ModelChooser(cfg2, cfg2.roles["reviewer"].models[0], Budget(5.0), 0.001)
    got2 = P.play_browser("http://x/", "http://x/", 60, 12, ch2, tmp_path / "two", driver=FakeGame())
    assert seen2 == [] and got2["passed"] is None and got2["why"] == "money"
    # the run's own money is used up
    cfg3, seen3 = seeing()
    ch3 = P.ModelChooser(cfg3, cfg3.roles["reviewer"].models[0], Budget(1.0, spent_usd=1.0), 0.3)
    got3 = P.play_browser("http://x/", "http://x/", 60, 12, ch3, tmp_path / "three", driver=FakeGame())
    assert seen3 == [] and got3["why"] == "budget" and got3["words"].endswith("the run's money limit is reached")


# -- Godot ----------------------------------------------------------------------------------------------------------
GAME_INPUT = ('\n[input]\n\nmove_left={\n"deadzone": 0.5,\n"events": []\n}\njump={\n"deadzone": 0.5,\n"events": []\n}\n')


@pytest.fixture
def screen(monkeypatch):
    monkeypatch.setattr(godotlib, "display_prefix", lambda: [])


def godot_game(folder, still=False):
    g = game(folder)
    with open(g / "project.godot", "a", encoding="utf-8") as f:
        f.write(GAME_INPUT)
    if still:
        (g / "still.marker").write_text("", encoding="utf-8")
    return g


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_the_godot_actions_and_the_plan():
    acts = godotlib.input_actions(Path("/nowhere"))
    assert acts == list(godotlib.DEFAULT_ACTIONS)
    plan = godotlib.play_schedule(["jump", "move_left"], 3, fps=10)
    assert plan[0] == {"frame": 5, "action": "jump", "pressed": True} and plan[1]["frame"] == 7
    assert all(e["frame"] < 30 for e in plan) and "jump held 0.2 s" in godotlib.schedule_text(plan)


def test_a_godot_play_injects_its_inputs_from_outside_the_project_and_cleans_up(tmp_path, screen, monkeypatch):
    g = godot_game(tmp_path / "proj")
    exe = fake_godot(tmp_path / "bin")
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_GODOT_LOG", str(log))
    before = snapshot(g)
    ch = Scripted()
    got = P.play_godot(g, str(exe), 6, ch, tmp_path / "out", turns=5)
    [args] = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    driver = Path(args[args.index("--script") + 1])
    inputs = Path(next(a for a in args if a.startswith(godotlib.INPUT_FLAG))[len(godotlib.INPUT_FLAG):])
    for p in (driver, inputs):
        assert not p.is_relative_to(g) and not p.exists() and not p.parent.exists()  # outside, and removed
    assert args[args.index("--quit-after") + 1] == "60" and args[args.index("--") + 1].startswith("--harness-input=")
    assert snapshot(g) == before  # the project's files are untouched
    assert got["passed"] is True and got["pictures"] == [f"turn-{i:02d}.png" for i in range(1, 6)]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == got["pictures"]  # the other frames are gone
    assert got["actions"][:2] == ["move_left", "jump"]
    [state] = ch.states
    assert len(state["pictures"]) == 4 and any("jump held" in h for h in state["history"])


def test_a_frozen_or_broken_godot_game_fails(tmp_path, screen):
    exe = fake_godot(tmp_path / "bin")
    frozen = P.play_godot(godot_game(tmp_path / "still", still=True), str(exe), 6, Scripted(), tmp_path / "o1", turns=6)
    assert frozen["passed"] is False and frozen["frozen"] == 2
    broken_dir = godot_game(tmp_path / "broken")
    (broken_dir / "broken.gd").write_text("oops\n", encoding="utf-8")
    broken = P.play_godot(broken_dir, str(exe), 6, Scripted(), tmp_path / "o2", turns=4)
    assert broken["passed"] is False and broken["errors"][0].startswith("SCRIPT ERROR: Parse Error")


def test_godot_with_no_screen_stays_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(godotlib, "display_prefix", lambda: None)
    got = P.play_godot(godot_game(tmp_path / "g"), str(fake_godot(tmp_path / "bin")), 6, Scripted(), tmp_path / "o")
    assert got["passed"] is None and got["why"] == "no_display"


def test_the_godot_test_command(tmp_path):
    g = game(tmp_path / "g")
    assert godotlib.test_command(g) is None
    (g / "addons" / "gut").mkdir(parents=True)
    (g / "addons" / "gut" / "gut_cmdln.gd").write_text("", encoding="utf-8")
    assert godotlib.test_command(g, "godot4")[:2] == ["godot4", "--headless"] and "-gexit" in godotlib.test_command(g)


# -- the stage ------------------------------------------------------------------------------------------------------
class O(Orchestrator):
    pass


def stage(tmp_path, raw=None, kind="browser-game"):
    cfg, seen = seeing(raw)
    img = __import__("roundtable.providers.scripted", fromlist=["ScriptedImages"]).ScriptedImages()
    cfg.register("img", img)
    events = []
    orch = O(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    orch.project.dir.mkdir(parents=True, exist_ok=True)
    orch.project.save_meta({"goals": ["a box that moves"], "kind": {"id": kind, "extras": []}})
    return orch, seen, events


def test_the_stage_plays_the_page_and_gives_evidence(tmp_path):
    orch, seen, events = stage(tmp_path)
    (orch.project.root / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    orch.play_driver = FakeGame()
    got = orch._play_check({"id": "plays", "how": "play", "seconds": 20})
    assert got["passed"] is True and got["words"].startswith("Played for 20 seconds: it worked")
    ev = got["evidence"]
    assert ev["pictures"][0] == ".harness/play/goal-1/plays/turn-01.png" and len(ev["pictures"]) == 4
    assert (orch.project.root / ev["pictures"][0]).is_file() and ev["cost_usd"] > 0
    assert orch.play_driver.opened[0].startswith("http://127.0.0.1:") and orch.play_driver.opened[0].endswith("/index.html")
    rec = P.read_record(orch.project.root, 0, "plays")
    assert rec["passed"] is True and rec["dir"] == ".harness/play/goal-1/plays"
    assert any(k == "play" for k, _ in events)


def test_the_stage_with_a_planted_freeze_fails_then_passes_once_fixed(tmp_path):
    orch, seen, events = stage(tmp_path)
    (orch.project.root / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    orch.play_driver = FakeGame(freeze_after=2)
    first = orch._play_check({"id": "plays", "how": "play", "seconds": 60})
    assert first["passed"] is False and first["evidence"]["broken"][0].startswith("The screen stopped changing")
    orch.play_driver = FakeGame()  # the fix task made the game move again
    again = orch._play_check({"id": "plays", "how": "play", "seconds": 60})
    assert again["passed"] is True and again["evidence"]["broken"] == []


def test_the_stage_with_no_seeing_model_is_unchecked_never_passed(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["ds"] = {"type": "openai_compat", "base_url": "https://example.invalid"}
    raw["roles"]["reviewer"] = {"model": "ds/deepseek-v4-flash"}
    orch, seen, _ = stage(tmp_path, raw)
    (orch.project.root / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    orch.play_driver = FakeGame()
    got = orch._play_check({"id": "plays", "how": "play"})
    assert got["passed"] is None and seen == [] and "none of the models can see" in got["words"]
    est = orch._play_estimate([])
    assert est["usd"] == 0.0 and "none of the models can see" in est["words"]


def test_the_stage_when_playing_is_off_or_there_is_no_page(tmp_path):
    raw = {**json.loads(json.dumps(RAW)), "playtest": {"enabled": "off"}}
    orch, *_ = stage(tmp_path / "off", raw)
    assert orch._play_check({"id": "plays", "how": "play"})["passed"] is None and orch._play_estimate([]) is None
    orch2, *_ = stage(tmp_path / "empty")
    assert "no index.html" in orch2._play_check({"id": "plays", "how": "play"})["words"]


def test_the_estimate_line_only_for_kinds_with_a_play_check(tmp_path):
    orch, *_ = stage(tmp_path / "game")
    est = orch._play_estimate([])
    assert est["id"] == "play" and est["usd"] == pytest.approx(0.30) and "up to $0.30" in est["words"]
    orch2, *_ = stage(tmp_path / "site", kind="website")
    assert orch2._play_estimate([]) is None
    orch3, *_ = stage(tmp_path / "godot", kind="godot-game")
    assert orch3._play_estimate([])["usd"] == pytest.approx(0.40)  # 20 seconds and a minute


def test_the_stage_plays_a_godot_game_through_the_workspace(tmp_path, screen, monkeypatch):
    exe = fake_godot(tmp_path / "bin")
    raw = {**json.loads(json.dumps(RAW)), "godot": {"path": str(exe)}}
    orch, seen, _ = stage(tmp_path, raw, kind="godot-game")
    godot_game(orch.project.root)
    ran = []
    real = orch.ws.run_command
    monkeypatch.setattr(orch.ws, "run_command", lambda a: ran.append(a["command"]) or real(a))
    got = orch._play_check({"id": "starts", "how": "play", "seconds": 20})
    assert got["passed"] is True and got["evidence"]["kind"] == "godot" and len(got["evidence"]["pictures"]) == 4
    assert len(ran) == 1 and "--write-movie" in ran[0] and "--harness-input=" in ran[0]
    assert seen[-1]["tools"] == {"report_play"}


def test_rough_findings_and_ideas_go_to_the_owner_not_to_the_builders(tmp_path):
    orch, *_ = stage(tmp_path)
    (orch.project.root / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    orch.play_driver = FakeGame()
    notes = []
    orch._journal = lambda kind, text, **kw: notes.append((text, kw.get("details", "")))
    cfg = orch.cfg
    cfg.register("a", ScriptedProvider("a", lambda m, s, msgs, tools: reply(calls=[("report_play", {
        "worked": True, "summary": "fun", "findings": [{"what": "the jump feels floaty", "severity": "rough"},
                                                      {"what": "add a high score", "severity": "idea"}]})])))
    got = orch._play_check({"id": "plays", "how": "play", "seconds": 20})
    assert got["passed"] is True and [f["what"] for f in got["evidence"]["ideas"]] == ["the jump feels floaty",
                                                                                     "add a high score"]
    assert notes and "add a high score" in notes[0][1]


# -- the kind -------------------------------------------------------------------------------------------------------
def test_the_godot_kind_loads_is_proposed_and_on_trial():
    cat = K.load_all(None)
    assert cat.problems == []
    k = cat.kinds["godot-game"]
    assert k.needs == ["godot"] and k.spec["look"] == "art" and set(k.prompts) == {"orchestrator", "coder", "reviewer"}
    assert [(i["id"], i["how"]) for i in K.proof_plan(k)] == [("imports", "command"), ("starts", "play"),
                                                             ("plays", "play")]
    assert K.propose("a Godot platformer", cat)[0][0] == "godot-game"
    assert K.propose("a tiny platformer with three levels", cat)[0][0] == "browser-game"
    assert K.status_words(k, None) == "On trial"
    plays = next(i for i in K.proof_plan(cat.kinds["browser-game"]) if i["id"] == "plays")
    assert plays["status"] == "trial"
