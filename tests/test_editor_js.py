"""The Files tab's page code run under Node with a tiny stand-in for the page (no browser): the colouring
(highlight.js), links from words to files and Markdown like GitHub (preview.js), and the Browser's rule that a
frame only ever opens this computer (browser.js). Skipped where Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "roundtable" / "ui" / "static"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node isn't installed")

SHIM = r"""
globalThis.Node = class {};
class N extends Node { constructor(tag){ super(); this.tagName=tag.toUpperCase(); this.children=[]; this.attrs={}; this.className=""; }
  setAttribute(k,v){ this.attrs[k]=String(v); } getAttribute(k){ return this.attrs[k] ?? null; } removeAttribute(k){ delete this.attrs[k]; }
  addEventListener(){} append(...k){ this.children.push(...k); } replaceChildren(...k){ this.children=k; }
  get textContent(){ return this.children.map(c => c instanceof N ? c.textContent : c.data).join(""); } }
class T extends Node { constructor(d){ super(); this.data=String(d); } }
globalThis.document = { createElement: (t) => new N(t), createTextNode: (d) => new T(d), getElementById: () => null, head: new N("head") };
globalThis.window = { addEventListener(){}, dispatchEvent(){} };
globalThis.location = { hostname: "127.0.0.1", port: "8765", protocol: "http:", hash: "" };
"""

PROBE = r"""
import "./shim.mjs";
const S = process.argv[2];
const hl = await import(S + "/highlight.js");
const pv = await import(S + "/preview.js");
const br = await import(S + "/browser.js");
const flat = (x) => [x].flat(Infinity);
const spans = (x) => flat(x).filter((n) => n.className).map((n) => [n.className, n.textContent]);
const text = (x) => flat(x).map((n) => (n.data !== undefined ? n.data : typeof n === "string" ? n : n.textContent)).join("");
const tags = (n, out = []) => { if (n && n.tagName) { out.push(n.tagName); n.children.forEach((c) => tags(c, out)); } return out; };
const find = (n, tag, out = []) => { if (n && n.tagName) { if (n.tagName === tag) out.push(n); n.children.forEach((c) => find(c, tag, out)); } return out; };
const out = {};
const py = "def f(x):\n    return 'a' # note\n";
out.python = spans(hl.highlight(py, "python"));
out.python_same = text(hl.highlight(py, "python")) === py;
out.html = spans(hl.highlight('<a href="x">hi</a><script>let y = 1;</script>', "html"));
out.json = spans(hl.highlight('{"k": 1, "s": "v"}', "json"));
out.js_hash = spans(hl.highlight("const a = '#nope'; // yes", "javascript"));
out.yaml = spans(hl.highlight("name: lamp\nsize: 3 # big", "yaml"));
out.css = spans(hl.highlight(".lamp { color: #fff; }", "css"));
out.kotlin = spans(hl.highlight("val x = \"a\"", "kt"));
out.shell = spans(hl.highlight("echo 'hi' # say", "sh"));
out.plain = hl.highlight("x", "");
out.links = pv.linkPaths("see src/app.py:12 and http://localhost:5173/x. not nope.py, and ./src/app.py", new Set(["src/app.py"]), { onPath(){}, onUrl(){} })
  .map((n) => (typeof n === "string" ? n : ["link", n.textContent]));
out.no_handlers = pv.linkPaths("src/app.py", new Set(["src/app.py"]), {});
const md = pv.gfm("---\ntitle: Hi\n---\n# Head\n\n| a | b |\n|:-|-:|\n| 1 | 2 |\n\n- [x] done\n- [ ] todo\n  - inner\n\n```py\nx = 1\n```\n\n![badge](https://img.shields.io/x.svg) ![local](pics/a.png) ~~old~~ <b>raw</b>", { picture: (p) => "/raw/pfile?file=" + p });
out.md_tags = tags(md);
out.md_align = find(md, "TH").filter((x) => x.attrs.style).map((x) => x.attrs.style);
out.md_imgs = find(md, "IMG").map((x) => x.attrs.src);
out.md_text = md.textContent.includes("<b>raw</b>");
out.resolve = [pv.resolve("docs", "../img/a.png"), pv.resolve("", "../x"), pv.resolve("a/b", "./c.md")];
out.frames = ["localhost:3000/a", "5173", "http://[::1]:8080", "http://example.com", "http://localhost.evil.com/", "javascript:alert(1)",
  "http://127.0.0.1:8765/", "http://localhost:99999"].map(br.frameUrl);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    d = tmp_path_factory.mktemp("js")
    (d / "shim.mjs").write_text(SHIM, encoding="utf-8")
    (d / "probe.mjs").write_text(PROBE, encoding="utf-8")
    res = subprocess.run([NODE, str(d / "probe.mjs"), STATIC.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_the_colouring_of_each_language(js):
    assert js["python"] == [["hl-k", "def"], ["hl-k", "return"], ["hl-s", "'a'"], ["hl-c", "# note"]] and js["python_same"]
    assert ["hl-t", "<a"] in js["html"] and ["hl-a", "href"] in js["html"] and ["hl-k", "let"] in js["html"]
    assert js["json"] == [["hl-key", '"k"'], ["hl-n", "1"], ["hl-key", '"s"'], ["hl-s", '"v"']]
    assert ["hl-s", "'#nope'"] in js["js_hash"] and ["hl-c", "// yes"] in js["js_hash"]
    assert ["hl-key", "name"] in js["yaml"] and ["hl-c", "# big"] in js["yaml"]
    assert ["hl-n", "#fff"] in js["css"] and ["hl-k", "val"] in js["kotlin"] and ["hl-c", "# say"] in js["shell"]
    assert js["plain"] == ["x"]


def test_paths_that_exist_and_local_addresses_become_links(js):
    assert js["links"] == ["see ", ["link", "src/app.py:12"], " and ", ["link", "http://localhost:5173/x"],
                           ". not nope.py, and ", ["link", "./src/app.py"]]
    assert js["no_handlers"] == ["src/app.py"]


def test_markdown_like_github_and_nothing_from_outside(js):
    t = js["md_tags"]
    assert "TABLE" in t and "THEAD" in t and "H2" in t and t.count("INPUT") == 2 and "S" in t and "CODE" in t
    assert js["md_align"] == ["text-align: left", "text-align: right"]
    assert js["md_imgs"] == ["/raw/pfile?file=pics/a.png"]  # the badge from outside isn't loaded
    assert js["md_text"]  # HTML in Markdown stays text
    assert js["resolve"] == ["img/a.png", "", "a/b/c.md"]


def test_the_browser_only_ever_frames_this_computer_and_never_the_app_itself(js):
    assert js["frames"] == ["http://127.0.0.1:3000/a", "http://127.0.0.1:5173/", "http://127.0.0.1:8080/", "", "", "", "", ""]
