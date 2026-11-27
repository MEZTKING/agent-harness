"""Reach (wave 8, stub: p1-reach fills it): the hourly stand-up, work that starts from outside without an open
door, and the heartbeat that says a harness is listening.

``automation.py`` calls these: the schedule's ``standup`` work calls ``standup``; the kinds ``events`` (more of a
GitHub repository's events), ``poll`` (an address the owner names) and ``local`` (``POST /hooks/<id>`` from a
program on this PC, loopback only) are checked by ``normalise_hook``, said in words by ``hook_words``, and asked
for new items by ``poll_hooks``, each item shaped as ``automation.poll`` makes them
(``{"key", "what", "title", "text", "project"?}``) and then claimed and acted on once, as issues are.
``beat`` is called at each sync. Until p1-reach fills them they do nothing. The signatures are frozen.
"""


HOOK_KINDS = ("events", "poll", "local")


def standup(ctx) -> dict:
    """Look at every project (no model) and write one journal line; ``{"text", "ok"}`` for the automation's
    record. Stub: ``{}`` (nothing done, nothing recorded)."""
    return {}


def poll_hooks(ctx, a: dict) -> list[dict]:
    """The new items for the automation ``a`` (a kind in ``HOOK_KINDS``). Stub: none."""
    return []


def beat(hub, machine: dict) -> None:
    """Say this machine is listening (``plans/listening.json``: its name and the time). Stub: nothing."""
    return None


def normalise_hook(raw: dict, a: dict) -> dict:
    """``a`` (the automation's common fields, already checked) completed from ``raw`` for a kind in
    ``HOOK_KINDS``; raises ``ValueError`` with a plain sentence for something the owner must fix. Stub: keeps
    what it makes (an idea, or a task for a project) and its ``hook`` settings as given."""
    a["make"] = "task" if raw.get("make") == "task" else "idea"
    if raw.get("project"):
        a["project"] = str(raw["project"])
    a["hook"] = dict(raw.get("hook") or {})
    return a


_WORDS = {"events": "Events on GitHub", "poll": "A change at an address you named",
          "local": "A program on this computer"}


def hook_words(a: dict) -> str:
    """What starts it and what it makes, in one sentence. Stub: the kind in plain words."""
    to = "a new idea" if a.get("make") != "task" else "a task"
    return f"{_WORDS.get(a.get('kind'), 'Something outside')} starts {to}."
