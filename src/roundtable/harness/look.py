"""The Look stage: visual directions for a project's app, the chosen design file, and its checks.

* ``submit_schema`` / ``validate_looks``: what the designer submits (``submit_looks``) and the strict
  checks on it (hex colours, required parts, readable contrast, directions that differ);
* ``render_mockups``: each mockup page as a picture (desktop 1280x800, phone 390x844) with
  Playwright for Python or for Node, when one is installed; skipped cleanly when not;
* ``design_markdown`` / ``tokens_css``: the project's ``design/DESIGN.md`` and ``design/tokens.css``;
* ``check_tokens``: colours and fonts written into the project's files instead of taken from the
  tokens, so a reviewer can reject a task that drifts from the look.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from .safeenv import clean_env

PALETTE_KEYS = ("background", "surface", "text", "muted", "accent", "accent_text")
COLOUR_NAMES = {"background": "Background", "surface": "Surface (cards, panels)", "text": "Text",
                "muted": "Muted text", "accent": "Accent", "accent_text": "Text on the accent"}
SIZES = {"": (1280, 800), "-phone": (390, 844)}
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
LENGTH = re.compile(r"^\d+(\.\d+)?(px|rem|em)$")
DESIGN_FILE = "design/DESIGN.md"
TOKENS_FILE = "design/tokens.css"
# body text needs AA (4.5:1); muted text is secondary, so large-text AA (3:1) is enough
CONTRAST_PAIRS = (("text", "background", 4.5), ("text", "surface", 4.5), ("accent_text", "accent", 4.5),
                  ("muted", "background", 3.0))


# -- colours ---------------------------------------------------------------------------------
def _hex6(c: str) -> str:
    c = c.strip().lower()
    return "#" + "".join(ch * 2 for ch in c[1:]) if len(c) == 4 else c


def _rgb(c: str) -> tuple[int, int, int]:
    c = _hex6(c)
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _luminance(c: str) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in _rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two hex colours (1 to 21)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _close(a: str, b: str) -> bool:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5 < 48


# -- the submission ----------------------------------------------------------------------------
def submit_schema() -> dict[str, Any]:
    s = {"type": "string"}
    hexs = {"type": "string", "description": "hex colour like #1f6f5c"}
    scheme = {"type": "object", "properties": {
        **{k: hexs for k in PALETTE_KEYS},
        "extra": {"type": "array", "description": "up to 2 more named colours",
                  "items": {"type": "object", "properties": {"name": s, "hex": hexs}, "required": ["name", "hex"]}}},
        "required": list(PALETTE_KEYS)}
    font = {"type": "object", "properties": {
        "family": {**s, "description": "a real Google Fonts family, or a system font stack name"},
        "fallbacks": {**s, "description": "CSS fallbacks, e.g. Georgia, serif"},
        "google": {"type": "boolean", "description": "true when it loads from Google Fonts"},
        "weights": {"type": "array", "items": {"type": "integer"}, "description": "weights the font has, e.g. [400, 700]"}},
        "required": ["family", "fallbacks"]}
    direction = {"type": "object", "properties": {
        "id": {**s, "description": "A, B, C..."},
        "name": {**s, "description": "two to four words"},
        "mood": {**s, "description": "one sentence"},
        "palette": {"type": "object", "properties": {"light": scheme, "dark": scheme}, "required": ["light", "dark"]},
        "fonts": {"type": "object", "properties": {"display": font, "body": font}, "required": ["display", "body"]},
        "shapes": {"type": "object", "properties": {
            "radius": {**s, "description": "corner radius as a CSS length, e.g. 4px"},
            "borders": {**s, "description": "how borders look, e.g. none, hairline 1px, thick 3px ink"},
            "density": {**s, "description": "compact, comfortable or airy"}}, "required": ["radius", "borders", "density"]},
        "motion": {**s, "description": "one line"},
        "signature": {**s, "description": "the one memorable detail"},
        "never": {"type": "array", "items": s, "description": "things this look must never do"},
        "mockup_html": {**s, "description": "one self-contained static HTML page of the app's main screen in this look"}},
        "required": ["id", "name", "mood", "palette", "fonts", "shapes", "motion", "signature", "never", "mockup_html"]}
    return {"type": "object", "properties": {"directions": {"type": "array", "items": direction}},
            "required": ["directions"]}


def _need(d: dict[str, Any], key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{where}: '{key}' is missing")
    return v.strip()


def _scheme(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} is missing")
    out: dict[str, Any] = {}
    for k in PALETTE_KEYS:
        v = _need(raw, k, where)
        if not HEX.match(v):
            raise ValueError(f"{where}.{k} is {v!r}: use a hex colour like #1f6f5c")
        out[k] = _hex6(v)
    extra = raw.get("extra") or []
    if not isinstance(extra, list) or len(extra) > 2:
        raise ValueError(f"{where}.extra: at most 2 named colours")
    out["extra"] = []
    for x in extra:
        name, v = _need(x if isinstance(x, dict) else {}, "name", f"{where}.extra"), str((x or {}).get("hex", ""))
        if not HEX.match(v.strip()):
            raise ValueError(f"{where}.extra '{name}' is {v!r}: use a hex colour like #1f6f5c")
        out["extra"].append({"name": name, "hex": _hex6(v)})
    for fg, bg, need in CONTRAST_PAIRS:
        ratio = contrast(out[fg], out[bg])
        if ratio < need:
            raise ValueError(f"{where}: {fg} {out[fg]} on {bg} {out[bg]} has contrast {ratio:.1f}:1, it needs at "
                             f"least {need}:1 to be readable. Make one darker or lighter")
    return out


def _font(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} is missing")
    weights = [int(w) for w in raw.get("weights") or [] if str(w).isdigit()]
    return {"family": _need(raw, "family", where).strip("'\""), "fallbacks": _need(raw, "fallbacks", where),
            "google": bool(raw.get("google")), "weights": sorted(set(weights))}


def _direction(raw: Any, n: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"direction #{n + 1} is not an object")
    where = f"direction {raw.get('id') or n + 1}"
    pal, fonts, shapes = raw.get("palette") or {}, raw.get("fonts") or {}, raw.get("shapes") or {}
    radius = _need(shapes, "radius", f"{where}.shapes")
    if not LENGTH.match(radius):
        raise ValueError(f"{where}.shapes.radius is {radius!r}: give one CSS length like 6px or 0.5rem")
    never = [str(x).strip() for x in raw.get("never") or [] if str(x).strip()]
    if not never:
        raise ValueError(f"{where}: 'never' needs at least one thing this look must never do")
    html = _need(raw, "mockup_html", where)
    if "<html" not in html.lower() and "<body" not in html.lower():
        raise ValueError(f"{where}: mockup_html must be a whole HTML page")
    if re.search(r"<script[^>]*\bsrc\s*=", html, re.I):
        raise ValueError(f"{where}: mockup_html must not load scripts; make it static")
    name = _need(raw, "name", where)
    if not 2 <= len(name.split()) <= 4:
        raise ValueError(f"{where}: the name {name!r} should be two to four words")
    return {
        "id": _need(raw, "id", where).upper(), "name": name, "mood": _need(raw, "mood", where),
        "palette": {"light": _scheme(pal.get("light"), f"{where}.palette.light"),
                    "dark": _scheme(pal.get("dark"), f"{where}.palette.dark")},
        "fonts": {"display": _font(fonts.get("display"), f"{where}.fonts.display"),
                  "body": _font(fonts.get("body"), f"{where}.fonts.body")},
        "shapes": {"radius": radius, "borders": _need(shapes, "borders", f"{where}.shapes"),
                   "density": _need(shapes, "density", f"{where}.shapes")},
        "motion": _need(raw, "motion", where), "signature": _need(raw, "signature", where),
        "never": never[:8], "mockup_html": html,
    }


def validate_looks(raw: Any, count: int, ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Check a submit_looks call; raises ValueError with what to fix."""
    if not isinstance(raw, list) or len(raw) != count:
        raise ValueError(f"send exactly {count} direction(s)")
    looks = [_direction(x, i) for i, x in enumerate(raw)]
    if ids:
        for d, want in zip(looks, ids):
            d["id"] = want
    seen: dict[str, str] = {}
    for d in looks:
        if d["id"] in seen:
            raise ValueError(f"two directions have the id {d['id']}: use A, B, C")
        seen[d["id"]] = d["name"]
    for i, a in enumerate(looks):
        for b in looks[i + 1:]:
            if a["name"].lower() == b["name"].lower():
                raise ValueError(f"{a['id']} and {b['id']} have the same name: make each direction its own")
            if a["fonts"]["display"]["family"].lower() == b["fonts"]["display"]["family"].lower():
                raise ValueError(f"{a['id']} and {b['id']} use the same display font "
                                 f"{a['fonts']['display']['family']}: give each direction its own")
            if _close(a["palette"]["light"]["accent"], b["palette"]["light"]["accent"]):
                raise ValueError(f"{a['id']} and {b['id']} have nearly the same accent colour: make them clearly different")
    return looks


def summary(d: dict[str, Any]) -> dict[str, Any]:
    """What other projects need to know so they don't repeat this look."""
    return {"name": d.get("name", ""), "accents": [d["palette"][s]["accent"] for s in ("light", "dark")],
            "display_font": d["fonts"]["display"]["family"]}


# -- pictures ----------------------------------------------------------------------------------
_NODE_SCRIPT = r"""
const { chromium } = require('playwright');
let input = '';
process.stdin.on('data', (c) => (input += c));
process.stdin.on('end', async () => {
  const jobs = JSON.parse(input);
  const browser = await chromium.launch();
  try {
    for (const j of jobs) {
      const page = await browser.newPage({ viewport: { width: j.width, height: j.height } });
      await page.route('**/*', (r) => {
        const u = r.request().url();
        return (u.startsWith('file:') || u.startsWith('data:') || /^https:\/\/fonts\.(googleapis|gstatic)\.com\//.test(u))
          ? r.continue() : r.abort();
      });
      await page.goto('file://' + j.html, { waitUntil: 'load', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(300);
      await page.screenshot({ path: j.png });
      await page.close();
    }
  } finally { await browser.close(); }
});
"""


def renderer() -> str | None:
    """'python' or 'node' when Playwright can be used to take the pictures, else None."""
    if importlib.util.find_spec("playwright") is not None:
        return "python"
    node = shutil.which("node")
    if node:
        try:
            ok = subprocess.run([node, "-e", "require.resolve('playwright')"], capture_output=True, timeout=20,
                                env=clean_env())
            if ok.returncode == 0:
                return "node"
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _allowed(url: str) -> bool:
    return url.startswith(("file:", "data:")) or bool(re.match(r"https://fonts\.(googleapis|gstatic)\.com/", url))


def _render_python(jobs: list[dict[str, Any]]) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for j in jobs:
                page = browser.new_page(viewport={"width": j["width"], "height": j["height"]})
                page.route("**/*", lambda r: r.continue_() if _allowed(r.request.url) else r.abort())
                try:
                    page.goto(Path(j["html"]).as_uri(), wait_until="load", timeout=30000)
                except Exception:
                    pass  # a slow font shouldn't cost the picture
                page.wait_for_timeout(300)
                page.screenshot(path=j["png"])
                page.close()
        finally:
            browser.close()


def _render_node(jobs: list[dict[str, Any]]) -> None:
    res = subprocess.run([shutil.which("node") or "node", "-e", _NODE_SCRIPT], input=json.dumps(jobs),
                         capture_output=True, text=True, timeout=60 + 30 * len(jobs), env=clean_env())
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[-400:])


def render_mockups(look_dir: Path, ids: list[str]) -> dict[str, Any]:
    """Take a desktop and a phone picture of each ``<id>.html``. Returns {"pictures": {id: [files]}, "note"}."""
    how = renderer()
    if not how:
        return {"pictures": {}, "note": "pictures skipped: Playwright isn't installed (the pages are still there)"}
    jobs = [{"html": str((look_dir / f"{i}.html").resolve()), "png": str((look_dir / f"{i}{suffix}.png").resolve()),
             "width": w, "height": h} for i in ids for suffix, (w, h) in SIZES.items()]
    try:
        (_render_python if how == "python" else _render_node)(jobs)
    except Exception as e:  # pictures are a help, never a reason to fail
        return {"pictures": {}, "note": f"pictures failed: {str(e)[:300]}"}
    pics = {i: [f"{i}{s}.png" for s in SIZES if (look_dir / f"{i}{s}.png").is_file()] for i in ids}
    return {"pictures": {i: v for i, v in pics.items() if v}, "note": f"pictures taken with Playwright ({how})"}


# -- the design file ---------------------------------------------------------------------------
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "extra"


def _stack(f: dict[str, Any]) -> str:
    fam = f["family"]
    return (f'"{fam}"' if " " in fam else fam) + (f", {f['fallbacks']}" if f.get("fallbacks") else "")


def _colours(d: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """(plain name, token, light hex, dark hex) for every colour of the look."""
    light, dark = d["palette"]["light"], d["palette"]["dark"]
    rows = [(COLOUR_NAMES[k], f"--color-{k.replace('_', '-')}", light[k], dark[k]) for k in PALETTE_KEYS]
    extras = {x["name"]: [x["hex"], x["hex"]] for x in light.get("extra", [])}
    for x in dark.get("extra", []):
        extras.setdefault(x["name"], [x["hex"], x["hex"]])[1] = x["hex"]
    rows += [(n, f"--color-{_slug(n)}", lh, dh) for n, (lh, dh) in extras.items()]
    return rows


def tokens_css(d: dict[str, Any]) -> str:
    fams = [f for f in (d["fonts"]["display"], d["fonts"]["body"]) if f.get("google")]
    imports = ""
    if fams:
        parts = [f"family={quote_plus(f['family'])}" + (f":wght@{';'.join(map(str, f['weights']))}" if f.get("weights") else "")
                 for f in fams]
        imports = f'@import url("https://fonts.googleapis.com/css2?{"&".join(parts)}&display=swap");\n\n'
    rows = _colours(d)
    common = [f"  --font-display: {_stack(d['fonts']['display'])};", f"  --font-body: {_stack(d['fonts']['body'])};",
              f"  --radius: {d['shapes']['radius']};"]
    light = "\n".join(f"  {t}: {lh};" for _, t, lh, _ in rows)
    dark = "\n".join(f"    {t}: {dh};" for _, t, _, dh in rows)
    return (f"/* The look: {d['name']}. Made by Roundtable from design/DESIGN.md: use only these tokens. */\n"
            f"{imports}:root {{\n  color-scheme: light dark;\n{light}\n" + "\n".join(common) + "\n}\n\n"
            f"@media (prefers-color-scheme: dark) {{\n  :root {{\n{dark}\n  }}\n}}\n")


def design_markdown(d: dict[str, Any], note: str = "") -> str:
    f, s = d["fonts"], d["shapes"]
    L = [f"# The look: {d['name']}", "", d["mood"], "",
         "**Use only these tokens.** Every colour, font and corner in the app comes from `design/tokens.css` "
         "(for example `var(--color-accent)`, `var(--font-display)`, `var(--radius)`). Never write a colour code "
         "or a font name anywhere else. Not a web app? Copy the same values into the platform's theme once, and "
         "use the theme everywhere.", "",
         "## Colours", "", "| Colour | Token | Light | Dark |", "|---|---|---|---|"]
    L += [f"| {n} | `{t}` | {lh} | {dh} |" for n, t, lh, dh in _colours(d)]
    L += ["", "## Fonts", "",
          f"- Headings and display: {_stack(f['display'])} (`var(--font-display)`)",
          f"- Body text: {_stack(f['body'])} (`var(--font-body)`)", "",
          "## Shapes", "", f"- Corners: {s['radius']} (`var(--radius)`)", f"- Borders: {s['borders']}",
          f"- Density: {s['density']}", "", "## Motion", "", d["motion"], "",
          "## The signature detail", "", d["signature"], "", "## Never", ""]
    L += [f"- {x}" for x in d["never"]]
    if note:
        L += ["", "## The owner's note when choosing it", "", note]
    return "\n".join(L) + "\n"


def design_text(root: Path, limit: int = 6000) -> str:
    """The project's design file for a prompt, trimmed; empty when there is none."""
    p = Path(root) / DESIGN_FILE
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        text = text[:limit] + "\n... (trimmed; read design/DESIGN.md for the rest)"
    return ("# The design file (design/DESIGN.md): every screen follows it. Use only the tokens in "
            "design/tokens.css for colours, fonts and corners.\n" + text)


# -- the check ---------------------------------------------------------------------------------
CHECKED = {".css", ".html", ".htm", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".kt"}
SKIP_DIRS = {"node_modules", ".git", ".harness", "dist", "build", "vendor", "tests", "test", "__tests__"}
_CSS_HEX = re.compile(r":[^;{}]*?(#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4}))\b")
_QUOTED_HEX = re.compile(r"""["'`]#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})["'`]""")
# '#add' is more often an element id than a colour: three digits count only beside a colour word
_QUOTED_HEX3 = re.compile(r"""(?i)(colou?r|background|fill|stroke|border|shadow)\b.*["'`]#[0-9a-f]{3}["'`]""")
_KT_COLOR = re.compile(r"Color\(\s*0x[0-9a-fA-F]{6,8}")
_FONT = re.compile(r"(font-family\s*:|fontFamily\s*[:=]|FontFamily\()(?![^;\n]*var\()", re.I)


def _is_test(rel: Path) -> bool:
    """Tests and throwaway check scripts (smoke-*.mjs, scratch files): they may name colours on purpose."""
    n = rel.name.lower()
    return (any(t in n for t in (".test.", ".spec.", "test_", "_test."))
            or n.startswith(("smoke", "scratch", "tmp-", "check-")) or "scripts" in rel.parts[:-1])


def check_tokens(project_root: str | Path, limit: int = 40) -> list[dict[str, Any]]:
    """Lines that hard-code a colour or a font instead of using design/tokens.css."""
    root = Path(project_root)
    out: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if (p.suffix.lower() not in CHECKED or not p.is_file() or any(part in SKIP_DIRS for part in rel.parts)
                or rel.as_posix() == TOKENS_FILE or _is_test(rel) or ".min." in p.name or p.stat().st_size > 500_000):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            kinds = []
            if (p.suffix.lower() in (".css", ".html", ".htm") and _CSS_HEX.search(line)) or _QUOTED_HEX.search(line) or _QUOTED_HEX3.search(line) \
                    or (p.suffix.lower() == ".kt" and _KT_COLOR.search(line)):
                kinds.append("colour")
            if _FONT.search(line):
                kinds.append("font")
            for k in kinds:
                out.append({"path": rel.as_posix(), "line": n, "kind": k, "text": line.strip()[:160]})
                if len(out) >= limit:
                    return out
    return out


def findings_text(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""
    lines = "\n".join(f"- {f['path']}:{f['line']} ({f['kind']}): {f['text']}" for f in findings)
    return ("# The design check: these lines use colours or fonts not taken from design/tokens.css\n" + lines
            + "\nReject the task if any of these lines are part of its changes; the fix is to use the tokens "
              "(var(--color-...), var(--font-...)).")


def ui_files(project_root: str | Path) -> bool:
    """True when the project already has screens (HTML, CSS, front-end or Kotlin files)."""
    root = Path(project_root)
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.suffix.lower() in CHECKED and p.is_file() and not any(part in SKIP_DIRS for part in rel.parts) \
                and rel.as_posix() != TOKENS_FILE:
            return True
    return False
