"""`harness` command line.

    roundtable init                          write a starter harness.yaml
    roundtable roles                         show role -> model routing
    roundtable ask ROLE "prompt"             one-off question to a role's model (routing check)
    roundtable image ROLE "prompt" [--out F] [--style S] [--size WxH] [--remove-bg] [--cost-only]
    roundtable image ROLE --styles           list the styles an image role's provider offers
    roundtable new DIR "goal" [--approve]    create a project and run it
    roundtable extend DIR "goal"             add a new goal to an existing project and run it
    roundtable run DIR                       resume a project
    roundtable approve DIR                   approve a plan waiting for approval
    roundtable status DIR                    task board and spend
    roundtable retry DIR TASK_ID             re-open a failed task
    roundtable skip DIR TASK_ID              mark a task done without running it
    roundtable metrics DIR                   per role/model success rate and cost
    roundtable ui [--port 8765]              web UI (same as `roundtable ui`)
    roundtable feedback DIR TASK_ID --good|--bad ["note"]   rate a finished task (feeds learning)

    roundtable probe [--role R] [--model M] [--images]   quick health check: regressions / boosts per model

    roundtable improve analyze [--llm]       find improvement proposals in run history
    roundtable improve propose ROLE --models a/x,b/y | --prompt-file F | --options JSON
                                          suggest your own change (then test it like any other)
    roundtable improve list | show ID        review proposals
    roundtable improve test ID               replay past tasks: current vs proposed setup
    roundtable improve apply ID | reject ID  decide
    roundtable improve rollback [VERSION]    undo applied changes
    roundtable improve status                what has been learned, and history
    roundtable improve cycle [--llm] [--test]  analyze + test + auto-apply per policy
"""

from __future__ import annotations

import argparse
import os
import json
import sys
from collections import defaultdict
from importlib import resources
from pathlib import Path

import yaml

from .harness.agent import Budget, run_agent
from .harness.config import load_config
from .harness.orchestrator import HarnessError, Orchestrator, Project
from .harness.tools import Toolbox
from .core.models import utcnow
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
    p = argparse.ArgumentParser(prog="roundtable", description="Roundtable Hold: projects, models and self-improvement")
    p.add_argument("--config", help="path to harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("-v", "--verbose", action="store_true", help="show every model turn and tool call")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("path", nargs="?", default="harness.yaml")
    s.add_argument("--force", action="store_true")
    sub.add_parser("roles")
    sub.add_parser("balance", help="the money left with providers that report it (DeepSeek)")
    s = sub.add_parser("ask")
    s.add_argument("role")
    s.add_argument("prompt")
    pv = sub.add_parser("providers", help="add, test and list AI providers")
    psub = pv.add_subparsers(dest="pcmd", required=True)
    psub.add_parser("presets", help="providers you can add with one command")
    psub.add_parser("list", help="configured providers")
    s = psub.add_parser("add", help="add a provider (to custom.yaml)")
    s.add_argument("preset", help="a preset id from `providers presets`, or custom / plugin")
    s.add_argument("--id", help="name to use in model refs (default: the preset id)")
    s.add_argument("--base-url")
    s.add_argument("--key-env", help="environment variable holding the API key")
    s.add_argument("--auth-header", help="send the key in this header instead of Authorization (e.g. api-key)")
    s.add_argument("--auth-prefix", default="", help="text before the key in that header (e.g. 'Bearer ')")
    s.add_argument("--header", action="append", default=[], help="extra header NAME=VALUE (repeatable)")
    s.add_argument("--query", action="append", default=[], help="extra URL query NAME=VALUE (e.g. api-version=...)")
    s.add_argument("--class", dest="plugin_class", help="plugin: 'my_file.py:MyProvider' in the plugins folder")
    for name in ("remove", "test", "models"):
        psub.add_parser(name).add_argument("id")
    s = sub.add_parser("assign", help="choose the model(s) a role uses: primary first, then fallbacks")
    s.add_argument("role")
    s.add_argument("models", nargs="+", help="provider/model ...")
    s.add_argument("--kind", choices=["chat", "image"], help="for a new role")
    s.add_argument("--description", help="for a new role: what it's good at (the planner reads this)")

    s = sub.add_parser("ui", help="open the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--hub-config")
    s.add_argument("--projects-dir", default=".")
    s.add_argument("--no-browser", action="store_true")
    s = sub.add_parser("image", help="generate one image with an image role")
    s.add_argument("role")
    s.add_argument("prompt", nargs="?", default="")
    s.add_argument("--out", default="image.png")
    s.add_argument("--style")
    s.add_argument("--size", help="WIDTHxHEIGHT, e.g. 64x64")
    s.add_argument("--remove-bg", action="store_true")
    s.add_argument("--cost-only", action="store_true", help="free price check, generates nothing")
    s.add_argument("--styles", action="store_true", help="list available styles")
    s = sub.add_parser("new")
    s.add_argument("dir")
    s.add_argument("goal")
    s.add_argument("--approve", action="store_true", help="stop after planning until you run `roundtable approve`")
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
    s = sub.add_parser("feedback", help="rate a finished task")
    s.add_argument("dir")
    s.add_argument("task_id")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--good", action="store_true")
    g.add_argument("--bad", action="store_true")
    s.add_argument("note", nargs="?", default="")

    s = sub.add_parser("probe", help="quick model regression / boost check")
    s.add_argument("--role", action="append", default=[], help="only models used by this role (repeatable)")
    s.add_argument("--model", action="append", default=[], help="provider/model to probe (repeatable)")
    s.add_argument("--probe", action="append", default=[], help="only this probe (repeatable)")
    s.add_argument("--images", action="store_true", help="also generate one real test image per image model (costs)")
    s.add_argument("--max-cost", type=float, default=1.0)
    s.add_argument("--no-save", action="store_true", help="don't add this run to the baseline history")
    s.add_argument("--details", action="store_true", help="show every probe result")

    imp = sub.add_parser("improve", help="self-improvement loop")
    isub = imp.add_subparsers(dest="icmd", required=True)
    s = isub.add_parser("analyze")
    s.add_argument("--llm", action="store_true", help="also ask the analyst model for proposals")
    s.add_argument("--max-cost", type=float, default=2.0)
    s.add_argument("--project", action="append", default=[], help="extra project dirs to learn from")
    s = isub.add_parser("propose", help="suggest your own change")
    s.add_argument("role")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--models", help="comma-separated chain, primary first")
    g.add_argument("--prompt-file")
    g.add_argument("--options", help='JSON, e.g. \'{"effort": "high"}\'')
    s.add_argument("--why", default="owner suggestion")
    s.add_argument("--risk", default="medium", choices=["low", "medium", "high"])
    s = isub.add_parser("list")
    s.add_argument("--all", action="store_true")
    for name in ("show", "apply", "reject"):
        s = isub.add_parser(name)
        s.add_argument("id")
        if name == "apply":
            s.add_argument("--force", action="store_true", help="apply even if untested, failed, or a model is acting up")
            s.add_argument("--skip-probe", action="store_true", help="don't health-check the involved models first")
    s = isub.add_parser("test")
    s.add_argument("id")
    s.add_argument("--samples", type=int, default=3)
    s.add_argument("--max-cost", type=float, default=2.0)
    s = isub.add_parser("rollback")
    s.add_argument("version", nargs="?", type=int)
    isub.add_parser("status")
    s = isub.add_parser("cycle")
    s.add_argument("--skip-probe", action="store_true")
    s.add_argument("--llm", action="store_true")
    s.add_argument("--test", action="store_true", help="replay-test new proposals (spends money)")
    s.add_argument("--samples", type=int, default=3)
    s.add_argument("--max-cost", type=float, default=2.0)
    return p


def _lab(cfg):
    from .improve.lab import Lab

    if not cfg.lab_dir:
        raise HarnessError("no lab directory (set improve.lab_dir in harness.yaml)")
    return Lab(cfg.lab_dir)


def _show_proposal(p) -> None:
    print(f"{p.id}  [{p.status}]  risk={p.risk}  source={p.source}  created {p.created_at}")
    print(f"  {p.summary()}")
    print(f"  why: {p.rationale}")
    if p.kind == "prompt":
        print("  --- proposed prompt ---")
        print("  " + p.change["prompt_text"].replace("\n", "\n  "))
    if p.evidence:
        print(f"  evidence: {json.dumps(p.evidence)}")
    if p.test:
        t = p.test
        print(f"  test: {t['verdict']} ({'passed' if t['passed'] else 'not passed'}) on {t['tasks_compared']} task(s): "
              f"current {t['current']['approved']} approved / ${t['current']['cost_usd']:.4f}, "
              f"candidate {t['candidate']['approved']} approved / ${t['candidate']['cost_usd']:.4f}"
              + (f"  [{t['note']}]" if t.get("note") else ""))


def _improve(args, cfg) -> None:
    from .improve.analysis import analyze, stats_table
    from .improve.evaluate import evaluate
    from .improve.loop import cycle

    lab = _lab(cfg)
    printer = _printer(args.verbose)

    def on_event(kind, d):
        if kind == "replay":
            print(f"  replaying {d['project']}:{d['task']} with {d['variant']} setup...", flush=True)
        else:
            printer(kind, d)

    if args.icmd == "analyze":
        ds, new, cost = analyze(cfg, lab, use_llm=args.llm, max_cost=args.max_cost,
                                extra=[Path(p) for p in args.project], on_event=on_event)
        print(f"Learned from {len(ds.projects)} project(s), {ds.tasks} task(s).\n")
        print(stats_table(ds) if ds.stats else "(no metrics yet - run some projects first)")
        print(f"\n{len(new)} new proposal(s)" + (f" (analyst cost ${cost:.4f})" if cost else "") + ":")
        for p in new:
            print(f"  {p.id}  {p.summary()}  [{p.risk}]")
            print(f"        {p.rationale}")
        if new:
            print("\nNext: roundtable improve show ID, then test / apply / reject")
    elif args.icmd == "propose":
        from .improve.lab import Proposal

        if args.models:
            kind, change = "routing", {"models": [m.strip() for m in args.models.split(",") if m.strip()]}
        elif args.prompt_file:
            kind, change = "prompt", {"prompt_text": Path(args.prompt_file).read_text(encoding="utf-8")}
        else:
            kind, change = "options", {"options": json.loads(args.options)}
        p = Proposal(id="", kind=kind, role=args.role, change=change, rationale=args.why, risk=args.risk, source="owner")
        p.validate(cfg)
        lab.add_proposal(p)
        print(f"added {p.id}: {p.summary()}\ntest it with: roundtable improve test {p.id}")
    elif args.icmd == "list":
        props = lab.proposals() if args.all else [p for p in lab.proposals() if p.status in ("proposed", "tested")]
        for p in props:
            verdict = f" test:{p.test['verdict']}" if p.test else ""
            print(f"{p.id}  {p.status:11} {p.risk:6} {p.source:5} {p.summary()}{verdict}")
        if not props:
            print("no open proposals" + ("" if args.all else " (use --all to see decided ones)"))
    elif args.icmd == "show":
        _show_proposal(lab.proposal(args.id))
    elif args.icmd == "test":
        p = lab.proposal(args.id)
        print(f"Testing {p.id} on up to {args.samples} past task(s), budget ${args.max_cost:.2f}...")
        evaluate(cfg, lab, p, samples=args.samples, max_cost=args.max_cost, on_event=on_event)
        _show_proposal(lab.proposal(args.id))
    elif args.icmd == "apply":
        p = lab.proposal(args.id)
        if p.status == "applied":
            sys.exit(f"{p.id} is already applied")
        if not args.force and not (p.test and p.test.get("passed")) and not (p.source == "rules" and p.kind == "routing"):
            sys.exit(f"{p.id} has not passed a replay test. Run `roundtable improve test {p.id}` or use --force.")
        if not args.skip_probe and cfg.improve.get("probe_before_apply", True):
            from .improve.probe import check, models_for_proposal

            models = models_for_proposal(cfg, p)
            print(f"Health-checking {', '.join(map(str, models))} before applying (skip with --skip-probe)...")
            reports = check(cfg, lab.root, [m for m in models if cfg.roles[p.role].kind == "chat"])
            _print_probe_reports(reports, details=False)
            bad = [r.model for r in reports if r.bad]
            if bad and not args.force:
                sys.exit(f"not applied: {', '.join(bad)} acting up right now. Retry later, or use --force.")
        version = lab.apply(p, cfg, reason="manual")
        print(f"applied {p.id} as version {version}: {p.summary()}\nundo with: roundtable improve rollback {version}")
    elif args.icmd == "reject":
        p = lab.proposal(args.id)
        p.status = "rejected"
        lab.save_proposal(p)
        print(f"rejected {p.id}")
    elif args.icmd == "rollback":
        v = lab.rollback(args.version)
        print(f"rolled back to the state before version {v}")
    elif args.icmd == "status":
        overlay, prompts = lab.learned()
        print(f"Lab: {lab.root}")
        print(f"Policy: auto_apply={cfg.improve.get('auto_apply', 'none')}\n")
        print("Effective routing (harness.yaml + learned):")
        for r in cfg.roles.values():
            learned = " (learned)" if r.name in (overlay.get("roles") or {}) else ""
            print(f"  {r.name:12} {' -> '.join(str(m) for m in r.models)}{learned}")
        if prompts:
            print(f"Learned prompts: {', '.join(sorted(prompts))}")
        hist = lab.history()
        if hist:
            print("\nHistory:")
            for h in hist[-15:]:
                detail = h.get("summary") or h.get("versions", "")
                print(f"  {h['at']}  {h['event']:11} {h.get('proposal', ''):8} v{h.get('version', '')} {detail}")
    elif args.icmd == "cycle":
        rep_ = cycle(cfg, lab, use_llm=args.llm, test=args.test, max_cost=args.max_cost,
                     samples=args.samples, on_event=on_event, probe=not args.skip_probe)
        print(json.dumps(rep_, indent=2))


def _image(args, cfg) -> None:
    role = cfg.roles.get(args.role)
    if not role or role.kind != "image":
        sys.exit(f"error: {args.role!r} is not an image role")
    ref = role.models[0]
    provider = cfg.provider(ref.provider)
    if args.styles:
        if not hasattr(provider, "styles"):
            sys.exit(f"error: {ref.provider} has no style catalog")
        for sid, st in sorted(provider.styles().items()):
            print(f"{sid:40} {st['min_width']}-{st['max_width']}px  {st.get('name', '')}")
        return
    if not args.prompt:
        sys.exit("error: give a prompt")
    opts = dict(role.options)
    if args.style:
        opts["style"] = args.style
    if args.size:
        w, _, h = args.size.lower().partition("x")
        opts["width"], opts["height"] = int(w), int(h or w)
    if args.remove_bg:
        opts["remove_bg"] = True
    if args.cost_only:
        if not hasattr(provider, "check_cost"):
            sys.exit(f"error: {ref.provider} has no free cost check")
        print(f"${provider.check_cost(opts.get('style') or ref.model, args.prompt, opts):.4f}")
        return
    data, ext, usage = provider.generate(ref.model, args.prompt, opts)
    out = Path(args.out)
    if out.suffix.lower() != f".{ext}":
        out = out.with_suffix(f".{ext}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    cost = cfg.cost(ref, usage)
    print(f"saved {out} ({len(data)} bytes) via {opts.get('style') or ref}"
          + (f" · ${cost:.4f}" if cost is not None else ""))


STATUS_MARK = {"OK": "ok", "NEW": "new", "DOWN": "DOWN", "REGRESSION": "REGRESSION", "BOOST": "boost",
               "SLOW": "slow", "FAST": "fast", "VERBOSE": "verbose"}


def _print_probe_reports(reports, details: bool) -> None:
    print(f"\n{'model':40} {'score':>7} {'usual':>6} {'time s':>7} {'usual':>6} {'tokens':>7} {'cost $':>8}  status")
    for r in reports:
        usual = f"{r.baseline_score:.0%}" if r.baseline_score is not None else "-"
        usual_t = f"{r.baseline_seconds:.0f}" if r.baseline_seconds is not None else "-"
        print(f"{r.model:40} {r.passed:>3}/{r.total:<3} {usual:>6} {r.seconds:7.1f} {usual_t:>6} {r.output_tokens:7} "
              f"{r.cost_usd:8.4f}  {' '.join(STATUS_MARK.get(s, s) for s in r.status)}")
        for n in r.notes:
            print(f"{'':42}- {n[:150]}")
        if details:
            for x in r.results:
                print(f"{'':42}{'pass' if x.passed else 'FAIL'} {x.probe:14} {x.seconds:5.1f}s  {(x.error or x.detail)[:90]}")


def _probe(args, cfg) -> None:
    from .improve.probe import check, models_in_config

    if not cfg.lab_dir:
        raise HarnessError("no lab directory (set improve.lab_dir in harness.yaml)")
    if args.model:
        from .harness.config import ModelRef

        refs = [ModelRef.parse(m) for m in args.model]
        image_kinds = {str(m) for r in cfg.roles.values() if r.kind == "image" for m in r.models}
        chat = [m for m in refs if str(m) not in image_kinds]
        image = [m for m in refs if str(m) in image_kinds]
    else:
        chat, image = models_in_config(cfg, args.role or None)
    print(f"Probing {len(chat)} chat model(s)" + (f" and {len(image)} image model(s)" if image else "") + "...")

    def on_result(r):
        print(f"  {'pass' if r.passed else 'FAIL'}  {r.model:38} {r.probe:14} {r.seconds:5.1f}s", flush=True)

    reports = check(cfg, cfg.lab_dir, chat, image, only=args.probe or None, generate_images=args.images,
                    max_cost=args.max_cost, save=not args.no_save, on_result=on_result if args.verbose else None)
    _print_probe_reports(reports, args.details)
    bad = [r for r in reports if r.bad]
    if bad:
        print(f"\n{len(bad)} model(s) acting up. Hold off on big changes that involve them.")
        sys.exit(1)
    if any("NEW" in r.status for r in reports):
        print("\nFirst run for some models: saved as their baseline. Run again later to detect changes.")


def _pairs(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        if "=" not in it:
            raise ValueError(f"expected NAME=VALUE, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _providers(args, cfg) -> None:
    from .providers.catalog import PRESETS
    from .providers.manage import add_provider, list_providers, provider_models, remove_provider, test_provider

    if args.pcmd == "presets":
        for pid, p in PRESETS.items():
            print(f"{pid:15} {p['category']:5} {p['name']}" + (f"  [{p['api_key_env']}]" if p.get("api_key_env") else ""))
        print("\nAdd one:  roundtable providers add <id>   (then set its key, and `roundtable providers test <id>`)")
        print("Anything else: `providers add custom --id NAME --base-url URL`, or a plugin (see README).")
    elif args.pcmd == "list":
        for p in list_providers(cfg.path):
            key = "" if not p["needs_key"] else ("key set" if p["key_set"] else f"set {p['api_key_env']}")
            print(f"{p['id']:15} {p['type']:14} {p['source']:12} {key:24} {p['base_url']}")
    elif args.pcmd == "add":
        block = add_provider(cfg.path, args.preset, pid=args.id, base_url=args.base_url, api_key_env=args.key_env,
                             auth_header=args.auth_header, auth_prefix=args.auth_prefix,
                             headers=_pairs(args.header), query=_pairs(args.query), **{"class": args.plugin_class})
        print(f"added provider {block['id']!r} to custom.yaml")
        if block.get("api_key_env") and not os.environ.get(block["api_key_env"]):
            print(f"next: set {block['api_key_env']} (or paste the key in the app's Settings), then "
                  f"`roundtable providers test {block['id']}`")
    elif args.pcmd == "remove":
        remove_provider(cfg.path, args.id)
        print(f"removed {args.id}")
    elif args.pcmd == "test":
        r = test_provider(cfg, args.id)
        if r["ok"]:
            print(f"{args.id}: OK, {r['models']} model(s), e.g. {', '.join(r['sample'][:6])}")
        else:
            sys.exit(f"{args.id}: FAILED - {r['error']}")
    elif args.pcmd == "models":
        for m in provider_models(cfg, args.id):
            print(f"{args.id}/{m}")


def _feedback(args) -> None:
    project = Project(args.dir)
    tasks = {t.id: t for t in project.tasks()}
    task = tasks.get(args.task_id)
    if not task:
        sys.exit(f"error: no task {args.task_id!r}")
    model = next((a["model"] for a in reversed(task.attempts) if a.get("outcome") == "approved"),
                 task.attempts[-1]["model"] if task.attempts else "?")
    project.append("metrics.jsonl", {"at": utcnow(), "task": task.id, "role": task.role, "model": model,
                                     "outcome": "owner_feedback", "rating": "good" if args.good else "bad",
                                     "note": args.note})
    print(f"recorded {'good' if args.good else 'bad'} rating for {task.id} ({model})")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        target = Path(args.path)
        if target.exists() and not args.force:
            sys.exit(f"error: {target} exists (use --force)")
        target.write_text(resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text())
        print(f"wrote {target}. Set your API keys as environment variables, then: roundtable roles")
        return
    if args.cmd == "feedback":
        return _feedback(args)
    if args.cmd == "ui":
        import os

        from .ui.server import serve

        return serve(hub_config=args.hub_config, harness_config=args.config, agent=os.environ.get("HUB_AGENT"),
                     host=args.host, port=args.port, open_browser=not args.no_browser, projects_dir=args.projects_dir)
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
        if args.cmd == "balance":
            from .providers.balance import balances

            found = balances(cfg)
            for name, b in found.items():
                print(f"{name:12} {b['amount']:.2f} {b['currency']}")
            if not found:
                print("None of your providers reports a balance (DeepSeek does, once its key is set).")
            return
        if args.cmd == "improve":
            return _improve(args, cfg)
        if args.cmd == "providers":
            return _providers(args, cfg)
        if args.cmd == "assign":
            from .providers.manage import set_role_models

            set_role_models(cfg.path, args.role, args.models, kind=args.kind, description=args.description)
            print(f"{args.role}: {' -> '.join(args.models)}  (saved in custom.yaml)")
            return
        if args.cmd == "probe":
            return _probe(args, cfg)
        if args.cmd == "image":
            return _image(args, cfg)
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
            print("plan approved; run `roundtable run DIR` to start")
            return
        elif args.cmd in ("retry", "skip"):
            getattr(orch, args.cmd)(args.task_id)
            print(f"{args.task_id}: {'re-opened' if args.cmd == 'retry' else 'skipped'}; run `roundtable run DIR` to continue")
            return
        result = orch.run(max_tasks=getattr(args, "max_tasks", None))
        print()
        _status(orch.project)
        hints = {
            "awaiting_approval": "Review the plan above, then: roundtable approve DIR && roundtable run DIR",
            "blocked": "A task failed. Inspect with `roundtable status DIR`, then `roundtable retry DIR TASK` or `roundtable skip DIR TASK`.",
            "paused_budget": "Budget reached. Raise limits.max_cost_usd in harness.yaml, then `roundtable run DIR`.",
            "paused": "Paused after --max-tasks. Continue with `roundtable run DIR`.",
        }
        if result in hints:
            print("\n" + hints[result].replace("DIR", args.dir))
    except yaml.YAMLError as e:
        sys.exit(f"error: harness.yaml is not valid YAML:\n{e}")
    except (HarnessError, ProviderError, FileNotFoundError, ValueError, KeyError, RuntimeError) as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ninterrupted - progress is saved; resume with `roundtable run DIR`")


if __name__ == "__main__":
    main()
