"""`roundtable plugin ...` and plugins' own commands (`roundtable <plugin-id> ...`).

    roundtable plugin list
    roundtable plugin add SOURCE [--yes] [--link]   a folder, a git link or a pip package
    roundtable plugin remove ID [--purge]           --purge also deletes its data folder
    roundtable plugin enable ID [--yes] | disable ID
    roundtable plugin settings ID [key=value ...]   show, or change, its settings
    roundtable plugin trust ID [--yes] | untrust ID   let it run as the app itself, or put it back in its box
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from .api import PluginError
from .manifest import Manifest

TRUST_NOTE = "A plugin is someone's program: add plugins from people you trust."


def box_note() -> str:
    """What the box holds a plugin to on this computer, then the trust note."""
    from .sandbox import supported

    return f"{supported()['words']}, unless it asks for more above. {TRUST_NOTE}"


def describe(m: Manifest) -> str:
    v = m.view()
    lines = [f"{m.name} {m.version}" + (f" by {m.author}" if m.author else ""), f"  {m.description}"]
    if m.homepage:
        lines.append(f"  {m.homepage}")
    lines.append(f"  Licence: {m.licence or 'not given'}")
    perms = v["permissions"]
    lines.append("  It asks to: " + ("; ".join(p["words"] for p in perms) if perms else "nothing special"))
    return "\n".join(lines)


def asker(assume_yes: bool, ask: Callable[[str], str] = input) -> Callable[[Manifest], bool]:
    def confirm(m: Manifest) -> bool:
        print(describe(m))
        print(f"\n{box_note()}")
        if assume_yes:
            return True
        return ask("Add it? [y/N] ").strip().lower() in ("y", "yes")

    return confirm


def _pairs(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        if "=" not in it:
            raise ValueError(f"write settings as key=value, not {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roundtable plugin", description="Add, remove and set up plugins.")
    p.add_argument("--config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    sub = p.add_subparsers(dest="pcmd", required=True)
    sub.add_parser("list", help="every plugin, on or off")
    s = sub.add_parser("add", help="add a plugin from a folder, a git link or a pip package")
    s.add_argument("source")
    s.add_argument("--yes", action="store_true", help="don't ask (you've read what it asks for)")
    s.add_argument("--link", action="store_true", help="a folder: use it where it is (for writing your own)")
    s = sub.add_parser("remove", help="remove a plugin you added")
    s.add_argument("id")
    s.add_argument("--purge", action="store_true", help="also delete its data folder")
    s = sub.add_parser("enable", help="switch a plugin on")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("disable", help="switch a plugin off").add_argument("id")
    s = sub.add_parser("trust", help="let a plugin you wrote or read run as the app itself, outside its box")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true", help="don't ask (you've read the warning)")
    sub.add_parser("untrust", help="put a plugin back in its box").add_argument("id")
    s = sub.add_parser("settings", help="show or change a plugin's settings")
    s.add_argument("id")
    s.add_argument("values", nargs="*", metavar="key=value")
    return p


def _list(cfg_path) -> None:
    from .manage import list_plugins

    for p in list_plugins(cfg_path):
        mark = {"on": "on ", "off": "off", "broken": "!! ", "needs_ok": "?? "}[p["status"]]
        where = "built in" if p["builtin"] else f"{p['source']} ({'trusted' if p['trusted'] else 'in its box'})"
        print(f"{mark} {p['id']:18} {p['version']:8} {where}")
        print(f"      {p['description']}")
        if p["problem"]:
            print(f"      {p['problem']}")


def main(argv: list[str], ask: Callable[[str], str] = input) -> None:
    from . import manage

    args = _parser().parse_args(argv)
    try:
        if args.pcmd == "list":
            return _list(args.config)
        if args.pcmd == "add":
            m = manage.add_plugin(args.config, args.source, asker(args.yes, ask), link=args.link)
            print(f"\nAdded {m['name']}; it's on. Settings: `roundtable plugin settings {m['id']}`")
        elif args.pcmd == "remove":
            manage.remove_plugin(args.config, args.id, purge=args.purge)
            print(f"Removed {args.id}." + ("" if args.purge else " Its data folder was kept (--purge deletes it)."))
        elif args.pcmd in ("enable", "disable"):
            manage.set_enabled(args.config, args.id, args.pcmd == "enable",
                               confirm=asker(getattr(args, "yes", False), ask))
            print(f"{args.id} is {'on' if args.pcmd == 'enable' else 'off'}.")
        elif args.pcmd in ("trust", "untrust"):
            trusting = args.pcmd == "trust"
            sure = not trusting or args.yes
            if trusting and not sure:
                print(manage.TRUST_WARNING)
                sure = ask("Trust it? [y/N] ").strip().lower() in ("y", "yes")
                if not sure:
                    sys.exit(f"Not changed: {args.id} stays in its box.")
            manage.set_trusted(args.config, args.id, trusting, sure=sure)
            print(f"{args.id} is {'trusted: it runs as the app itself' if trusting else 'back in its box'}.")
        elif args.pcmd == "settings":
            values = manage.set_settings(args.config, args.id, _pairs(args.values)) if args.values \
                else manage.get_settings(args.config, args.id)
            for k, v in values.items():
                print(f"{k} = {v}")
            if not values:
                print(f"{args.id} has no settings.")
    except manage.NeedsOk as e:
        sys.exit(f"Not changed: {e.manifest.name} wasn't given your OK.")
    except (PluginError, ValueError, FileNotFoundError) as e:
        sys.exit(f"error: {e}")


def run_plugin_command(pid: str, argv: list[str], config: str | None = None) -> bool:
    """`roundtable <plugin-id> [command] [args]`: False when no plugin that's on has that id."""
    from ..harness.config import load_config

    try:
        cfg = load_config(config)
    except (FileNotFoundError, ValueError):
        return False
    host = cfg.plugin_host()
    p = host.get(pid)
    if p is None or p.status != "on":
        return False
    commands = host.commands(pid)
    name = argv[0] if argv else ""
    if name not in commands:
        names = ", ".join(sorted(commands)) or "none"
        sys.exit(f"{p.manifest.name}: commands are {names}. Run `roundtable {pid} COMMAND`.")
    result = commands[name](host.context(p), argv[1:])
    if isinstance(result, int) and result:
        sys.exit(result)
    return True
