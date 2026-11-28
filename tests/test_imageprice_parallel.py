"""Picture spending counted safely when several pictures are made at once (harness/imageprice.py)."""

import json
import threading

from roundtable.harness import imageprice


def test_twenty_pictures_priced_from_four_threads_add_up_exactly(tmp_path):
    f = tmp_path / "metrics.jsonl"
    prices = [round(0.01 + i * 0.0013, 6) for i in range(20)]
    start = threading.Barrier(4)

    def worker(mine):
        start.wait()  # all four at once
        for usd in mine:
            imageprice.record(f, {"model": "openrouter-images/made-up", "cost_usd": usd, "outcome": "approved",
                                  "note": "x" * 3000})  # long lines: a torn write would show

    threads = [threading.Thread(target=worker, args=(prices[i::4],)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20 and all(json.loads(ln)["note"] == "x" * 3000 for ln in lines)
    assert imageprice.spent([f]) == round(sum(prices), 9)
    assert sorted(json.loads(ln)["cost_usd"] for ln in lines) == sorted(prices)
    assert abs(imageprice.reported([f])["openrouter-images/made-up"] - sum(prices) / 20) < 1e-12


def test_spent_skips_errors_and_the_owners_notes(tmp_path):
    f = tmp_path / "spend.jsonl"
    imageprice.record(f, {"model": "m", "cost_usd": 0.04})
    imageprice.record(f, {"model": "m", "cost_usd": 9, "outcome": "error"})
    imageprice.record(f, {"model": "m", "cost_usd": 9, "outcome": "owner_feedback"})
    with f.open("a") as fh:
        fh.write("not json\n")
    assert imageprice.spent([f, tmp_path / "missing.jsonl"]) == 0.04
