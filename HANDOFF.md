# Handoff – 28 November 2026 (wave 9 and the chat merged, 1.5.0 not released)

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
| Phone Part B | **Merged** into the session branch before wave 9 (commit 4d0e2e6); its leftovers (Part A of w9-phone) are in `w9-integrate` |
| Wave 9 → **1.5.0** | **Merged** on branch `w9-integrate` (all seven helpers and every hook-up line; version 1.5.0; not pushed, not released): sound (ElevenLabs, Stable Audio, $2 a project, made in code otherwise), the office (built; its pictures not made), eleven languages and right to left (built; the tables not made; the sweep done), to-dos as buttons and every hub project a seat with who runs it (`reach.readers`), the set-up a repository declares, the estimate's defaults from real runs, the critic looking again, local counts and run timelines, the iPhone page (built, off), a running app's frame on the phone, the proof run, a picture limit per project, the phone's Part A. **Not done:** the coordinator's paid runs, the phone's Part B (languages) |
| The chat → **1.5.0** | **Merged** on branch `chat-integrate` (step 0, chat-server, chat-desktop, chat-phone and every hook-up; not pushed): a chat for each project and one for everything (Hall) on the PC and the phone, in place of Letters; DeepSeek V4 Flash, $1 a day (Settings → Spending, shared); cards for anything that spends; the phone answers by itself with its own DeepSeek key; old letters under "Earlier messages"; the Letters screens deleted. Untried on a real PC and phone; the ten-message real check and the owner's music-player test are still to do |
| Phone ↔ PC sync, This phone | Built and tested with made-up hubs; **never run on real machines** |
| Engines | MCP tool servers (Unreal, Godot, Blender), the Godot checker – not yet tried with the real programs |

## 3. What to do next

1. Merge `w9-integrate` into the session branch (all tests green there: see DEVLOG's newest entry).
2. The coordinator's paid runs, each priced first, the real figure in DEVLOG (the list and the estimates are in
   DEVLOG's newest entry): the language tables (about $0.92), the sound adapters' real calls (about $0.30), the
   office art (quote free, sample at most $1.50, the rest only after the owner's yes, at most $10 in all), the proof
   run (at most $3), one real streamed call per provider.
3. Ask Fable, and note in `plans/notes-for-owner.md`: the iPhone page and its certificate, the frame relay, the
   loopback telemetry receiver and the outside-collector switch, sound licences for a game the owner might sell,
   a subscription as a service's price, machine-translated words shipped and labelled.
4. The phone's Part B (the language tables in the APK, plural forms, right to left), after the tables exist.
5. The chat (merged on `chat-integrate`): the real check first, ten messages in a made-up project on DeepSeek V4
   Flash with the balance read before and after (about one cent); then on the owner's PC and phone through Remote
   Control: the installed build shows the chat and streams, `#/letters` lands on it, the hub's old letters show
   under Earlier messages and `inbox/` is unchanged; the test APK installs over the last one and the Chat tab answers
   in all three modes. Then the owner drives the music player's five accepted ideas through it (at most $2) before
   the release. What it leaves: `plans/gaps.md` ("The chat, what 1.5.0 leaves", "A hub request can't be proven to
   come from a tap").
6. Release 1.5.0 (CLAUDE.md "Releasing").
7. On the owner's PC and phone through Remote Control: the beta list above, wave 8's table in DEVLOG's 1.4.0
   entry, and wave 9's (the office in the frozen window, a bought sound playing, Arabic on both, Part A's
   screens on a real phone).

## 4. Where to read more

- The look: `docs/desktop-design.md` ("The look: Eclipse"), `docs/art.md` (every picture, its
  prompt and cost). The phone's look: `mobile/.../ui/theme/Theme.kt`.
- What the owner must do: `plans/owner-todo.md`; decisions made for them (with Fable's advice):
  `plans/notes-for-owner.md`.
- Parity with other harnesses: `plans/parity.md`; kinds: `plans/kinds.md`; the whole workflow:
  `plans/workflow.md`; borrowed ideas: `plans/inspiration.md`.
