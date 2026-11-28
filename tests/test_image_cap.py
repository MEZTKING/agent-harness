"""The project's own picture limit (wave 9, limits.max_image_usd): the next picture is never bought past it."""

import json

from roundtable.harness import projectsettings
from roundtable.providers.base import Usage
from roundtable.providers.scripted import ScriptedImages

from .test_harness import RAW, Brain, make


class PricedImages(ScriptedImages):
    def generate(self, model, prompt, options=None):
        data, ext, _ = super().generate(model, prompt, options)
        return data, ext, Usage(output_tokens=1, cost_usd=0.30)


def _plan(n):
    return [{"id": f"P{i}", "title": f"picture {i}", "role": "designer", "description": f"a made-up picture {i}",
             "acceptance": "png", "depends_on": [], "output_path": f"assets/p{i}.png"} for i in range(1, n + 1)]


def test_pictures_stop_at_the_projects_limit(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw.setdefault("limits", {})["max_image_usd"] = 0.5
    orch, a, b, img, events = make(tmp_path, raw=raw, brain=Brain(plan=_plan(3)))
    priced = PricedImages()
    orch.cfg.register("img", priced)
    orch.start("three made-up pictures")
    orch.run()
    tasks = {t.id: t for t in orch.project.tasks()}
    assert tasks["P1"].status == "done" and len(priced.prompts) == 1  # the second would pass $0.50
    stopped = [t for t in tasks.values() if t.status != "done"]
    assert stopped and all("limit of $0.50" in t.summary for t in stopped)
    assert any(k == "image_cap" for k, _ in events)


def test_no_limit_buys_every_picture_and_the_setting_is_known(tmp_path):
    orch, a, b, img, events = make(tmp_path, brain=Brain(plan=_plan(2)))
    orch.start("two made-up pictures")
    assert orch.run() == "done" and len(img.prompts) == 2
    assert orch.cfg.limits.max_image_usd == 0.0
    assert "max_image_usd" in projectsettings.LIMIT_KEYS
    assert projectsettings.coerce("limits", {"max_image_usd": "0.5"}) == {"max_image_usd": 0.5}
