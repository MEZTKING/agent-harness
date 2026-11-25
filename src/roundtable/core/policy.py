"""Permission rules: who may read whose card and who may message whom.

Rules are evaluated in order; the *last* matching rule wins, so you can
write broad rules first and narrow exceptions after them. If no rule
matches, ``default`` applies.

    rules:
      - {from: "*", to: "*", allow: [read_card]}
      - {from: backend, to: frontend, allow: [message]}
      - {from: "*", to: finance, deny: [message]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase

ACTIONS = ("read_card", "message")


@dataclass
class Rule:
    source: str
    target: str
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def matches(self, source: str, target: str) -> bool:
        return fnmatchcase(source, self.source) and fnmatchcase(target, self.target)


class PolicyError(PermissionError):
    pass


@dataclass
class Policy:
    rules: list[Rule] = field(default_factory=list)
    default: str = "deny"  # "allow" | "deny"

    @classmethod
    def from_config(cls, rules: list[dict] | None, default: str = "deny") -> "Policy":
        if default not in ("allow", "deny"):
            raise ValueError(f"default_policy must be 'allow' or 'deny', got {default!r}")
        parsed = []
        for i, r in enumerate(rules or []):
            for key in ("allow", "deny"):
                bad = set(r.get(key, [])) - set(ACTIONS)
                if bad:
                    raise ValueError(f"rule #{i}: unknown action(s) {sorted(bad)}; valid: {ACTIONS}")
            parsed.append(
                Rule(
                    source=str(r.get("from", "*")),
                    target=str(r.get("to", "*")),
                    allow=list(r.get("allow", [])),
                    deny=list(r.get("deny", [])),
                )
            )
        return cls(rules=parsed, default=default)

    def allowed(self, source: str, target: str, action: str) -> bool:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        if source == target:
            return True  # an agent can always read/message itself
        decision = self.default == "allow"
        for rule in self.rules:
            if not rule.matches(source, target):
                continue
            if action in rule.deny:
                decision = False
            elif action in rule.allow:
                decision = True
        return decision

    def check(self, source: str, target: str, action: str) -> None:
        if not self.allowed(source, target, action):
            raise PolicyError(f"policy denies {source!r} -> {target!r} ({action})")
