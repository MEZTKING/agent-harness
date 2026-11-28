"""The chat's brain: who answers, what it is told, what it costs, and the cards it offers (1.5.0).

Step 0 freezes the signatures, the constants and the "never silence" codes below; chat-server fills them in.

- The model: the ``chat`` role (``HarnessConfig.chat_role``), else ``deepseek/deepseek-v4-flash``, else the
  project's cheapest other allowed model. Anything matching :data:`NEVER` is refused in code, whatever the
  configuration says.
- What is sent: the fixed opening and the command table (``prompts/chat-opening.json``, the same file the phone
  carries in its assets), the project's state cut to ``cfg.chat.context_tokens`` (fixed parts first, so the
  provider's cache takes them), the newest :data:`HISTORY` messages and the owner's words; the reply capped at
  :data:`REPLY_TOKENS`. Text from agents and files is marked as quoted material, never instructions.
- It never acts by itself: an ``Action: /<command> …`` line at the end of an answer becomes a card
  (:func:`card_for`), built by the app from the parsed command; only a tap (:func:`tap`) runs it.
- The daily allowance, ``cfg.chat.max_usd_per_day`` (the owner's $1), across every device: reserved before
  the call, settled with the real charge.
- When nothing can answer, the app answers itself (:func:`cannot`), with the same words on every device.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

NEVER = ("v4-pro",)  # never answers the chat, whatever the configuration says
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
REPLY_TOKENS = 700
HISTORY = 12  # the newest messages sent each time
SUMMARY_AFTER = 30  # older history is summed up once a chat passes this many messages (/compact)
OPENING_FILE = Path(__file__).parent / "prompts" / "chat-opening.json"  # copied into the phone's assets
PHONE_OPENING = "mobile/app/src/main/assets/chat-opening.json"  # (relative to the repository)

# Why nothing can answer: the code in GET /api/chats/read's ``can.why`` and the words the app writes itself.
# The buttons are BUTTONS ids (chatstore.py). {ago}, {limit}, {pc} are filled in.
CANNOT: dict[str, dict[str, Any]] = {
    "no_machine": {"words": "Nothing can answer right now: your PC last listened {ago}. Add a DeepSeek key to get "
                            "answers here at once (about a tenth of a cent a message), or I'll answer when your PC "
                            "is next on.", "buttons": ["add_key"]},
    "key_refused": {"words": "DeepSeek refused the key. Your message is kept.", "buttons": ["change_key"]},
    "no_credit": {"words": "The DeepSeek account is empty. Your message is kept.", "buttons": ["top_up"]},
    "offline": {"words": "No internet. Your message is kept and sent when you're back.", "buttons": []},
    "allowance": {"words": "Today's chat allowance ({limit}) is used.", "buttons": ["raise_today"]},
    "off": {"words": "The chat is switched off in Settings.", "buttons": []},
    "pc_stopped": {"words": "Your PC stopped answering; I'm answering from this phone.", "buttons": []},
}


def never(model: str) -> bool:
    """True for a model the chat must never use."""
    m = str(model or "").lower()
    return any(n in m for n in NEVER)


# -- stubs (chat-server fills these in) --------------------------------------------------------------------------
def model_for(cfg, project) -> Any:
    """The ModelRef that answers ``project``'s chat (None: Hall, or the app's own choice); never one in NEVER."""
    return None


def context(app, chat: str) -> str:
    """What the model is told about ``chat``: the fixed opening first, then the state, cut to the budget."""
    return ""


def reply(app, chat: str, text: str, files=(), on_delta: Callable[[str, str], None] | None = None,
          aloud: bool = False) -> dict[str, Any]:
    """Answer the owner's ``text`` in ``chat``; returns the answer's line (chatstore's line shape)."""
    return cannot("off")


def card_for(app, chat: str, action_line: str) -> dict[str, Any] | None:
    """The card for an ``Action: /<command> …`` line, or None when the command isn't in the table."""
    return None


def tap(app, chat: str, card_id: str, confirmed: bool = False, button: str = "do", pc: bool = False) -> dict[str, Any]:
    """A tap on one of a card's buttons (chatstore.BUTTONS): runs, queues or cancels it; returns the card's line
    as it now stands. Only an owner's tap runs anything that spends or can't be undone (``confirmed`` for a card
    with ``confirm``).
    ``pc``: the PC's own app (every command); the phone's route never runs a PC-only command."""
    return cannot("off")


def drain(app) -> int:
    """Answer every waiting message this machine can claim (the auto-sync); returns how many it answered."""
    return 0


def estimate(cfg, chat: str) -> float:
    """What the next message in ``chat`` is likely to cost, in dollars."""
    return 0.0


def cannot(why: str, **vals: Any) -> dict[str, Any]:
    """The app's own line when no model can answer (:data:`CANNOT`): ``who: app``, its words and buttons."""
    from . import chatstore

    spec = CANNOT[why]
    words = spec["words"]
    for k, v in vals.items():
        words = words.replace("{" + k + "}", str(v))
    line: dict[str, Any] = {"id": chatstore.new_id(), "at": chatstore.now(), "who": "app", "seat": "", "text": words}
    if spec["buttons"]:
        line["card"] = {"id": "app-" + why, "title": "", "line": words, "command": "", "state": "open",
                        "buttons": [{"id": b, "words": BUTTON_WORDS[b], **({"primary": True} if i == 0 else {})}
                                    for i, b in enumerate(spec["buttons"])]}
    return line


BUTTON_WORDS = {"do": "Do it", "not_now": "Not now", "cancel": "Cancel", "here": "Run it on This phone instead",
                "setup_phone": "Set up This phone first", "add_key": "Add a DeepSeek key",
                "change_key": "Change the key", "top_up": "Top up", "raise_today": "Raise it for today"}
