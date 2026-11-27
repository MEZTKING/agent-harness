"""Kinds: what sort of thing a project makes, as data (plans/kinds.md, docs/kinds.md).

A kind is a folder: ``kind.yaml`` (schema ``kind@1``), optional ``prompts/<role>.md``, ``card.md`` and
``template/``. An extra (``_extras/<id>/extra.yaml``, schema ``extra@1``) stacks on a kind: packaging as an
APK or an EXE. Nothing in a kind is code: the engine stays the same, a kind only changes the roles' prompts,
the plan's shape, what is checked and what the owner reads.

Kinds are looked for in three places, later ones winning: the built-in ones (``roundtable/kinds/builtin``),
the owner's own (``<app folder>/kinds``), and a project's frozen copy (``.harness/kind.json``, written at
approval; see harness/kindstage.py).

The file may only say ``trial`` or ``not_yet``. "Proven" is earned: a gallery entry built with the kind
where every proof item that counts passed (``status_of``; kept in ``<app folder>/kinds/state.json``).
"""

from __future__ import annotations

import copy
import io
import json
import re
import stat
import statistics
import zipfile
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

SCHEMA, EXTRA_SCHEMA = "kind@1", "extra@1"
STATUSES = ("trial", "not_yet")
STATUS_WORDS = {"proven": "Proven", "trial": "On trial", "not_yet": "Not yet"}
LOOKS = ("on", "off", "art")
PROOF_HOW = ("page_opens", "command", "play", "picture", "file_exists")
ROLE_KINDS = ("chat", "image")
GROUPS = ["Websites", "Web apps", "Browser games", "Desktop apps", "Mobile apps", "Mods and add-ons", "Other"]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
KIND_KEYS = {"schema", "id", "name", "blurb", "group", "status", "extends", "match", "examples", "needs", "roles",
             "plan", "look", "proof", "pictures", "targets", "extras_allowed", "plugins", "estimate", "start", "ship"}
EXTRA_KEYS = {"schema", "id", "name", "blurb", "status", "match", "needs", "targets", "proof", "plan", "task",
              "pc_only", "ship"}
RECIPE_KEYS = ("start", "ship")  # how to start the thing built and how to build it to hand out (d2-ship tightens)
MAX_RECIPE_WORDS = 500
PLAN_KEYS = {"has_ui", "skeleton_first", "spec_sections", "questions", "dont"}
EXTRA_PLAN_KEYS = {"dont"}
PROOF_KEYS = {"id", "how", "words", "optional", "command", "seconds", "status", "path"}
LIST_KEYS = ("match", "examples", "needs", "pictures", "targets", "extras_allowed", "plugins")
# What an imported .rtkind may hold: text and pictures, never code (by name: no scripts, pages or programs)
SAFE_EXT = {".yaml", ".yml", ".md", ".txt", ".json", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 200
MAX_TOTAL = 20 * 1024 * 1024


class KindError(ValueError):
    """A kind that can't be used, in words the owner can act on."""


@dataclass
class Kind:
    id: str
    name: str
    blurb: str = ""
    group: str = "Other"
    status: str = "trial"  # in the file: trial | not_yet ("proven" is earned: status_of)
    spec: dict[str, Any] = field(default_factory=dict)  # the checked kind.yaml (after `extends`, for a resolved one)
    prompts: dict[str, str] = field(default_factory=dict)  # role -> text appended to that role's own prompt
    card_md: str = ""
    source: str = "builtin"  # builtin | own | project
    folder: str = ""
    is_extra: bool = False
    extras: list[dict[str, Any]] = field(default_factory=list)  # stacked extras (resolved kinds only)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Kind":
        known = cls.__dataclass_fields__
        return cls(**{k: copy.deepcopy(v) for k, v in (d or {}).items() if k in known})

    # handy views of the spec
    @property
    def plan(self) -> dict[str, Any]:
        return self.spec.get("plan") or {}

    @property
    def needs(self) -> list[str]:
        return list(self.spec.get("needs") or [])

    @property
    def usable(self) -> bool:
        return self.status != "not_yet"


@dataclass
class Catalog:
    kinds: dict[str, Kind] = field(default_factory=dict)
    extras: dict[str, Kind] = field(default_factory=dict)
    problems: list[dict[str, Any]] = field(default_factory=list)  # [{where, problems: [...]}] cards refused


# -- reading and checking -------------------------------------------------------------------------------
def _lines_of(text: str) -> dict[str, int]:
    """Each key path ("plan.questions.0.options") and the line it starts on (1-based)."""
    out: dict[str, int] = {}
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return out

    def walk(node, path: str) -> None:
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                p = f"{path}.{k.value}" if path else str(k.value)
                out[p] = k.start_mark.line + 1
                walk(v, p)
        elif isinstance(node, yaml.SequenceNode):
            for i, v in enumerate(node.value):
                p = f"{path}.{i}"
                out[p] = v.start_mark.line + 1
                walk(v, p)

    if root is not None:
        walk(root, "")
    return out


def _at(lines: dict[str, int], path: str) -> str:
    while path:
        if path in lines:
            return f"line {lines[path]}"
        path = path.rpartition(".")[0]
    return "the file"


def parse_text(text: str, is_extra: bool = False) -> tuple[dict[str, Any] | None, list[str]]:
    """The YAML of a kind (or an extra) checked: (the data, []) or (None, the problems with their lines)."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}" if mark else "the file"
        return None, [f"{where}: this isn't readable YAML ({getattr(e, 'problem', None) or e})"]
    return validate(raw, lines=_lines_of(text), is_extra=is_extra)


def validate(raw: Any, lines: dict[str, int] | None = None, is_extra: bool = False,
             known_needs: set[str] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Check a kind's data. Returns (the cleaned data, []) or (None, problems), each problem naming its line."""
    lines = lines or {}
    probs: list[str] = []

    def bad(path: str, text: str) -> None:
        probs.append(f"{_at(lines, path)}: {text}")

    if not isinstance(raw, dict):
        return None, ["the file: it must be a list of settings (key: value), starting with schema: kind@1"]
    want = EXTRA_SCHEMA if is_extra else SCHEMA
    if raw.get("schema") != want:
        bad("schema", f"schema must be {want} (it says {raw.get('schema')!r})")
    allowed = EXTRA_KEYS if is_extra else KIND_KEYS
    for k in raw:
        if k not in allowed:
            bad(str(k), f"{k!r} isn't a setting a {'extra' if is_extra else 'kind'} can have")
    kid = raw.get("id")
    if not isinstance(kid, str) or not ID_RE.match(kid):
        bad("id", "id must be a short name in lower case: letters, numbers and hyphens (like browser-game)")
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        bad("name", "name is missing: the words the owner reads, like Browser game")
    for k in ("blurb", "group", "extends", "task"):
        if k in raw and not isinstance(raw[k], str):
            bad(k, f"{k} must be plain words")
    status = raw.get("status", "trial")
    if status == "proven":
        bad("status", "status can't say proven: that is earned when something built with it passes its proof")
    elif status not in STATUSES:
        bad("status", f"status must be trial or not_yet (it says {status!r})")
    for k in LIST_KEYS:
        if k in raw and (not isinstance(raw[k], list) or not all(isinstance(x, str) for x in raw[k])):
            bad(k, f"{k} must be a list of words, like [a, b]")
    if known_needs is None:
        try:
            from .. import prereq

            known_needs = set(prereq.BY_ID)
        except Exception:  # noqa: BLE001 - the catalog is a help; without it any need is accepted
            known_needs = None
    if known_needs is not None and isinstance(raw.get("needs"), list):
        for i, n in enumerate(raw["needs"]):
            if isinstance(n, str) and n not in known_needs:
                bad(f"needs.{i}", f"needs names {n!r}, which isn't a tool the harness knows "
                                  f"(one of: {', '.join(sorted(known_needs))})")
    if "pc_only" in raw and not isinstance(raw["pc_only"], bool):
        bad("pc_only", "pc_only must be true or false")
    if "look" in raw and raw["look"] not in LOOKS and raw["look"] not in (True, False):
        bad("look", f"look must be on, off or art (it says {raw['look']!r})")
    _check_roles(raw.get("roles"), bad)
    _check_plan(raw.get("plan"), bad, EXTRA_PLAN_KEYS if is_extra else PLAN_KEYS)
    _check_proof(raw.get("proof"), bad)
    _check_estimate(raw.get("estimate"), bad)
    for k in RECIPE_KEYS:
        _check_recipe(k, raw.get(k), bad)
    if probs:
        return None, probs
    data = dict(raw)
    data["status"] = status
    if "look" in data and isinstance(data["look"], bool):  # YAML reads a bare on/off as true/false
        data["look"] = "on" if data["look"] else "off"
    return data, []


def _check_roles(roles: Any, bad) -> None:
    if roles is None:
        return
    if not isinstance(roles, dict) or set(roles) - {"add", "prompts"}:
        bad("roles", "roles may only have add: and prompts:")
        return
    for name, spec in (roles.get("add") or {}).items():
        p = f"roles.add.{name}"
        if not ROLE_RE.match(str(name)):
            bad(p, f"the role name {name!r} must be one lower-case word")
        if not isinstance(spec, dict) or set(spec) - {"kind", "description"}:
            bad(p, "an added role has only kind: (chat or image) and description:")
        elif spec.get("kind", "chat") not in ROLE_KINDS:
            bad(p, f"an added role's kind must be chat or image (it says {spec.get('kind')!r})")
    for role, rel in (roles.get("prompts") or {}).items():
        p = f"roles.prompts.{role}"
        if not isinstance(rel, str) or not _safe_rel(rel) or not rel.endswith(".md"):
            bad(p, f"the prompt for {role} must be a .md file inside the kind's folder, like prompts/{role}.md")


def _check_plan(plan: Any, bad, allowed: set[str]) -> None:
    if plan is None:
        return
    if not isinstance(plan, dict):
        bad("plan", "plan must be a list of settings")
        return
    for k in plan:
        if k not in allowed:
            bad(f"plan.{k}", f"plan.{k} isn't a plan setting this file can have")
    for k in ("has_ui", "skeleton_first"):
        if k in plan and not isinstance(plan[k], bool):
            bad(f"plan.{k}", f"plan.{k} must be true or false")
    if "spec_sections" in plan and (not isinstance(plan["spec_sections"], list)
                                    or not all(isinstance(x, str) for x in plan["spec_sections"])):
        bad("plan.spec_sections", "plan.spec_sections must be a list of section titles")
    for i, q in enumerate(plan.get("questions") or []):
        p = f"plan.questions.{i}"
        if not isinstance(q, dict) or not q.get("id") or not q.get("question"):
            bad(p, "each question needs an id: and a question:")
            continue
        opts = q.get("options") or []
        ids = [str(o.get("id") if isinstance(o, dict) else o) for o in opts]
        if len(ids) < 2:
            bad(p, f"the question {q['id']!r} needs at least two options")
        elif q.get("recommended") is not None and str(q["recommended"]) not in ids:
            bad(f"{p}.recommended", f"recommended must be one of the options ({', '.join(ids)})")
    for i, d in enumerate(plan.get("dont") or []):
        if not isinstance(d, dict) or not isinstance(d.get("text"), str):
            bad(f"plan.dont.{i}", "each don't needs a text: (and a why:)")


def _check_proof(proof: Any, bad) -> None:
    if proof is None:
        return
    if not isinstance(proof, list):
        bad("proof", "proof must be a list of checks")
        return
    seen = set()
    for i, item in enumerate(proof):
        p = f"proof.{i}"
        if not isinstance(item, dict):
            bad(p, "each proof check is a list of settings: id, how, words")
            continue
        for k in item:
            if k not in PROOF_KEYS:
                bad(f"{p}.{k}", f"{k!r} isn't a setting a proof check can have")
        if not item.get("id") or item.get("id") in seen:
            bad(p, "each proof check needs its own id")
        seen.add(item.get("id"))
        if item.get("how") not in PROOF_HOW:
            bad(f"{p}.how", f"how must be one of {', '.join(PROOF_HOW)} (it says {item.get('how')!r})")
        if not isinstance(item.get("words"), str) or not item["words"].strip():
            bad(p, "each proof check needs words: what the owner reads, like It opens with no errors")
        if item.get("status", "trial") not in STATUSES:
            bad(f"{p}.status", "a proof check's status is trial or not_yet")
        if "command" in item and not isinstance(item["command"], str):
            bad(f"{p}.command", "command must be one line of words")
        if "path" in item and (not isinstance(item["path"], str) or not _safe_rel(item["path"])):
            bad(f"{p}.path", "path must be inside the project, like dist/*.apk")
        if "seconds" in item and (not isinstance(item["seconds"], (int, float)) or item["seconds"] <= 0):
            bad(f"{p}.seconds", "seconds must be a number above 0")
        if "optional" in item and not isinstance(item["optional"], bool):
            bad(f"{p}.optional", "optional must be true or false")


def _check_recipe(key: str, recipe: Any, bad) -> None:
    if recipe is None:
        return
    if (not isinstance(recipe, dict)
            or not all(isinstance(k, str) and isinstance(v, str) and len(v) <= MAX_RECIPE_WORDS
                       for k, v in recipe.items())):
        bad(key, f"{key} must be a list of settings, each a short line of words (like command: npm start)")


def _check_estimate(est: Any, bad) -> None:
    if est is None:
        return
    if not isinstance(est, dict):
        bad("estimate", "estimate must have tasks:, usd: and minutes:, each [lowest, highest]")
        return
    for k, v in est.items():
        if k not in ("tasks", "usd", "minutes"):
            bad(f"estimate.{k}", f"estimate.{k} isn't one of tasks, usd, minutes")
        elif (not isinstance(v, list) or len(v) != 2 or not all(isinstance(x, (int, float)) for x in v)
              or v[0] < 0 or v[0] > v[1]):
            bad(f"estimate.{k}", f"estimate.{k} must be [lowest, highest], like [1, 4]")


def _safe_rel(rel: str) -> bool:
    p = Path(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts and not rel.startswith(("/", "\\")) \
        and ":" not in rel


# -- loading ----------------------------------------------------------------------------------------------
def builtin_dir() -> Path:
    return Path(str(resources.files("roundtable").joinpath("kinds/builtin")))


def own_dir(home: Path | str | None) -> Path | None:
    return Path(home) / "kinds" if home else None


def load_folder(folder: Path, source: str, is_extra: bool = False) -> tuple[Kind | None, list[str]]:
    """One kind (or extra) from its folder; (None, problems) when the card is refused."""
    f = folder / ("extra.yaml" if is_extra else "kind.yaml")
    try:
        text = f.read_text(encoding="utf-8")
    except OSError as e:
        return None, [f"the file: couldn't read {f.name} ({e.strerror or e})"]
    data, probs = parse_text(text, is_extra=is_extra)
    if data is None:
        return None, probs
    prompts: dict[str, str] = {}
    for role, rel in ((data.get("roles") or {}).get("prompts") or {}).items():
        p = folder / rel
        if not p.is_file():
            line = _lines_of(text).get(f"roles.prompts.{role}")
            probs.append(f"{'line ' + str(line) if line else 'the file'}: the prompt file {rel} isn't there")
            continue
        prompts[role] = p.read_text(encoding="utf-8").strip()
    if probs:
        return None, probs
    card = folder / "card.md"
    return Kind(id=data["id"], name=data["name"].strip(), blurb=str(data.get("blurb") or "").strip(),
                group=str(data.get("group") or "Other"), status=data["status"], spec=data, prompts=prompts,
                card_md=card.read_text(encoding="utf-8").strip() if card.is_file() else "", source=source,
                folder=str(folder), is_extra=is_extra), []


def load_all(home: Path | str | None = None) -> Catalog:
    """Every kind and extra: the built-in ones, then the owner's own (``<home>/kinds``), later ones winning."""
    cat = Catalog()
    for base, source in ((builtin_dir(), "builtin"), (own_dir(home), "own")):
        if not base or not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            if (d / "kind.yaml").is_file():
                _add(cat, d, source, False)
        extras = base / "_extras"
        if extras.is_dir():
            for d in sorted(p for p in extras.iterdir() if p.is_dir() and (p / "extra.yaml").is_file()):
                _add(cat, d, source, True)
    return cat


def _add(cat: Catalog, folder: Path, source: str, is_extra: bool) -> None:
    k, probs = load_folder(folder, source, is_extra)
    if k is None:
        cat.problems.append({"where": f"{source}: {folder.name}", "problems": probs})
    else:
        (cat.extras if is_extra else cat.kinds)[k.id] = k


# -- extends and extras -------------------------------------------------------------------------------------
def _merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    """``top`` over ``base``: settings replace, except the ones that add up (written once, shared)."""
    out = copy.deepcopy(base)
    for k, v in top.items():
        if k in ("schema", "extends"):
            continue
        if k == "needs":
            out[k] = list(dict.fromkeys([*(out.get(k) or []), *v]))
        elif k == "proof":
            out[k] = _merge_proof(out.get(k) or [], v)
        elif k == "roles":
            r = copy.deepcopy(out.get("roles") or {})
            for part in ("add", "prompts"):
                if v.get(part):
                    r[part] = {**(r.get(part) or {}), **v[part]}
            out[k] = r
        elif k == "plan":
            p = copy.deepcopy(out.get("plan") or {})
            for pk, pv in v.items():
                if pk == "dont":
                    have = {d["text"] for d in p.get("dont") or []}
                    p["dont"] = [*(p.get("dont") or []), *(d for d in pv if d["text"] not in have)]
                elif pk == "questions":
                    mine = {q["id"] for q in pv}
                    p["questions"] = [*(q for q in p.get("questions") or [] if q["id"] not in mine), *pv]
                else:
                    p[pk] = copy.deepcopy(pv)
            out[k] = p
        else:
            out[k] = copy.deepcopy(v)
    return out


def _merge_proof(base: list[dict[str, Any]], top: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {p["id"]: dict(p) for p in base}
    for p in top:
        by[p["id"]] = {**by.get(p["id"], {}), **p}
    return list(by.values())


def resolve(kind_id: str, extras: list[str] | None = None, catalog: Catalog | None = None,
            home: Path | str | None = None) -> Kind:
    """The kind with its ``extends`` chain merged (shared pieces written once) and the extras stacked on."""
    cat = catalog or load_all(home)
    if kind_id not in cat.kinds:
        raise KindError(f"there's no kind called {kind_id!r}")
    chain: list[Kind] = []
    k: Kind | None = cat.kinds[kind_id]
    while k is not None:
        if any(c.id == k.id for c in chain):
            raise KindError(f"{kind_id}: its extends: goes round in a circle ({' → '.join(c.id for c in chain)})")
        chain.append(k)
        parent = k.spec.get("extends")
        if parent and parent not in cat.kinds:
            raise KindError(f"{k.id} extends {parent!r}, which isn't there")
        k = cat.kinds.get(parent) if parent else None
    spec: dict[str, Any] = {}
    prompts: dict[str, str] = {}
    for c in reversed(chain):  # the furthest parent first
        spec = _merge(spec, c.spec)
        for role, text in c.prompts.items():
            prompts[role] = f"{prompts[role]}\n\n{text}" if role in prompts else text
    top = chain[0]
    spec["id"], spec["name"] = top.id, top.name
    out = Kind(id=top.id, name=top.name, blurb=top.blurb, group=top.group, status=top.status, spec=spec,
               prompts=prompts, card_md=top.card_md, source=top.source, folder=top.folder)
    allowed = set(spec.get("extras_allowed") or [])
    for eid in dict.fromkeys(extras or []):
        if eid not in cat.extras:
            raise KindError(f"there's no extra called {eid!r}")
        if eid not in allowed:
            raise KindError(f"{top.name} can't have the extra {cat.extras[eid].name}")
        e = cat.extras[eid]
        out.extras.append({"id": e.id, "name": e.name, "blurb": e.blurb, "status": e.status,
                           "task": str(e.spec.get("task") or ""), "pc_only": bool(e.spec.get("pc_only"))})
        es = e.spec
        out.spec["needs"] = list(dict.fromkeys([*(out.spec.get("needs") or []), *(es.get("needs") or [])]))
        out.spec["targets"] = list(dict.fromkeys([*(out.spec.get("targets") or []), *(es.get("targets") or [])]))
        out.spec["proof"] = _merge_proof(out.spec.get("proof") or [],
                                         [{**p, "from": e.id} for p in es.get("proof") or []])
        if (es.get("plan") or {}).get("dont"):
            out.spec["plan"] = _merge({"plan": out.spec.get("plan") or {}}, {"plan": {"dont": es["plan"]["dont"]}})["plan"]
    return out


# -- choosing a kind ---------------------------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _words(text: str) -> list[str]:
    return _WORD.findall(str(text or "").lower())


def _hit(goal_words: list[str], phrase: str) -> bool:
    """A match word (or phrase) in the goal, allowing a plural or -ing on the last word."""
    pw = _words(phrase)
    if not pw:
        return False
    n = len(pw)
    for i in range(len(goal_words) - n + 1):
        part = goal_words[i:i + n]
        if part[:-1] == pw[:-1] and (part[-1] == pw[-1] or part[-1] in (pw[-1] + "s", pw[-1] + "es", pw[-1] + "ing")):
            return True
    return False


def propose(goal: str, kinds: Catalog | dict[str, Kind] | None = None,
            home: Path | str | None = None) -> list[tuple[str, float, str]]:
    """The kinds that fit an idea, best first: [(id, score, why)]. Free (a word match, no model call).

    Only kinds usable now take part; ``other`` is always offered, last unless nothing else matched.
    A longer phrase counts more than one word ("music player" beats "play")."""
    pool = kinds.kinds if isinstance(kinds, Catalog) else (kinds if kinds is not None else load_all(home).kinds)
    gw = _words(goal)
    scored = []
    for k in pool.values():
        if not k.usable or k.id == "other" or k.is_extra:
            continue
        said = [m for m in (k.spec.get("match") or []) if _hit(gw, m)]
        # a phrase inside a longer one that also matched doesn't count twice ("play" inside "player")
        said = [m for m in said if not any(m != o and _hit(_words(o), m) for o in said)]
        score = sum(len(_words(m)) ** 1.5 for m in said)
        if score:
            why = "because you said " + " and ".join(f"“{m}”" for m in said[:2])
            scored.append((k.id, round(score, 2), why))
    scored.sort(key=lambda x: (-x[1], x[0]))
    other = ("other", 0.0, "it doesn't look like anything the harness has a recipe for yet" if not scored
             else "if it's none of these")
    if "other" in pool:
        scored.append(other)
    return scored


def propose_extras(goal: str, kind: Kind | str, catalog: Catalog | None = None,
                   home: Path | str | None = None) -> list[str]:
    """The extras an idea asks for ("…for my Android phone" → apk), among those the kind allows."""
    cat = catalog or load_all(home)
    k = cat.kinds.get(kind) if isinstance(kind, str) else kind
    if k is None:
        return []
    allowed = set(k.spec.get("extras_allowed") or [])
    if k.spec.get("extends") and not allowed:
        try:
            allowed = set(resolve(k.id, catalog=cat).spec.get("extras_allowed") or [])
        except KindError:
            allowed = set()
    gw = _words(goal)
    return [e.id for e in cat.extras.values() if e.id in allowed and any(_hit(gw, m) for m in e.spec.get("match") or [])]


# -- what the builders read ----------------------------------------------------------------------------------------
def overlay(kind: Kind, base_prompt=None, prompt_names: dict[str, str] | None = None) -> dict[str, Any]:
    """The kind as a config overlay, in ``config.apply_overlay``'s shape: ``{"roles": {}, "prompts": {...}}``,
    plus ``add_roles`` (roles the kind brings; they borrow the models of an existing role of the same sort).

    A kind never picks models: ``roles`` stays empty. Each role's prompt gets the kind's text **appended**
    (``base_prompt(name)`` is the role's own prompt; ``prompt_names`` maps role → its prompt's name)."""
    names = prompt_names or {}
    prompts = {}
    for role, text in kind.prompts.items():
        name = names.get(role, role)
        base = base_prompt(name) if base_prompt else ""
        prompts[name] = (f"{base.rstrip()}\n\n" if base else "") + f"# What this project is: {kind.name}\n{text}\n"
    add = {n: dict(s) for n, s in ((kind.spec.get("roles") or {}).get("add") or {}).items()}
    return {"roles": {}, "prompts": prompts, "add_roles": add}


def apply_to_config(cfg, kind: Kind):
    """A copy of the config with the kind laid over it: the prompts and the added roles, nothing else."""
    from ..harness.config import RoleSpec, apply_overlay

    c = cfg.variant()
    names = {}
    for role in kind.prompts:
        spec = c.roles.get(role)
        if not spec:
            continue
        name = spec.prompt or role
        if "\n" in name or " " in name.strip():  # an inline prompt: give it a name so the overlay can extend it
            c.prompt_overrides[f"kind-{role}"] = name
            spec.prompt = name = f"kind-{role}"
        names[role] = name
    ov = overlay(kind, base_prompt=c.prompt_text, prompt_names=names)
    for name, spec in ov["add_roles"].items():
        if name in c.roles:
            continue
        like = next((r for r in c.roles.values() if r.kind == spec.get("kind", "chat") and r.models), None)
        if like is None:
            continue  # nothing to borrow models from: the role isn't added (the plan simply can't use it)
        c.roles[name] = RoleSpec(name=name, models=list(like.models), kind=like.kind,
                                 description=str(spec.get("description") or ""), options=dict(like.options),
                                 review=like.review)
    prompts = {n: t for n, t in ov["prompts"].items() if any(names.get(r) == n for r in names)}
    apply_overlay(c, {"roles": ov["roles"]}, prompts)
    return c


def plan_brief(kind: Kind) -> str:
    """What the planner reads about the kind, after its job."""
    p = kind.plan
    out = [f"# What this project is: {kind.name}", kind.blurb]
    if p.get("spec_sections"):
        out.append("- The spec has these sections, in this order: " + ", ".join(p["spec_sections"]) + ".")
    if p.get("skeleton_first"):
        out.append("- The first task works alone, before any other: the folder layout, the shared names and the "
                   "data shapes. Every other task depends on it, and names the files it may touch.")
    if "has_ui" in p:
        out.append(f"- has_ui: {'true' if p['has_ui'] else 'false'}.")
    for q in p.get("questions") or []:
        opts = [str(o.get("label") or o.get("id")) if isinstance(o, dict) else str(o) for o in q.get("options") or []]
        rec = next((str(o.get("label") or o.get("id")) for o in q.get("options") or []
                    if isinstance(o, dict) and str(o.get("id")) == str(q.get("recommended"))), q.get("recommended"))
        out.append(f"- Put this in the decisions (header {q.get('header') or q['id']}): {q['question']} "
                   f"Options: {', '.join(opts)}." + (f" Recommend: {rec}." if rec else ""))
    for d in p.get("dont") or []:
        out.append(f"- Don't: {d['text']}" + (f" ({d['why']})" if d.get("why") else "") + ". Keep it in the don't list.")
    proof = [i for i in kind.spec.get("proof") or [] if i.get("status", "trial") != "not_yet"]
    if proof:
        out.append("- It is proven by: " + "; ".join(i["words"] for i in proof) + ". Plan so these can pass.")
    for e in kind.extras:
        out.append(f"- Extra: {e['name']}. {e['task']}".rstrip())
    return "\n".join(x for x in out if x)


def worker_brief(kind: Kind, role: str) -> str:
    """What a builder reads about the kind in its task ("" for nothing to add)."""
    if kind.id == "other" and not kind.extras:
        return ""
    out = [f"# What this project is: {kind.name}", kind.blurb]
    for d in kind.plan.get("dont") or []:
        out.append(f"- Don't: {d['text']}" + (f" ({d['why']})" if d.get("why") else ""))
    proof = [i for i in kind.spec.get("proof") or [] if i.get("status", "trial") != "not_yet" and not i.get("optional")]
    if proof:
        out.append("- When it's finished it must pass: " + "; ".join(i["words"] for i in proof) + ".")
    for e in kind.extras:
        out.append(f"- It is also packed as: {e['name']}.")
    return "\n".join(x for x in out if x)


def proof_plan(kind: Kind) -> list[dict[str, Any]]:
    """The kind's proof checks (with its extras'), for the proof stage (harness/proof.py ``plan_for``).

    Each item: {id, how, words, optional, status, from, command?, seconds?, path?}. A ``not_yet`` item is
    shown but can't be checked yet; it doesn't count towards "proven"."""
    out = []
    for i in kind.spec.get("proof") or []:
        item = {"id": i["id"], "how": i["how"], "words": i["words"], "optional": bool(i.get("optional")),
                "status": i.get("status", "trial"), "from": i.get("from", kind.id)}
        for k in ("command", "seconds", "path"):
            if k in i and i[k] not in ("", None):
                item[k] = i[k]
        if item["how"] == "command" and not item.get("command"):
            item["command"] = ""  # the project's own check command (project settings) is used
        out.append(item)
    return out


# -- honest status -----------------------------------------------------------------------------------------------------
def state_path(home: Path | str) -> Path:
    return Path(home) / "kinds" / "state.json"


def read_state(home: Path | str | None) -> dict[str, Any]:
    if not home:
        return {}
    p = state_path(home)
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("kinds") or {} if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def counted(proof_lines: list[dict[str, Any]]) -> bool:
    """Every proof line that counts passed (an optional or not-yet line doesn't count; none at all isn't proof)."""
    need = [p for p in proof_lines if not p.get("optional") and p.get("status", "trial") != "not_yet"]
    return bool(need) and all(p.get("passed") is True for p in need)


def write_state(home: Path | str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """state.json from the gallery's entries: for each kind, how many were built, how many proven, the medians."""
    by: dict[str, dict[str, Any]] = {}
    for e in entries:
        kid = (e.get("kind") or {}).get("id")
        if not kid:
            continue
        s = by.setdefault(kid, {"built": 0, "proven": 0, "usd": [], "minutes": [], "tasks": []})
        s["built"] += 1
        s["proven"] += 1 if counted(e.get("proof") or []) else 0
        for k, v in (("usd", (e.get("cost") or {}).get("counted_usd")), ("minutes", e.get("minutes")),
                     ("tasks", e.get("tasks"))):
            if isinstance(v, (int, float)):
                s[k].append(v)
    out = {kid: {"built": s["built"], "proven": s["proven"],
                 "median": {k: round(statistics.median(s[k]), 2) for k in ("usd", "minutes", "tasks") if s[k]}}
           for kid, s in by.items()}
    p = state_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"kinds": out}, indent=1) + "\n", encoding="utf-8")
    return out


def status_of(kind: Kind, state: dict[str, Any] | None) -> str:
    if kind.status == "not_yet":
        return "not_yet"
    s = (state or {}).get(kind.id) or {}
    return "proven" if s.get("proven", 0) >= 1 else "trial"


def status_words(kind: Kind, state: dict[str, Any] | None) -> str:
    st = status_of(kind, state)
    if st == "proven":
        return f"Proven ({(state or {}).get(kind.id, {}).get('built', 1)} built)"
    return STATUS_WORDS[st]


# -- what the owner reads -----------------------------------------------------------------------------------------------
def _range(lo_hi: list[float] | None, unit: str) -> str:
    if not lo_hi:
        return ""
    lo, hi = lo_hi
    if unit == "$":
        return f"${lo:.2f}–${hi:.2f}" if lo != hi else f"${lo:.2f}"
    return f"{lo:g}–{hi:g} {unit}" if lo != hi else f"{lo:g} {unit}"


def card(kind: Kind, state: dict[str, Any] | None = None, missing: list[str] | None = None,
         tool_names: dict[str, str] | None = None) -> dict[str, Any]:
    """A kind as the owner reads it: short first (name, blurb, status, typical cost and time), the rest folded."""
    st = (state or {}).get(kind.id) or {}
    median = st.get("median") or {}
    est = kind.spec.get("estimate") or {}
    real = bool(median.get("usd") is not None and st.get("built"))
    cost = f"about ${median['usd']:.2f}" if real else _range(est.get("usd"), "$")
    time = (f"about {median['minutes']:g} min" if real and median.get("minutes") is not None
            else _range(est.get("minutes"), "min"))
    names = tool_names or {}
    miss = set(missing or [])
    status = status_of(kind, state)
    line = " · ".join(x for x in (cost, time) if x)
    return {
        "id": kind.id, "name": kind.name, "blurb": kind.blurb, "group": kind.group, "source": kind.source,
        "status": status, "status_words": status_words(kind, state), "usable": kind.usable,
        "built": st.get("built", 0),
        "typical": line + ("" if real or not line else " (a guess)"), "guess": not real,
        "typical_tip": ("The middle of what earlier builds really cost and took." if real else
                        "A guess: nothing has been built with this yet."),
        "needs": [{"id": n, "name": names.get(n, n), "missing": n in miss} for n in kind.needs],
        "missing": [names.get(n, n) for n in kind.needs if n in miss],
        "examples": list(kind.spec.get("examples") or []),
        "extras_allowed": list(kind.spec.get("extras_allowed") or []),
        "extras": [{"id": e["id"], "name": e["name"]} for e in kind.extras],
        "proof": [{"id": i["id"], "words": i["words"], "optional": i.get("optional", False),
                   "not_yet": i.get("status") == "not_yet"} for i in proof_plan(kind)],
        "more": {"card": kind.card_md, "spec_sections": list(kind.plan.get("spec_sections") or []),
                 "roles_added": sorted(((kind.spec.get("roles") or {}).get("add") or {})),
                 "prompts_for": sorted(kind.prompts), "look": kind.spec.get("look", "on"),
                 "targets": list(kind.spec.get("targets") or []), "plugins": list(kind.spec.get("plugins") or [])},
    }


def extra_card(extra: Kind) -> dict[str, Any]:
    return {"id": extra.id, "name": extra.name, "blurb": extra.blurb, "status": extra.status,
            "status_words": STATUS_WORDS.get(extra.status, extra.status), "pc_only": bool(extra.spec.get("pc_only")),
            "needs": extra.needs, "source": extra.source}


def wizard_options(home: Path | str | None = None, catalog: Catalog | None = None) -> list[dict[str, Any]]:
    """The answers to the wizard's "What do you want to make?": the kinds usable now first, the ones not ready
    yet greyed under "Coming", and "Something else" (the ``other`` kind) last."""
    cat = catalog or load_all(home)
    order = {g: i for i, g in enumerate(GROUPS)}
    ks = sorted((k for k in cat.kinds.values() if k.id != "other"), key=lambda k: (order.get(k.group, 99), k.name))
    out = [{"id": k.id, "label": k.name, "description": k.blurb, "group": k.group} for k in ks if k.usable]
    out += [{"id": k.id, "label": k.name, "description": k.blurb, "group": "Coming", "disabled": True,
             "tip": "Not ready yet: the harness can't build or prove this sort of thing so far."}
            for k in ks if not k.usable]
    if "other" in cat.kinds:
        out.append({"id": "other", "label": "Something else", "description": cat.kinds["other"].blurb, "group": "Other"})
    return out


# The wizard's answers from before kinds (asks.KINDS) mapped onto kinds and extras
OLD_WIZARD = {"web": ("web-app", []), "game": ("browser-game", []), "android": ("web-app", ["apk"]),
              "windows": ("web-app", ["exe"])}


def from_wizard(chosen: str, other: str = "", idea: str = "", home: Path | str | None = None,
                catalog: Catalog | None = None) -> dict[str, Any]:
    """The wizard's "What do you want to make?" answer as {kind, extras, by, why}: a kind's id, an old answer
    (web, game, android, windows), or "Something else" with words (proposed from those words and the idea)."""
    cat = catalog or load_all(home)
    if chosen in OLD_WIZARD:
        kid, extras = OLD_WIZARD[chosen]
        if kid in cat.kinds:
            return {"kind": kid, "extras": list(extras), "by": "owner", "why": "you chose it"}
    if chosen in cat.kinds and cat.kinds[chosen].usable and chosen != "other":
        return {"kind": chosen, "extras": propose_extras(f"{other} {idea}", chosen, cat), "by": "owner",
                "why": "you chose it"}
    best = propose(f"{other} {idea}", cat)
    kid, _, why = best[0] if best else ("other", 0.0, "")
    return {"kind": kid, "extras": propose_extras(f"{other} {idea}", kid, cat), "by": "roundtable", "why": why}


# -- sharing a kind ----------------------------------------------------------------------------------------------------------
_KEYS: list[re.Pattern] | None = None


def key_shaped(text: str) -> bool:
    """True when the text holds something shaped like a key, a token or a password (backup.py's patterns)."""
    global _KEYS
    if _KEYS is None:
        from ..backup import SECRET_PATTERNS

        _KEYS = [re.compile(p.pattern.decode()) for p, _ in SECRET_PATTERNS]
    return any(p.search(text) for p in _KEYS)


def export(kind: Kind) -> bytes:
    """The kind's folder as a ``.rtkind`` (a zip): its YAML, prompts, card and safe template files. Never a
    project's content; refuses to share anything shaped like a key."""
    folder = Path(kind.folder)
    if not folder.is_dir():
        raise KindError(f"{kind.name} has no folder to share")
    main = "extra.yaml" if kind.is_extra else "kind.yaml"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder).as_posix()
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in SAFE_EXT or p.stat().st_size > MAX_FILE:
                continue
            if rel != main and not rel.startswith(("prompts/", "template/")) and rel != "card.md":
                continue
            data = p.read_bytes()
            if p.suffix.lower() in {".yaml", ".yml", ".md", ".txt", ".json"} and key_shaped(data.decode("utf-8", "replace")):
                raise KindError(f"{rel} has something shaped like a key in it: take it out, then share again")
            z.writestr(rel, data)
    return buf.getvalue()


def import_file(data: bytes, home: Path | str, confirm: bool = False) -> dict[str, Any]:
    """Read a ``.rtkind``. Without ``confirm`` nothing is written: the answer says what the kind would switch
    on (tools it needs, plug-ins, roles, commands its proof runs). With ``confirm`` it goes in the owner's own
    kinds (``<home>/kinds/<id>``; an extra in ``_extras``). Refused: code or unknown file types, links,
    ``..`` or absolute paths, files over 5 MB, too many files, and anything shaped like a key."""
    problems: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        return {"ok": False, "problems": ["This isn't a kind file (.rtkind)."]}
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        return {"ok": False, "problems": [f"It holds {len(infos)} files; a kind has at most {MAX_FILES}."]}
    files: dict[str, bytes] = {}
    total = 0
    for i in infos:
        name = i.filename
        if i.is_dir():
            continue
        mode = (i.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            problems.append(f"{name}: a link to somewhere else isn't allowed")
            continue
        if not _safe_rel(name) or "\\" in name:
            problems.append(f"{name}: a file outside the kind's folder isn't allowed")
            continue
        if Path(name).suffix.lower() not in SAFE_EXT:
            problems.append(f"{name}: only text and pictures are allowed in a kind, never code or programs")
            continue
        if i.file_size > MAX_FILE:
            problems.append(f"{name}: it's over 5 MB")
            continue
        total += i.file_size
        if total > MAX_TOTAL:
            problems.append("It's over 20 MB in all.")
            break
        body = z.read(i)
        if len(body) > MAX_FILE:
            problems.append(f"{name}: it's over 5 MB")
            continue
        if Path(name).suffix.lower() in {".yaml", ".yml", ".md", ".txt", ".json"} and key_shaped(body.decode("utf-8", "replace")):
            problems.append(f"{name}: it has something shaped like a key or a password in it")
            continue
        files[name] = body
    is_extra = "extra.yaml" in files
    main = "extra.yaml" if is_extra else "kind.yaml"
    if main not in files and not problems:
        problems.append("There's no kind.yaml in it.")
    if problems:
        return {"ok": False, "problems": problems}
    spec, probs = parse_text(files[main].decode("utf-8", "replace"), is_extra=is_extra)
    if spec is None:
        return {"ok": False, "problems": [f"{main}, {p}" for p in probs]}
    for role, rel in ((spec.get("roles") or {}).get("prompts") or {}).items():
        if rel not in files:
            problems.append(f"{main}: the prompt for {role} ({rel}) isn't in the file")
    if problems:
        return {"ok": False, "problems": problems}
    target = own_dir(home) / ("_extras" if is_extra else "") / spec["id"]
    clash = [k for k, c in (("own", target.exists()),
                            ("builtin", (builtin_dir() / ("_extras" if is_extra else "") / spec["id"]).exists())) if c]
    would = {
        "id": spec["id"], "name": spec["name"], "is_extra": is_extra,
        "needs": list(spec.get("needs") or []), "plugins": list(spec.get("plugins") or []),
        "roles_added": sorted(((spec.get("roles") or {}).get("add") or {})),
        "prompts_for": sorted(((spec.get("roles") or {}).get("prompts") or {})),
        "commands": [p["command"] for p in spec.get("proof") or [] if p.get("command")],
        "replaces": ("your own kind with the same name" if "own" in clash
                     else "the built-in one with the same name, for you" if "builtin" in clash else ""),
        "files": sorted(files),
    }
    if not confirm:
        return {"ok": True, "installed": False, "would": would,
                "reply": f"{spec['name']} is ready to add. Nothing changes until you say yes."}
    if target.exists():
        import shutil

        shutil.rmtree(target)
    for name, body in files.items():
        p = target / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return {"ok": True, "installed": True, "would": would, "path": str(target),
            "reply": f"Added {spec['name']}. It shows as On trial until something built with it passes its proof."}
