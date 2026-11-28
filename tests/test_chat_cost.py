"""What the chat costs (1.5.0): a message is priced from the tokens the service reports, at DeepSeek's listed
prices (half off-peak); the day's allowance is every device's spend, reserved before the call and settled after;
"at most $N" on a build is the run's own limit. Scripted models, a made-up hub and project."""

from __future__ import annotations

import pytest

from roundtable import chat, chatstore
from roundtable.harness import slash
from roundtable.harness.config import DEFAULT_PRICING, in_peak
from roundtable.providers.base import Usage

from .chatworld import World


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def table_figure() -> float:
    """The plan's table: 5,000 cached + 1,000 fresh + 300 out on deepseek-v4-flash."""
    p = DEFAULT_PRICING["deepseek-v4-flash"]
    p = p if in_peak(p["peak_utc"]) else {**p, **p["offpeak"]}
    return (5000 * p["cache_read"] + 1000 * p["input"] + 300 * p["output"]) / 1_000_000


def test_a_6000_in_300_out_message_costs_the_tables_figure(world):
    world.model.usage = Usage(input_tokens=1000, output_tokens=300, cache_read_tokens=5000)
    line = chat.reply(world.app, world.chat, "how is it?")
    assert line["cost_usd"] == pytest.approx(table_figure(), abs=1e-6)
    assert table_figure() == pytest.approx(0.000906, abs=1e-6) or table_figure() == pytest.approx(0.000453, abs=1e-6)
    assert chat.estimate(world.cfg, world.chat) == pytest.approx(table_figure(), abs=1e-6)


def test_the_allowance_counts_every_devices_spend_today(world):
    chatstore.append(None, world.hub, "hall", {"who": "chat", "seat": "phone-abc123", "text": "x", "cost_usd": 0.4})
    chatstore.append(world.home, world.hub, world.chat, {"who": "chat", "seat": chatstore.me()["id"], "text": "y",
                                                         "cost_usd": 0.5})
    assert chat.spent_today(world.app) == pytest.approx(0.9)
    world.cfg.chat.max_usd_per_day = 0.9
    assert world.read()["can"] == {"answer": False, "why": "allowance"}
    line = chat.reply(world.app, world.chat, "hello")
    assert line["who"] == "app" and "$0.90" in line["text"]


def test_the_reserve_is_set_aside_during_the_call_and_settled_after(world):
    seen = []

    def during(model, system, messages, tools):
        seen.append(chat.spent_today(world.app))
        return "ok"

    world.model.answers = [during]
    line = chat.reply(world.app, world.chat, "x")
    assert seen[0] >= chat._reserve(world.cfg, chat.model_for(world.cfg, None)) > 0
    assert chat.spent_today(world.app) == pytest.approx(line["cost_usd"])  # settled with the real charge


def test_the_chats_spend_is_in_the_wallets_ledger_as_chat(world):
    chat.reply(world.app, world.chat, "x")
    ledger = list((world.home / "usage").rglob("*"))
    assert ledger, "the chat's call is in the usage ledger"
    text = "".join(p.read_text(encoding="utf-8") for p in ledger if p.is_file())
    assert '"role": "chat"' in text or '"role":"chat"' in text


def test_at_most_n_is_the_runs_own_limit_and_a_scripted_run_stops_at_it(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, plan=True)
    orch = w.orch
    spent0 = orch.budget.spent_usd
    status = slash.build_project(orch, "", cap=0.0002)
    assert status != "done"
    meta = orch.project.meta()
    assert orch.budget.limit_usd == pytest.approx(spent0 + 0.0002)
    # one call can't be cut off halfway: it stops at the first charge past the limit
    assert meta.get("spent_usd", 0) - spent0 < 0.0002 + 0.001
    assert slash.split_cap("the accepted ideas, at most $2") == ("the accepted ideas", 2.0)
    assert slash.split_cap("$3 max") == ("", 3.0) and slash.split_cap("no limit") == ("no limit", None)


def test_a_card_says_the_price_and_where_it_stops(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, plan=True)
    w.model.answers = ["The plan waits for you.\nAction: /approve at most $2"]
    card = chat.reply(w.app, w.chat, "approve it, at most $2")["card"]
    assert card["title"] == "Approve the plan and build" and card["cap_usd"] == 2.0
    assert card["price_usd"] > 0 and card["line"].startswith("About $") and "stops at $2.00" in card["line"]
