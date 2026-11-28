# Handoff – 28 November 2026 (wave 9, step 0)

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
| Waves 4–8 → **1.0.0 to 1.4.0** | **On `main`; 1.3.0 and 1.4.0 are released from it** (1.4.0 merged as #25). 1.0.0 the new name and the Eclipse look; 1.1.0 the done list, stages, finishing, real builds, money limits; 1.2.0 every model at once (the checking dial, rivals, the router, named agents); 1.3.0 it learns (the allowance, the charter, plug-ins in a box, search by meaning); 1.4.0 the board, words as they are written, `/` commands, follow-ups, timers, what each job may do, the editor and previews, work from outside, CI, the stand-up. DEVLOG has every hook-up. If a release of 1.0.0 to 1.2.0 is missing on GitHub, check before cutting 1.5.0 |
| Beta (1.1.0 to 1.4.0) | Untried on real machines: a real Godot play, real EXE/APK/mod builds, window pictures, the emulator, junctions, the editor/PDF/Talk in the frozen app, engines installing themselves, the frozen `--python` and `--plugin-box`, the real cost of the checking dial and of a learning cycle, the six starter faces (initials show) |
| Phone Part B | **On the session branch** `ccr-fca0772b-7ma69z` (commit 4d0e2e6, after 1.4.0, not released): words as they are written, the `/` menu, the queue, follow-ups, the new-project cards, timers' lines, the team, documents, previews and Talk on the phone. What it left is wave 9 helper 4 |
| Wave 9 → **1.5.0** | **Step 0 done** (branch `w9-step0`, to be merged into the session branch): the seams with frozen signatures for the seven helpers (sound, the office, languages, the phone, the rows once declined, the biggest gaps, the proof run), the six phone routes Part B left with `phone.PHONE_NARROW`, This phone checked to answer like the PC, `docs/sound.md` (prices read on the day). A bare run sends byte for byte the same requests (`tests/test_wave9_seam.py`). The plan: the coordinator's `wave9-plan.md`; each open row names its helper in `plans/parity.md` and `plans/gaps.md` |
| Phone ↔ PC sync, This phone | Built and tested with made-up hubs; **never run on real machines** |
| Engines | MCP tool servers (Unreal, Godot, Blender), the Godot checker – not yet tried with the real programs |

## 3. What to do next

1. Merge `w9-step0` into the session branch; branch the seven wave 9 helpers off it (`w9-sound`, `w9-office`,
   `w9-words`, `w9-phone`, `w9-local`, `w9-gaps`, `w9-proof`), each in its own worktree; merge them in that
   order, `w9-phone` Part B last (it sweeps words in files the others add).
2. The owner's questions, each a one-tap card: which sound service (ElevenLabs about $6 a month, or Stable
   Audio at about 8 cents a clip – `docs/sound.md`); the office's sample sheet after its quote; the iPhone
   page (Fable's advice first); which languages ship; the proof run (at most $3).
3. Spend only after the merges, each priced first and written in DEVLOG: the language tables, the sound
   adapters' real calls, the office art (at most $10), the proof run, one real streamed call per provider.
4. Release 1.5.0 (CLAUDE.md "Releasing").
5. On the owner's PC and phone through Remote Control: the beta list above, wave 8's table in DEVLOG's 1.4.0
   entry, and wave 9's (the office in the frozen window, a bought sound playing, Arabic on both, Part B's
   leftovers on a real phone).

## 4. Where to read more

- The look: `docs/desktop-design.md` ("The look: Eclipse"), `docs/art.md` (every picture, its
  prompt and cost). The phone's look: `mobile/.../ui/theme/Theme.kt`.
- What the owner must do: `plans/owner-todo.md`; decisions made for them (with Fable's advice):
  `plans/notes-for-owner.md`.
- Parity with other harnesses: `plans/parity.md`; kinds: `plans/kinds.md`; the whole workflow:
  `plans/workflow.md`; borrowed ideas: `plans/inspiration.md`.
