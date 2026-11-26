# Ideas borrowed from two open-source projects

The owner (26 November 2026) asked to take inspiration from:

- **Munder Difflin** (github.com/HarnessMD/munder-difflin, MIT; its pixel art is not):
  a desktop "office" of agents, each a real coding CLI (Claude Code, Codex, Gemini,
  OpenCode and more) on the owner's own subscriptions, with an orchestrator, a shared git
  "hive" of mailboxes, memory and a task board, and an "Ask me" queue. It came from a
  Reddit post, "My view when my opencode agents are working".
- **DeepSeek Harness Mobile** (github.com/sorsama/deepseek-harness-mobile, MIT): a phone
  client for the DeepSeek Harness, with approvals, live replies, a terminal, files,
  changes, rewind and notifications.

We take **ideas, not code**. Each idea is listed under the release it belongs to
(PLAN.md), and then marked done in the devlog when it's built.

## Release 2 – Proof it works

- **Evidence on every change.** Munder Difflin won't merge a pull request without
  screenshots under "Before" and "After" (or a recording, or red-then-green tests, or a
  measurement for speed). A Roundtable task attaches its proof the same way: test
  output, a screenshot, a number, and the reviewer judges the proof, not the code.
- **A fake model that follows a script, run against the real Roundtable.** Their
  conformance suite runs the real server with a scripted model, so everything is tested
  without a paid key. We have scripted providers; extend them to drive the desktop and
  phone end to end.
- **A time breakdown per task**: waiting for the first word, the model writing, tools,
  waiting for the owner. Unrecorded time is left out, never shown as zero.
- **Cost counted the right way** (partly done 26 November): "work tokens" (input, output
  and cache writes; cache reads apart), running totals that survive restarts, and the
  provider's own balance or quota where it reports one, never a guess.

## Release 3 – Your repositories and delivery

- **Webhooks and schedules start work**: CI results and GitHub events become tasks, with
  a trust mode (everything waits for the owner, or only instructions do, or nothing
  does).
- **Keys through a broker**: an agent calls a local address and Roundtable adds the key,
  so agents never see secrets, and a key saved later reaches running agents.
- **No destructive default**: removing a worktree or a branch must say why; a folder
  with uncommitted work is kept.

## Release 4 – The phone

- **Needs you cards straight from the list**, with options, the recommendation and
  more than one choice where it fits. One-tap approval only for short things (their rule:
  four lines); longer ones open for review. Approve and Reject on the notification
  itself.
- **Answers bound to the connection**: an answer typed before the phone lost its link
  can't settle a request the PC has since asked again. No retry queue for answers.
- **Notifications from one classifier**: finished, needs you, failed, money, idle, each
  with its own channel and a key so the same news never comes twice; quiet only when
  that project is open on screen; a tap opens it.
- **Staying connected**: an opt-in background service and a 15-minute fallback; backoff
  with jitter; a resume from the last seen item instead of a full reload; a slower
  keep-alive than theirs (2 seconds is hard on a battery).
- **Failures named with one fix each** ("Nothing answered", "Not on this phone's
  network", "Pair again").
- **Drafts that survive** an interruption, and **dictation** for new ideas.
- Keep what we do better: Hub mode works without the PC, routes are whitelisted (give
  each paired phone its own scope, for example read-only), TLS is always pinned, and the
  pinned key doesn't change when the PC changes network.

## Release 5 – Sessions

- **Drive CLIs headless where possible** (`claude -p --output-format stream-json`,
  `codex exec --json`); a real terminal only for "chat in any folder".
- **One table per engine**: its command, model and resume flags, how to give it the first
  prompt, its compact and clear commands (`null` when not checked), and how to install
  it. A missing CLI shows one Install button.
- **Control through the CLI's hooks, not keystrokes**: pause or a refused tool is a "deny"
  answer, steering is extra context on the next turn, stop is "don't continue".
- **The owner owns the prompt**: queued messages wait while the agent is busy or the
  owner is typing; automation never wipes a draft or presses Escape.
- **Never type into a permission question**; proof of delivery comes from the CLI's own
  "prompt submitted" signal, not from timing.
- **Live replies as one provisional row** that the saved message replaces; only the
  settled message is written to git.
- **Queue or steer**: "next turn" or "into the running turn", chosen in the composer.
- **The changes of each turn** as a folded "Changed 3 files" row; **rewind** with a
  preview of the files it would restore; fork.
- **Readable tool cards** with copy, open and "show raw", and a setting for how much
  detail to show.
- **Resume only what the CLI can really open**; reap stray processes at start only when
  their identity matches.

## Release 6 – True tandem

- **A circuit breaker for every agent**, checked every 30 seconds, one step at a time:
  healthy → steering → limited → stopped. It trips on 8 identical tool calls in a row,
  5 errors in a row, runaway output, a token or money cap, or no progress for 5 minutes.
  It's quiet during compaction, and the same warning is never sent twice in 10 minutes.
  The limited step really refuses tools (theirs only asks politely).
- **Helpers in their own worktrees** asked for as small request files with an objective,
  a model and a token cap; a switch and a limit on how many run at once.
- **A fleet file** the planner reads: every agent's state, tokens, cost, breaker level and
  last action.
- **Handoffs per piece of work**, and a clean start (handoff, then clear) when an agent
  switches to different work.

## The hub and the journal (any release)

- **Message envelope**: a type (request, inform, propose, query, agree, refuse, done),
  a thread, a hop count Roundtable controls (dropped past 12), and mail to an unknown
  address goes back to the sender, never lost. "Never send a message that only says
  thanks."
- **One committer, batched commits**: git is slow and fights over its lock; commit in
  batches off the main path, and keep logs and ledgers out of git.
- **Memory without a model**: rules that never move, pinned facts, recent notes; old
  lines move word for word to an archive that's searched, never summarised away.
- **Task cards keep their fields** when an agent rewrites the list; done cards are
  archived; a card waiting on the owner is never called stale.

## What not to copy

- Long files that do everything (theirs: 8,400 and 3,400 lines); design docs that no
  longer match the code; an orchestrator whose rules live only in its prompt (ours makes
  structured decisions that code checks).
- Screen-scraping and timing tricks to drive CLIs; many engines marked "not checked".
- Any signed-in phone getting the whole PC (theirs has no lesser access); plain HTTP on
  the local network; a pairing key that changes with the network.
- A protocol that changes every release: version ours and publish one schema.
