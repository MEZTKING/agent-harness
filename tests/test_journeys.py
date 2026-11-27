"""journeys.walk: the done list's steps, walked as a person would (a fake walker, and the real browser when here)."""

from pathlib import Path

import pytest

from roundtable.harness import journeys, look, showit


def test_steps_are_read_in_every_written_form():
    assert journeys.step_of("click Start") == {"do": "click", "text": "Start", "into": ""}
    assert journeys.step_of({"click": "Start"}) == {"do": "click", "text": "Start", "into": ""}
    assert journeys.step_of({"do": "type", "text": "Ann", "into": "Name"}) == {"do": "type", "text": "Ann", "into": "Name"}
    assert journeys.step_of({"type": "Ann", "into": "Name"}) == {"do": "type", "text": "Ann", "into": "Name"}
    assert journeys.step_of("type 'Ann' into Name") == {"do": "type", "text": "Ann", "into": "Name"}
    assert journeys.step_of("expect_no_errors") == {"do": "expect_no_errors", "text": "", "into": ""}
    assert journeys.step_of("dance wildly") is None and journeys.step_of({"click": 1, "press": 2}) is None


def test_an_item_always_starts_at_the_app_and_unknown_steps_make_it_a_look():
    assert journeys.steps_of({"steps": ["click Start"]})[0]["do"] == "open"
    assert [s["do"] for s in journeys.steps_of({})] == ["open", "expect_no_errors"]  # page_opens
    assert journeys.steps_of({"steps": ["click Start", "smell the roses"]}) is None
    assert [s["do"] for s in journeys.steps_of({"steps": "click Start; expect_text Score"})] == \
        ["open", "click", "expect_text"]


def fake(answers):
    def walker(jobs):
        for j in jobs:
            Path(j["png"]).write_bytes(b"png")
        return [dict(answers[j["id"]], id=j["id"]) for j in jobs]
    return walker


def test_walk_gives_each_item_its_answer_in_plain_words(tmp_path):
    items = [{"id": "D1", "steps": ["click Start", "expect_text Score"]}, {"id": "D2", "steps": []},
             {"id": "D3", "steps": ["juggle"]}]
    got = journeys.walk("http://127.0.0.1:1/", "http://127.0.0.1:1/", items, tmp_path,
                        walker=fake({"D1": {"passed": False, "failed_step": 2, "why": "Timeout 5000ms exceeded",
                                            "errors": ["boom"]},
                                     "D2": {"passed": True, "failed_step": None, "errors": []}}))
    assert got["D1"]["passed"] is False and got["D1"]["step"] == "see “Score”" and got["D1"]["errors"] == ["boom"]
    assert got["D1"]["words"].startswith("Stopped at step 3 (see “Score”)") and got["D1"]["picture"] == "D1.png"
    assert got["D2"]["passed"] is True and got["D2"]["words"] == "Walked it: all 2 steps worked."
    assert got["D3"]["passed"] is None  # its steps aren't ones the harness knows


def test_without_playwright_every_item_is_unchecked_never_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(look, "renderer", lambda: None)
    got = journeys.walk("http://x/", "http://x/", [{"id": "D1"}, {"id": "D2", "steps": ["click Go"]}], tmp_path)
    assert {k: v["passed"] for k, v in got.items()} == {"D1": None, "D2": None}
    assert "Playwright isn't installed" in got["D1"]["words"]


def test_a_walker_that_breaks_is_written_down(tmp_path):
    def broken(jobs):
        raise OSError("no browser")
    got = journeys.walk("http://x/", "http://x/", [{"id": "D1"}], tmp_path, walker=broken)
    assert got["D1"]["passed"] is None and "no browser" in got["D1"]["why"]


GAME = """<!doctype html><title>Made-up counter</title>
<button id="go">Start</button><p id="out"></p>
<script>
document.getElementById('go').onclick = () => { %s };
</script>"""


@pytest.mark.skipif(not look.renderer(), reason="Playwright isn't installed here")
def test_a_real_walk_finds_a_button_that_does_nothing(tmp_path):
    items = [{"id": "D1", "steps": ["click Start", "expect_text Score: 1"]},
             {"id": "D2", "steps": ["open", "expect_no_errors"]},
             {"id": "D3", "steps": [{"open": "https://example.com/"}]}]
    broken, fixed = tmp_path / "broken", tmp_path / "fixed"
    for d, js in ((broken, "/* nothing happens */ missing();"),
                  (fixed, "document.getElementById('out').textContent = 'Score: 1';")):
        d.mkdir()
        (d / "index.html").write_text(GAME % js, encoding="utf-8")
    with showit.StaticServer(broken) as srv:
        bad = journeys.walk(srv.url, srv.url, items, tmp_path / "out1")
    with showit.StaticServer(fixed) as srv:
        good = journeys.walk(srv.url, srv.url, items, tmp_path / "out2")
    assert bad["D1"]["passed"] is False and bad["D1"]["step"] == "see “Score: 1”"
    assert any("missing" in e for e in bad["D1"]["errors"])  # the console's error is the evidence
    assert good["D1"]["passed"] is True and good["D2"]["passed"] is True
    assert (tmp_path / "out2" / "D1.png").is_file()
    assert good["D3"]["passed"] is False and "not the app's own" in good["D3"]["why"]  # only the app may load
