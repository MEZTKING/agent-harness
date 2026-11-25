"""`agent-hub` command line.

    agent-hub init                       create hub.yaml + data dir
    agent-hub agents                     list agents and permissions
    agent-hub cards                      overview of all readable cards
    agent-hub card show [AGENT]          full card (default: yourself)
    agent-hub card set --summary ... --change "what changed"
    agent-hub card refresh-git [--repo-path .]
    agent-hub send TO[,TO] "subject" "body" [--kind ask]
    agent-hub inbox [--all] [--mark-read]
    agent-hub reply MSG_ID "body"
    agent-hub thread THREAD_ID
    agent-hub subscribe AGENT [--off]
    agent-hub mcp                        run the MCP server (stdio)

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
    template = resources.files("agentharness").joinpath("templates/hub.example.yaml").read_text()
    target.write_text(template, encoding="utf-8")
    print(f"wrote {target}. Edit the agents and rules, then try: agent-hub --agent <id> cards")


def build_parser() -> argparse.ArgumentParser:
    # --config/--agent work both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="path to hub.yaml")
    common.add_argument("--agent", default=argparse.SUPPRESS, help="act as this agent id (default $HUB_AGENT)")

    p = argparse.ArgumentParser(prog="agent-hub", description="Cross-repo agent communication hub")
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

    s = sub.add_parser("mcp", help="run the MCP server for this agent")
    s.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)

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
        elif args.cmd == "mcp":
            from .hub.mcp_server import run

            run(hub, me, transport=args.transport)
    except (HubError, PolicyError, FileNotFoundError, ValueError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
