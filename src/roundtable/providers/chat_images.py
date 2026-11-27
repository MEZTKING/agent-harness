"""Image models reached through a chat endpoint (OpenRouter's image models: GPT Image, Nano Banana…).

These models answer a chat request that asks for `modalities: ["image", "text"]` with the picture
as a data address in `message.images`. The exact charge comes back in the usage block when asked
(OpenRouter's `usage.include`), so every picture is costed precisely.

Options: ``aspect_ratio`` (e.g. "16:9", "1:1") and ``size``: "1K", "2K" or "4K" (OpenRouter's
``image_config.image_size``), "largest" (4K, the most any of these models offers), or "WIDTHxHEIGHT" (sent as
``image_config.size``; verify at a real run which models read it). With no ``size`` nothing is sent and the
model uses its own default, so the price stays as before.

Two more options (wave 8):

* ``from_image``: an earlier picture (bytes, a ``data:`` address or a file path) sent with the instruction, so
  the answer is an edit of it. Only models that take a picture in get it; any other is refused with a plain
  sentence before the request is made, so nothing is paid.
* ``transparent``: a see-through background. Asked of the model where it can (``image_config.background``);
  otherwise the prompt asks for a plain magenta background and the cut-out is done here with Pillow. The
  picture is always a PNG then, with a ``Transparent`` note in it saying which way it was done, and
  ``options["record"]`` (a dict, if the caller passes one) gets ``{"transparent": "model" | "cut-out",
  "from_image": bool}``.

Which models can is a guess by name (``PICTURE_IN``, ``TRANSPARENT_NATIVE``; verify at a real run); a role's
options ``picture_in: true/false`` and ``transparent_native: true/false`` say it for certain.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any

from .base import ImageProvider, ProviderError, Usage
from .openai_compat import _client, _reported_cost, _wrap_errors

SIZES = ("1K", "2K", "4K")
LARGEST = "4K"
# OpenRouter model ids (by their start) that take a picture in, and that make a see-through background
# themselves (verify at a real run: the lists change as models do)
PICTURE_IN = ("google/gemini", "openai/gpt", "openai/o", "black-forest-labs/flux", "bytedance/seed")
TRANSPARENT_NATIVE = ("openai/gpt",)
KEY_COLOUR = (255, 0, 255)  # the plain background asked for when the cut-out is done here
KEY_WORDS = ("Put the subject on a plain, flat, solid magenta background (#FF00FF) that fills the whole picture, "
             "with no shadow, gradient, floor or pattern, and use no magenta in the subject itself.")
MAX_PICTURE_IN = 20 * 1024 * 1024
_WXH = re.compile(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$")


def image_config(options: dict[str, Any]) -> dict[str, Any]:
    """The ``image_config`` block for these options ({} when neither an aspect nor a size is asked for)."""
    out: dict[str, Any] = {}
    if options.get("aspect_ratio"):  # e.g. "16:9" (Gemini image models)
        out["aspect_ratio"] = str(options["aspect_ratio"])
    size = str(options.get("size") or "").strip()
    if size:
        up = size.upper()
        m = _WXH.match(size)
        if up in SIZES:
            out["image_size"] = up
        elif up == "LARGEST":
            out["image_size"] = LARGEST
        elif m:
            out["size"] = f"{int(m.group(1))}x{int(m.group(2))}"
        else:
            raise ProviderError(f"a picture size of {size!r} isn't known: use 1K, 2K, 4K, largest or "
                                "WIDTHxHEIGHT", retryable=False)
    if options.get("transparent") and natively_transparent(options.get("_model", ""), options):
        out["background"] = "transparent"
    return out


def _bare(model: str) -> str:
    return str(model or "").lower().removeprefix("openrouter/")


def _said(options: dict[str, Any], key: str) -> bool | None:
    v = options.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "yes", "false", "no"):
        return v.lower() in ("true", "yes")
    return None


def takes_picture(model: str, options: dict[str, Any] | None = None) -> bool:
    """Does this model take an earlier picture in (to edit it)?"""
    said = _said(options or {}, "picture_in")
    return said if said is not None else _bare(model).startswith(PICTURE_IN)


def natively_transparent(model: str, options: dict[str, Any] | None = None) -> bool:
    said = _said(options or {}, "transparent_native")
    return said if said is not None else _bare(model).startswith(TRANSPARENT_NATIVE)


def _has_pillow() -> bool:
    try:
        import PIL.Image  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def refusal(model: str, options: dict[str, Any] | None) -> str | None:
    """Why this model can't do what the options ask, in a plain sentence; None when it can. Asked before any
    request, so a refusal costs nothing."""
    options = options or {}
    if options.get("from_image") and not takes_picture(model, options):
        return (f"{model} can't take an earlier picture to change, so nothing was sent and nothing was paid. "
                "Choose a picture model that can (Nano Banana or GPT Image) for this job in Models.")
    if options.get("transparent") and not natively_transparent(model, options) and not _has_pillow():
        return (f"{model} can't make a see-through picture and this computer can't cut one out (Pillow is "
                "missing), so nothing was sent and nothing was paid. Reinstall the app, then try again.")
    return None


_MIME = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif", b"RIFF": "image/webp"}


def picture_url(src: Any) -> str:
    """An earlier picture as a ``data:`` address: bytes, an address already, or a file path."""
    if isinstance(src, str) and src.startswith("data:image/") and ";base64," in src:
        return src
    if isinstance(src, (str, Path)):
        p = Path(src)
        try:
            if not p.is_file() or p.stat().st_size > MAX_PICTURE_IN:
                raise ProviderError(f"the earlier picture {p.name} isn't there or is bigger than 20 MB",
                                    retryable=False)
            src = p.read_bytes()
        except OSError as e:
            raise ProviderError(f"the earlier picture {p.name} couldn't be read ({e})", retryable=False) from e
    if not isinstance(src, (bytes, bytearray)) or not src:
        raise ProviderError("the earlier picture to change isn't a picture", retryable=False)
    if len(src) > MAX_PICTURE_IN:
        raise ProviderError("the earlier picture is bigger than 20 MB", retryable=False)
    mime = next((m for head, m in _MIME.items() if bytes(src).startswith(head)), "")
    if not mime:
        raise ProviderError("the earlier picture to change isn't a PNG, JPEG, GIF or WebP", retryable=False)
    return f"data:{mime};base64," + base64.b64encode(bytes(src)).decode()


def has_see_through(data: bytes) -> bool:
    """Does the picture have see-through parts already?"""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
            return False
        return im.convert("RGBA").getextrema()[3][0] < 250
    except Exception:  # noqa: BLE001
        return False


def corner_colour(im) -> tuple[int, int, int]:
    """The average of the four corners: the plain background a picture was asked to stand on."""
    w, h = im.size
    pts = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return tuple(sum(p[i] for p in pts) // 4 for i in range(3))  # type: ignore[return-value]


def cut_out(data: bytes, key: tuple[int, int, int] | None = None, tolerance: int = 60, how: str = "cut-out") -> bytes:
    """Make the plain background see-through (Pillow): pixels near ``key`` (by default the corners' colour)
    go clear, with a soft edge over the next ``tolerance`` steps. A PNG with a ``Transparent`` note."""
    from PIL import Image, ImageChops, PngImagePlugin

    im = Image.open(io.BytesIO(data)).convert("RGB")
    key = tuple(key) if key else corner_colour(im)
    diff = ImageChops.difference(im, Image.new("RGB", im.size, key))
    r, g, b = diff.split()
    far = ImageChops.lighter(ImageChops.lighter(r, g), b)  # how far each pixel is from the background colour
    tol = max(1, int(tolerance))
    alpha = far.point(lambda v: 0 if v <= tol else 255 if v >= 2 * tol else (v - tol) * 255 // tol)
    out = im.convert("RGBA")
    out.putalpha(alpha)
    info = PngImagePlugin.PngInfo()
    info.add_text("Transparent", how)
    buf = io.BytesIO()
    out.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _note(data: bytes, how: str) -> bytes:
    """The picture as a PNG with its ``Transparent`` note (the model made it see-through itself)."""
    from PIL import Image, PngImagePlugin

    im = Image.open(io.BytesIO(data)).convert("RGBA")
    info = PngImagePlugin.PngInfo()
    info.add_text("Transparent", how)
    buf = io.BytesIO()
    im.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def picture_from_message(msg: Any) -> tuple[bytes, str]:
    """The first picture in a chat answer: (bytes, extension). Raises if there's none."""
    extra = getattr(msg, "model_extra", None) or {}
    images = getattr(msg, "images", None) or extra.get("images") or []
    for img in images:
        url = (img.get("image_url") or {}).get("url") if isinstance(img, dict) else None
        if url and url.startswith("data:") and ";base64," in url:
            head, data = url.split(";base64,", 1)
            return base64.b64decode(data), _EXT.get(head[5:], "png")
    raise ProviderError("the image model answered without a picture", retryable=True)


class ChatImagesProvider(ImageProvider):
    def __init__(self, provider_id: str, api_key_env: str | None = "OPENROUTER_API_KEY",
                 base_url: str | None = "https://openrouter.ai/api/v1", timeout: float = 600.0, **client_opts):
        self.name = provider_id
        self.api_key_env = api_key_env
        self._openai, self.client = _client(api_key_env, base_url, timeout, **client_opts)

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        options = options or {}
        why = refusal(model, options)
        if why:  # before any request: nothing is sent and nothing is paid
            raise ProviderError(why, retryable=False)
        transparent = bool(options.get("transparent"))
        how = ("model" if natively_transparent(model, options) else "cut-out") if transparent else ""
        extra: dict[str, Any] = {"modalities": ["image", "text"], "usage": {"include": True}}
        config = image_config({**options, "_model": model})
        if config:
            extra["image_config"] = config
        text = prompt
        if how == "model":
            text += "\n\nMake the background fully see-through (transparent)."
        elif how == "cut-out":
            text += "\n\n" + KEY_WORDS
        content: Any = text
        if options.get("from_image"):
            content = [{"type": "text", "text": text},
                       {"type": "image_url", "image_url": {"url": picture_url(options["from_image"])}}]
        resp = _wrap_errors(self._openai, self.name, model, self.api_key_env, lambda: self.client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": content}], extra_body=extra))
        if not resp.choices:
            raise ProviderError(f"{self.name}: empty answer from {model}", retryable=True)
        data, ext = picture_from_message(resp.choices[0].message)
        if transparent:
            data, how = see_through(data, how)
            ext = "png"
        if isinstance(options.get("record"), dict):
            options["record"].update({"transparent": how, "from_image": bool(options.get("from_image"))})
        u = resp.usage
        return data, ext, Usage(input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                                output_tokens=getattr(u, "completion_tokens", 0) or 0,
                                cost_usd=_reported_cost(u))


def see_through(data: bytes, how: str) -> tuple[bytes, str]:
    """The answer made see-through: kept when the model did it, else cut out here. (PNG bytes, the way it was
    done: "model", "cut-out", or "cut-out (from the model's own background)" when the model was asked but
    didn't.)"""
    if how == "model":
        if has_see_through(data):
            return _note(data, "model"), "model"
        how = "cut-out (from the model's own background)"
        return cut_out(data, None, how=how), how
    return cut_out(data, KEY_COLOUR, how="cut-out"), "cut-out"
