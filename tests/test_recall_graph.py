"""The memory picture (recall.graph) and the recall API (ui/recallapi.py), on a made-up lab."""

import base64
import json

import pytest

from roundtable import documents as docs
from roundtable import recall
from roundtable.ui import recallapi


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def agent(home, aid, name, job, hired=True):
    f = home / "agents" / aid / "agent.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"name: {name}\njob: {job}\nhired: {str(hired).lower()}\n", encoding="utf-8")


def made_up_lab(tmp_path):
    home = tmp_path / "home"
    agent(home, "torvic", "Torvic", "builder")
    agent(home, "vera", "Vera", "checker")
    doc = docs.add_file(home, "style.md", b"Round corners everywhere.")
    roots = []
    for i, name in enumerate(("Bakery", "Racer", "Notes")):
        root = tmp_path / name.lower()
        (root / ".harness").mkdir(parents=True)
        (root / ".harness" / "project.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        jsonl(root / ".harness" / "metrics.jsonl", [
            {"task": "T1", "role": "coder", "agent": "torvic", "tags": ["ui", "save"]},
            {"task": "T2", "role": "coder", "agent": "torvic", "tags": ["ui"]},
            {"task": "T3", "role": "tester", "tags": ["tests"]}])
        jsonl(root / ".harness" / "reviews.jsonl", [
            {"kind": "verdict", "task": "T1", "role": "coder", "approved": True},
            {"kind": "verdict", "task": "T2", "role": "coder", "approved": False},
            {"kind": "decision", "task": "T2", "approved": False}])
        if i == 0:
            jsonl(root / ".harness" / recall.LOG, [{"task": "T1", "n": 2, "docs": [doc["id"]]},
                                                    {"task": "T2", "n": 1, "docs": [doc["id"], "gone"]}])
        roots.append(root)
    return home, roots, doc


def test_the_graph_counts_on_a_made_up_lab(tmp_path):
    home, roots, doc = made_up_lab(tmp_path)
    g = recall.graph(roots, home)
    kinds = {n["id"]: n["kind"] for n in g["nodes"]}
    assert kinds["agent:torvic"] == "agent" and kinds["agent:vera"] == "agent" and kinds[f"doc:{doc['id']}"] == "document"
    assert sum(1 for k in kinds.values() if k == "project") == 3
    edges = {(e["from"], e["to"], e["kind"]): e["count"] for e in g["edges"]}
    built = [v for (a, b, k), v in edges.items() if a == "agent:torvic" and k == "built"]
    assert built == [2, 2, 2]
    assert edges[("agent:vera", "agent:torvic", "checked")] == 6
    assert edges[(f"project:{recall.pid_of(roots[0])}", f"doc:{doc['id']}", "used")] == 2
    assert {n["label"]: n["weight"] for n in g["nodes"] if n["kind"] == "topic"} == {"ui": 6, "save": 3, "tests": 3}
    assert g["sentence"] == "Torvic has built in 3 projects; Vera checked most of it."
    assert "Vera checked the work of Torvic (6 times)" in g["lines"]


def test_an_empty_lab_says_so(tmp_path):
    assert recall.graph([], tmp_path)["sentence"] == "Nothing built yet, so there's no one to show."


class FakeApp:
    def __init__(self, roots, cfg=None):
        import threading

        self.roots, self._cfg = roots, cfg
        self.hub, self.agent, self.hub_lock = None, "me", threading.RLock()

    def _lab_projects(self):
        return self.roots

    def need_cfg(self):
        return self._cfg


def test_the_api_routes(tmp_path, monkeypatch):
    from roundtable.ui.server import ApiError

    home, roots, doc = made_up_lab(tmp_path)
    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    app = FakeApp(roots)
    r = recallapi.routes(app)
    assert set(r) == {("GET", "/api/recall"), ("POST", "/api/recall/ask"), ("GET", "/api/documents"),
                      ("POST", "/api/documents"), ("GET", "/api/recall/graph")}
    got = r[("GET", "/api/recall")]({"q": ["round corners"]})
    assert got["pieces"][0]["doc"] == doc["id"]
    listing = r[("GET", "/api/documents")]({})
    assert len(listing["documents"]) == 1 and {p["name"] for p in listing["projects"]} == {"Bakery", "Racer", "Notes"}
    added = r[("POST", "/api/documents")]({"action": "add", "name": "b.txt",
                                           "data": base64.b64encode(b"Blue skies").decode(), "private": True})
    assert added["document"]["private"] and len(added["documents"]) == 2
    assert added["documents"][1]["private_words"] == "Never leaves this computer"
    pid = listing["projects"][0]["id"]
    ch = r[("POST", "/api/documents")]({"action": "change", "id": doc["id"], "projects": [pid]})
    assert ch["document"]["projects"] == [pid]
    gone = r[("POST", "/api/documents")]({"action": "remove", "id": doc["id"]})
    assert gone["removed"] == 1 and len(gone["documents"]) == 1
    with pytest.raises(ApiError):
        r[("POST", "/api/documents")]({"action": "remove", "id": doc["id"]})
    with pytest.raises(ApiError):
        r[("POST", "/api/recall/ask")]({"question": ""})
    assert r[("GET", "/api/recall/graph")]({})["sentence"].startswith("Torvic")
