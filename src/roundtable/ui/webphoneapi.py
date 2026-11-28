"""The page for an iPhone (webphone.py), as an API. On the PC only: the phone server never routes these.

    GET  /api/webphone                       -> {enabled, can_turn_on, why_not, words, links, fingerprint,
                                                 fingerprint_words, devices, warning, phone_on, owner_yes}
    POST /api/webphone {enabled: bool}       -> the same; turning it on is refused (403) until the advice is in
                                                and the owner said yes
    POST /api/webphone/answer {yes: bool}    -> the same: the owner's answer on its card
"""

from __future__ import annotations

from typing import Any

from .. import webphone
from .countsapi import home_of


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/webphone"): lambda q: view(app),
        ("POST", "/api/webphone"): lambda body: change(app, body or {}),
        ("POST", "/api/webphone/answer"): lambda body: answer(app, body or {}),
    }


def _phone_status(app) -> dict[str, Any]:
    phone = getattr(app, "phone", None)
    try:
        return phone.status() if phone is not None else {}
    except Exception:  # noqa: BLE001 - no phone server: the card says so
        return {}


def view(app) -> dict[str, Any]:
    return webphone.status(home_of(app), _phone_status(app))


def change(app, body: dict[str, Any]) -> dict[str, Any]:
    if "enabled" not in body:
        raise ValueError("Say whether to turn the page on or off.")
    try:
        webphone.set_enabled(home_of(app), bool(body["enabled"]))
    except PermissionError as e:
        from .server import ApiError

        raise ApiError(str(e), 403) from None
    return view(app)


def answer(app, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body.get("yes"), bool):
        raise ValueError("Answer yes or no.")
    webphone.answer(home_of(app), body["yes"])
    return view(app)
