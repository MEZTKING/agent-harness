"""What models and the harness write as they go, read in the owner's language (wave 9).

One model call (the project's cheapest allowed chat model, ``makers.allowed`` obeyed), priced first, kept by the
hash of the text in ``.harness/translations/`` so it is paid for once. Reasons translated without a tap (``why``
starting with ``auto``) are off unless the owner switched them on, and stop at their own small daily allowance.
Nothing is translated for a project whose allowed makers leave no model.

The same file makes whole tables (``table``): the eleven the app ships, or a language the owner adds in Settings.
Each batch is checked: every ``{hole}`` must survive, no sentence may come back empty, and a batch that comes
back mostly unchanged is refused. From the command line, price first::

    python -m roundtable.translate --config harness.yaml --lang ar             # the price, nothing spent
    python -m roundtable.translate --config harness.yaml --lang ar --confirm   # makes ui/static/lang/ar.json
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import threading
from pathlib import Path
from typing import Any, Callable

from . import words as W

SYSTEM = ("You translate short pieces of a desktop app and what its AI helpers wrote for its owner, from British "
          "English into {language}. Keep the meaning, keep it plain and short. Keep every {{hole}} in curly brackets "
          "exactly as it is, untranslated. Never translate these names: {keep}. Keep code, file paths, model names "
          "and numbers as they are. Call submit_translation once.")

BATCH = 60
_LOCK = threading.Lock()


class TranslateError(Exception):
    """Plain words for why nothing was translated (and nothing was spent)."""


# -- the model ---------------------------------------------------------------------------------------------------
def _chat_models(cfg: Any) -> list[Any]:
    out: list[Any] = []
    for r in (getattr(cfg, "roles", {}) or {}).values():
        if getattr(r, "kind", "chat") == "chat":
            out += [m for m in r.models if m not in out]
    return out


def _unit_price(cfg: Any, m: Any) -> float:
    from .providers.base import Usage

    try:
        c = cfg.cost(m, Usage(input_tokens=1000, output_tokens=1000))
    except Exception:  # noqa: BLE001
        c = None
    return math.inf if c is None else c


def _values(root: Any) -> dict[str, Any] | None:
    if root is None:
        return None
    from .harness import projectsettings as ps

    try:
        st = ps.load(Path(root))
    except Exception:  # noqa: BLE001
        return {"makers_allowed": ["(settings with a mistake)"]}
    return {"makers_allowed": ["(settings with a mistake)"]} if st.errors else st.values


def model_for(cfg: Any, root: Any = None) -> Any:
    """The translator: ``translate.model`` if allowed, else the cheapest chat model the project allows (None: none)."""
    from .harness import makers
    from .harness.config import ModelRef, section

    if cfg is None:
        return None
    values = _values(root)
    chosen = str(section(cfg, "translate").get("model") or "").strip()
    if chosen:
        try:
            ref = ModelRef.parse(chosen)
            if makers.allowed(values, ref):
                return ref
        except ValueError:
            pass
    models = [m for m in _chat_models(cfg) if makers.allowed(values, m)]
    return min(models, key=lambda m: _unit_price(cfg, m)) if models else None


def _language_name(lang: str) -> str:
    m = W.meta(lang)
    return str(m.get("name") or lang)


def _cost(cfg: Any, ref: Any, chars_in: int, chars_out: int) -> float | None:
    from .providers.base import Usage

    try:
        return cfg.cost(ref, Usage(input_tokens=chars_in // 3 + 250, output_tokens=chars_out // 2 + 60))
    except Exception:  # noqa: BLE001
        return None


def price(cfg, text: str, lang: str) -> float | None:
    """What translating ``text`` into ``lang`` would cost, in dollars, without spending (None: can't tell, or no
    model). British English and empty text cost nothing."""
    if not str(text or "").strip() or lang == W.DEFAULT:
        return 0.0
    ref = model_for(cfg)
    if ref is None:
        return None
    c = _cost(cfg, ref, len(SYSTEM) + len(text), len(text))
    return None if c is None else round(c, 6)


# -- the cache and the allowance ---------------------------------------------------------------------------------
def _key(text: str, lang: str) -> str:
    return hashlib.sha256(f"{lang}\n{text}".encode("utf-8")).hexdigest()[:32]


def cache_dir(root: str | Path) -> Path:
    return Path(root) / ".harness" / "translations"


def cached(root: str | Path, text: str, lang: str) -> str | None:
    try:
        row = json.loads((cache_dir(root) / f"{_key(text, lang)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    got = row.get("text") if isinstance(row, dict) else None
    return got if isinstance(got, str) and got else None


def _spend_file() -> Path:
    return W._home() / "translate-spend.jsonl"


def _today() -> str:
    return _dt.date.today().isoformat()


def spent_today() -> float:
    """What translations made without a tap cost today, in dollars."""
    total = 0.0
    try:
        lines = _spend_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("day") == _today() and row.get("auto"):
            total += float(row.get("usd") or 0)
    return round(total, 6)


def _note_spend(usd: float, why: str, root: Any, auto: bool) -> None:
    p = _spend_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"day": _today(), "usd": round(usd, 6), "why": why[:40], "project": Path(root).name if root else "",
           "auto": auto}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def is_auto(why: str) -> bool:
    return str(why or "").strip().lower().startswith("auto")


# -- one piece -------------------------------------------------------------------------------------------------
def _call(cfg: Any, ref: Any, lang: str, prompt: str, schema: dict[str, Any], limit: float, role: str,
          on_use: Any = None) -> tuple[dict[str, Any], float]:
    from .harness.agent import Budget, run_agent
    from .harness.tools import Tool, Toolbox
    from .providers.base import ToolSpec

    got: dict[str, Any] = {}

    def submit(args: dict[str, Any]) -> str:
        got.update(args)
        return "translation recorded"

    box = Toolbox()
    box.add(Tool(ToolSpec("submit_translation", "Give the translation.", schema), submit, terminal=True))
    system = SYSTEM.format(language=_language_name(lang), keep=", ".join(W.KEEP))
    res = run_agent(cfg, ref, system, prompt, box, Budget(limit, on_use=on_use), max_steps=3, max_tokens=4000,
                    require_terminal="submit_translation", role=role)
    return got, float(res.cost_usd or 0.0)


def _record_usage(ref: Any, use: Any, cost: Any, root: Any) -> None:
    from .harness import usage

    try:
        usage.record(usage.row_for(ref, use, cost, "(translate)", root or W._home()))
    except Exception:  # noqa: BLE001 - the ledger is a convenience; the spend file is the allowance's record
        pass


def words(cfg, root, text: str, lang: str, why: str) -> dict[str, Any]:
    """``{"text", "cached": bool, "usd"}``: ``text`` in ``lang``. Kept by its hash, so asked for again it is free.
    Raises :class:`TranslateError` (nothing spent) when no model may see the project, when reasons aren't to be
    translated without a tap, or when today's allowance for those is used up."""
    text = str(text or "")
    if not text.strip() or not lang or lang == W.DEFAULT or cfg is None:  # no harness set up: as it is
        return {"text": text, "cached": False, "usd": 0.0}
    if root is not None:
        hit = cached(root, text, lang)
        if hit is not None:
            return {"text": hit, "cached": True, "usd": 0.0}
    ref = model_for(cfg, root)
    if ref is None:
        raise TranslateError("No model this project allows can translate it. Allow a maker in the project's "
                             "settings, or read it in English.")
    estimate = _cost(cfg, ref, len(SYSTEM) + len(text), len(text))
    auto = is_auto(why)
    with _LOCK:
        if auto:
            s = W.load_settings()
            if not s["auto_reasons"]:
                raise TranslateError("Reasons aren't translated by themselves. Switch it on in Settings → Language, "
                                     "or tap Read in your language.")
            if spent_today() + (estimate or 0.0) > s["allowance_usd"]:
                raise TranslateError("Today's allowance for translating by itself is used up. Tap Read in your "
                                     "language to translate this one, or raise the allowance in Settings → Language.")
        schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
        limit = max(0.02, 3 * (estimate or 0.0))
        got, usd = _call(cfg, ref, lang, f"# Why it's being read\n{why}\n\n# The text\n{text}", schema, limit,
                         "(translate)", on_use=lambda r, use, cost, role: _record_usage(r, use, cost, root))
        _note_spend(usd, why, root, auto)
    out = str(got.get("text") or "").strip()
    if not out:
        raise TranslateError("The translation came back empty. Try again in a moment.")
    if root is not None:
        d = cache_dir(root)
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{_key(text, lang)}.json").write_text(json.dumps(
                {"text": out, "lang": lang, "why": why[:40], "model": str(ref), "usd": round(usd, 6),
                 "at": _dt.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return {"text": out, "cached": False, "usd": round(usd, 6)}


# -- whole tables ------------------------------------------------------------------------------------------------
def english() -> list[str]:
    """Every sentence of the English table (``ui/static/lang/en-GB.json``), in its order."""
    raw = W._read(W.STATIC_LANG / f"{W.DEFAULT}.json")
    return [k for k in raw if not k.startswith("@")]


def table_price(cfg: Any, sentences: list[str], lang: str) -> dict[str, Any]:
    """``{sentences, batches, usd, model}``: what a whole table would cost (``usd`` None: can't tell)."""
    ref = model_for(cfg)
    chars = sum(len(s) for s in sentences)
    batches = max(1, math.ceil(len(sentences) / BATCH)) if sentences else 0
    usd = None
    if ref is not None:
        from .providers.base import Usage

        # about 3.5 characters a token in, translations a third longer, and the numbered list's own words
        use = Usage(input_tokens=int((batches * (len(SYSTEM) + 400) + chars) / 3.5) + 4 * len(sentences),
                    output_tokens=int(chars * 1.33 / 3) + 10 * len(sentences))
        try:
            c = cfg.cost(ref, use)
        except Exception:  # noqa: BLE001
            c = None
        usd = None if c is None else round(c, 4)
    return {"sentences": len(sentences), "batches": batches, "usd": usd, "model": str(ref or "")}


def check_batch(asked: list[str], got: dict[str, Any]) -> list[str]:
    """What is wrong with one batch ([] when fine)."""
    out = W.problems({k: got.get(k) or "" for k in asked})
    alpha = [k for k in asked if re.search(r"[A-Za-z]{3}", k)]
    same = [k for k in alpha if got.get(k) == k]
    if len(alpha) >= 8 and len(same) > len(alpha) // 2:
        out.append(f"{len(same)} of {len(alpha)} came back in English")
    return out


def table(cfg: Any, lang: str, sentences: list[str] | None = None, confirm: bool = False,
          log: Callable[[str], None] = print, max_usd: float = 1.0, by: str = "model") -> dict[str, Any]:
    """Translate the English table into ``lang``. Without ``confirm``: the price only. With it: batches, each
    checked (a batch with a problem is asked once more, then left English), stopping at ``max_usd``. Returns
    ``{table, usd, left: [sentence], problems: [str], price}``; ``table`` carries its ``@meta``."""
    sentences = english() if sentences is None else list(sentences)
    quote = table_price(cfg, sentences, lang)
    if not confirm:
        return {"table": {}, "usd": 0.0, "left": sentences, "problems": [], "price": quote}
    ref = model_for(cfg)
    if ref is None:
        raise TranslateError("No chat model is set up to translate with. Add one in Models.")
    m = W.meta(lang)
    done: dict[str, Any] = {}
    spent, left, issues = 0.0, [], []
    for start in range(0, len(sentences), BATCH):
        batch = sentences[start:start + BATCH]
        if spent >= max_usd:
            left += batch
            continue
        prompt = ("Translate each of these into the target language. Answer with items in the same order, each "
                  "with the number you were given.\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(batch, 1)))
        schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
            "type": "object", "required": ["n", "text"], "properties": {"n": {"type": "integer"},
                                                                        "text": {"type": "string"}}}}}}
        got: dict[str, Any] = {}
        for attempt in range(2):
            args, usd = _call(cfg, ref, lang, prompt, schema, max(0.05, max_usd - spent), "(translate)")
            spent += usd
            got = {}
            for it in args.get("items") or []:
                try:
                    got[batch[int(it.get("n")) - 1]] = str(it.get("text") or "")
                except (TypeError, ValueError, IndexError):
                    continue
            bad = check_batch(batch, got)
            if not bad:
                break
            log(f"batch {start // BATCH + 1}: {bad[0]}" + (" (asking again)" if attempt == 0 else " (left English)"))
            if attempt == 1:
                issues += bad
                got = {k: v for k, v in got.items() if not W.problems({k: v})}
        done.update({k: v for k, v in got.items() if v and v.strip()})
        left += [k for k in batch if k not in done]
        log(f"batch {start // BATCH + 1} of {quote['batches']}: {len(done)} so far, ${spent:.4f}")
    out = {"@meta": {"by": by, "model": str(ref), "made": _dt.date.today().isoformat(),
                     "name": m.get("name", lang), "own_name": m.get("own_name", lang), "rtl": W.rtl(lang)},
           **done}
    return {"table": out, "usd": round(spent, 6), "left": left, "problems": issues, "price": quote}


def save_table(path: str | Path, tbl: dict[str, Any]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tbl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .harness.config import load_config

    ap = argparse.ArgumentParser(description="Make a language table, price first.")
    ap.add_argument("--config", required=True, help="the harness.yaml whose models translate")
    ap.add_argument("--lang", required=True, action="append", help="a language code (again for more)")
    ap.add_argument("--confirm", action="store_true", help="spend: without it only the price is shown")
    ap.add_argument("--max-usd", type=float, default=1.0, help="stop once this much was spent (all languages)")
    ap.add_argument("--out", default=str(W.STATIC_LANG), help="where the tables go")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    spent = 0.0
    for lang in a.lang:
        r = table(cfg, lang, confirm=a.confirm, max_usd=max(0.0, a.max_usd - spent))
        q = r["price"]
        if not a.confirm:
            print(f"{lang}: {q['sentences']} sentences in {q['batches']} batches on {q['model'] or 'no model'}: "
                  f"about {'$%.4f' % q['usd'] if q['usd'] is not None else 'an unknown price'}")
            continue
        spent += r["usd"]
        save_table(Path(a.out) / f"{lang}.json", r["table"])
        print(f"{lang}: {len(r['table']) - 1} translated, {len(r['left'])} left English, ${r['usd']:.4f}"
              + (f"; problems: {r['problems'][:3]}" if r["problems"] else ""))
    if a.confirm:
        print(f"spent ${spent:.4f} in all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
