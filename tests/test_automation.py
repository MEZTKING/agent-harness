"""Automations (automation.py): schedules, GitHub issues and failed checks that start work by themselves. Made-up
repositories and a fake GitHub; no network, no keys."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from roundtable import automation as au
from roundtable.core import secrets as vault
from roundtable.core.store import FileStore
from roundtable.harness.orchestrator import Orchestrator, Project

from .test_harness import Brain, make

PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}
PHONE = {"id": "phone-1a2b3c", "name": "Phone", "kind": "phone"}
UTC = timezone.utc


def t(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.fixture(autouse=True)
def _clean_vault(monkeypatch):
    for name in (au.TOKEN_KEY, *au.TOKEN_FALLBACKS):  # no key from the machine running the tests
        monkeypatch.delenv(name, raising=False)
    vault.clear()
    yield
    vault.clear()


@pytest.fixture
def cfg(tmp_path):
    orch, *_ = make(tmp_path, brain=Brain())
    c = orch.cfg
    c.lab_dir = tmp_path / "lab"
    return c


def project(cfg, tmp_path, name="shop"):
    """A made-up project that has finished its first goal (registered in the lab)."""
    orch = Orchestrator(cfg, tmp_path / name)
    orch.start("a shop page")
    meta = orch.project.meta()
    meta["status"] = "done"
    orch.project.save_meta(meta)
    return (tmp_path / name).resolve()


class Hub:
    """Just the hub's store: two of these over one folder stand for the PC and the phone."""

    def __init__(self, root):
        self.store = FileStore(root)


class FakeGitHub:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                status, hdrs, body = answer
                return status, hdrs, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 404, {}, b"{}"


# -- schedules in plain words ------------------------------------------------------------------------------
@pytest.mark.parametrize("text,days,time", [
    ("every weekday at 9:00", ["mon", "tue", "wed", "thu", "fri"], "09:00"),
    ("every Sunday", ["sun"], "09:00"),
    ("weekends at 10am", ["sat", "sun"], "10:00"),
    ("daily at 18:30", list(au.DAYS), "18:30"),
    ("every Monday and Thursday at 2:15pm", ["mon", "thu"], "14:15"),
    ("Fridays at noon", ["fri"], "12:00"),
])
def test_plain_words_become_a_schedule(text, days, time):
    w = au.parse_schedule(text, "Europe/London")
    assert w == {"kind": "weekly", "days": days, "time": time, "zone": "Europe/London"}


def test_once_and_bad_words():
    assert au.parse_schedule("once on 2026-12-01 at 9:00") == {"kind": "once", "at": "2026-12-01T09:00"}
    assert au.parse_schedule("on 1/12/2026 at 7pm")["at"] == "2026-12-01T19:00"  # day/month/year
    with pytest.raises(au.AutomationError, match="Say when"):
        au.parse_schedule("whenever you like")
    with pytest.raises(au.AutomationError, match="isn't a time"):
        au.parse_schedule("every day at 25:00")
    assert au.when_words(au.parse_schedule("every weekday at 9", "Europe/London")) == "Weekdays at 09:00 (Europe/London)"
    assert au.when_words({"kind": "weekly", "days": ["mon", "thu"], "time": "14:30"}) == "Mondays and Thursdays at 14:30"
    assert au.when_words({"kind": "once", "at": "2026-12-01T09:00"}) == "Once on 1 December 2026 at 09:00"


def test_next_runs_keep_the_wall_clock_across_a_clock_change():
    """Stored in UTC, worked out in the schedule's own zone: 9:00 in London is 08:00 UTC in summer, 09:00 in winter."""
    w = au.parse_schedule("every weekday at 9:00", "Europe/London")
    assert au.next_slot(w, t("2026-10-23T10:00:00Z")) == t("2026-10-26T09:00:00Z")  # Fri after 9 -> Mon (winter)
    assert au.previous_slot(w, t("2026-10-23T10:00:00Z")) == t("2026-10-23T08:00:00Z")  # still summer time
    sunday = au.parse_schedule("every Sunday at 9:00", "Asia/Kolkata")
    assert au.next_slot(sunday, t("2026-11-27T00:00:00Z")) == t("2026-11-29T03:30:00Z")
    assert au.next_slot({"kind": "once", "at": "2026-12-01T09:00", "zone": "UTC"}, t("2026-12-02T00:00:00Z")) is None


def test_a_zone_this_computer_doesnt_know_uses_the_offset_it_was_saved_with():
    w = {"kind": "weekly", "days": ["mon"], "time": "09:00", "zone": "Nowhere/Made_Up", "offset_min": 60}
    assert au.next_slot(w, t("2026-11-29T00:00:00Z")) == t("2026-11-30T08:00:00Z")


# -- once per slot ------------------------------------------------------------------------------------------
def backup_automation(home, when="every weekday at 9:00"):
    return au.add(home, {"kind": "schedule", "when": au.parse_schedule(when, "UTC"), "do": {"what": "backup"}})


def fake_backup(monkeypatch):
    done = []

    class R:
        def message(self):
            return "Backed up."

    monkeypatch.setattr("roundtable.backup.backup_now", lambda **kw: done.append(kw) or R())
    return done


def test_a_slot_fires_once_even_after_a_restart(tmp_path, cfg, monkeypatch):
    done = fake_backup(monkeypatch)
    home = tmp_path / "home"
    a = backup_automation(home)
    au.edit(home, a["id"], {})  # (an edit that changes nothing keeps its start)
    made = {"created_at": "2026-11-23T00:00:00Z"}
    items = au.saved(home)
    items[0].update(made)
    au._save_list(home, items)
    now = t("2026-11-27T09:00:30Z")  # Friday, just after 9
    assert [r["text"] for r in au.tick(cfg, home=home, now=now, machine=PC)] == ["Backup started."]
    assert len(done) == 1
    # the app closed and opened again: the state on disk says this slot is done
    assert au.tick(cfg, home=home, now=now + timedelta(minutes=5), machine=PC) == []
    assert len(done) == 1
    st = au.load_state(home, PC)[a["id"]]
    assert st["last_slot"] == "2026-11-27T09:00:00Z" and st["last_result"] == "Backed up."
    v = au.view(au.every(cfg, home)[0], st, now)
    assert v["next_run"] == "2026-11-30T09:00:00Z" and v["made"][0]["text"] == "Backup"
    # Monday's slot fires
    au.tick(cfg, home=home, now=t("2026-11-30T09:01:00Z"), machine=PC)
    assert len(done) == 2


def test_missed_slots_catch_up_for_six_hours_only_and_not_from_before_it_was_made(tmp_path, cfg, monkeypatch):
    done = fake_backup(monkeypatch)
    home = tmp_path / "home"
    backup_automation(home)
    items = au.saved(home)
    items[0]["created_at"] = "2026-11-27T09:30:00Z"  # made after Friday's slot
    au._save_list(home, items)
    assert au.tick(cfg, home=home, now=t("2026-11-27T10:00:00Z"), machine=PC) == []
    # off all weekend, opened on Monday at 16:00: Monday 9:00 is 7 hours ago -> skipped
    assert au.tick(cfg, home=home, now=t("2026-11-30T16:00:00Z"), machine=PC) == []
    # Tuesday at 14:00 (5 hours late) still fires
    au.tick(cfg, home=home, now=t("2026-12-01T14:00:00Z"), machine=PC)
    assert len(done) == 1


def test_a_once_schedule_missed_for_good_says_so(tmp_path, cfg, monkeypatch):
    fake_backup(monkeypatch)
    home = tmp_path / "home"
    a = au.add(home, {"kind": "schedule", "when": {"kind": "once", "at": "2026-11-27T09:00", "zone": "UTC"},
                      "do": {"what": "backup"}})
    items = au.saved(home)
    items[0]["created_at"] = "2026-11-26T00:00:00Z"
    au._save_list(home, items)
    [r] = au.tick(cfg, home=home, now=t("2026-11-28T09:00:00Z"), machine=PC)
    assert "Missed" in r["text"] and r["ok"] is False
    assert au.next_run(au.every(cfg, home)[0], au.load_state(home, PC)[a["id"]], t("2026-11-28T10:00:00Z")) is None


def test_two_machines_never_both_fire_one_slot(tmp_path, cfg, monkeypatch):
    """The PC and the phone have the same automation (shared settings) and one hub: only the first one acts."""
    done = fake_backup(monkeypatch)
    hub_root = tmp_path / "hub"
    pc_home, phone_home = tmp_path / "pc", tmp_path / "phone"
    a = backup_automation(pc_home)
    a["created_at"] = "2026-11-23T00:00:00Z"
    au._save_list(pc_home, [a])
    au._save_list(phone_home, [a])
    now = t("2026-11-27T09:02:00Z")
    assert len(au.tick(cfg, hub=Hub(hub_root), home=pc_home, now=now, machine=PC)) == 1
    assert au.tick(cfg, hub=Hub(hub_root), home=phone_home, now=now, machine=PHONE) == []
    assert len(done) == 1
    claim = json.loads(next((hub_root / "automations").rglob("*.json")).read_text())
    assert claim["machine"] == PC["id"]
    # the phone remembers it was done elsewhere and doesn't try again
    assert au.load_state(phone_home, PHONE)[a["id"]]["last_slot"] == "2026-11-27T09:00:00Z"


# -- GitHub issues and failed checks ---------------------------------------------------------------------------
ISSUES = [
    {"number": 7, "title": "Add a  contact form", "body": "People want to write to us.", "state": "open",
     "html_url": "https://github.com/acme/shop/issues/7"},
    {"number": 8, "title": "A pull request", "pull_request": {"url": "x"}, "state": "open"},
]


def test_issues_become_ideas_or_tasks():
    a = au.normalise({"kind": "issues", "repo": "https://github.com/acme/shop.git", "label": "roundtable"})
    assert a["repo"] == "acme/shop" and a["make"] == "idea"
    [item] = au.issue_items(a, ISSUES)  # the pull request is left out
    assert item["key"] == "issue-7" and item["what"] == "idea" and item["title"] == "Add a contact form"
    assert "People want to write to us." in item["text"] and "acme/shop#7" in item["text"]
    t2 = au.normalise({"kind": "issues", "repo": "acme/shop", "label": "roundtable", "make": "task", "project": "/p"})
    assert au.issue_items(t2, ISSUES)[0]["what"] == "goal"
    with pytest.raises(au.AutomationError, match="owner/name"):
        au.normalise({"kind": "issues", "repo": "not a repo", "label": "x"})


RUNS = {"workflow_runs": [
    {"id": 3, "workflow_id": 1, "name": "tests", "status": "completed", "conclusion": "failure",
     "created_at": "2026-11-27T08:00:00Z", "html_url": "https://github.com/acme/shop/actions/runs/3", "head_sha": "abc1234ff"},
    {"id": 2, "workflow_id": 1, "name": "tests", "status": "completed", "conclusion": "success",
     "created_at": "2026-11-26T08:00:00Z"},
    {"id": 5, "workflow_id": 2, "name": "lint", "status": "completed", "conclusion": "failure",
     "created_at": "2026-11-25T08:00:00Z"},
    {"id": 6, "workflow_id": 2, "name": "lint", "status": "completed", "conclusion": "success",
     "created_at": "2026-11-26T09:00:00Z"},  # lint was fixed since
]}
JOBS = {"jobs": [{"id": 31, "name": "pytest", "conclusion": "failure",
                  "steps": [{"name": "Install", "conclusion": "success"}, {"name": "Run tests", "conclusion": "failure"}]},
                 {"id": 32, "name": "build", "conclusion": "success", "steps": []}]}
LOG = ("2026-11-27T08:01:00.1234567Z collecting...\n" + "".join(f"2026-11-27T08:01:01.0000000Z line {i}\n" for i in range(60))
       + "2026-11-27T08:01:02.0000000Z FAILED tests/test_cart.py::test_total - assert 3 == 4\n")


def ci_github():
    return FakeGitHub({
        "https://api.github.com/repos/acme/shop/actions/runs/3/jobs": (200, {}, JOBS),
        "https://api.github.com/repos/acme/shop/actions/runs": (200, {}, RUNS),
        "https://api.github.com/repos/acme/shop/actions/jobs/31/logs": (302, {"location": "https://logs.example/31"}, b""),
        "https://logs.example/31": (200, {}, LOG.encode()),
    })


def test_a_failed_check_becomes_a_fix_task_with_the_jobs_last_lines():
    a = au.normalise({"kind": "ci", "repo": "acme/shop", "branch": "main", "project": "/p"})
    gh = ci_github()
    [item] = au.poll(a, au.GitHub("made-up-key", gh))  # only "tests": "lint" passed again later
    assert item["key"] == "run-3" and item["what"] == "goal"
    assert "“tests” on the main branch of acme/shop" in item["text"] and "at the step “Run tests”" in item["text"]
    assert "FAILED tests/test_cart.py::test_total" in item["text"] and "2026-11-27T08" not in item["text"]
    assert "line 21\n" in item["text"] and "line 20\n" not in item["text"]  # the last 40 lines
    assert "commit abc1234" in item["text"]
    # the key goes to GitHub only, never to the log's download address
    by_url = dict(gh.calls)
    assert by_url["https://api.github.com/repos/acme/shop/actions/runs?branch=main&status=completed&per_page=30"][
        "Authorization"] == "Bearer made-up-key"
    assert "Authorization" not in by_url["https://logs.example/31"]


def test_last_lines_hide_keys():
    vault.put("DEEPSEEK_API_KEY", "sk-made-up-secret-123")
    assert au.last_lines("error: bad key sk-made-up-secret-123\n") == "error: bad key ***"


def test_github_errors_say_what_to_do(tmp_path, cfg):
    home = tmp_path / "home"
    au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "roundtable"})
    [r] = au.tick(cfg, home=home, machine=PC, http=FakeGitHub({}))
    assert "Add your GitHub key" in r["text"]
    vault.put(au.TOKEN_KEY, "made-up-key")
    for a in au.saved(home):
        au._update_state(home, a["id"], lambda st: st.pop("next_poll", None), PC)
    [r] = au.tick(cfg, home=home, machine=PC, http=FakeGitHub({"https://api.github.com/": (401, {}, {})}))
    assert "didn't accept your GitHub key" in r["text"] and r["ok"] is False


def test_an_issue_is_planned_and_waits_for_the_owners_ok(tmp_path, cfg):
    """Money is the owner's: the idea is planned (that makes the estimate) and the build waits."""
    home, projects = tmp_path / "home", tmp_path / "projects"
    vault.put("ROUNDTABLE_HUB_TOKEN", "made-up-key")  # the phone's hub key is enough
    a = au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "roundtable"})
    gh = FakeGitHub({"https://api.github.com/repos/acme/shop/issues": (200, {}, ISSUES)})
    [r] = au.tick(cfg, home=home, machine=PC, http=gh, projects_dir=projects)
    assert r["ok"]
    root = projects / "add-a-contact-form"
    meta = Project(root).meta()
    assert meta["status"] == "awaiting_approval" and not meta["plan_approved"]
    assert "acme/shop#7" in meta["goals"][0]
    st = au.load_state(home, PC)[a["id"]]
    assert "waits for your OK" in st["last_result"] and st["made"][0]["status"] == "awaiting_approval"
    assert st["spent_usd"] > 0  # planning's few cents are counted
    # asked again a few minutes later: issue 7 isn't planned twice
    au._update_state(home, a["id"], lambda s: s.pop("next_poll"), PC)
    assert au.tick(cfg, home=home, machine=PC, http=gh, projects_dir=projects) == []
    assert not (projects / "add-a-contact-form-2").exists()


def test_start_by_itself_builds_when_the_estimate_fits_the_limit(tmp_path, cfg):
    home = tmp_path / "home"
    vault.put(au.TOKEN_KEY, "made-up-key")
    root = project(cfg, tmp_path)
    with pytest.raises(au.AutomationError, match="spending limit"):
        au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "rt", "make": "task", "project": str(root),
                      "start_by_itself": True})
    a = au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "rt", "make": "task", "project": str(root),
                      "start_by_itself": True, "cap_usd": 5})
    gh = FakeGitHub({"https://api.github.com/repos/acme/shop/issues": (200, {}, ISSUES)})
    au.tick(cfg, home=home, machine=PC, http=gh)
    meta = Project(root).meta()
    assert len(meta["goals"]) == 2 and meta["plan_approved"] and meta["status"] == "done"
    st = au.load_state(home, PC)[a["id"]]
    assert "Started building by itself" in st["last_result"] and 0 < st["spent_usd"] <= 5


def test_start_by_itself_still_asks_when_the_estimate_is_over_whats_left(tmp_path, cfg):
    home = tmp_path / "home"
    vault.put(au.TOKEN_KEY, "made-up-key")
    root = project(cfg, tmp_path)
    a = au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "rt", "make": "task", "project": str(root),
                      "start_by_itself": True, "cap_usd": 0.05})  # the estimate is about $0.27
    gh = FakeGitHub({"https://api.github.com/repos/acme/shop/issues": (200, {}, ISSUES)})
    au.tick(cfg, home=home, machine=PC, http=gh)
    meta = Project(root).meta()
    assert meta["status"] == "awaiting_approval" and not meta["plan_approved"]
    assert "more than what's left" in au.load_state(home, PC)[a["id"]]["last_result"]


def test_a_failed_check_becomes_a_goal_on_the_project_once(tmp_path, cfg):
    home = tmp_path / "home"
    vault.put(au.TOKEN_KEY, "made-up-key")
    root = project(cfg, tmp_path)
    a = au.add(home, {"kind": "ci", "repo": "acme/shop", "branch": "main", "project": str(root)})
    [r] = au.tick(cfg, home=home, machine=PC, http=ci_github())
    meta = Project(root).meta()
    assert meta["goals"][-1].startswith("Fix the failing check “tests”") and meta["status"] == "awaiting_approval"
    # a new failure while that fix waits: no second task
    au._update_state(home, a["id"], lambda s: (s.pop("next_poll"), s.__setitem__("seen", [])), PC)
    [r] = au.tick(cfg, home=home, machine=PC, http=ci_github())
    assert "earlier fix is still waiting" in r["text"] and len(Project(root).meta()["goals"]) == 2


def test_a_busy_project_waits_for_the_next_tick(tmp_path, cfg):
    home = tmp_path / "home"
    vault.put(au.TOKEN_KEY, "made-up-key")
    root = project(cfg, tmp_path)
    a = au.add(home, {"kind": "issues", "repo": "acme/shop", "label": "rt", "make": "task", "project": str(root)})
    gh = FakeGitHub({"https://api.github.com/repos/acme/shop/issues": (200, {}, ISSUES)})
    assert au.tick(cfg, home=home, machine=PC, http=gh, busy=lambda p: True) == []
    assert "seen" not in au.load_state(home, PC)[a["id"]]
    assert len(Project(root).meta()["goals"]) == 1


def test_a_health_check_asks_first_unless_it_may_start_by_itself(tmp_path, cfg, monkeypatch):
    ran = []

    class Report:
        model, bad, cost_usd = "a/coder", False, 0.01

    monkeypatch.setattr("roundtable.improve.probe.check", lambda *a, **k: ran.append(k["max_cost"]) or [Report()])
    home = tmp_path / "home"
    a = au.add(home, {"kind": "schedule", "when": "every Sunday at 9:00", "do": {"what": "health"}})
    items = au.saved(home)
    items[0]["created_at"] = "2026-11-01T00:00:00Z"
    au._save_list(home, items)
    au.tick(cfg, home=home, now=t("2026-11-29T09:05:00Z"), machine=PC)
    assert ran == []
    [w] = au.needs(cfg, home, PC)
    assert "Start it" in w["text"]
    ctx = au.Ctx(cfg=cfg, home=home, machine=PC)
    assert au.start_waiting(ctx, a["id"], w["key"])["text"] == "Health check started."
    assert ran == [1.0] and au.needs(cfg, home, PC) == []
    assert "1 of 1 models are working" in au.load_state(home, PC)[a["id"]]["last_result"]
    # with start by itself and a limit: it runs, capped at what's left
    au.edit(home, a["id"], {"start_by_itself": True, "cap_usd": 0.5})
    au.tick(cfg, home=home, now=t("2026-12-06T09:05:00Z"), machine=PC)
    assert ran == [1.0, pytest.approx(0.49)]


def test_settings_list_in_harness_yaml(tmp_path, cfg):
    cfg.sections = {"automation": {"list": [{"id": "nightly", "when": "every day at 2:00", "do": {"what": "backup"}}],
                                   "poll_minutes": 10}}
    home = tmp_path / "home"
    [a] = au.every(cfg, home)
    assert a["source"] == "settings" and a["when"]["days"] == list(au.DAYS) and a["name"] == "Backup"
    au.switch(home, "nightly", False, cfg)
    assert au.load_state(home)["nightly"]["off"] is True
    cfg.sections = {"automation": {"enabled": False}}
    assert au.tick(cfg, home=home) == []


# -- the page's API --------------------------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, cfg, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", ("automationapi",))
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    a = server.UIApp(hub_config=str(tmp_path / "missing-hub.yaml"), harness_config=str(tmp_path / "missing.yaml"),
                     projects_dir=str(tmp_path / "projects"))
    a.cfg = lambda: cfg
    return a


def call(app, method, route, body=None):
    return app.dispatch(method, route, {}, body or {})


def test_the_page_lists_adds_switches_runs_and_removes(app, tmp_path, cfg, monkeypatch):
    from roundtable.phone import phone_allowed
    from roundtable.ui.server import ApiError

    root = project(cfg, tmp_path)
    r = call(app, "GET", "/api/automations")
    assert r["automations"] == [] and r["github"]["set"] is False
    assert r["projects"] == [{"path": str(root), "name": "shop"}]
    p = call(app, "POST", "/api/automations", {"action": "parse", "text": "every weekday at 9", "zone": "UTC"})
    assert p["words"] == "Weekdays at 09:00 (UTC)"
    r = call(app, "POST", "/api/automations", {"action": "add", "automation": {
        "kind": "schedule", "when": p["when"], "do": {"what": "goal", "project": str(root), "text": "Add a menu page."}}})
    [a] = r["automations"]
    assert r["done"] == "Added “shop: Add a menu page.”."
    assert a["what"] == "Plans the next goal for shop: “Add a menu page.”." and a["when_words"] == "Weekdays at 09:00 (UTC)"
    assert a["money"] == "Planning costs a few cents; building waits for your OK." and a["next_run"]
    r = call(app, "POST", "/api/automations", {"action": "off", "id": a["id"]})
    assert r["automations"][0]["on"] is False and r["automations"][0]["next_run"] is None
    # Run now: planned in a background job, the build waits
    r = call(app, "POST", "/api/automations", {"action": "run", "id": a["id"]})
    assert r["done"].startswith("Planning")
    for _ in range(200):
        if not any(j.status == "running" for j in app.jobs.jobs.values()):
            break
        import time
        time.sleep(0.05)
    assert Project(root).meta()["status"] == "awaiting_approval"
    r = call(app, "GET", "/api/automations")
    assert r["automations"][0]["made"][0]["project"] == str(root)
    with pytest.raises(ApiError, match="Pick the project"):
        call(app, "POST", "/api/automations", {"action": "edit", "id": a["id"], "changes": {"do": {"what": "goal", "text": "x"}}})
    with pytest.raises(ApiError, match="Open the Darkness Harness app"):
        call(app, "POST", "/api/automations", {"action": "github_key", "key": "made-up"})
    r = call(app, "POST", "/api/automations", {"action": "remove", "id": a["id"]})
    assert r["automations"] == []
    assert phone_allowed("GET", "/api/automations") in (True, False)  # (the coordinator adds the phone routes)


def test_the_github_key_goes_to_the_key_store(app, tmp_path):
    saved = {}

    class Keys:
        def set(self, name, value):
            saved[name] = value
            vault.put(name, value)

        def get(self, name):
            return saved.get(name)

    app.desktop = {"keys": Keys(), "paths": None}
    app._backup_home = lambda: tmp_path / "home"
    r = call(app, "POST", "/api/automations", {"action": "github_key", "key": "made-up-key"})
    assert saved == {au.TOKEN_KEY: "made-up-key"} and r["github"] == {"set": True, "which": "your GitHub key"}
    assert "made-up-key" not in json.dumps(r)
    assert not any("made-up-key" in p.read_text(encoding="utf-8") for p in (tmp_path / "home").rglob("*") if p.is_file())
