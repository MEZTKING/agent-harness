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
| Desktop app | **0.6.0 released** (the living plan): `RoundtableHold-Setup-0.6.0.exe` on the v0.6.0 release. The owner has it installed (`roundtable version` on their PC) |
| Branch `ccr-fca0772b-7ma69z` | Ahead of `main`: plan fixes (answers kept, turned-down ideas stay out, carry-on after running out of steps), the phone app, these docs. Not yet merged or released |
| Roundtable Mobile | Built and tried in Hub mode; a test APK went to the owner on 25 November. PC mode untried. Not released (needs a signing key) |
| `roundtable connect` | Merged into main in MSE-Studio-Engine, MCSuperMods, blockloom and cutline-studio; their sessions report into the hub |
| Hub (`agent-hub-data`) | Agents: harness, mse-studio-engine, mcsupermods, blockloom, cutline-studio, music-player, me. Plans are published to `plans/<project>.md` |

## 3. The yardstick: the music player

A browser music player built only from the owner's answers (web app, no framework,
`file://`-runnable). Plan v5: 14 tasks; the owner's answers are all in (see
`plans/owner-todo.md`, "Decided for you"). Lab: a throw-away folder with a DeepSeek-only
`harness.yaml` (the planner on V4 Pro, everything else on V4 Flash) using the hub's
config.

Run so far: task 1 done and approved; task 2 ran out of steps (fixed in `2e1b1ba`) and
is being run again on its own, with the DeepSeek balance checked before (2.97 USD) and
after, to learn the real cost per task. Roundtable's count says about $1.34 spent in
all, which is probably too high (plans/gaps.md). **Ask the owner before building the
rest**, with the true total.

## 4. What to do next

1. Finish the cost check; put DeepSeek's real `cache_read` prices into the defaults and
   the template; fix the estimate's defaults (plans/gaps.md).
2. Tell the owner the true total and carry on with the music player if they agree.
3. Release 2, "Proof it works" (PLAN.md), shaped by what the music player run shows.
4. Then merge the branch and release (CLAUDE.md, "Releasing").
