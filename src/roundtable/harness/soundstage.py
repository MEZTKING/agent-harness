"""The sound job: effects and music made by the service the owner picked, priced first (wave 9).

A stage mixin like the picture job (orchestrator ``_run_image_task``). A stub with its frozen signature:
Helper w9-sound fills it (licence check, the cap through soundprice.py, the check of the file, the fallback
to a sound made in code, ``assets/sounds/CREDITS.md``). Until then a sound task is never run: it says so.
"""

from __future__ import annotations


class SoundStage:
    def _run_sound_task(self, task, role) -> bool:
        task.summary = "sound isn't set up"
        return False
