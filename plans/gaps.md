# What the harness couldn't do yet

(Roundtable Hold is Darkness Harness from 1.0.0; older entries keep the old name.)

The owner's rule (26 November 2026): when a job meant for Roundtable needs something it
can't do, add it to Roundtable, or write it here with what happened and where it
belongs. Newest first. Move an item to "Fixed" with the commit when it's done.

## Open

- **What wave 8's phone Part B left** (28 November, wave 9 step 0): Part B (commit 4d0e2e6, on the session
  branch after 1.4.0) built words as they are written, the `/` menu, the queue, follow-ups, the new-project
  cards, the team, documents, previews and Talk. Left: the countdown and the hold while typing on a card with a
  timer, Answer these, the look's pictures on its card, the documents list, hiring from the Team screen and Talk
  through the PC. Their six routes answer the phone since step 0, each narrowed to its safe part
  (`phone.PHONE_NARROW`: a timer is only held, an agent only hired, never a PC-only card, Talk only the words
  heard), with fixtures in the conformance test. → wave 9, helper 4 (w9-phone), Part A.
- **Sound and music aren't made** (28 November, wave 9 step 0): the owner said yes, up to $2 a project, once a
  service is chosen. The seams are in (`providers/base.py` `SoundProvider`, `harness/soundprice.py`,
  `harness/soundstage.py`, a role's `kind: sound`, the estimate); the two adapters raise "not built yet"; the
  prices read on the day are in `docs/sound.md`. Which service is the owner's question 1. → wave 9, helper 1
  (w9-sound).
- **The office, other languages, local counts and traces, the iPhone page, to-dos as actions and the proof run
  are stubs** (28 November, wave 9 step 0): `office.py`, `officeart.py` (helper 2), `words.py`, `translate.py`,
  `ui/static/words.js` (helper 3), `localcounts.py`, `otel.py` (helper 5), `todoactions.py` (helper 6),
  `proofrun.py` (helper 7). Each does nothing until filled; a bare run is byte for byte as before
  (`tests/test_wave9_seam.py`). → wave 9.
- **Wave 8 untried on real machines** (27 November, 1.4.0): a real EXE's window picture (`winshot`), an
  emulator started, an APK opened and pictured; links into a task's copy on a real `node_modules` (Windows
  junctions); the editor, Open as PDF and Talk in the frozen app's window; engines installing themselves; the
  phone's runtime update and a forced bad one, import from Files, the fold; one real streamed call per
  provider (a few cents, estimate first). All beta until tried on the owner's PC and phone through Remote
  Control. → 1.4.x.
- **The stand-up has no sentence written by a model** (27 November, p1-reach): its one line is put together
  from the projects' states, with no model call (so it costs nothing); a model-written summary needs a
  priced place in autopilot's allowance first. → later.
- **Android: `androidx.window` comes from Google's Maven** (27 November, 1.4.0): the hinge needs Jetpack
  WindowManager; the cloud build fetched it through the Maven mirror init script, and an offline build with an
  empty cache can't. CI fetches it. → watch the first CI run.
- **Branch switch from the app refuses while any task is unfinished** (27 November, 1.4.0, the safety
  review): pending or running tasks, a project that says it is planning or building, or a kept task copy all
  stop it, so nothing is built on the wrong branch. Finish, skip or pause first. → by design; revisit if it
  gets in the way.

- **Learning's real cost is unmeasured** (27 November, wave 7): the weekly learning allowance ($2, the
  owner's figure) and the yardstick were only run with scripted models. One small real cycle (balance before
  and after, the real cost of one prompt test beside the guesses in DEVLOG) is the next check. → 1.3.x.
- **The frozen app's own Python and the plug-in box are untried on Windows** (27 November, wave 7):
  `--python` (pyexec.py, pytest bundled) and `--plugin-box` work through the real entry script here, the
  Windows Job Object and a boxed plug-in trying the internet only run on the owner's PC through Remote
  Control. On Windows "no internet" and "only its own folder" are held inside Python (it stops a plug-in that
  tries, not one written to break out); a kernel-level box needs Windows Sandbox or WSL. → 1.3.x, then later.
- **Search by meaning uses no maker's embeddings** (27 November, wave 7): `recall.embeddings` is read and does
  nothing; there is no embeddings call to price yet. The owner's answer (27 November): leave it off; offer it
  later as a switch with its price shown. (A PDF's text is read since 1.4.0: see Fixed.)
- **Documents and the memory picture aren't on the phone** (27 November, wave 7): the phone has What it
  learned (with Undo), and Find and Ask since Part B. The documents list (`GET /api/documents`, read only, open
  to the phone since wave 9 step 0) → wave 9, helper 4 (w9-phone).


- **"Ask me first" on the phone is wired but untried on a real phone** (26 November; re-checked 27 November):
  the phone passes `ROUNDTABLE_ASK_FIRST=1` (`RoundtableApp.kt` `askFirstEnv`), This phone's harness turns it
  into `ROUNDTABLE_GATE=all` (`onphone.py`), and the gate makes every command wait for a card (`harness/gate.py`).
  Only a check on the owner's phone through the PC remains. → wave 8 (coordinator, through Remote Control).
- **The phone and PC sync hasn't met real machines** (26 November): seats, claims, live sessions, shared
  settings, carry-on and pairing are built and tested with made-up hubs; a real PC + phone run (through
  Remote Control and USB) is the next check.

- **Owner to-dos that send them out of the app** (26 November, the owner: "I'm not supposed to ever
  leave the app; you're meant to set up everything so all my agents do it"): Roundtable still writes
  to-dos like "paste these lines into Settings > Environments", "pip install on each PC", "set the default
  branch on GitHub". Each must become an action Roundtable does itself (GitHub tools, the cloud
  environment tools, Remote Control on the PC) or a one-tap card in the app. Three such to-dos were
  dropped by hand today. → wave 9, helper 6 (w9-gaps): `todoactions.action_for` (stub in place).

- **A project run elsewhere is half-visible on the desktop** (26 November, the owner's screenshot): MSE
  Studio's plan, made in a cloud session, shows only as a "harness" to-do "the plan is ready: approve it"
  with a **done** button (which just ticks the to-do, it doesn't approve), no seat of its own, and Chat
  says "no harness run". The desktop should show every hub project as its own seat with its plan and cards
  (as the phone does in Hub mode), and an approval to-do should offer **Open the plan** / **Approve**
  (sent through the hub to wherever the project lives). Approving through the hub needs a Roundtable
  listening there (`roundtable remote --watch`); the desktop should say whether one is. → slice 2.

- **The phone has no screen for a project's settings yet** (26 November): the desktop's project page has
  it and the phone's routes serve `/api/project/settings`; the phone screen comes with slice 2.
- **This phone: only x86_64 was built and smoke-tested** (26 November); arm64 (the owner's phone) is built
  by the runtime workflow and must be tried on the phone through the PC. The runtime workflow doesn't link `previous` releases yet; Docker Hub limits can
  stop a local build (use the `BASE_IMAGE` mirror).
- **A repository's machine set-up is by hand** (26 November): MSE Studio's tests needed Qt's system
  libraries (`libegl1` and others) and its add-on repositories cloned next to it, done by hand. A project's
  `setup` can run commands, but cloning sibling repositories and system packages should be declared too.

- **The phone and the PC as one Roundtable** (owner, 26 November: "This mobile roundtable should be
  able to connect with the PC, and all sessions should be synced, etc., and everything else that is
  necessary"). Slice 2 of "This phone", right after slice 1:
  - the on-phone hub is a git copy of `agent-hub-data`, synced in the background (on start, after each
    task, every few minutes, and at once when the app opens), so projects, plans, to-dos, letters,
    journal, pictures and session logs match on both;
  - **My PC** on the phone: the PC connection (the paired phone server, hidden so far) finished,
    switched on and tested on the owner's PC, so the phone can drive the PC's Roundtable directly on
    the same Wi-Fi, no GitHub;
  - one Table showing every seat (this phone, the PC, other sessions), with who is building what; a
    project is built on one machine at a time (a claim in the hub), and either can pick up the other's
    paused run;
  - the Session and Live views of a run on either machine readable on the other;
  - settings that matter on both (limits, autopilot, profiles, keys stay per machine) synced.
  → next, after slice 1.

- **Godot: the checker hasn't met a real Godot yet** (26 November): built and tested against a stand-in;
  the first run on the owner's PC (or a session allowed to run Godot) should confirm `--import`, the Movie
  Maker frames and the error lines. No Android/HTML5 export. 1.1.0 adds playing it for a minute (a driver
  script given with `--script`, inputs from a file outside the project) and the GUT/gdUnit command
  (`godot.test_command`), also only tried against the stand-in: beta until run on the owner's PC.

- **MCP tool servers: only workers use them, and only from harness.yaml** (26 November): planning,
  asks and the run report get no MCP tools, there's no page in the app to add or check a server
  (`roundtable mcp list` only), and nothing has been tried against a real Unreal editor yet. An
  "Unreal game" kind (plans/kinds.md) would set the roles, the server and pictures of the game
  running. → release 2 (a real try on the owner's PC), kinds after.

- **Autopilot's phone switch in Hub mode waits for the PC** (26 November): the hub command is done
  by the PC's next sync (about a minute), and the phone shows the new state only after the PC has
  written `plans/autopilot.json`. → release 4.

- **The phone app's release build fails** (26 November): `./gradlew assembleRelease` stops in R8
  (code shrinking: "Compilation failed to complete"); test builds (debug) work. Fix the keep rules
  before the phone release → wave 9, helper 4 (w9-phone), Part A item 9.

- **Question cards: no "Are you sure?" for deleting** (26 November): no card deletes anything yet, so
  only spending asks twice. A card that removes something (a reference, a don't) should set
  `confirm` on its option the same way. → release 2.
- **Question cards: the phone can't run the new-project wizard** (26 November): the wizard's cards
  are served by `/api/asks?wizard=1` and work on the PC; the phone still uses its plain form in PC
  mode and has no way to start a project in Hub mode. → wave 8, p1-phone (part B).
- **Question cards: the look's pictures aren't on the phone's card** (26 November): the card names
  each look and its mood; the pictures are in the hub (`plans/looks/...`) but the phone doesn't
  load them into the card yet. → wave 8, p1-phone (part B).
- **Question cards: a reworded question loses its typed answer only in Hub mode** (26 November):
  a card answered from the phone is refused when the question changed since (its `stamp`); the
  reply says so, but the phone doesn't fetch the new card until the next refresh. → release 4.
- **Plugins from pip need Python on the computer** (26 November): the Windows app has no pip,
  so `plugin add <pip name>` needs a Python installed; folders and git links work without.
  Fetching a wheel ourselves would close it, for plugins with no compiled parts.

- **Backups can't upload to Google Drive by themselves** (26 November): backups go into
  Google Drive for desktop's folder, which then syncs them; with no Drive app, a folder of
  the owner's choosing. Sending them straight to Drive through its API needs a Google Cloud
  OAuth client the owner creates once (folder mode needs nothing). → release 3 or later,
  only if the folder isn't enough.
- **Backups: a project's code bundle isn't checked for keys** (26 November): `--with-code`
  adds a `git bundle`, which is compressed, so the key check can't read it. Only what's
  committed goes in (not `.env` files that git ignores). Unpacking the bundle to check it
  would close this.
- **Backups: no folder picker in the app** (26 November): the folder is typed (or Google
  Drive is found by itself). A Browse button needs the desktop window's file dialog.

- **(Fixed 26 November: big files come back as an outline; see Fixed.) Big files make every step dear** (26 November): the player's `js/app.js` is 188 KB, read
  in full; GLM-5.3 through OpenRouter has almost no cache discount, so each step of the tests
  task cost about 2 cents. Workers should read files in parts, and the planner should keep
  files small. → release 2.

- **The project's counted cap keeps old over-counts** (26 November): `max_cost_usd` adds up
  Roundtable's own count since the project began, including the days it was ten times too
  high, so it stops runs early. It should follow the real spend where a balance is known.
  → release 2.

- **References: the phone can't add one from its own screen yet.** The hub command works
  (`reference_add` with `text`, `reference_remove` with `id`), but Roundtable Mobile has no
  "Make it like this" box or "Like these" view. → wave 8, p1-phone (part B).
- **References: sites that refuse automated readers stay unread.** Reddit and others answer
  403 to a plain reader; the scout says so and works from the rest. A real browser (the
  Playwright the Look step uses) or the site's own API would read more. → release 2.
- **References: the address check happens before the request, not on the connection.** A
  site could answer a different address the second time it is looked up (and the
  session's proxy looks it up itself). Connecting to the checked address, or reading
  through the sandbox, closes that. → release 6 (the sandbox for commands).
- **References: a repository's size is checked after it is copied.** git can't stop a
  clone at a size, so a huge repository is downloaded (within 120 seconds) before it is
  refused and deleted. A size check through the GitHub API first would avoid that. →
  wave 9, helper 6 (w9-gaps).
- **References: a reference that couldn't be read isn't tried again by itself.** Remove
  it and add it again. No real run of the scout has been made yet (it costs credit). →
  wave 9, helper 6 (w9-gaps).
- **The estimate's defaults are guesses.** With no history it assumes 60,000 input and
  8,000 output tokens per attempt. In real money the music player's estimate was about
  right once the cost count was fixed (below), but the defaults should come from real
  runs (steps × context) and be checked after each one. → wave 9, helper 6 (w9-gaps).
- **Commands from the phone need a running Roundtable.** In a cloud session the watcher
  stops after two hours; with the desktop app closed, nothing answers. Since 1.4.0 the PC says when it last
  listened (`reach.py` `beat`, `GET /api/listening`), and the phone shows it since Part B (`data/Team.kt`
  `listening`). A hub project's seat on the desktop saying the same → wave 9, helper 6 (w9-gaps).
- **The critique can be about an older version.** It's now labelled with its version;
  the critic should look again after a revision that changes many tasks. → wave 9, helper 6 (w9-gaps).

## Fixed

- **Pictures: no editing of an earlier picture, no see-through output, spending not counted safely in
  parallel** → fixed in 1.4.0 (wave 8, p1-proof): `providers/chat_images.py` takes an earlier picture
  (`from_image`) and asks for transparency where the model can, cutting it out itself where it can't
  (`transparent`); `harness/imageprice.py` `record` writes each cost line whole under a lock, also for agents'
  faces (`agents.make_face`).
- **Pictures of Android and desktop apps** → fixed in 1.4.0 (wave 8, p1-proof; beta until tried on the owner's
  PC): an EXE's window is pictured when it starts and an empty window gets one fix task (`harness/winshot.py`,
  `shipstage._ship_smoke`); an APK is installed, opened and pictured on an emulator the harness starts and always
  stops (`harness/emulator.py`), and with no test phone a one-tap card offers to make one (PC only). The Live
  frame on the phone stays wave 9.
- **A PDF's text isn't read** → fixed in 1.4.0 (wave 8, p1-editor): `documents.pdf_text` reads it with pypdf, for
  search and the Files tab.

- **Long tasks have no compaction** → fixed (found built at the 1.4.0 re-audit, 27 November): a conversation past
  the threshold has its older steps summed up by a cheap model, keeping the task, the files changed and the last
  steps (`plugins/builtin/compactor.py`, called from `harness/agent.py` `run_agent` each step).
- **Running one task isn't in the app** → fixed (found built at the 1.4.0 re-audit): "Just the next task" on the
  project's card (`ui/static/project.js`, `run` with `max_tasks: 1`).
- **Plugins can't be held to their permissions** → fixed in 1.3.0: every installed plugin runs in its own box
  (plugins/sandbox.py); Trusted ones and built-ins run in the app. (Was: a plugin was Python running inside the app, so its permissions were what it said, not what it was allowed.)
- **No plugin catalogue** → fixed in 1.3.0: Tools → Plug-ins and skills (plugins/market.py, catalogue.json),
  pinned to exact commits, with newer versions shown; and Make one (plugins/make.py).

- **Reviews can still reject for the wrong reasons** (fixed in 1.2.0, 27 November): a rejection counts only
  when it quotes the line of the task, its done list, its don't list or the failing test output that the work
  breaks. An unquoted one is asked once more; if it still quotes nothing, a checker from another maker decides,
  and it is never turned into a pass by itself (`harness/panel.py`,
  `tests/test_panel.py::test_reviews_can_no_longer_reject_for_the_wrong_reasons`). How often a real checker
  needs asking again is only known after a real run.
- **Pictures: no size option** (fixed in 1.2.0): `size` (1K, 2K, 4K, `largest` or WIDTHxHEIGHT) goes to the
  image models (`providers/chat_images.py`, `image_config`). With no size nothing extra is sent, so existing
  pictures cost the same; agents' faces ask for a 1K square. Which models read WIDTHxHEIGHT is checked at a
  real run.
- **"Only these services" let every maker behind a service see a project** (found and fixed in 1.2.0): a
  project kept to OpenRouter could reach every company OpenRouter carries. "Only models made by these
  companies" (`makers_allowed`) now sits beside it, checked in one place (`harness/makers.py`,
  `Orchestrator._may_use`) by the router, the panel, rivals, the council, agents and the usage stage.
- **The lab's replays ignored a project's allowed lists** (found and fixed in 1.2.0): the replay copied the
  project without `.harness/project.yaml`, so it ran with no allowed list. The settings now travel with the
  copy, and a project whose lists leave a role with no model is left out (`improve/evaluate.py`).

- **Nothing proves the work runs** (fixed in 1.1.0, 27 November): every plan has a done list
  (`harness/donelist.py`, `donestage.py`); after the last task the finishing step starts the product, walks
  the list in a browser, runs its commands and files checks, and turns failures into fix tasks within two
  rounds (`finishstage.py`, `journeys.py`); apps that start with a command are started, shown and stopped
  (`appserver.py`, the App tab's Start, `ui/appapi.py`); games are played for a minute by a model that can
  see (`playtest.py`). Real browser journeys and play on Windows are beta until tried on the owner's PC.
- **A run can start above the estimate the owner saw** (fixed in 1.1.0): approval records the agreed amount
  and a run that would cost a quarter more (at least 50 cents) pauses with one card (`moneystage.py`,
  `test_a_run_can_start_above_the_estimate_the_owner_saw`).
- **Autopilot doesn't stop a run at its own limit** (fixed in 1.1.0): what's left of autopilot's money is
  written as the run's allowance and binds it (`AllowanceReached`, `test_autopilot_stops_a_run_at_its_own_limit`).
- **Autopilot can't approve a plan with pictures** (fixed in 1.1.0): picture models are priced from the
  provider's real charges or `pricing.<model>.per_image` (`imageprice.py`,
  `test_autopilot_can_approve_a_plan_with_pictures`).
- **Roundtable doesn't know what this machine can build** (fixed in 1.1.0): the planner is told exactly
  which targets this machine can build and why not the rest, and at the end the EXE, APK or mod is built,
  checked and started once (`shipstage.py`, `ship.py`). What it can't build is shown as not checked and
  never stops the project. Real builds on Windows are beta until done on the owner's PC.
- **Tasks are planned too big** (fixed in 1.1.0): plans come in stages, the first a working slice; each task
  names its files and a rough size, overlapping tasks run one after the other (`harness/stages.py`).
- **Split tasks didn't say what's left, partial work wasn't handed on, "spent with nothing finished" wasn't
  shown** (fixed in 1.1.0): a stuck task is diagnosed by another maker's model and retried, split, planned
  around or parked, with one card at the end; every split or retry gets a written handover
  (`unstick.py`, `handoff.py`); the report says what was spent with nothing finished.

- **OpenRouter cost more than it needed to** (26 November): requests now ask for the cheapest
  route, and big files are read as an outline plus the parts needed, not whole.

- **A cheap reviewer rejected good work and money went with nothing finished** (26 November):
  reviewers see the later tasks and judge only theirs; after a rejection the next reviewer
  model judges; a run stops at half its real-money limit when nothing has passed.

- **An empty account failed tasks, and a long task ran past the real-money limit**
  (26 November): out of credit now pauses the run and asks for a top-up; the limit is
  checked inside long tasks too.

- **Self-improvement missed a cheap model that mostly failed** (26 November): it compared
  cost per attempt and wanted 5 tries of the fallback. It now also compares the cost per
  finished task and spots a fallback that keeps rescuing the primary.

- **Every app looks the same** (26 November): an app with screens now gets a Look step in
  its plan – three different looks with pictures, the chosen one written as
  `design/DESIGN.md` and `design/tokens.css` that every task and review follows, a check
  for colours and fonts outside it, and never the look of another project unless asked.
- **A task too big for one attempt failed the run** (26 November): the music player's
  tasks 9 and 10 ran out of 60 steps twice each. A task whose every attempt ran out of
  steps is now split by the planner into 2–4 smaller tasks, once
  (`Orchestrator._split_if_too_big`, `limits.split_stuck_tasks`).
- **The cost count was about ten times too high** (26 November): text a model had
  already seen was charged at the full input price. Task 2 of the music player was
  counted at $0.27; the DeepSeek balance went down by about 2–3 cents. Cache hits are now
  charged at a tenth of the input price unless the pricing says otherwise, and every run
  notes the real balance at its start and end (`.harness/balance.jsonl`, the
  `real_cost` event, `roundtable balance`) for providers that report one (DeepSeek).
- **A revision forgot the owner's answers and offered turned-down ideas again**
  (26 November, `01219e3`): settled choices, answers and decided ideas stay on the page;
  a reworded copy of a turned-down idea is dropped.
- **New ideas were marked as accepted** because they reused an old idea's id
  (25 November): items are matched by wording.
- **A task that ran out of steps with no fallback model ended the run** (26 November,
  `2e1b1ba`): it now carries on once, from the files it already wrote.
