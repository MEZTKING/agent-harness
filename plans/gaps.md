# What the harness couldn't do yet

(Roundtable Hold is Darkness Harness from 1.0.0; older entries keep the old name.)

The owner's rule (26 November 2026): when a job meant for Roundtable needs something it
can't do, add it to Roundtable, or write it here with what happened and where it
belongs. Newest first. Move an item to "Fixed" with the commit when it's done.

## Open

- **Pictures: no editing of an earlier picture** (27 November, the Eclipse art for 1.0.0): the image route
  (`providers/chat_images.py`, ChatImagesProvider) can only make new pictures. The ring had to be cut out of
  the backdrop by hand with Pillow. It should take an earlier picture and an instruction. → 1.1.0.
- **Pictures: no see-through output** (27 November, same job): there's no transparent background option, so
  the ring and wordmark were made on black and their transparency worked out from brightness by hand. The
  image route should ask for transparency where the model can do it, and do the cut-out itself where it
  can't. → 1.1.0.
- **Pictures: spending isn't counted safely in parallel** (27 November, same job): two pictures made at once
  overwrote each other's cost line, so the art's spending had to be added up by hand ($0.89 in all,
  `docs/art.md`). Picture spending must be counted safely when several run at once. → 1.1.0 (money).
- **Pictures: no size option** (27 November, same job): the route can't ask for a resolution, so a 16:9
  picture came back at 1280×720 and the Windows icon and phone art were scaled from it. A size (or "largest
  the model allows") should be part of the request. → 1.2.0, with every model at once.

- **"Ask me first" for commands on the phone isn't wired** (26 November): the phone stores the choice and
  passes `ROUNDTABLE_ASK_FIRST=1`, but `run_command` can't yet stop mid-task for an allow/deny card.
  → next phone slice.
- **The phone and PC sync hasn't met real machines** (26 November): seats, claims, live sessions, shared
  settings, carry-on and pairing are built and tested with made-up hubs; a real PC + phone run (through
  Remote Control and USB) is the next check.

- **Owner to-dos that send them out of the app** (26 November, the owner: "I'm not supposed to ever
  leave the app; you're meant to set up everything so all my agents do it"): Roundtable still writes
  to-dos like "paste these lines into Settings > Environments", "pip install on each PC", "set the default
  branch on GitHub". Each must become an action Roundtable does itself (GitHub tools, the cloud
  environment tools, Remote Control on the PC) or a one-tap card in the app. Three such to-dos were
  dropped by hand today. → with the rebuilt desktop app.

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
  by the runtime workflow and must be tried on the phone through the PC. "Ask me first" for commands is
  stored but not used yet. The runtime workflow doesn't link `previous` releases yet; Docker Hub limits can
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
  Maker frames and the error lines. No GUT/gdUnit test runner yet, and no Android/HTML5 export. → release 2.

- **MCP tool servers: only workers use them, and only from harness.yaml** (26 November): planning,
  asks and the run report get no MCP tools, there's no page in the app to add or check a server
  (`roundtable mcp list` only), and nothing has been tried against a real Unreal editor yet. An
  "Unreal game" kind (plans/kinds.md) would set the roles, the server and pictures of the game
  running. → release 2 (a real try on the owner's PC), kinds after.

- **Autopilot can't approve a plan with pictures** (26 November): the estimate doesn't price picture
  models (an image role's cost comes out unknown), so autopilot leaves those plans for the owner.
  Pricing pictures per image in `plandoc.estimate` would let it decide. → release 2.
- **Autopilot doesn't stop a run at its own limit** (26 November): it stops answering when the spend
  limit is reached, but a run it already started carries on within the project's own limits
  (`max_cost_usd`, the real-money limit per run). Passing autopilot's remaining money to the run as
  an extra limit would close it. → release 2.
- **Autopilot's phone switch in Hub mode waits for the PC** (26 November): the hub command is done
  by the PC's next sync (about a minute), and the phone shows the new state only after the PC has
  written `plans/autopilot.json`. → release 4.

- **The phone app's release build fails** (26 November): `./gradlew assembleRelease` stops in R8
  (code shrinking: "Compilation failed to complete"); test builds (debug) work. Fix the keep rules
  before the phone release (release 4).

- **A run can start above the estimate the owner saw** (26 November): the music player's
  packaging was estimated at $3.45 by the planner, after the owner had been told $0.50–1.50;
  nothing stopped to ask. A run should pause and ask when its plan's estimate is above the
  amount the owner agreed to. → release 2.

- **Question cards: no "Are you sure?" for deleting** (26 November): no card deletes anything yet, so
  only spending asks twice. A card that removes something (a reference, a don't) should set
  `confirm` on its option the same way. → release 2.
- **Question cards: the phone can't run the new-project wizard** (26 November): the wizard's cards
  are served by `/api/asks?wizard=1` and work on the PC; the phone still uses its plain form in PC
  mode and has no way to start a project in Hub mode. → release 4 (the phone).
- **Question cards: the look's pictures aren't on the phone's card** (26 November): the card names
  each look and its mood; the pictures are in the hub (`plans/looks/...`) but the phone doesn't
  load them into the card yet. → release 4.
- **Question cards: a reworded question loses its typed answer only in Hub mode** (26 November):
  a card answered from the phone is refused when the question changed since (its `stamp`); the
  reply says so, but the phone doesn't fetch the new card until the next refresh. → release 4.
- **Plugins can't be held to their permissions** (26 November): a plugin is Python running
  inside Roundtable, so `network`, `files` and `shell` are what it says, not what it's
  allowed. Running plugins in a separate process with no network and only their own folder
  would make them real. → release 3.
- **No plugin catalogue** (26 November): plugins are added by folder, git link or pip name.
  A list of known plugins to browse and add from the app (and a check for new versions)
  → release 3.
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

- **Roundtable doesn't know what this machine can build** (26 November): for the music
  player's APK and EXE, the build facts (where the Android SDK is, that there's no system
  Gradle, versions that work, no Wine for Windows builds) had to be written into the goal
  by hand. A project memory with the machine's tools, checked once, belongs in release 2.
- **(Fixed 26 November: big files come back as an outline; see Fixed.) Big files make every step dear** (26 November): the player's `js/app.js` is 188 KB, read
  in full; GLM-5.3 through OpenRouter has almost no cache discount, so each step of the tests
  task cost about 2 cents. Workers should read files in parts, and the planner should keep
  files small. → release 2.

- **The project's counted cap keeps old over-counts** (26 November): `max_cost_usd` adds up
  Roundtable's own count since the project began, including the days it was ten times too
  high, so it stops runs early. It should follow the real spend where a balance is known.
  → release 2.

- **Reviews can still reject for the wrong reasons** (Fable, 26 November, from the music
  player's restyle): a rejection should quote the line of the task it breaks or not count;
  tasks that split one piece of work should say what's left for the next; a model that runs
  out of steps should hand its partial work on; the run summary should show "spent with
  nothing finished". → release 2.

- **References: the phone can't add one from its own screen yet.** The hub command works
  (`reference_add` with `text`, `reference_remove` with `id`), but Roundtable Mobile has no
  "Make it like this" box or "Like these" view. → release 4.
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
  release 3.
- **References: a reference that couldn't be read isn't tried again by itself.** Remove
  it and add it again. No real run of the scout has been made yet (it costs credit). →
  release 2.
- **Long tasks have no compaction; the token saver's "compact at 120k" needs it.** The
  token saver (26 November) slims tool results as they arrive, but a long task's
  conversation still grows without limit; the plugin it comes from asks the harness to
  summarise old turns once a conversation passes about 120,000 tokens. → release 5.
- **The estimate's defaults are guesses.** With no history it assumes 60,000 input and
  8,000 output tokens per attempt. In real money the music player's estimate was about
  right once the cost count was fixed (below), but the defaults should come from real
  runs (steps × context) and be checked after each one. → release 2.
- **Nothing proves the work runs.** The coder can't open a browser and has no sample
  files, so a task's "done when" (open the page, import three songs) is never checked;
  the critic said so on every version of the music player plan. → release 2. *Partly
  done (26 November): "Show it" takes pictures of a web app's page after every approved
  task and shows them, with the app live, in the desktop app and on the phone.* Still to
  do, all release 2:
  - **A model that can see judges the pictures** (against the task's "done when" and the
    design file) and the reviewer reads its verdict; today nobody looks but the owner.
  - **Apps that start with a command** (`npm start`, `npm run dev`, a Python server): only
    their static `index.html` is shown, or nothing. Roundtable should start the command,
    wait for its port, take the pictures and stop it.
  - **Android and desktop apps**: no pictures yet (an emulator or Robolectric drawing for
    Android; a window capture for an EXE).
  - **Games**: play for a minute (a scripted input or random keys) and take pictures and a
    short clip, with the console's errors.
  - **The Live frame only works on the same computer**: the app's own server listens on
    127.0.0.1, so `roundtable ui --host` from another machine shows only the pictures.
- **Tasks are planned too big.** Splitting after the fact now works (below), but the
  planner should size tasks up front (a rough step budget each). → release 2.
- **Commands from the phone need a running Roundtable.** In a cloud session the watcher
  stops after two hours; with the desktop app closed, nothing answers. → release 3 (say
  on the phone when no Roundtable is listening, and when it last was).
- **Running one task, or until a point, isn't in the app.** `run(max_tasks=1)` exists in
  code; the app and the phone can only run everything. → release 2 (a "do one task"
  button, useful while costs are being checked).
- **The critique can be about an older version.** It's now labelled with its version;
  the critic should look again after a revision that changes many tasks. → release 2.

## Fixed

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
