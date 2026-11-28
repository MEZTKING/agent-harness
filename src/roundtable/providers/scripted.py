"""A deterministic fake provider for tests and dry runs.

Give it a list of responses (or a function) and it plays them back, so the
whole orchestrator can be exercised without API keys or spend.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import ChatResponse, ImageProvider, Provider, ProviderError, SoundProvider, ToolCall, Usage

Script = Callable[[str, str, list[dict[str, Any]], list], ChatResponse | dict]


def reply(text: str = "", calls: list[tuple[str, dict]] | None = None, id_prefix: str = "c") -> ChatResponse:
    tool_calls = [ToolCall(id=f"{id_prefix}{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls or [])]
    return ChatResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end",
        usage=Usage(input_tokens=100, output_tokens=20),
    )


Chunks = int | list[list[tuple[str, str]]] | None


class ScriptedProvider(Provider):
    """``chunks`` (wave 8): what a call given ``on_delta`` is told as it "writes". A number sends the reply's
    text in pieces of that many characters; a list holds one list of ``(kind, piece)`` per call, used in turn
    (a call with none left sends nothing). Without ``on_delta`` it is never used, and the calls recorded and
    the responses are the same with or without it."""

    def __init__(self, name: str = "scripted", script: Script | list | None = None, chunks: Chunks = None):
        self.name = name
        self.script = script if script is not None else []
        self.calls: list[dict[str, Any]] = []
        self.chunks = list(chunks) if isinstance(chunks, list) else chunks

    def _stream(self, resp: ChatResponse, on_delta) -> None:
        if isinstance(self.chunks, int) and self.chunks > 0:
            text = resp.text or ""
            for i in range(0, len(text), self.chunks):
                on_delta("text", text[i:i + self.chunks])
        elif isinstance(self.chunks, list) and self.chunks:
            for kind, piece in self.chunks.pop(0):
                on_delta(kind, piece)

    def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None, *, on_delta=None):
        self.calls.append({"model": model, "system": system, "messages": list(messages), "tools": tools})
        if callable(self.script):
            resp = self.script(model, system, messages, tools or [])
        elif self.script:
            resp = self.script.pop(0)
        else:
            raise ProviderError(f"{self.name}: script exhausted")
        if isinstance(resp, Exception):
            raise resp
        resp.model = resp.model or model
        if on_delta is not None and self.chunks:
            self._stream(resp, on_delta)
        return resp


class ScriptedImages(ImageProvider):
    def __init__(self, name: str = "scripted-images"):
        self.name = name
        self.prompts: list[str] = []

    def generate(self, model, prompt, options=None):
        self.prompts.append(prompt)
        # 1x1 transparent PNG
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
        )
        return png, "png", Usage(output_tokens=1)


class ScriptedSoundProvider(SoundProvider):
    """A fake sound service (wave 9): plays back ``sounds`` (``(audio bytes, extension, cost in dollars)``) in
    turn, quotes ``price`` for every sound and answers ``licence``. Counts its calls, so a test can prove that a
    refused quote made none."""

    def __init__(self, name: str = "scripted-sounds", sounds: list[tuple[bytes, str, float]] | None = None,
                 price: float | None = 0.01, licence: dict[str, Any] | None = None, balance: float | None = None):
        self.name = name
        self.sounds = list(sounds or [])
        self.price = price
        self._licence = dict(licence or {"commercial": True, "words": "Made-up licence for tests.", "link": "",
                                         "read_on": ""})
        self._balance = balance
        self.prompts: list[str] = []
        self.quotes: list[str] = []
        self.calls = 0

    def quote(self, model, prompt, options=None):
        self.quotes.append(prompt)
        return self.price

    def generate(self, model, prompt, options=None):
        self.calls += 1
        self.prompts.append(prompt)
        if not self.sounds:
            raise ProviderError(f"{self.name}: no sounds left")
        data, ext, cost = self.sounds.pop(0)
        return data, ext, Usage(cost_usd=cost)

    def licence(self):
        return dict(self._licence)

    def balance(self):
        return self._balance
