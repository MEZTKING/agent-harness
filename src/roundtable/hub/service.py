"""The Hub: project cards, messaging, and change notifications between agents.

On-disk layout (inside the store):

    cards/<agent>.json          one project card per agent
    inbox/<agent>/<msg-id>.json one file per delivered message (``hops``: how many replies deep it is)
    state/<agent>.json          {"read": [...msg ids], "subscriptions": [...agent ids]}

Every public method takes ``actor`` – the agent performing the action – and
enforces the policy from ``hub.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..core.config import HubConfig
from ..core.models import MESSAGE_KINDS, Message, ProjectCard, new_id, utcnow
from ..core.policy import PolicyError
from ..core.store import Store, iter_json, make_store

MAX_READ_IDS = 2000
# A conversation passed back and forth more than this many times is stopped and goes back to whoever sent the
# last one, so two agents can't keep answering each other for ever (Munder Difflin's hive does the same).
HOP_CAP = 12
# ``to="everyone"``: every agent in the hub but the sender, one copy each, all in one thread; replies go back to
# the sender only (``reply`` answers whoever sent it). Agents the rules don't let the sender message are left out.
EVERYONE = "everyone"


class HubError(ValueError):
    pass


class Hub:
    def __init__(self, config: HubConfig, store: Store | None = None):
        self.config = config
        self.store = store or make_store(config.storage, config.base_dir)
        from .journal import Journal

        self.journal = Journal(self)

    def refresh_config(self) -> bool:
        """Read the projects and rules again (after a sync brought a new hub.yaml); True when they changed.

        Storage stays as it is: only who is in the hub and what they may do can change while running."""
        from ..core.config import read_config

        try:
            fresh = read_config(self.config.path)
        except Exception:  # missing, half-written or broken: keep working with what was read before
            return False
        if fresh.agents == self.config.agents and fresh.policy == self.config.policy:
            return False
        self.config.agents, self.config.policy = fresh.agents, fresh.policy
        return True

    # -- helpers ----------------------------------------------------------
    def _require_agent(self, agent: str) -> None:
        if agent not in self.config.agents:
            self.refresh_config()  # added to the hub's hub.yaml since this was read
        if agent not in self.config.agents:
            known = ", ".join(sorted(self.config.agents)) or "(none)"
            raise HubError(f"unknown agent {agent!r}; known agents: {known}")

    def _state(self, agent: str) -> dict[str, Any]:
        state = self.store.read_json(f"state/{agent}.json") or {}
        state.setdefault("read", [])
        state.setdefault("subscriptions", [])
        return state

    def _load_card(self, agent: str) -> ProjectCard:
        data = self.store.read_json(f"cards/{agent}.json")
        if data:
            return ProjectCard.from_dict(data)
        spec = self.config.agents[agent]
        return ProjectCard(agent=agent, repo=spec.repo, summary=spec.description)

    def _allowed(self, source: str, target: str, action: str) -> bool:
        return self.config.policy.allowed(source, target, action)

    # -- directory ----------------------------------------------------------
    def list_agents(self, actor: str) -> list[dict[str, Any]]:
        self._require_agent(actor)
        out = []
        for agent_id, spec in sorted(self.config.agents.items()):
            out.append(
                {
                    "id": agent_id,
                    "repo": spec.repo,
                    "role": spec.role,
                    "description": spec.description,
                    "can_read_card": self._allowed(actor, agent_id, "read_card"),
                    "can_message": self._allowed(actor, agent_id, "message"),
                }
            )
        return out

    # -- cards ----------------------------------------------------------------
    def get_card(self, actor: str, agent: str) -> dict[str, Any]:
        self._require_agent(actor)
        self._require_agent(agent)
        self.config.policy.check(actor, agent, "read_card")
        self.store.sync()
        return self._load_card(agent).to_dict()

    def list_cards(self, actor: str) -> list[dict[str, Any]]:
        self._require_agent(actor)
        self.store.sync()
        out = []
        for agent_id in sorted(self.config.agents):
            if not self._allowed(actor, agent_id, "read_card"):
                continue
            card = self._load_card(agent_id)
            out.append(
                {
                    "agent": card.agent,
                    "repo": card.repo,
                    "summary": card.summary,
                    "status": card.status,
                    "updated_at": card.updated_at,
                    "last_change": card.recent_changes[0]["note"] if card.recent_changes else "",
                }
            )
        return out

    def update_card(
        self,
        actor: str,
        change_note: str | None = None,
        notify: bool = True,
        **fields: Any,
    ) -> dict[str, Any]:
        """Update the actor's own card. A ``change_note`` is logged and, if
        ``notify`` is true, pushed to subscribers and dependents."""
        self._require_agent(actor)
        bad = set(fields) - set(ProjectCard.EDITABLE)
        if bad:
            raise HubError(f"cannot edit field(s) {sorted(bad)}; editable: {ProjectCard.EDITABLE}")
        if "depends_on" in fields:
            deps = fields["depends_on"]
            if isinstance(deps, str):
                deps = [d.strip() for d in deps.split(",") if d.strip()]
            for d in deps:
                self._require_agent(d)
            fields["depends_on"] = list(deps)

        self.store.sync()
        card = self._load_card(actor)
        for key, value in fields.items():
            if value is not None:
                setattr(card, key, value)
        if change_note:
            card.add_change(change_note, by=actor)
        card.updated_at = utcnow()
        card.updated_by = actor

        writes: dict[str, Any] = {f"cards/{actor}.json": card.to_dict()}
        notified: list[str] = []
        if change_note and notify:
            for recipient in self.watchers(actor):
                msg = Message(
                    id=new_id(),
                    sender=actor,
                    recipient=recipient,
                    kind="notify",
                    subject=f"[{actor}] card updated",
                    body=change_note,
                    created_at=utcnow(),
                )
                msg.thread_id = msg.id
                writes[f"inbox/{recipient}/{msg.id}.json"] = msg.to_dict()
                notified.append(recipient)

        summary = f"card({actor}): {change_note or 'update'}"
        self.store.write_json(writes, summary[:200])
        return {"card": card.to_dict(), "notified": notified}

    def set_recent_commits(self, actor: str, commits: list[str]) -> dict[str, Any]:
        self._require_agent(actor)
        self.store.sync()
        card = self._load_card(actor)
        card.recent_commits = commits
        card.updated_at = utcnow()
        card.updated_by = actor
        self.store.write_json({f"cards/{actor}.json": card.to_dict()}, f"card({actor}): refresh commits")
        return card.to_dict()

    def watchers(self, agent: str) -> list[str]:
        """Agents that should hear about changes to ``agent``'s card:
        explicit subscribers plus anyone whose card depends_on it,
        filtered to those allowed to read ``agent``'s card."""
        out = set()
        for other in self.config.agents:
            if other == agent:
                continue
            if agent in self._state(other)["subscriptions"] or agent in self._load_card(other).depends_on:
                if self._allowed(other, agent, "read_card"):
                    out.add(other)
        return sorted(out)

    # -- subscriptions ----------------------------------------------------------
    def subscribe(self, actor: str, agent: str, on: bool = True) -> list[str]:
        self._require_agent(actor)
        self._require_agent(agent)
        if on:
            self.config.policy.check(actor, agent, "read_card")
        self.store.sync()
        state = self._state(actor)
        subs = set(state["subscriptions"])
        subs.add(agent) if on else subs.discard(agent)
        state["subscriptions"] = sorted(subs)
        verb = "subscribe" if on else "unsubscribe"
        self.store.write_json({f"state/{actor}.json": state}, f"{actor}: {verb} {agent}")
        return state["subscriptions"]

    # -- messaging ----------------------------------------------------------------
    def send(
        self,
        actor: str,
        to: str | list[str],
        subject: str,
        body: str,
        kind: str = "ask",
        in_reply_to: str | None = None,
        _thread_id: str | None = None,
        _skip_policy: bool = False,
        _hops: int | None = None,
    ) -> list[dict[str, Any]]:
        """Deliver a message (``to="everyone"``: every other agent the sender may message, in one thread). Past
        ``HOP_CAP`` replies in a row it isn't delivered: the sender gets it back with a note instead (the returned
        message then has ``bounced: true``)."""
        self._require_agent(actor)
        if kind not in MESSAGE_KINDS:
            raise HubError(f"kind must be one of {MESSAGE_KINDS}")
        recipients = [to] if isinstance(to, str) else list(to)
        recipients = [r.strip() for r in recipients if r and r.strip()]
        if EVERYONE in recipients:
            if EVERYONE in self.config.agents:
                raise HubError(f"an agent is called {EVERYONE!r}, so a message to everyone is ambiguous; "
                               "rename that agent in hub.yaml")
            self.refresh_config()
            rest = [r for r in recipients if r != EVERYONE]
            everyone = [a for a in sorted(self.config.agents) if a != actor
                        and (_skip_policy or self._allowed(actor, a, "message"))]
            recipients = list(dict.fromkeys(rest + everyone))
            if not recipients:
                raise HubError("nobody to send to: no other agent in the hub may be messaged by " + actor)
            _thread_id = _thread_id or new_id()  # one thread for the whole message
        if not recipients:
            raise HubError("no recipients")
        for r in recipients:
            self._require_agent(r)
            if not _skip_policy:
                self.config.policy.check(actor, r, "message")

        hops = self._hops_after(actor, in_reply_to) if _hops is None else _hops
        if hops > HOP_CAP:
            return [self._bounce(actor, recipients, subject, body, hops, in_reply_to, _thread_id)]

        writes: dict[str, Any] = {}
        sent = []
        for r in recipients:
            msg = Message(
                id=new_id(),
                sender=actor,
                recipient=r,
                kind=kind,
                subject=subject,
                body=body,
                created_at=utcnow(),
                in_reply_to=in_reply_to,
            )
            msg.thread_id = _thread_id or msg.id
            data = msg.to_dict() | {"hops": hops}
            writes[f"inbox/{r}/{msg.id}.json"] = data
            sent.append(data)
        self.store.write_json(writes, f"msg {actor} -> {','.join(recipients)}: {subject}"[:200])
        return sent

    def _raw_inbox_message(self, agent: str, message_id: str | None) -> dict[str, Any] | None:
        if not message_id or "/" in message_id or "\\" in message_id or message_id.startswith("."):
            return None
        return self.store.read_json(f"inbox/{agent}/{message_id}.json")

    @staticmethod
    def _hops_of(data: dict[str, Any] | None) -> int:
        try:
            return max(0, int((data or {}).get("hops") or 0))
        except (TypeError, ValueError):
            return 0

    def _hops_after(self, actor: str, in_reply_to: str | None) -> int:
        """A new message starts at 0; an answer to one in the actor's inbox is one more than that one."""
        if not in_reply_to:
            return 0
        parent = self._raw_inbox_message(actor, in_reply_to)
        return self._hops_of(parent) + 1 if parent else 1

    def _bounce(self, actor: str, recipients: list[str], subject: str, body: str, hops: int,
                in_reply_to: str | None, thread_id: str | None) -> dict[str, Any]:
        """The stopped message back in the sender's own inbox, with a plain note on top."""
        who = ", ".join(recipients)
        note = (f"Not sent to {who}: this conversation has gone back and forth {hops - 1} times, which is "
                f"more than {HOP_CAP}. It was stopped so it can't go round for ever. If it still needs an "
                "answer, start a new message with what is left to settle.")
        msg = Message(id=new_id(), sender=actor, recipient=actor, kind="notify", subject=f"Stopped: {subject}"[:300],
                      body=f"{note}\n\n--- What you tried to send ---\n{body}", created_at=utcnow(),
                      in_reply_to=in_reply_to)
        msg.thread_id = thread_id or msg.id
        data = msg.to_dict() | {"hops": hops, "bounced": True, "bounced_to": recipients}
        self.store.write_json({f"inbox/{actor}/{msg.id}.json": data},
                              f"msg {actor}: stopped after {hops - 1} replies: {subject}"[:200])
        return data

    def _get_inbox_message(self, agent: str, message_id: str) -> Message:
        if "/" in message_id or "\\" in message_id or message_id.startswith("."):
            raise HubError("invalid message id")
        data = self.store.read_json(f"inbox/{agent}/{message_id}.json")
        if not data:
            raise HubError(f"message {message_id!r} not found in {agent}'s inbox")
        return Message.from_dict(data)

    def reply(self, actor: str, message_id: str, body: str) -> dict[str, Any]:
        """Reply to a message in the actor's inbox. Replies are always allowed:
        the original sender started the conversation."""
        self._require_agent(actor)
        self.store.sync()
        original = self._get_inbox_message(actor, message_id)
        subject = original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}"
        return self.send(
            actor,
            original.sender,
            subject,
            body,
            kind="reply",
            in_reply_to=original.id,
            _thread_id=original.thread_id or original.id,
            _skip_policy=True,
            _hops=self._hops_of(self._raw_inbox_message(actor, original.id)) + 1,
        )[0]

    def inbox(
        self,
        actor: str,
        unread_only: bool = True,
        mark_read: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._require_agent(actor)
        self.store.sync()
        state = self._state(actor)
        read = set(state["read"])
        msgs = []
        for _, data in iter_json(self.store, f"inbox/{actor}"):
            m = Message.from_dict(data)
            is_read = m.id in read
            if unread_only and is_read:
                continue
            d = m.to_dict() | {k: data[k] for k in ("hops", "bounced", "bounced_to") if k in data}
            d["read"] = is_read
            msgs.append(d)
        msgs.sort(key=lambda d: d["created_at"])
        msgs = msgs[-limit:] if limit else msgs
        if mark_read and msgs:
            self.mark_read(actor, [m["id"] for m in msgs])
        return msgs

    def mark_read(self, actor: str, ids: list[str]) -> int:
        self._require_agent(actor)
        state = self._state(actor)
        read = list(dict.fromkeys(state["read"] + list(ids)))
        state["read"] = read[-MAX_READ_IDS:]
        self.store.write_json({f"state/{actor}.json": state}, f"{actor}: mark {len(ids)} read")
        return len(ids)

    def thread(self, actor: str, thread_id: str) -> list[dict[str, Any]]:
        """All messages in a thread visible to the actor (sent or received)."""
        self._require_agent(actor)
        self.store.sync()
        out = []
        for agent_id in self.config.agents:
            for _, data in iter_json(self.store, f"inbox/{agent_id}"):
                if data.get("thread_id") == thread_id and actor in (data.get("sender"), data.get("recipient")):
                    out.append(data)
        out.sort(key=lambda d: d["created_at"])
        return out


__all__ = ["EVERYONE", "Hub", "HubError", "PolicyError"]
