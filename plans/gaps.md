# What Roundtable couldn't do yet

The owner's rule (26 November 2026): when a job meant for Roundtable needs something it
can't do, add it to Roundtable, or write it here with what happened and where it
belongs. Newest first. Move an item to "Fixed" with the commit when it's done.

## Open

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
  the critic said so on every version of the music player plan. → release 2 (build,
  test, start, screenshot, a model that can see).
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
