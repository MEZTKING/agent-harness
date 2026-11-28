"""The estimate's defaults from real runs (wave 9): medians by job and size, the fixed figures below ten rows,
and the estimate written beside the real cost after a run. Made-up projects only."""

import json

from roundtable.harness import estimatedefaults as ed


def _project(root, rows, sizes=None):
    h = root / ".harness"
    h.mkdir(parents=True)
    (h / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if sizes:
        (h / "stages.json").write_text(json.dumps({"sizes": sizes}), encoding="utf-8")
    return h / "metrics.jsonl"


def test_defaults_come_from_twelve_real_rows(tmp_path):
    rows = [{"task": f"T{i}", "role": "coder", "outcome": "approved", "input_tokens": 10_000 + i * 1_000,
             "output_tokens": 2_000 + i * 100} for i in range(12)]
    rows.append({"task": "T1", "role": "coder", "outcome": "owner_feedback"})  # not an attempt
    rows.append({"task": "P1", "role": "artist", "outcome": "approved", "input_tokens": 0, "output_tokens": 0})
    f = _project(tmp_path / "kite-shop", rows, sizes={f"T{i}": "small" for i in range(12)})
    d = ed.for_role([f], "coder")
    assert d["basis"] == "coder" and d["samples"] == 12
    assert d["input"] == 15_500 and d["output"] == 2_550  # the median, not the mean
    lo, hi = d["spread"]["input"]
    assert lo < d["input"] < hi
    assert "12 real attempts" in d["words"]
    assert ed.for_role([f], "coder", "small")["basis"] == "coder, small tasks"
    assert ed.for_role([f], "coder", "large")["basis"] == "coder"  # no large ones: the job as a whole
    assert ed.for_role([f], "tester")["basis"] == "every job"  # another job: every attempt here
    assert ed.tokens([f], "coder") == (15_500, 2_550)


def test_below_ten_rows_the_fixed_figures_stand(tmp_path):
    rows = [{"task": "T1", "role": "coder", "input_tokens": 5_000, "output_tokens": 500}] * 9
    f = _project(tmp_path / "pond", rows)
    d = ed.for_role([f], "coder")
    assert (d["input"], d["output"]) == ed.FALLBACK and d["basis"] == "fixed"
    assert "Fewer than 10" in d["words"]
    assert ed.for_role([], "coder")["basis"] == "fixed"
    assert ed.for_role([tmp_path / "missing.jsonl"], "coder")["basis"] == "fixed"


def test_lab_files_are_found_and_read_once(tmp_path):
    lab = tmp_path / "lab"
    a = _project(lab / "a", [{"task": "T1", "role": "coder", "input_tokens": 100, "output_tokens": 10}] * 6)
    _project(lab / "b", [{"task": "T1", "role": "coder", "input_tokens": 300, "output_tokens": 30}] * 6)
    files = ed.lab_metric_files(a.parent, lab)
    assert len(files) == 3  # this project's own, then both lab projects (a twice: read once)
    assert len(ed.rows(files)) == 12


def test_after_a_run_the_estimate_sits_beside_the_real_cost(tmp_path):
    h = tmp_path / ".harness"
    got = ed.after_run(h, 1.00, 1.10, "kite-shop", now="2026-11-28T10:00:00Z")
    assert got["line"] == "" and got["row"]["drift"] == 0.1
    got = ed.after_run(h, 1.00, 1.60, "kite-shop")
    assert got["line"].startswith("kite-shop: the run cost $1.60, 60% more than the estimate of $1.00")
    got = ed.after_run(h, 2.00, 1.00)
    assert "50% less" in got["line"]
    assert ed.after_run(h, None, 1.0)["line"] == "" and ed.after_run(h, 0, 1.0)["row"]["drift"] is None
    assert len(ed.history(h)) == 5
