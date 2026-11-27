"""Wave 6 end to end, scripted: a made-up game with one hard task under Balanced. The hard task is tagged, routed
to the model that wins its kind of work, built by two rivals from different makers, checked by two makers who
didn't build it; the estimate is within 10 % of what was spent and the extra checking stays inside its allowance.
Every stage is the real one (the full Orchestrator); the models are scripted (the maker is the provider id)."""

import json

from roundtable.harness import dial, makers

from .test_dial import RealStages, _tap_charges, build, plan_of, run_spend


def game_plan():
    plan = plan_of("ordinary", "hard", "ordinary", "ordinary")
    for t in plan:
        t["files"] = [f"src/part{t['id'][1:]}.py"]
    plan[1].update(title="the game loop", description="write the game loop", tags=["game-logic"],
                   why_hard="the turn order is easy to get wrong")
    return plan


def test_a_made_up_game_with_one_hard_task_under_balanced(tmp_path):
    plan = game_plan()
    before, _ = build(tmp_path, cls=RealStages, plan=plan, name="before", tandem={"default": "lean"})
    before.start("a made-up board game")
    before.plan()
    before.approve()
    assert before.run() == "done"
    # the past: b's coder has won game-logic work every time (5 or more judged tries), a's has no record of it
    rows = []
    for i, ln in enumerate((before.project.dir / "metrics.jsonl").read_text().splitlines() * 2):
        r = json.loads(ln)
        if r["role"] == "coder":
            r.update(task=f"P{i}", model="b/coder2", tags=["game-logic"], hard=False, risky=False)
        rows.append(json.dumps(r))

    orch, events = build(tmp_path, cls=RealStages, plan=plan, name="game")
    _tap_charges(orch)
    orch.start("a made-up board game")
    (orch.project.dir / "metrics.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    orch.plan()
    doc = orch.project.plan_doc()
    est = doc["estimate"]
    assert doc["checking"] == "balanced" and set(doc["checking_estimates"]) == set(dial.LEVELS)
    assert any(e["id"] == "dial" for e in est["extras"])
    orch.approve()
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    hard = tasks["T2"]

    # tagged
    assert hard.hard and "game-logic" in hard.tags
    row = [json.loads(x) for x in (orch.project.dir / "metrics.jsonl").read_text().splitlines()][-8:]
    assert any(r.get("task") == "T2" and "game-logic" in (r.get("tags") or []) for r in row)
    # routed: b's coder goes first for game logic, with the reason
    routed = [d for k, d in events if k == "routed" and d.get("task") == "T2"]
    assert routed and (routed[0]["model"], routed[0]["from"]) == ("b/coder2", "a/coder")
    assert "game logic" in routed[0]["why"] and not routed[0]["explore"]
    # built by two rivals from different makers; one was chosen, the other kept with why
    last = hard.attempts[-1]
    assert last["outcome"] == "approved" and len(last["rivals"]) == 2
    assert len({r["maker"] for r in last["rivals"]}) == 2 and sum(bool(r["picked"]) for r in last["rivals"]) == 1
    assert [k for k, _ in events if k == "rival_kept"]
    # checked by two makers, neither the builder's
    counted = [r for r in last["reviews"] if r["counted"] is True]
    builder = makers.maker(last["model"])
    assert len({r["maker"] for r in counted}) == 2 and builder not in {r["maker"] for r in counted}
    # the ordinary tasks had the usual one builder and one checker
    assert all(len(tasks[t].attempts) == 1 and "rivals" not in tasks[t].attempts[0] for t in ("T1", "T3", "T4"))

    # the estimate within 10 % (less the money kept for a stuck task, which a clean run never spends)
    spare = sum(e.get("usd") or 0 for e in est["extras"] if e["id"] == "unstick")
    spend = run_spend(orch)
    assert abs(est["cost_usd"] - spare - spend) <= 0.10 * spend, (est, spend)
    # the extras stayed inside their own share of the money
    a = dial.allowance_view(orch.project.root, orch.project.meta())
    assert a["usd"] and a["spent"] <= a["usd"] and not a["used_up"]
    assert not {"stage_error"} & {k for k, _ in events}
    print(f"\nend to end: estimate ${est['cost_usd'] - spare:.4f}, spend ${spend:.4f}, "
          f"extras ${a['spent']:.4f} of ${a['usd']:.4f}; T2 built by {last['model']}, "
          f"rivals {[r['model'] for r in last['rivals']]}, checked by {[r['model'] for r in counted]}")
