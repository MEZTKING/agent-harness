"""`harness` command line.

    harness init                          write a starter harness.yaml
    harness roles                         show role -> model routing
    harness ask ROLE "prompt"             one-off question to a role's model (routing check)
    harness new DIR "goal" [--approve]    create a project and run it
    harness extend DIR "goal"             add a new goal to an existing project and run it
    harness run DIR                       resume a project
    harness approve DIR                   approve a plan waiting for approval
    harness status DIR                    task board and spend
    harness retry DIR TASK_ID             re-open a failed task
    harness skip DIR TASK_ID              mark a task done without running it
    harness metrics DIR                   per role/model success rate and cost
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from importlib import resources
from pathlib import Path

from .harness.agent import Budget, run_agent
from .harness.config import load_config
from .harness.orchestrator import HarnessError, Orchestrator, Project
from .harness.tools import Toolbox
from .providers.base import ProviderError

STATUS_ICON = {"pending": "·", "running": "▶", "done": "✓", "failed": "✗", "skipped": "-"}


def _printer(verbose: bool):
    def on_event(kind: str, d: dict) -> None:
        if kind == "task_start":
            print(f"\n▶ [{d['task']}] {d['title']}  ({d['role']})", flush=True)
        elif kind == "attempt":
            print(f"  attempt {d['attempt']} on {d['model']}", flush=True)
        elif kind == "tool_call" and verbose:
            mark = "!" if d["error"] else "-"
            print(f"    {mark} {d['tool']} {json.dumps(d['args'])[:150]}", flush=True)
        elif kind == "model_turn" and verbose and d.get("text"):
            print(f"    > {d['text'][:200]}", flush=True)
        elif kind == "review":
            verdict = "approved" if d["approved"] else "REJECTED"
            print(f"  review: {verdict} - {d['feedback'][:300]}", flush=True)
        elif kind == "task_end":
            print(f"{STATUS_ICON.get(d['status'], '?')} [{d['task']}] {d['status']}: {d['summary'][:300]}", flush=True)
        elif kind == "plan":
            print("\nPlan:", flush=True)
            for t in d["tasks"]:
                print(f"  {t}", flush=True)
        elif kind == "planning":
            print(f"Planning with {d['model']}...", flush=True)
        elif kind == "provider_error":
            print(f"  provider error ({d['model']}): {d['error'][:300]}", flush=True)
        elif kind == "status":
            print(f"[status: {d['status']}]", flush=True)

    return on_event


def _status(project: Project) -> None:
    meta = project.meta()
    print(f"Project: {project.root}")
    print(f"Status:  {meta.get('status')}    Spent: ${meta.get('spent_usd', 0):.4f}"
          + (f" (+{meta['unpriced_calls']} unpriced calls)" if meta.get("unpriced_calls") else ""))
    for i, g in enumerate(meta.get("goals", []), 1):
        print(f"Goal {i}:  {g}")
    print()
    for t in project.tasks():
        deps = f"  (after {', '.join(t.depends_on)})" if t.depends_on else ""
        print(f" {STATUS_ICON.get(t.status, '?')} {t.id:6} {t.role:10} {t.title}{deps}")
        if t.status in ("done", "failed") and t.summary:
            print(f"          {t.summary[:160]}")
    summary = project.dir / "summary.md"
    if meta.get("status") == "done" and summary.exists():
        print(f"\nReport: {summary}")


def _metrics(project: Project) -> None:
    path = project.dir / "metrics.jsonl"
    if not path.exists():
        print("no metrics yet")
        return
    agg: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(float))
    for line in path.read_text().splitlines():
        r = json.loads(line)
        a = agg[(r["role"], r["model"])]
        a["attempts"] += 1
        a[r["outcome"]] += 1
        a["cost"] += r.get("cost_usd") or 0
        a["seconds"] += r.get("seconds") or 0
    print(f"{'role':10} {'model':38} {'tries':>5} {'ok':>4} {'rate':>5} {'cost $':>9} {'avg s':>6}")
    for (role, model), a in sorted(agg.items()):
        rate = a["approved"] / a["attempts"] if a["attempts"] else 0
        print(f"{role:10} {model:38} {int(a['attempts']):5} {int(a['approved']):4} {rate:5.0%} "
              f"{a['cost']:9.4f} {a['seconds'] / a['attempts']:6.1f}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description="Multi-provider project harness")
    p.add_argument("--config", help="path to harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("-v", "--verbose", action="store_true", help="show every model turn and tool call")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("path", nargs="?", default="harness.yaml")
    s.add_argument("--force", action="store_true")
    sub.add_parser("roles")
    s = sub.add_parser("ask")
    s.add_argument("role")
    s.add_argument("prompt")
    s = sub.add_parser("new")
    s.add_argument("dir")
    s.add_argument("goal")
    s.add_argument("--approve", action="store_true", help="stop after planning until you run `harness approve`")
    s.add_argument("--max-tasks", type=int)
    s = sub.add_parser("extend")
    s.add_argument("dir")
    s.add_argument("goal")
    s.add_argument("--max-tasks", type=int)
    s = sub.add_parser("run")
    s.add_argument("dir")
    s.add_argument("--max-tasks", type=int)
    for name in ("approve", "status", "metrics"):
        sub.add_parser(name).add_argument("dir")
    for name in ("retry", "skip"):
        s = sub.add_parser(name)
        s.add_argument("dir")
        s.add_argument("task_id")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        target = Path(args.path)
        if target.exists() and not args.force:
            sys.exit(f"error: {target} exists (use --force)")
        target.write_text(resources.files("agentharness").joinpath("templates/harness.example.yaml").read_text())
        print(f"wrote {target}. Set your API keys as environment variables, then: harness roles")
        return
    if args.cmd in ("status", "metrics"):
        project = Project(args.dir)
        if not project.exists:
            sys.exit(f"error: no project in {args.dir}")
        return _status(project) if args.cmd == "status" else _metrics(project)

    try:
        cfg = load_config(args.config)
        if args.cmd == "roles":
            for r in cfg.roles.values():
                chain = " -> ".join(str(m) for m in r.models)
                tag = " [planner]" if r.name == cfg.planner_role else " [reviewer]" if r.name == cfg.reviewer_role else ""
                print(f"{r.name:12} {r.kind:5} {chain}{tag}")
                if r.description:
                    print(f"{'':18} {r.description}")
            return
        if args.cmd == "ask":
            role = cfg.roles.get(args.role)
            if not role:
                sys.exit(f"error: unknown role {args.role!r}")
            if role.kind != "chat":
                sys.exit("error: `ask` only works for chat roles")
            res = run_agent(cfg, role.models[0], cfg.prompt_text(role.prompt), args.prompt, Toolbox(),
                            Budget(cfg.limits.max_cost_usd), max_steps=1, max_tokens=role.max_tokens, options=role.options)
            print(res.text)
            cost = f"${res.cost_usd:.5f}" if cfg.cost(role.models[0], res.usage) is not None else "unpriced"
            print(f"\n[{res.model} · {res.usage.input_tokens} in / {res.usage.output_tokens} out · {cost}]", file=sys.stderr)
            return

        orch = Orchestrator(cfg, args.dir, on_event=_printer(args.verbose))
        if args.cmd == "new":
            orch.start(args.goal, require_approval=args.approve)
        elif args.cmd == "extend":
            orch.extend(args.goal)
        elif args.cmd == "approve":
            orch.approve()
            print("plan approved; run `harness run DIR` to start")
            return
        elif args.cmd in ("retry", "skip"):
            getattr(orch, args.cmd)(args.task_id)
            print(f"{args.task_id}: {'re-opened' if args.cmd == 'retry' else 'skipped'}; run `harness run DIR` to continue")
            return
        result = orch.run(max_tasks=getattr(args, "max_tasks", None))
        print()
        _status(orch.project)
        hints = {
            "awaiting_approval": "Review the plan above, then: harness approve DIR && harness run DIR",
            "blocked": "A task failed. Inspect with `harness status DIR`, then `harness retry DIR TASK` or `harness skip DIR TASK`.",
            "paused_budget": "Budget reached. Raise limits.max_cost_usd in harness.yaml, then `harness run DIR`.",
            "paused": "Paused after --max-tasks. Continue with `harness run DIR`.",
        }
        if result in hints:
            print("\n" + hints[result].replace("DIR", args.dir))
    except (HarnessError, ProviderError, FileNotFoundError, ValueError) as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ninterrupted - progress is saved; resume with `harness run DIR`")


if __name__ == "__main__":
    main()
