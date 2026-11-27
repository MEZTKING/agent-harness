"""Learning shared between the owner's machines through the private hub (wave 7).

    learning/changes/<id>.json     one learned change: {id, kind, role, change, numbers, state: on | undone |
                                   waiting, machine, machine_name, at, undone_at, undone_by, words}
    learning/spend/<machine>.json  what learning spent this week on that machine: {machine, week, usd}
    learning/agents/<id>/agent.yaml and face.*   the named agents (never memory.md: it holds project lessons)

What goes to the hub: settings, counts, costs, model ids and prompt text that ``charter.scrub`` leaves as it
is (a prompt the scrub would change is kept on this machine). Never a project's name, a task, a review's words
or the analyst's rationale.

``tick(app)``: take the other machines' changes, then publish this machine's new changes and undos. The
learned state is then rebuilt from every change in force, in ``(at, id)`` order (ledger.settle →
``Lab.rebuild``), so every machine ends with the same state. An undo anywhere wins: a change file that says
undone is never written back to on (putting a change back makes a new one).

Each pulled change passes ``charter.check`` here too; one the charter wants a tap for waits for the owner; a
change naming a model this machine doesn't have is kept aside as "not usable here" and tried again later. A
pulled change is watched here like a local one (``canary.start``). Tools and kind tweaks travel as waiting
items only (their words), never as code.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..harness.config import HarnessConfig, section
from . import ledger
from .lab import Lab, Proposal

CHANGES = "learning/changes"
SPEND = "learning/spend"
AGENTS = "learning/agents"
STATE_FILE = "shared.json"  # in the lab: what this machine pushed and what it kept aside
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
FACES = ("face.webp", "face.png", "face.jpg")


def on(cfg: HarnessConfig) -> bool:
    """``learning.share`` in harness.yaml; on unless set to false."""
    return section(cfg, "learning").get("share", True) is not False


def week(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now(timezone.utc)).isocalendar()
    return f"{y}-W{w:02d}"


# -- this machine's record ----------------------------------------------------------------------------------
def _state(lab: Lab) -> dict[str, Any]:
    st = ledger._shared_state(lab)
    for k in ("pushed", "names", "unusable", "refused", "elsewhere", "agents"):
        if not isinstance(st.get(k), dict):
            st[k] = {}
    return st


def _save_state(lab: Lab, st: dict[str, Any]) -> None:
    lab._write_json(STATE_FILE, st)


def _digest(doc: Any) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _local_id(sid: str) -> str:
    return "S" + hashlib.sha256(sid.encode()).hexdigest()[:9]


# -- what one change looks like on the hub ---------------------------------------------------------------------
def _scrubbed(p: Proposal, lab: Lab) -> dict[str, Any] | None:
    """The change's settings as they may leave this machine, or None when they may not."""
    from . import charter

    ch = p.change if isinstance(p.change, dict) else {}
    if p.kind == "routing":
        models = [m for m in ch.get("models") or [] if isinstance(m, str) and ledger._REF.match(m)]
        return {"models": models} if models and len(models) == len(ch.get("models") or []) else None
    if p.kind == "options":
        opts = ch.get("options") if isinstance(ch.get("options"), dict) else None
        if opts is None:
            return None
        clean = {k: v for k, v in opts.items() if isinstance(k, str) and ledger._SAFE_KEY.match(k)
                 and (isinstance(v, (int, float, bool)) or (isinstance(v, str) and re.match(r"^[\w.-]{1,40}$", v)))}
        return {"options": clean} if clean == opts else None
    if p.kind == "prompt":
        text = ch.get("prompt_text")
        if not isinstance(text, str):
            return None
        try:
            if charter.scrub(text, lab) != text:
                return None  # the scrub would change it: it names something of a project's
        except Exception:  # noqa: BLE001 - unsure means it stays here
            return None
        return {"prompt_text": text}
    return None


def doc_for(p: Proposal, lab: Lab, me: dict[str, str], cfg: HarnessConfig | None = None) -> dict[str, Any] | None:
    """The hub file for one of this machine's changes, or None when it isn't shared."""
    sid = ledger.shared_id(p, me["id"])
    base = {"id": sid, "kind": p.kind, "role": p.role, "machine": me["id"], "machine_name": me.get("name", ""),
            "at": p.applied_at or p.created_at, "words": ledger.what(p, cfg), "numbers": ledger.numbers(p)}
    if p.kind not in ledger.CORE_KINDS:  # a tool or kind tweak: its words only, as something waiting
        if p.status not in ("proposed", "tested", "needs_owner"):
            return None
        return {**base, "id": f"{_slug(me['id'])}-{_slug(p.id)}-waiting", "change": {}, "state": "waiting",
                "numbers": {}, "undone_at": "", "undone_by": ""}
    change = _scrubbed(p, lab)
    if change is None:
        return None
    out = p.status in ledger.TAKEN_OUT
    return {**base, "change": change, "state": "undone" if out else "on",
            "undone_at": _undone_at(lab, p) if out else "", "undone_by": me["id"] if out else ""}


def _slug(text: str) -> str:
    return ledger._slug(text)


def _undone_at(lab: Lab, p: Proposal) -> str:
    rows = [r for r in lab.history() if r.get("proposal") == p.id and r.get("event") == "undone"]
    return str(rows[-1].get("at") or "") if rows else ""


def _read_changes(hub) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        rels = hub.store.list(CHANGES)
    except Exception:  # noqa: BLE001
        return out
    for rel in rels:
        try:
            doc = hub.store.read_json(rel)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("id"), str) and _ID.match(doc["id"]):
            out[doc["id"]] = doc
    return out


# -- one round -------------------------------------------------------------------------------------------------
def share_round(hub, lab: Lab, cfg: HarnessConfig, me: dict[str, str], home: Path | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """Pull the others' changes, settle the learned state, publish this machine's. Returns what happened."""
    from ..core.models import utcnow
    from . import canary, charter

    st = _state(lab)
    hub_docs = _read_changes(hub)
    report: dict[str, Any] = {"pulled": [], "undone": [], "pushed": 0, "not_usable": [], "refused": [],
                              "waiting": []}
    proposals = lab.proposals()
    by_origin = {p.origin: p for p in proposals if p.origin}
    mine_by_sid = {ledger.shared_id(p, me["id"]): p for p in proposals if not ledger.pulled(p, me["id"])}
    changed = False
    new_pulled: list[Proposal] = []
    st["elsewhere"] = {}
    for sid, doc in sorted(hub_docs.items(), key=lambda kv: (str(kv[1].get("at") or ""), kv[0])):
        mid = str(doc.get("machine") or "")
        if doc.get("machine_name") and mid:
            st["names"][mid] = str(doc["machine_name"])[:60]
        undone = doc.get("state") == "undone"
        if mid == me["id"]:  # one of mine: another machine may have undone it
            p = mine_by_sid.get(sid)
            if p and undone and p.status in ledger.IN_FORCE and doc.get("undone_by") not in ("", me["id"]):
                _take_out(lab, p, str(doc.get("undone_by") or ""))
                report["undone"].append(p.id)
                changed = True
            continue
        if doc.get("state") == "waiting" or doc.get("kind") not in ledger.CORE_KINDS:
            st["elsewhere"][sid] = {"words": str(doc.get("words") or "")[:200], "kind": str(doc.get("kind") or ""),
                                    "role": str(doc.get("role") or ""),
                                    "from": st["names"].get(mid) or ledger._machine_words(mid)}
            report["waiting"].append(sid)
            continue
        p = by_origin.get(sid)
        if p is not None:
            if ledger.pulled(p, me["id"]) and undone and p.status in ledger.IN_FORCE:
                _take_out(lab, p, str(doc.get("undone_by") or mid))
                report["undone"].append(p.id)
                changed = True
            continue
        q = Proposal(id=_local_id(sid), kind=str(doc.get("kind")), role=str(doc.get("role") or ""),
                     change=doc.get("change") if isinstance(doc.get("change"), dict) else {},
                     rationale="", risk="low", source="shared", origin=sid, machine=mid,
                     evidence={"numbers": ledger._clean_numbers(doc.get("numbers") or {})},
                     created_at=str(doc.get("at") or utcnow()), applied_at=str(doc.get("at") or ""))
        if undone:  # kept, so the ledger can show it and it is never offered again
            q.status = "undone"
            lab.save_proposal(q)
            lab._log("shared_undone", proposal=q.id, origin=sid, by=mid)
            continue
        try:
            q.validate(cfg)
        except ValueError as e:
            st["unusable"][sid] = {"words": str(doc.get("words") or ledger.what(q, cfg))[:200],
                                   "why": _unusable_words(str(e)), "from": mid}
            report["not_usable"].append(sid)
            continue
        st["unusable"].pop(sid, None)
        try:
            charter.check(cfg, q, lab, by_owner=False)
        except charter.CharterError as e:
            if getattr(e, "needs_owner", False):
                q.status = "needs_owner"
                lab.save_proposal(q)
                lab._log("needs_owner", proposal=q.id, summary=q.summary(), why=str(e)[:300])
                report["waiting"].append(sid)
            else:
                st["refused"][sid] = str(e)[:300]
                report["refused"].append(sid)
            continue
        q.status = "applied"
        lab.save_proposal(q)
        lab._log("shared_in", proposal=q.id, origin=sid, by=mid, summary=q.summary())
        new_pulled.append(q)
        report["pulled"].append(q.id)
        changed = True
    if changed or _drifted(lab, cfg, me["id"]):
        ledger.settle(lab, cfg, me["id"], "shared")
    version = (lab._versions() or [0])[-1]
    for q in new_pulled:
        try:
            canary.start(lab, q, version)
        except Exception:  # noqa: BLE001 - the watch is a help; the change is in force either way
            pass

    # publish this machine's changes and undos
    writes: dict[str, Any] = {}
    hub_docs = {**hub_docs}
    for p in lab.proposals():
        if ledger.pulled(p, me["id"]):
            if p.status in ledger.TAKEN_OUT and p.origin in hub_docs and hub_docs[p.origin].get("state") == "on":
                doc = {**hub_docs[p.origin], "state": "undone", "undone_at": _undone_at(lab, p) or utcnow(),
                       "undone_by": me["id"]}
                writes[f"{CHANGES}/{p.origin}.json"] = doc
                hub_docs[p.origin] = doc
            continue
        if p.source == "shared" and not p.applied_at:
            continue
        if p.kind in ledger.CORE_KINDS and not (p.applied_at and p.status in ledger.IN_FORCE + ledger.TAKEN_OUT):
            continue
        doc = doc_for(p, lab, me, cfg)
        if doc is None:
            continue
        sid = doc["id"]
        if hub_docs.get(sid, {}).get("state") == "undone":
            continue  # an undo anywhere wins, and keeps who made it
        if doc["state"] == "undone" and sid not in hub_docs and sid not in st["pushed"]:
            continue  # never shared while in use: nothing to take back
        dg = _digest(doc)
        if st["pushed"].get(sid) == dg and sid in hub_docs:
            continue
        writes[f"{CHANGES}/{sid}.json"] = doc
        st["pushed"][sid] = dg
    spend = _my_week_spend(lab, now)
    if spend is not None:
        rel = f"{SPEND}/{_slug(me['id'])}.json"
        doc = {"machine": me["id"], "week": week(now), "usd": round(float(spend), 6)}
        try:
            old = hub.store.read_json(rel)
        except (OSError, ValueError):
            old = None
        if old != doc:
            writes[rel] = doc
    if home is not None:
        writes.update(_agents_out(hub, Path(home), st))
    if writes:
        hub.store.write_json(writes, f"learning: from {me.get('name') or me['id']}")
        report["pushed"] = sum(1 for k in writes if k.startswith(CHANGES))
    if home is not None:
        report["agents_in"] = _agents_in(hub, Path(home))
    _save_state(lab, st)
    report["state"] = lab.state_id()
    return report


def _drifted(lab: Lab, cfg: HarnessConfig, me: str) -> bool:
    """A change from another machine is in force but the learned state isn't what the list gives (an undo here
    through Lab.undo rebuilds from its own snapshot, which may not hold the pulled changes)."""
    return ledger._any_pulled(lab, me) and _expected(lab, cfg, me) != lab.state_id()


def _expected(lab: Lab, cfg: HarnessConfig, me: str) -> str:
    import shutil

    probe = Lab(lab.root / ".share-probe")
    try:
        probe.rebuild(ledger.in_force(lab, me), cfg)
        return probe.state_id()
    finally:
        shutil.rmtree(probe.root, ignore_errors=True)


def _take_out(lab: Lab, p: Proposal, by: str) -> None:
    from .lab import KINDS

    p.status = "undone"
    p.undone_why = ""
    lab.save_proposal(p)
    spec = KINDS.get(p.kind)
    if spec and spec.on_undo:
        spec.on_undo(lab, p)
    lab._log("undone", proposal=p.id, summary=p.summary(), by=by, why="")


def _unusable_words(err: str) -> str:
    if "provider" in err:
        return "It uses a model this machine doesn't have. Add that service here to use it."
    if "role" in err:
        return "It changes a job this machine doesn't have."
    return "This machine can't use it as it is."


# -- the wallet's weekly totals ---------------------------------------------------------------------------
def _my_week_spend(lab: Lab, now: datetime | None = None) -> float | None:
    from . import wallet

    fn = getattr(wallet, "spent_week", None) or getattr(wallet, "spent_this_week", None)
    if not callable(fn):
        return None
    try:
        return float(fn(lab))
    except Exception:  # noqa: BLE001
        return None


def others_spent(hub, wk: str | None = None, me: str | None = None) -> float:
    """What learning spent this week on the owner's other machines (for the wallet: one allowance for all)."""
    me = ledger.this_machine()["id"] if me is None else me
    wk = wk or week()
    total = 0.0
    try:
        rels = hub.store.list(SPEND)
    except Exception:  # noqa: BLE001
        return 0.0
    for rel in rels:
        try:
            d = hub.store.read_json(rel) or {}
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("machine") != me and d.get("week") == wk:
            v = ledger._num(d.get("usd"))
            total += max(0.0, v or 0.0)
    return round(total, 6)


# -- named agents: the card and the face, never the memory --------------------------------------------------------
def _agents_out(hub, home: Path, st: dict[str, Any]) -> dict[str, Any]:
    from ..core.store import BinaryFile, TextFile

    try:
        from ..agents import FACE_SHARE_MAX, agents_dir
    except Exception:  # noqa: BLE001
        return {}
    root = agents_dir(home)
    out: dict[str, Any] = {}
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or not _AGENT_ID.match(d.name) or not (d / "agent.yaml").is_file():
            continue
        files: dict[str, Any] = {f"{AGENTS}/{d.name}/agent.yaml": TextFile((d / "agent.yaml").read_text(encoding="utf-8"))}
        for face in FACES:
            f = d / face
            if f.is_file() and f.stat().st_size <= FACE_SHARE_MAX:
                files[f"{AGENTS}/{d.name}/{face}"] = BinaryFile(f.read_bytes())
                break
        dg = hashlib.sha256(b"".join(bytes(v) if isinstance(v, bytes) else str(v).encode()
                                     for _, v in sorted(files.items()))).hexdigest()[:16]
        if st["agents"].get(d.name) != dg:
            out.update(files)
            st["agents"][d.name] = dg
    return out


def _agents_in(hub, home: Path) -> list[str]:
    """Agents made on another machine and missing here: their card and face (one already here is never changed)."""
    from ..sync import hub_root

    try:
        from ..agents import FACE_SHARE_MAX, agents_dir
    except Exception:  # noqa: BLE001
        return []
    src = (hub_root(hub) or Path("/nonexistent")) / AGENTS
    if not src.is_dir():
        return []
    root = agents_dir(home)
    taken = []
    removed = {x.name.rsplit("-", 1)[0] for x in (root / ".removed").iterdir()} if (root / ".removed").is_dir() else set()
    for d in sorted(src.iterdir()):
        if not d.is_dir() or not _AGENT_ID.match(d.name) or (root / d.name).exists() or d.name in removed:
            continue
        card = d / "agent.yaml"
        if not card.is_file() or card.stat().st_size > 64 * 1024:
            continue
        try:
            import yaml

            if not isinstance(yaml.safe_load(card.read_text(encoding="utf-8")), dict):
                continue
        except Exception:  # noqa: BLE001
            continue
        dest = root / d.name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "agent.yaml").write_text(card.read_text(encoding="utf-8"), encoding="utf-8")
        for face in FACES:
            f = d / face
            if f.is_file() and f.stat().st_size <= FACE_SHARE_MAX:
                (dest / face).write_bytes(f.read_bytes())
                break
        taken.append(d.name)
    return taken


# -- the seam sync.tick calls ----------------------------------------------------------------------------------------
def tick(app: Any) -> dict[str, Any]:
    """One round of sharing: publish this machine's changes, take the others'."""
    hub = getattr(app, "hub", None)
    if not hub:
        return {}
    try:
        cfg = app.cfg()
    except Exception:  # noqa: BLE001
        cfg = None
    if not cfg or not getattr(cfg, "lab_dir", None):
        return {}
    if not on(cfg):
        return {"off": True}
    try:
        home = app._backup_home()
    except Exception:  # noqa: BLE001
        home = None
    lock = getattr(app, "hub_lock", None)
    try:
        if lock is None:
            return share_round(hub, Lab(cfg.lab_dir), cfg, ledger.this_machine(), home)
        with lock:
            return share_round(hub, Lab(cfg.lab_dir), cfg, ledger.this_machine(), home)
    except Exception as e:  # noqa: BLE001 - sharing is a help; the next round tries again
        return {"error": f"learning: {e}"[:300]}
