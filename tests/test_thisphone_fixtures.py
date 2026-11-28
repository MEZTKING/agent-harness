"""This phone's answers to the four calls the phone checks against the PC's (wave 9, ThisPhoneSameAnswersTest.kt).

The fixtures in mobile/app/src/test/resources/thisphone/ are This phone's real answers on a made-up project.
With UPDATE_GOLDENS=1 this test writes them again; otherwise it checks each call still answers with the same keys
the fixture has, so a change to This phone's answers can't slip past the phone's own test unseen."""

import json
import os
from pathlib import Path
from urllib.parse import urlencode

from .test_onphone import call, clean_env  # noqa: F401  (fixture)
from .test_onphone_same_answers import CALLS, both  # noqa: F401  (fixture)

OUT = Path(__file__).resolve().parents[1] / "mobile/app/src/test/resources/thisphone"
NAMES = {"/api/files/preview": "file_preview", "/api/recall/ask": "recall_ask", "/api/usage": "usage",
         "/api/agents": "agents"}


def _keys(v):
    if isinstance(v, dict):
        return {k: _keys(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_keys(v[0])] if v else []
    return None


def test_this_phones_fixtures_match_its_answers(both):  # noqa: F811
    srv, desk, project = both
    write = os.environ.get("UPDATE_GOLDENS") == "1"
    for method, route, query, body in CALLS:
        q = {k: v.replace("{project}", project) for k, v in query.items()}
        status, data = call(srv, method, route + ("?" + urlencode(q) if q else ""), body)
        assert status == 200, route
        f = OUT / f"{NAMES[route]}.json"
        if write:
            text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False).replace(project,
                                                                                         "/home/owner/lab/made-up-bakery")
            text = text.replace(os.path.dirname(os.path.dirname(project)), "/home/owner")
            OUT.mkdir(parents=True, exist_ok=True)
            f.write_text(text + "\n", encoding="utf-8")
            continue
        kept = json.loads(f.read_text(encoding="utf-8"))
        assert set(_keys(data)) == set(_keys(kept)), f"{f.name}: run with UPDATE_GOLDENS=1 to write it again"
