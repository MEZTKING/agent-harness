"""Wave 9, step 0: This phone answers like the PC.

A made-up home served by ``onphone.make_local_server`` (Roundtable on the phone itself), and the same home
read through the desktop's own ``dispatch`` (a second ``UIApp`` over the same hub and harness files, as the
PC's window would make it), give answers of the same shape for the four calls the phone's Part B leans on:
a file's preview, Ask (the price first, nothing spent), usage and the named agents.
"""

import json
import threading
import zipfile

import pytest

from roundtable import onphone
from roundtable.improve.lab import Lab
from roundtable.ui.server import UIApp

from .test_onphone import TOKEN, call, clean_env  # noqa: F401  (fixture)


def shape(v, depth=0):
    """The keys and kinds of an answer, not its values (times and paths differ between two servers)."""
    if isinstance(v, dict):
        return {k: shape(x, depth + 1) for k, x in sorted(v.items())} if depth < 3 else "object"
    if isinstance(v, list):
        return [shape(v[0], depth + 1)] if v else []
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return "null" if v is None else "text"


@pytest.fixture
def both(tmp_path, clean_env):  # noqa: F811
    home = tmp_path / "home"
    import os

    os.environ["ROUNDTABLE_WORKSPACES"] = str(tmp_path / "workspaces")
    httpd, phone_app = onphone.make_local_server(home, 0, TOKEN)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    project = tmp_path / "workspaces" / "made-up-bakery"
    (project / ".harness").mkdir(parents=True)
    (project / ".harness" / "project.json").write_text(json.dumps({"goals": ["a made-up bakery"], "status": "done"}),
                                                       encoding="utf-8")
    (project / "README.md").write_text("# A made-up bakery\n", encoding="utf-8")
    with zipfile.ZipFile(project / "menu.zip", "w") as z:  # a file with a richer view (an archive's list)
        z.writestr("bread.txt", "a made-up loaf")
    Lab(phone_app.cfg().lab_dir).register_project(project)
    desk = UIApp(str(phone_app.hub_config_path), str(phone_app.harness_config_path), agent=phone_app.agent,
                 projects_dir=str(tmp_path / "workspaces"))
    srv = {"base": f"http://127.0.0.1:{httpd.server_address[1]}"}
    yield srv, desk, str(project)
    httpd.shutdown()
    httpd.server_close()


CALLS = [
    ("GET", "/api/files/preview", {"path": "{project}", "file": "menu.zip"}, None),
    ("POST", "/api/recall/ask", {}, {"question": "what does the bakery sell?", "confirm": False}),
    ("GET", "/api/usage", {}, None),
    ("GET", "/api/agents", {}, None),
]


@pytest.mark.parametrize("method,route,query,body", CALLS, ids=[c[1] for c in CALLS])
def test_this_phone_gives_the_same_shape_as_the_pc(both, method, route, query, body):
    from urllib.parse import urlencode

    srv, desk, project = both
    q = {k: v.replace("{project}", project) for k, v in query.items()}
    status, on_phone = call(srv, method, route + ("?" + urlencode(q) if q else ""), body)
    assert status == 200, on_phone
    on_pc = desk.dispatch(method, route, {k: [v] for k, v in q.items()}, body or {})
    on_pc = json.loads(json.dumps(on_pc, default=str))
    assert shape(on_phone) == shape(on_pc)


def test_ask_from_this_phone_spends_nothing_without_a_yes(both):
    srv, desk, project = both
    status, data = call(srv, "POST", "/api/recall/ask", {"question": "what does the bakery sell?", "confirm": False})
    assert status == 200 and not data.get("answer")
