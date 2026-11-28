"""The office's pixel art: the quote, the sample sheet, then the rest, never past $10 (wave 9).

Every piece is in ``ui/static/office/manifest.json`` (its prompt, Retro Diffusion style, size and options), made
by Retro Diffusion, never drawn in code. The steps, each waiting for the one before:

1. ``quote(provider)``: ``check_cost`` for every piece (Retro Diffusion's own price check: it spends nothing),
   summed, with the sample sheet's share. Over ``TRIM_AT`` ($8, leaving $2 for second tries) the pieces the
   office can do without are left out, most dispensable first, and the quote says which.
2. ``make(provider, "sample", ...)``: the sample pieces (the wall, one agent's walk and work, the desk, the shelf
   and two bubbles), at most ``SAMPLE_CAP_USD`` a try, laid side by side on one sheet by Pillow (arranging finished
   pictures, not drawing). ``sample_ask`` is the one card the owner answers: Make the rest, Try the sample again,
   or Stop here. Both paid answers carry ``confirm``, so no timer and no autopilot can give them, and the card is
   answered on the PC only.
3. ``make(provider, "rest", ...)``: only after ``approve``. Every call is reserved first and settled with the real
   charge (``reserve`` / ``settle`` / ``release`` under one lock), against ``CAP_USD`` for everything ever spent
   in that spend file. A piece that would pass the cap is never asked for; a failed piece is tried once more.
   ``remake`` makes one piece again, priced, inside the same cap.

Where things are, for the app (``paths(app)``)::

    <app home>/office-art/office-art-spend.jsonl   one line per paid piece: {at, piece, stage, style, cost_usd}
    <app home>/office-art/office-art-state.json    {sample: {...}, approved, stopped, files: {id: name}, ...}
    <app home>/office-art/pieces/                  the pictures, and sample-sheet.png

The shipped art lives next to the manifest (``ui/static/office/``), made by the coordinator with the CLI.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from .core.models import utcnow

CAP_USD = 10.0
SAMPLE_CAP_USD = 1.5
TRIM_AT = 8.0  # the quote leaves $2 of the cap for second tries
MANIFEST = Path(__file__).parent / "ui" / "static" / "office" / "manifest.json"
STATE_NAME = "office-art-state.json"
SPEND_NAME = "office-art-spend.jsonl"
SHEET_NAME = "sample-sheet.png"
PICTURE_EXTS = ("png", "gif", "webp")
SHEET_GAP = 8
SHEET_BACK = (10, 10, 15, 255)  # the Eclipse near-black behind the laid-out pieces
# the least the view needs to open: the room, a desk and one figure that can walk and work
REQUIRED = ("wall", "floor", "desk")

_LOCK = threading.Lock()
_HELD: dict[str, dict[str, float]] = {}  # spend file -> {token: dollars held for a call not yet settled}


class OfficeArtError(ValueError):
    """A plain-words reason the office art can't go on (shown to the owner as it is)."""


class OfficeCapReached(OfficeArtError):
    """The piece would take the office art past its cap: it is not asked for."""


# -- the manifest --------------------------------------------------------------------------------------------------
def _doc(path: Path | None = None) -> dict[str, Any]:
    try:
        doc = json.loads((path or MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def manifest() -> list[dict[str, Any]]:
    """Every piece: ``{id, file, style, width, height, prompt, options, stage: "sample" | "rest"}`` (plus ``kind``,
    and where it applies ``sheet``, ``draw``, ``agent`` and ``trim``: higher is left out first when the quote is too
    dear; no ``trim`` means the office needs it)."""
    return [dict(p) for p in _doc().get("pieces") or [] if isinstance(p, dict) and p.get("id")]


def layout() -> dict[str, Any]:
    """The room, the props' places, the spots the figures stand at, and which pieces each figure and bubble uses."""
    return {k: v for k, v in _doc().items() if k != "pieces"}


def _piece(piece_id: str) -> dict[str, Any]:
    p = next((p for p in manifest() if p["id"] == piece_id), None)
    if p is None:
        raise OfficeArtError(f"There's no office piece called {piece_id!r}.")
    return p


def _opts(piece: dict[str, Any]) -> dict[str, Any]:
    return {"width": int(piece["width"]), "height": int(piece["height"]), **(piece.get("options") or {})}


# -- the quote ---------------------------------------------------------------------------------------------------
def _known_styles(provider) -> set[str] | None:
    fn = getattr(provider, "styles", None)
    if not callable(fn):
        return None
    try:
        return set(fn() or {})
    except Exception:  # noqa: BLE001 - the list couldn't be read: the price check says what's wrong
        return None


def _money(x: float) -> str:
    return f"${x:.2f}"


def quote(provider) -> dict[str, Any]:
    """``{"pieces": [{id, usd}], "sample_usd", "total_usd", "cap": 10.0}``; spends nothing.

    Also ``rest_usd``, ``left_out`` ([{id, usd, why}]: trimmed to stay under $8), ``problems`` ([{id, why}]: a style
    the service doesn't offer, or a price it couldn't give), ``ok`` and ``words`` (one plain sentence)."""
    out: dict[str, Any] = {"pieces": [], "sample_usd": 0.0, "rest_usd": 0.0, "total_usd": 0.0, "cap": CAP_USD,
                           "trim_at": TRIM_AT, "left_out": [], "problems": [], "ok": False}
    if provider is None or not callable(getattr(provider, "check_cost", None)):
        out["words"] = "Retro Diffusion isn't set up yet, so the office art can't be priced. Add its key in Models."
        return out
    known = _known_styles(provider)
    priced: list[dict[str, Any]] = []
    for p in manifest():
        if known is not None and p["style"] not in known:
            out["problems"].append({"id": p["id"], "why": f"Retro Diffusion doesn't offer the style {p['style']!r} any more."})
            continue
        try:
            usd = float(provider.check_cost(p["style"], p["prompt"], _opts(p)))
        except Exception as e:  # noqa: BLE001 - one price that can't be had: said, not guessed
            out["problems"].append({"id": p["id"], "why": f"Couldn't get its price ({str(e)[:160]})."})
            continue
        priced.append({"id": p["id"], "usd": round(usd, 4), "stage": p["stage"], "trim": p.get("trim")})
    # too dear: leave out the pieces the office can do without, the most dispensable group first
    total = sum(x["usd"] for x in priced)
    for level in sorted({x["trim"] for x in priced if x["trim"] is not None and x["stage"] == "rest"}, reverse=True):
        if total <= TRIM_AT:
            break
        for x in [x for x in priced if x["trim"] == level and x["stage"] == "rest"]:
            priced.remove(x)
            total -= x["usd"]
            out["left_out"].append({"id": x["id"], "usd": x["usd"], "why": "Left out to keep the whole under "
                                                                           f"{_money(TRIM_AT)}."})
    out["pieces"] = [{"id": x["id"], "usd": x["usd"], "stage": x["stage"]} for x in priced]
    out["sample_usd"] = round(sum(x["usd"] for x in priced if x["stage"] == "sample"), 4)
    out["total_usd"] = round(sum(x["usd"] for x in priced), 4)
    out["rest_usd"] = round(out["total_usd"] - out["sample_usd"], 4)
    missing_sample = [p["id"] for p in manifest() if p["stage"] == "sample" and p["id"] not in {x["id"] for x in priced}]
    if out["problems"] and missing_sample:
        out["words"] = (f"Couldn't price {len(out['problems'])} of the pieces, among them the sample's. Look at the "
                        "problems under More, then try the quote again.")
    elif out["sample_usd"] > SAMPLE_CAP_USD:
        out["words"] = (f"The sample sheet would cost {_money(out['sample_usd'])}, more than its "
                        f"{_money(SAMPLE_CAP_USD)}. The manifest needs smaller pieces first.")
    elif out["total_usd"] > TRIM_AT:
        out["words"] = (f"Even with pieces left out the office would cost {_money(out['total_usd'])}, more than "
                        f"{_money(TRIM_AT)}. The manifest needs fewer or smaller pieces first.")
    else:
        out["ok"] = True
        out["words"] = (f"The office costs about {_money(out['total_usd'])}: the sample sheet first "
                        f"({_money(out['sample_usd'])}), then the rest ({_money(out['rest_usd'])}) once you like it. "
                        f"Never more than {_money(CAP_USD)} in all.")
        if out["left_out"]:
            out["words"] += f" {len(out['left_out'])} pieces left out to keep it under {_money(TRIM_AT)}."
        if out["problems"]:
            out["words"] += f" {len(out['problems'])} pieces couldn't be priced and won't be made."
    return out


# -- the money: reserve, then settle with the real charge -------------------------------------------------------------
def _rows(spent_file: Path | str) -> list[dict[str, Any]]:
    try:
        lines = Path(spent_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def spent(spent_file: Path | str, stage: str | None = None) -> float:
    """Dollars already charged for the office art in this spend file (one stage's, when named)."""
    return round(sum(float(r.get("cost_usd") or 0.0) for r in _rows(spent_file)
                     if stage is None or r.get("stage") == stage), 6)


def _key(spent_file: Path | str) -> str:
    return str(Path(spent_file).resolve())


def held(spent_file: Path | str) -> float:
    with _LOCK:
        return round(sum(_HELD.get(_key(spent_file), {}).values()), 6)


def reserve(spent_file: Path | str, usd: float, cap: float = CAP_USD) -> str:
    """Hold ``usd`` for one call, under one lock, if what was spent, what is held and this stay within ``cap``
    (never above ``CAP_USD``); raises ``OfficeCapReached`` otherwise. Returns the token to settle or release."""
    cap = min(float(cap), CAP_USD)
    usd = max(0.0, float(usd or 0.0))
    with _LOCK:
        hold = _HELD.setdefault(_key(spent_file), {})
        if spent(spent_file) + sum(hold.values()) + usd > cap + 1e-9:
            raise OfficeCapReached(f"That would take the office art past its {_money(cap)} cap, so it isn't asked for.")
        token = uuid.uuid4().hex
        hold[token] = usd
        return token


def settle(spent_file: Path | str, token: str, real_usd: float, row: dict[str, Any]) -> None:
    """The call was made: write its real charge (one whole line) and let the hold go."""
    p = Path(spent_file)
    line = json.dumps({"at": utcnow(), **row, "cost_usd": round(float(real_usd or 0.0), 6)}) + "\n"
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
        _HELD.get(_key(p), {}).pop(token, None)


def release(spent_file: Path | str, token: str) -> None:
    """The call failed or was refused: nothing was charged, the hold goes."""
    with _LOCK:
        _HELD.get(_key(spent_file), {}).pop(token, None)


# -- the state: what was made, and the owner's yes -------------------------------------------------------------------
def _state_path(spent_file: Path | str) -> Path:
    return Path(spent_file).with_name(STATE_NAME)


def state(spent_file: Path | str) -> dict[str, Any]:
    try:
        st = json.loads(_state_path(spent_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st = st if isinstance(st, dict) else {}
    st.setdefault("files", {})
    st.setdefault("approved", False)
    st.setdefault("stopped", False)
    return st


def _save_state(spent_file: Path | str, st: dict[str, Any]) -> None:
    p = _state_path(spent_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def approve(spent_file: Path | str) -> dict[str, Any]:
    """The owner's yes to the sample sheet: only then may ``make(..., "rest", ...)`` run."""
    with _LOCK:
        st = state(spent_file)
        if not st.get("sample"):
            raise OfficeArtError("There's no sample sheet to approve yet. Make the sample first.")
        st.update(approved=True, stopped=False, approved_at=utcnow())
        _save_state(spent_file, st)
    return st


def stop(spent_file: Path | str) -> dict[str, Any]:
    """"Stop here": nothing more is made; the sample stays. The card goes away."""
    with _LOCK:
        st = state(spent_file)
        st.update(stopped=True, stopped_at=utcnow())
        _save_state(spent_file, st)
    return st


# -- making the pieces --------------------------------------------------------------------------------------------
def _ext(data: bytes, given: str) -> str:
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return given if given in PICTURE_EXTS else "png"


def _write_piece(out: Path, piece: dict[str, Any], data: bytes, ext: str) -> str:
    out.mkdir(parents=True, exist_ok=True)
    name = f"{piece['id']}.{_ext(data, ext)}"
    for old in PICTURE_EXTS:  # one picture per piece: an older try is kept aside, never deleted
        prev = out / f"{piece['id']}.{old}"
        if prev.exists():
            prev.replace(out / f".{piece['id']}.{old}.old")
    (out / name).write_bytes(data)
    return name


def _one(provider, piece: dict[str, Any], est: float, out: Path, spent_file: Path, stage: str,
         cap: float) -> tuple[str, Any]:
    """Make one piece: reserve, call, settle; a failed call is released and tried once more.
    ("made", (file, usd)) | ("skipped", why) | ("failed", why)."""
    why = ""
    for _attempt in (1, 2):
        try:
            token = reserve(spent_file, est, cap)
        except OfficeCapReached as e:
            return "skipped", str(e)
        try:
            data, ext, usage = provider.generate(piece["style"], piece["prompt"], {"style": piece["style"], **_opts(piece)})
        except Exception as e:  # noqa: BLE001 - refused or failed: nothing charged, try once more
            release(spent_file, token)
            why = str(e)[:200]
            continue
        real = getattr(usage, "cost_usd", None)
        real = est if real is None else float(real)
        settle(spent_file, token, real, {"piece": piece["id"], "stage": stage, "style": piece["style"]})
        return "made", (_write_piece(out, piece, data, ext), real)
    return "failed", f"Didn't work twice: {why}"


def _find(out: Path, piece_id: str, files: dict[str, str] | None = None) -> Path | None:
    name = (files or {}).get(piece_id)
    if name and (out / name).is_file():
        return out / name
    for ext in PICTURE_EXTS:
        p = out / f"{piece_id}.{ext}"
        if p.is_file():
            return p
    return None


def make(provider, stage: str, out, spent_file) -> dict[str, Any]:
    """Make the pieces of ``stage`` ("sample" or "rest") into ``out``, each reserved then settled in ``spent_file``.

    Returns ``{made: [ids], skipped: [{id, why}], failed: [{id, why}], usd, spent, stage, words}`` (and ``sheet``
    for the sample). Raises ``OfficeArtError`` with plain words when the step may not run."""
    if stage not in ("sample", "rest"):
        raise OfficeArtError('Say which part to make: "sample" or "rest".')
    out, spent_file = Path(out), Path(spent_file)
    st = state(spent_file)
    if stage == "rest" and not st.get("approved"):
        raise OfficeArtError("The rest of the office waits for your yes to the sample sheet. Look at the sample "
                             "first, then choose Make the rest.")
    if stage == "sample" and st.get("approved"):
        raise OfficeArtError("You've already said yes to the sample, so it isn't made again. Make the rest, or one "
                             "piece again from its card.")
    q = quote(provider)
    if not q["ok"]:
        raise OfficeArtError(q["words"])
    price = {x["id"]: x["usd"] for x in q["pieces"]}
    todo = [p for p in manifest() if p["id"] in price and p["stage"] == stage]
    if stage == "rest":
        todo = [p for p in todo if not _find(out, p["id"], st.get("files"))]
        cap = CAP_USD
    else:
        if sum(price[p["id"]] for p in todo) > SAMPLE_CAP_USD:
            raise OfficeArtError(f"The sample would cost more than {_money(SAMPLE_CAP_USD)}. Nothing was made.")
        # a try of the sample never passes its own cap, nor the whole one
        cap = min(CAP_USD, spent(spent_file) + held(spent_file) + SAMPLE_CAP_USD)
    made, skipped, failed, usd = [], [], [], 0.0
    for p in todo:
        kind, res = _one(provider, p, price[p["id"]], out, spent_file, stage, cap)
        if kind == "made":
            name, cost = res
            made.append(p["id"])
            usd += cost
            with _LOCK:
                st2 = state(spent_file)
                st2["files"][p["id"]] = name
                _save_state(spent_file, st2)
        else:
            (skipped if kind == "skipped" else failed).append({"id": p["id"], "why": res})
    res: dict[str, Any] = {"made": made, "skipped": skipped, "failed": failed, "usd": round(usd, 6),
                           "spent": spent(spent_file), "cap": CAP_USD, "stage": stage}
    with _LOCK:
        st = state(spent_file)
        if stage == "sample":
            sheet = sample_sheet(out, st.get("files"))
            tries = int((st.get("sample") or {}).get("tries") or 0) + 1
            st["sample"] = {"at": utcnow(), "usd": round(usd, 6), "sheet": sheet.name if sheet else "", "tries": tries,
                            "rest_usd": q["rest_usd"], "left_out": q["left_out"]}
            st.update(approved=False, stopped=False)
            res["sheet"] = str(sheet) if sheet else ""
        else:
            st["rest"] = {"at": utcnow(), "usd": round(usd, 6), "made": len(made),
                          "missing": [x["id"] for x in skipped + failed]}
        _save_state(spent_file, st)
    what = "sample sheet" if stage == "sample" else "rest of the office"
    words = f"Made {len(made)} piece{'s' if len(made) != 1 else ''} of the {what} for {_money(usd)}"
    words += f" ({_money(res['spent'])} of {_money(CAP_USD)} spent in all)."
    if skipped:
        words += f" {len(skipped)} not asked for: they would pass the cap."
    if failed:
        words += f" {len(failed)} didn't work twice: make them again from their cards."
    res["words"] = words
    return res


def remake(provider, piece_id: str, out, spent_file, confirm: bool = False) -> dict[str, Any]:
    """One piece made again (the owner disliked it): its price first; with ``confirm`` it is made, inside the cap."""
    out, spent_file = Path(out), Path(spent_file)
    p = _piece(piece_id)
    st = state(spent_file)
    if p["stage"] == "rest" and not st.get("approved"):
        raise OfficeArtError("That piece is part of the rest, which waits for your yes to the sample sheet.")
    try:
        est = float(provider.check_cost(p["style"], p["prompt"], _opts(p)))
    except Exception as e:  # noqa: BLE001 - no price, no call
        raise OfficeArtError(f"Couldn't get the price of {piece_id} ({str(e)[:160]}). Try again in a minute.") from e
    left = round(CAP_USD - spent(spent_file) - held(spent_file), 6)
    if not confirm:
        return {"made": False, "id": piece_id, "usd": est, "left": left, "fits": est <= left + 1e-9,
                "words": (f"Making {piece_id} again costs about {_money(est)}; {_money(max(0.0, left))} of the "
                          f"{_money(CAP_USD)} is left." if est <= left + 1e-9 else
                          f"Making {piece_id} again ({_money(est)}) would pass the {_money(CAP_USD)} cap.")}
    kind, res = _one(provider, p, est, out, spent_file, p["stage"], CAP_USD)
    if kind != "made":
        return {"made": False, "id": piece_id, "usd": 0.0, "words": res}
    name, cost = res
    with _LOCK:
        st = state(spent_file)
        st["files"][piece_id] = name
        _save_state(spent_file, st)
    if p["stage"] == "sample" and not st.get("approved"):
        sample_sheet(out, st["files"])
    return {"made": True, "id": piece_id, "usd": cost, "spent": spent(spent_file),
            "words": f"Made {piece_id} again for {_money(cost)}."}


# -- the sample sheet: finished pictures laid side by side (arranging, not drawing) -----------------------------------
def _first_frame_size(im, piece: dict[str, Any]) -> tuple[int, int]:
    sheet = piece.get("sheet") or {}
    cols, rows = int(sheet.get("cols") or 1), int(sheet.get("rows") or 1)
    return max(1, im.width // cols), max(1, im.height // rows)


def sample_sheet(out, files: dict[str, str] | None = None) -> Path | None:
    """The sample pieces side by side on one sheet (``sample-sheet.png`` in ``out``), each whole (an animation's
    whole sheet, so its frames show), scaled up by whole numbers so the pixels stay crisp. None without Pillow or
    without pictures."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow is a dependency, but a build without it shows the pieces one by one
        return None
    out = Path(out)
    ims = []
    for p in [p for p in manifest() if p["stage"] == "sample"]:
        f = _find(out, p["id"], files)
        if not f:
            continue
        try:
            im = Image.open(f)
            im.seek(0)
            ims.append(im.convert("RGBA"))
        except Exception:  # noqa: BLE001 - a picture Pillow can't read is left off the sheet
            continue
    if not ims:
        return None
    tallest = max(im.height for im in ims)
    scale = max(1, min(4, 192 // max(1, tallest)))
    ims = [im.resize((im.width * scale, im.height * scale), Image.NEAREST) for im in ims]
    width = sum(im.width for im in ims) + SHEET_GAP * (len(ims) + 1)
    height = max(im.height for im in ims) + 2 * SHEET_GAP
    sheet = Image.new("RGBA", (width, height), SHEET_BACK)
    x = SHEET_GAP
    for im in ims:
        sheet.alpha_composite(im, (x, SHEET_GAP + (height - 2 * SHEET_GAP - im.height) // 2))
        x += im.width + SHEET_GAP
    path = out / SHEET_NAME
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(path, "PNG")
    return path


# -- in the app ---------------------------------------------------------------------------------------------------
def paths(app) -> tuple[Path, Path]:
    """(the pictures' folder, the spend file) in the app's own home folder."""
    base = Path(app._backup_home()) / "office-art"
    return base / "pieces", base / SPEND_NAME


def provider_for(cfg) -> Any:
    """The Retro Diffusion provider from the harness's settings, or None when none is set up."""
    for name, spec in (getattr(cfg, "providers", None) or {}).items():
        if isinstance(spec, dict) and spec.get("type") == "retrodiffusion":
            try:
                return cfg.provider(name)
            except Exception:  # noqa: BLE001 - set up wrongly: treated as not set up
                return None
    return None


def art_dir(app=None) -> Path | None:
    """Where the office's pictures are: those made on this computer when they are complete, else the shipped ones
    next to the manifest; None when neither has what the view needs."""
    dirs = []
    if app is not None:
        try:
            dirs.append(paths(app)[0])
        except Exception:  # noqa: BLE001 - no home folder (a bare app in tests)
            pass
    dirs.append(MANIFEST.parent)
    for d in dirs:
        if _complete(d):
            return d
    return None


def _complete(d: Path) -> bool:
    if not all(_find(d, pid) for pid in REQUIRED):
        return False
    figures = (layout().get("agents") or {}).values()
    return any(_find(d, f.get("walk", "")) and _find(d, f.get("work", "")) for f in figures if isinstance(f, dict))


def ready(app=None) -> bool:
    """Whether the office has its pictures (else the switch is hidden and the Ring stays)."""
    return art_dir(app) is not None


def data_url(p: Path) -> str:
    kind = {"gif": "image/gif", "webp": "image/webp"}.get(p.suffix.lstrip(".").lower(), "image/png")
    return f"data:{kind};base64," + base64.b64encode(p.read_bytes()).decode()


def pictures(app=None) -> dict[str, Any]:
    """The view's pictures as data addresses, with the layout: ``{art, pieces: {id: {url, kind, sheet, draw}}, ...}``."""
    d = art_dir(app)
    if d is None:
        return {"art": False, "pieces": {}}
    files = {}
    if app is not None and d == paths(app)[0]:
        files = state(paths(app)[1]).get("files") or {}
    pieces = {}
    for p in manifest():
        f = _find(d, p["id"], files)
        if f:
            pieces[p["id"]] = {"url": data_url(f), "kind": p.get("kind"), "sheet": p.get("sheet"), "draw": p.get("draw")}
    return {"art": True, "pieces": pieces, **layout()}


def sample_ask(app) -> dict[str, Any] | None:
    """The one card once the sample sheet is made: Make the rest, Try the sample again, or Stop here. The paid
    answers carry ``confirm`` (no timer or autopilot can give them); PC only. Answered at ``POST /api/office/answer``."""
    from .asks import _ask

    try:
        out, spent_file = paths(app)
    except Exception:  # noqa: BLE001 - no home folder
        return None
    st = state(spent_file)
    sample = st.get("sample") or {}
    if not sample or st.get("approved") or st.get("stopped"):
        return None
    spent_now = spent(spent_file)
    rest = float(sample.get("rest_usd") or 0.0)
    again = float(sample.get("usd") or 0.0)
    opts = [{"id": "rest", "label": f"Make the rest ({_money(rest)})",
             "description": f"Makes the other pieces. Never more than {_money(CAP_USD)} in all; "
                            f"{_money(spent_now)} spent so far.",
             "confirm": f"This spends about {_money(rest)} of your Retro Diffusion credit."}]
    if spent_now + again <= CAP_USD - rest:  # a second sample only while the rest still fits under the cap
        opts.append({"id": "again", "label": f"Try the sample again ({_money(again)})",
                     "description": "Makes the sample pieces again from the same descriptions.",
                     "confirm": f"This spends about {_money(again)} of your Retro Diffusion credit."})
    opts.append({"id": "stop", "label": "Stop here", "description": "Nothing more is made. The Ring stays as it is."})
    detail = (f"The sample cost {_money(again)}. The rest costs about {_money(rest)}."
              + (f" {len(sample.get('left_out') or [])} pieces were left out to keep it under {_money(TRIM_AT)}."
                 if sample.get("left_out") else ""))
    ask = _ask("officeart", "office_art", "Office art", "The office's sample sheet is ready. Make the rest?", opts,
               recommended="rest", detail=detail, source={"sample_at": sample.get("at", "")}, pc_only=True,
               route="/api/office/answer")
    ask["allow_other"] = False
    sheet = out / str(sample.get("sheet") or SHEET_NAME)
    if sheet.is_file():
        ask["picture"] = data_url(sheet)
    return ask
