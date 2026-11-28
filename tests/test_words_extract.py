"""The English table and the ratchet (tools/words_extract.py), the sweep (tools/words_sweep.py) and the turn from
left and right to logical properties. Made-up modules only, except the ratchet and the table, which read the real
pages."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _load(name):
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    return importlib.import_module(name)


X = _load("words_extract")
SW = _load("words_sweep")

# Template strings and joined text the owner reads that don't pass the table yet. The coordinator's sweep brings it
# down (17 after wave 9's sweep, 28 November 2026); it may only fall. Raise it only by turning a sentence into t(…).
NOT_THROUGH_LIMIT = 17


def test_the_extractor_finds_sentences_in_h_title_toast_dialog_and_t():
    src = '''
import { h, toast, dialog } from "./core.js";
const STATES = { running: "Being built", done: "Done", id: "x-y" };
export function view(p) {
  toast("Saved: the old one is kept");
  dialog({ title: "Clear attempts?", text: "Nothing is lost.", yes: "Clear", no: "Keep them" });
  return h("section", { class: "card wide", title: "What each part does", href: "#/p/x" }, h("h2", {}, "Your projects"),
    h("p", {}, ok ? "It works" : "It doesn't"), h("input", { placeholder: "Write here", "aria-label": "The idea" }),
    t("{n} for you", { n }), h("p", {}, `${p.n} waiting for you`), h("p", {}, "Cost: " + money(p.usd)),
    h("span", { class: "x" }, "·"), h("code", {}, ".mono { margin: 0; padding: 0; }"));
}
'''
    found, left = X.sentences_of(src)
    assert {"Being built", "Done", "Saved: the old one is kept", "Clear attempts?", "Nothing is lost.", "Clear",
            "Keep them", "What each part does", "Your projects", "It works", "It doesn't", "Write here", "The idea",
            "{n} for you", "Cost:"} <= found
    assert not {"card wide", "#/p/x", "x-y", "·", "section", "x"} & found
    assert not any("margin" in s for s in found)
    assert sorted((s.tok.kind, s.joined) for s in left) == [("str", True), ("tpl", False)]


def test_the_server_s_fixed_messages_are_in_the_table(tmp_path):
    p = tmp_path / "x.py"
    p.write_text('from .server import ApiError\nraise ApiError("Write your question first.")\n'
                 'raise ApiError(f"no {x}")\nW.t("About {usd} to read it.")\nfoo.t("not words")\n', encoding="utf-8")
    assert X.py_sentences(p) == {"Write your question first.", "About {usd} to read it."}


def test_the_english_table_has_every_sentence():
    sentences, _ = X.extract()
    table = json.loads(X.TABLE.read_text(encoding="utf-8"))
    missing = [s for s in sentences if s not in table]
    assert not missing, f"{len(missing)} sentences aren't in en-GB.json: run python tools/words_extract.py"
    assert all(table[k] == k for k in table if not k.startswith("@"))


def test_the_ratchet_the_count_not_through_the_table_never_rises():
    _, left = X.extract()
    n = X.not_through(left)
    assert n <= NOT_THROUGH_LIMIT, (f"{n} sentences reach the screen without the language table (was "
                                    f"{NOT_THROUGH_LIMIT}). Use t(\"… {{name}} …\", {{ name }}) instead of a template "
                                    "string, or run python tools/words_sweep.py")


# -- the sweep: five made-up modules, byte for byte ------------------------------------------------------------
MODULES = {
    "one.js": (
        'import { h } from "./core.js";\nexport const a = (n) => h("p", {}, `${n} for you`);\n',
        'import { h } from "./core.js";\nimport { t } from "./words.js";\n'
        'export const a = (n) => h("p", {}, t("{n} for you", { n }));\n'),
    "two.js": (
        'import * as words from "./words.js";\nimport { h } from "./core.js";\n'
        'export const b = (p) => h("a", { title: `Open ${p.name} in its folder`, href: `#/p/${p.id}` }, p.name);\n',
        'import * as words from "./words.js";\nimport { h } from "./core.js";\n'
        'export const b = (p) => h("a", { title: words.t("Open {name} in its folder", { name: p.name }), '
        'href: `#/p/${p.id}` }, p.name);\n'),
    "three.js": (
        'import { h, toast } from "./core.js";\nconst t = 3;\n'
        'export function c(x) { toast(`Saved ${x.count} of ${x.total}: "${x.title.trim()}"`); return t; }\n',
        'import { h, toast } from "./core.js";\nimport { t as wt } from "./words.js";\nconst t = 3;\n'
        'export function c(x) { toast(wt("Saved {count} of {total}: \\"{v1}\\"", { count: x.count, total: x.total, '
        'v1: x.title.trim() })); return t; }\n'),
    "four.js": (
        'import { h } from "./core.js";\nimport { t } from "./words.js";\n'
        'export const d = (s) => h("p", {}, s.ok ? `${s.n} done` : "None", ` · ${s.a.n} and ${s.b.n}`, `{${s.x}}`);\n',
        'import { h } from "./core.js";\nimport { t } from "./words.js";\n'
        'export const d = (s) => h("p", {}, s.ok ? t("{n} done", { n: s.n }) : "None", t(" · {n} and {n2}", '
        '{ n: s.a.n, n2: s.b.n }), `{${s.x}}`);\n'),
    "five.js": (
        'import { h } from "./core.js";\nconst url = `/api/x?${q}`;\nexport const e = () => h("p", {}, `${a} · ${b}`, '
        '"Cost: " + `${c} dollars`);\n',
        None),  # nothing to turn: a path, no words, and joined text (counted, not turned)
}


def test_the_sweep_rewrites_five_made_up_modules_byte_for_byte():
    for name, (src, want) in MODULES.items():
        out, n = SW.sweep_text(src)
        assert out == (want if want is not None else src), name
        assert n == (0 if want is None else out.count("t(\"") + out.count("t(' ")), name


@pytest.mark.skipif(not shutil.which("node"), reason="Node isn't installed")
def test_the_swept_modules_are_still_good_javascript(tmp_path):
    for name, (src, want) in MODULES.items():
        p = tmp_path / name.replace(".js", ".mjs")
        p.write_text(SW.sweep_text(src)[0], encoding="utf-8")
        out = subprocess.run([shutil.which("node"), "--check", str(p)], capture_output=True, text=True)
        assert out.returncode == 0, (name, out.stderr)


def test_the_swept_sentences_are_found_as_keys():
    out, _ = SW.sweep_text(MODULES["three.js"][0])
    found, left = X.sentences_of(out)
    assert 'Saved {count} of {total}: "{v1}"' in found and not left


# -- left and right into logical properties --------------------------------------------------------------------
def test_left_and_right_become_logical_properties_but_the_ring_s_centre_stays():
    css = (".a { margin-left: 4px; padding-right: 2px; text-align: left; }\n.b { position: absolute; right: 0; }\n"
           ".ring-disc { left: 50%; transform: translate(-50%, -50%); }\n.c { padding: 6px 10px 6px 0; }\n"
           ".d { border-left: 3px solid red; border-left-color: blue; }")
    out, n = SW.logical_css(css)
    assert out == (".a { margin-inline-start: 4px; padding-inline-end: 2px; text-align: start; }\n"
                   ".b { position: absolute; inset-inline-end: 0; }\n"
                   ".ring-disc { left: 50%; transform: translate(-50%, -50%); }\n"
                   ".c { padding-block: 6px; padding-inline: 0 10px; }\n"
                   ".d { border-inline-start: 3px solid red; border-inline-start-color: blue; }")
    assert n == 4


def test_a_module_s_own_styles_turn_but_its_code_does_not():
    src = 'const CSS = `.x { margin-left: 2px; }`;\nconst box = { left: 3, right: 4 };\nel.style.left = "4px";\n'
    out, n = SW.logical_js(src)
    assert n == 1 and out == ('const CSS = `.x { margin-inline-start: 2px; }`;\nconst box = { left: 3, right: 4 };\n'
                              'el.style.left = "4px";\n')
