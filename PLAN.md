# Roundtable Hold – plan

The owner writes the idea and makes the decisions; models from every maker plan, build,
check and fix it together, and every task is easy to see on the desktop and the phone.
What was done when, and why: [DEVLOG.md](DEVLOG.md). Where things stand right now:
[HANDOFF.md](HANDOFF.md). What Roundtable couldn't do yet: [plans/gaps.md](plans/gaps.md).

## Decisions so far

- **One interface for every provider** (Anthropic native, OpenAI-compatible for
  DeepSeek and others, image APIs, plugins); roles map to models in config, with
  fallback chains. Any model, any maker, is the point.
- **The plan is the product** (25 November 2026, the owner chose Fable's advice and
  order). An idea becomes a living plan document – summary, in and out of scope, don'ts,
  spec, decisions with options and a recommendation, questions, ideas, a critique by a
  second model, an estimate – that the owner argues with before anything is built.
- **Proof, not opinions:** a task counts as done when it builds, passes tests, starts
  and looks right, not when a reviewer says "looks good" (release 2).
- **The phone is a window on the desktop app**, not a second product: The Table
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
| 2 | **Proof it works**: every task builds, passes tests and starts; screenshots checked by a model that can see; a Proof tab; a speed number per project; a project memory file. Web apps first, then desktop, Android, Java | Next – being shaped by the music player run |
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
