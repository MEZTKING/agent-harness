# Roundtable Hold – devlog

Newest first. What was asked, what was done (files and functions, so the next session
finds them), what was decided and why, and what's still open. The plan is
[PLAN.md](PLAN.md); how to run things is in [README.md](README.md).

## 2026-11-26 – OpenRouter, and the Budget / Balanced / Quality settings

The owner plans games from bought Fab assets and asked: OpenRouter or Openference, and
"maybe both: one for budget and one for non-budget". They added an OpenRouter key (saved
through the credential form; a $100 limit on the key).

- `harness/config.py`: `profiles:` (named role overlays, checked against roles and
  providers) and `default_profile`; `HarnessConfig.for_profile`; `_listed_price` reads
  OpenRouter's published prices (`providers/prices.py`, kept a day) for models with no
  `pricing:` line.
- `orchestrator.py`: `profile()`, `set_profile()`, `profile_estimates()`; the plan document
  keeps `estimates` per setting and `profile`; `remote.py` action `profile`; the desktop
  plan page's setting buttons (`profilePicker` in `app.js`, `plan_post`).
- `plandoc._reprice`: past work is priced at today's model (same tokens, another price), so
  each setting's estimate differs; `history_by_role` keeps the model and the tokens.
- `providers/openai_compat.py`: OpenRouter's exact cost per call (`usage.include`,
  `_reported_cost`); `providers/balance.py`: OpenRouter's credits as a balance.
- The lab: Budget, Balanced (default) and Quality; the music player's remaining 8 tasks
  are estimated at about $1.21 on Budget or Balanced and about $33 on Quality (rough:
  Sonnet would likely need fewer steps).
- Tests: profiles, repricing, OpenRouter balance and cost; 147 pass.
- Open: the phone's setting picker; routing by how hard a task is (simple parts on
  DeepSeek even in Quality).

## 2026-11-26 – The recommended split: Openference plus DeepSeek

The owner's second Openference key reaches 51 models; they asked for the split: Claude
for planning and design, another maker for the critique and the reviews, DeepSeek direct
for the coding.

- The yardstick lab's `harness.yaml`: planner Claude Opus 5.5 (fallback DeepSeek V4 Pro),
  critic GPT-6.1 Terra (fallback GLM-5.3), designer Claude Sonnet 5.5 (fallback GLM-5.3),
  coder DeepSeek V4 Flash direct (fallback V4 Pro), reviewer GPT-6 Luna (fallbacks Claude
  Haiku 5.5, DeepSeek Flash). Terra and Luna answered through Roundtable; Claude is
  refused until the Openference balance is at least $1 (fallbacks take over meanwhile).
- `templates/harness.example.yaml`: the `openference` provider and the split as a
  commented block; README "The recommended split" with the `roundtable assign` commands
  for the owner's PC.
- `providers/openai_compat._said`: errors carry the service's own words; a 402 says
  "out of credit for <model> – top up your balance". `DEFAULT_PRICING`: GPT-6 Luna,
  GPT-6.1 Terra, GLM-5.2.
- Test: `test_service_error_message_is_kept`; 144 pass.
- Open: Openference has no balance endpoint, so its real cost isn't checked yet (its
  `X-Quota-*` headers are plan units).

## 2026-11-26 – Openference as a provider

The owner has an API key for Openference (openference.com): one OpenAI- and
Anthropic-compatible service in front of 55 models from 15 makers.

- The key is saved through the credential form for `api.openference.com` (the proxy adds
  it; nothing in files). A real call through `roundtable ask` worked.
- `providers/catalog.py`: the `openference` preset (`https://api.openference.com/v1`,
  `OPENFERENCE_API_KEY`). `harness/config.py` `DEFAULT_PRICING`: Openference's prices for
  the models we're likely to use (its model ids, as `GET /v1/models` gives them).
- The owner's key is limited to one model (`DeepSeek-V4.1-Flash-1017`); asking for
  Claude Haiku 5.5 was refused (`model_not_allowed_for_key`). Widening it is the owner's
  choice, in Openference's dashboard (plans/owner-todo.md).
- Openference has no balance endpoint; its replies carry `X-Quota-Cost` and
  `X-Quota-Remaining` (plan units). Open: read those for the real-cost check.

## 2026-11-26 – A look of its own: the Look stage

The owner: "I want the UI to be unique for whatever application I make, so how can I
integrate that." They chose a Look step in Roundtable, tried next on the music player.

- `harness/look.py` (new): the `submit_looks` schema and its strict checks
  (`validate_looks`: hex colours, every part present, two to four word names, a CSS length
  for corners, no external scripts in the mockup, different names, display fonts and accent
  colours, and readable contrast by `contrast` – text 4.5:1 on background and surface, text
  on the accent 4.5:1, muted text 3:1); `render_mockups` (desktop 1280x800 and phone
  390x844 pictures with Playwright for Python or Node, only Google Fonts let through,
  skipped with a note when neither is installed); `design_markdown` and `tokens_css` (the
  design file and CSS custom properties for light and dark); `check_tokens` /
  `findings_text` (hard-coded colours and fonts in .css/.html/.js/.ts/.kt files outside
  `design/tokens.css`, ignoring node_modules, .git, .harness and test files); `ui_files`.
- `harness/lookstage.py` (new): the `LookStage` mixin of the Orchestrator – `look(brief,
  count)` (one designer call, mockups saved to `.harness/look/<id>.html`, pictures next to
  them, `doc["look"]`), `_used_looks` (the looks chosen in the lab's other projects go in the
  prompt, not to be reused unless the brief asks), `_choose_look` (plan action `look`),
  `apply_look` (writes and commits `design/DESIGN.md` and `design/tokens.css`, adds task
  "Restyle the app in the chosen look" for the coder when screens are already built),
  `_adjust_look`, `_design_context`, `_design_findings`, `_look_pictures`.
- `harness/orchestrator.py`: `Orchestrator(LookStage)`; `plan()` runs `_look_stage()` after
  the critique; `revise_plan` calls `apply_look` when the chosen look changed;
  `PLAN_ACTIONS` gains `look`; `_project_context` (so every task) and `_review` include the
  design file, the review also the check's findings; `_publish_plan` copies the pictures to
  the hub as `plans/looks/<project>/<id>.png` (and `-phone.png`); the design role never gets
  tasks (`_not_for_tasks`).
- `harness/plandoc.py`: `has_ui` in the plan submission and document; `carry_over` keeps
  the looks and `has_ui`; `look_open`; an unchosen look counts as a choice in `open_items`
  and shows as "a look to choose" in `summary_line` (Needs you); `render_markdown` has a
  Look section (`{A}` ids, "(chosen)", picture links, `image_base`); `context_text` names
  the chosen look.
- `harness/config.py`: `design_role` (default: a chat role named `designer`, else the
  planner) and `look_stage` (`auto` or `off`; YAML's bare `off` is read as off).
- `core/store.py`: `BinaryFile`, so the hub store can write pictures.
- `remote.py`: actions `look` (choose, through the plan edits) and `looks` (new looks, long).
- `ui/server.py`: plan action `looks` as a background job, `GET /api/plan/looks` (the
  pictures as data addresses, which the page's rules allow), log lines for the look events.
  `ui/static/app.js` `lookSection` in the plan page (pictures side by side, Choose this look
  with an optional note, Make new looks with a starting point); `style.css`.
- `prompts/designer.md` (new); `prompts/orchestrator.md`: `has_ui`.
- `templates/harness.example.yaml`: a chat `designer` role (Opus-class with a DeepSeek
  fallback, 32,000 tokens for three mockups), `design_role`, `look_stage`; the pixel-art
  image role is now called `artist` (README updated to match).
- README: "A look of its own" under The living plan.
- Tests: `tests/test_look.py` (15, one renders a real picture when Playwright is there);
  141 pass. A hand-written direction rendered to a picture on desktop and phone sizes.
- Decided: a note with the choice ("the second, but warmer") gets one designer call that
  changes that direction before it's applied, and the note is also written in the design
  file; if that call fails the chosen direction is applied as it was. Approve isn't blocked
  by an unchosen look. The check flags every hard-coded colour or font in the project, not
  only the task's lines; the reviewer is told to reject when they're part of the task.
- Open: the phone side of the Look section (`mobile/`); the screenshot check of finished
  screens against the look (release 2's Proof); trying it on the music player.
## 2026-11-26 – A real-money limit per run

The owner chose to carry on with Flash first and V4 Pro taking over, and to stop at $1.

- `limits.max_real_usd_per_run` (new, default off) and `Orchestrator._real_spend_over_limit`:
  between tasks the run reads the providers' real balances and pauses (status paused,
  a "money" Needs you note) once they fell by the limit since the run started.
- Test: `test_run_pauses_when_real_spend_reaches_its_limit`; 128 pass.
- The yardstick's config: the coder role falls back to DeepSeek V4 Pro; the run's real
  limit is $1.

## 2026-11-26 – The music player's run stopped; tasks too big are now split

The owner said to build the rest of the music player.

- Tasks 3–6 were done and approved; tasks 9 (remember the library) and 10 (cover art and
  the visualiser) ran out of 60 steps on both attempts, so the run stopped as blocked.
- Real cost of that run: the DeepSeek balance went from 2.93 to 2.47 USD ($0.46, of which
  about $0.32 went on the four failed attempts); Roundtable counted $0.74. The earlier
  "about 3 cents a task" was read from a balance that hadn't caught up yet.
- `orchestrator._split_if_too_big` (new): when every attempt at a task ran out of steps,
  the planner replaces it with 2–4 smaller tasks (`revise_plan(by="harness")`), once per
  task (`.harness/split.json`); `limits.split_stuck_tasks` (default on).
- Test: `test_task_that_keeps_running_out_of_steps_is_split_once`; 127 pass.
- Open: the planner should size tasks up front; ask the owner before carrying on.

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
