"""What you use most (wave 9, MD-91): counted on this computer only, never a name, a text or an id."""

import json
import random
import re
import string
from pathlib import Path

import pytest

from roundtable import localcounts
from roundtable.localcounts import count, family

SOURCE = Path(localcounts.__file__).read_text(encoding="utf-8")


def test_the_module_opens_no_connection():
    for bad in ("urllib", "socket", "requests", "http.client", "httpx", "aiohttp"):
        assert not re.search(rf"\b{re.escape(bad)}\b", SOURCE.replace("never sent", "")), bad


def test_families_are_route_words_only():
    assert family("GET", "/api/roundtable") == "see.roundtable"
    assert family("POST", "/api/board/answer-several") == "do.board.answer-several"
    assert family("GET", "/api/project/settings?path=/home/x/secret-game") == "see.project.settings"
    assert family("GET", "/api/journal/my-secret-project") == "see.journal"  # the name in the path is cut off
    assert family("POST", "/api/inbox/space-game/read") == "do.inbox"
    assert family("GET", "/api/jobs/abc123") == "see.jobs"
    assert family("GET", "/api/files/v2") == "see.files"  # a word with digits stops the family there
    for quiet in ("/api/features", "/api/changes", "/api/ping", "/api/counts", "/api/pair/claim"):
        assert family("GET", quiet) is None
    assert family("GET", "/index.html") is None and family("GET", "/api") is None


def _made_up_text(rng):
    pool = string.ascii_letters + string.digits + " /.-_?=&é中"
    return "".join(rng.choice(pool) for _ in range(rng.randint(1, 40)))


def test_no_project_name_or_free_text_is_ever_kept(tmp_path):
    """A property over made-up events: whatever goes in, the file holds route words and numbers only."""
    rng = random.Random(9)
    names = [f"Secret Project {i}" for i in range(20)] + ["my-game", "Bakery Site"]
    for _ in range(400):
        name = rng.choice(names)
        method = rng.choice(["GET", "POST"])
        path = rng.choice([f"/api/journal/{name}", f"/api/inbox/{name}/read", f"/api/project?path=/p/{name}",
                           f"/api/{_made_up_text(rng)}", "/api/plan", f"/api/cards/{name}"])
        count(tmp_path, family(method, path) or "")
        count(tmp_path, _made_up_text(rng))  # anything that isn't a family is refused
        count(tmp_path, name)
    raw = (tmp_path / "counts.json").read_text(encoding="utf-8")
    for name in names:
        assert name not in raw and name.lower().replace(" ", "-") not in raw
    data = json.loads(raw)
    for day, fams in data["days"].items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
        for fam, n in fams.items():
            assert re.fullmatch(r"(see|do)(\.[a-z][a-z_-]*){1,3}", fam) and isinstance(n, int)


def test_a_refreshing_screen_is_one_look_and_buttons_count_each_press(tmp_path):
    for _ in range(50):
        count(tmp_path, "see.roundtable")
        count(tmp_path, "do.plan")
    v = localcounts.view(tmp_path)
    got = {r["family"]: r["count"] for r in v["top"]}
    assert got == {"do.plan": 50, "see.roundtable": 1}
    assert v["top"][0]["name"] == "Plan buttons" and "Plan buttons" in v["words"]
    assert v["screens"][0]["name"] == "Home"


def test_clear_empties_the_file_and_off_stops_counting(tmp_path):
    count(tmp_path, "do.plan")
    v = localcounts.clear(tmp_path)
    assert v["top"] == [] and json.loads((tmp_path / "counts.json").read_text())["days"] == {}
    localcounts.set_on(tmp_path, False)
    count(tmp_path, "do.plan")
    assert localcounts.view(tmp_path)["top"] == [] and not localcounts.is_on(tmp_path)
    localcounts.set_on(tmp_path, True)
    count(tmp_path, "do.plan")
    assert localcounts.view(tmp_path)["top"][0]["count"] == 1


def test_a_bare_word_like_the_seam_tests_is_not_a_family(tmp_path):
    assert count(tmp_path, "hall") is None and list(tmp_path.iterdir()) == []


@pytest.fixture
def app(tmp_path, monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "countsapi"))
    a = UIApp(None, "missing.yaml")
    a._backup_home = lambda: tmp_path
    return a


def test_the_settings_page_shows_and_clears_them(app, tmp_path):
    count(tmp_path, "do.chat")
    assert app.dispatch("GET", "/api/counts", {}, {})["top"][0]["name"] == "Sending a message"
    assert app.dispatch("POST", "/api/counts", {}, {"action": "off"})["on"] is False
    assert app.dispatch("POST", "/api/counts", {}, {"action": "clear"})["top"] == []
    with pytest.raises(ValueError):
        app.dispatch("POST", "/api/counts", {}, {"action": "send"})


def test_the_phone_can_neither_see_nor_clear_them():
    from roundtable.phone import phone_allowed

    assert not phone_allowed("GET", "/api/counts") and not phone_allowed("POST", "/api/counts")
