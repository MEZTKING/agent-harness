"""The repository's own rules: its CLAUDE.md, AGENTS.md and the newest devlog entry, trimmed to a budget.

The text is the same on every call of a run, so it sits in the models' system prompt where the
prompt cache keeps it (see ``RepoStage._with_repo_rules``).
"""

from __future__ import annotations

import re
from pathlib import Path

ENTRY_FILES = ("DEVLOG", "HANDOFF", "CHANGELOG", "NEWS")  # for these only the newest entry counts
_HEADING = re.compile(r"^(#{1,6})\s+\S")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
CUT = "… (cut to fit)"


def _headings(lines: list[str]) -> list[tuple[int, int]]:
    """(line index, level) of every Markdown heading outside code fences."""
    out, fenced = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((i, len(m.group(1))))
    return out


def newest_entry(text: str, name: str = "") -> str:
    """The newest entry of a devlog-like file: the section with the latest date in its heading, else the
    first one (a handoff without dates is read whole)."""
    lines = text.splitlines()
    heads = _headings(lines)
    levels = sorted({lv for _, lv in heads if lv > 1 and sum(1 for _, x in heads if x == lv) >= 2})
    if not levels:
        return text
    level = levels[0]
    starts = [i for i, lv in heads if lv == level]
    sections = []
    for n, start in enumerate(starts):
        end = next((i for i, lv in heads if i > start and lv <= level), len(lines))
        if n + 1 < len(starts):
            end = min(end, starts[n + 1])
        sections.append((start, end))
    dated = [(m.group(0), s) for s in sections if (m := _DATE.search(lines[s[0]]))]
    if dated:
        start, end = max(dated, key=lambda x: x[0])[1]  # ties keep the first (max returns the first)
    elif name.upper().startswith("HANDOFF"):
        return text
    else:
        start, end = sections[0]
    return "\n".join(lines[start:end]).strip()


def trim(text: str, budget: int) -> str:
    """At most ``budget`` characters, every heading kept, each section's body shortened fairly."""
    text = text.strip()
    if len(text) <= budget:
        return text
    lines = text.splitlines()
    heads = {i for i, _ in _headings(lines)}
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for i, line in enumerate(lines):
        if i in heads:
            sections.append((line, []))
        else:
            sections[-1][1].append(line)
    sections = [s for s in sections if s[0] is not None or any(x.strip() for x in s[1])]
    head_cost = sum(len(h) + 1 for h, _ in sections if h)
    body_budget = budget - head_cost - len(sections) * (len(CUT) + 1)
    if body_budget <= 0:  # only the headings fit (or not all of them)
        out, used = [], 0
        for h, _ in sections:
            if h and used + len(h) + 1 <= budget:
                out.append(h)
                used += len(h) + 1
        return "\n".join(out)
    sizes = {n: sum(len(x) + 1 for x in b) for n, (_, b) in enumerate(sections)}
    shares: dict[int, int] = {}
    left, todo = body_budget, sorted(sizes, key=lambda n: sizes[n])
    while todo:
        n = todo.pop(0)
        shares[n] = min(sizes[n], left // (len(todo) + 1))
        left -= shares[n]
    out = []
    for n, (h, body) in enumerate(sections):
        if h:
            out.append(h)
        keep, used = [], 0
        for line in body:
            if used + len(line) + 1 > shares[n]:
                room = shares[n] - used - 1
                if room > 40:
                    keep.append(line[:room])
                keep.append(CUT)
                break
            keep.append(line)
            used += len(line) + 1
        out.extend(keep)
    return "\n".join(out)[:budget]


def read_rules(root: str | Path, files: list[str], budget: int) -> list[tuple[str, str]]:
    """(title, text) for each rules file that exists, trimmed so all of them fit in ``budget`` characters."""
    root = Path(root)
    found: list[tuple[str, str]] = []
    for rel in files:
        p = (root / rel)
        try:
            if not p.is_file() or root.resolve() not in p.resolve().parents:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if Path(rel).name.upper().startswith(ENTRY_FILES):
            text = newest_entry(text, Path(rel).name)
            title = f"The newest entry of {rel}"
        else:
            title = rel
        if text.strip():
            found.append((title, text))
    out, left = {}, budget
    order = sorted(range(len(found)), key=lambda i: len(found[i][1]))
    for k, i in enumerate(order):
        share = left // (len(order) - k)
        out[i] = trim(found[i][1], share)
        left -= len(out[i])
    return [(found[i][0], out[i]) for i in range(len(found))]
