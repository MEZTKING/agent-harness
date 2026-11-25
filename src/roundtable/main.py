"""`roundtable`: one command for everything in Roundtable Hold.

Hub & journal (where things stand, across projects and sessions):
    roundtable where [PROJECT]            where was I? last session, next steps, todos, plans
    roundtable log done|todo|plan|decision|note "text" [--priority high]
    roundtable todo [PROJECT] [--plans]   open todos (and plans)
    roundtable close ID [--drop]          finish (or drop) a todo / plan
    roundtable session "what I did" --next "step" ...   end-of-session handoff
    roundtable history [PROJECT]          journal entries
    roundtable agents | cards | card show|set|refresh-git
    roundtable send TO "subject" "body" | inbox | reply ID "text" | thread ID | subscribe PROJECT
    roundtable mcp --agent PROJECT        MCP server for Claude Code and other agents

Projects (the harness: the best model for each role, working together):
    roundtable new DIR "goal" [--approve] | run DIR | extend DIR "goal" | approve DIR
    roundtable status DIR | retry DIR TASK | skip DIR TASK | metrics DIR
    roundtable feedback DIR TASK --good|--bad ["note"]
    roundtable roles | ask ROLE "prompt" | image ROLE "prompt"

Models & self-improvement:
    roundtable probe [--role R] [--images]   regression / boost detector
    roundtable improve analyze|propose|list|show|test|apply|reject|rollback|status|cycle

Everything else:
    roundtable ui [--port 8765]           web UI for all of the above
    roundtable init                       write starter hub.yaml and harness.yaml
    roundtable update [--check] [--ref BRANCH] [--force]   built-in updater
    roundtable version

Options: --config FILE (hub.yaml for hub commands, harness.yaml for project commands;
defaults $HUB_CONFIG / $HARNESS_CONFIG), --agent PROJECT (hub identity, default $HUB_AGENT).
Run `roundtable COMMAND --help` for details.
"""

from __future__ import annotations

import sys

HUB_COMMANDS = {"where", "log", "todo", "close", "session", "history", "agents", "cards", "card", "send",
                "inbox", "reply", "thread", "subscribe", "mcp", "ui"}
HARNESS_COMMANDS = {"new", "run", "extend", "approve", "status", "retry", "skip", "metrics", "feedback", "roles",
                    "ask", "image", "probe", "improve"}
VALUE_FLAGS = {"--config", "--agent"}


def _command(argv: list[str]) -> str | None:
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg in VALUE_FLAGS:
            skip = True
            continue
        if arg.startswith("-"):
            continue
        return arg
    return None


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = _command(argv)
    if cmd is None or cmd == "help":
        print(__doc__.strip())
        return
    if cmd == "init":
        return _init(argv)
    if cmd in ("update", "version"):
        return _update(argv, cmd)
    try:
        if cmd in HUB_COMMANDS:
            from .cli import main as hub_main

            return hub_main(argv)
        if cmd in HARNESS_COMMANDS:
            from .harness_cli import main as harness_main

            if "--agent" in argv:  # hub identity flag means nothing to project commands
                i = argv.index("--agent")
                del argv[i:i + 2]
            return harness_main(argv)
        sys.exit(f"roundtable: unknown command {cmd!r}. Run `roundtable help`.")
    finally:
        if cmd not in ("mcp", "ui") and sys.stderr.isatty():
            from .updater import cached_notice

            notice = cached_notice()
            if notice:
                print(f"\n{notice}", file=sys.stderr)


def _update(argv: list[str], cmd: str) -> None:
    import argparse

    from . import __version__
    from .updater import UpdateError, check, install_info, update

    p = argparse.ArgumentParser(prog=f"roundtable {cmd}")
    p.add_argument("cmd")
    p.add_argument("--check", action="store_true", help="only report whether an update is available")
    p.add_argument("--ref", help="branch or tag to follow (default: the one you installed from)")
    p.add_argument("--force", action="store_true", help="reinstall even if up to date / checkout is dirty")
    args = p.parse_args(argv)
    info = install_info()
    if cmd == "version":
        where = info.path or info.url or "package archive"
        print(f"Roundtable Hold {__version__} ({info.kind} install, {info.ref or '-'} @ {info.commit[:7] or '-'}, {where})")
        return
    try:
        if args.check:
            st = check(args.ref, info)
            print(st.message)
            sys.exit(1 if st.available else 0)
        update(args.ref, force=args.force, info=info)
    except UpdateError as e:
        sys.exit(f"update failed: {e}")


def _init(argv: list[str]) -> None:
    from importlib import resources
    from pathlib import Path

    force = "--force" in argv
    for name, template in (("hub.yaml", "hub.example.yaml"), ("harness.yaml", "harness.example.yaml")):
        target = Path(name)
        if target.exists() and not force:
            print(f"kept existing {target} (use --force to overwrite)")
            continue
        target.write_text(resources.files("roundtable").joinpath(f"templates/{template}").read_text())
        print(f"wrote {target}")
    print("Next: edit them, set your API keys, then `roundtable probe` and `roundtable where`.")


if __name__ == "__main__":
    main()
