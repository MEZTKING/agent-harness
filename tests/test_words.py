"""The app in the owner's language (words.py, words.js, ui/wordsapi.py).

Made-up tables in a made-up app home; the page code runs under Node with a tiny stand-in for the page. British
English is the default and needs no table: with it nothing is looked up and the page is exactly as it was.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from roundtable import words as W
from roundtable.ui import server

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/roundtable/ui/static"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="Node isn't installed")

AR = {"@meta": {"by": "model", "model": "a/made-up", "name": "Arabic", "own_name": "العربية", "rtl": True},
      "Approve the plan": "وافق على الخطة",
      "Done": "تم",
      "{n} tasks": {"zero": "لا مهام", "one": "مهمة واحدة", "two": "مهمتان", "few": "{n} مهام", "many": "{n} مهمة",
                    "other": "{n} من المهام"},
      "Hello {name}": "مرحبا {name}",
      "Darkness Harness is ready": "Darkness Harness جاهز",
      "Translated by a model; some words may be off. Tell me and I'll fix them.": "ترجمة آلية."}
JA = {"@meta": {"by": "model", "name": "Japanese", "own_name": "日本語"},
      "{n} tasks": {"other": "{n} 件のタスク"}, "Done": "完了"}


@pytest.fixture
def tables(tmp_path, monkeypatch):
    """A shipped Arabic and Japanese table (in a made-up static folder) and the made-up app home."""
    lang = tmp_path / "lang"
    lang.mkdir()
    (lang / "en-GB.json").write_text(json.dumps({"@meta": {"by": "person"}, "Done": "Done"}), encoding="utf-8")
    (lang / "ar.json").write_text(json.dumps(AR, ensure_ascii=False), encoding="utf-8")
    (lang / "ja.json").write_text(json.dumps(JA, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(W, "STATIC_LANG", lang)
    return lang


# -- Python ----------------------------------------------------------------------------------------------------
def test_english_is_the_default_and_looks_nothing_up(tables):
    assert W.language(None) == "en-GB" and W.catalogue("en-GB") == {}
    assert W.t("Done") == "Done" and W.t("Hello {name}", name="Sam") == "Hello Sam"
    assert W.plural(1, "{n} task", "{n} tasks") == "1 task" and W.plural(3, "{n} task", "{n} tasks") == "3 tasks"


def test_t_swaps_a_known_sentence_and_leaves_an_unknown_one(tables):
    assert W.t("Approve the plan", "ar") == "وافق على الخطة"
    assert W.t("Something new", "ar") == "Something new"
    assert W.t("Hello {name}", "ar", name="Sam") == "مرحبا Sam"
    assert W.t("  Done ", "ar") == "  تم "  # the spaces around it are kept


def test_plurals_for_arabic_six_forms_and_japanese_one(tables):
    got = {n: W.t("{n} tasks", "ar", n=n) for n in (0, 1, 2, 3, 11, 100)}
    assert got == {0: "لا مهام", 1: "مهمة واحدة", 2: "مهمتان", 3: "3 مهام", 11: "11 مهمة", 100: "100 من المهام"}
    assert W.t("{n} tasks", "ja", n=1) == "1 件のタスク" and W.t("{n} tasks", "ja", n=5) == "5 件のタスク"
    assert [W.plural_category("ru", n) for n in (1, 3, 5, 21)] == ["one", "few", "many", "one"]


def test_the_chosen_language_its_direction_and_the_label(tables):
    assert W.available()[:3] == ["en-GB", "ar", "ja"]
    W.save_settings(lang="ar")
    assert W.language(None) == "ar" and W.t("Done") == "تم"
    v = W.view()
    assert v["dir"] == "rtl" and v["lang"] == "ar" and v["by_model"] and v["label"] == "ترجمة آلية."
    assert {"code": "ja", "name": "Japanese", "own_name": "日本語", "rtl": False, "by_model": True} in v["langs"]
    W.save_settings(lang="en-GB")
    v = W.view()
    assert v["dir"] == "ltr" and v["table"] == {} and v["label"] == ""


def test_a_language_with_no_table_falls_back_to_english(tables):
    W.save_settings(lang="ko")
    assert W.language(None) == "en-GB"


def test_the_owners_fixes_win_over_the_shipped_table(tables):
    W.fix("ar", "Done", "انتهى")
    assert W.t("Done", "ar") == "انتهى" and W.view("ar")["fixes"] == 1
    W.fix("ar", "Done", "")
    assert W.t("Done", "ar") == "تم"


def test_a_table_added_in_the_app_lives_in_the_data_folder(tables):
    d = W.data_lang_dir()
    d.mkdir(parents=True)
    (d / "x-welsh.json").write_text(json.dumps({"@meta": {"by": "model", "name": "Welsh", "own_name": "Cymraeg"},
                                                "Done": "Wedi gorffen"}), encoding="utf-8")
    assert "x-welsh" in W.available() and W.t("Done", "x-welsh") == "Wedi gorffen" and not W.rtl("x-welsh")


def test_problems_finds_lost_holes_empty_sentences_and_a_translated_name():
    assert W.problems(AR) == []
    bad = {"Hello {name}": "مرحبا", "Done": "", "Darkness Harness is ready": "الظلام جاهز",
           "{n} tasks": {"one": "مهمة", "other": "{n} مهام"}}
    found = W.problems(bad)
    assert len(found) == 3 and any("holes" in p for p in found) and any("empty" in p for p in found)
    assert any("name" in p for p in found)  # the plural "one" form may drop {n}: that one is fine


# -- the routes --------------------------------------------------------------------------------------------------
def _app(monkeypatch):
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "wordsapi"))
    return server.UIApp.__new__(server.UIApp)


def test_the_routes_choose_a_language_and_fix_a_word(tables, monkeypatch):
    from roundtable.ui import wordsapi

    app = _app(monkeypatch)
    assert {("GET", "/api/words"), ("POST", "/api/translate")} <= set(wordsapi.routes(app))
    assert wordsapi.words_get(app)["lang"] == "en-GB"
    with pytest.raises(server.ApiError, match="Choose another language first"):
        wordsapi.fix(app, {"english": "Done", "text": "x"})
    with pytest.raises(server.ApiError, match="isn't in the app yet"):
        wordsapi.set_language(app, {"lang": "ko"})
    out = wordsapi.set_language(app, {"lang": "ar"})
    assert out["dir"] == "rtl" and out["table"]["Done"] == "تم"
    with pytest.raises(server.ApiError, match="curly brackets"):
        wordsapi.fix(app, {"english": "Hello {name}", "text": "مرحبا"})
    assert wordsapi.fix(app, {"english": "Done", "text": "انتهى"})["table"]["Done"] == "انتهى"
    with pytest.raises(server.ApiError, match="between"):
        wordsapi.settings(app, {"allowance_usd": 9})
    assert wordsapi.settings(app, {"auto_reasons": True, "allowance_usd": 0.2})["auto_reasons"] is True


def test_the_brand_is_never_in_the_english_table():
    table = json.loads((STATIC / "lang/en-GB.json").read_text(encoding="utf-8"))
    assert "Darkness Harness" not in table and "Darkness" not in table
    assert table["@meta"]["by"] == "person"


def test_every_shipped_table_keeps_every_hole_of_its_english():
    """Run over the real files: a bad translation fails CI."""
    for p in sorted((STATIC / "lang").glob("*.json")):
        table = json.loads(p.read_text(encoding="utf-8"))
        assert W.problems(table) == [], p.name
        assert p.stem == "en-GB" or table.get("@meta", {}).get("by") in ("model", "person"), p.name


# -- the page code ------------------------------------------------------------------------------------------------
SHIM = r"""
globalThis.Node = class {};
class N extends Node { constructor(tag){ super(); this.tagName=tag.toUpperCase(); this.children=[]; this.attrs={}; this.className=""; this.title=""; }
  setAttribute(k,v){ this.attrs[k]=String(v); } getAttribute(k){ return this.attrs[k] ?? null; } removeAttribute(k){ delete this.attrs[k]; }
  addEventListener(){} append(...k){ this.children.push(...k); } replaceChildren(...k){ this.children=k; }
  get textContent(){ return this.children.map(c => c instanceof N ? c.textContent : c.data).join(""); } }
class T extends Node { constructor(d){ super(); this.data=String(d); } }
const root = new N("html"); root.lang = "en-GB"; root.dir = "";
root.removeAttribute = function(k){ if (k === "dir") this.dir = ""; };
globalThis.document = { createElement: (t) => new N(t), createTextNode: (d) => new T(d), getElementById: () => null,
  head: new N("head"), documentElement: root };
globalThis.window = { addEventListener(){}, dispatchEvent(){} };
globalThis.location = { hostname: "127.0.0.1", port: "8765", protocol: "http:", hash: "" };
"""


def _node(tmp_path, body: str) -> dict:
    (tmp_path / "shim.mjs").write_text(SHIM, encoding="utf-8")
    probe = tmp_path / "probe.mjs"
    probe.write_text('import "./shim.mjs";\nconst S = process.argv[2];\n'
                     'const words = await import(S + "/words.js");\nconst core = await import(S + "/core.js");\n'
                     + body, encoding="utf-8")
    out = subprocess.run([NODE, str(probe), STATIC.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_auto_swaps_known_sentences_and_never_touches_raw_or_kept_text(tmp_path):
    got = _node(tmp_path, f"""
const T = {json.dumps({k: v for k, v in AR.items() if not k.startswith('@')}, ensure_ascii=False)};
const before = core.h("p", {{ title: "Done" }}, "Done").textContent;
words.use("ar", T);
const swapped = core.h("button", {{ title: "Approve the plan", "aria-label": "Done" }}, "Approve the plan");
const raw = core.h("h2", {{ raw: true, title: "Done" }}, "Done");
const kept = core.h("h2", {{}}, words.keep("Done"));
const unknown = core.h("p", {{}}, "Something new");
const filled = core.fill(core.h("div"), "Done", 3);
console.log(JSON.stringify({{ before, swapped: [swapped.textContent, swapped.attrs.title, swapped.attrs["aria-label"]],
  raw: [raw.textContent, raw.attrs.title], kept: kept.textContent, unknown: unknown.textContent,
  filled: filled.textContent, spaced: words.auto(" Done "), dir: words.dir(), lang: words.lang() }}));
""")
    assert got["before"] == "Done"
    assert got["swapped"] == ["وافق على الخطة", "وافق على الخطة", "تم"]
    assert got["raw"] == ["Done", "Done"] and got["kept"] == "Done"  # a project called "Done" keeps its name
    assert got["unknown"] == "Something new" and got["filled"] == "تم3" and got["spaced"] == " تم "
    assert got["dir"] == "rtl" and got["lang"] == "ar"


@needs_node
def test_t_fills_holes_and_plurals_in_english_arabic_and_japanese(tmp_path):
    got = _node(tmp_path, f"""
const forms = {{ one: "{{n}} task", other: "{{n}} tasks" }};
const en = [words.t(forms, {{ n: 1 }}), words.t(forms, {{ n: 4 }}), words.t("Hello {{name}}", {{ name: "Sam" }}),
  words.t("{{a}} of {{b}}", {{ a: 1 }})];
words.use("ar", {json.dumps({k: v for k, v in AR.items() if not k.startswith('@')}, ensure_ascii=False)});
const ar = [0, 1, 2, 3, 11, 100].map((n) => words.t(forms, {{ n }}));
const hello = words.t("Hello {{name}}", {{ name: "Sam" }});
words.use("ja", {json.dumps({k: v for k, v in JA.items() if not k.startswith('@')}, ensure_ascii=False)});
const ja = [1, 5].map((n) => words.t(forms, {{ n }}));
console.log(JSON.stringify({{ en, ar, hello, ja, dir: words.dir() }}));
""")
    assert got["en"] == ["1 task", "4 tasks", "Hello Sam", "1 of {b}"]
    assert got["ar"] == ["لا مهام", "مهمة واحدة", "مهمتان", "3 مهام", "11 مهمة", "100 من المهام"]
    assert got["hello"] == "مرحبا Sam" and got["ja"] == ["1 件のタスク", "5 件のタスク"] and got["dir"] == "ltr"


@needs_node
def test_load_sets_lang_and_dir_for_arabic_and_unsets_them_for_english(tmp_path):
    got = _node(tmp_path, """
const answer = (body) => async () => ({ ok: true, json: async () => body });
globalThis.fetch = answer({ lang: "ar", dir: "rtl", locale: "ar", table: { Done: "تم" } });
await words.load();
const ar = [document.documentElement.lang, document.documentElement.dir, words.auto("Done"), words.locale()];
globalThis.fetch = answer({ lang: "en-GB", dir: "ltr", locale: "en-GB", table: {} });
await words.load();
const en = [document.documentElement.lang, document.documentElement.dir, words.auto("Done")];
globalThis.fetch = async () => { throw new Error("offline"); };
await words.load();
console.log(JSON.stringify({ ar, en, offline: words.lang() }));
""")
    assert got["ar"] == ["ar", "rtl", "تم", "ar"]
    assert got["en"] == ["en-GB", "", "Done"] and got["offline"] == "en-GB"


@needs_node
def test_english_with_the_table_loaded_is_byte_for_byte_the_page_it_was(tmp_path):
    """Three pages' worth of words (a card, a page heading, a dialog's parts) drawn before and after words.load()
    answered British English: the same text and attributes."""
    got = _node(tmp_path, """
const draw = () => {
  const a = core.card("Language", core.h("p", { title: "The language the app is written in" }, "Looking…"));
  const b = core.page("Settings", "Keys, the hub, backups, updates and more", core.h("button", { "aria-label": "Done" }, "Done"));
  const c = core.h("div", {}, core.h("input", { placeholder: "Your wording" }), core.money(0.5), core.taskPill("done"));
  const dump = (n) => n.tagName ? [n.tagName, n.attrs, n.title, n.className, n.children.map(dump)] : n.data;
  return JSON.stringify([a, b, c].map(dump));
};
const before = draw();
globalThis.fetch = async () => ({ ok: true, json: async () => ({ lang: "en-GB", dir: "ltr", locale: "en-GB", table: { Done: "NO" } }) });
await words.load();
console.log(JSON.stringify({ same: before === draw() }));
""")
    assert got["same"]


def test_the_house_style_line_asks_for_the_owners_language_and_nothing_in_english(tables):
    assert W.owner_line() == ""
    W.save_settings(lang="ar")
    line = W.owner_line()
    assert line.startswith("Write to the owner in Arabic") and "code" in line and "Darkness Harness" in line
