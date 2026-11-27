# Darkness Harness – devlog

(Roundtable Hold before 1.0.0; entries below 1.0.0 keep the old name.)

Newest first. What was asked, what was done (files and functions, so the next session
finds them), what was decided and why, and what's still open. The plan is
[PLAN.md](PLAN.md); how to run things is in [README.md](README.md).

## 2026-11-27 – 1.2.0: wave 6 put together ("every model at once")

Asked: merge the seven wave 6 branches in order (d3-limits, d3-router, d3-panel with both its commits, d3-rivals,
d3-council, d3-agents, d3-dial), do every hook-up line from the helpers' reports and the coordinator's decisions,
re-run the dial's 10 % test on the real stages, one scripted end-to-end check, the screens, version 1.2.0 with its
notes, gaps and parity. No release; the six starter faces are not made here (they cost money).

What each part is, plainly:
- **Limits** (d3-limits, c41ffea): a ledger of every charge (`<app home>/usage/<month>.jsonl`, numbers and names
  only), limits per service (day/month dollars, day tokens) and per job on one project, "what's used" per service,
  who has seen a project (`harness/usage.py` `UsageStage`, `ui/usageapi.py`, `static/usage.js`).
- **The router** (d3-router, 82879a1): tasks tagged by kind of work, each sent to the model that wins that kind
  (5 judged tries and a 0.15 lead), a capped share of easy tasks tried on newer models under Balanced; the lab's
  numbers per tag (`harness/tasktags.py`, `router.py`, `improve/analysis.py`, `ui/strengthsapi.py`,
  `static/strengths.js`).
- **The panel** (d3-panel, a6f8d5e, 119d4ae): checkers from another maker, two on hard or risky tasks and a third
  on a split; a rejection counts only when it quotes the line it breaks (`harness/panel.py`).
- **Rivals** (d3-rivals, 55e98bc): two or three makers build a hard task in their own copies; tests then one pick
  call choose; the others kept as branches and patches (`harness/rivals.py`).
- **The council** (d3-council, e7f5db7): rival planners and a chair under Maximum, "Where the planners disagreed"
  (`harness/council.py`, `ui/councilapi.py`, `static/council.js`, `Council.kt`, `CouncilFold.kt`).
- **Agents** (d3-agents, 75f5dce): named agents per job with notes, memory and a face; `.rtagent` files; a `size`
  option for picture models (`agents.py`, `harness/agentstage.py`, `ui/agentsapi.py`, `static/agents.js`,
  `providers/chat_images.image_config`).
- **The dial** (d3-dial, 4128f58): Lean, Balanced, Maximum with three prices on the plan, the extra checking's own
  allowance, who built and who checked each task (`harness/dial.py`, `ui/tandemapi.py`, `static/tandem.js`,
  `Tandem.kt`, `TandemLine.kt`).

Merges (fc0d086 … a903746): no textual conflicts. The helpers' ready-made hook-up diffs (limits, council) applied
cleanly.

Hook-ups (37560fd, 8b41453, and this commit):
- `orchestrator.py`: `Orchestrator(UsageStage, RouterStage, PanelStage, RivalsStage, CouncilStage, AgentStage,
  DialStage, MoneyStage, …)`. The whole MRO checked: no new clash (only wave 5's `_look_wanted` and
  `_shots_wanted`), and no stage method shadowed by the Orchestrator's own. `_usage_out` and the `pause` of an
  `OutOfCredit` in `_attempt_loop` and `_run`; `_blocked` at the top of the image loop; `DOC_PARTS` gains
  `_tags_doc`; `_tags_trim(new)` right after the plan call; `meta["checking"]` written before the
  `_council_plan` hook (so the council reads the new plan's level); `PLAN_ACTIONS` gains `checking`
  (`dial.set_checking`, no revise needed); `_dial_agreed` after `_money_agreed` in `approve()`.
- `agent.Budget.charge`: `on_charge` in `try`, `on_use` in `finally` (the ledger keeps the line that stopped a run).
- **The dial no longer counts the panel's extra checkers twice**: `panel._result` puts the cost of every checker
  after the first in `captured["panel_extra_usd"]`; `_attempt_loop` passes it to `_metric`, which leaves it out of
  the row's `cost_usd` and writes it as `panel_extra_usd` (only when there is one, so lean rows are unchanged).
- `showstage._learn_from_task`: `_agent_learn`. `projectsettings`: `checking`, `agent_memory`.
- `asks._approve_ask`: "Checking: Balanced (about $0.40 of this)" in Approve's description (not for a lean plan,
  so older projects read as before). `plandoc.render_markdown`: `council.markdown`. `routing.view`: `warnings`
  (`panel.same_maker_warnings`).
- `retention.py`: `not_chosen(root)`, `not_chosen_words`, `clear_not_chosen(root, task, rival)` – the attempts
  not chosen with their size; only the owner's Clear removes them, the daily sweep never does
  (`tests/test_not_chosen.py`). `ui/tidyapi.py`: `GET /api/tidy/not-chosen`, `POST /api/tidy/not-chosen/clear`
  (only projects the app knows). `static/tidy.js`: the list behind More, a Clear per project with a confirm.
- `harness_cli.py`: `roundtable improve stats [--by-tag] [--project DIR]`.
- `ui/server.py` `FEATURE_APIS`: councilapi, usageapi, strengthsapi, agentsapi, tandemapi. `phone.py`
  `PHONE_ROUTES`: `/api/tandem`, `/api/tandem/council`, `/api/usage`, `/api/agents` (all read only; limits,
  faces, export and import stay on the PC). `tandemapi` names the agent by its name, not its id.
- Conformance: `calls.json` gains tandem and council (the phone has no usage or agents screen yet, so those
  aren't calls it makes); fixtures written again (`ROUNDTABLE_WRITE_FIXTURES=1`, timestamps only elsewhere);
  `ConformanceTest.kt` reads both.
- Desktop: `settings.js` – the usage card first under Spending; `models.js` – Strengths and Agents tabs, job
  limits under the jobs table, the same-maker warning above it; `plan.js` – one fold "Models: … · Checking: …"
  with the sets and `checkingChoice` (hidden while busy or finished), `councilFold`, the who-built-it line under
  each task (`taskLines(tasks, who)`); `project.js` – the same line in the task list, a "Who may see it" group
  (services, makers, agent memory and `seenList`), `checking` beside the set of models; `style.css` – `.tl-who`.
- Phone `ProjectScreen.kt`: `CouncilFold` after the done card; `CheckingChoice` (three buttons with prices,
  Maximum asks first with both figures and the planners' cost; sent as the plan's `checking` command, which
  `remote.py` already passes to `plan_update`); `TaskLines` with `TandemLine` under each built task.
- `pyproject.toml`: Pillow is a run-time dependency; package data `ui/static/agents/*`. The PyInstaller spec lists
  `PIL.Image` and its WebP, PNG and JPEG plug-ins.

Tests changed at hook-up, and why:
- The helpers' tests subclassed `(XStage, Orchestrator)`, which can't make an MRO once the stage is a base:
  `class O(*((Orchestrator,) if issubclass(Orchestrator, XStage) else (XStage, Orchestrator)))` (router,
  rivals, council, agents, dial).
- `test_tandem_seam`: "nobody defines them yet" became "only the stages define them". `test_stage_hooks.STAGES`
  has all seven.
- `test_router`: the trim is now checked through `plan()` (the warning in the saved document); "exploring needs
  the dial" runs at lean (Balanced explores now).
- `test_rivals`: the scripted rejection quotes the task's line (the real panel would re-ask an unquoted one);
  "lean is the usual way" sets lean (new plans are Balanced).
- `test_dial`: its `Approving` mixin is empty (approve calls the hook itself). The 10 % test now runs on the full
  Orchestrator with every real stage (`RealStages`); the stand-in version is gone.

**The 10 % test with the real stages** (made-up 4-task plan: ordinary, hard, risky, ordinary). First run: Lean 0 %,
Balanced −7.9 %, Maximum −15.3 %. The rivals' pick call reads every rival's diff and summary but was priced as one
review. Now priced as one review per rival (`dial._task_price`, `pick_reviews`): **Lean 0.0 %, Balanced −2.6 %,
Maximum −4.4 %** (estimate under the spend). The unsticking allowance ($0.15, money kept for a stuck task, never
spent in a clean run) is left out of the comparison and shown beside it.

**End to end** (`tests/test_tandem_e2e.py`): a made-up board game, one hard task (game logic) under Balanced. It
was tagged; routed to b's coder ("wins … game logic", from a's); built by two rivals from two makers, one kept
as a branch; checked by two makers neither of them the builder's; estimate $0.207 against $0.216 spent (−4 %);
the extras spent $0.072 of their $0.25 allowance.

Screens (Playwright, Eclipse and Ash; scratchpad `v12-shots/`): the plan with the checking fold and its three
buttons, Maximum's confirm, each task's "Built by Coder2 (Torvic) · best of 2 · checked by Reviewer and
Reviewer3" with More, Models → Strengths ("Best at game logic: 9 of 9") and Agents (initials until the faces are
made), Settings → Spending with "What's used", a project's "Only A has seen this project". No console errors.

Decided (coordinator): no picture size sent when none is asked for (existing pictures cost the same); Pillow at
run time; lean does nothing (not even the quote rule); `meta["checking"]` above the council hook; the panel's
extra checkers kept out of the metrics row's cost.

Still open: the six starter faces (the coordinator, after the owner's yes: `agents.face_prompt` for each, costs in
`docs/art.md`); a real run on DeepSeek plus one other maker at Balanced to measure the real extra cost and how
often a checker is asked again; the Agents screen on the phone; the phone's usage card; HANDOFF step 4 (the
old-name starter) is still to do before 1.2.0 is released.

## 2026-11-27 – 1.1.0: wave 5 put together ("finished, not just built")

Asked: merge the seven wave 5 branches in order (d2-money, d2-done, d2-stages, d2-unstick, d2-finish, d2-play,
d2-ship), do every hook-up line from the helpers' reports, keep 1.0's look and wording, test everything, look at
the screens, one scripted end-to-end check, version 1.1.0 with its notes, gaps and parity. No release.

What each part is, plainly:
- **Money** (d2-money, 66f7d44): approval records what the owner agreed to (`meta["agreed"]`); a run that would
  cost a quarter more (at least $0.50 of room) pauses with one card (Carry on / Finish with what's there / Stop);
  autopilot writes its remaining money as the run's allowance (`AllowanceReached`); picture models are priced from
  real charges or `pricing.<model>.per_image` (`harness/moneystage.py`, `harness/imageprice.py`, `autopilot.allow`).
- **The done list and prep** (d2-done, 0c1ce0d): what a person can do with the finished thing, planned with the
  plan, the kind's checks merged in, `.harness/done.json`; the done gate blocks on a failed must with one
  "Not finished" card (Try fixing again / Accept as it is / Stop); the idea tidied into a brief under More
  (`harness/donelist.py`, `donestage.py`, `prep.py`, `ui/doneapi.py`, `static/donelist.js`, `DoneCard.kt`).
- **Stages and parts** (d2-stages, 2619445): a working slice first, stages run in order with a note (and a light
  re-plan when there are lessons) at each boundary, `files` per task with overlap warnings, several parts in their
  own folders, `stage_stop: each` (`harness/stages.py`, `ui/stagesapi.py`, `static/stages.js`, `StageStrip.kt`).
- **Unsticking and handovers** (d2-unstick, f772634): a failed task diagnosed once by another maker's model
  (retry with advice, split, plan around, park), one "stuck" card at the end, written handovers, "spent with
  nothing finished" in the report (`harness/unstick.py`, `harness/handoff.py`).
- **Finishing** (d2-finish, e522dba): after the last task the product is started, the done list walked in a
  browser, commands and files checked, failures turned into fix tasks within 2 rounds, $0.50 and 6 tasks;
  apps that start with a command are started and stopped; the App tab's Start (`harness/finishstage.py`,
  `journeys.py`, `appserver.py`, `ui/appapi.py`, `static/appstart.js`, `showit.take_shots(ws=…)`).
- **Play-testing** (d2-play, 23b3795): a model that can see plays a browser or Godot game for a minute; broken
  findings fail the item, rough ones become ideas; the `godot-game` kind (trial) (`harness/playtest.py`,
  `godot.record_play`, `kinds/builtin/godot-game/`).
- **Shipping** (d2-ship, cd66457): the planner is told what this machine can build; at the end the EXE, APK or
  mod is built, its file checked (`PK`/`MZ`), started once; one fix task per target; recipes from imported kinds
  always ask first; `android-app` kind, `java-mod` to trial (`harness/ship.py`, `shipstage.py`, `kinds/model.py`).

Merges (9fda49e … edbac73): no textual conflicts. Clashes with 1.0 found by the tests: `--color-oak-line` in
`appstart.js`, `donelist.js`, `stages.js` → `--color-line` (b7b5908). ProjectScreen.kt, watch.js and
test_brand_words.py weren't touched by the helpers.

Hook-ups (91128eb, acb8fe6):
- `orchestrator.py`: `Orchestrator(MoneyStage, KindStage, ParallelStage, RepoStage, LookStage, ReferenceStage,
  ShowStage, DoneStage, StagesStage, UnstickStage, FinishStage, PlayStage, ShipStage)` – no method clashes
  (checked over the whole MRO); `AllowanceReached` branch in `_run`; `_stage_after_task` after a passed task
  (and in `worktrees._merge_task`); `_stage_stop` before the final "blocked" in `_run` and `_parallel_end`;
  `_handoff_split` in `_split_if_too_big`; `wasted_words` and `_done_report_note` in `_finish`; `done_add` /
  `done_remove` in `plan_update`; `estimate_line(est, meta["agreed"])` (also in `ui/server.py`).
- `asks.py`: the over-estimate/allowance money card and its answers; the `not_finished` card; one `stuck` card
  in place of per-task cards; `APPLY["not_finished"]`, `APPLY["stuck"]` (lazy imports, `_lazy`).
  `donestage.apply_not_finished` also calls `finishstage.clear_rounds`.
- `autopilot.decide`: `not_finished` → `decide_not_finished` (fix at most once, never accept); `stuck` → left.
- `plandoc`: "Done when" in the markdown, `donelist.context` in `context_text`, `stages.markdown` for the tasks.
- `kindstage`: proof lines take the done list's pass or fail per line over the proof stage's answer
  (`_kind_proof_base`); `_kind_outputs` gains jar and the two APK paths. `proof.HOWS["play"]` with
  `_play_passed` (done list by `kind_id`, else the newest `play.json`), so browser-game can be proven; its
  `card.md` no longer says "not checked yet".
- `projectsettings`: `stage_stop` (off, each). `retention.Sweep.goal_dirs` for `.harness/play/` and
  `.harness/journeys/` (newest `shots_keep` per goal).
- `ui/server.py`: `doneapi`, `stagesapi`, `appapi` in `FEATURE_APIS`; `frame-src` gains `appapi.FRAME_SRC`;
  `stop_apps()` at exit (also `desktop._stop_apps` after the window closes). `phone.py`: `/api/done`,
  `/api/done/evidence`, `/api/stages`. `tests/conformance/calls.json` + three new fixtures, all written again;
  `ConformanceTest.kt` makes the three calls.
- Desktop: `plan.js` (done card after the plan's top, `stagedTaskList` for the tasks), `project.js` overview
  (`doneLine`, `stagesStrip`), `watch.js` `appTab` (`appStartCard` above; the "for now" note gone).
- Phone: `ProjectScreen.kt` `calmPlan`: `DoneCard(machine, path)` after the kind, `StageStrip` above the tasks
  (only with a PC or this phone; nothing in Hub mode).

Fixed while putting it together (each with a test in `tests/test_wave5.py` or the helper's file):
- `_money_agreed` with no plan agreed $0, so any run past 50 cents paused: now it agrees nothing.
- The finishing step planned (paid) fixes for a failed nice-to-have: only `must` items get fixes now.
- An extra's "The EXE was built" was checked by the finishing step before the ship step built anything, and
  trapped the project: such `file_exists` items are left to the ship step, which records onto them too.
- Coordinator decision: a target this machine can't build is `must=False` (shown as not checked, the reason
  given), for the ship item and the extra's own file check; it follows `can_build` if the machine changes.
- `npm …` checks in a folder with no package.json read "nothing to run yet" (unchecked), not failed.
- "an Android app" alone no longer picks the native `android-app` kind (a wrapped site is a website with the APK
  extra); "native android", "kotlin", "jetpack compose" still do.
- A stage task's part went after the role (`(coder) · Game`), breaking the task-line parsers on the desktop and
  phone: now `title · Game (coder)`.
- `donelist.markdown`/`context` skip items that aren't items. The done card's pictures are thumbnails.
- Tests: `tests/conftest.py` gives every run a made-up computer with no build tools and no browser, so a machine
  with Java, the Android SDK or Playwright doesn't change results (shipping and play tests bring their own).
  `test_stage_hooks.py` tests the seam on `Seam` (the Orchestrator without the wave 5 mixins) and checks the full
  Orchestrator with no done list, stages or kind runs as before (only the unstick allowance in the estimate).
  The helpers' `class O(XStage, Orchestrator)` became `class O(Orchestrator)`; d2-ship's, d2-stages', d2-finish's
  and d2-done's tests updated for the real gate (a failed build now ends "blocked" with the card).

Checked: 1272 Python tests pass (none skipped); the phone's `testDebugUnitTest assembleDebug` passes, with the
conformance run; `node --check` on all 35 static modules; Playwright screenshots of the plan page with a done
list and stages, the overview's strip, and the App tab starting and stopping an app (Eclipse and Ash), no
console errors. End to end (`test_a_made_up_game_with_a_planted_bug_is_planned_built_found_fixed_and_done`):
plan with a done list, two stages and the estimate's extra lines → approve → T1, T2 in stage order → the
finishing step finds Start does nothing → F1 → passes → done, nobody asked.

Still open (beta until the owner's PC): a real Godot play, real EXE/APK/mod builds and starts, real browser
journeys and the App tab's frame on Windows; the phone's DoneCard and StageStrip on a real phone. The small real
DeepSeek run of the finishing loop wasn't done here. Not released.

## 2026-11-27 – 1.0.0: wave 4 put together, Roundtable Hold becomes Darkness Harness

Asked: merge wave 4's last two branches (d1-skin, then d1-phone; d1-passage, d1-words, d1-art and wave 5's step 0
were already on the session branch), do every hook-up line the helpers left, add the art gaps, version 1.0.0 with
its notes, rewrite the handoff and the headings, test everything and look at the screens. No release yet.

What each part is, plainly:
- **The passage** (d1-passage, 1544be4): nothing installed is lost. `desktop.pick_home`/`app_home`: the new
  `DarknessHarness` folder only if it holds something, else the old `RoundtableHold`; `default_projects_dir` keeps
  an existing `Roundtable Projects`. `KeyStore` writes under "Darkness Harness" and reads the old service too.
  `updater.pick_installer` takes either installer name. The installer keeps its AppId, removes the old exe and
  shortcuts, moves the firewall rules (asks once on a silent update, only where the old rules exist), and ships
  `packaging/old_name_starter.py` as a tiny `RoundtableHold.exe` so a hand-made taskbar pin still opens the app.
  `app.yml`: both APK names, the `upgrade-test` job (already passed once on Windows CI), and a `release` job that
  needs it. Phone: `Releases.kt` takes either APK name. Guard test `tests/test_passage.py`.
- **The words** (d1-words, ac92ada): `brand.py`, `BRAND` in `static/core.js`, the new name or "the harness" in
  every string the app serves; `brand.SWITCHED` with `is_switched` reading both journal forms;
  `tests/test_brand_words.py` fails on the old name outside an allow-list of names machines read.
- **The art** (d1-art, c655c5d): Eclipse backdrop, ring, wordmark, emblem, favicon, `packaging/darkness.ico`,
  the phone's launcher icon and `eclipse_phone.webp`, all by image models ($0.89, `docs/art.md`).
- **The desktop look** (d1-skin, c5126c1): one token block in `style.css` with Eclipse, Pitch and Ash; Home's Ring
  in `hall.js`; Space Grotesk, Inter, JetBrains Mono; `tests/test_contrast.py`.
- **Wave 5's step 0** (9115566–327a010, behaviour-neutral): the stages' seam in the orchestrator (hooks, `add_tasks`,
  end steps in both run paths) and the done list's file (`.harness/done.json`); wave 5 builds on it.
- **The phone** (d1-phone, e123532): `Theme.kt` with the three looks, the Ring on the Table, the Look setting in
  `Comfort.kt`, the new fonts, the label "Darkness"; applicationId unchanged and tested.

Done here (the hook-ups):
- Merges of d1-skin and d1-phone had no conflicts; every d1-art file is byte-for-byte d1-art's.
- Phone wording left over: `data/Plain.kt` (letters: "The harness replied", "Darkness: Done. …"), `Hall.kt`,
  `Sync.kt`, `Search.kt`, `SessionLog.kt`, `Crash.kt`, `net/Api.kt` (line 84 and the two pairing errors),
  `GitHubHub.kt` commit messages ("(Darkness phone app)"), `update/UpdateWorker.kt`, and the on-phone harness's
  messages in `runtime/` (`RuntimeController`, `HarnessRuntimeService`, `RuntimeFailure`, `ProotCommand`). The
  "not running" message starts with the name, so `Api.kt`'s pass-through check still lets it through.
  `RuntimeManifest.DEFAULT_READINESS` keeps the old words (the on-phone Python prints them). Tests updated; the
  conformance fixtures written again from the desktop.
- `THIRD_PARTY_NOTICES.md`: Space Grotesk, Inter and JetBrains Mono (desktop woff2, phone ttf); Fraunces and
  Nunito Sans marked as no longer shipped.
- `packaging/roundtable.spec` and `installer.iss` use `packaging/darkness.ico`; the old `roundtable.ico`/`.png`
  removed.
- `watch.js`'s bar colours and every old token name in `kinds.js`, `rewind.js`, `search.js`, `compose.js`,
  `gallery.js`, `notify.js`, `proof.js`, `tools.js` moved to the new tokens; the aliases dropped from `style.css`.
  `test_contrast.py` now checks every `static/*.js` for written colours and old token names.
- Home's Ring and `ring.webp`: measured the painted ring (rim at 46% of the picture, centre 0.7% right and 1.6% up);
  `.ring-disc` now draws the art at 109% at `58.8% 30.5%`, so the lights sit on the rim (it was 118%, centred,
  which left them inside the glow). The wordmark is narrower (200px) so it clears the eclipse's edge. With no
  projects the backdrop's own eclipse is turned off (two eclipses showed). Ash draws its chrome ring and types
  the name (the art is pale, made for dark). The backdrop-brightness test runs now and passes.
- Phone Table: `eclipse_phone` drawn at 60% (was 85%) so the drawn rim leads; the outer thin circle is the
  intended orbit, not the art.
- README intro (Eclipse instead of Candlelit Oak, the data folder for new and old installs), "What's new in
  1.0.0", `whatsnew.md` written again; version 1.0.0 in `pyproject.toml` and `__init__.py` (the phone's
  versionCode follows).
- `plans/gaps.md`: four picture gaps from the art job (editing, see-through, safe parallel spending, size).
- CLAUDE.md, AGENTS.md, PLAN.md, HANDOFF.md under the new name; PLAN.md has the waves 4–9 table.

Decided (reversible): names machines read keep the old name (package, command, repository, AppId,
applicationId, pairing link, `remote.PREFIX`, `ROUNDTABLE_*`, `rt-theme`); `~/.roundtable` is not renamed
(core/config.py, harness/config.py and onphone.py all read it); the old-name starter stays until 1.2.0.

Still open: the release itself (merge to main, `app.yml` with `release_tag: v1.0.0`); after 1.0.0 the
`upgrade-test` job still looks for the last `RoundtableHold-Setup-*` release (right for the 1.x line, change at
1.2.0 with the starter); on the owner's PC: the in-app update from 0.12.0, the one-time firewall question, the
pinned taskbar icon; on the phone: the 1.0.0 test APK over 0.12.0, still paired.

## 2026-11-27 – 0.12.0: wave 3 put together

Asked: merge the seven wave 3 branches (w3-phone, w3-desk, w3-proof, w3-rewind, w3-web, w3-kinds, w3-link, in that
order), do every hook-up line, firewall rules in the installer, the conformance run over every new phone call, test
everything, version 0.12.0. No release.

What each part is, plainly:
- **Phone comfort** (w3-phone, beta until tried on the phone): accent, true black, text size, buzz, how much Watch
  shows, pinned and put-away projects, what you sent (copy, edit and send again), a battery checklist, a rail or two
  panes on a big screen (`data/Comfort.kt`, `ui/ComfortScreen.kt`, `ui/SentHistory.kt`, `ui/adaptive/`). Later on
  the branch (266c4b5): the Table's title stays on one line, New idea and My notes get their own row, the empty
  "0 need you" banner is gone (screenshot test `tableHeaderAllButtonsBig`).
- **Command line, live output, pounds** (w3-desk): a project's Command line tab, this PC only and refused when the
  app is open to the network (`terminal.py`, `ui/terminalapi.py`, `static/terminal.js`); a task's command written
  to `.harness/live/` as it prints, with a Stop for that one command (`harness/livecmd.py`, `tools.run_command`);
  "≈ £" beside dollars from the European Central Bank's daily file (`money.py`, `ui/moneyapi.py`,
  `static/pounds.js`, `data/Pounds.kt`).
- **Proof** (w3-proof): pictures before (reused by commit) and after each task, the tests before and after, and one
  look by a model that can see, as advice for the reviewer, capped at $0.05 a task (`harness/proof.py`,
  `ProofStage` in `showstage.py`, `ui/proofapi.py`, `static/proof.js`, `ui/ProofCard.kt`).
- **Rewind** (w3-rewind): Undo this task or go back to before it, files shown first, a safety ref before anything
  moves, Put it back, Try another way (a separate copy); never for pushed work (`harness/rewind.py`,
  `ui/rewindapi.py`, `static/rewind.js`, `ui/RewindSheet.kt`).
- **Web search** (w3-web): `web_search` and `web_read` for the builders, the reviewer and the planner, four engines,
  6 searches and 10 pages a task, key-shaped text removed, off for projects kept to some providers unless their
  setting says on (`harness/websearch.py`, `ui/websearchapi.py`, `static/websearch.js`).
- **Kinds and the Gallery** (w3-kinds): kinds as folders of data (website, web app, browser game, something else;
  APK and EXE extras; the mod card "Not yet"), proposed from the idea for free, confirmed on the plan's first card,
  frozen at approval; a Gallery record per finished goal (`kinds/`, `harness/kindstage.py`, `ui/kindsapi.py`,
  `static/kinds.js`, `static/gallery.js`, the phone's Gallery and kind card).
- **Finding the PC and conformance** (w3-link): the PC answers the phone's "who's there?" on UDP 8767 (private
  senders only, never the code); pairing codes end in two letters bound to the certificate (`discovery.py`,
  `net/Discovery.kt`, `ui/FindPcCard.kt`); every phone call run against a real phone server
  (`tests/conformance/`, `ConformanceTest.kt`); `docs/phone-security.md`.

Merges: no conflicts. One clash the compiler found: kinds and proof both declared `ProofLine` (same fields) in the
phone's `data` package; the kinds copy went.

Hook-ups done:
- `server.py` `FEATURE_APIS`: rewindapi, proofapi, terminalapi, moneyapi, websearchapi, kindsapi; `serve()` sets
  `app.local_only`. `phone.py` `PHONE_ROUTES`: rewind (5), proof (2), a task's live command and its Stop, rates,
  kinds (4) and the Gallery (5) – never the command line itself; `PhoneAccess.start/stop` run the discovery
  responder (`discovery_port`, 0 in the tests through `conftest.py`); `start_pairing` uses `bound_code`.
- `orchestrator.py`: `Task.previous_attempts`; `KindStage` first among the bases; the kind laid over the config in
  `__init__`, `set_profile` and `profile_estimates`; `_kind_propose` in `start()`; the kind's part added inside
  `_plan_call` (so plan and revise both get it) and in `_worker_prompt`; `doc["kind"]` on the first plan;
  `_kind_freeze` in `approve()`; `_proof_before` before each task (`_run` and `worktrees._lane`); `_proof_text(task,
  checks)` in the review prompt; `websearch.add_tools` for workers, the reviewer and the planner; `ws.live` set in
  `_run_task`; `livecmd.stop_strays` at the end of `run()` and in `stop_all`; the Gallery record written in `run()`
  after the end-of-run balance check, with that check's real cost (`_gallery_record(tasks, real_usd)`), so no extra
  balance request is made.
- `plandoc.estimate(..., screens=)` adds `proof.estimate_usd` for reviewed tasks when the app has screens
  (`proof_usd` in the estimate); `carry_over` keeps `doc["kind"]`. `repostage._task_checks` returns `now` (the
  proof's tests line). `proof.results_for` (new, small): a kind's proof list checked against a goal's proof records.
- `session.tool_step` and `activity.js` `TOOL_WORDS`: "Searched the web for …", "Read a page: …". `desktop.py`
  `KNOWN_KEYS`: Brave Search, Tavily. Project setting `web_search` ("", on, off).
- `asks.py`: the wizard's "What do you want to make?" lists the kinds (the ones not ready greyed under "Coming"),
  `wizard_project` returns `kind`, `extras`, `kind_by`, `apply_wizard_kind` after `start` (server and the message
  box); a `kind` card first on the plan, answered with `set_kind` (a change waits as a plan change, then Update the
  plan); autopilot keeps the recommended kind.
- `retention.py`: `.harness/live/*.log` older than `logs_days`; ways back older than `rewind_days` (30).
- Desktop: the Gallery room and header link; the kind card first on the plan; History card on Overview; Undo this
  task, proof and a running task's live output in Watch (kept per task so redraws don't restart them); proof under
  the App tab's pictures; the Command line tab; pounds in the header, Money, the estimate and Settings → Spending;
  web search on Tools; Make another like this / Start one fill the wizard (`rt-wizard-prefill`).
- Phone: Gallery from the Table and its route; Undo… on a finished task (`RewindSheet`); the kind card (read only
  while the kind question waits as a card) and pounds beside the estimate; proof on the Live tab; Look for my PC in
  pairing, with the code checked against the certificate before it is sent (`PairingOffer.found`); Look for it on
  an unreachable PC (`ConnectionsViewModel.findPc`); `CHANGE_WIFI_MULTICAST_STATE` and `ACCESS_WIFI_STATE`.
- `app.yml` runs the phone's unit tests. Installer: two firewall rules (TCP 8766, UDP 8767, private networks,
  RoundtableHold.exe only), removed on uninstall.

Decided:
- The installer runs without administrator rights, and only an administrator can add a firewall rule. So a normal
  install asks once (one Windows yes) when the rules aren't there yet; silent updates and CI never ask, and then
  Windows asks as before when the phone first connects. Making the installer admin-only would put a prompt on every
  update instead.
- No kind card when Roundtable's only guess is "Something else": nothing useful to ask. The plan page still shows it.
- Hinge detection on foldables needs `androidx.window`, which isn't in the offline Gradle cache: `folded` stays
  false; two panes still come from the screen's width.
- Older tests about plan cards now confirm the kind first, as the wizard does; new tests cover the kind card, the
  "Something else" rule, the wizard's kinds and autopilot.

Tests: Python 992 pass (the conformance run included, 73 phone calls); phone 318 unit tests and the debug build pass; every
desktop JS file parses; the desktop opened with Playwright (Hall, Gallery both tabs, Tools, Settings and Spending,
the wizard, a project's tabs with the Command line running a command): no page or console errors.

Still open – only the real PC or phone can show these: the firewall rules and their one prompt on Windows; the
command line and Stop on Windows (process trees); rewind with Windows git; discovery on the home Wi-Fi; the phone's
comfort screens, Gallery, Undo… and proof card on the real phone; a real proof judge with a model that can see; web
search with the keyless engine for real. Also open: `androidx.window` for the hinge; a full git log view.

## 2026-11-27 – wave 2 put together

Asked: merge the seven wave 2 branches into one (w2-small, w2-compact, w2-cli, w2-memory, w2-files, w2-watch,
w2-message), do each part's hook-up lines, test everything. No release yet.

What each part is, plainly:
- **Small things** (w2-small): a conversation in the hub passed back and forth more than 12 times stops and goes
  back to its sender (hops); a **daily tidy-up** that removes old logs, pictures, spill files, merged worktrees
  and old hub runs, with a log and a dry run, never the project's own files or attachments (`retention.py`,
  `harness/eventlog.py` archives old events instead of cutting them, `ui/tidyapi.py`, `static/tidy.js`);
  **What's new**: a short card once after the app updates (`ui/whatsnewapi.py`, `static/whatsnew.js`).
- **Compaction** (w2-compact): a long task's older steps summed up by a cheap model (built-in plugin `compactor`).
- **Coding helpers** (w2-cli): Claude Code and Codex as workers on the owner's own subscriptions
  (`providers/cli_engine.py`, `docs/cli-workers.md`).
- **Memory and search** (w2-memory): a small project memory and this computer's (`memory.py`), and one search over
  plans, tasks, journal, letters, memory, notes and files (`search.py`, `ui/searchapi.py`, `static/search.js`,
  the phone's Search screen).
- **Files** (w2-files): browse a project's folder, open its files, save a copy, see the commands its tasks ran
  (`ui/filesapi.py`, `static/files.js`, the phone's Files screen).
- **Watch** (w2-watch): where each task's time went, how full its context is, files changed, several tasks side
  by side (desktop and phone).
- **The message box** (w2-message): one box with drafts kept, pictures, files, @file, Speak, and Next task or Now
  (`attachments.py`, `ui/attachapi.py`, `static/compose.js`, the phone's Composer and New idea screen).

Merges: only one conflict, `plugins/builtin/__init__.py` (compactor and attachments both registered: kept both, in
the order token saver, cost log, compactor, attachments).

Hook-ups done:
- `config.py`: `retention` in `FEATURE_SECTIONS`; `cli` in `PROVIDER_TYPES` and built in `HarnessConfig.provider()`.
- `agent.run_agent` hands a role on a `cli` provider to `cli_engine.run_cli_agent`; `model_turn` carries the four
  token counts; `tool_call` carries `waited_ms` (time waiting for Ask me first, `Workspace.run_command`,
  `Toolbox.take_waited`) and `agent_done` its total. `ParallelStage.stop_all` also stops every coding CLI.
- `catalog.py`: the coding helpers' entry is now in `PRESETS` (`CODING_HELPERS` kept as a name for it); Settings'
  Add a service hides the key box for it and its link says "How it works".
- `server.py` `FEATURE_APIS`: whatsnewapi, tidyapi, searchapi, filesapi, attachapi. `phone.py` `PHONE_ROUTES`:
  what's new, search, peek, memory, files (from the ready patch) and the message box's nine routes. The w2-files
  patch applied cleanly (`/raw/pfile`, the PDF frame headers, the Files tab, its styles).
- Desktop: `app.js` imports whatsnew.js, the Search room and the top bar's search box (`index.html`); Settings →
  Advanced has the tidy-up card; AutoSync's `daily_tidy()` after the backup; one Activity line per tidy-up;
  `roundtable tidy`; `session()` reads archived events too.
- Memory: `memory_block` in the planner's prompt (plan and revise) and every worker's (`Orchestrator._memory_part`),
  `learn_from_task` after each task (`ShowStage._learn_from_task`, from `_after_task`, so it works one at a time and
  several at once), `learn_answer` when the owner answers a plan question, `refresh_machine` when the Tools page
  is read on the desktop. THIRD_PARTY_NOTICES names Munder Difflin's `src/main/reflect.ts` and
  `src/shared/memoryShape.ts` as the design (no code copied).
- `sync.session_lines`: every line says its task; turns carry `ms`, `first_ms` and the tokens, tools `ms` and
  `waited_ms`; `agent_done` lines carry `other_ms`. Lines that only carry times have no words: the desktop's
  remote Watch skips them, the phone already did.
- Phone: Search icon and "+ New idea" on the Table; a search hit for a project or the journal opens the project,
  a letter opens Letters, the rest opens in place; a Files button on a project (`machineApi`: the PC or this
  phone that has it); "Tell the planner" uses the message box when the project is on a connected machine.
- The message box on the desktop: Talk to the planner (Ask → `chat`, Instruct → `note` with Next task or Now),
  Add to it (a new goal with pictures and files), the plan's Tell the planner, and Letters (words only: a new
  `noFiles` option keeps drafts and Speak without Attach).
- Several tasks at once: the template's `limits.max_parallel: 3`, and the recommended setup adds it when the owner
  hasn't set one; `parse_config` still defaults to 1.

Decided: the plan tab's "Tell the planner" (desktop and phone) still adds a change that waits for Update the plan;
the message box's `note` records a standing instruction instead, so the words go the plan's way and pictures or
files, when there are any, also go through the message box. Otherwise a note before approval would never show
the Update button.

Tests: `tests/test_wave2_hookups.py` (8: the cli type, routes and API modules, retention section, the template's
3, tokens and waiting time, task ids and times on the phone's lines, memory in prompts and learning from a
rejection, the CLI hand-over); the CLI orchestrator test now goes through the real hook. 825 Python tests pass;
phone: 252 unit tests and the debug build pass; every desktop JS file parses.

Still open: a Watch line for `compacted` events (optional); `refresh_machine` on app start (only on the Tools page
now); the phone's hub summary (`hub_session`) still reads the live event log only; `cli_engine.stop_all` stops every
coding CLI on the computer, not only that run's; at release, the README's "What's new in <version>" and
`python -m roundtable.updater --whatsnew-bundle`. Not tried on a real PC or phone yet.

## 2026-11-27 – 0.10.0: wave 1 – safety and several tasks at once

From plans/parity.md, Fable's order (plans/notes-for-owner.md). Six helpers, merged here with the hook-up lines.
- Breaker and timings (45f0115): `harness/breaker.py` (`Breaker`, `BreakerSettings`, `call_key`, `work_tokens`),
  `run_agent` steer → refuse → stop (`stop="breaker"`), `ms` on every model/tool event, `agent_done` totals.
  Policy after Munder Difflin `src/main/breaker.ts` (MIT).
- Ask me first (1a74e9e, ee98920): `harness/gate.py` (`classify`, `mode_for`, `Gate`), `run_command` waits on a
  `command` card (asks.py), files in `.harness/gate/`, default `risky`; desktop and phone cards; project setting
  `ask_first`; the phone's switch; server lets command cards through while the run works. Behaviour after DSH
  Mobile's ON-DEVICE.md, no code taken.
- Several tasks at once (473232f…d61c558): `harness/worktrees.py` (`Worktrees`, `ParallelStage`), merges in task
  order, `<task>-merge` fix-ups, kept worktrees with a reason, money/claim/stop_all stop all, task ids on every
  event, `max_parallel` read from harness.yaml (default 1). Removal rule after Munder Difflin's worktreeFate.ts
  (idea only).
- Notifications (8b92ce6): `notify.py` (`classify`, `Feed`), `ui/notifyapi.py`, `static/notify.js` (bell, pop-ups),
  phone `notify/` (Classifier twin, channels, answer buttons), shared test cases.
- Automations (5d5cf99): `automation.py` (schedules, GitHub issues, failed checks, once per slot across restarts and
  machines, money asks first), `ui/automationapi.py`, `static/automation.js`, `roundtable automation`, AutoSync tick.
  Ported from Munder Difflin `src/shared/weeklySchedule.ts` and DSH Mobile `AutomationPresentation.kt` (MIT).
- Tools (42195fc): `prereq.py` (12 tools found/installed, MCP servers added/tested/given to jobs via custom.yaml),
  `ui/toolsapi.py`, `static/tools.js`, the Tools tab. Catalogue shape after Munder Difflin toolCatalog.ts/toolsStatus.ts.
- Coordinator: `config.section()` and `FEATURE_APIS` seams; showstage's Godot tool uses the task's worktree; lab
  replays never wait on Ask me first. 669 tests; phone tests and build pass; no console errors on the new pages.
Needs the owner's PC/phone: real installs, notifications and their buttons, command cards on the phone.

## 2026-11-27 – 0.9.2: keys kept away from the helpers' commands

The owner: "go ahead and work with Fable and add everything" (from plans/parity.md). Fable's plan (in
plans/notes-for-owner.md): fix the keys first, alone, then three waves with a release each.

- `safeenv` (b7f82c2): `core/secrets.py` (in-memory vault: keys and the hub's git login out of os.environ),
  `harness/safeenv.py` `clean_env` (denylist: vault names, KNOWN_KEYS, provider `api_key_env`s, *KEY*/*TOKEN*/
  *SECRET*/*PASSWORD*/*CREDENTIAL*, GIT_CONFIG_*, GH/GITHUB tokens, askpass, the launch token, any value equal
  to a stored secret; adds GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never, an empty credential helper). Used by
  tools.run_command, checks.run, godot.run, mcp_tools (stdio), look/showit node runs, orchestrator/repostage/
  sync/evaluate git in project folders, scout clone. Providers, balance, manage, routing, the UI read keys
  through the vault; desktop KeyStore and onphone write to it; GitStore passes the hub login explicitly.
  Tests: tests/test_safeenv.py (env dumps through every path, an ast guard on subprocess calls, providers).
- Not covered: plugins and Playwright run in Roundtable's own process; a command still runs as the owner
  (the sandbox is release 6; Ask me first is wave 1).

## 2026-11-27 – 0.9.1: short first, details on request

The owner (phone screenshots of a finished plan): "Too much information everywhere – overload"; "No live";
then "put all the links I've sent in a document so I can see"; and "look at Munder Difflin and DSH Mobile,
see what they have that we don't … let me know the difference before you make any changes".

- New rule in CLAUDE.md: short first, details on request.
- `calm` branch (039b80f…7e6a30e): plandoc `title`/`summary` from the planner, `short_title`, `plan_title`,
  `state_sentence`, `estimate_line`, `waiting_items`; `render_markdown(waiting=)` with the builders' brief
  folded; orchestrator `plan_words()` in `.asks.json`; hall/roundtable read them; phone `PlanTop`/`MoreAboutPlan`/
  Fold.kt, desktop plan.js `splitPlan`/`taskLines`; Live: "Final pictures", `ShowStage.show_it_now`, remote
  action `show_it`, `/api/hub/live`; My notes: `/api/notes`, `/api/note`, `hall.hub_notes`, phone NotesScreen.
- One-off hub data: the music player's pictures taken from the cloud copy and published (it was built before
  pictures existed); `notes/links.md` (every link the owner sent, grouped) and `notes/compared-with-munder-
  difflin-and-dsh.md` in the hub.
- **Comparison with Munder Difflin and DSH Mobile** (branch `parity`, `plans/parity.md`, 9123df9): 172 features,
  47 have, 55 partly, 55 missing, 15 not wanted; top gap a security fix (workers' shell commands can read the
  API keys: `run_command` passes the app's environment). Nothing built from it yet – the owner asked to see the
  differences first.

## 2026-11-26 – 0.9.0: the desktop rebuilt, the phone and PC as one, Opus codes

Asked by the owner: "check the app for more errors … the roundtable hall was supposed to show all my
projects … fix the homepage, the UI layout is not great"; "why is Claude Sonnet the coder and why can't I
change it"; "I'm not supposed to ever leave the app"; "rebuild the whole desktop app … use my references
as a guide"; "make Opus 5.5 the default coder and DeepSeek Flash the backup"; "do the phone and PC sync";
"MSE Studio should be Opus only" then "leave MSE Studio". Built by helpers (Opus, medium effort, as asked).

- **PC set-up fixes** (`3f726fb`): `desktop.KNOWN_KEYS` + `provider_key_names` (a custom provider's key
  loaded at start: the OpenRouter key showed "missing"), `key_label`; `balance.check_key`,
  `manage.test_provider` (Test checks the key, not the public model list); new template = the owner's
  split, no V4 Pro; `recommended.py` (Use the recommended setup); `desktop.migrate_configs` (V4 Pro →
  Flash, old templates replaced, a journal decision line).
- **Opus codes by default**: template, recommended setup and the phone's first start: coder
  `anthropic/claude-opus-5-5` (effort medium) → `deepseek/deepseek-v4-flash`; Budget keeps Flash.
- **Hall data** (`73adaaf`): the hub repository's hub.yaml is re-read on every sync (agents added later
  never reached the PC: `connect_hub` copied them once); `ui/hall.py` seat model (every project a seat with
  a friendly name, Roundtable-built projects out from under "harness", "My notes"); `/api/hub/plan`,
  `/api/hub/command`; plan-ready to-dos get Open the plan / Approve.
- **Desktop rebuilt** (`desktop-rebuild`, 8 commits): `static/` as ES modules (app, core, asks, autopilot,
  hall, needs, projects, project, plan, watch, journal, letters, activity, models, settings, machines);
  `routing.py` (`/api/routing`: change who does every job, per set); `/api/features`; design in
  `docs/desktop-design.md`. Every audit item fixed (ids, jargon, raw paths and variable names, empty
  states, layout at 1000–1920 px).
- **Sync, Roundtable side** (`c9acff9`, `b775f7d`): `sync.py` (machine seats in hub.yaml, `project_key`,
  claims with heartbeats and takeover, live sessions in `sessions/<key>/<run>.jsonl`, `machines/<seat>.json`,
  `settings/shared.yaml`), `ui/syncapi.py` (`/api/machines`, `/api/hub/session`, `/api/settings/shared`,
  `/api/hub/carry_on`), `limits.max_usd_per_day`, remote commands addressed by `machine`, git pulls that
  settle clashes file by file. The owner's own machine seats (role: machine) may send commands.
- **Sync, phone side** (`aaee145`): `data/MultiBackend.kt`, `data/Sync.kt` (several connections at once,
  seats merged, commands routed), Your computers (Join my hub, pairing), watch a build from anywhere,
  shared and per-project settings, a runtime update check.
- **MSE Studio**: switched to Opus through OpenRouter at the owner's word, then left at the owner's word
  before anything was built; its plan is paused in the hub and nothing was pushed.

Open: everything here needs a run on the owner's real PC and phone (a folder shared through Remote
Control, the phone by USB); "Ask me first" on the phone isn't wired; a change to one model set isn't
shared between machines (only the base choices and the default set are).

## 2026-11-26 – 0.8.0: the phone in plain words, its updater, This phone (beta), existing apps

Asked by the owner, in this order: "I dont understand anything i cant click the ideas or questions";
"as less clicks as possible with the most information … or at least organized and useful"; "use my
phone as harness itself so I'm not using GitHub … just like DSH Mobile"; "this mobile Roundtable should
connect with the PC and all sessions should be synced"; "get everything ready for MSE Studio … try that
out through Roundtable"; "every single repo … configurable in a file … through phone or desktop"; "an
app updater for both". Built by helpers on their own branches, merged here.

- **Phone in plain words** (`88d9ce3`, `3f9f5b7`): `Asks.fromPlan` builds cards whatever the plan's state
  and `Asks.planCommands` answers with remote.py's own commands; remote.py's `answer {question,text}` fixed;
  `data/Plain.kt` (letters as sentences, receipts read at once and grouped), `NeedsOrder.organise` (by
  project, then questions → money → to-dos → ideas → letters), Mark all read, `StatusText.tidy`, "Letters"
  tab; orchestrator `_attention(details=)` and `_finish` next steps in plain words; `_close_goal_plans`
  (the cause of finished goals staying in Future plans: the plan entry lived in another hub journal);
  planner prompt and `plandoc.PLAIN`: questions for a non-programmer.
- **Phone updater** (`71a863b`): `update/Releases.kt`, `AppUpdater.kt`, `Installer.kt` (PackageInstaller),
  `UpdateWorker.kt`, `ui/UpdateCard.kt`; borrowed from DSH Mobile's `update/` (UpdateChecker, Checksums,
  PackageInstallerGateway, InstallStatus, ResumableDownloader; credited). remote.py `todo_done` and a Done
  button on to-do cards in Hub mode.
- **This phone (beta)**, slice 1 (Fable's plan in plans/notes-for-owner.md): Python `onphone.py`
  (`roundtable phone serve --local`, launch token from the environment, `/api/health`, `/api/keys`,
  `/api/hub`, first-start DeepSeek-only config, seat `phone-xxxxxx`), `runtime/` (Dockerfile, build,
  manifest in DSH's schema 1 with xz layers, Ed25519 signing; `runtime/test-key/` is a public TEST key)
  and `.github/workflows/runtime.yml` (`665bd6c`); Android `runtime/` borrowed from DSH Mobile's
  `runtime/` (AndroidRuntimeSystem, AppVersion, FsOps, HarnessLog, HarnessProcess, HarnessRuntimeService,
  HarnessSupervisor, LayerDownloader, ManifestPolicy, ManifestVerifier, ProotCommand, RuntimeInstaller,
  RuntimeLayout, RuntimeManifest, TarExtractor, with tests; proot binaries byte for byte, GPL-2, source
  linked), `ThisPhoneScreen`, `HarnessScreen`, `RuntimeViewModel`, `net/ThisPhone.kt` (loopback only)
  (`beb4d03`). x86_64 layers built and smoke-tested here; arm64 and a real phone not yet.
- **Existing apps (repository mode)** (`c53d2f4`): `harness/repostage.py` (own branch `roundtable/…`,
  `.git/info/exclude`, commit guard, the repo's rules in every prompt), `projectsettings.py`
  (`.harness/project.yaml` over `roundtable.yaml` over defaults; test, env, setup, timeout, branch,
  rules_files, providers_allowed, profile, limits, look, show_it, notes), `reporules.py`, `checks.py`
  (baseline, only new failures blamed), `roundtable settings` / `set`, `/api/project/settings` (also on the
  phone's routes), a Settings card on the desktop project page, `docs/repositories.md`.
- **MSE Studio set up** for a first try: its tests pass here (686) with the add-ons next to it and Qt's
  system libraries installed; a DeepSeek-only lab config; planning with `roundtable new … --approve`.

Open: real-phone tests (proot on Android 16/ColorOS, installs, the updater) through the owner's PC once a
folder is shared; slice 2 (sync with the hub and the PC); the phone screen for project settings; the
real runtime signing key before the official phone release.

## 2026-11-26 – Godot games, with Blender (0.7.3)

The owner: "Do one for Godot support as well… I want that to work with Blender and everything… make
another framework as well." Godot and Blender need no new code to be driven (MCP from 0.7.2: Godlink
MCP, tomyud1/godot-mcp, and MCP for Blender, both MIT, both stdio); what was missing was proof.

- `harness/godot.py` (new): `find_godot` (setting, `$GODOT`, PATH, usual folders; never downloads),
  `project_dir` (root or one down), `check` (`--headless --import`, then `--headless --quit-after 60`;
  `errors_in` picks out script and load errors), `screenshots` (Movie Maker, `--write-movie
  frames/frame.png --fixed-fps 30 --quit-after N`, `xvfb-run -a` and opengl3 on a Linux without a
  screen; keeps 3 frames), `run` (kills the process tree on a timeout), `game_tool` (`run_game`).
- `config.py`: `godot:` (`GodotSettings`: path, frames, timeout, enabled). `showit.take_shots` →
  `_game_shots` for a Godot project with no web page (pictures `start`, `middle`, `desktop`; the check's
  errors; a plain note when Godot isn't installed); `showstage._shots_wanted`; orchestrator gives
  `run_game` to writing workers and the reviewer on Godot projects; app.js names the new pictures.
- Tests: `tests/test_godot.py` with a stand-in Godot (`tests/fixtures/fake_godot.py`); 335 pass.
- `docs/godot.md`: installing, the Godot and Blender plug-ins, harness.yaml (a `game_builder` and a
  `modeller` role), Blender to Godot as .glb, how the check works.

Not tried with a real Godot (running a downloaded program wasn't allowed in this session): `--import`
(4.3+), Movie Maker's frame names and xvfb need the first real run. A "Godot game" kind (plans/kinds.md)
would bundle these roles, the check and the prompts.

## 2026-11-26 – Money to-dos close when the run carries on

The owner's phone showed 16 "need you", two of them the music player's "high" money to-dos, though that
project finished hours ago. `Orchestrator._attention("money", …)` was never resolved, and a finished run
didn't close any. `run` now resolves `approval`, `budget` and `money` when it resumes, and `_finish` does
too. Test: `test_money_and_budget_todos_close_when_the_run_goes_on`. One-off hub fix: closed the two stale
to-dos (87fe66, c908ed) and the DeepSeek-prices one (e85317; prices are built in).

## 2026-11-26 – Tool servers (MCP) for roles, and Unreal Engine (0.7.2)

The owner asked for something that can drive Unreal Engine's assets and Blueprints, then "Go ahead"
on building MCP support into Roundtable. Unreal 5.8's own plug-in, Unreal MCP, serves the editor's
tools over streamable HTTP at `http://127.0.0.1:8000/mcp` (Epic's docs: no stdio, no password, one call
at a time, and with tool search on only four tools: list_toolsets, describe_toolsets, describe_tools,
call_tool).

- `harness/mcp_tools.py` (new): `MCPServerClient` (one server, its own thread and event loop with the
  `mcp` 2.x `Client`, stdio or streamable HTTP, one call at a time, timeouts), `MCPPool` (one run's
  servers: `tools_for`, `failed`, `close`), `tool_name` (`mcp__<server>__<tool>`), `result_text`
  (pictures and files as one line), `check_servers` (the CLI). A JSON string sent where the schema wants
  an object is decoded (Unreal's `call_tool`).
- `harness/config.py`: `mcp_servers:` (`command`/`args`/`env`/`cwd` or `url`/`headers`; `tools` allow-list,
  `timeout`, `enabled`) and `mcp:` on chat roles, with plain errors. Opt-in: a role without `mcp` sees none.
- `orchestrator.py`: `_add_mcp_tools` for workers (and the reviewer only if its own role lists `mcp`),
  `_close_mcp` when a run ends. A server that can't start gives an `mcp_error` event and the run goes on.
- `improve/evaluate.py`: replay tests get no MCP tools (`mcp_allowed = False`), so the lab never changes
  an editor that happens to be open.
- `roundtable mcp list` (`harness_cli._mcp_list`; `main._after` keeps `roundtable mcp` for the hub server).
- The Windows build had `mcp` excluded: `packaging/roundtable.spec` now collects `mcp` (but its CLI) and
  `mcp_types`, and the installed app's `--self-test` checks the MCP client is there (`_mcp_client_present`).
- Tests: `tests/test_mcp_tools.py` with `tests/fixtures/fake_mcp_server.py` (a made-up editor over stdio,
  and over HTTP with `FAKE_MCP_PORT`, like Unreal). 318 pass.
- Docs: `docs/mcp.md`, `docs/unreal.md` (installing Unreal 5.8, turning on Unreal MCP, Claude Code or a
  Roundtable role), README.
- Fab kits (the owner's list): advice given in chat – one framework (the Blueprint Soulslike Framework) plus
  a matching environment first; several packs say "Allows AI usage: No".

Open: not tried against a real Unreal editor (needs the owner's PC) or on Windows yet; MCP tools aren't
offered to planning, asks or the report; no MCP page in the app; `create_mcp_http_client` comes from a
private module of the SDK.

## 2026-11-26 – The phone APK on every release

The owner asked where the APKs are kept (only in the session's scratch folder and in chat) and chose
to attach them to every release from 0.7.1. `.github/workflows/app.yml`: a new `android-apk` job builds
the test APK (Java 17, the runner's Android SDK) and the Windows job attaches it as
`RoundtableMobile-<version>-test.apk`. `mobile/test-key/debug.keystore` (Android's standard debug key,
password `android`; README there) signs every test build the same way, so a new test APK installs over
the last one; it's the key that signed the APKs already sent, so no uninstall. The release key stays
separate and out of git.

## 2026-11-26 – Pictures taken in the same second keep their order (Windows)

CI on Windows listed two tasks' pictures oldest first: `shots.json` times are to the second, and ties
fell to folder order. `showit.take_shots` records a running number (`seq`, `_next_seq`) and `history`
sorts by time then that number. Test: `test_pictures_taken_in_the_same_second_keep_their_order`.

## 2026-11-26 – Hub ids always move forward (Windows clock)

CI on Windows failed `test_commands_through_the_hub`: "revise" and "approve" sent one after the other
got the same timestamp (Windows' clock ticks about every 16 ms), so their order came from the random
suffix and "approve" could run first (and be refused while changes waited). `core/models.new_id`
now keeps the timestamp moving forward within the process; `test_ids_made_one_after_another_sort_in_order`
uses a frozen clock. 294 pass.

## 2026-11-26 – Release 0.7.1

The owner chose to ship the live view and the phone crash fix. `pyproject.toml` and
`roundtable.__version__` 0.7.1; README "What's new in 0.7.1".

## 2026-11-26 – The phone crash: Android's regex engine

The owner's phone (Android 16) closed Roundtable Mobile on every start after the hub token. The new
crash catcher (`data/Crash.kt`: details saved, safe mode, "Send the details to my PC") delivered the
trace to the hub: `NoClassDefFoundError: com.meztking.roundtable.data.Markdown` in the Letters list –
the class failed to initialise because Android's ICU regex refuses a bare `}` (and `]`) that Java
accepts (`trailingBraceId`, `checkRe` in Markdown.kt; three more in PlanDoc.kt). The JVM tests never
saw it. All five escaped; `tests/test_mobile_regex.py` scans every `Regex("…")` in the Kotlin sources
so it can't come back.
## 2026-11-26 – See what's being made: Show it, the Live and Session tabs

The owner: "You should be able to visually see what each session is making. If they're making an
app or anything, you should be able to see the app being made … You should be able to see
everything, not just text. Follow the Claude Code CLI; we want it to be very similar to that."

- **Show it** (`harness/showit.py`, new): after each approved task, when the plan has `has_ui` or
  the project has an `index.html` (`entry_page`: the top, `public/`, `www/`, `dist/` …),
  `take_shots` serves the folder on a local `StaticServer` (127.0.0.1, a free port, the folder only:
  `safe_path` refuses `..`, absolute paths, hidden parts and links out; `content_type`) and
  `render_pages` takes desktop 1280×800, phone 390×844 and, when the app uses
  `prefers-color-scheme` (`supports_dark`), dark pictures, with console and page errors and the
  title, through Playwright for Python or Node (as `look.py`; requests outside the app and Google
  Fonts are blocked). Saved to `.harness/shots/<task>/{desktop,phone,dark}.png` (+ `.jpg`) and
  `shots.json`, plus `shots/latest.json`. Never fatal: no Playwright is a note, a crash is `failed`.
  A `package.json` start command is noted (`start_command`), the static page shown.
- `harness/showstage.py` (new, a mixin like the Look stage): `_after_task` runs `_show_it` (emits
  `shots`) and `_publish_live`: `plans/shots/<project>/session.json` after every task, and with new
  pictures `showit.hub_files`: `latest-{desktop,phone,dark}.jpg`, `<task>-desktop.jpg` for each
  finished task (at most `HUB_KEEP` = 20, the oldest removed) and `latest.json`. Pictures go to the
  hub as JPEG (Playwright writes both; a PNG only when under 300 KB), so the names end in `.jpg`.
  `_hub_name` is shared with `_publish_plan`. Config `show_it: auto|off`.
- `core/store.py`: a value of `None` in `write_json` removes that file (FileStore unlinks; GitStore
  `git rm --cached` for tracked ones).
- `harness/tools.py`: `file_change` (a unified diff, trimmed to 8 KB, with lines added and removed);
  `Workspace.last_change` after each write or edit; `Toolbox.take_change`. `harness/agent.py`:
  `_tool_event` keeps that diff and the end of a command's output in the `tool_call` event;
  `model_turn` carries the role.
- `harness/session.py` (new): `tasks_from_events` turns events.jsonl into each task run's steps
  (`tool_step`: Read / Write / Edit with diff / Run passed or failed / Search / Finished; the
  model's words with the turn's cost; attempts, reviews, pictures, errors), `outputs` (pictures and
  apk/zip/exe… by the task that wrote them, else by time), `redact` (backup's key patterns),
  `hub_session` (the latest task's last 40 steps as lines), `cursor` (the event log's size).
- Desktop: `ui/live.py` (new): `LivePreview`, a second read-only web server on another port for
  the apps themselves (`/<project key>/<file>`, its own CSP: no internet, `frame-ancestors` the app);
  another port is another origin, so `sandbox="allow-scripts allow-same-origin allow-forms"` can't
  reach Roundtable's pages or API. `live`, `session_view`, `raw` (pictures inline under a sandbox
  CSP, everything else as a download, never as a page). `ui/server.py`: `/api/project/live`
  (`inline=1`: data addresses for the phone), `/api/project/session` (`since` cursor; `compact=1`),
  `/raw/shot` and `/raw/file`, `frame-src` the preview's origin, the `shots` line; `serve()` and
  `desktop.py` start the preview. `ui/roundtable.py`: the seat's `shot`. `phone.py`: both routes in
  `PHONE_ROUTES`.
- `static/app.js`: the project page's tabs (`runTabs`, `#/run/<path>?tab=live|session`),
  `liveTab` (the frame with Computer/Phone width, Reload, Open in browser; the newest pictures and
  the Earlier strip; `enlarge`), `sessionTab` (a terminal transcript: `stepNode`, `diffView`,
  `outputList`; follows live and keeps to the newest step until the owner scrolls up), `follow`,
  the seat's thumbnail. `style.css`: the Live and Session styles (`--term-*`, dark oak in both looks).
- Phone: `data/Live.kt` (`LiveShots`, `SessionSummary`, `Live.parse*`, `dataUrl`),
  `ui/LiveTab.kt` (pictures, tap for full screen with pinch to zoom, the steps), the project's
  **Live** tab (index 3), `Backend.live` (Hub: `GitHubHub.shots` / `session` / `shot` bytes; PC:
  `Api.live` / `session`).
- Tests: `tests/test_show_it.py` (15), `LiveTest` (3), `ScreensTest` +3 (`10-project-live`, dark,
  empty). Screenshots of a made-up "harbour tides" page built by a scripted run (Live and Session,
  light and dark, the seat, the enlarged picture, the phone frame) looked at.
- Decided: the iframe app runs on its own port rather than the same origin (with
  `allow-same-origin` on the same origin a model-written app could call Roundtable's API and run
  commands); hub pictures as JPEG, not PNG, to stay small.
- Open (plans/gaps.md): a model that can see judging the pictures; start commands for apps that
  aren't a static page; screenshots of Android and desktop apps; games played for a minute; the
  Live frame only works on this computer (not through `roundtable ui --host`).

## 2026-11-26 – 0.7.0's installer build stopped: a second version number

The app workflow refused `release_tag: v0.7.0` because `roundtable.__version__` still said 0.6.0
(only `pyproject.toml` had been raised). Fixed; `test_the_two_version_numbers_match` keeps the two
equal; CLAUDE.md's release steps name both. Nothing had been published, so 0.7.0 now also carries
autopilot (merged meanwhile; README "What's new").

## 2026-11-26 – Autopilot: decisions while the owner is away

The owner: "Add an autopilot button so you'll automatically make decisions while I'm off my
screen." The spirit is the coordinator's own rule: reversible choices are made freely and written
down; anything important waits for the owner.

- `src/roundtable/autopilot.py` (new): the state in the app's settings (`<app home>/config/app.json`,
  key `autopilot`: on, until, spend_cap_usd 2.00, started_at, spent_usd, never), `turn_on` /
  `turn_off` / `set_never` / `status` / `parse_until` ("1h", "tonight" = 8am, "08:00", ISO), the log
  (`autopilot-log.jsonl` and `autopilot-log.md`, newest first; `entries`), `decide` (the guard rails)
  and `tick(cfg, hub, home, start, busy, now)`: every project's `open_asks` answered one at a time
  through `asks.answer_ask` (no second way of changing things); a long step it starts goes to
  `start` (the desktop app: `UIApp.start_answer_job`; the command line: `finish_now`). Rules in code:
  the recommendation for plan choices, questions, look, setting and ideas (none: left open);
  approve only when the estimate fits what's left of the cap and the project's own limit and the
  cost is known, preferring "start at half price" when it starts before `until`; a failed task
  retried once with the same models (`autopilot_retried` in the project's meta); money pauses
  left; never an option with `confirm` or one that deletes, publishes, releases or merges
  (`_safe`); at most 3 plan updates per project per session (`MAX_REVISES`, no endless loops); it
  turns itself off at `until` or the cap (`_should_stop`; spent = Roundtable's count since
  started_at, or the providers' real balance drop when larger). A card left for the owner is
  logged once per question. Each choice is a journal `decision` ("Autopilot chose … because …");
  on/off go in the harness's hub journal; `plans/autopilot.json` in the hub carries the state and
  newest log lines for the phone in Hub mode (`_publish`). A tick saves only its own fields
  (`_keep`), so the owner's switch made meanwhile wins.
- `asks.py`: an idea the planner marks `recommended: false` has no recommendation.
- `ui/server.py`: `/api/autopilot` (GET status and log, POST on / off / never),
  `start_answer_job` (shared with `/api/asks`), `autopilot_tick`. `ui/roundtable.py`:
  `AutoSync.tick` runs autopilot after the backup, the cheap runs and the hub sync; seats carry
  `autopilot`, the table carries the switch. `phone.py`: `/api/autopilot` in `PHONE_ROUTES`.
  `remote.py`: the `autopilot` hub command (`autopilot_command`). `main.py`: `roundtable autopilot
  on|off|status|log|never|--watch`; `roundtable remote --watch` ticks autopilot too.
- Desktop (`static/`): the **Autopilot** button next to Today (outlined off, lit amber on with
  "until 8am · $0.40 of $2.00"), its card (until: Off when I'm back / 1 hour / Tonight / Custom; the
  spend limit; tooltips), **What autopilot did** with links to the plans, the seats' *autopilot*
  mark, **Never on autopilot** on the project's panel. The header's end (`.hdr-end`) holds Today and
  Autopilot; on a narrow window the name hides so they fit.
- Phone: `data/Autopilot.kt`, `ui/AutopilotSheet.kt` (toggle, sheet, log, seat marks), the
  `Backend.autopilot` / `setAutopilot` pair (Hub: reads `plans/autopilot.json`, sends the hub
  command to the project the PC reads; PC: `/api/autopilot`).
- Tests: `tests/test_autopilot.py` (17), `AutopilotTest`, three screenshots in `ScreensTest`.
- Decided: an unknown plan cost (an unpriced picture model) waits for the owner rather than being
  guessed; a run autopilot started isn't stopped at the cap (its project's limits apply), noted in
  plans/gaps.md.

## 2026-11-26 – Release 0.7.0

The owner chose to release. `pyproject.toml` 0.7.0; README "What's new in 0.7.0"; Settings no
longer breaks when there's no hub file (the config editor says it's not set up yet). Pull
request to main, CI, merge, then the app workflow with `release_tag: v0.7.0`.

## 2026-11-26 – Cheaper everywhere: DeepSeek off-peak, and start when it's cheaper

The owner: "Make them all cheaper while keeping the quality."

- DeepSeek charges half outside its peak hours (reported: 01:00–04:00 and 06:00–10:00 UTC, since
  August 2026). `harness/config.py`: prices may carry `offpeak` rates and `peak_utc` windows
  (`DEEPSEEK_PEAK`, `in_peak`, `next_offpeak`, `price_now`); `DEFAULT_PRICING` has DeepSeek's
  current official prices (V4-Flash: $0.44 / $1.32, cache $0.014; half off-peak) for
  `deepseek-flash` (V4.1-Flash, DeepSeek's newest cheap model, in its model list) and
  `deepseek-v4-flash`.
- `Orchestrator.cheap_start_at` / `start_when_cheap`; `run()` waits while `start_after` is in the
  future ("waiting_cheap"); `due_cheap_runs` and `AutoSync.start_cheap_runs` (desktop tick) start
  them on time via `UIApp.start_run_job`. The approve card offers "Approve, start at HH:MM UTC"
  when a model doing the work is half price later.
- Quality is untouched: same models, same reviews and checks; only when and through which door.
- Tests: `test_deepseek_is_half_price_off_peak`, `test_approve_can_wait_for_the_cheaper_hours`;
  258 pass. Open: the peak hours come from news reports of DeepSeek's announcement; check its
  pricing page now and then.

## 2026-11-26 – Cheaper OpenRouter: the cheapest route, and no whole big files

The owner: "Find a way to optimise token usage for OpenRouter" (they'll top up the credit).

- OpenRouter sends a model to one of many companies, at prices far apart for the same model:
  GLM-5.3 from $0.07 to $2.10 per million input tokens; GPT-6.1 Terra has a half-price route.
  `OpenAICompatProvider(routing=)`: for OpenRouter, requests ask for `provider.sort = "price"`
  (with `require_parameters`, so tool calls stay supported) unless a provider's config says
  `routing: throughput | latency | none`; `last_route` records which company answered. Real
  check: the same GLM-5.3 call cost $0.000295 with OpenRouter's own choice and $0.000116 with
  price routing (2.5x less; both the same company, a dearer and a cheaper endpoint).
- `Workspace.read_file`: a file over 400 lines isn't read whole; the model gets its outline
  (definitions and headings with line numbers) and the first 120 lines, then reads parts of up
  to 600 lines (`_outline_and_head`, `WHOLE_FILE_LINES`, `MAX_RANGE_LINES`). The music player's
  188 KB `js/app.js` comes back as 10.6 KB. Every later step re-sends what was read, so this
  saves on every step after.
- Claude through gateways already uses its cache (`cache_control`, earlier today); GPT, Gemini,
  DeepSeek and GLM cache by themselves.
- Tests: `test_openrouter_asks_for_the_cheapest_route_unless_told_otherwise`,
  `test_big_files_come_back_as_an_outline_and_a_start`; 256 pass.
## 2026-11-26 – The Candlelit Oak look

The owner asked: "Also do a redesign for Roundtable." Roundtable designed three looks for
itself and the owner tapped **A, Candlelit Oak**: "a warm, hushed hall where a single candle
burns beside whoever needs you"; signature: "a carved wooden round table in the middle of the
Hall, with the seat that needs you lit by a flickering amber candle-glow".

- Desktop (`src/roundtable/ui/static/`): `style.css` rewritten on the design file's tokens
  (`--color-*`, `--font-display` Fraunces, `--font-body` Nunito Sans, `--radius` 18px) plus a few
  derived ones (wells, good/bad/warn, tag colours per theme), light by default, dark under
  `prefers-color-scheme` and `:root[data-theme]`. New `theme.js` applies the choice before the page
  draws; Settings has a new **Look** card (`lookCard` in `app.js`: Light, Dark, Same as this
  computer; kept in the browser's storage). `index.html`: the sidebar became a header (the
  emblem, the rooms as pills in a `.rooms` row that scrolls sideways on a phone, **Today** spend
  `#today-spend`, filled by the Hall's `draw`); element ids and `data-nav` unchanged.
- The Hall (`viewRoundtable`): with up to seven seats the seats sit around the carved table
  (`.rt-strip.ring`, each seat's angle in `--a`, CSS `sin()`/`cos()`), with an empty chair
  ("+ Pull up a chair", to `#/new`) and "The Hall · N seats · M need you" on the table; more seats,
  or a narrower window, make a grid under the table. Dark shows the painted hall, light the table
  alone on the warm floor. Seats show status, the latest line, progress, "% done" and the spend.
  Only a waiting seat gets the candle glow, a slow 3-second flicker (`rt-candle`), steady with
  `prefers-reduced-motion` (which now stops every animation). The running seat's glow and the
  pulsing dots are gone (the design's "never" list).
- Question cards: options stacked, big; the recommended one (always first) filled in amber with a
  RECOMMENDED tag (the text "(Recommended)" became "Recommended"); the Other box dashed with a dark
  Send. The plan page, wizard, task board, chat, minutes and Settings use the same cards, pills and
  buttons. All text pairs checked at WCAG AA or better (muted on the well 5.1:1 is the lowest).
- Fonts are served by the app (the CSP allows nothing outside): `fraunces.woff2`,
  `nunito-sans.woff2`, `nunito-sans-italic.woff2` (Latin variable files from fontsource 5.3.0);
  `ui/server.py` registers the woff2 and webp types. Credits and the OFL in THIRD_PARTY_NOTICES.md.
- Art: `hall.png` and `emblem.png` are original art generated by an image model for this project
  (in the session scratchpad, `rt-art/`). Made from them: `static/hall.webp` (73 KB),
  `static/table.webp` (the table cut out, 44 KB), `static/emblem.png` (128 px), `static/icon.png`
  (favicon, 64 px), `packaging/roundtable.ico` (16–256 px) and `packaging/roundtable.png` (256 px).
- Phone (`mobile/`): `ui/theme/Theme.kt` now has `LightOak`/`DarkOak` palettes; `Hall`'s colours
  (the old names, so the screens hardly changed) read whichever `RoundtableTheme` picked from the
  phone's dark setting; Fraunces and Nunito Sans as fixed weights in `res/font/`; corners 12–18.
  New `Hall.onAccent`, `Hall.candle`, `Hall.onWood`, `Hall.on(color)` (text on a filled colour;
  it also fixes the "chosen" chip, which drew ink on ink), `candleFlicker()` (steady when the
  phone's animations are off). Table screen: the emblem in the header, the painted table in the
  middle with the count on the wood, the waiting seat lit by the flickering candle, the selected
  seat ringed (not lit). `AskCard`: the recommended answer filled amber with a RECOMMENDED tag.
  The launcher icon is now the emblem (`mipmap-*/ic_launcher_foreground.png` on the dark oak
  background; the drawn vector is gone); the window background follows light/dark
  (`values-night/themes.xml`). The painted hall is left off the phone for readability.
  The plan tab's choices are rounded oak boxes, the recommended one edged in amber.
  `ScreensTest`: three dark drawings added (`+night`), and animations turned off before each
  drawing (as a phone set to reduce motion), otherwise the flickering candle kept each drawing
  waiting about two minutes. 49 Android tests pass; the APK builds.
- Decided: no external font requests (the app works offline and its CSP forbids them); the hub
  path that sat at the foot of the sidebar is hidden in the header (it is in Settings).
- Open: check the window on a real Windows PC (WebView2 needs CSS `sin()`, in Edge since 2023);
  the phone's look on a real phone; the Settings page fails as a whole when there is no hub
  config at all (seen with a made-up lab; it was like that before).

## 2026-11-26 – Cards and plugins merged and wired; the APK and EXE finished by hand

- Merged `question-cards` (tap-to-answer cards everywhere: `asks.py`, `/api/asks`, the desktop
  cards and wizard, the phone's `AskCard`, the hub `answer` action) and wired the plugin system
  into the parts it couldn't touch: `orchestrator.emit` → `plugins_notify`, `run` →
  `plugins_begin_run`, roles passed to `run_agent`; `/api/plugins` in `ui/server.py`;
  Settings → Plugins (`pluginsCard` in `app.js`). 254 tests pass.
- The music player's APK and EXE: Roundtable's run spent its $1.51 limit with one of four tasks
  done (the copy script); the planner had estimated $3.45, above the $0.50–1.50 the coordinator
  had told the owner. Fable advised stopping the paid run and finishing by hand (notes for the
  owner). The Android app Roundtable had half written built after one fix (a wrong
  `shouldInterceptRequest` signature); the Electron wrapper was written by hand, built for
  Windows x64 on Linux without Wine, and checked by starting the same app code under a virtual
  screen. Both sent to the owner; neither tried on a real phone or Windows yet.
- Gaps: a run must stop and ask when its estimate is above what the owner was shown; workers
  read big files whole.

## 2026-11-26 – Answer by tapping: question cards

The owner asked: "Roundtable question and answer based mainly, just like the way you ask me
questions and I have to answer by pressing. More pressing of those rather than typing, but
obviously give an option to type as well."

- New `src/roundtable/asks.py`: one card shape for everything that waits for the owner
  (`id, kind, header ≤ 12, question, detail, options [{id, label, description, confirm?,
  picture?}], recommended (first), multi, allow_other, other_hint, stamp, answer, source`).
  `open_asks(orch, answered=False)` builds them in order: money pause, failed tasks, then
  (until approved) decisions, questions, the look, the setting, ideas, approval. `answer_ask`
  applies an answer through the existing actions only (`plan_update` choose/answer/idea/look/
  note, `set_profile`, `approve`, `retry`, `accept`, `skip`, `steer`) and returns `then`
  (run, revise, looks) for the caller to start; `finish` does that in the foreground (hub).
  `stamp` refuses an answer to a question that changed; `confirm` options need `confirmed`
  ("Are you sure?"); `skip` keeps a card away until it changes (`asks_dismissed` in
  project.json). `wizard_asks`/`wizard_project`/`slug`: the new-project cards.
- `harness/plandoc.py`: questions carry `options` (2–4), `recommended`, `multi` and a
  `header`; decisions a `header` (`_questions`, `_header`, the submission schema,
  `_question_markdown` writes "Answers: …" under each question). Old plans without them still
  work (a text box only). `prompts/orchestrator.md` asks for likely answers, recommendation first.
- `harness/orchestrator.py`: `Task.stronger` and `retry(task, stronger=True)` with
  `stronger_models` (the Quality setting's models for the role); `raise_budget` (a per-project
  `budget_extra_usd`, so "Carry on with $X more" doesn't change other projects); why a run
  paused is kept as `pause` (budget, money, money_nothing_done, credit); `plan_update("answer")`
  records the tapped `chosen` ids; `_publish_plan` also writes `plans/<project>.asks.json`
  (`_asks_json`), and `_attention` publishes so the phone sees a new card.
  `harness/lookstage.py`: the wizard's look answer (`look_step`, `look_brief`) wins over the config.
- `ui/server.py`: `GET /api/asks` (`?path=`, `?answered=1`, `?wizard=1`) and `POST /api/asks`
  (an answer, or `{wizard: …}` to start a project with the chosen setting, references and look);
  `phone.py` lets the phone use both. `ui/roundtable.py`: each waiting project's Needs you item
  carries its next card (`ask`, `asks`).
- `ui/static/app.js`: `askCard(ask, onAnswer, opts)` (chip, question, big options with the
  recommended first and marked, ticks and Done, Other… with a text box, number keys and Enter,
  the second "Are you sure?" card, Not now) and `answerAsk`; used on the Hall's Needs you, the
  plan page (Your input, with Answered folded away; the look card has the pictures, the Look
  section keeps the details) and the new `#/new` wizard (`viewNew`); the old form stays under
  "Or type the folder and the goal yourself". `style.css`: `.ask*` using the theme's variables.
- `remote.py`: the `answer` action (`_answer`) so phones and other machines answer the same way.
- Phone: `data/Asks.kt` (`Ask`, `AskReply`, `Asks.parse`, `fromPlan` for a hub without the
  asks file, `commandFields`, `requestBody`), `ui/AskCard.kt`, cards on Needs you
  (`NeedsList`/`TableScreen` `onAnswer`, `askNeed`) and the Plan tab (`ProjectUi.asks`,
  `ProjectActions.answer`); `Backend.asks`/`answer` (Hub: the asks file and the `answer` command,
  lists sent as JSON arrays; PC: `/api/asks`); `PlanDoc` no longer mistakes "Answers:" for the
  owner's answer.
- Tests: `tests/test_asks.py` (12); Android `AsksTest` (5), `GitHubHubTest.cardsInHubMode`,
  two new screen drawings. Screenshots in the session scratchpad (`cards-shots/`).
- Open: see plans/gaps.md (deleting cards, the wizard on the phone, look pictures on the phone).
  The app is dark only, so the wizard looks the same in a light-scheme browser.
## 2026-11-26 – Plugins

The owner asked: "Of course, a plugin system, just like DeepSeek Harness as well. So we can
add in token saving or whatever else people would want to add."

- New package `src/roundtable/plugins/`:
  - `api.py`: `API_VERSION = 1`, the `Plugin` base class (do-nothing hooks), `PluginContext`
    (settings, `data_dir` = `<app home>/plugins/<id>/`, `log`, `project_root`, `role`,
    `state`, `shared`, `emit`, `cost_of`), `HOOKS`, `PERMISSIONS` and `permission_words`.
  - `manifest.py`: `roundtable-plugin.toml` or `[tool.roundtable.plugin]` in pyproject
    (`find_manifest` looks in the folder, `src/` and one package down, where pip puts it),
    `parse_manifest` (id, name, version, description, author, licence, homepage, entry,
    api, hooks, permissions, settings schema), `check_api`, `Setting.coerce`.
  - `loader.py`: `load_object("module:object")`, now also used by `type: plugin` providers
    (`HarnessConfig._load_plugin`), so both load code the same way under the same trust rule.
  - `host.py`: `PluginHost` (built-ins first, then installed ones), `Conversation`
    (`tools`, `on_tool_result`, `before_model_call`, `after_model_call`), `notify` and
    `begin_run` for the orchestrator, `route` and `commands`. A hook that raises or returns
    the wrong type: caught, written to the plugin's `errors.log`, the plugin switched off
    until the next run, a `plugin_error` event in plain words.
  - `manage.py`: `list_plugins`, `set_enabled`, `get_settings`/`set_settings`, `add_plugin`
    (folder, git link or pip package; shows the manifest and asks first; records the
    permissions said yes to), `remove_plugin`, and `api()` for the app's `/api/plugins`.
  - `cli.py`: `roundtable plugin list|add|remove|enable|disable|settings` and
    `roundtable <plugin-id> COMMAND` (`main.py`: `plugin` command, `_plugin_command`).
  - `builtin/token_saver.py`: the token saver behind the plugin API (`TokenSaverPlugin`;
    `on_tool_result`, `tools` for `expand_output`); `builtin/cost_log.py`: the example
    (`after_model_call` writes `calls.csv`; route `GET summary`).
- `harness/agent.py` `run_agent`: new `role` and `project_root` arguments; plugin tools join
  the toolbox (never replacing one), `before_model_call` can change what is sent (the kept
  conversation isn't changed), `after_model_call` after each call, tool results go through
  `on_tool_result` with the token saver first. `harness/config.py`: `HarnessConfig.plugins`
  (state), `plugin_host()` (shared with profile variants through `_shared`),
  `merge_custom` carries `plugins:`, `_token_saver` lays `plugins: token-saver:` over
  `token_saver:`. `harness_cli._printer` prints `plugin_error`.
- Decided: installed plugins' code is kept in `<app home>/plugin-code/<id>/` and loaded from
  there (added at the end of `sys.path`, so the app's own packages win). A folder is copied
  rather than installed editable because the Windows app has no pip; a git link is cloned
  then copied; a pip package is downloaded as a wheel first (a zip, reading it runs nothing)
  so the owner sees its permissions before anything is installed. Permissions can't be
  enforced in Python: the install step says so plainly. A plugin that later asks for more
  stays off until the owner says yes again. Built-ins can be switched off, not removed.
- Docs: `docs/plugins.md` (new: using, trust, writing one step by step, hooks, ctx,
  permissions, versions), README "Plugins", the template's `plugins:` comment,
  THIRD_PARTY_NOTICES (the shape follows DeepSeek Harness's plugins; no code copied).
- Tests: `tests/test_plugins.py` (23); `tests/test_saver.py` unchanged and passing. 241 pass.
- Open: the orchestrator, the app's server and its Settings card still need their few lines
  (the hand-over lists them); a plugin catalogue and sandboxing are in plans/gaps.md.
## 2026-11-26 – Tap to answer, plugins, and a new look for Roundtable

The owner: Roundtable should ask by "pressing, rather than typing, but obviously give an option
to type"; "also do a redesign for Roundtable"; and "a plugin system, just like DeepSeek
Harness, so we can add token saving or whatever else people want".

- Merged the Google Drive backups (`backup.py`, 218 tests pass).
- Roundtable's Look step designed three looks for Roundtable itself (a hand-made plan for a
  `roundtable-ui` project in the lab: the Hall, a Needs you card answered by tapping;
  Claude Sonnet through OpenRouter, $0.15): Candlelit Oak, Ink Stamp Hall, Sea-Glass Dials.
  The owner chose **A, Candlelit Oak**; its design file is written in that lab project.
- Two jobs started in parallel worktrees with separate files: `plugins` (the plugin API, the
  token saver as the first built-in plugin, a cost-log example, `roundtable plugin …`) and
  `question-cards` (one "ask" shape for everything waiting for the owner, answer by tapping
  on the desktop and the phone, a new-project wizard of cards). The restyle follows them.

## 2026-11-26 – Backups (to Google Drive's folder)

The owner asked: "Also add support to back up settings to Google Drive, and anything else
important." For Roundtable.

- New `src/roundtable/backup.py`. One `.zip` (`roundtable-backup-<host>-<YYYY-MM-DD-HHMM>.zip`)
  with `manifest.json` (format, time, host, version, roots, every file's size and SHA-256,
  what was skipped or refused). `find_sources` finds harness.yaml, custom.yaml, hub.yaml, the
  lab, a local-only hub's data and the lab's projects; `collect` lists the files (app
  settings, `hub-path`, `phone.json`, the lab, each project's `.harness/` without spill,
  scratch and references); `make_backup` writes it, `--with-code` adds a `git bundle` per
  project (`_bundle`).
- Never keys: `secret_reason` refuses `keys.json`, the phone key, `.env` files and anything
  that looks like a key (sk-…, sk-or-v1-…, sk-ant-…, AKIA…, ghp_/github_pat_…, xox…, PEM
  private keys, a key written into a setting in a YAML/JSON file); refused files are named in
  the result and the manifest.
- Locking: `encrypt`/`decrypt`, AES-256-GCM with a scrypt key, header `RTBK` + version +
  salt + nonce (as associated data), `.zip.enc`. The passphrase is never stored
  (`remember_passphrase` keeps it in memory for the app's session).
- Where: `find_drive_folders` (drive letters D–Z with `My Drive` on Windows,
  `~/Library/CloudStorage/GoogleDrive-*/My Drive` on a Mac, `~/Google Drive`),
  `resolve_destination` (`auto` → `My Drive/Roundtable backups`, or any folder); `prune`
  keeps the newest N of this computer's regular backups and touches nothing else. Settings
  `backup: {to, keep, daily, encrypt}` live in the app's own `config/app.json`
  (`load_settings`/`save_settings`); the last backup and a short log in `backup-state.json`.
- Restore: `open_backup` (checks every file's hash), `restore_plan` and `summary` (new,
  replaces, same), `restore` asks, makes a `-before-restore` safety backup next to the file,
  clones missing projects' code from their bundle, writes the files, and points the lab's
  `projects.json` at where the projects are now. Folders are stored relative to the app
  folder or the user's home where they can be, so a restore on a new PC lands right.
- Automatic: `run_daily` (at most once a day, never during a run or plan job, never raises),
  called from `AutoSync.daily_backup` in the app's minute tick; `before_update` from
  `updater.backup_first`, just before an update installs (into the app folder's `backups/`
  when no Drive is found). Messages show in Settings → Backups and the activity feed
  (`feed_items`).
- CLI `roundtable backup now|list|restore|where|settings` (`main.py`); app routes
  `GET/POST /api/backup` (`UIApp.backup_status`, `backup_action`); the Backups card in
  Settings (`backupsCard` in `app.js`).
- Decided: a hub on GitHub isn't backed up (it's on GitHub); a hub kept only on this computer
  is. Paired phones' names and hashed tokens go in, the phone certificate and key don't, so
  phones pair again. A file with a key-looking string is left out rather than stopping the
  whole backup. Daily backups are on by default; they only run once a folder is found.
- Tests: `tests/test_backup.py` (30): round trip with two projects, code bundle, refused key
  files, the key patterns, locking and a wrong passphrase, keep-N pruning, Drive detection,
  restore asks and saves a safety backup, damaged backups, daily once a day and not during a
  job, the app tick, the updater hook, the settings routes, the command line. 218 pass.
- Open (plans/gaps.md): uploading straight to Drive (needs an OAuth client the owner makes
  once), checking code bundles for keys, a folder picker.

## 2026-11-26 – The restyle finished; the player becomes an APK and an EXE

- T16 (styling, Claude Sonnet) accepted by the owner from screenshots; T17 (tests, README,
  GLM-5.3) used its $0.50 limit before its review and was accepted after a hand check
  (396 tests pass). The restyle cost about $4.18 of real money in all.
- The owner asked for an Android APK and a Windows EXE as well as the web version: added as
  a new goal on the project (one code base wrapped twice: a Kotlin WebView app with
  WebViewAssetLoader, and Electron zipped for Windows without Wine), $1.50 real limit.
- Two gaps noted: Roundtable doesn't know the machine's build tools; big files make every
  step dear.

## 2026-11-26 – Claude through OpenRouter was paying full price on every step

The restyle's styling step (Claude Sonnet 5.5 through OpenRouter) cost $1.78 for one
attempt: about $0.12 a step, because nothing was cached. Claude only reads what it has
already seen at the cache price when the request marks it (`cache_control`); DeepSeek and
OpenAI do it by themselves, so this never showed before. The run also went past its real
limit ($1.36 against $1.08 left), because the balance was only looked at once a minute.

- `providers/openai_compat._needs_cache_marks` / `_mark_cache`: for Claude models through any
  OpenAI-style gateway, the system prompt and the newest user or tool message carry
  `cache_control`. Checked with two real calls: the second cost a twelfth of the first.
- `Orchestrator._on_charge`: the real balance is also checked as soon as a tenth of the
  run's limit has been counted since the last look.
- The yardstick lab's counted cap (`max_cost_usd`) was raised from 8 to 15: it had filled up
  with the earlier over-count; the real limit is what protects the owner.
- `Orchestrator.accept` and the remote `accept` action: the owner accepts a task's work as it
  is (used for the restyle's T15).
- Tests: `test_claude_through_a_gateway_gets_cache_marks`,
  `test_real_money_is_checked_sooner_when_spending_fast`,
  `test_owner_can_accept_a_rejected_task_as_it_is`; 188 pass.

## 2026-11-26 – Throwaway scripts no longer fail reviews

The restyle's T15 was rejected twice more ($0.78): once fairly (its new font test missed a
case), then for colour codes in `smoke-l1.mjs`, a throwaway check script an earlier attempt
left untracked in the project, although the reviewer found "the product work checks out".

- `orchestrator._worker_prompt`: throwaway scripts go in `.harness/scratch/` or are deleted;
  `Workspace.path` lets workers read and write `.harness/scratch/` (the rest of `.harness`
  stays closed); `look._is_test`: the design check ignores check scripts (`smoke*`,
  `scratch*`, `tmp-*`, `check-*`, anything under `scripts/`).
- Tests: `test_design_check_ignores_throwaway_check_scripts`,
  `test_workers_may_write_throwaway_scripts_in_harness_scratch`; 185 pass.
- The run stopped as Fable advised; waiting for the owner (plans/notes-for-owner.md).

## 2026-11-26 – The restyle stalled; Fable's advice; stronger reviews

The restyle to Record Shop Sleeve spent $1.03 and finished nothing: Flash ran out of steps,
then the reviewer (GPT-6 Luna) rejected GLM-5.3's work twice – once fairly (the favicon's
colours), once for work that was the next task's job – and the run hit its $1 limit.

- Asked Fable (the owner's rule for important things); its advice and what was done are in
  `plans/notes-for-owner.md`.
- `orchestrator._review(stronger=)`: after a rejection the next reviewer model gives the
  verdict; `_later_tasks_text`: reviewers see the tasks still to come and are told to judge
  only theirs; `_real_spent` / `_real_spend_over_limit(fraction)`: a run pauses at half its
  real-money limit when nothing has passed. Tests: `test_reviewer_is_told_what_later_tasks_will_do`,
  `test_after_a_rejection_the_next_reviewer_model_judges`,
  `test_run_stops_at_half_its_money_with_nothing_finished`; 183 pass.
- Fable's other points went to `plans/gaps.md`.

## 2026-11-26 – One restyle, not two

Choosing look A for the music player and updating the plan gave both the planner's own
restyle tasks (T15–T17) and the Look stage's "Restyle the app in the chosen look" (L1),
so the same work would be done twice.

- `lookstage._restyle_task`: no restyle task when a pending or running task already names
  the look or works on `design/tokens`; an open one is skipped. Test:
  `test_no_second_restyle_when_the_planner_already_planned_the_look`; 180 pass.
- Merged the "Make it like this" branch (references read by a scout); see its entry below.

## 2026-11-26 – Make it like this: references

The owner: "I'll make an option so that you can input ideas that already exist, and you can
make it similar to that, into my multi-agent manager." What `plans/inspiration.md` did by hand
(two projects read and turned into ideas, plus a licence decision), Roundtable now does for
any project.

- Input: `Orchestrator.start(goal, references=[...])`; `roundtable new DIR "goal" --like X`
  (repeatable, `harness_cli.py`); the app's new-project form has a "Make it like this" box
  (`viewRuns`, server `project_new` with `_lines`); later through `plan_update("reference_add",
  text=...)` / `reference_remove` (new `PLAN_ACTIONS`), the plan page's **Like these** section
  (`likeSection` in `app.js`), and the hub command for the phone (`remote.execute` takes them
  as plan edits). A reference is a link, a GitHub repository (`owner/name` or its address) or
  a description (`scout.parse_reference`).
- `harness/scout.py` (new): `check_url` (http/https only; no user names in addresses; every
  resolved address must be public: private, loopback, link-local, shared, reserved and
  IPv4-mapped ones are refused), `fetch_url` (no automatic redirects: at most 5, each
  re-checked; 2 MB; 20 s; a plain user agent; HTML to text with `html_to_text`, links kept,
  scripts dropped), `clone_repo` (`git clone --depth 1 --single-branch
  --no-recurse-submodules`, hooks and symlinks off, `.git` and any symlinks removed, 100 MB
  cap, 120 s), `untrusted` (wraps every page and repository text in `<untrusted-content>`
  with a note), `ScoutTools` (`fetch_url`, `clone_repo`, and read-only `list_files`,
  `read_file`, `search` over the copies; raw pages in `.harness/references/<id>/pages/`,
  copies in `.harness/references/<id>/repo/`), `report_schema`, `normalise_report` and
  `code_reuse_for` ("allowed with credit" only for MIT, BSD, Apache, ISC, zlib or MPL, decided
  in code whatever the model says).
- `harness/refstage.py` (new, a mixin like `lookstage.py`): `new_reference` (ids R1, R2…,
  never reused), `ReferenceStage.scout` (one run of the scout role with `submit_reference`,
  `limits.max_scout_steps` = 30; cost from the budget recorded on the reference; any failure
  recorded as `status: failed`, never raised), `_scout_pending`, `_add_reference`,
  `_remove_reference` (deletes its folder), `references_text` (the planner's "Things the owner
  wants it to be like", trimmed, with the copying rule), `_reference_looks`.
- `orchestrator.py`: `plan()` scouts unread references first and puts the reports in the
  planner's job and in `doc["references"]`; `revise_plan` scouts a newly added one before
  re-planning; `_run_with_fallback(max_steps=)`; the scout role isn't given tasks.
- `plandoc.py`: `carry_over` keeps `references`; `render_markdown` has a "Like these" section
  (`{R1}`, title, what it is, borrow, avoid, licence, code); `context_text` gives tasks and
  reviews a short form plus which references' code may be used (credited in
  `THIRD_PARTY_NOTICES.md`) or that none may.
- `lookstage._looks_job`: the references' looks go to the designer as a starting point.
- `config.py`: `scout_role` (default a chat role `scout`, else the planner), `max_scout_steps`.
- Prompts: `prompts/scout.md` (new: data never instructions, say what couldn't be read, never
  invent, similar never a copy, the licence rule); `prompts/orchestrator.md` has the rule too.
- `templates/harness.example.yaml`: a `scout` role (DeepSeek Flash, Pro as fallback) and
  `scout_role: scout`. README: "Make it like this" under The living plan.
- Tests: `tests/test_references.py` (13: scouted before planning and in the planner's prompt;
  untrusted wrapping and the scout's prompt; code reuse forced by the licence; reports kept
  across a revision, in plan.md, the context and the worker's prompt; added later, waits,
  read on revise, removed, ids not reused; a failed scout recorded while planning goes on;
  the designer gets the references' look; the hub command; the app's routes; the CLI's
  `--like`; the address check with a resolver stub; redirects re-checked, the 2 MB cap,
  HTML text, a 403, a redirect loop; parsing and clone safety). No real network or model.
  179 pass.

Decided: references wait in `project.json` until the first plan, then live in the plan
document. A failed reference isn't retried by itself (each try costs). The report's
`sources` are the addresses the tools really read, not what the model says it read.

Open (in `plans/gaps.md`): the phone's own screen for references; sites that refuse plain
readers; the address is checked before the request, not on the connection; a repository's
size is checked only after copying; no real scout run yet.

## 2026-11-26 – Switch freely, ask Fable about the big things

The owner: "You can switch freely, you don't have to ask questions, however anything super
important ask Fable and note them down so I can read it later."

- CLAUDE.md: the rule, and what counts as super important.
- `plans/notes-for-owner.md` (new): the notes the owner reads later, newest first.
- `Orchestrator._learn_after_run` (new, `improve.after_each_run`): after every run the
  improvement cycle runs with rules only (no model calls, tests or probes) and applies what
  `improve.auto_apply` allows; each switch goes in the journal as a decision with its reason
  and undo command. Test: `test_learning_after_each_run_applies_rule_backed_switches`; 166 pass.
- The lab: `improve: {after_each_run: true, auto_apply: low}`.

## 2026-11-26 – The music player is finished; the first real Look step

The owner topped up DeepSeek; the last pieces were built with the token saver on.

- The rest of crossfade (T14b, T14c), the tests (T7) and the how-to (T8) are done: all 15
  tasks, 377 of the player's own tests passing, no page errors, the library remembered
  after a reload. That run cost $0.72 of real money ($0.39 DeepSeek, $0.33 OpenRouter);
  Roundtable counted $0.69.
- DeepSeek Flash ran out of 60 steps on all four tasks; GLM-5.3 through OpenRouter (the
  fallback) finished each in 8–29 steps for $0.06–0.13. The token saver kept about 3,100
  tokens out of the conversations (the outputs here were mostly small).
- The whole yardstick so far: about $3.45 of real money for planning (five versions) and
  building a 15-task web app, including the failed attempts that led to the fixes above.
- The Look step on the finished player: the designer (Claude Sonnet 5.5 through OpenRouter,
  because Claude through Openference has no credit) made three looks – Record Shop Sleeve,
  Phosphor Deck, Riso Poster Pop – with pictures for a computer and a phone, for about
  $0.26. The pictures went to the hub (`plans/looks/music-player/`). The owner chose A,
  Record Shop Sleeve; the restyle is building.
- Open: Roundtable should notice that GLM-5.3 finishes what Flash can't and suggest it
  first; the lab's designer goes back to Openference's Claude once it has credit.

## 2026-11-26 – The token saver

The owner: "Add in a plugin for DeepSeek token saver just like the ones that exist, before
using it." The one meant is dsh-plugin-save-token 2.1.3 (MIT, Copyright (c) 2026
PlayWithAI), a DeepSeek Harness plugin. Its algorithms are ported from its `src/index.js`
as Roundtable's own module; credit and licence in the new `THIRD_PARTY_NOTICES.md`.

- `harness/saver.py`: `TokenSaver.process` runs on every tool result as it enters the
  conversation in `agent.run_agent` (new `saver=` argument), for every provider. In order:
  exempt tools (`read_file`, `expand_output`) pass through; `_dedupe` (byte-identical
  result of the same call within 90 s → a stub, original still spilled); the size
  threshold (1,400 bytes, 6,000 for error results); `build_candidate` – lossless first
  (`toon_compress`: a uniform JSON array as `name[N]{k1,k2}:` and CSV-style rows, read
  back by `toon_decode`), else `compress_json` (structural shortening), else
  `compress_lines` (table mode: head/tail rows and a stride sample with `L61:` line
  numbers; otherwise head/tail window plus up to 25 error-like lines); `passes_gate`
  (≤ 72% of the bytes, ≥ 500 bytes saved, fewer estimated tokens via `est_tokens`);
  `_spill` writes `.harness/spill/<id>.txt` atomically before anything is replaced – if
  it fails, nothing is. The notice reads `[saved-output #<id> …]` and names
  `expand_output` (`TokenSaver.expand`: the full text or a line range) and the file.
- `SaverConfig` / `HarnessConfig.token_saver`: `token_saver:` in harness.yaml (`false`
  turns it off; unknown settings are an error); the plugin's defaults; a commented
  example in `templates/harness.example.yaml`.
- `Workspace.path(read_spill=True)`: `read_file` may read `.harness/spill/`, nothing may
  write there.
- Metering: each replacement emits a `token_saver` event (tool, strategy, bytes before
  and after, `tokens_saved_est`) into events.jsonl; `AgentResult.saved_tokens_est`;
  `Orchestrator._metric` writes `saved_tokens_est` (worker plus reviewer) per attempt;
  `Project.saved_tokens_est()` sums it and `roundtable status` prints it.
- `Orchestrator._saver()`: one saver per conversation (worker, reviewer, planner, report),
  so a dedupe stub only ever points at something that model has really seen.
- Tests: `tests/test_saver.py` (14: each strategy, lossless round trip, error lines,
  pass-throughs, dedupe inside and after the window, spill failure, exemptions,
  `expand_output`, settings, and an end-to-end run where the next model call sees the
  marker and the metrics carry the saving). `test_roundtable.py`'s scripted chat brain
  now allows `expand_output` among the read-only tools. 165 pass.

Decided, and where it differs from the original:
- Prompt cache: a result is changed once, as it enters; messages already sent are never
  rewritten, so DeepSeek's (and Anthropic's) cached prefix stays the same.
- Truly lossless: the original's CSV cells turned `1` and `"1"`, `null` and `"null"`
  into the same text. Here strings that could be misread are JSON-quoted, and a bare
  array's header has no name (`[300]{…}:`), so `toon_decode` gives back equal data.
- The gate counts the notice too (the original measured the text without it), so a
  replacement is never more tokens than what it replaced.
- `L61:` numbers are the line's number in the original output, even after blank runs
  and repeats were folded (the original numbered the folded lines).
- Lines with neither pipes nor tabs no longer count as a table shape: in the original a
  plain log passed as a table and lost its error-line protection.
- Dedupe is per conversation and hashes the whole text (the original: shared across
  sessions, first 64 KB).
- Not taken: the dashboard, the `llm/stream` metering of real billed tokens (Roundtable
  already counts those), and compaction (Roundtable has none: `plans/gaps.md`).

Open: `run_command` still cuts its output at 12,000 characters before the saver sees
it, so a very long output's middle is lost before it could be spilled; with the saver on
that limit could be raised. Not yet tried in a real run.

## 2026-11-26 – The DeepSeek account ran empty: pause, don't fail

The last music player run (V4 Pro first) finished half of the crossfade task (the task
was split in two) and then hit "Insufficient Balance": the DeepSeek account is at $0.06.
That run spent $1.11 of real money although its limit was $1, because the limit was only
checked between tasks.

- `ProviderError.out_of_credit` (set on a 402 by `openai_compat`) and `agent.OutOfCredit`:
  a run remembers the providers that ran out (`Orchestrator._broke`), skips their models
  for the rest of the run, and when no model of a role is left it pauses (status
  `paused`, a "money" Needs you note) with the task back to pending and its credit errors
  dropped, instead of failing it.
- `Orchestrator._on_charge`: the real-money limit is also checked inside a long task, at
  most once a minute (`REAL_CHECK_SECONDS`), from the run's second minute.
- Tests: `test_out_of_credit_pauses_the_run_instead_of_failing_the_task`,
  `test_real_money_limit_is_checked_inside_a_long_task`; 151 pass.
- The owner's "no DeepSeek Pro for now": the lab's learned version 1 rolled back, and
  V4 Pro replaced by GLM-5.3 through OpenRouter (cheap: about $0.07 / $1.40 per million)
  in every setting.
- Open: the music player's last pieces (the rest of crossfade, tests, the how-to) wait
  for the owner: top up DeepSeek, or finish on OpenRouter.

## 2026-11-26 – The suggestion applied; learned order inside a setting

The owner: apply Roundtable's suggestion (V4 Pro codes first) and finish the music player,
"but after this don't use the DeepSeek Pro models for now".

- Applied `P44cf47` in the lab (learned version 1). It had no effect at first: the
  project's Balanced setting laid its own order over the learned one.
  `HarnessConfig.for_profile` now keeps a learned order when it only reorders that
  setting's own models (`cfg.learned`, set by `Lab.apply_learned`). Test:
  `test_learned_order_still_applies_inside_a_profile`; 149 pass.
- The last three tasks are building with V4 Pro first.
- Open: once they're done, take V4 Pro out of the lab's settings and roll the learned
  version back (the owner's "not for now").

## 2026-11-26 – Self-improvement learns from the music player: cost per finished task

The music player run paused itself at its $1 real limit ($1.19 spent, Roundtable counted
$1.22 – the count now matches the bill), with 11 of 14 tasks done. `roundtable improve
analyze` showed DeepSeek Flash finishing 7 of 17 attempts and V4 Pro 4 of 4, but made no
suggestion: the rules wanted 5 judged tries of the fallback and compared cost per attempt.

- `improve/analysis.py`: `ModelStats.cost_per_success` (failed attempts included) and a new
  rule `_rescue_proposal`: when the primary finishes half or less and the fallback finished
  at least 90% of 3 or more tries for less per finished task, propose the fallback first.
  On the music player it proposes V4 Pro first ($0.19 against $0.28 per finished task).
- Test: `test_rule_spots_a_fallback_that_keeps_rescuing_a_cheap_primary`; 148 pass.
- Open: the owner decides whether to apply it.

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
