# Handoff – 26 November 2026

For the next agent (any model, any tool). Read this first, then `AGENTS.md` (short
rules), `CLAUDE.md` (the same rules in full), `PLAN.md`, the newest entries of
`DEVLOG.md`, `plans/owner-todo.md` and `plans/gaps.md`. Nothing important lives only
on a machine (`/tmp`, the scratchpad and the yardstick lab are throw-away).

## 1. What this is

Roundtable Hold: the owner writes an idea, Roundtable turns it into a plan they argue
with, then models from every maker build it task by task, each task reviewed, all of it
visible on the desktop app and the phone. Details: CLAUDE.md, "The pieces".

## 2. Where things stand

| Piece | State |
|---|---|
| Desktop app | **0.7.0 being released** from the session branch (see DEVLOG): tap-to-answer cards, the Candlelit Oak look, the Look step, references, plugins (token saver built in), backups, picture models, Budget / Balanced / Quality, OpenRouter and Openference, real-money limits, off-peak starts, learned model switches |
| Roundtable Mobile | Built (cards and the new look included); not released (needs a signing key) |
| Hub (`agent-hub-data`) | Agents: harness, mse-studio-engine, mcsupermods, blockloom, cutline-studio, music-player, me |
| The yardstick (music player) | Finished: web app (Record Shop Sleeve look), Android APK and Windows EXE sent to the owner (not yet tried on real devices). About $13 of real money spent on the day across DeepSeek and OpenRouter, much of it on Roundtable faults now fixed |

## 3. Where to read more

- What the owner must do: `plans/owner-todo.md`; decisions made for them (with Fable's advice):
  `plans/notes-for-owner.md`.
- What Roundtable can't do yet: `plans/gaps.md`. Next releases: `PLAN.md` (Proof it works next),
  then kinds (`plans/kinds.md`), self-repair later (`plans/self-repair.md`), the whole workflow
  (`plans/workflow.md`), borrowed ideas (`plans/inspiration.md`).
- The lab used for real runs is throw-away (the scratchpad `yard/`); its harness.yaml shows the
  owner's split: Openference and OpenRouter for planning, design and checks, DeepSeek V4.1-Flash
  direct for coding, GLM-5.3 through OpenRouter as fallback; no DeepSeek V4 Pro for now (owner).

## 4. What to do next

1. Check the 0.7.0 release exists and works; tell the owner.
2. Release 2, "Proof it works": automatic build, test, start and screenshots judged by a seeing
   model; stop and ask above the shown estimate; task sizing; project memory of the machine.
3. Kinds: the web app kind and one-tap APK/EXE extras first.
