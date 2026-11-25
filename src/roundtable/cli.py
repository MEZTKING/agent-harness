"""Hub & journal commands (`roundtable where/log/send/...`; also available as `agent-hub`).

    roundtable init                       create hub.yaml + data dir
    roundtable agents                     list agents and permissions
    roundtable cards                      overview of all readable cards
    roundtable card show [AGENT]          full card (default: yourself)
    roundtable card set --summary ... --change "what changed"
    roundtable card refresh-git [--repo-path .]
    roundtable send TO[,TO] "subject" "body" [--kind ask]
    roundtable inbox [--all] [--mark-read]
    roundtable reply MSG_ID "body"
    roundtable thread THREAD_ID
    roundtable subscribe AGENT [--off]
    roundtable mcp                        run the MCP server (stdio)
    roundtable ui [--port 8765]           web UI (journal, projects, messages, harness runs, models, improve)

  Journal ("where was I"):
    roundtable where [AGENT]              briefing: last session, next steps, open todos, plans
    roundtable log done|todo|plan|decision|note "text" [--priority high]
    roundtable todo [AGENT] [--plans]     open todos (and plans)
    roundtable close ID [--drop] [--note]  finish (or drop) a todo / plan
    roundtable session "what I did" --next "step" --next "step"   end-of-session handoff
    roundtable history [AGENT] [--kind K] [--limit N]

Identity: --agent or $HUB_AGENT.  Config: --config or $HUB_CONFIG or ./hub.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources
from pathlib import Path

from .core.config import load_config
from .core.policy import PolicyError
from .hub.service import Hub, HubError


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _agent(args) -> str:
    agent = args.agent or os.environ.get("HUB_AGENT")
    if not agent:
        sys.exit("error: no agent identity; pass --agent or set HUB_AGENT")
    return agent


def cmd_init(args) -> None:
    target = Path(args.path)
    if target.exists() and not args.force:
        sys.exit(f"error: {target} exists (use --force to overwrite)")
    template = resources.files("roundtable").joinpath("templates/hub.example.yaml").read_text()
    target.write_text(template, encoding="utf-8")
    print(f"wrote {target}. Edit the agents and rules, then try: roundtable --agent <id> cards")


def build_parser() -> argparse.ArgumentParser:
    # --config/--agent work both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="path to hub.yaml")
    common.add_argument("--agent", default=argparse.SUPPRESS, help="act as this agent id (default $HUB_AGENT)")

    p = argparse.ArgumentParser(prog="roundtable", description="Roundtable Hold: hub, journal and messaging")
    p.add_argument("--config", help="path to hub.yaml")
    p.add_argument("--agent", help="act as this agent id (default $HUB_AGENT)")
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser

    def add_parser(name, **kw):
        return _add(name, parents=[common], **kw)

    sub.add_parser = add_parser  # type: ignore[method-assign]

    s = sub.add_parser("init", help="create a starter hub.yaml")
    s.add_argument("path", nargs="?", default="hub.yaml")
    s.add_argument("--force", action="store_true")

    sub.add_parser("agents", help="list agents and what you may do with each")
    sub.add_parser("cards", help="overview of readable project cards")

    card = sub.add_parser("card", help="show or edit project cards")
    csub = card.add_subparsers(dest="card_cmd", required=True)
    _cadd = csub.add_parser
    csub.add_parser = lambda name, **kw: _cadd(name, parents=[common], **kw)  # type: ignore[method-assign]
    cs = csub.add_parser("show")
    cs.add_argument("target", nargs="?")
    cset = csub.add_parser("set", help="edit your own card")
    for f in ("summary", "goal", "status", "interfaces", "notes", "repo"):
        cset.add_argument(f"--{f}")
    cset.add_argument("--depends-on", help="comma-separated agent ids")
    cset.add_argument("--change", help="change note; notifies subscribers/dependents")
    cset.add_argument("--no-notify", action="store_true")
    cr = csub.add_parser("refresh-git", help="store recent commits from a local repo on your card")
    cr.add_argument("--repo-path", default=".")
    cr.add_argument("--count", type=int, default=10)

    s = sub.add_parser("send", help="message one or more agents")
    s.add_argument("to", help="recipient id(s), comma-separated")
    s.add_argument("subject")
    s.add_argument("body")
    s.add_argument("--kind", default="ask", choices=["ask", "notify", "request"])

    s = sub.add_parser("inbox", help="read your inbox")
    s.add_argument("--all", action="store_true", help="include already-read messages")
    s.add_argument("--mark-read", action="store_true")
    s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("reply")
    s.add_argument("message_id")
    s.add_argument("body")

    s = sub.add_parser("thread")
    s.add_argument("thread_id")

    s = sub.add_parser("subscribe")
    s.add_argument("target")
    s.add_argument("--off", action="store_true")

    s = sub.add_parser("where", help="where was I? briefing for one or all projects")
    s.add_argument("target", nargs="?")
    s.add_argument("--full", action="store_true", help="don't abbreviate (all-projects view)")
    s = sub.add_parser("log", help="add a journal entry")
    s.add_argument("kind", choices=["done", "todo", "plan", "decision", "note"])
    s.add_argument("text")
    s.add_argument("--priority", default="normal", choices=["high", "normal", "low"])
    s.add_argument("--details", default="")
    s.add_argument("--tag", action="append", default=[])
    s = sub.add_parser("todo", help="list open todos")
    s.add_argument("target", nargs="?")
    s.add_argument("--plans", action="store_true", help="include future plans")
    s = sub.add_parser("close", help="mark a todo/plan done")
    s.add_argument("entry_id")
    s.add_argument("--drop", action="store_true", help="dropped instead of done")
    s.add_argument("--note", default="")
    s = sub.add_parser("session", help="end-of-session summary and next steps")
    s.add_argument("summary")
    s.add_argument("--next", action="append", default=[], help="a next step (repeatable)")
    s = sub.add_parser("history", help="journal entries, oldest first")
    s.add_argument("target", nargs="?")
    s.add_argument("--kind", action="append", default=[])
    s.add_argument("--limit", type=int, default=30)

    s = sub.add_parser("ui", help="open the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--harness-config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    s.add_argument("--projects-dir", default=".", help="where new harness projects are created")
    s.add_argument("--no-browser", action="store_true")

    s = sub.add_parser("mcp", help="run the MCP server for this agent")
    s.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)

    if args.cmd == "ui":
        from .ui.server import serve

        return serve(hub_config=args.config, harness_config=args.harness_config,
                     agent=args.agent or os.environ.get("HUB_AGENT"), host=args.host, port=args.port,
                     open_browser=not args.no_browser, projects_dir=args.projects_dir)
    try:
        hub = Hub(load_config(args.config))
        me = _agent(args)
        if args.cmd == "agents":
            _print(hub.list_agents(me))
        elif args.cmd == "cards":
            _print(hub.list_cards(me))
        elif args.cmd == "card":
            if args.card_cmd == "show":
                _print(hub.get_card(me, args.target or me))
            elif args.card_cmd == "set":
                fields = {
                    k: getattr(args, k)
                    for k in ("summary", "goal", "status", "interfaces", "notes", "repo")
                    if getattr(args, k) is not None
                }
                if args.depends_on is not None:
                    fields["depends_on"] = args.depends_on
                res = hub.update_card(me, change_note=args.change, notify=not args.no_notify, **fields)
                _print({"updated": True, "notified": res["notified"]})
            elif args.card_cmd == "refresh-git":
                from .hub.gitinfo import recent_commits

                card = hub.set_recent_commits(me, recent_commits(args.repo_path, args.count))
                _print({"recent_commits": card["recent_commits"]})
        elif args.cmd == "send":
            sent = hub.send(me, args.to.split(","), args.subject, args.body, kind=args.kind)
            _print([{"id": m["id"], "to": m["recipient"]} for m in sent])
        elif args.cmd == "inbox":
            _print(hub.inbox(me, unread_only=not args.all, mark_read=args.mark_read, limit=args.limit))
        elif args.cmd == "reply":
            _print(hub.reply(me, args.message_id, args.body))
        elif args.cmd == "thread":
            _print(hub.thread(me, args.thread_id))
        elif args.cmd == "subscribe":
            _print({"subscriptions": hub.subscribe(me, args.target, on=not args.off)})
        elif args.cmd == "where":
            from .hub.journal import Journal

            briefs = hub.journal.where(me, args.target)
            if not briefs:
                print("No journal entries yet. Start with: roundtable log todo \"...\" or roundtable session \"...\"")
            for b in briefs:
                print(Journal.format_brief(b, compact=not (args.target or args.full)) + "\n")
        elif args.cmd == "log":
            e = hub.journal.add(me, args.kind, args.text, priority=args.priority, details=args.details,
                                source="cli", tags=args.tag)
            print(f"logged {e['kind']} [{e['id']}] for {me}")
        elif args.cmd == "todo":
            kinds = ["todo", "plan"] if args.plans else ["todo"]
            rows = hub.journal.entries(me, args.target, kinds=kinds, status="open")
            for e in sorted(rows, key=lambda e: ({"high": 0, "normal": 1, "low": 2}[e["priority"]], e["created_at"])):
                print(f"[{e['id']}] {e['kind']:4} {'!' if e['priority'] == 'high' else ' '} {e['text']}")
            if not rows:
                print("nothing open")
        elif args.cmd == "close":
            e = hub.journal.close(me, args.entry_id, dropped=args.drop, note=args.note)
            print(f"{e['status']}: [{e['id']}] {e['text']}")
        elif args.cmd == "session":
            e = hub.journal.session_end(me, args.summary, args.next, source="cli")
            print(f"session logged [{e['id']}] with {len(e['next'])} next step(s)")
        elif args.cmd == "history":
            for e in hub.journal.entries(me, args.target, kinds=args.kind or None, limit=args.limit):
                state = f" ({e['status']})" if e["status"] else ""
                print(f"{e['created_at'][:16]}  {e['kind']:8} [{e['id']}] {e['text']}{state}")
                for n in e["next"]:
                    print(f"{'':35}next: {n}")
        elif args.cmd == "mcp":
            from .hub.mcp_server import run

            run(hub, me, transport=args.transport)
    except (HubError, PolicyError, FileNotFoundError, ValueError, RuntimeError) as e:  # incl. JournalError, GitError
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
