"""Costs also in pounds (money.py, ui/moneyapi.py). A made-up bank file; nothing goes out."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from roundtable import money

ECB = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube><Cube time='2026-11-26'>
    <Cube currency='USD' rate='1.0500'/><Cube currency='JPY' rate='160.00'/>
    <Cube currency='GBP' rate='0.8400'/>
  </Cube></Cube>
</gesmes:Envelope>"""
NOW = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)


class Bank:
    def __init__(self, body=ECB, fail=False):
        self.body, self.fail, self.calls = body, fail, []

    def __call__(self, url, timeout):
        self.calls.append(url)
        if self.fail:
            raise OSError("offline")
        return self.body


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(url, timeout):
        raise AssertionError("a test tried to reach the bank")

    monkeypatch.setattr(money, "OPENER", refuse)


def test_the_parser_reads_a_made_up_file():
    assert money.parse_ecb(ECB.decode()) == ("2026-11-26", 0.8)
    with pytest.raises(ValueError):
        money.parse_ecb("<html>not the bank</html>")


def test_once_a_day_then_kept(tmp_path):
    bank = Bank()
    r = money.rate(tmp_path, opener=bank, now=NOW)
    assert r["per_usd"] == 0.8 and r["source"] == "ecb" and r["at"] == "2026-11-26" and not r["stale"]
    assert r["currency"] == "GBP" and "European Central Bank" in r["words"]
    money.rate(tmp_path, opener=bank, now=NOW + timedelta(hours=3))
    assert len(bank.calls) == 1 and bank.calls[0] == money.ECB_URL  # nothing about the owner in it
    r = money.rate(tmp_path, opener=Bank(fail=True), now=NOW + timedelta(days=1))
    assert r["per_usd"] == 0.8 and r["source"] == "saved" and not r["stale"]


def test_a_stale_rate_is_labelled(tmp_path):
    money.rate(tmp_path, opener=Bank(), now=NOW)
    later = NOW + timedelta(days=9)
    r = money.rate(tmp_path, opener=Bank(fail=True), now=later)
    assert r["stale"] and r["per_usd"] == 0.8 and "old" in r["words"]
    # a failed try waits an hour before the next one
    bank = Bank(fail=True)
    money.rate(tmp_path, opener=bank, now=later + timedelta(minutes=10))
    assert bank.calls == []


def test_no_rate_at_all_says_so(tmp_path):
    r = money.rate(tmp_path, opener=Bank(fail=True), now=NOW)
    assert r["per_usd"] is None and r["source"] == "none" and "dollars" in r["words"]


def test_a_typed_rate_wins_and_off_asks_nobody(tmp_path):
    money.rate(tmp_path, opener=Bank(), now=NOW)
    money.save(tmp_path, {"rate": "0.79"})
    bank = Bank()
    r = money.rate(tmp_path, opener=bank, now=NOW + timedelta(days=2))
    assert r["per_usd"] == 0.79 and r["source"] == "typed" and bank.calls == []
    assert money.rate(tmp_path, {"rate": 0.7}, opener=bank, now=NOW)["per_usd"] == 0.79  # the app's choice on top
    money.save(tmp_path, {"rate": "auto", "show": "usd"})
    r = money.rate(tmp_path, opener=bank, now=NOW + timedelta(days=3))
    assert r["show"] == "usd" and r["per_usd"] is None and bank.calls == []
    with pytest.raises(ValueError):
        money.save(tmp_path, {"rate": "lots"})
    with pytest.raises(ValueError):
        money.save(tmp_path, {"show": "gbp"})
    assert money.settings(tmp_path / "fresh", {"rate": 0.75})["rate"] == 0.75  # harness.yaml's money:


@pytest.mark.parametrize("usd, rate, text", [
    (1.1875, 0.8, "≈ £0.95"),
    (1.00625, 1.0, "≈ £1.01"),   # half up, not banker's rounding
    (0.005, 1.0, "≈ £0.01"),
    (0.004, 1.0, "≈ under £0.01"),
    (0, 0.8, "≈ £0.00"),
    (1234.5, 1.0, "≈ £1,235"),
    (99.994, 1.0, "≈ £99.99"),
    (3.45, None, ""),
    (None, 0.8, ""),
    ("abc", 0.8, ""),
    (-2, 0.8, ""),
])
def test_pounds_rounds_correctly(usd, rate, text):
    assert money.pounds_text(usd, rate) == text


def test_through_the_app(tmp_path, monkeypatch):
    from roundtable.ui import server

    from .test_livecmd import _app

    app, _ = _app(tmp_path)
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "moneyapi"))
    monkeypatch.setattr(app, "_backup_home", lambda: tmp_path / "home")
    monkeypatch.setattr(money, "OPENER", Bank())
    r = app.dispatch("GET", "/api/rates", {}, {})
    assert r["per_usd"] == 0.8 and r["show"] == "usd+gbp"
    r = app.dispatch("POST", "/api/rates", {}, {"rate": 0.75})
    assert r["per_usd"] == 0.75 and r["source"] == "typed"
    with pytest.raises(server.ApiError):
        app.dispatch("POST", "/api/rates", {}, {"show": "pounds only"})


def test_the_desktop_rounds_the_same(tmp_path):
    """pounds.js's poundsText gives the same words as pounds_text (run by node where it is installed)."""
    import json
    import shutil
    import subprocess
    from importlib import resources

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    js = resources.files("roundtable").joinpath("ui/static/pounds.js").read_text(encoding="utf-8")
    body = js[js.index("export function poundsText"):js.index('// "≈ £0.95", or')].replace("export ", "")
    amounts = [0, 0.001, 0.004, 0.005, 0.0062, 0.12, 0.125, 1.005, 1.1875, 3.45, 12.345, 99.994, 99.996, 100.5, 1234.5]
    rates = [0.79, 0.8, 1.0, 0.7812]
    script = tmp_path / "check.js"
    script.write_text(body + f"\nconsole.log(JSON.stringify({json.dumps(amounts)}.flatMap((u) => "
                      f"{json.dumps(rates)}.map((p) => poundsText(u, p)))));\n", encoding="utf-8")
    got = json.loads(subprocess.run([node, str(script)], capture_output=True, text=True, check=True).stdout)
    assert got == [money.pounds_text(u, p) for u in amounts for p in rates]
