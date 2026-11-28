"""The chat that replaced Letters, step 0: the seams chat-server, chat-desktop and chat-phone fill (1.5.0).

With every stub in place and nothing using them, the harness behaves exactly as before: a bare scripted
plan-and-run sends byte for byte the golden requests of test_sweep_seam.py. The frozen signatures, the routes,
the line and card shapes, the hub layout, the settings and the phone's copies are checked here.
"""

import gzip
import importlib
import inspect
import json
import re
from pathlib import Path

import pytest

from roundtable import chat, chatstore, phone, sync
from roundtable.harness.config import ChatSettings, merge_custom, parse_config
from roundtable.ui import chatsapi
from roundtable.ui.server import FEATURE_APIS

from .test_harness import RAW
from .test_sweep_seam import GOLDEN, requests_of

ROOT = Path(__file__).resolve().parents[1]
KT = ROOT / "mobile/app/src/main/java/com/meztking/roundtable"

# The same line and card as mobile/app/src/test/…/data/ChatTest.kt: both apps read this shape alike.
SAMPLE_LINE = """{"id": "20261128T101500123-3fa9c1d2", "at": "2026-11-28T10:15:00.123Z", "who": "chat",
 "seat": "pc-desk-1a2b", "device": "PC-Desk", "text": "Five ideas are accepted and ready to build.",
 "thinking": "The board shows five accepted.", "cost_usd": 0.0009, "model": "deepseek/deepseek-v4-flash",
 "answers": "20261128T101458001-0c0ffee0",
 "files": [{"name": "sketch.png", "sha": "ab12", "ext": "png", "size": 120000, "kind": "picture"}],
 "card": {"id": "c1", "title": "Build the 5 accepted ideas", "line": "About $1.40, stops at $2.00.",
          "price_usd": 1.4, "cap_usd": 2.0, "command": "/build accepted at most $2", "state": "open",
          "buttons": [{"id": "do", "words": "Build", "primary": true}, {"id": "not_now", "words": "Not now"}]}}"""


def _sig(fn):
    return re.sub(r"pathlib(\._local)?\.Path", "Path", str(inspect.signature(fn))).replace("'", "")


# -- byte for byte as before ----------------------------------------------------------------------------------
def test_a_bare_plan_and_run_still_sends_the_golden_requests(tmp_path, monkeypatch):
    assert requests_of(tmp_path, monkeypatch) == gzip.decompress(GOLDEN.read_bytes()).decode("utf-8")


# -- the frozen signatures ------------------------------------------------------------------------------------
def test_chatstore_has_its_frozen_signatures():
    want = {
        "chat_id": "(project_or_none: str | None) -> str",
        "append": "(home: Path, hub, chat: str, line: dict[str, Any]) -> dict[str, Any]",
        "read": "(home: Path, hub, chat: str, since: str = , limit: int = 200) -> dict[str, Any]",
        "earlier": "(hub, chat: str) -> list[dict[str, Any]]",
        "attach": "(home: Path, hub, chat: str, name: str, data: bytes) -> dict[str, Any]",
        "waiting": "(hub) -> list[dict[str, Any]]",
        "claim": "(hub, chat: str, turn: str, seat: str) -> bool",
        "chats": "(app) -> list[dict[str, Any]]",
        "day_path": "(chat: str, day: str, seat: str) -> str",
        "file_path": "(chat: str, sha: str, ext: str) -> str",
        "claim_path": "(chat: str, turn: str) -> str",
        "order_key": "(line: dict[str, Any]) -> tuple[str, str, str]",
        "check_line": "(line: dict[str, Any]) -> dict[str, Any]",
        "check_card": "(card: dict[str, Any]) -> dict[str, Any]",
    }
    assert {k: _sig(getattr(chatstore, k)) for k in want} == want


def test_chat_has_its_frozen_signatures():
    want = {
        "model_for": "(cfg, project) -> Any",
        "context": "(app, chat: str) -> str",
        "reply": ("(app, chat: str, text: str, files=(), on_delta: Callable[[str, str], None] | None = None, "
                  "aloud: bool = False) -> dict[str, Any]"),
        "card_for": "(app, chat: str, action_line: str) -> dict[str, Any] | None",
        "tap": ("(app, chat: str, card_id: str, confirmed: bool = False, button: str = do, pc: bool = False)"
                " -> dict[str, Any]"),
        "drain": "(app) -> int",
        "estimate": "(cfg, chat: str) -> float",
        "cannot": "(why: str, **vals: Any) -> dict[str, Any]",
        "never": "(model: str) -> bool",
    }
    assert {k: _sig(getattr(chat, k)) for k in want} == want
    assert chat.NEVER == ("v4-pro",) and chat.DEFAULT_MODEL == "deepseek/deepseek-v4-flash"
    assert (chat.REPLY_TOKENS, chat.HISTORY, chat.SUMMARY_AFTER) == (700, 12, 30)


def test_never_refuses_v4_pro_whatever_it_is_called():
    assert chat.never("deepseek/deepseek-v4-pro") and chat.never("DeepSeek-V4-Pro") and chat.never("or/v4-pro-max")
    assert not chat.never("deepseek/deepseek-v4-flash") and not chat.never("")


# -- the shapes -------------------------------------------------------------------------------------------------
def test_the_hub_layout():
    assert chatstore.day_path("hall", "2026-11-28", "pc-desk-1a2b") == "chats/hall/2026-11-28.pc-desk-1a2b.jsonl"
    assert chatstore.file_path("music-player-1a2b3c4d", "ab12", "png") == "chats/music-player-1a2b3c4d/files/ab12.png"
    assert chatstore.claim_path("hall", "t1") == "chats/hall/claims/t1.json"
    with pytest.raises(ValueError):
        chatstore.day_path("../inbox", "2026-11-28", "s")
    assert "chats/<chat>/<day>.<seat>.jsonl" in chatstore.__doc__
    assert "chats/<chat>/claims/<turn>.json" in chatstore.__doc__


def test_chat_ids():
    assert chatstore.chat_id(None) == chatstore.chat_id("") == "hall"
    assert chatstore.chat_id("Music-Player-1a2b3c4d") == "music-player-1a2b3c4d"
    assert chatstore.chat_id("hall") == "project-hall"  # a project can't take Hall's place
    assert chatstore.is_chat("hall") and not chatstore.is_chat("a/b") and not chatstore.is_chat("")


def test_the_sample_line_and_card_are_the_frozen_shape():
    line = json.loads(SAMPLE_LINE)
    assert chatstore.check_line(line) == line
    assert set(line) <= set(chatstore.LINE_KEYS) and set(line["card"]) <= set(chatstore.CARD_KEYS)
    with pytest.raises(ValueError):
        chatstore.check_line({**line, "who": "me"})
    with pytest.raises(ValueError):
        chatstore.check_card({**line["card"], "state": "maybe"})
    with pytest.raises(ValueError):
        chatstore.check_card({**line["card"], "buttons": [{"id": "do"}]})
    assert chatstore.check_line({**line, "extra": 1}) == line  # unknown keys are dropped
    a = {"at": "2026-11-28T10:15:00.123Z", "seat": "b", "id": "2"}
    b = {"at": "2026-11-28T10:15:00.123Z", "seat": "a", "id": "9"}
    assert sorted([a, b], key=chatstore.order_key) == [b, a]
    assert re.match(r"^\d{8}T\d{9}-[0-9a-f]{8}$", chatstore.new_id())
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", chatstore.now())


def test_every_cannot_line_is_a_line_with_known_buttons():
    assert set(chat.BUTTON_WORDS) == set(chatstore.BUTTONS)
    assert set(chat.CANNOT) == {"no_machine", "key_refused", "no_credit", "offline", "allowance", "off",
                                "pc_stopped"}
    for why, spec in chat.CANNOT.items():
        assert set(spec["buttons"]) <= set(chatstore.BUTTONS)
        line = chatstore.check_line(chat.cannot(why, ago="3 hours ago", limit="$1.00"))
        assert line["who"] == "app" and "{" not in line["text"]
    assert "3 hours ago" in chat.cannot("no_machine", ago="3 hours ago")["text"]
    assert chat.cannot("allowance", limit="$1.00")["card"]["buttons"][0] == {"id": "raise_today",
                                                                           "words": "Raise it for today",
                                                                           "primary": True}


# -- the stubs do nothing -----------------------------------------------------------------------------------------
def test_with_no_hub_and_no_harness_nothing_is_sent_or_spent(tmp_path):
    """(Step 0 checked the stubs did nothing; chat-server filled them: now only the local copy is written.)"""
    line = chatstore.append(tmp_path, None, "hall", {"who": "owner", "seat": "s", "text": "hello"})
    assert line["text"] == "hello" and line["id"] and line["at"]
    assert [x["text"] for x in chatstore.read(tmp_path, None, "hall")["lines"]] == ["hello"]
    assert chatstore.earlier(None, "hall") == [] and chatstore.waiting(None) == [] and chatstore.chats(None) == []
    assert chatstore.claim(None, "hall", "t", "s") is False
    assert chatstore.attach(tmp_path, None, "hall", "a.txt", b"hi")["size"] == 2
    assert chat.drain(None) == 0
    assert chat.estimate(None, "hall") == 0.0 and chat.model_for(None, None) is None
    assert {p.name for p in tmp_path.iterdir()} == {"chats"}


# -- the routes -------------------------------------------------------------------------------------------------
ROUTES = {("GET", "/api/chats"), ("GET", "/api/chats/read"), ("POST", "/api/chats/say"), ("POST", "/api/chats/tap"),
          ("POST", "/api/chats/stop"), ("GET", "/api/chats/file")}


def test_the_routes_are_served_and_the_phone_has_all_six():
    assert "chatsapi" in FEATURE_APIS
    keys = set(importlib.import_module("roundtable.ui.chatsapi").routes(object()))
    assert keys == ROUTES | {("POST", "/api/chats/tap/pc")}
    assert ROUTES <= phone.PHONE_ROUTES
    assert ("POST", "/api/chats/tap/pc") not in phone.PHONE_ROUTES  # every command: the PC's own app only
    assert not phone.phone_allowed("POST", "/api/chats/tap/pc")


def test_the_routes_answer_in_their_frozen_shapes():
    class App:
        home = hub = None

    r = chatsapi.routes(App())
    assert [c["id"] for c in r[("GET", "/api/chats")]({})["chats"]] == ["hall"]
    got = r[("GET", "/api/chats/read")]({"chat": ["hall"]})
    assert {"lines", "at", "answering", "can"} <= set(got) and set(got["can"]) == {"answer", "why"}
    assert set(r[("POST", "/api/chats/say")]({"chat": "hall", "text": "hi"})) == {"line", "turn"}
    from roundtable.ui import chatsapi as _api

    _api.wait("hall")
    note = chat.cannot("allowance", limit="$1.00")
    chatstore.append(chat.home_of(App()), None, "hall", {**note, "seat": chatstore.me()["id"]})
    app_card = note["card"]["id"]  # the app's own card: Not now just folds it
    assert set(r[("POST", "/api/chats/tap")]({"chat": "hall", "card": app_card, "button": "not_now"})) == {"line"}
    assert r[("POST", "/api/chats/stop")]({"chat": "hall", "turn": "t"}) == {"stopped": False}
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError):
        r[("GET", "/api/chats/read")]({"chat": ["../inbox"]})


def test_the_phones_tap_is_narrowed():
    narrow = phone.PHONE_NARROW[("POST", "/api/chats/tap")]
    assert narrow({"chat": "hall", "card": "c1"}) == {"chat": "hall", "card": "c1", "button": "do",
                                                      "confirmed": False}
    assert narrow({"chat": "hall", "card": "c1", "button": "here", "confirmed": True})["confirmed"] is True
    assert narrow({"chat": "hall", "card": "c1", "confirmed": "yes"})["confirmed"] is False  # only a real yes
    for bad in ({"chat": "hall", "card": "c1", "pc": True}, {"chat": "hall", "card": "c1", "command": "/test"},
                {"chat": "hall", "card": "c1", "button": "run_anything"}, {"chat": "hall"}):
        with pytest.raises(phone.NarrowRefused):
            narrow(bad)


# -- the settings -------------------------------------------------------------------------------------------------
def test_the_chat_settings_and_role():
    cfg = parse_config(RAW)
    assert cfg.chat == ChatSettings(enabled=True, max_usd_per_day=1.0, context_tokens=5000)
    assert cfg.chat_role is None  # no role "chat": chat.model_for chooses
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["chat"] = {"model": raw["roles"]["orchestrator"]["model"]}
    raw["chat"] = {"max_usd_per_day": 2.5, "context_tokens": 4000}
    cfg = parse_config(raw)
    assert cfg.chat_role == "chat" and cfg.chat.max_usd_per_day == 2.5 and cfg.chat.context_tokens == 4000
    assert parse_config({**RAW, "chat": False}).chat.enabled is False
    with pytest.raises(ValueError):
        parse_config({**RAW, "chat": {"max_usd_per_day": -1}})
    assert merge_custom({**RAW, "chat": {"enabled": False}}, {"chat": {"max_usd_per_day": 3}})["chat"] == {
        "enabled": False, "max_usd_per_day": 3}


def test_the_allowance_is_a_shared_setting(tmp_path):
    assert sync.CHAT_LIMIT in sync.SHARED_LIMITS
    assert sync._clean({"limits": {"chat_usd_per_day": 2}}) == {"limits": {"chat_usd_per_day": 2.0}}
    import yaml

    harness = tmp_path / "harness.yaml"
    harness.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    assert sync.local_snapshot(harness, tmp_path / "home")["limits"]["chat_usd_per_day"] == 1.0
    sync.apply_shared({"limits": {"chat_usd_per_day": 2.0, "max_cost_usd": 7}}, harness, tmp_path / "home")
    custom = yaml.safe_load((tmp_path / "custom.yaml").read_text(encoding="utf-8"))
    assert custom["chat"] == {"max_usd_per_day": 2.0} and "chat_usd_per_day" not in custom["limits"]
    snap = sync.local_snapshot(harness, tmp_path / "home")["limits"]
    assert snap["chat_usd_per_day"] == 2.0 and snap["max_cost_usd"] == 7.0


# -- the phone's copies ------------------------------------------------------------------------------------------
def test_the_opening_is_one_file_the_phone_carries_too():
    pc = json.loads(chat.OPENING_FILE.read_text(encoding="utf-8"))
    assert {"version", "opening", "commands", "reply_tokens", "history", "model"} <= set(pc)
    assert (pc["reply_tokens"], pc["history"], pc["model"]) == (chat.REPLY_TOKENS, chat.HISTORY, "deepseek-v4-flash")
    assert (ROOT / chat.PHONE_OPENING).read_bytes() == chat.OPENING_FILE.read_bytes()


def test_the_phone_seams_are_there():
    chat_kt = (KT / "data/Chat.kt").read_text(encoding="utf-8")
    for name in ("class ChatLine", "class ChatCard", "class CardButton", "class ChatFile", "class ChatSummary",
                 "class ChatRead", "class CanAnswer", "object ChatLayout"):
        assert name in chat_kt
    for b in chatstore.BUTTONS:
        assert f'"{b}"' in chat_kt
    brain = (KT / "data/ChatBrain.kt").read_text(encoding="utf-8")
    assert "interface ChatBrain" in brain and "fun say(" in brain and "Flow<Piece>" in brain
    assert "fun chatBrain(" in (KT / "data/MultiBackend.kt").read_text(encoding="utf-8")
    store = (KT / "data/Store.kt").read_text(encoding="utf-8")
    assert "var chatKey" in store and "chatSeat" in store
