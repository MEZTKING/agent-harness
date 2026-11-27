# Handoff – 27 November 2026 (evening)

For the next agent (any model, any tool). Read this first, then `AGENTS.md` (short
rules), `CLAUDE.md` (the same rules in full), `PLAN.md`, the newest entries of
`DEVLOG.md`, `plans/owner-todo.md`, `plans/notes-for-owner.md` and `plans/gaps.md`.
Nothing important lives only on a machine (`/tmp`, the scratchpad and any lab are
throw-away).

## 1. What this is

**Darkness Harness** (Roundtable Hold before 1.0.0): the owner writes an idea, the harness
turns it into a plan they argue with, then models from every maker build it task by task,
each task reviewed and proved, all of it visible on the desktop app and the phone. The aim
from 1.0.0: whole apps and games from one idea, every model at once, a harness that
improves itself. Details: CLAUDE.md, "The pieces".

Names machines read keep the old name for good: the `roundtable` package and command
(`darkness` is a second command), the repository `MEZTKING/agent-harness`, the installer's
AppId, the phone's applicationId `com.meztking.roundtable`, the `roundtable://pair` link,
`remote.PREFIX` (`roundtable:`), `~/.roundtable`, `ROUNDTABLE_*` variables and `rt-theme`.
`tests/test_passage.py` and `tests/test_brand_words.py` guard both sides of that line.

## 2. Where things stand

| Piece | State |
|---|---|
| Waves 1–3 | **Released** as 0.10.0, 0.11.0 and 0.12.0: autopilot and several tasks at once, comfort on the phone, proof, rewind, web search, kinds, the command line, pounds |
| Wave 4 → **1.0.0** | **Ready, not released**: the new name and the Eclipse look on the PC and the phone, the safe upgrade (old data folder, keys and pairing used where they are; an old-name starter exe; both APK names; the firewall rules moved). Put together on branch `d1-integrate`; all tests green. The `upgrade-test` CI job already passed once |
| Wave 5 → 1.1.0 | Being built on the `d2-*` branches (stages, the done list, finishing, play-testing, money limits, shipping, unsticking). Step 0 (the stages' seam, behaviour-neutral) is already in 1.0.0 |
| Waves 6–9 | Planned (PLAN.md's table): every model at once, it learns, the parity sweep, the rows once declined |
| Phone ↔ PC sync, This phone | Built and tested with made-up hubs; **never run on real machines** |
| Engines | MCP tool servers (Unreal, Godot, Blender), the Godot checker – not yet tried with the real programs |

## 3. What to do next

1. Release 1.0.0 (CLAUDE.md "Releasing"): pull request from the session branch to `main`, CI
   green, merge, run `app.yml` with `release_tag: v1.0.0`; check the installer and both APK
   names are on the release; tell the owner plainly (the README's "What's new in 1.0.0").
2. On the owner's PC through Remote Control (once a folder is shared): the in-app update from
   0.12.0, the one-time firewall question, an old taskbar pin, the new Start-menu entry. On the
   phone by USB: the 1.0.0 test APK over 0.12.0, still paired.
3. Merge wave 5's `d2-*` branches when their helpers report, then 1.1.0.
4. At 1.2.0: remove the old-name starter (`packaging/old_name_starter.py`, the spec's second
   EXE, the installer lines) and point `upgrade-test` at the last 1.x installer.
5. `plans/gaps.md`: the picture gaps (editing, see-through, safe parallel spending, size), Ask me
   first on the phone, owner to-dos that leave the app.

## 4. Where to read more

- The look: `docs/desktop-design.md` ("The look: Eclipse"), `docs/art.md` (every picture, its
  prompt and cost). The phone's look: `mobile/.../ui/theme/Theme.kt`.
- What the owner must do: `plans/owner-todo.md`; decisions made for them (with Fable's advice):
  `plans/notes-for-owner.md`.
- Parity with other harnesses: `plans/parity.md`; kinds: `plans/kinds.md`; the whole workflow:
  `plans/workflow.md`; borrowed ideas: `plans/inspiration.md`.
