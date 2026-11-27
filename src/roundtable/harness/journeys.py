"""Using the finished app as a person would: each done-list item's steps, walked in a real browser.

The steps have a fixed vocabulary (the done list's, harness/donelist.py):

    open [path]          open the app (or one of its own pages)
    click <text>         click the button, link or thing showing that text
    type <text> [into]   type into the field labelled or hinted ``into`` (else where the cursor is)
    press <key>          press a key (Enter, ArrowLeft, Space…)
    wait [seconds]       wait (at most 10 seconds)
    expect_text <text>   that text must show within 5 seconds
    expect_no_errors     the page must have logged no errors so far

A step may be written ``"click Start"``, ``{"click": "Start"}`` or ``{"do": "click", "text": "Start"}``;
``type`` takes ``{"type": "Ann", "into": "Name"}``. ``walk`` runs every item in Playwright (Python's, or
Node's as the pictures do) and gives each ``{passed, failed_step, why, errors, picture}``. Only the app's own
address may load (``showit._may_load``). Without Playwright every item is ``passed: None`` (unchecked) with
the reason – never a pass.

Beta: walked for real here in the cloud with Node's Playwright; not yet tried on the owner's PC.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import look as looklib
from .safeenv import clean_env

VERBS = ("open", "click", "type", "press", "wait", "expect_text", "expect_no_errors")
MAX_STEPS = 30
MAX_WAIT = 10.0
STEP_MS = 5000
NO_PLAYWRIGHT = "couldn't be tried: Playwright isn't installed on this computer"


class NoWalker(RuntimeError):
    """Playwright isn't installed: the journeys stay unchecked."""


def step_of(raw: Any) -> dict[str, Any] | None:
    """One step as {do, text, into}, or None when it isn't one of the known verbs."""
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        verb, _, rest = s.partition(" ")
        verb = verb.strip().lower().rstrip(":")
        rest = rest.strip().strip("'\"")
        into = ""
        if verb == "type":
            m = re.match(r"^['\"]?(.*?)['\"]?\s+into\s+['\"]?(.+?)['\"]?$", rest)
            if m:
                rest, into = m.group(1), m.group(2)
        return {"do": verb, "text": rest, "into": into} if verb in VERBS else None
    if isinstance(raw, dict):
        verb = str(raw.get("do") or raw.get("action") or raw.get("step") or "").strip().lower()
        text = raw.get("text", raw.get("target", raw.get("value", raw.get("key", raw.get("path", raw.get("seconds", ""))))))
        if not verb:
            known = [k for k in raw if str(k).lower() in VERBS]
            if len(known) != 1:
                return None
            verb = str(known[0]).lower()
            text = raw[known[0]]
        if verb not in VERBS:
            return None
        return {"do": verb, "text": "" if text is None or text is True else str(text).strip(),
                "into": str(raw.get("into") or raw.get("field") or "").strip()}
    return None


def steps_of(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The item's steps, cleaned; None when any step isn't one the harness can do (the item is then looked
    at instead). An item with no steps just opens the app and expects no errors."""
    raw = item.get("steps")
    if raw in (None, "", []):
        return [{"do": "open", "text": "", "into": ""}, {"do": "expect_no_errors", "text": "", "into": ""}]
    if isinstance(raw, str):
        raw = [ln for ln in re.split(r"\n|;", raw) if ln.strip()]
    if not isinstance(raw, list):
        return None
    out = [step_of(s) for s in raw[:MAX_STEPS]]
    if any(s is None for s in out):
        return None
    if not out or out[0]["do"] != "open":  # always start at the app
        out.insert(0, {"do": "open", "text": "", "into": ""})
    return out  # type: ignore[return-value]


def step_words(step: dict[str, Any]) -> str:
    d, t = step["do"], step.get("text") or ""
    return {"open": f"open {t or 'the app'}", "click": f"click “{t}”",
            "type": f"type “{t}”" + (f" into {step['into']}" if step.get("into") else ""),
            "press": f"press {t}", "wait": f"wait {t or '1'} s", "expect_text": f"see “{t}”",
            "expect_no_errors": "no errors on the page"}.get(d, d)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip(".-") or "item"


# -- the runners -----------------------------------------------------------------------------------------------
_NODE_SCRIPT = r"""
const { chromium } = require('playwright');
let input = '';
process.stdin.on('data', (c) => (input += c));
process.stdin.on('end', async () => {
  const jobs = JSON.parse(input);
  const out = [];
  const fonts = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;
  const browser = await chromium.launch();
  try {
    for (const j of jobs) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      const page = await ctx.newPage();
      const errors = [];
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      page.on('pageerror', (e) => errors.push(String(e && e.message || e)));
      await page.route('**/*', (r) => {
        const u = r.request().url();
        return (u.startsWith(j.base) || u.startsWith('data:') || u.startsWith('blob:') || fonts.test(u)) ? r.continue() : r.abort();
      });
      let failed = null, why = '';
      for (let i = 0; i < j.steps.length; i++) {
        const s = j.steps[i];
        try {
          if (s.do === 'open') {
            const u = s.text ? new URL(s.text.replace(/^\//, ''), j.url).href : j.url;
            if (!u.startsWith(j.base)) throw new Error('that address is not the app\'s own');
            await page.goto(u, { waitUntil: 'load', timeout: 20000 });
            await page.waitForTimeout(300);
          } else if (s.do === 'click') {
            let t = page.getByRole('button', { name: s.text });
            if (!(await t.count())) t = page.getByRole('link', { name: s.text });
            if (!(await t.count())) t = page.getByText(s.text);
            await t.first().click({ timeout: j.step_ms });
            await page.waitForTimeout(250);
          } else if (s.do === 'type') {
            if (s.into) {
              let f = page.getByLabel(s.into);
              if (!(await f.count())) f = page.getByPlaceholder(s.into);
              await f.first().fill(s.text, { timeout: j.step_ms });
            } else { await page.keyboard.type(s.text); }
          } else if (s.do === 'press') {
            await page.keyboard.press(s.text || 'Enter');
            await page.waitForTimeout(200);
          } else if (s.do === 'wait') {
            await page.waitForTimeout(Math.min(j.max_wait, Math.max(0, parseFloat(s.text) || 1)) * 1000);
          } else if (s.do === 'expect_text') {
            await page.getByText(s.text).first().waitFor({ state: 'visible', timeout: j.step_ms });
          } else if (s.do === 'expect_no_errors') {
            if (errors.length) throw new Error('the page logged errors: ' + errors.slice(0, 3).join(' / '));
          }
        } catch (e) { failed = i; why = String(e && e.message || e).split('\n')[0].slice(0, 300); break; }
      }
      try { await page.screenshot({ path: j.png }); } catch (e) { /* the picture is a help */ }
      out.push({ id: j.id, passed: failed === null, failed_step: failed, why, errors: errors.slice(0, 20) });
      await ctx.close();
    }
  } finally { await browser.close(); }
  process.stdout.write(JSON.stringify(out));
});
"""


def _walk_python(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from urllib.parse import urljoin

    from playwright.sync_api import sync_playwright

    from .showit import _may_load

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for j in jobs:
                ctx = browser.new_context(viewport={"width": 1280, "height": 800})
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda exc, e=errors: e.append(str(exc)))
                page.route("**/*", lambda r, b=j["base"]: r.continue_() if _may_load(r.request.url, b) else r.abort())
                failed, why = None, ""
                for i, s in enumerate(j["steps"]):
                    try:
                        d, t, ms = s["do"], s.get("text") or "", j["step_ms"]
                        if d == "open":
                            u = urljoin(j["url"], t.lstrip("/")) if t else j["url"]
                            if not u.startswith(j["base"]):
                                raise RuntimeError("that address is not the app's own")
                            page.goto(u, wait_until="load", timeout=20000)
                            page.wait_for_timeout(300)
                        elif d == "click":
                            loc = page.get_by_role("button", name=t)
                            if not loc.count():
                                loc = page.get_by_role("link", name=t)
                            if not loc.count():
                                loc = page.get_by_text(t)
                            loc.first.click(timeout=ms)
                            page.wait_for_timeout(250)
                        elif d == "type":
                            if s.get("into"):
                                f = page.get_by_label(s["into"])
                                if not f.count():
                                    f = page.get_by_placeholder(s["into"])
                                f.first.fill(t, timeout=ms)
                            else:
                                page.keyboard.type(t)
                        elif d == "press":
                            page.keyboard.press(t or "Enter")
                            page.wait_for_timeout(200)
                        elif d == "wait":
                            try:
                                sec = float(t or 1)
                            except ValueError:
                                sec = 1.0
                            page.wait_for_timeout(min(j["max_wait"], max(0.0, sec)) * 1000)
                        elif d == "expect_text":
                            page.get_by_text(t).first.wait_for(state="visible", timeout=ms)
                        elif d == "expect_no_errors" and errors:
                            raise RuntimeError("the page logged errors: " + " / ".join(errors[:3]))
                    except Exception as e:  # the step failed: that is the answer
                        failed, why = i, str(e).splitlines()[0][:300] if str(e) else type(e).__name__
                        break
                try:
                    page.screenshot(path=j["png"])
                except Exception:  # the picture is a help
                    pass
                out.append({"id": j["id"], "passed": failed is None, "failed_step": failed, "why": why,
                            "errors": errors[:20]})
                ctx.close()
        finally:
            browser.close()
    return out


def _walk_node(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(len(j["steps"]) for j in jobs)
    res = subprocess.run([shutil.which("node") or "node", "-e", _NODE_SCRIPT], input=json.dumps(jobs),
                         capture_output=True, text=True, timeout=90 + 15 * total, env=clean_env())
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[-400:])
    return json.loads(res.stdout or "[]")


def default_walker(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    how = looklib.renderer()
    if not how:
        raise NoWalker(NO_PLAYWRIGHT)
    return (_walk_python if how == "python" else _walk_node)(jobs)


# -- the walk ------------------------------------------------------------------------------------------------
def walk(url: str, base: str, items: list[dict[str, Any]], out_dir: Path,
         walker: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None) -> dict[str, dict[str, Any]]:
    """Walk each item's steps on the app at ``url`` (only ``base`` may load). Returns {item id: result} with
    result = {passed: True/False/None, failed_step, step, why, errors, picture, words}. Never raises."""
    out_dir = Path(out_dir)
    jobs: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    for item in items:
        iid = str(item.get("id") or "")
        steps = steps_of(item)
        if steps is None:
            results[iid] = {"passed": None, "failed_step": None, "why": "its steps aren't ones the harness can do",
                            "errors": [], "picture": "", "words": "Couldn't be walked: its steps aren't ones "
                                                                  "the harness knows."}
            continue
        jobs.append({"id": iid, "url": url, "base": base, "steps": steps, "step_ms": STEP_MS, "max_wait": MAX_WAIT,
                     "png": str(out_dir / f"{_safe(iid)}.png")})
    if not jobs:
        return results
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        got = (walker or default_walker)(jobs)
    except NoWalker as e:
        for j in jobs:
            results[j["id"]] = {"passed": None, "failed_step": None, "why": str(e), "errors": [], "picture": "",
                                "words": f"Couldn't be walked: {str(e)}."}
        return results
    except Exception as e:  # noqa: BLE001 - a walk is a help: written down, never raised
        for j in jobs:
            results[j["id"]] = {"passed": None, "failed_step": None, "why": f"the browser failed: {str(e)[:300]}",
                                "errors": [], "picture": "", "words": "Couldn't be walked: the browser failed."}
        return results
    by_id = {str(r.get("id")): r for r in got or [] if isinstance(r, dict)}
    for j in jobs:
        r = by_id.get(j["id"])
        if r is None:
            results[j["id"]] = {"passed": None, "failed_step": None, "why": "the browser gave no answer for it",
                                "errors": [], "picture": "", "words": "Couldn't be walked: no answer."}
            continue
        fs = r.get("failed_step")
        step = j["steps"][fs] if isinstance(fs, int) and 0 <= fs < len(j["steps"]) else None
        passed = bool(r.get("passed")) and step is None
        pic = Path(j["png"]).name if Path(j["png"]).is_file() else ""
        errors = [str(e)[:300] for e in (r.get("errors") or [])][:20]
        if passed:
            words = f"Walked it: all {len(j['steps'])} steps worked."
        elif step is not None:
            words = f"Stopped at step {fs + 1} ({step_words(step)}): {str(r.get('why') or 'it did not happen')[:200]}"
        else:
            words = f"It didn't work: {str(r.get('why') or 'no reason given')[:200]}"
        results[j["id"]] = {"passed": passed, "failed_step": fs if step is not None else None,
                            "step": step_words(step) if step else "", "why": str(r.get("why") or "")[:300],
                            "errors": errors, "picture": pic, "words": words}
    return results
