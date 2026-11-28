"""To-dos become actions: the owner never leaves the app (wave 9, w9-gaps).

The owner, 26 November 2026: "For the to-do list I'm not supposed to ever leave the app; you're meant to set up
everything so all my agents do it – that's the whole point."

``action_for(todo, app)`` gives the one button a to-do card shows: ``{label, route, body, confirm}`` (plus
``kind``, ``close`` and ``tip``), or None. Each kind of to-do the harness writes maps to something the app does
in one tap:

* **approve** – "the plan is ready": approve it here, or through the hub where the project lives;
* **carry on / try again / open** – a paused or stopped run: carry on, retry the task, or open its page;
* **key** – a missing key: the app's own key form (Settings → API keys), never a file or a command;
* **job** – a role to add: the recommended set-up's own route;
* **tool** – a tool to install: the Tools page's install job (``prereq``), always the owner's tap;
* **github** – a GitHub setting (the default branch): through the GitHub key the app already holds;
* **backups** – turn on daily backups with the folder found (``backup.turn_on``);
* **hand over** – anything only a session can do (a cloud environment's set-up script, a programmer's
  instruction, checking a price list): sent as a letter to the session that manages it, never to the owner.

A to-do with no action keeps Done and is counted (``counts``). ``tests/test_todoactions.py`` fails if the
harness's own code writes a to-do that tells the owner to "go to", "paste", "type" or "run" something without
an action here.

Routes starting with ``#/`` open a page in the app (the card's button navigates); the rest are POSTs the
server does through ``POST /api/todo/act`` (``ui/todoapi.py``), from this table only, never a route the page
sends.
"""

from __future__ import annotations

import re
from typing import Any

# the sentence asks the owner to do something by hand: these need an action
IMPERATIVE = re.compile(r"(?:^|[.:;!?]\s+|\bthen\s+|\band\s+|\bor\s+)(go to|paste|type|run)\b", re.I)

PLAN_READY = re.compile(r"\bplan is ready\b", re.I)
TASK_FAILED = re.compile(r"^Task (?P<task>[A-Za-z0-9_.-]+)\b.*\bdidn'?t pass", re.I)
TOP_UP = re.compile(r"\btop (?:it |that account |the balance |your balance )?up\b|\bout of credit\b", re.I)
BUDGET = re.compile(r"\bspending limit\b.*\bcarry on\b|\bchoose carry on\b", re.I)
REAL_LIMIT = re.compile(r"\bthe limit you set\b.*\brun again\b", re.I)
DAY_LIMIT = re.compile(r"\btoday'?s spending limit\b", re.I)
STAGE = re.compile(r"\btry it, then carry on\b", re.I)
SETUP_DECLARED = re.compile(r"\bchoose fetch and install\b", re.I)
SETUP_FAILED = re.compile(r"\bsetup command\b", re.I)
OPEN_PROJECT = re.compile(r"\bnot finished yet\b|\bfinished nothing\b|\byou agreed to about\b|\bcouldn'?t be finished\b"
                          r"|\bwaits for you\b|\bnot everything could be (?:done|set up)\b"
                          r"|\bis stuck\b|\bnothing has happened for a while\b|\byou agreed\b", re.I)
ROLE = re.compile(r"\badd an? (?P<role>[a-z][a-z-]{1,30}) role\b|\brecommended split\b|\broundtable assign\b", re.I)
KEY = re.compile(r"\b(?:add|save|needs?|missing|no|enter)\b[^.]{0,30}\b(?:api )?key\b|\bkey (?:for|is missing)\b", re.I)
DEFAULT_BRANCH = re.compile(r"\bdefault branch\b", re.I)
REPO_IN = re.compile(r"\b(?:of|for|on)\s+`?(?P<repo>[A-Za-z0-9][\w.-]*(?:/[\w.-]+)?)`?", re.I)
BACKUPS = re.compile(r"\bback ?ups?\b|\bback up\b", re.I)
CLOUD = re.compile(r"\bcloud environments?\b|\bsetup (?:lines|script)\b|\benvironment\b.*\bsetup\b", re.I)
PRICES = re.compile(r"\bcheck\b.*\bprices?\b|\bprices?\b.*\bcheck\b", re.I)
INSTALL = re.compile(r"\binstall\b|\bneeds?\b", re.I)
TECHNICAL = re.compile(r"`|\b(pip|npm|pnpm|gradlew?|git|clone|commit|venv|cli)\b|~/|\$[A-Z_]{3,}", re.I)


def _act(kind: str, label: str, route: str, body: dict[str, Any] | None = None, confirm: str | None = None,
         close: bool = True, tip: str = "") -> dict[str, Any]:
    return {"kind": kind, "label": label, "route": route, "body": body or {}, "confirm": confirm, "close": close,
            "tip": tip}


def _project_path(todo: dict[str, Any], app) -> str:
    """The folder of a project on this computer that the to-do is about ('' when it runs elsewhere)."""
    if todo.get("path"):
        return str(todo["path"])
    pid = str(todo.get("project") or "")
    if not pid or app is None:
        return ""
    try:
        for p in app._lab_projects():
            if p.name == pid:
                return str(p)
    except Exception:  # noqa: BLE001 - no lab here: the hub's way, or a page
        pass
    return ""


def _hub_target(todo: dict[str, Any]) -> tuple[str, str]:
    agent = str(todo.get("hub_agent") or todo.get("agent") or todo.get("project") or "")
    return agent, str(todo.get("project") or agent)


def _run(todo: dict[str, Any], app, action: str, label: str, confirm: str | None = None, tip: str = "",
         **extra: Any) -> dict[str, Any]:
    """A project action here (``/api/project``), else the same command through the hub."""
    path = _project_path(todo, app)
    if path:
        return _act("run", label, "/api/project", {"path": path, "action": action, **extra}, confirm, tip=tip)
    agent, folder = _hub_target(todo)
    hub_action = "carry_on" if action in ("run", "raise_budget") else action
    fields = {k: v for k, v in extra.items()}
    return _act("hub", label, "/api/hub/command", {"agent": agent, "folder": folder, "action": hub_action,
                                                   **({"fields": fields} if fields else {})}, confirm,
                tip=tip or "Sent through the hub to the computer that builds it")


def _page(todo: dict[str, Any], label: str, tab: str = "", tip: str = "") -> dict[str, Any]:
    pid = str(todo.get("project") or "")
    route = f"#/p/{pid}" + (f"/{tab}" if tab else "") if pid else "#/needs"
    return _act("page", label, route, close=False, tip=tip or "Opens it here, in the app")


def _tool_for(text: str):
    """The Tools page's tool a to-do names (by its name or id), or None."""
    try:
        from . import prereq
    except Exception:  # noqa: BLE001
        return None
    low = text.lower()
    for t in prereq.CATALOG:
        names = {t.id.lower(), t.name.lower(), t.name.split(" (")[0].lower()}
        if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names if len(n) > 2):
            return t
    return None


def _handover(todo: dict[str, Any], label: str, to: str = "", tip: str = "") -> dict[str, Any]:
    agent = to or str(todo.get("agent") or todo.get("hub_agent") or todo.get("project") or "")
    return _act("handover", label, "/api/todo/handoff", {"agent": str(todo.get("agent") or agent),
                                                          "id": str(todo.get("id") or ""), "to": agent},
                tip=tip or "Sent as a letter to the session that works on it: it does this with its own tools, "
                           "not you")


def action_for(todo: dict[str, Any], app) -> dict[str, Any] | None:
    """``{"label", "route", "body", "confirm"}`` (and ``kind``, ``close``, ``tip``) for the button on ``todo``,
    or None when there's nothing better than Done."""
    text = " ".join(str(todo.get("text") or "").split())
    if not text:
        return None
    details = str(todo.get("details") or "")
    m = TASK_FAILED.search(text)
    if PLAN_READY.search(text):
        return _run(todo, app, "approve", "Approve and start",
                    confirm="Approve the plan and start building? It spends up to its estimate.",
                    tip="The same as Approve on the plan's page")
    if m:
        return _run(todo, app, "retry", "Try it again", task=m.group("task"))
    if SETUP_DECLARED.search(text):
        return _act("page", "Open its card", "#/needs", close=False, tip="The card lists what it will fetch and install")
    if TOP_UP.search(text):
        if todo.get("project"):
            return _run(todo, app, "run", "I've topped up: carry on",
                        tip="Carries on from where it stopped once the account has money again")
        return _act("page", "See the balances", "#/settings/services", close=False,
                    tip="Each service's balance, and its own page for adding money")
    if BUDGET.search(text):
        return _run(todo, app, "raise_budget", "Carry on",
                    confirm="Give this project more money and carry on?")
    if REAL_LIMIT.search(text):
        return _run(todo, app, "run", "Carry on",
                    confirm="Carry on? This run has already spent the most you allowed for one run.")
    if DAY_LIMIT.search(text):
        return _act("page", "See the spending limits", "#/settings/spending", close=False,
                    tip="It carries on by itself tomorrow; raise today's limit there to go on now")
    if STAGE.search(text):
        return _run(todo, app, "run", "Carry on", tip="Starts the next stage")
    if SETUP_FAILED.search(text):
        return _page(todo, "Open its settings", "settings", tip="Change the setup command there, then run again")
    if OPEN_PROJECT.search(text):
        return _page(todo, "Open the project")
    if ROLE.search(text):
        return _act("job", "Use the recommended set-up", "/api/setup/recommended", {},
                    confirm="Put in the recommended set-up (who plans, who codes and who checks, with a critic for "
                            "every plan)? Your other settings stay as they are; the old file is kept.")
    if DEFAULT_BRANCH.search(text):
        rm = REPO_IN.search(text)
        repo = rm.group("repo") if rm else str(todo.get("repo") or "")
        branch = "main"
        return _act("github", "Set it on GitHub", "/api/todo/github", {"repo": repo, "branch": branch},
                    confirm=f"Make {branch} the default branch of {repo or 'this repository'} on GitHub?",
                    tip="Done with the GitHub key the app already holds")
    if CLOUD.search(text):
        return _handover(todo, "Hand it to that session",
                         tip="For the session that manages that cloud environment: it sets the script itself")
    if KEY.search(text):
        return _act("page", "Add the key", "#/settings/keys", close=False,
                    tip="The app's own key form: the key is saved on this computer only")
    if BACKUPS.search(text):
        return _act("backups", "Turn on backups", "/api/todo/backup", {},
                    tip="Every day, into the Google Drive folder found on this computer (or the folder you chose)")
    if INSTALL.search(text):
        tool = _tool_for(text)
        if tool is not None:
            return _act("tool", f"Install {tool.name}", "/api/tools/install", {"tool": tool.id},
                        confirm=f"Install {tool.name} on this computer?", close=False,
                        tip="Installed in the background; the Tools page shows how it went")
    if PRICES.search(text):
        return _handover(todo, "Ask an agent to check", tip="An agent reads the price list and corrects the counts")
    if IMPERATIVE.search(text) or TECHNICAL.search(text) or TECHNICAL.search(details):
        return _handover(todo, "Hand it to an agent")
    return None


def counts(todos: list[dict[str, Any]], app) -> dict[str, int]:
    """{"with": n, "without": m}: how many of these to-dos have an action, and how many only Done."""
    out = {"with": 0, "without": 0}
    for t in todos:
        out["with" if action_for(t, app) else "without"] += 1
    return out


def needs_action(text: str) -> bool:
    """The sentence tells the owner to do something by hand ("go to", "paste", "type", "run")."""
    return bool(IMPERATIVE.search(" ".join((text or "").split())))
