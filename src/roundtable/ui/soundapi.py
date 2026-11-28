"""Sound and music for a project, and the service that makes them (wave 9), as an API.

    GET  /api/sounds          ?path=<project> -> {sounds: [{task, title, file, kind, seconds, made, service,
                              usd, why, licence}], spent, cap, owner_cap, words, just_for_me, service}
                              Read only; the phone may call it (phone.PHONE_ROUTES).
    POST /api/sounds/again    {path, task, confirm?} -> without confirm: {confirm: true, question, usd} (nothing
                              spent); with confirm the sound is made again inside the cap: the same as GET.
    POST /api/sounds/project  {path, max_usd?, just_for_me?} -> the same as GET. The project's own sound figure
                              (never above the owner's) and whether it's "just for me".
    GET  /api/sounds/service  -> {service, cards: [{id, name, price, licence, buys, key_env, has_key, docs}]}
    POST /api/sounds/service  {service: "elevenlabs_sound" | "stable_audio" | "", confirm?} -> without confirm a
                              question; with confirm it is kept in custom.yaml (the provider and the role
                              ``sounds``): the same as GET.
    POST /api/sounds/test     {service, confirm?} -> without confirm: {confirm: true, question, usd}; with confirm
                              one 1-second effect is made: {ok, why, usd, audio: data address}.

Everything that spends, writes or changes a setting stays on the PC: only ``GET /api/sounds`` is offered to the
phone. Every price is shown before it is spent.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from ..harness import soundcheck, soundprice, soundstage
from ..providers.base import ProviderError, SoundProvider

ROLE = "sounds"
SERVICES = {
    "elevenlabs_sound": {
        "model": "effects", "name": "ElevenLabs",
        "price": "About 12 cents a minute of sound effects and 15 cents a minute of music, on a plan of about $6 a "
                 "month.",
        "licence": "Paid plans may sell what it makes; the free plan may not.",
        "buys": "$2 buys about a thousand seconds of effects: every sound a small game needs, and a music loop.",
    },
    "stable_audio": {
        "model": "stable-audio-2.5", "name": "Stable Audio",
        "price": "About 8 cents a clip, whatever its length. Pay as you go, no monthly plan.",
        "licence": "You may sell what it makes while your yearly revenue is under $1 million.",
        "buys": "$2 buys about 25 clips: music and ambience first, some effects made in code.",
    },
}


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/sounds"): lambda q: listing(app, _arg(q, "path")),
        ("POST", "/api/sounds/again"): lambda body: again(app, body or {}),
        ("POST", "/api/sounds/project"): lambda body: set_project(app, body or {}),
        ("GET", "/api/sounds/service"): lambda q: services(app),
        ("POST", "/api/sounds/service"): lambda body: set_service(app, body or {}),
        ("POST", "/api/sounds/test"): lambda body: test(app, body or {}),
    }


def _arg(q, name: str) -> str:
    return str((q.get(name) or [""])[0] or "")


def _err(text: str, code: int = 400):
    from .server import ApiError

    return ApiError(text, code)


def _money(x: float) -> str:
    return f"${x:g}" if float(x).is_integer() else f"${x:.2f}"


def _project(app, path: str):
    cfg = app.need_cfg()
    return cfg, app.project(cfg, path)


def _role(cfg):
    role = cfg.roles.get(ROLE)
    if role is not None and role.kind == "sound":
        return role
    return next((r for r in cfg.roles.values() if r.kind == "sound"), None)


def _service(cfg) -> str:
    role = _role(cfg)
    if role is None:
        return ""
    spec = (getattr(cfg, "providers", None) or {}).get(role.models[0].provider) or {}
    return str(spec.get("type") or role.models[0].provider)


# -- a project's sounds ----------------------------------------------------------------------------------------
def listing(app, path: str) -> dict[str, Any]:
    cfg, proj = _project(app, path)
    root = proj.root
    rows = soundstage.read_sounds(root)
    spent, limit = soundprice.spent(root), soundprice.cap(cfg, root)
    bought = sum(1 for r in rows if r.get("made") == "bought")
    code = sum(1 for r in rows if r.get("made") == "code")
    if not rows:
        words = "No sounds yet." if _role(cfg) else "No sound service is picked: sounds are made in code."
    else:
        parts = [f"{bought} bought" if bought else "", f"{code} made in code" if code else ""]
        words = f"${spent:.2f} of {_money(limit)} used. " + ", ".join(p for p in parts if p).capitalize() + "."
    own = soundprice.project_sound(root)
    return {"sounds": rows, "spent": spent, "cap": limit, "owner_cap": soundprice.owner_cap(cfg), "words": words,
            "just_for_me": bool(own.get("just_for_me")), "service": _service(cfg)}


def _find(root, task: str) -> dict[str, Any]:
    row = next((r for r in soundstage.read_sounds(root) if r.get("task") == task), None)
    if not row:
        raise _err("That sound isn't in this project. Open the project again to see its sounds.", 404)
    return row


def _opts(row: dict[str, Any]) -> dict[str, Any]:
    kind = row.get("kind") if row.get("kind") in ("effect", "music") else "effect"
    return {"kind": kind, "seconds": soundprice.seconds_of(kind, row.get("seconds")), "loop": bool(row.get("loop"))}


def again(app, body: dict[str, Any]) -> dict[str, Any]:
    """Make one sound again, priced first and inside the project's cap."""
    cfg, proj = _project(app, str(body.get("path") or ""))
    root = proj.root
    row = _find(root, str(body.get("task") or ""))
    role = _role(cfg)
    if role is None:
        raise _err("No sound service is picked. Choose one in Settings → Services → Sound and music first.")
    ref = role.models[0]
    opts = _opts(row)
    prompt = str(row.get("prompt") or row.get("title") or "")
    usd = soundprice.quote(cfg, ref, prompt, opts)
    if usd is None:
        raise _err("This sound's price can't be told, so it isn't made again. Check the sound service in Settings.")
    left = soundprice.cap(cfg, root) - soundprice.spent(root)
    if not body.get("confirm"):
        return {"confirm": True, "usd": usd, "question": f"Make \"{row.get('title') or 'this sound'}\" again for about "
                f"${usd:.2f}? ${max(left, 0):.2f} of this project's sound money is left."}
    try:
        provider = cfg.provider(ref.provider)
    except ProviderError:
        provider = None
    if not isinstance(provider, SoundProvider):
        raise _err("The sound service isn't set up on this computer. Add its key in Settings → Services.")
    try:
        token = soundprice.reserve(root, cfg, usd)
    except soundprice.SoundCapReached as e:
        raise _err(f"{e} Raise this project's sound money first, or keep the sound made in code.") from None
    t0 = time.monotonic()
    try:
        data, ext, usage = provider.generate(ref.model, prompt, opts)
    except ProviderError as e:
        soundprice.release(root, token)
        raise _err(f"The sound wasn't made: {e}") from None
    real = usage.cost_usd if usage.cost_usd is not None else usd
    ok, why = soundcheck.check(data, ext, opts["kind"], opts["seconds"])
    soundprice.settle(root, token, real, {"task": row.get("task"), "title": row.get("title"), "model": str(ref),
                                          "kind": opts["kind"], "seconds": opts["seconds"], "quote": usd, "ok": ok,
                                          "again": True})
    if not ok:
        raise _err(f"The new sound didn't pass the check ({why}) – the old one is kept. It cost ${real:.2f}.")
    rel = row.get("file") or f"assets/sounds/{soundstage.slug(row.get('title') or row.get('task'))}.{ext}"
    if Path(rel).suffix.lower() != f".{ext}":
        rel = str(Path(rel).with_suffix(f".{ext}"))
    dest = (root / rel).resolve()
    if root.resolve() not in dest.parents:
        raise _err("That sound's file is outside the project, so it isn't replaced.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    try:
        lic = provider.licence() or {}
    except Exception:  # noqa: BLE001
        lic = {}
    entry = {**row, "file": rel, "made": "bought", "service": getattr(provider, "name", ref.provider),
             "model": str(ref), "usd": round(real, 6), "why": "",
             "licence": {k: lic.get(k) for k in ("commercial", "words", "link", "read_on") if k in lic},
             "at": soundstage._now(), "day": soundstage._today(), "seconds_taken": round(time.monotonic() - t0, 2)}
    soundstage.add_credit(root, entry)
    soundstage.note_sound(root, entry)
    return listing(app, str(proj.root))


def set_project(app, body: dict[str, Any]) -> dict[str, Any]:
    """The owner's tap: this project's own sound figure (never above the owner's) and "just for me"."""
    cfg, proj = _project(app, str(body.get("path") or ""))
    meta = proj.meta()
    own = dict(meta.get("sound") or {}) if isinstance(meta.get("sound"), dict) else {}
    if "max_usd" in body:
        try:
            usd = float(body["max_usd"])
        except (TypeError, ValueError):
            raise _err("Nothing was changed: say an amount in dollars, such as 1.50.") from None
        top = soundprice.owner_cap(cfg)
        if usd < 0:
            raise _err("Nothing was changed: the amount can't be below nothing.")
        if usd > top:
            raise _err(f"Nothing was changed: a project may spend at most {_money(top)} on sound (your figure in "
                       "Settings → Services → Sound and music).")
        own["max_usd"] = round(usd, 2)
    if "just_for_me" in body:
        own["just_for_me"] = bool(body["just_for_me"])
    meta["sound"] = own
    proj.save_meta(meta)
    return listing(app, str(proj.root))


# -- the service ---------------------------------------------------------------------------------------------------
def _custom_path(app):
    cfg = app.cfg()
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    path = Path(p) if p else None
    if not path or not path.is_file():
        raise _err("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.", 503)
    return path


def services(app) -> dict[str, Any]:
    from ..core import secrets as vault
    from ..providers.catalog import PRESETS

    cfg = app.cfg()
    cards = []
    for sid, card in SERVICES.items():
        preset = PRESETS.get(sid) or {}
        env = preset.get("api_key_env", "")
        try:
            has_key = bool(vault.get(env)) if env else False
        except Exception:  # noqa: BLE001 - the key store can't be read: say no key
            has_key = False
        cards.append({"id": sid, "name": card["name"], "price": card["price"], "licence": card["licence"],
                      "buys": card["buys"], "key_env": env, "has_key": has_key, "docs": preset.get("docs", "")})
    return {"service": _service(cfg) if cfg else "", "cards": cards,
            "owner_cap": soundprice.owner_cap(cfg) if cfg else soundprice.CAP_DEFAULT}


def set_service(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness.config import load_custom, save_custom
    from ..providers.catalog import preset_block

    sid = str(body.get("service") or "")
    if sid and sid not in SERVICES:
        raise _err("Nothing was changed: choose ElevenLabs or Stable Audio.")
    if not body.get("confirm"):
        q = (f"Use {SERVICES[sid]['name']} for this computer's game sounds? {SERVICES[sid]['price']} Each sound is "
             "priced before it's made, and a project spends at most $2 on sound." if sid else
             "Stop buying sounds? New sounds are made in code; the ones already bought stay.")
        return {"confirm": True, "question": q, "service": sid}
    path = _custom_path(app)
    custom = load_custom(path)
    providers = dict(custom.get("providers") or {})
    roles = dict(custom.get("roles") or {})
    if sid:
        providers.setdefault(sid, preset_block(sid))
        roles[ROLE] = {"kind": "sound", "model": f"{sid}/{SERVICES[sid]['model']}",
                       "description": "makes the game's sound effects and music"}
    else:
        roles.pop(ROLE, None)
    custom["providers"], custom["roles"] = providers, roles
    custom["sound"] = {**(custom.get("sound") if isinstance(custom.get("sound"), dict) else {}), "service": sid}
    save_custom(path, custom)
    return services(app)


def test(app, body: dict[str, Any]) -> dict[str, Any]:
    """One 1-second effect from the service, priced first: proves the key and the service work."""
    from ..harness.config import ModelRef

    sid = str(body.get("service") or "")
    if sid not in SERVICES:
        raise _err("Choose ElevenLabs or Stable Audio to test.")
    cfg = app.need_cfg()
    name = next((n for n, spec in (cfg.providers or {}).items() if (spec or {}).get("type") == sid), None)
    if not name:
        raise _err(f"{SERVICES[sid]['name']} isn't set up yet: pick it above first.")
    ref = ModelRef(name, SERVICES[sid]["model"])
    opts = {"kind": "effect", "seconds": 1.0}
    usd = soundprice.quote(cfg, ref, "a short soft click", opts)
    if not body.get("confirm"):
        return {"confirm": True, "usd": usd, "question": (f"Make one 1-second test sound for about ${usd:.2f}?"
                if usd is not None else "Make one 1-second test sound? Its price can't be told first.")}
    try:
        provider = cfg.provider(name)
        data, ext, usage = provider.generate(ref.model, "a short soft click", opts)
    except ProviderError as e:
        return {"ok": False, "why": str(e), "usd": 0.0}
    ok, why = soundcheck.check(data, ext, "effect", 1.0)
    mime = "audio/wav" if ext == "wav" else "audio/mpeg"
    return {"ok": ok, "why": why, "usd": usage.cost_usd if usage.cost_usd is not None else usd,
            "audio": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}
