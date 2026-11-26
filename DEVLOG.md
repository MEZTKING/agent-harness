# Roundtable Hold – devlog

Newest first. What was asked, what was done (files and functions, so the next session
finds them), what was decided and why, and what's still open. The plan is
[PLAN.md](PLAN.md); how to run things is in [README.md](README.md).

## 2026-11-26 – Ideas from Munder Difflin and DeepSeek Harness Mobile

The owner asked to take inspiration from a Reddit post ("My view when my opencode agents
are working"; Reddit refuses requests from here, so the post itself wasn't read), from
github.com/HarnessMD/munder-difflin and from github.com/sorsama/deepseek-harness-mobile.

- Both repositories were read (both MIT; we take ideas, not code).
- `plans/inspiration.md` (new): the ideas worth borrowing, each under its release –
  evidence on every change and a scripted-model test of the real server (Proof); webhooks
  with a trust mode and a key broker (Repositories); Needs you cards, answers bound to
  the connection, classified notifications, staying connected (Phone); headless CLIs,
  one table per engine, control through hooks, the owner owns the prompt (Sessions);
  the circuit breaker, helpers in worktrees, the fleet file (Tandem); the message
  envelope, batched commits and memory without a model (hub). Plus what not to copy.
- `PLAN.md`: the decision recorded.
- The owner forked both and chose that their code may be borrowed too (MIT), with
  credit in `THIRD_PARTY_NOTICES.md`; the forks stay untouched as the reference
  (CLAUDE.md, `plans/inspiration.md`).
- Open: build them, release by release.

## 2026-11-26 – The whole workflow in one place

The owner: "Basically Roundtable should be able to do my entire workflow in one place."

- `plans/workflow.md` (new): the owner's workflow in 16 steps (from the idea to the
  release, the devlog and the phone), who does each today and what Roundtable can do.
- `PLAN.md`: a new release 3, **Your repositories and delivery** (work in the owner's own
  GitHub repositories by their rules, keep their documents, push, pull request, CI,
  merge, release). The owner chose to put it right after Proof; the phone, sessions,
  tandem and games move to 4–7.
- Open: everything marked No or Part in `plans/workflow.md`.

## 2026-11-26 – The real cost: balance checks and a fairer price for cache hits

The owner chose to run one task and check the real cost before building the rest.

- Task 2 of the music player was run again on its own and approved. Roundtable counted
  $0.27; the DeepSeek balance went from 2.97 to 2.94 USD (it updates a little late).
  The count was about ten times too high: text the model had already seen was priced
  as new input.
- `harness/config.py` `cost`: a cache hit costs a tenth of the input price unless
  `cache_read` is set.
- `providers/balance.py` (new): reads a provider's balance (DeepSeek's `/user/balance`,
  or a provider's own `balance_url`). `Orchestrator.run` notes it at the start and the
  end (`_note_balance`, `.harness/balance.jsonl`, the `real_cost` event);
  `roundtable balance` prints it.
- Tests: `test_cache_hits_cost_a_tenth_unless_priced`,
  `test_real_balance_noted_at_start_and_end`; 126 pass.
- Open: the estimate's defaults should come from real runs (plans/gaps.md).

## 2026-11-26 – The docs follow the owner's layout; "use Roundtable, and grow it"

The owner asked: "If you find anything that you can't do, using the roundtable of course
add that system. Make sure that the documentation side of things is the same as how I do
everything on my GitHubs."

- New, in the same shape as MSE-Studio-Engine's: `CLAUDE.md` (full rules, the pieces,
  tests, releasing, sub-agents), `AGENTS.md` (the short version), `HANDOFF.md`, this
  devlog (filled in from the history below), `plans/owner-todo.md` and `plans/gaps.md`
  (what Roundtable couldn't do, with where each belongs). `ROADMAP.md` became `PLAN.md`,
  with the decisions and the six releases the owner chose.
- Decided: the owner's rule goes in CLAUDE.md – a job Roundtable can't do becomes part of
  Roundtable (with a test) or an entry in `plans/gaps.md`, never only a workaround.
- Decided: commits here now follow the owner's rule from their other repositories – no
  attribution lines and no model names. Model ids stay in configs, pricing and tests,
  where Roundtable needs them.
- Open: everything in `plans/gaps.md`.

## 2026-11-26 – The music player build: two fixes from the first real run

The owner answered plan v4 (Next and Back like a real player, the queue starts fresh,
crossfade and sortable columns in) and said to build it.

- `harness/plandoc.py` `carry_over`: settled decisions, answered questions and decided
  ideas stay in the document when the planner drops them; a new idea close to one the
  owner turned down (`_similar`, word overlap) is dropped; ids renumbered on a clash;
  `context_text` lists "The owner doesn't want: …"; an older critique says which version
  it was about. `orchestrator.plan_update("idea", accept=False)` now tells the planner.
  (`01219e3`)
- `orchestrator._run_task`: a task that runs out of steps with no fallback model carries
  on once, told its changes are still in the files (`2e1b1ba`). Task 2 (the core logic)
  had stopped at 40 steps.
- The run's costs were far above the estimate (about $0.25 for 14 tasks; over $0.50
  counted for two). The owner chose to run one task and check the real balance first.
- Tests: `test_settled_items_stay_and_turned_down_ideas_dont_come_back`,
  `test_out_of_steps_without_fallback_carries_on_once`; 124 pass.

## 2026-11-25 – Plan answers matched by wording

- `plandoc.carry_over` matched ideas by id, so the planner's new I1–I4 were shown as
  accepted. Now decisions (by question, then option label), answers (by question) and
  ideas (by text) are matched by wording.

## 2026-11-25 – Roundtable Mobile (Android), first usable version

The owner asked for "a roundtable for mobile harness" like deepseek-harness-mobile but
more advanced, then "also make the mobile application so I can see myself".

- `mobile/` (Kotlin, Compose): The Table (concept A), Needs you cards (B), notifications
  (C, `work/Watch.kt`), project and plan screens, Letters, Setup and Settings.
  `data/Hall.kt` has a Hub backend (GitHub contents and trees API, fine-grained token) and
  a PC backend (the phone server). 38 unit tests. The version comes from
  `pyproject.toml`; signing from the environment or the ignored `mobile/signing/`, else
  the debug key.
- A test APK and an overview picture went to the owner.
- Open: PC mode on a real PC; a release signing key; switching on `SHOW_PHONE`.

## 2026-11-25 – The living plan (0.6.0), plans in the hub, commands through the hub

The owner asked to follow Fable's advice and order: the living plan first.

- `harness/plandoc.py`: the plan document (summary, scope, don'ts, spec, decisions,
  questions, ideas, critique, estimate, pending, history), its markdown with item ids
  for the phone, `context_text` for workers and reviewers, the estimate from history.
- `orchestrator.py`: `plan()` with the document, the estimate and a critique by
  `critic_role` (one automatic revision on a high-severity point); `plan_update` edits
  wait as pending; `revise_plan` keeps done and running tasks and reports a diff;
  `approve` refuses while changes wait; `_publish_plan` writes `plans/<project>.md` to
  the hub.
- `remote.py`: the owner's `roundtable:` hub messages are done by the desktop app's
  auto-sync or `roundtable remote --watch`, replied to and marked read once.
- The desktop app's plan page (`#/plan/<path>`); the planner asks product questions
  first. Released as **0.6.0**.

## 2026-11-25 – Phone access

- `phone.py`: a separate TLS server with a self-signed certificate pinned by
  fingerprint; pairing by an 8-character code or a QR code (5 minutes, 5 tries);
  device tokens kept only as hashes; a whitelist of routes; `/api/changes` long-poll.
  Hidden in the app until the phone release.

## 2026-11-25 – `roundtable connect` and release 0.5.0

- `connect.py`: Claude Code sessions in other repositories join the hub – `.mcp.json`,
  SessionStart/Stop/SessionEnd hooks, `--cloud-script` for cloud environments. Connected:
  MSE-Studio-Engine, MCSuperMods, blockloom, cutline-studio.
- The Roundtable command centre (live seats, activity feed, chat, auto-sync) became the
  main screen. Released as **0.5.0**.

## 2026-11-25 – From the first commit to 0.4.0

- The hub (Phase 1), the multi-provider harness (Phase 2), the self-improvement loop
  (Phase 3), the project journal, model health probes, Retro Diffusion pixel art.
- The web UI, the built-in updater, the Windows desktop app with installer, setup wizard
  and auto-update; any AI provider (catalog, custom APIs, plugins); the candlelit round
  table theme (0.4.0); raising the budget from the app.
