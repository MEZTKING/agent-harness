"""The desktop's chat (1.5.0: static/chat.js, chatcard.js and the boxes they use): the checks the other modules have
(it parses, colours only from the Eclipse tokens, logical properties for right-to-left, text that reads at AA in
every theme), and a few behaviours run in Node with a tiny stand-in page: the model's words never become a link or a
picture, a card's buttons, a card made on another device shows none, the cost words, and the chat id twin."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from roundtable import chatstore

from . import test_contrast as contrast

STATIC = Path(__file__).resolve().parents[1] / "src" / "roundtable" / "ui" / "static"
OWNED = ("chat.js", "chatcard.js", "compose.js", "stream.js", "queue.js", "voice.js")
STYLED = ("chat.js", "chatcard.js")
node = pytest.mark.skipif(not shutil.which("node"), reason="Node isn't installed here")


def _css(name: str) -> str:
    text = (STATIC / name).read_text(encoding="utf-8")
    m = re.search(r'"data-for": "\w+" \}, `(.*?)`\)\);', text, re.S)
    assert m, f"{name} carries its own style block"
    return m.group(1)


@node
@pytest.mark.parametrize("name", OWNED)
def test_it_parses_as_a_module(name, tmp_path):
    copy = tmp_path / (Path(name).stem + ".mjs")
    copy.write_text((STATIC / name).read_text(encoding="utf-8"), encoding="utf-8")
    res = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("name", STYLED)
def test_colours_only_from_the_tokens(name):
    css = _css(name)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", css), name
    defined = set(contrast.tokens("eclipse"))
    used = set(re.findall(r"var\((--[\w-]+)\)", css))
    assert used and used <= defined, sorted(used - defined)


@pytest.mark.parametrize("name", STYLED)
def test_logical_properties_for_right_to_left(name):
    css = _css(name)
    for bad in (r"\b(?:margin|padding|border)-(?:left|right)\b", r"(?<![\w-])(?:left|right)\s*:", r"text-align:\s*(?:left|right)",
                r"float:\s*(?:left|right)", r"(?<![\w-])(?:width|height)\s*:"):
        assert not re.search(bad, css), (name, bad)


def _pairs(css: str):
    """(selector, text token, background token) for each rule that sets both."""
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        fg = re.search(r"(?<![\w-])color:\s*var\((--[\w-]+)\)", body)
        bg = re.search(r"background:\s*var\((--[\w-]+)\)", body)
        if fg and bg:
            yield sel.strip(), fg.group(1), bg.group(1)


@pytest.mark.parametrize("theme", contrast.THEMES)
def test_text_reads_at_aa_on_its_own_background(theme):
    t = contrast.tokens(theme)
    surface = contrast.colour(t, "--color-surface")
    bad, seen = [], 0
    for name in STYLED:
        for sel, fg, bg in _pairs(_css(name)):
            seen += 1
            b = contrast.colour(t, bg)
            b = contrast.over(b, surface) if b[3] < 1 else b
            r = contrast.ratio(contrast.colour(t, fg), b)
            if r < 4.5:
                bad.append(f"{name} {sel}: {fg} on {bg} {r:.2f}")
    assert seen >= 6 and not bad, bad


def test_every_word_goes_through_the_table():
    """Sentences reach the screen through h()/fill() (words.auto) or t(): no template string or + joined text where
    the owner reads it, so the words ratchet (tests/test_words_extract.py) doesn't rise."""
    import sys

    sys.path.insert(0, str(STATIC.parents[3] / "tools"))
    import words_extract as X

    for name in ("chat.js", "chatcard.js"):
        found, left = X.sentences_of((STATIC / name).read_text(encoding="utf-8"))
        assert not left, (name, [s.tok.value for s in left])
        assert len(found) > 20, name


def test_the_model_s_words_are_never_html_and_cards_post_only_to_the_pc_route():
    text = (STATIC / "chat.js").read_text(encoding="utf-8") + (STATIC / "chatcard.js").read_text(encoding="utf-8")
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "markdown(" not in text and "inlineMd" not in text
    assert re.findall(r'post\("(/api/chats/[\w/]+)"', text) and set(re.findall(r'post\("(/api/chats/[\w/]+)"', text)) <= {
        "/api/chats/tap/pc", "/api/chats/say", "/api/chats/stop"}
    assert '"/api/chats/tap"' not in text  # the desktop's own app taps through /tap/pc


# -- behaviour, in Node with a stand-in page ---------------------------------------------------------------------
SHIM = r"""
class Node { constructor() { this.childNodes = []; this.parentNode = null; }
  append(...k) { for (const x of k) { const n = typeof x === "string" ? new Text(x) : x; n.parentNode = this; this.childNodes.push(n); } }
  replaceChildren(...k) { this.childNodes = []; this.append(...k); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes = []; this.append(String(v)); }
  get firstChild() { return this.childNodes[0] || null; }
  get isConnected() { return false; } }
class Text extends Node { constructor(d) { super(); this.data = d; } get textContent() { return this.data; } }
class El extends Node { constructor(t) { super(); this.tagName = t.toUpperCase(); this.attrs = {}; this.className = ""; this.style = {};
    this.classList = { add() {}, remove() {}, toggle() {} }; this.listeners = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { (this.listeners[k] ||= []).push(f); }
  querySelector() { return null; } querySelectorAll() { return []; }
  set title(v) { this.attrs.title = v; } get title() { return this.attrs.title; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t), createTextNode: (d) => new Text(d), head: new El("head") };
const all = (n, out = []) => { out.push(n); for (const c of n.childNodes || []) all(c, out); return out; };
const chat = await import("./chat.js");
const cc = await import("./chatcard.js");
const out = {};
const rich = chat.richText("# Done\nSee [the shop](https://evil.example/x) and ![logo](https://evil.example/a.png)\n- **one** `two`\n```\ncode\n```\nhttps://evil.example/bare");
out.rich_tags = [...new Set(all(rich).filter((n) => n.tagName).map((n) => n.tagName))].sort();
out.rich_text = rich.textContent;
out.rich_attrs = all(rich).filter((n) => n.attrs).flatMap((n) => Object.keys(n.attrs));
const card = { id: "c1", title: "Build the 5 accepted ideas", line: "The accepted ideas are built and checked.", price_usd: 1.4, cap_usd: 2,
  command: "/build accepted --at-most 2", state: "open", buttons: [{ id: "do", words: "Build", primary: true }, { id: "not_now", words: "Not now" }] };
const node = cc.chatCard(card, { chat: "bakery" });
out.buttons = all(node).filter((n) => n.tagName === "BUTTON").map((n) => n.textContent);
out.card_text = node.textContent;
out.untrusted = all(cc.chatCard(card, { chat: "bakery", trusted: false })).filter((n) => n.tagName === "BUTTON").length;
out.queued = cc.chatCard({ ...card, state: "queued", queued_for: "PC-Desk · last listened 3 hours ago",
  buttons: [{ id: "here", words: "Run it on This phone instead" }, { id: "cancel", words: "Cancel" }] }, { chat: "bakery" }).textContent;
out.done = all(cc.chatCard({ ...card, state: "done" }, { chat: "bakery" })).filter((n) => n.tagName === "BUTTON").length;
out.price = cc.priceWords(card);
out.cost = [0.0009, 0.0003, 0.003, 0.034, 0].map(chat.costWords);
out.ids = ["Music Player", "hall", "", "github.com/someone/bakery-app/web", "--x--"].map(chat.chatIdOf);
out.wrote = chat.wroteCard({ project: "bakery-app", count: 2 }).textContent;
console.log(JSON.stringify(out));
"""


@node
def test_behaviour_in_a_stand_in_page(tmp_path):
    for f in STATIC.glob("*.js"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(SHIM, encoding="utf-8")
    res = subprocess.run(["node", "run.js"], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    # the model's words: text only, never a link or a picture, and nothing carries an address
    assert "A" not in out["rich_tags"] and "IMG" not in out["rich_tags"], out["rich_tags"]
    assert {"B", "CODE", "PRE", "UL", "LI", "P"} <= set(out["rich_tags"])
    assert "the shop (https://evil.example/x)" in out["rich_text"] and "[logo]" in out["rich_text"]
    assert "a.png" not in out["rich_text"] and not {"href", "src"} & set(out["rich_attrs"])
    # a card: title, sentence, price and two buttons; none when made elsewhere or done
    assert out["buttons"] == ["Build", "Not now"]
    assert "Build the 5 accepted ideas" in out["card_text"] and "About $1.40 · stops at $2.00" in out["card_text"]
    assert out["untrusted"] == 0 and out["done"] == 0
    assert "Queued for PC-Desk · last listened 3 hours ago" in out["queued"]
    assert out["price"] == "About $1.40 · stops at $2.00"
    assert out["cost"] == ["0.1¢", "under 0.1¢", "0.3¢", "$0.03", ""]
    # the chat id is chatstore.chat_id's twin
    assert out["ids"] == [chatstore.chat_id(x) for x in ["Music Player", "hall", "", "github.com/someone/bakery-app/web", "--x--"]]
    assert "Bakery App wrote to you" in out["wrote"] and "2 new messages" in out["wrote"]
