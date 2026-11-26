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
    roundtable connect [DIR]              join this repo's Claude Code sessions to the hub (MCP + hooks)
    roundtable connect --cloud-script     setup script for Claude Code cloud environments
    roundtable remote [--watch 60]        do commands sent through the hub (from the phone)

Projects (the harness: the best model for each role, working together):
    roundtable new DIR "goal" [--approve] | run DIR | extend DIR "goal" | approve DIR
    roundtable status DIR | retry DIR TASK | skip DIR TASK | metrics DIR
    roundtable feedback DIR TASK --good|--bad ["note"]
    roundtable roles | ask ROLE "prompt" | image ROLE "prompt"
    roundtable balance                     money left with providers that report it (DeepSeek)

Providers (any AI API):
    roundtable providers presets | list | add PRESET | remove ID | test ID | models ID
    roundtable assign ROLE provider/model [fallback ...]   which model does a role

Models & self-improvement:
    roundtable probe [--role R] [--images]   regression / boost detector
    roundtable improve analyze|propose|list|show|test|apply|reject|rollback|status|cycle

Plugins (extra pieces: token saving, cost logs, tools...):
    roundtable plugin list | add SOURCE | remove ID | enable ID | disable ID | settings ID [key=value]
    roundtable PLUGIN-ID COMMAND ...      a plugin's own commands

Everything else:
    roundtable ui [--port 8765]           web UI for all of the above
    roundtable init                       write starter hub.yaml and harness.yaml
    roundtable update [--check] [--ref BRANCH] [--force]   built-in updater
    roundtable version
    roundtable backup now|list|where|restore FILE   back up settings, learned settings and plans
                                          (to Google Drive's folder or --to PATH; never API keys)
    roundtable app                        open the desktop app (window) from a source install

Options: --config FILE (hub.yaml for hub commands, harness.yaml for project commands;
defaults $HUB_CONFIG / $HARNESS_CONFIG), --agent PROJECT (hub identity, default $HUB_AGENT).
Run `roundtable COMMAND --help` for details.
"""

from __future__ import annotations

import sys

HUB_COMMANDS = {"where", "log", "todo", "close", "session", "history", "agents", "cards", "card", "send",
                "inbox", "reply", "thread", "subscribe", "mcp", "ui"}
HARNESS_COMMANDS = {"new", "run", "extend", "approve", "status", "retry", "skip", "metrics", "feedback", "roles",
                    "ask", "image", "probe", "improve", "providers", "assign", "balance"}
VALUE_FLAGS = {"--config", "--agent", "--description"}


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
    if cmd == "remote":
        return _remote(argv)
    if cmd == "backup":
        from .backup import main as backup_main

        rest = list(argv)
        rest.remove(cmd)
        return backup_main(rest)
    if cmd in ("connect", "hook"):
        from .connect import main as connect_main

        rest = list(argv)
        rest.remove(cmd)
        return connect_main(cmd, rest)
    if cmd == "plugin":
        from .plugins.cli import main as plugin_main

        rest = list(argv)
        rest.remove(cmd)
        return plugin_main(rest)
    if cmd == "app":
        from .desktop import main as app_main

        return sys.exit(app_main([a for a in argv if a != "app"]))
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
        if _plugin_command(argv, cmd):
            return
        sys.exit(f"roundtable: unknown command {cmd!r}. Run `roundtable help`.")
    finally:
        if cmd not in ("mcp", "ui") and sys.stderr.isatty():
            from .updater import cached_notice

            notice = cached_notice()
            if notice:
                print(f"\n{notice}", file=sys.stderr)


def _plugin_command(argv: list[str], cmd: str) -> bool:
    """`roundtable <plugin-id> ...`: a command a plugin adds (False when no plugin has that id)."""
    from .plugins.cli import run_plugin_command

    rest = list(argv)
    config = None
    if "--config" in rest:
        i = rest.index("--config")
        config = rest[i + 1] if i + 1 < len(rest) else None
        del rest[i:i + 2]
    rest.remove(cmd)
    return run_plugin_command(cmd, rest, config)


def _remote(argv: list[str]) -> None:
    import argparse
    import time

    from .core.config import load_config as load_hub
    from .harness.config import load_config
    from .hub.service import Hub
    from .remote import process

    p = argparse.ArgumentParser(prog="roundtable remote",
                                description="Do the owner's commands sent through the hub (e.g. from the phone).")
    p.add_argument("cmd")
    p.add_argument("--config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("--watch", type=float, metavar="SECONDS", help="keep checking every SECONDS")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if not cfg.hub:
        sys.exit("roundtable remote: harness.yaml has no hub: section, so there's nowhere to read commands from")
    hub = Hub(load_hub(cfg.hub.get("config"), nearby=True))
    while True:
        n = process(cfg, hub)
        if n:
            print(f"did {n} command(s)", flush=True)
        if not args.watch:
            return
        time.sleep(args.watch)


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
        target.write_text(resources.files("roundtable").joinpath(f"templates/{template}").read_text(encoding="utf-8"))
        print(f"wrote {target}")
    print("Next: edit them, set your API keys, then `roundtable probe` and `roundtable where`.")


if __name__ == "__main__":
    main()
