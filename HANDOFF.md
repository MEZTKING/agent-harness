# Handoff – 27 November 2026 (night)

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
| Wave 5 → **1.1.0** | **Ready, not released**, on branch `d2-integrate` (on top of 1.0.0): the done list and prep, stages and parts, trying what was built and fixing what breaks, the App tab's Start, play-testing, real builds of EXE/APK/mod, stuck tasks worked out with handovers, money limits (agreed amount, autopilot's allowance, priced pictures). All tests green; DEVLOG has every hook-up |
| Beta in 1.1.0 | Only tried against stand-ins: a real Godot play, real EXE/APK/mod builds and starts, real browser journeys and the App tab's frame on Windows, the phone's done card and stage strip on a real phone |
| Wave 6 → **1.2.0** | **Ready, not released**, on branch `d3-integrate` (on top of 1.1.0): every model at once – the checking dial (Lean, Balanced, Maximum, priced on the plan, its own allowance), rivals on hard tasks, checkers from other makers who must quote what's broken, the router and Strengths, rival planners under Maximum, named agents, limits per service and job, "who has seen this project", `makers_allowed`. All tests green; DEVLOG has every hook-up and the 10 % figures |
| Beta in 1.2.0 | Only scripted so far: the real cost of the extra checking against the estimate, how often a checker must be asked again, real pickers and councils, OpenRouter's picture size, the phone's checking buttons on a real phone. The six starter faces are not made yet (initials show) |
| Waves 7–9 | Planned (PLAN.md's table): it learns, the parity sweep, the rows once declined |
| Phone ↔ PC sync, This phone | Built and tested with made-up hubs; **never run on real machines** |
| Engines | MCP tool servers (Unreal, Godot, Blender), the Godot checker – not yet tried with the real programs |

## 3. What to do next

1. Release 1.0.0 (CLAUDE.md "Releasing"): pull request from the session branch to `main`, CI
   green, merge, run `app.yml` with `release_tag: v1.0.0`; check the installer and both APK
   names are on the release; tell the owner plainly (the README's "What's new in 1.0.0").
2. On the owner's PC through Remote Control (once a folder is shared): the in-app update from
   0.12.0, the one-time firewall question, an old taskbar pin, the new Start-menu entry. On the
   phone by USB: the 1.0.0 test APK over 0.12.0, still paired.
3. Release 1.1.0 after 1.0.0 (branch `d2-integrate`; README "What's new in 1.1.0"). Before or soon after:
   on the owner's PC through Remote Control, play a real Godot game, build and start an EXE, build an APK and
   a mod jar, walk a web app with real Playwright, open the App tab's frame; then the small real DeepSeek run
   of a tiny browser game to watch the finishing loop with real models (estimate first, balance before and
   after).
4. Wave 6 / 1.2.0 (branch `d3-integrate`): make the six starter faces after the owner's yes (`agents.face_prompt`,
   at most $3, costs in `docs/art.md`, files in `ui/static/agents/<id>.webp`); one small real run on DeepSeek plus
   one other maker at Balanced (estimate first, balance before and after; write the real extra cost beside the
   10 % figures in DEVLOG); then release after 1.1.0.
5. At 1.2.0: remove the old-name starter (`packaging/old_name_starter.py`, the spec's second
   EXE, the installer lines) and point `upgrade-test` at the last 1.x installer.
6. `plans/gaps.md`: the picture gaps (editing, see-through, safe parallel spending), Ask me
   first on the phone, owner to-dos that leave the app, window pictures of an EXE and an emulator the
   harness starts (moved to wave 8). Wave 7: the lab learning from `reviews.jsonl` and the tag stats.

## 4. Where to read more

- The look: `docs/desktop-design.md` ("The look: Eclipse"), `docs/art.md` (every picture, its
  prompt and cost). The phone's look: `mobile/.../ui/theme/Theme.kt`.
- What the owner must do: `plans/owner-todo.md`; decisions made for them (with Fable's advice):
  `plans/notes-for-owner.md`.
- Parity with other harnesses: `plans/parity.md`; kinds: `plans/kinds.md`; the whole workflow:
  `plans/workflow.md`; borrowed ideas: `plans/inspiration.md`.
