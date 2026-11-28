"""The office's pixel art (officeart.py, wave 9): the quote, the sample sheet, the owner's yes, the rest, the cap.

A fake Retro Diffusion answers check_cost and generate from a table: no network, no keys, nothing spent.
"""

from __future__ import annotations

import io
import json
import re
import threading
from pathlib import Path

import pytest
from PIL import Image

from roundtable import officeart
from roundtable.providers.base import ProviderError, Usage

STATIC = Path(officeart.__file__).parent / "ui" / "static"


def png(w: int, h: int) -> bytes:
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (40, 30, 90, 255)).save(b, "PNG")
    return b.getvalue()


class FakeRD:
    """check_cost and generate answering from a table (dollars per piece by style)."""

    def __init__(self, prices=None, fail=(), refuse_styles=()):
        self.prices = prices or {}
        self.fail = dict.fromkeys(fail, 1)  # piece prompt fragments that fail once
        self.refuse = set(refuse_styles)
        self.checks = 0
        self.made: list[str] = []
        self.lock = threading.Lock()

    def styles(self):
        return {p["style"]: {} for p in officeart.manifest() if p["style"] not in self.refuse}

    def _usd(self, style):
        return self.prices.get(style, 0.05)

    def check_cost(self, style, prompt, options=None):
        with self.lock:
            self.checks += 1
        return self._usd(style)

    def generate(self, model, prompt, options=None):
        for frag, n in list(self.fail.items()):
            if frag in prompt and n:
                self.fail[frag] = n - 1
                raise ProviderError("generation failed - refunded", retryable=True)
        with self.lock:
            self.made.append(prompt)
        o = options or {}
        return png(int(o.get("width", 64)), int(o.get("height", 64))), "png", Usage(cost_usd=self._usd(model) * 0.9)


def test_the_manifest_has_every_piece_once_with_a_style_size_and_prompt():
    m = officeart.manifest()
    ids = [p["id"] for p in m]
    assert len(ids) == len(set(ids)) and 30 <= len(ids) <= 36
    for p in m:
        assert {"id", "file", "style", "width", "height", "prompt", "options", "stage"} <= set(p), p["id"]
        assert p["stage"] in ("sample", "rest")
    sample = {p["id"] for p in m if p["stage"] == "sample"}
    assert sample == {"wall", "maelin-walk", "maelin-work", "desk", "shelf", "bubble-question", "bubble-tick"}
    lay = officeart.layout()
    for fig in lay["agents"].values():
        assert fig["walk"] in ids and fig["work"] in ids
    for b in lay["bubbles"].values():
        assert b in ids
    assert {p["piece"] for p in lay["props"]} <= set(ids)
    assert set(lay["agents"]) >= {"maelin", "torvic", "ondra", "kestrel", "calla", "pell", "helper-a", "helper-b"}


def test_no_prompt_names_another_project_and_no_file_in_the_office_folder_is_a_drawing():
    text = json.dumps(officeart.manifest()).lower()
    for other in ("munder", "difflin", "pokemon", "stardew", "nintendo", "in the style of"):
        assert other not in text
    for f in (STATIC / "office").rglob("*"):
        assert f.suffix.lower() != ".svg", f
        if f.is_file() and f.suffix == ".json":
            assert "<svg" not in f.read_text(encoding="utf-8")


def test_the_quote_sums_right_and_spends_nothing():
    rd = FakeRD()
    q = officeart.quote(rd)
    n = len(officeart.manifest())
    assert q["ok"] and q["cap"] == 10.0 and len(q["pieces"]) == n and not q["left_out"]
    assert q["total_usd"] == pytest.approx(0.05 * n) and q["sample_usd"] == pytest.approx(0.05 * 7)
    assert q["rest_usd"] == pytest.approx(q["total_usd"] - q["sample_usd"])
    assert rd.checks == n and rd.made == []  # only the price check: nothing made
    assert "$" in q["words"]


def test_a_quote_over_eight_dollars_trims_and_says_what_went():
    rd = FakeRD(prices={"rd_core__topdown": 0.35, "animation__four_angle_walking": 0.3, "animation__any_animation": 0.3})
    q = officeart.quote(rd)
    assert q["ok"] and q["total_usd"] <= officeart.TRIM_AT
    gone = [x["id"] for x in q["left_out"]]
    assert gone and gone[0] == "plant"  # the most dispensable first
    assert all(p["stage"] == "rest" for p in officeart.manifest() if p["id"] in gone)
    assert "left out" in q["words"]
    kept = {x["id"] for x in q["pieces"]}
    assert not kept & set(gone)


def test_a_quote_that_cannot_get_under_the_line_is_not_ok():
    q = officeart.quote(FakeRD(prices={"animation__any_animation": 1.2}))
    assert not q["ok"] and "Even with pieces left out" in q["words"] and q["left_out"]


def test_an_unknown_style_is_a_problem_not_a_guess():
    q = officeart.quote(FakeRD(refuse_styles={"rd_plus__ui_element"}))
    assert {p["id"] for p in q["problems"]} == {p["id"] for p in officeart.manifest() if p["style"] == "rd_plus__ui_element"}
    assert not q["ok"]  # two of them are the sample's


def test_no_provider_is_said_plainly():
    q = officeart.quote(None)
    assert q["cap"] == 10.0 and not q["ok"] and "Models" in q["words"]


def test_the_rest_before_the_owners_yes_is_refused(tmp_path):
    rd = FakeRD()
    with pytest.raises(officeart.OfficeArtError, match="your yes"):
        officeart.make(rd, "rest", tmp_path / "out", tmp_path / "spend.jsonl")
    with pytest.raises(officeart.OfficeArtError, match="no sample"):
        officeart.approve(tmp_path / "spend.jsonl")
    assert rd.made == []


def test_the_sample_then_the_yes_then_the_rest(tmp_path):
    rd = FakeRD()
    out, spent = tmp_path / "out", tmp_path / "spend.jsonl"
    res = officeart.make(rd, "sample", out, spent)
    assert sorted(res["made"]) == sorted(p["id"] for p in officeart.manifest() if p["stage"] == "sample")
    assert (out / "sample-sheet.png").is_file() and Image.open(out / "sample-sheet.png").width > 64
    assert res["usd"] == pytest.approx(0.045 * 7)  # the real charge, not the estimate
    assert officeart.spent(spent) == pytest.approx(res["usd"])
    officeart.approve(spent)
    rest = officeart.make(rd, "rest", out, spent)
    assert len(rest["made"]) == len(officeart.manifest()) - 7 and not rest["failed"]
    assert officeart.spent(spent) <= officeart.CAP_USD
    assert officeart.ready() in (True, False)  # the shipped folder is untouched
    assert officeart._complete(out)
    rows = [json.loads(x) for x in spent.read_text().splitlines()]
    assert {r["stage"] for r in rows} == {"sample", "rest"} and all("cost_usd" in r for r in rows)
    with pytest.raises(officeart.OfficeArtError):
        officeart.make(rd, "sample", out, spent)  # once approved, the sample isn't made again


def test_a_failed_piece_is_tried_once_more(tmp_path):
    rd = FakeRD(fail=("One seamless wall tile",))
    res = officeart.make(rd, "sample", tmp_path / "o", tmp_path / "s.jsonl")
    assert "wall" in res["made"] and not res["failed"]


def test_a_piece_over_the_cap_is_never_asked_for(tmp_path):
    spent = tmp_path / "s.jsonl"
    officeart.settle(spent, "x", 9.9, {"piece": "earlier", "stage": "rest"})  # nearly all of it already spent
    rd = FakeRD()
    res = officeart.make(rd, "sample", tmp_path / "o", spent)
    assert len(res["made"]) == 2 and len(res["skipped"]) == 5  # 0.05 each fits twice under $10
    assert len(rd.made) == 2
    assert officeart.spent(spent) <= officeart.CAP_USD + 1e-9


def test_the_cap_holds_across_four_threads(tmp_path):
    spent = tmp_path / "s.jsonl"
    got, refused = [], []

    def worker():
        for _ in range(10):
            try:
                tok = officeart.reserve(spent, 0.4)
            except officeart.OfficeCapReached:
                refused.append(1)
                continue
            officeart.settle(spent, tok, 0.4, {"piece": "p", "stage": "rest"})
            got.append(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 25 and len(refused) == 15
    assert officeart.spent(spent) == pytest.approx(10.0)
    with pytest.raises(officeart.OfficeCapReached):
        officeart.reserve(spent, 0.01)
    with pytest.raises(officeart.OfficeCapReached):
        officeart.reserve(tmp_path / "other.jsonl", 10.5, cap=50)  # never above the owner's figure


def test_a_released_hold_charges_nothing(tmp_path):
    spent = tmp_path / "s.jsonl"
    tok = officeart.reserve(spent, 9.0)
    with pytest.raises(officeart.OfficeCapReached):
        officeart.reserve(spent, 2.0)
    officeart.release(spent, tok)
    assert officeart.spent(spent) == 0 and officeart.held(spent) == 0
    officeart.release(spent, officeart.reserve(spent, 2.0))


def test_remake_prices_first_then_makes_inside_the_cap(tmp_path):
    rd = FakeRD()
    out, spent = tmp_path / "o", tmp_path / "s.jsonl"
    officeart.make(rd, "sample", out, spent)
    with pytest.raises(officeart.OfficeArtError):
        officeart.remake(rd, "sofa", out, spent)  # part of the rest: waits for the yes
    look = officeart.remake(rd, "desk", out, spent)
    assert look["made"] is False and look["fits"] and "$0.05" in look["words"]
    n = len(rd.made)
    done = officeart.remake(rd, "desk", out, spent, confirm=True)
    assert done["made"] and len(rd.made) == n + 1
    assert list(out.glob(".desk.png.old"))  # the older try is kept aside


class App:
    def __init__(self, home):
        self.home = home

    def _backup_home(self):
        return self.home


def test_the_sample_card_has_confirm_is_pc_only_and_goes_once_answered(tmp_path):
    app = App(tmp_path)
    assert officeart.sample_ask(app) is None  # nothing made yet: no card
    out, spent = officeart.paths(app)
    officeart.make(FakeRD(), "sample", out, spent)
    ask = officeart.sample_ask(app)
    assert ask["id"].startswith("officeart") and ask["pc_only"] and ask["allow_other"] is False
    ids = [o["id"] for o in ask["options"]]
    assert ids[0] == "rest" and set(ids) == {"rest", "again", "stop"}
    for o in ask["options"]:
        assert bool(o.get("confirm")) == (o["id"] != "stop")  # both paid answers need the owner's confirmed tap
    assert re.search(r"Make the rest \(\$\d+\.\d\d\)", ask["options"][0]["label"])
    assert ask["picture"].startswith("data:image/png;base64,")
    assert ask["route"] == "/api/office/answer"
    officeart.stop(spent)
    assert officeart.sample_ask(app) is None
