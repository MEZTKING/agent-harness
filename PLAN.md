# Darkness Harness – plan

(Roundtable Hold before 1.0.0.)

The owner writes the idea and makes the decisions; models from every maker plan, build,
check and fix it together, and every task is easy to see on the desktop and the phone.
What was done when, and why: [DEVLOG.md](DEVLOG.md). Where things stand right now:
[HANDOFF.md](HANDOFF.md). What the harness couldn't do yet: [plans/gaps.md](plans/gaps.md).

## Darkness Harness: the releases from 1.0.0

The owner's aim (27 November 2026): whole apps and games from one idea, every model working at once, a
harness that improves itself, and a darker look. One wave of helpers per release:

| Wave | Release | What the owner gets | State |
|---|---|---|---|
| 1–3 | 0.10.0–0.12.0 | Autopilot, the done list, comfort on the phone, proof, rewind, web search, kinds | **Released** |
| 4 | 1.0.0 | The new name (Darkness Harness) and the new look (Eclipse); nothing installed is lost | **Ready**: put together on `d1-integrate`, waiting to be merged and released |
| 5 | 1.1.0 | Whole apps and games, finished and tested (stages, the done list, play-testing, money limits) | Being built on the `d2-*` branches |
| 6 | 1.2.0 | Every model at once, checking each other | Planned |
| 7 | 1.3.0 | It learns and improves itself: routing, prompts and tools, safely | Planned |
| 8 | 1.4.0 | Everything the other harnesses do (`plans/parity.md`) | Planned |
| 9 | 1.5.0 | The rows once declined, and the proof run | Planned |

Names machines read keep the old name for good: the `roundtable` package and command (`darkness` is a
second command), the repository, the installer's AppId, the phone's applicationId, the pairing link,
`remote.PREFIX`, `~/.roundtable` and the `ROUNDTABLE_*` variables. Old data folders, keys and the
projects folder are used where they are; nothing is moved.

## Decisions so far (before 1.0.0, under the old name)

- **One interface for every provider** (Anthropic native, OpenAI-compatible for
  DeepSeek and others, image APIs, plugins); roles map to models in config, with
  fallback chains. Any model, any maker, is the point.
- **The plan is the product** (25 November 2026, the owner chose Fable's advice and
  order). An idea becomes a living plan document – summary, in and out of scope, don'ts,
  spec, decisions with options and a recommendation, questions, ideas, a critique by a
  second model, an estimate – that the owner argues with before anything is built.
- **Proof, not opinions:** a task counts as done when it builds, passes tests, starts
  and looks right, not when a reviewer says "looks good" (release 2).
- **The phone can also be a seat of its own** (owner, 26 November 2026: "use my phone as harness
  itself so I'm not using GitHub … just like DSH Mobile"; Fable's plan in plans/notes-for-owner.md):
  Roundtable runs on the phone in a small Linux inside the app, synced with the hub in the
  background. Heavy builds (APK, EXE, game engines) stay on the PC.
- **The phone is a window on the desktop app** too: The Table
  (concept A) with decision cards (B) and notifications (C). Away from home it works
  through the hub (commands as hub messages).
- **Sessions:** drive Claude Code as a worker first, then Roundtable's own loop for every
  other model (release 4).
- **Tandem where it pays:** second opinions on plans and designs, best-of-several only
  on hard tasks, escalation from cheap to strong (release 5).
- **Use Roundtable, and grow it** (26 November 2026): what it can't do becomes part of
  it, not a workaround (CLAUDE.md).
- **The whole workflow in one place** (26 November 2026): "Roundtable should be able to
  do my entire workflow in one place." Each step and where it stands:
  [plans/workflow.md](plans/workflow.md). Repositories and delivery come right after
  Proof, so merges without the owner watching are safe.
- **Kinds** (26 November 2026, the owner's idea, Fable's method): Roundtable reshapes itself for
  each sort of software through "kinds" – recipe cards of roles, prompts, tools, proof, build
  targets, the Look step, templates, plugins and default questions – not by rewriting its own
  code. The list of every kind and the first five: [plans/kinds.md](plans/kinds.md). Later: a
  harness that repairs itself ([plans/self-repair.md](plans/self-repair.md)).
- **Ideas from Munder Difflin and DeepSeek Harness Mobile** (26 November 2026, the
  owner's pick): evidence on every change, a circuit breaker per agent, CLIs driven
  through their own hooks, Needs you cards with one-tap answers, answers bound to the
  connection. Each idea, under its release: [plans/inspiration.md](plans/inspiration.md).
- **Yardstick:** each release is judged by how far a real project gets unaided. The
  first is a music player for the browser (`plans/music-player.md` in the hub); the
  owner chose web apps and browser games first, then desktop, Android, Minecraft/Java.
- **Defaults the owner chose for release 2:** proof for all kinds of project, web apps
  first; Claude for checking screenshots; the dial at Balanced.

## Releases

| # | Release | State |
|---|---|---|
| 0.1–0.5 | Hub, harness, self-improvement, the desktop app and command centre, `roundtable connect` | **Released** (0.5.0) |
| 1 | **The living plan**: plan document, critique, edits that wait and one update, estimate, plans in the hub, commands through the hub | **Released** as 0.6.0; fixes since (answers kept across revisions, turned-down ideas stay out, a task carries on after running out of steps) are on the branch |
| 2 | **Proof it works, and a look of its own**: every task builds, passes tests and starts; screenshots checked by a model that can see; a Proof tab; a speed number per project; a project memory file. **The Look**: three mockups to choose from in the plan, a design file per project (colours, type, shapes, a signature detail, what never to do) that every task follows, screenshots checked against it, and no two projects alike. Web apps first, then desktop, Android, Java | Next – being shaped by the music player run |
| 3 | **Your repositories and delivery**: a project can be one of the owner's GitHub repositories; Roundtable follows its CLAUDE.md, reads its handoff, works on a branch, keeps its devlog, handoff and owner-todo, pushes, opens the pull request, watches and fixes CI, merges and releases (merge and release as Needs you cards unless the owner gave standing permission). See [plans/workflow.md](plans/workflow.md) | Not started (owner, 26 November: after Proof) |
| 4 | **Phone, first release**: pairing, The Table, Needs you cards, project, task, Minutes and Ask/Steer, new idea, notifications | Built and tried in Hub mode (`mobile/`); not released |
| 5 | **Sessions**: work in any repository from Roundtable – Claude Code driven as a worker, then the own loop; approvals, changes view, terminal, resume | Not started |
| 6 | **True tandem**: parallel tasks in separate worktrees, routing by kind of job, best-of-several, escalation, the Careful / Balanced / Fast dial, a sandbox for commands | Not started |
| 7 | **Games and assets**: style guide and asset checks, sound and music, an approval gallery, scripted playtesting | Not started |

Explicitly not, for now: no 3D pipeline, no store publishing, no more than about four
tasks at once, no automatic merging of conflicts without review.

## Done before the releases above

- **Hub:** agent registry, permission policy, file and git storage, project cards,
  messaging, change notifications, MCP server, CLI, the project journal.
- **Harness:** provider adapters, roles with fallback chains, planner, review and retry,
  git-backed workspace, budget, approval gate, resume, hub reporting, per-attempt
  metrics.
- **Self-improvement:** metrics, reviewer feedback and owner ratings → proposals
  (routing, prompts, options) → replay tests on real past tasks → manual or policy-based
  apply → versioned learned overlay with exact rollback; model health probes.

Possible later: new-model scouting on past tasks; routing by kind of task (front end,
back end, shaders); a hosted real-time hub; an A2A bridge.
