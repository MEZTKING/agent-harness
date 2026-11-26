# The owner's whole workflow in Roundtable

The owner (26 November 2026): "Basically Roundtable should be able to do my entire
workflow in one place." This is that workflow, step by step, as it runs today across
Claude Code sessions, GitHub and the owner's repositories, and what Roundtable can do
of each. Every "No" or "Part" is a gap (plans/gaps.md) with a release in PLAN.md.

| # | Step | Today, done by | Roundtable | Release |
|---|---|---|---|---|
| 1 | Write the idea; get a plan with choices, recommendations, don'ts, questions; answer from the phone | Roundtable | **Yes** (the living plan, the phone) | 1 ✓ |
| 2 | Work **in my existing repositories** (MSE-Studio-Engine, MCSuperMods, blockloom, …), on the session's branch, following each one's CLAUDE.md / AGENTS.md / WORKING-RULES.md | Claude Code sessions | **No**: projects live in Roundtable's own lab folders | 3 |
| 3 | Read where the last session left off (HANDOFF.md, the newest DEVLOG.md entries, plans/owner-todo.md) before starting | Claude Code sessions | **Part**: the hub journal, not the repo's own files | 3 |
| 4 | The right model for each job (strongest for hard design, Opus for careful coding, Sonnet for bounded work), with a full brief | Claude Code with sub-agents | **Part**: roles and fallbacks; no "kind of job" routing | 5 |
| 5 | Several agents at once, one worktree and branch each, files assigned; one merges and re-runs everything | Claude Code with sub-agents | **No**: one task at a time, one folder | 5 |
| 6 | Proof: tests pass, the thing builds and starts, screenshots I can see | Claude Code by hand | **No**: one reviewer's opinion | 2 |
| 7 | Keep the devlog (a new entry at the top), the handoff, owner-todo and "Decided for you" | Claude Code by hand | **No** | 3 |
| 8 | Commits in my style (no attribution, no model names, `[skip ci]` where builds cost money); push the branch | Claude Code | **Part**: commits in its own folder; no push | 3 |
| 9 | Pull request, wait for CI, fix what fails, merge when it's green | Claude Code with the GitHub tools | **No** | 3 |
| 10 | Release when I say so: raise the version, run the workflow, check the release exists, tell me plainly what's out | Claude Code with the GitHub tools | **No** | 3 |
| 11 | Sessions in the other repositories talk to each other; send one clear instruction to another session | The hub + Claude Code | **Yes** (hub, `roundtable connect`) | ✓ |
| 12 | Chat with a model in any folder, see its edits and commands, approve the risky ones, resume later | Claude Code, DeepSeek Harness | **No** | 4 |
| 13 | Money: an estimate before, the real cost after, stop and ask when it runs over | Me, by hand | **Yes** now (estimate, real balance); the estimate's defaults are guesses | 2 |
| 14 | Decisions and news on my phone: approve, choose, failures, money | Roundtable Mobile | **Yes** in Hub mode; not released | Phone |
| 15 | Cloud environments, keys through the credential form, other machines | claude.ai settings | **No** (and partly can't be: those are claude.ai's settings) | later |
| 16 | Art and sound for games, checked against a style | Partly (images) | **Part** | 6 |

## What "in one place" needs, in short

- **A project can be one of my repositories** (owner/name, a branch), not only a lab
  folder. Roundtable clones it, reads its rules and handoff, works on a branch, and the
  repository's own documents are kept up to date the way its CLAUDE.md says.
- **Delivery:** push, pull request, CI watched and fixed, merge, release – each step shown
  as a task and each one that's mine (merge, release) waiting as a Needs you card unless
  I've given standing permission for that repository.
- **Proof** before delivery, so unattended merges are safe.
- **Sessions** for the work that isn't a plan: a chat with any model in any folder.
