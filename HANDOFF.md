# Handoff – 26 November 2026 (evening)

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
| Desktop app | **0.9.0** (26 November): rebuilt from scratch (`ui/static/` ES modules, design in `docs/desktop-design.md`): the Hall with every project as a seat, Needs you first, editable routing, Settings for everything (keys with a real Test, recommended setup, spending, hub, phone pairing, backups, plugins, updates). Claude Opus 5.5 (medium) codes by default, DeepSeek V4 Flash backs it up; no V4 Pro (owner) |
| Roundtable Mobile | 0.9.0 test APK on the release (updates itself from Settings → About): plain words, Needs you organised, several connections at once (This phone + PC + hub), Your computers, watch builds anywhere, shared settings. **This phone (beta)**: Roundtable inside the app (proot), runtime releases `runtime-…` signed with the TEST key |
| Phone ↔ PC sync | Built (`sync.py`, `ui/syncapi.py`, `data/MultiBackend.kt`): machine seats, claims, live sessions, shared settings, carry on, pairing. **Never run on real machines** |
| Existing apps (repository mode) | Built: own branch, the repo's rules, baseline + new-failure checks, per-project settings file. Tried on MSE Studio (plan made, then the owner paused it; nothing pushed) |
| Engines | MCP tool servers (Unreal, Godot, Blender), the Godot game checker – not yet tried with the real programs |
| Hub (`agent-hub-data`) | Agents: harness, mse-studio-engine, mcsupermods, blockloom, cutline-studio, music-player, me, knightgame, agent-harness; the owner's to-do list is empty |

**The next step everything waits on:** the owner shares one folder from the Claude desktop app
(suggested `C:\Users\Rakib\Roundtable`, Settings → Claude Code → Remote Control) and plugs the phone in
by USB; then test on the real PC and phone (CLAUDE.md "Test on the owner's PC"): the 0.9.0 desktop, pairing,
This phone, the sync, Godot, Unreal.

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

1. Check the 0.9.0 release and the runtime release exist; tell the owner.
2. Real-machine tests once a folder is shared (above); fix what they find.
3. plans/gaps.md: Ask me first on the phone, owner to-dos that leave the app, the estimate's picture
   prices, a model set's own changes shared between machines, the phone's release signing key.
4. Then: kinds (plans/kinds.md), proof for more app types, the owner's next project.
