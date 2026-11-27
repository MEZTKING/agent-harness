"""Ask me first: a command a builder wants to run waits for the owner's tap.

The setting ``ask_first`` has three values:

* ``off``   – commands run straight away (as before);
* ``risky`` – only commands that look risky wait: deleting or writing outside the project, sending code
  to GitHub, throwing work away (``git reset --hard``), installing from the internet, administrator rights,
  a download run straight away (``curl … | sh``), reading saved passwords or keys, changing the computer;
* ``all``   – every command waits.

Where it comes from, the first that is set: the project's own setting (``ask_first`` in
``.harness/project.yaml`` or ``roundtable.yaml``), then this machine's (``$ROUNDTABLE_GATE``, which "This
phone" sets from the app's "Ask me first"), then ``gate: {ask_first: …}`` in harness.yaml, then
:data:`DEFAULT_MODE`. ``gate: {timeout_minutes: 30}`` is how long a command waits for an answer.

A waiting command is a file, ``.harness/gate/<id>.ask.json``; ``asks.open_asks`` shows it as a card of
kind ``command`` (desktop, phone, the hub's ``.asks.json``) and ``asks.answer_ask`` writes the answer next
to it (``<id>.answer.json``), which :meth:`Gate.check` is polling for. Files, so an answer from another
process (the hub's remote commands, the phone server) reaches the run. "Always allow this in this project"
keeps a pattern in ``.harness/gate/allowed.json``.

This is not a sandbox: it reads the command as text, so it can be fooled (a script it doesn't read, a
command built at run time). It shows the owner what will run; ``safeenv.clean_env`` keeps the keys out.
The wording follows DSH Mobile's "Ask me first" (Allow once / Don't allow, the whole command shown, over
256 KB not run); no code is taken from it.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

MODES = ("off", "risky", "all")
DEFAULT_MODE = "risky"
DEFAULT_TIMEOUT_MIN = 30.0
MAX_COMMAND_BYTES = 256 * 1024  # too long to show in full means not run (and not asked)
ENV = "ROUNDTABLE_GATE"  # this machine's choice for this process and its children (the phone sets it)
GATE_DIR = ".harness/gate"
ALLOWED_FILE = "allowed.json"
FOLD_LINES = 12  # a longer command is folded on the card ("Show all")
FOLD_CHARS = 1200

ALLOW, ALWAYS, DENY = "allow", "always", "deny"
EVERY = "you chose to see every command first"


# -- the setting ------------------------------------------------------------------------------------------
def norm_mode(value: Any) -> str | None:
    """off / risky / all from what a file or the phone says; None when it says nothing usable."""
    if value is True:
        return "all"
    if value is False:
        return "off"
    v = str(value if value is not None else "").strip().lower()
    return {"1": "all", "yes": "all", "true": "all", "on": "all", "ask": "all", "always": "all", "every": "all",
            "0": "off", "no": "off", "false": "off", "run": "off", "never": "off"}.get(v, v if v in MODES else None)


def _project_value(root: Path) -> Any:
    from . import projectsettings as ps

    if "ask_first" in ps.BY_KEY:  # the project-settings line is in: it validates the value
        st = ps.load(root)
        return st.values.get("ask_first") if st.sources.get("ask_first") != "default" else None
    value = None
    for name in (ps.REPO_FILE, ps.PROJECT_FILE):  # .harness/project.yaml wins over roundtable.yaml
        raw, _ = ps._read_raw(root / name)
        if "ask_first" in raw:
            value = raw["ask_first"]
    return value


def _section(cfg: Any) -> dict[str, Any]:
    from .config import section

    return section(cfg, "gate") if cfg is not None else {}


def mode_for(root: str | Path, cfg: Any = None) -> str:
    """The setting that applies to this project on this machine now."""
    for value in (_safe(_project_value, Path(root)), os.environ.get(ENV), _section(cfg).get("ask_first")):
        mode = norm_mode(value)
        if mode:
            return mode
    return DEFAULT_MODE


def _safe(fn: Callable[..., Any], *a: Any) -> Any:
    try:
        return fn(*a)
    except Exception:  # a broken project file must never let commands through unseen: fall back
        return None


def timeout_for(cfg: Any = None) -> float:
    """Seconds a command waits for an answer before it's refused."""
    try:
        minutes = float(_section(cfg).get("timeout_minutes") or DEFAULT_TIMEOUT_MIN)
    except (TypeError, ValueError):
        minutes = DEFAULT_TIMEOUT_MIN
    return max(minutes, 0.01) * 60


# -- reading a command ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    """Why one part of a command needs asking, and what "Always allow" would remember for it."""

    reason: str  # plain words, after "Asked because "
    pattern: str  # a prefix ("git push") or the whole command (exact)
    exact: bool = False
    segment: str = ""  # the part of the command it's about, normalised


def normalise(command: str) -> str:
    return " ".join(command.split())


_SPLIT = re.compile(r"\|\||&&|;|\r?\n|(?<![>&<|])\|(?![|&])|(?<![>&<0-9])&(?![>&0-9])")


def segments(command: str) -> list[str]:
    """The simple commands in a line: split at ; && || | & and new lines (quotes aren't followed)."""
    return [s.strip() for s in _SPLIT.split(command) if s and s.strip()]


def tokens(seg: str) -> list[str]:
    try:
        if "\\" in seg:  # Windows paths: keep the backslashes, drop the quotes
            return [t.strip("\"'") for t in shlex.split(seg, posix=False)]
        return shlex.split(seg, posix=True)
    except ValueError:
        return [t.strip("\"'") for t in seg.split()]


_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS = {"env", "nohup", "time", "command", "exec", "nice", "ionice", "stdbuf", "timeout", "builtin", "call", "start"}


def program(toks: list[str]) -> tuple[str, list[str]]:
    """The program a simple command starts (lower case, no .exe) and its arguments, past `FOO=1`, env, nohup."""
    i = 0
    while i < len(toks) and (_ASSIGN.match(toks[i]) or toks[i].lower() in _WRAPPERS):
        if toks[i].lower() == "timeout" and i + 1 < len(toks) and re.fullmatch(r"[\d.]+[smhd]?", toks[i + 1]):
            i += 1
        i += 1
    if i >= len(toks):
        return "", []
    name = re.split(r"[\\/]", toks[i])[-1].lower()
    for ext in (".exe", ".cmd", ".bat", ".com"):
        name = name.removesuffix(ext)
    return name, toks[i + 1:]


_VALUEISH = re.compile(r"[/\\.=:'\"$%~*@()\[\]{}<>,;\s]|^\d")
_CODE_FLAGS = {"-c", "-e", "--eval", "-command", "/c", "/k", "-encodedcommand", "-r"}


def prefix_of(seg: str) -> str:
    """What "Always allow" remembers for an ordinary command: its first words, up to a path or a value
    (``python -m pytest tests -q`` → ``python -m pytest``; ``npm run build`` → ``npm run build``)."""
    toks = tokens(seg)
    name, args = program(toks)
    out = [name] if name else (toks[:1] or [seg])
    for t in args:
        if len(out) >= 3 or _VALUEISH.search(t) or t.lower() in _CODE_FLAGS or (t.startswith("-") and len(out) > 1 and out[-1].startswith("-")):
            break
        out.append(t)
    return " ".join(out)


def _subcommand(args: list[str], skip_with_value: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """The first word that isn't an option (``git -C dir push`` → push), and what follows it."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in skip_with_value:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a.lower(), args[i + 1:]
    return "", []


_DRIVE = re.compile(r"^[A-Za-z]:[\\/]|^[A-Za-z]:$")
_HARMLESS = {"/dev/null", "nul", "/dev/stdout", "/dev/stderr", "con", "$null", "/dev/tty"}


def where(path: str, root: Path | None) -> str:
    """"inside", "outside", "project" (the project folder itself) or "unknown" (a setting decides it)."""
    p = path.strip("\"'")
    if not p or p.lower() in _HARMLESS:
        return "inside"
    if p.startswith("~") or re.match(r"^(\$\{?HOME\b|%USERPROFILE%|%HOMEPATH%|\$env:)", p, re.I):
        return "outside"
    if p.startswith("$") or p.startswith("%"):
        return "unknown"
    if root is None:
        root = Path.cwd()
    if _DRIVE.match(p) or p.startswith("\\\\"):  # a Windows path: compare as text
        r = PureWindowsPath(str(root)).as_posix().lower().rstrip("/")
        q = PureWindowsPath(p).as_posix().lower().rstrip("/")
        if not _DRIVE.match(str(root)):
            return "outside"
        return "project" if q == r else "inside" if q.startswith(r + "/") and ".." not in q.split("/") else "outside"
    base = Path(p) if p.startswith("/") else root / p.replace("\\", "/")
    try:
        full = Path(os.path.normpath(str(base)))
        r = Path(os.path.normpath(str(root)))
    except (OSError, ValueError):
        return "unknown"
    if full == r:
        return "project"
    return "inside" if r in full.parents else "outside"


_WIN_SWITCH = re.compile(r"^/[A-Za-z?]{1,2}(:\S*)?$")
_WIN_PROGS = {"del", "erase", "rd", "rmdir", "copy", "xcopy", "move", "robocopy", "mkdir", "md", "type", "attrib"}


def _paths(name: str, args: list[str]) -> list[str]:
    """The arguments of a command that are paths (not options)."""
    out = []
    for a in args:
        if a.startswith("-") or (name in _WIN_PROGS and _WIN_SWITCH.match(a)):
            continue
        out.append(a)
    return out


def _ps_paths(args: list[str]) -> list[str]:
    """PowerShell's -Path / -LiteralPath / -Destination values, and plain positional ones."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.lower() in ("-path", "-literalpath", "-destination", "-filepath") and i + 1 < len(args):
            out.append(args[i + 1])
            i += 2
            continue
        if a.startswith("-"):
            i += 2 if a.lower() in ("-value", "-encoding", "-itemtype", "-include", "-exclude", "-filter") else 1
            continue
        out.append(a)
        i += 1
    return out


DELETERS = {"rm", "rmdir", "unlink", "shred", "del", "erase", "rd", "remove-item", "ri", "trash"}
COPIERS = {"cp", "mv", "copy", "move", "xcopy", "robocopy", "ln", "install", "copy-item", "move-item", "cpi", "mi"}
WRITERS = {"tee", "touch", "mkdir", "md", "chmod", "chown", "chgrp", "truncate", "set-content", "add-content",
           "out-file", "new-item", "ni", "sc", "ac"}
ELEVATE = {"sudo", "su", "doas", "runas", "pkexec", "gsudo"}
SYSTEM = {"shutdown": "it shuts down or restarts the computer", "reboot": "it restarts the computer",
          "halt": "it shuts down the computer", "poweroff": "it shuts down the computer",
          "diskpart": "it changes the computer's disks", "fdisk": "it changes the computer's disks",
          "format": "it can wipe a disk", "setx": "it changes the computer's settings for every program",
          "reg": "it changes the Windows registry", "crontab": "it sets up something that runs on a timer",
          "schtasks": "it sets up something that runs on a timer", "systemctl": "it starts or stops the computer's services",
          "launchctl": "it starts or stops the computer's services", "sc.exe": "it changes the computer's services",
          "set-executionpolicy": "it changes what PowerShell lets run", "killall": "it stops other programs",
          "taskkill": "it stops other programs", "pkill": "it stops other programs",
          "stop-computer": "it shuts down the computer", "restart-computer": "it restarts the computer"}
INSTALLERS = {
    # program: (its install words, the word after which come package names)
    "pip": ("install",), "pip3": ("install",), "pipx": ("install", "run"), "uv": ("add", "install"),
    "npm": ("install", "i", "add", "isntall"), "pnpm": ("add", "install", "i"), "yarn": ("add", "global"),
    "bun": ("add", "install", "i"), "apt": ("install",), "apt-get": ("install",), "dnf": ("install",),
    "yum": ("install",), "apk": ("add",), "zypper": ("install", "in"), "pacman": ("-s", "-sy", "-syu"),
    "brew": ("install",), "choco": ("install",), "winget": ("install",), "scoop": ("install",),
    "cargo": ("install",), "go": ("install", "get"), "gem": ("install",), "composer": ("require",),
    "dotnet": ("tool", "add"), "conda": ("install",), "mamba": ("install",), "flatpak": ("install",),
    "snap": ("install",), "install-module": ("",), "install-package": ("",), "install-script": ("",),
}
_SECRETS = re.compile(
    r"\.ssh[/\\]|\bid_(rsa|ed25519|ecdsa|dsa)\b|\.aws[/\\]credentials|\.netrc\b|\.git-credentials|"
    r"\bgit\s+credential(-\w+)?\s+(fill|get)|\bcmdkey\b|\bsecurity\s+(find|dump)-|\bsecret-tool\b|"
    r"\bkeyring\s+get\b|Get-StoredCredential|\bvaultcmd\b|CredentialManager|\bgh\s+auth\s+token\b|"
    r"roundtable-hold[/\\]|\.roundtable[/\\]|\bkeys\.json\b|\.gnupg[/\\]|\bgpg\s+--export-secret", re.I)
_DOWNLOAD_RUN = re.compile(
    r"\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|fetch)\b[^|;&\n]*\|\s*(sudo\s+)?"
    r"(ba|z|da|k|fi)?sh\b|\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|;&\n]*\|\s*(sudo\s+)?"
    r"(python3?|perl|ruby|node|iex|invoke-expression|pwsh|powershell|cmd)\b|"
    r"\b(ba|z)?sh\s+<\(\s*(curl|wget)|\b(iex|invoke-expression)\b|downloadstring\(|"
    r"\bsource\s+<\(\s*(curl|wget)", re.I)
_SEND = re.compile(r"(^|\s)(-T|--upload-file|-d|--data(-\w+)?|-F|--form|-X\s*(POST|PUT|PATCH|DELETE))(\s|=|$)", re.I)
_REDIRECT = re.compile(r"(?:^|[^0-9&<>])\d?>>?\|?\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>]+)")
_SHELL_INNER = re.compile(r"^\s*(?:\S*[\\/])?(?:ba|z|da|k)?sh(?:\.exe)?\s+(?:-\w*c\w*)\s+(.+)$|"
                          r"^\s*(?:\S*[\\/])?(?:cmd(?:\.exe)?\s+/[ck]|(?:powershell|pwsh)(?:\.exe)?\s+(?:-\w+\s+)*-c(?:ommand)?)\s+(.+)$",
                          re.I | re.S)
_SCRIPT_EXT = (".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd")


def classify(command: str, root: str | Path | None = None, _depth: int = 0) -> list[Finding]:
    """What makes a command risky, part by part (empty: nothing risky found)."""
    root = Path(root) if root is not None else None
    whole = normalise(command)
    out: list[Finding] = []

    def exact(reason: str, seg: str = "") -> None:
        out.append(Finding(reason, whole, True, normalise(seg) or whole))

    def prefix(reason: str, seg: str, pre: str) -> None:
        out.append(Finding(reason, pre, False, normalise(seg)))

    if _DOWNLOAD_RUN.search(command):
        exact("it downloads a program from the internet and runs it straight away")
    if _SECRETS.search(command):
        exact("it reads saved passwords, keys or logins")
    for seg in segments(command):
        inner = _SHELL_INNER.match(seg)
        if inner and _depth < 3:  # bash -c "…", cmd /c …, powershell -Command "…": read what's inside
            text = (inner.group(1) or inner.group(2) or "").strip().strip("\"'")
            for f in classify(text, root, _depth + 1):
                out.append(Finding(f.reason, whole, True, normalise(seg)) if f.exact else f)
            continue
        toks = tokens(seg)
        name, args = program(toks)
        if not name:
            continue
        low = [a.lower() for a in args]
        for m in _REDIRECT.finditer(seg):
            target = m.group(1).strip("\"'")
            if not target.startswith("&") and where(target, root) in ("outside", "unknown"):
                exact(f"it writes to {target}, outside the project", seg)
        if name in ELEVATE or (name in ("start-process", "start") and "runas" in low):
            exact("it runs with administrator rights", seg)
            rest = " ".join(args[1:] if name in ("su",) else args)
            if rest and _depth < 3 and name not in ("start-process", "start"):
                out.extend(f for f in classify(rest, root, _depth + 1) if not f.exact)
        if name in SYSTEM:
            exact(SYSTEM[name], seg)
        if name == "dd" and any(a.startswith("of=") and where(a[3:], root) != "inside" for a in args):
            exact("it writes straight onto a disk or a file outside the project", seg)
        if name.startswith("mkfs"):
            exact("it can wipe a disk", seg)
        if name in ("kill",) and "-1" in args:
            exact("it stops every program you're running", seg)
        if name in DELETERS or (name == "find" and "-delete" in low):
            paths = (_ps_paths(args) if name in ("remove-item", "ri") else
                     args[:1] if name == "find" else _paths(name, args))
            if name == "find" and not paths:
                paths = ["."]
            for p in paths:
                w = where(p, root)
                if w == "project" and name != "find":  # find picks files inside it: that's fine
                    exact("it deletes the whole project", seg)
                elif w in ("outside", "unknown"):
                    exact(f"it deletes {p}, outside the project" if w == "outside"
                          else f"it deletes {p}, and that depends on a setting it can't see", seg)
        if name in COPIERS:
            paths = _ps_paths(args) if "-" in name or name in ("cpi", "mi") else _paths(name, args)
            if name == "robocopy":
                paths = paths[:2]
            moves = name in ("mv", "move", "move-item", "mi")
            for i, p in enumerate(paths if moves else paths[-1:]):
                if where(p, root) in ("outside", "unknown"):
                    taking = moves and i < len(paths) - 1
                    exact(f"it {'takes' if taking else 'writes'} {p}, outside the project", seg)
        if name in WRITERS:
            paths = _ps_paths(args) if "-" in name or name in ("ni", "sc", "ac") else _paths(name, args)
            if name in ("chmod", "chown", "chgrp") and paths:
                paths = paths[1:]
            for p in paths:
                if where(p, root) in ("outside", "unknown"):
                    exact(f"it changes {p}, outside the project", seg)
        if name == "git":
            _git(args, seg, exact, prefix)
        if name == "gh":
            sub, rest = _subcommand(args, ("-R", "--repo"))
            act, _ = _subcommand(rest)
            if sub and act not in ("view", "list", "status", "diff", "checks", "") and sub not in ("help", "version", "status"):
                prefix("it changes things on GitHub", seg, f"gh {sub} {act}".strip())
        if name in ("python", "python3", "py") and low[:2] == ["-m", "pip"]:
            name, args, low = "pip", args[2:], low[2:]
        if name in INSTALLERS:
            _install(name, args, low, seg, prefix)
        if name in ("scp", "sftp", "ftp", "nc", "ncat", "netcat", "telnet"):
            exact("it sends files or data to another computer", seg)
        if name == "rsync" and any(re.match(r"^[\w.@-]+:", a) for a in args):
            exact("it sends files or data to another computer", seg)
        if name == "ssh":
            exact("it runs commands on another computer", seg)
        if name in ("curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm") and _SEND.search(" " + " ".join(args)):
            exact("it sends data from this computer to a website", seg)
        if name in ("curl", "wget") and any(where(a[a.find("=") + 1:] if "=" in a else a, root) == "outside"
                                            for a in _after(args, ("-o", "--output", "-O", "-P", "--output-document"))):
            exact("it downloads a file to a place outside the project", seg)
        if _depth < 2:
            out.extend(_script(name, args, seg, root, whole))
    seen, unique = set(), []
    for f in out:
        key = (f.reason, f.pattern, f.exact)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _after(args: list[str], opts: tuple[str, ...]) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a in opts] + [a for a in args if "=" in a and a.split("=")[0] in opts]


def _git(args: list[str], seg: str, exact: Callable, prefix: Callable) -> None:
    sub, rest = _subcommand(args, ("-C", "-c", "--git-dir", "--work-tree"))
    low = [a.lower() for a in rest]
    if sub == "push":
        if any(a in ("-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d") or a.startswith("--force")
               or a.startswith("+") or (a.startswith(":") and len(a) > 1) for a in rest):
            exact("it force-pushes or deletes on the server, which can overwrite work there", seg)
        else:
            prefix("it sends your code to GitHub or another server", seg, "git push")
    elif sub == "reset" and "--hard" in low:
        prefix("it throws away changes that aren't saved in git", seg, "git reset --hard")
    elif sub == "clean" and any(a.startswith("-") and "f" in a.lstrip("-") for a in low if not a.startswith("--")) | ("--force" in low):
        prefix("it deletes the files git doesn't keep", seg, "git clean")
    elif sub in ("checkout", "restore") and ("." in rest or "--" in rest and "." in rest[rest.index("--"):]):
        prefix("it throws away changes that aren't saved in git", seg, f"git {sub} .")
    elif sub == "branch" and any(a in ("-D", "--delete") for a in rest) or sub == "branch" and "-d" in rest and "--force" in rest:
        prefix("it deletes a branch", seg, "git branch -D")
    elif sub in ("filter-branch", "filter-repo"):
        exact("it rewrites the project's whole history", seg)
    elif sub == "reflog" and "expire" in low or sub == "gc" and "--prune=now" in low:
        exact("it removes git's safety copies of old work", seg)
    elif sub == "config" and any(a in ("--global", "--system") for a in low):
        exact("it changes git's settings for every project on this computer", seg)
    elif sub == "stash" and any(a in ("drop", "clear") for a in low):
        prefix("it throws away saved changes (a stash)", seg, f"git stash {next(a for a in low if a in ('drop', 'clear'))}")


def _install(name: str, args: list[str], low: list[str], seg: str, prefix: Callable) -> None:
    words = INSTALLERS[name]
    if words == ("",):  # Install-Module and the like: the word is the program
        prefix("it downloads and installs something from the internet", seg, name)
        return
    sub, rest = _subcommand(args) if not name == "pacman" else (next((a for a in low if a.startswith("-s")), ""), args)
    if name == "pacman":
        if sub in words:
            prefix("it downloads and installs something from the internet", seg, f"pacman {sub}")
        return
    if sub not in words:
        return
    if name == "yarn" and sub == "global":
        sub2, rest = _subcommand(rest)
        if sub2 != "add":
            return
        sub = "global add"
    if name == "dotnet" and sub == "tool":
        if _subcommand(rest)[0] != "install":
            return
        sub = "tool install"
    pkgs = [a for a in _paths(name, rest) if not a.startswith((".", "/", "\\")) and not re.match(r"^[A-Za-z]:", a)]
    opts = [a.lower() for a in rest if a.startswith("-")]
    if name in ("pip", "pip3", "uv"):
        if any(o in ("-r", "--requirement", "-e", "--editable", "-c") for o in opts):
            # from the project's own files: pip install -r requirements.txt / -e .
            named = [a for a, prev in zip(rest, [""] + rest) if not a.startswith("-")
                     and prev.lower() not in ("-r", "--requirement", "-e", "--editable", "-c")]
            pkgs = [a for a in named if not a.startswith((".", "/")) and not a.endswith((".txt", ".toml"))]
    globally = any(o in ("-g", "--global", "--user", "--system") for o in opts) or sub == "global add"
    from_own_files = not pkgs and name in ("npm", "pnpm", "bun", "yarn", "pip", "pip3", "uv", "composer")
    if from_own_files and not globally:
        return  # npm install / pip install -r requirements.txt: what the project already lists
    what = ", ".join(pkgs[:3]) + (" and more" if len(pkgs) > 3 else "") if pkgs else "something"
    prefix(f"it downloads and installs {what} from the internet" + (" for the whole computer" if globally else ""),
           seg, f"{name} {sub}")


def _script(name: str, args: list[str], seg: str, root: Path | None, whole: str) -> list[Finding]:
    """A project script it runs (bash build.sh, ./setup.sh, .\\make.ps1): what's risky inside it."""
    if name in ("bash", "sh", "zsh", "dash", "source", ".", "pwsh", "powershell", "cmd"):
        cand = [a for a in args if not a.startswith("-") and not _WIN_SWITCH.match(a)][:1]
    else:
        toks = tokens(seg)
        _, rest = program(toks)
        first = toks[len(toks) - len(rest) - 1] if toks else ""
        cand = [first] if first.lower().endswith(_SCRIPT_EXT) else []
    out = []
    for c in cand:
        if not c.lower().endswith(_SCRIPT_EXT) and name not in ("bash", "sh", "zsh", "dash", "source", "."):
            continue
        if where(c, root) != "inside":
            continue
        p = (root or Path.cwd()) / c.replace("\\", "/")
        try:
            if not p.is_file() or p.stat().st_size > MAX_COMMAND_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for f in classify(text, root, 2):
            out.append(Finding(f"the script {c} it runs: {f.reason}", whole, True, normalise(seg)))
    return out


# -- the gate ---------------------------------------------------------------------------------------------
def refusal_too_long(size: int) -> str:
    return (f"This command is {size // 1024} KB, too long to show the owner in full (the limit is 256 KB), so it "
            "wasn't asked about and didn't run. Split it into smaller commands.")


def refusal_denied(note: str = "") -> str:
    text = ("The owner didn't allow this command, so it didn't run. Don't try to do the same thing another way; "
            "carry on without it, or say in your summary why it's needed.")
    return text + (f" The owner says: {note}" if note else "")


def refusal_timeout(minutes: float) -> str:
    return (f"Nobody answered within {_minutes(minutes)}, so this command didn't run. Carry on without it, or say in "
            "your summary why it's needed.")


def _minutes(m: float) -> str:
    return f"{m:g} minute{'s' * (m != 1)}" if m >= 1 else f"{round(m * 60)} seconds"


class Gate:
    """Decides, for one project, whether a command may run now; waits for the owner when it must ask.

    ``on_change`` is called (with no arguments) when a card appears or goes, so the caller can publish the
    hub's ``.asks.json``; ``context`` returns {id, title} of the task doing the work (default: the task
    marked running in tasks.json)."""

    def __init__(self, root: str | Path, cfg: Any = None, on_change: Callable[[], Any] | None = None,
                 context: Callable[[], dict[str, Any] | None] | None = None, poll: float = 0.5,
                 timeout: float | None = None):
        self.root = Path(root).resolve()
        self.cfg = cfg
        self.on_change = on_change
        self.context = context
        self.poll = poll
        self.timeout = timeout  # seconds; None: from the settings
        self.waited = 0.0  # seconds spent waiting for answers, for limits that count time

    @property
    def dir(self) -> Path:
        return self.root / GATE_DIR

    def mode(self) -> str:
        return mode_for(self.root, self.cfg)

    def wait_seconds(self) -> float:
        return self.timeout if self.timeout is not None else timeout_for(self.cfg)

    # what "Always allow" remembered
    def allowed(self) -> list[dict[str, Any]]:
        try:
            data = json.loads((self.dir / ALLOWED_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [p for p in (data.get("patterns") or []) if isinstance(p, dict) and p.get("text")]

    def remember(self, findings: list[Finding]) -> None:
        have = self.allowed()
        keys = {(p["text"], bool(p.get("exact"))) for p in have}
        for f in findings:
            if (f.pattern, f.exact) not in keys:
                have.append({"text": f.pattern, "exact": f.exact, "reason": f.reason, "at": _now()})
                keys.add((f.pattern, f.exact))
        self.dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.dir / ALLOWED_FILE, {"patterns": have})

    def forget(self, text: str) -> bool:
        have = self.allowed()
        left = [p for p in have if p["text"] != text]
        if len(left) != len(have):
            _write_json(self.dir / ALLOWED_FILE, {"patterns": left})
        return len(left) != len(have)

    def _covered(self, f: Finding, whole: str, patterns: list[dict[str, Any]]) -> bool:
        for p in patterns:
            if p.get("exact"):
                if p["text"] == whole:
                    return True
            elif not f.exact and (f.segment == p["text"] or f.segment.startswith(p["text"] + " ")):
                return True
        return False

    def needs(self, command: str, mode: str | None = None) -> list[Finding]:
        """What in this command still needs the owner's say-so (empty: it may run)."""
        mode = mode or self.mode()
        if mode == "off":
            return []
        found = classify(command, self.root)
        if mode == "all":  # every part asks; the risky parts with their own reason
            risky_segs = {f.segment for f in found}
            found += [Finding(EVERY, prefix_of(s), False, normalise(s))
                      for s in segments(command) if normalise(s) not in risky_segs]
            if not found:
                found = [Finding(EVERY, normalise(command), True, normalise(command))]
        whole = normalise(command)
        pats = self.allowed()
        return [f for f in found if not self._covered(f, whole, pats)]

    def check(self, command: str) -> str | None:
        """None: it may run. Otherwise the tool result to give the model instead of running it. Waits."""
        size = len(command.encode("utf-8", errors="replace"))
        if size > MAX_COMMAND_BYTES:
            return refusal_too_long(size)
        mode = self.mode()
        findings = self.needs(command, mode)
        if not findings:
            return None
        cid = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{secrets.token_hex(3)}"
        limit = self.wait_seconds()
        ask = self._card(cid, command, findings, mode, limit)
        self.dir.mkdir(parents=True, exist_ok=True)
        ask_file, answer_file = self.dir / f"{cid}.ask.json", self.dir / f"{cid}.answer.json"
        _write_json(ask_file, ask)
        self._changed()
        start = time.monotonic()
        answer: dict[str, Any] | None = None
        try:
            while time.monotonic() - start < limit:
                answer = _read_json(answer_file)
                if answer is not None:
                    break
                time.sleep(min(self.poll, max(limit - (time.monotonic() - start), 0.01)))
            else:
                answer = _read_json(answer_file)  # one last look, so an answer on the stroke counts
        finally:
            self.waited += time.monotonic() - start
            for f in (ask_file, answer_file):
                try:
                    f.unlink()
                except OSError:
                    pass
            self._changed()
        if answer is None:
            return refusal_timeout(limit / 60)
        choice, note = answer.get("choice"), str(answer.get("note") or "").strip()
        if choice == ALWAYS:
            self.remember(findings)
            return None
        if choice == ALLOW:
            return None
        return refusal_denied(note)

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # publishing the card is a help: never stop the command over it
                pass

    def _task(self) -> dict[str, Any]:
        if self.context:
            try:
                t = self.context()
                if t:
                    return {"id": str(t.get("id", "")), "title": str(t.get("title", ""))}
            except Exception:
                pass
        try:
            tasks = json.loads((self.root / ".harness" / "tasks.json").read_text(encoding="utf-8") or "[]")
        except (OSError, ValueError):
            return {}
        running = [t for t in tasks if isinstance(t, dict) and t.get("status") == "running"]
        return {"id": str(running[0].get("id", "")), "title": str(running[0].get("title", ""))} if len(running) == 1 else {}

    def _card(self, cid: str, command: str, findings: list[Finding], mode: str, limit: float) -> dict[str, Any]:
        lines = command.splitlines() or [""]
        folded = len(lines) > FOLD_LINES or len(command) > FOLD_CHARS
        preview = "\n".join(lines[:FOLD_LINES])[:FOLD_CHARS] if folded else command
        reasons = list(dict.fromkeys(f.reason for f in findings))
        prefixes = list(dict.fromkeys(f.pattern for f in findings if not f.exact))
        remember = "this exact command" if any(f.exact for f in findings) or not prefixes else \
            " and ".join(f"“{p}”" for p in prefixes[:3])
        now = time.time()
        return {"id": cid, "command": command, "preview": preview, "folded": folded, "lines": len(lines),
                "size": len(command.encode("utf-8", errors="replace")), "reasons": reasons, "mode": mode,
                "remember": remember, "patterns": [{"text": f.pattern, "exact": f.exact} for f in findings],
                "task": self._task(), "asked_at": _iso(now), "expires_at": _iso(now + limit), "expires": now + limit,
                "pid": os.getpid()}

    # for asks.py
    def pending(self) -> list[dict[str, Any]]:
        """The commands waiting now, oldest first; a card left by a run that stopped is cleared."""
        if not self.dir.is_dir():
            return []
        out = []
        for f in sorted(self.dir.glob("*.ask.json")):
            data = _read_json(f)
            if not data:
                continue
            if float(data.get("expires") or 0) + 120 < time.time() or not _alive(data.get("pid")):
                for g in (f, f.with_name(f.name.replace(".ask.json", ".answer.json"))):
                    try:
                        g.unlink()
                    except OSError:
                        pass
                continue
            if (f.with_name(f.name.replace(".ask.json", ".answer.json"))).exists():
                continue  # answered: the run is about to pick it up
            out.append(data)
        return out

    def answer(self, cid: str, choice: str, note: str = "") -> bool:
        """Give the waiting command its answer (allow, always or deny); False when it's no longer waiting."""
        if choice not in (ALLOW, ALWAYS, DENY):
            raise ValueError(f"unknown answer {choice!r}")
        if not re.fullmatch(r"[\w-]+", cid) or not (self.dir / f"{cid}.ask.json").is_file():
            return False
        _write_json(self.dir / f"{cid}.answer.json", {"choice": choice, "note": note[:2000], "at": _now()})
        return True


def _alive(pid: Any) -> bool:
    """Whether the process that asked is still running (True when it can't be told)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return True  # os.kill(pid, 0) would end it on Windows; the expiry clears stale cards there
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _now() -> str:
    return _iso(time.time())


def _read_json(p: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(p: Path, data: dict[str, Any]) -> None:
    tmp = p.with_name(p.name + f".{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
