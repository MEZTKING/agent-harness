"""A made-up world for the chat's tests: a hub in a temp folder, a finished made-up project on this machine,
a session agent in another repository, the owner's phone as a machine seat, and scripted models (the chat's
own on a scripted ``deepseek`` provider). No network, no keys."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from roundtable.providers.base import ChatResponse, Usage
from roundtable.providers.scripted import ScriptedProvider

from .test_harness import RAW, make
from .test_hub import RAW as HUB_RAW
from .test_plan import PlanBrain

CHAT_MARK = "You are the chat of Darkness Harness"


class ChatModel:
    """The chat's scripted model: answers in turn (text, or (text, usage)), and records what it was sent."""

    def __init__(self, answers=None, usage: Usage | None = None):
        self.answers = list(answers or [])
        self.usage = usage or Usage(input_tokens=1000, output_tokens=300, cache_read_tokens=5000)
        self.sent: list[dict] = []

    def __call__(self, model, system, messages, tools):
        self.sent.append({"model": model, "system": system, "messages": messages, "tools": [t.name for t in tools]})
        a = self.answers.pop(0) if self.answers else "All fine."
        if callable(a):
            a = a(model, system, messages, tools)
        if isinstance(a, ChatResponse):
            return a
        text, use = (a if isinstance(a, tuple) else (a, self.usage))
        return ChatResponse(text=text, usage=use)


class World:
    def __init__(self, tmp_path: Path, monkeypatch, answers=None, plan: bool = False, chunks=7,
                 extra_raw: dict | None = None):
        from roundtable.ui.server import UIApp

        self.tmp = tmp_path
        hub_raw = json.loads(json.dumps(HUB_RAW))
        hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
        hub_raw["agents"] = {"me": {}, "harness": {}, "website": {"repo": "me/website", "title": "Website"},
                             "phone-abc123": {"title": "Phone (Test)", "role": "machine"}}
        hub_raw["rules"] = [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]
        (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
        hraw = json.loads(json.dumps(RAW))
        hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
        hraw["providers"]["deepseek"] = {"type": "scripted"}
        hraw.update(extra_raw or {})
        self.model = ChatModel(answers)
        brain = PlanBrain() if plan else None
        orch, a, b, img, events = make(tmp_path, raw=hraw, brain=brain)
        self.deepseek = ScriptedProvider("deepseek", self.model, chunks=chunks)
        orch.cfg.register("deepseek", self.deepseek)
        self.cfg = orch.cfg
        self.cfg.lab_dir = tmp_path / "lab"
        if plan:
            orch.start("bakery site", require_approval=True)
            assert orch.run() == "awaiting_approval"
        else:
            orch.start("bakery site")
            assert orch.run() == "done"
        orch._register_with_lab()
        self.orch = orch
        self.root = orch.project.root
        self.home = tmp_path / "home"
        monkeypatch.setenv("ROUNDTABLE_HOME", str(self.home))
        app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml")
        app.cfg = lambda: self.cfg
        app.need_cfg = lambda: self.cfg
        app.projects_dir = tmp_path / "projects"
        app.agent = "me"
        app.home = self.home
        self.app = app
        self.hub = app.hub
        from roundtable import chat

        self.chat = chat.chat_for_path(app, str(self.root))

    def say(self, text, chat=None, **kw):
        from roundtable.ui import chatsapi

        chat = chat or self.chat
        got = self.app.dispatch("POST", "/api/chats/say", {}, {"chat": chat, "text": text, **kw})
        assert chatsapi.wait(chat, 20)
        return got

    def read(self, chat=None, since=""):
        q = {"chat": [chat or self.chat]}
        if since:
            q["since"] = [since]
        return self.app.dispatch("GET", "/api/chats/read", q, {})

    def lines(self, chat=None):
        from roundtable import chatstore

        return chatstore.lines_of(self.home, self.hub, chat or self.chat)

    def last(self, who="chat", chat=None):
        return [x for x in self.lines(chat) if x["who"] == who][-1]

    def tap(self, card, button="do", confirmed=False, chat=None, route="/api/chats/tap/pc"):
        return self.app.dispatch("POST", route, {}, {"chat": chat or self.chat, "card": card, "button": button,
                                                     "confirmed": confirmed})["line"]
