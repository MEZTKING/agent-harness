"""The app in the owner's language, and what models write read in it (words.py, translate.py).

    GET  /api/words                 {lang, dir, locale, table, langs: [{code, name, own_name, rtl, by_model}],
                                     label, by_model, fixes, auto_reasons, allowance_usd, spent_today}
    POST /api/words/language        {lang}                       -> the same as GET
    POST /api/words/fix             {english, text}              ("" puts the table's wording back) -> GET
    POST /api/words/settings        {auto_reasons?, allowance_usd?} -> GET
    POST /api/words/add             {name, confirm?}: without confirm the price first, nothing sent; with it a
                                    background job that makes the table in the app's data folder
    POST /api/translate             {path, text, why, confirm?}: without confirm {price_usd, cached, words};
                                    with it {text, cached, usd, words}

The phone may call ``GET /api/words`` and ``POST /api/translate`` (price first; the same allowance). Choosing the
language, fixing a word and adding a language stay on the PC.
"""

from __future__ import annotations

import re
from typing import Any

from .. import translate as tr
from .. import words as W

MAX_TEXT = 6000


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/words"): lambda q: words_get(app),
        ("POST", "/api/words/language"): lambda body: set_language(app, body),
        ("POST", "/api/words/fix"): lambda body: fix(app, body),
        ("POST", "/api/words/settings"): lambda body: settings(app, body),
        ("POST", "/api/words/add"): lambda body: add(app, body),
        ("POST", "/api/translate"): lambda body: translate(app, body),
    }


def words_get(app) -> dict[str, Any]:
    out = W.view()
    out["spent_today"] = tr.spent_today()
    return out


def set_language(app, body) -> dict[str, Any]:
    from .server import ApiError

    lang = str(body.get("lang") or "").strip()
    if lang not in W.available():
        raise ApiError("That language isn't in the app yet. Choose another, or add it with Add a language.")
    W.save_settings(lang=lang)
    return words_get(app)


def fix(app, body) -> dict[str, Any]:
    from .server import ApiError

    lang = W.language(app)
    english = str(body.get("english") or "")
    text = str(body.get("text") or "")
    if lang == W.DEFAULT:
        raise ApiError("British English is the app's own wording. Choose another language first.")
    if not english.strip() or len(english) > 2000 or len(text) > 2000:
        raise ApiError("Choose the sentence to change, and write your wording in a line or two.")
    if text.strip() and W.holes(text) != W.holes(english):
        missing = sorted(W.holes(english) - W.holes(text))
        raise ApiError("Keep the parts in curly brackets as they are" +
                       (f": {', '.join('{' + h + '}' for h in missing)}." if missing else "."))
    W.fix(lang, english, text)
    return words_get(app)


def settings(app, body) -> dict[str, Any]:
    from .server import ApiError

    changes: dict[str, Any] = {}
    if "auto_reasons" in body:
        changes["auto_reasons"] = bool(body.get("auto_reasons"))
    if "allowance_usd" in body:
        try:
            v = float(body.get("allowance_usd"))
        except (TypeError, ValueError):
            raise ApiError("Write the allowance as a number of dollars, like 0.10.") from None
        if not 0 <= v <= 5:
            raise ApiError("Keep the daily allowance between $0 and $5.")
        changes["allowance_usd"] = v
    W.save_settings(**changes)
    return words_get(app)


def _code_for(name: str) -> str:
    n = name.strip().lower()
    for code, m in W.LANGS.items():
        if n in (code.lower(), str(m["name"]).lower(), str(m["own_name"]).lower()):
            return code
    slug = re.sub(r"[^a-z]+", "-", n).strip("-")[:24]
    return f"x-{slug}" if slug else ""


def add(app, body) -> dict[str, Any]:
    from .server import ApiError

    name = str(body.get("name") or "").strip()
    code = _code_for(name)
    if not code or len(name) > 40:
        raise ApiError("Write the language's name, like Welsh or Italian.")
    if code == W.DEFAULT:
        raise ApiError("British English is already the app's own language.")
    cfg = app.need_cfg()
    sentences = tr.english()
    quote = tr.table_price(cfg, sentences, code)
    if quote["usd"] is None:
        raise ApiError("No chat model with a known price is set up to translate with. Add one in Models first.")
    if not body.get("confirm"):
        return {"code": code, "price": quote, "words": W.t(
            "About {usd} to translate {n} sentences into {name}.", usd=f"${quote['usd']:.2f}", n=quote["sentences"],
            name=name)}
    if code not in W.LANGS:  # a language the app didn't know: its name, as the owner wrote it
        W.LANGS.setdefault(code, {"name": name, "own_name": name, "rtl": False})

    def run(job):
        r = tr.table(cfg, code, sentences, confirm=True, log=job.line, max_usd=max(0.05, 2 * quote["usd"]))
        r["table"]["@meta"]["name"] = W.LANGS[code]["name"]
        tr.save_table(W.data_lang_dir() / f"{code}.json", r["table"])
        job.line(f"{len(r['table']) - 1} sentences translated, {len(r['left'])} left in English, ${r['usd']:.4f}")
        return {"code": code, "usd": r["usd"], "left": len(r["left"])}

    return {"job": app.jobs.start("words", f"translate the app into {name}", run, target="words").view(),
            "code": code, "price": quote}


def translate(app, body) -> dict[str, Any]:
    from .server import ApiError

    text = str(body.get("text") or "")
    why = str(body.get("why") or "a piece of text")[:60]
    if not text.strip():
        raise ApiError("There's nothing to translate.")
    if len(text) > MAX_TEXT:
        raise ApiError("That's too long to translate in one go. Open it and translate a part.")
    lang = str(body.get("lang") or W.language(app))
    if lang == W.DEFAULT:
        return {"text": text, "cached": False, "usd": 0.0, "price_usd": 0.0, "words": ""}
    cfg = app.need_cfg()
    root = app.project(cfg, str(body.get("path") or "")).root
    hit = tr.cached(root, text, lang)
    name = W.meta(lang).get("name", lang)
    if hit is not None:
        return {"text": hit, "cached": True, "usd": 0.0, "price_usd": 0.0, "words": W.t("Read before; free.")}
    ref = tr.model_for(cfg, root)
    if ref is None:
        raise ApiError(W.t("No model this project allows can translate it. Allow a maker in the project's settings, "
                           "or read it in English."))
    est = tr._cost(cfg, ref, len(tr.SYSTEM) + len(text), len(text))
    if not body.get("confirm") and not tr.is_auto(why):
        return {"text": "", "cached": False, "usd": 0.0, "price_usd": est,
                "words": W.t("About {usd} to read it in {name}.",
                             usd=f"${est:.4f}" if est is not None else "an unknown price", name=name)}
    try:
        out = tr.words(cfg, root, text, lang, why)
    except tr.TranslateError as e:
        raise ApiError(str(e)) from None
    return {**out, "price_usd": est, "words": W.t("Translated by a model; some words may be off.")}
