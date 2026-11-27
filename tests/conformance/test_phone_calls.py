"""The phone app's calls, run against a real phone server (calls.json lists them).

1. ``test_every_phone_call_answers``: a real ``PhoneAccess`` over a made-up hub and a scripted
   project, paired the way the phone pairs, runs every call in calls.json and checks the keys the
   phone reads. With ``ROUNDTABLE_WRITE_FIXTURES=1`` it writes the answers to
   ``mobile/app/src/test/resources/conformance/<name>.json`` for ConformanceTest.kt.
2. ``test_no_unlisted_phone_calls``: every ``"/api/…"`` string in the phone app's Kotlin must be in
   calls.json, and every listed call must be one the phone server allows.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import pytest

from roundtable import onphone
from roundtable.phone import PhoneAccess, phone_allowed

from ..test_roundtable import setup  # noqa: F401  (fixture)

HERE = Path(__file__).parent
REPO = HERE.parent.parent
KOTLIN = REPO / "mobile/app/src/main/java"
FIXTURES = REPO / "mobile/app/src/test/resources/conformance"
SPEC = json.loads((HERE / "calls.json").read_text(encoding="utf-8"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")
FAKE_ROOT = "/home/owner/lab"  # tmp folders in the fixtures read as this


def _fill(v, values):
    if isinstance(v, str):
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), v)
    if isinstance(v, list):
        return [_fill(x, values) for x in v]
    if isinstance(v, dict):
        return {k: _fill(x, values) for k, x in v.items()}
    return v


def _call(port, method, path, body=None, token=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the phone pins the fingerprint (test_phone.py checks that)
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if method == "POST" else None)
    if method == "POST":
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def paired(setup, tmp_path):  # noqa: F811
    app, orch, brain, cfg = setup
    app.projects_dir = tmp_path / "projects"  # new projects from the phone land here, not in the checkout
    app.projects_dir.mkdir()
    p = PhoneAccess(app, tmp_path / "home", name="made-up-pc")
    app.phone = p
    p.enable(port=0)
    code = p.start_pairing()["code"]
    status, text = _call(p.port, "POST", "/api/pair/claim", {"code": code, "device_name": "Made-up Phone"})
    assert status == 200, text
    yield app, orch, p, json.loads(text)["token"], tmp_path
    p.stop()


def _scrub(text: str, tmp: Path) -> str:
    for raw in {str(tmp), str(tmp.resolve()), json.dumps(str(tmp))[1:-1]}:
        text = text.replace(raw, FAKE_ROOT)
    return text


def test_every_phone_call_answers(paired):
    app, orch, p, token, tmp = paired
    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    orch.run()
    project = str(orch.project.root) if hasattr(orch, "project") else str(tmp / "proj")
    (Path(project) / "README.md").write_text("# A made-up bakery\n", encoding="utf-8")
    app.hub.journal.add("proj", "todo", "check the logo colours", priority="high")
    msg = app.hub.send("frontend", "proj", "hello", "a made-up note")
    notes_dir = Path(app.hub.store.root) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "garden-ideas.md").write_text("# Garden ideas\n\nA made-up note.\n", encoding="utf-8")
    notes = app.dispatch("GET", "/api/notes", {}, {}).get("notes") or [{"name": "none"}]
    values = {"project": project, "agent": "proj", "file": "README.md",
              "message": msg[0]["id"], "note": notes[0].get("name", "none")}

    write = os.environ.get("ROUNDTABLE_WRITE_FIXTURES") == "1"
    failures = []
    for c in SPEC["calls"]:
        if c.get("local"):
            continue
        path = _fill(c["path"], values)
        query = _fill(c.get("query") or {}, values)
        url = path + ("?" + urlencode(query) if query else "")
        status, text = _call(p.port, c["method"], url, _fill(c.get("body") or {}, values), token)
        if os.environ.get("CONFORMANCE_DEBUG"):
            print(c["name"], status, text[:300])
        if status != 200:
            failures.append(f"{c['name']}: {c['method']} {path} → {status} {text[:200]}")
            continue
        data = json.loads(text)
        if c.get("shape") == "list" and not isinstance(data, list):
            failures.append(f"{c['name']}: expected a list")
        missing = [k for k in c.get("needs", []) if not isinstance(data, dict) or k not in data]
        if missing:
            failures.append(f"{c['name']}: missing {missing}")
        for k, field in (c.get("save") or {}).items():
            values[k] = data[field]
        if write:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            pretty = json.dumps(json.loads(_scrub(text, tmp)), indent=1, sort_keys=True, ensure_ascii=False)
            (FIXTURES / f"{c['name']}.json").write_text(pretty + "\n", encoding="utf-8")
    _wait_for_jobs(app)
    assert not failures, "\n".join(failures)
    for c in SPEC["calls"]:  # the phone's tests need a fixture for every call made to the PC
        assert c.get("local") or (FIXTURES / f"{c['name']}.json").is_file(), \
            f"no fixture for {c['name']}: run with ROUNDTABLE_WRITE_FIXTURES=1"


def _wait_for_jobs(app, timeout_s: float = 60) -> None:
    """Runs the calls started (a scripted build, Run the tests) finish before the server stops."""
    import time

    end = time.monotonic() + timeout_s
    while time.monotonic() < end and any(j.status == "running" for j in list(app.jobs.jobs.values())):
        time.sleep(0.1)


def _kotlin_paths() -> set[str]:
    found = set()
    for f in KOTLIN.rglob("*.kt"):
        text = f.read_text(encoding="utf-8")
        text = re.sub(r"FEATURE_PREFIXES\s*=\s*listOf\([^)]*\)", "", text)  # a guard, not calls
        for m in re.finditer(r'"(/api/[A-Za-z0-9_/.\-]*)', text):
            found.add(m.group(1))
    return found


def _covered(literal: str, listed: list[str]) -> bool:
    if literal in listed:
        return True
    if literal.endswith("/"):  # "/api/inbox/" + agent: a listed call starts with it
        return any(p.startswith(literal) for p in listed)
    return any(PLACEHOLDER.sub("x", p) == literal for p in listed)


def test_no_unlisted_phone_calls():
    listed = [c["path"] for c in SPEC["calls"]]
    exempt = set(SPEC["exempt"])
    found = _kotlin_paths()
    assert len(found) > 30  # the regex still finds the app's calls
    unlisted = sorted(p for p in found if p not in exempt and not _covered(p, listed))
    assert not unlisted, f"the phone calls these but calls.json doesn't list them: {unlisted}"
    for c in SPEC["calls"]:
        if c["path"] in exempt:
            continue
        sample = PLACEHOLDER.sub("x", c["path"])
        if c.get("local"):  # Roundtable on the phone itself answers these (onphone.py)
            assert f'"{c["path"]}"' in Path(onphone.__file__).read_text(encoding="utf-8"), c["name"]
        else:
            assert phone_allowed(c["method"], sample), f"{c['name']}: {c['method']} {c['path']} isn't allowed for phones"
    names = [c["name"] for c in SPEC["calls"]]
    assert len(names) == len(set(names))


def test_the_check_catches_an_unlisted_call(monkeypatch, tmp_path):
    (tmp_path / "Extra.kt").write_text('val x = call("GET", "/api/something/new")\n'
                                       'val FEATURE_PREFIXES = listOf("/api/rewind")\n', encoding="utf-8")
    monkeypatch.setattr(__import__(__name__, fromlist=["x"]), "KOTLIN", tmp_path)
    found = _kotlin_paths()
    assert found == {"/api/something/new"}
    assert not _covered("/api/something/new", [c["path"] for c in SPEC["calls"]])
    assert _covered("/api/inbox/", ["/api/inbox/{agent}"]) and _covered("/api/jobs/", ["/api/jobs/{job}"])
