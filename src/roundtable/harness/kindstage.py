"""Kinds, the Orchestrator's side: the project's kind proposed, confirmed, frozen at approval, laid over the
config, told to the planner and the builders, and a Gallery record written when a goal is finished.

A mixin, like the Look and Show stages. ``meta["kind"] = {id, extras, by, why, confirmed, choices}`` and
``meta["parts"] = [{id, name, kind, extras, folder}]`` (one part in version 1). Once the plan is approved the
resolved kind is frozen in ``.harness/kind.json``: editing a kind later never changes a project already being
built ("Use the newest recipe" is ``kind_use_newest``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import kinds as kindlib
from ..core.models import utcnow
from ..kinds import gallery as gallerylib

FROZEN = "kind.json"
REPLAN_WORDS = "Changing it re-plans the work: about the cost of one plan (usually a few cents)."


class KindStage:
    def _kind_say(self, kind: str, data: dict[str, Any]) -> None:
        """An event that never fails (the config is laid over in ``__init__``, before the listener is set)."""
        try:
            self.emit(kind, data)
        except Exception:  # noqa: BLE001
            pass

    # -- where kinds live ------------------------------------------------------------------------------------
    def _kind_home(self) -> Path:
        from ..desktop import app_home

        return app_home()

    def _kind_catalog(self) -> kindlib.Catalog:
        return kindlib.load_all(self._kind_home())

    def _kind_frozen_path(self) -> Path:
        return self.project.dir / FROZEN

    def _kind_fixed(self) -> bool:
        meta = self.project.meta() if self.project.exists else {}
        return bool(meta.get("plan_approved") and self.project.plan_doc())

    def _kind(self) -> kindlib.Kind | None:
        """The project's kind: the frozen copy once approved, else the chosen one resolved; None for none."""
        frozen = self._kind_frozen_path()
        if frozen.is_file():
            try:
                return kindlib.Kind.from_dict(json.loads(frozen.read_text(encoding="utf-8")).get("kind") or {})
            except (OSError, ValueError, TypeError):
                pass
        if not self.project.exists:
            return None
        chosen = self.project.meta().get("kind") or {}
        if not chosen.get("id"):
            return None
        try:
            k = kindlib.resolve(chosen["id"], chosen.get("extras") or [], self._kind_catalog())
        except kindlib.KindError as e:
            self._kind_say("kind_error", {"error": str(e)})
            return None
        if self._kind_fixed():  # approved before anyone froze it (an older approve): freeze it now
            self._kind_freeze(k)
        return k

    def _kind_freeze(self, kind: kindlib.Kind | None = None) -> None:
        """Write the snapshot (at approval: ``approve()`` calls this). Never overwrites an existing one."""
        p = self._kind_frozen_path()
        if p.is_file():
            return
        if kind is None:
            chosen = (self.project.meta() or {}).get("kind") or {}
            if not chosen.get("id"):
                return
            try:
                kind = kindlib.resolve(chosen["id"], chosen.get("extras") or [], self._kind_catalog())
            except kindlib.KindError:
                return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": utcnow(), "kind": kind.to_dict()}, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")

    def kind_use_newest(self) -> dict[str, Any]:
        """"Use the newest recipe": the frozen copy replaced by the kind as it is now (the owner's button)."""
        p = self._kind_frozen_path()
        chosen = (self.project.meta() or {}).get("kind") or {}
        if not chosen.get("id"):
            return {"ok": False, "reply": "This project has no kind yet."}
        try:
            k = kindlib.resolve(chosen["id"], chosen.get("extras") or [], self._kind_catalog())
        except kindlib.KindError as e:
            return {"ok": False, "reply": f"Couldn't use the newest recipe: {e}."}
        if p.is_file():
            p.unlink()
        if self._kind_fixed():
            self._kind_freeze(k)
        self.cfg = self._kind_cfg(self._settle_cfg(self.base_cfg.for_profile(self.profile())))
        self.emit("kind", {"id": k.id, "newest": True})
        return {"ok": True, "reply": f"This project now uses the newest {k.name} recipe, from the next task on."}

    # -- the config ------------------------------------------------------------------------------------------------
    def _kind_cfg(self, cfg):
        """The config with the kind laid over it (prompts appended, roles added); unchanged without a kind."""
        try:
            k = self._kind()
            return kindlib.apply_to_config(cfg, k) if k else cfg
        except Exception as e:  # noqa: BLE001 - a kind is a help; it never stops a run
            self._kind_say("kind_error", {"error": str(e)[:300]})
            return cfg

    # -- choosing ------------------------------------------------------------------------------------------------------
    def _kind_propose(self, goal: str) -> dict[str, Any] | None:
        """Pick a kind for a new project (free: a word match). Kept as Roundtable's guess until confirmed."""
        meta = self.project.meta()
        if (meta.get("kind") or {}).get("id"):
            return meta["kind"]
        try:
            cat = self._kind_catalog()
            choices = kindlib.propose(goal, cat)
        except Exception as e:  # noqa: BLE001
            self._kind_say("kind_error", {"error": str(e)[:300]})
            return None
        if not choices:
            return None
        kid, _, why = choices[0]
        chosen = {"id": kid, "extras": kindlib.propose_extras(goal, kid, cat), "by": "roundtable", "why": why,
                  "confirmed": False, "choices": [{"id": c[0], "why": c[2]} for c in choices[:3]]}
        self._kind_save(chosen, cat)
        return chosen

    def _kind_save(self, chosen: dict[str, Any], cat: kindlib.Catalog) -> None:
        meta = self.project.meta()
        meta["kind"] = chosen
        k = cat.kinds.get(chosen["id"])
        meta["parts"] = [{"id": "main", "name": k.name if k else chosen["id"], "kind": chosen["id"],
                          "extras": list(chosen.get("extras") or []), "folder": "."}]
        self.project.save_meta(meta)
        self.cfg = self._kind_cfg(self._settle_cfg(self.base_cfg.for_profile(self.profile())))
        self.emit("kind", {"id": chosen["id"], "extras": chosen.get("extras") or [], "by": chosen.get("by")})

    def set_kind(self, kind_id: str, extras: list[str] | None = None, by: str = "owner",
                 replan: bool = True) -> dict[str, Any]:
        """The owner (or autopilot) confirms or changes the kind. Before approval a change re-plans; after
        approval the kind is fixed ("Try another way" or a new goal instead)."""
        from .orchestrator import HarnessError

        if self._kind_fixed():
            raise HarnessError("The kind is fixed once the plan is approved. To make it as something else, use "
                               "Try another way, or start a new goal.")
        cat = self._kind_catalog()
        k = cat.kinds.get(kind_id)
        if not k:
            raise HarnessError(f"There's no kind called {kind_id!r}. Choose one from the list.")
        if not k.usable:
            raise HarnessError(f"{k.name} isn't ready yet. Choose another, or Something else.")
        old = (self.project.meta() or {}).get("kind") or {}
        extras = list(dict.fromkeys(extras if extras is not None else (old.get("extras") or [])))
        try:
            kindlib.resolve(kind_id, extras, cat)
        except kindlib.KindError as e:
            raise HarnessError(str(e)[:1].upper() + str(e)[1:] + ".") from None
        changed = old.get("id") != kind_id or sorted(old.get("extras") or []) != sorted(extras)
        chosen = {"id": kind_id, "extras": extras, "by": by,
                  "why": "you chose it" if by == "owner" else (old.get("why") or ""), "confirmed": True,
                  "choices": old.get("choices") or []}
        self._kind_save(chosen, cat)
        doc = self.project.plan_doc()
        replanned = False
        if doc:
            doc["kind"] = self._kind_doc()
            self.project.save_plan_doc(doc)
            if changed and replan:
                extra_names = [cat.extras[e].name for e in extras if e in cat.extras]
                self.revise_plan(f"The owner says this is a {k.name}"
                                 + (f" with {', '.join(extra_names)}" if extra_names else "")
                                 + ". Re-plan it as one: follow 'What this project is' below.", by=by)
                doc = self.project.plan_doc() or doc
                doc["kind"] = self._kind_doc()
                self.project.save_plan_doc(doc)
                replanned = True
            self._publish_plan()
        return {"kind": self._kind_doc(), "replanned": replanned,
                "reply": (f"It's a {k.name} now. The plan was made again for it." if replanned
                          else f"Kept as a {k.name}.")}

    def _kind_doc(self) -> dict[str, Any] | None:
        """The first card on the plan: what Roundtable thinks this is, why, and the other choices."""
        chosen = (self.project.meta() or {}).get("kind") or {}
        k = self._kind()
        if not k:
            return None
        cat = self._kind_catalog()
        state = kindlib.read_state(self._kind_home())
        fixed = self._kind_fixed()
        why = chosen.get("why") or ""
        if chosen.get("confirmed"):
            question = f"This is a {k.name}" + (f" with {', '.join(e['name'] for e in k.extras)}" if k.extras else "") + "."
        else:
            question = f"This looks like a {k.name}" + (f", {why}" if why else "") + ". Right?"
        ids = [c["id"] for c in chosen.get("choices") or [] if c.get("id") in cat.kinds][:3]
        ids = list(dict.fromkeys([k.id, *ids, *(["other"] if "other" in cat.kinds else [])]))
        return {"id": k.id, "name": k.name, "blurb": k.blurb, "by": chosen.get("by", ""), "why": why,
                "confirmed": bool(chosen.get("confirmed")), "fixed": fixed, "question": question,
                "status": kindlib.status_of(k, state), "status_words": kindlib.status_words(k, state),
                "extras": [{"id": e["id"], "name": e["name"]} for e in k.extras],
                "choices": [{"id": i, "name": cat.kinds[i].name if i != "other" else "Something else",
                             "recommended": i == k.id} for i in ids],
                "change_words": "" if fixed else REPLAN_WORDS,
                "frozen": self._kind_frozen_path().is_file()}

    def _kind_ask(self) -> dict[str, Any] | None:
        """The kind card as an ask (asks.py wraps it: kind ``kind``, answered by ``set_kind``)."""
        d = self._kind_doc()
        if not d or d["confirmed"] or d["fixed"]:
            return None
        return {"header": "Kind", "question": d["question"], "recommended": d["id"],
                "options": [{"id": c["id"], "label": c["name"]} for c in d["choices"]], "detail": d["change_words"]}

    # -- what the planner and the builders read ----------------------------------------------------------------------------
    def _kind_plan_part(self) -> str:
        k = self._kind()
        return f"\n\n{kindlib.plan_brief(k)}" if k else ""

    def _kind_worker_part(self, role: str) -> str:
        k = self._kind()
        return kindlib.worker_brief(k, role) if k else ""

    def _kind_proof(self) -> list[dict[str, Any]]:
        k = self._kind()
        return kindlib.proof_plan(k) if k else []

    def _kind_proof_plan(self):
        """The kind's checks handed to the proof stage, when that is there (harness/proof.py ``plan_for``)."""
        try:
            from . import proof as prooflib  # wave 3's proof stage; not every copy has it yet
        except ImportError:
            return None
        fn = getattr(prooflib, "plan_for", None)
        return fn(self._kind_proof()) if fn else None

    # -- the Gallery -------------------------------------------------------------------------------------------------------------
    def _kind_proof_lines(self, tasks: list, kind: kindlib.Kind | None) -> list[dict[str, Any]]:
        """Each proof check with passed True, False or None (not checked). The proof stage's own results win
        when it has them (``proof.results_for(root, items, tasks)``); otherwise what Roundtable can see here."""
        items = kindlib.proof_plan(kind) if kind else []
        if not items:
            return []
        try:
            from . import proof as prooflib

            fn = getattr(prooflib, "results_for", None)
            if fn:
                got = fn(self.project.root, items, tasks)
                if isinstance(got, list):
                    return got
        except Exception:  # noqa: BLE001 - not there, or it failed: fall back to what we can see
            pass
        from . import showit

        ids = {t.id for t in tasks}
        shots = [r for r in showit.history(self.project.root, limit=200) if r.get("task") in ids]
        newest = shots[0] if shots else None
        out = []
        for i in items:
            passed: bool | None = None
            if i.get("status") == "not_yet":
                passed = None
            elif i["how"] in ("page_opens", "picture") and newest:
                if newest.get("failed") or (i["how"] == "page_opens" and newest.get("errors")):
                    passed = False
                elif newest.get("pictures"):
                    passed = True
            elif i["how"] == "file_exists" and i.get("path"):
                passed = any(self.project.root.glob(i["path"]))
            out.append({"id": i["id"], "words": i["words"], "passed": passed, "optional": i.get("optional", False),
                        "status": i.get("status", "trial")})
        return out

    def _kind_pictures(self, tasks: list) -> list[Path]:
        from . import showit

        ids = {t.id for t in tasks}
        for r in showit.history(self.project.root, limit=200):
            if r.get("task") in ids and r.get("pictures"):
                d = showit.shots_root(self.project.root) / r.get("dir", "")
                return [d / name for name in (r["pictures"] or {}).values() if (d / name).is_file()]
        return []

    def _kind_outputs(self) -> list[dict[str, str]]:
        root = self.project.root
        out = []
        for pattern, what in (("dist/*.apk", "apk"), ("*.apk", "apk"), ("dist/*.exe", "exe"), ("*.exe", "exe"),
                              ("dist/*.zip", "zip"), ("index.html", "page"), ("public/index.html", "page")):
            for p in sorted(root.glob(pattern))[:3]:
                out.append({"kind": what, "path": p.relative_to(root).as_posix()})
        return out[:8]

    def _gallery_record(self, tasks: list) -> dict[str, Any] | None:
        """One Gallery record for the goal just finished (written once; never fails the run)."""
        try:
            return self._gallery_write(tasks)
        except Exception as e:  # noqa: BLE001
            self._kind_say("gallery_error", {"error": str(e)[:300]})
            return None

    def _gallery_write(self, tasks: list) -> dict[str, Any] | None:
        meta = self.project.meta()
        goal_index = len(meta.get("goals") or [1]) - 1
        mine = [t for t in tasks if t.goal_index == goal_index]
        done = [t for t in mine if t.status == "done"]
        if not done:
            return None
        k = self._kind()
        doc = self.project.plan_doc() or {}
        ids = {t.id for t in mine}
        seconds = 0.0
        p = self.project.dir / "metrics.jsonl"
        if p.is_file():
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if row.get("task") in ids:
                    seconds += float(row.get("seconds") or 0)
        counted = round(sum(float(a.get("cost_usd") or 0) for t in mine for a in t.attempts), 4)
        real = None
        try:
            real = self._real_spent()
        except Exception:  # noqa: BLE001 - only when the providers say
            real = None
        goal = meta["goals"][goal_index]
        entry = {
            "project": self.project.root.name, "goal": gallerylib.goal_key(goal_index), "goal_index": goal_index,
            "path": str(self.project.root), "title": doc.get("title") or goal.split("\n", 1)[0][:80],
            "summary": doc.get("summary") or "", "goal_text": goal[:500],
            "kind": {"id": k.id, "name": k.name} if k else {"id": "", "name": ""},
            "extras": [{"id": e["id"], "name": e["name"]} for e in (k.extras if k else [])],
            "finished_at": utcnow(), "tasks": len(done), "minutes": round(seconds / 60, 1),
            "cost": {"counted_usd": counted, "real_usd": real}, "profile": self.profile(),
            "models": [{"task": t.id, "role": t.role, "model": (t.attempts[-1] or {}).get("model", "")}
                       for t in done if t.attempts],
            "proof": self._kind_proof_lines(mine, k), "outputs": self._kind_outputs(), "commit": self._head() or "",
        }
        res = gallerylib.record(self._kind_home(), entry, self._kind_pictures(done))
        if res["written"]:
            self.emit("gallery", {"project": entry["project"], "goal": entry["goal"], "title": entry["title"]})
            self._gallery_hub(res["entry"])
        return res["entry"]

    def _gallery_hub(self, entry: dict[str, Any]) -> None:
        try:
            hub = self._hub()
            if not hub:
                return
            from ..core.store import TextFile

            files = {k: TextFile(v) for k, v in gallerylib.hub_files(entry, self._hub_name()).items()}
            hub.store.write_json(files, f"gallery({self._hub_name()}): {entry['goal']}")
        except Exception as e:  # noqa: BLE001 - the hub is optional
            self.emit("hub_error", {"error": f"gallery: {e}"})

