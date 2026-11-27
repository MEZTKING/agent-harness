# Notes for the owner

What was decided while you were away, so you can read it later. The owner's rule (26 November
2026): switch freely without asking; anything super important goes to Fable for advice first,
and is noted here – the question, Fable's advice, and what was done. Newest first.

Roundtable's own model switches are in the hub journal as decisions ("Switched by Roundtable:
… Why: …", each with its undo command).

## 2026-11-27

- **Asked Fable: your keys, and the order to "add everything" from Munder Difflin and DSH Mobile.**
  The comparison (`plans/parity.md`) found that commands the AI helpers run could read your API keys
  (the app put them where every command could see them). *Fable's advice, taken:* fix the keys first and
  release it alone (0.9.2): commands, tests, Godot runs and tool servers get a cleaned environment with no
  keys, no hub token and no saved GitHub login, and keys stay inside the parts that call the models.
  Honest limit: a command running as you on your PC could still dig a key out of Windows' own store, so the
  full fix is the sandbox planned for later; until then risky commands wait for your tap ("Ask me first",
  next release). Then three waves, at most seven helpers each, a release after each: (1) safety and several
  tasks at once – a breaker for stuck helpers, Ask me first, 3 tasks at once (switched on in wave 2),
  notifications, schedules and GitHub issues as work, a Tools page; (2) time and memory in Watch, long-task
  summaries, Claude Code and Codex as helpers, memory and search, files and a command log, the message box
  with attachments and dictation; (3) rewind and fork, phone comfort, Wi-Fi discovery, web search for
  helpers, before/after pictures, kinds, a desktop terminal and pounds. Not building: a public tunnel,
  usage counts, an iPhone app. Later: Slack/Telegram, a phone terminal, a spoken conversation, the animated
  office, other languages. Anything needing your PC or phone is marked beta until you share a folder.
  *Done:* the key fix started (27 November); the waves follow, one release each.

## 2026-11-26

- **Asked Fable: how should the phone run Roundtable itself, "just like DSH Mobile"?** You asked
  for the phone to be the harness, so you don't wait on GitHub. Fable's advice, taken:
  - **The DSH way**: a small Linux (Debian with Python, git and Node) inside the app, run with proot,
    downloaded once and checked by signature; Roundtable runs in it on the phone and the app talks
    to it directly. Borrow DSH's runtime code (MIT, credited; the proot program itself is GPL-2,
    noted separately). Not "Python inside the APK": that has no shell or git, so it couldn't build.
  - **Our own download, built by GitHub Actions** in this repository, not DSH's (theirs has no Python).
    It's signed: the test phone app accepts a test key, clearly labelled; the official phone release
    will need a real key you add as a secret (in your to-do list).
  - **Commands have no sandbox on a phone** (Android allows none). They can't reach your photos or
    other apps, but they can change anything inside the app, keys included. You'll choose **Run it**
    or **Ask me first**; Run it is the default for builds.
  - **The hub stays in step** in the background (a normal git copy on the phone, synced when it can);
    the phone becomes its own seat, so the PC and the phone never build the same project at once.
  - **What a phone can't build**: Android APKs, Windows EXEs, Godot, Unreal, Blender – those stay on the
    PC, and the app will say so. Web apps and Python work. About 200–300 MB to download once.
  - **Also**: the PC connection (phone to PC on your Wi-Fi, no GitHub) is nearly built and is the
    quicker fix for slowness when the PC is on; it gets finished alongside.
  - **Done:** PLAN.md changed (the phone is now also a seat of its own); building in slices – first
    "This phone (beta)": set up, keys, idea → plan → approve → run with DeepSeek. Real-phone tests
    through your PC and USB once a folder is shared.

- **Asked Fable: finish the APK and EXE through Roundtable, or by hand?** The run had spent
  $1.51 with one task of four done, and I had told you $0.50–1.50 while Roundtable's planner
  said $3.45. My mistake, not Roundtable's. Fable: stop the paid run, finish the two small
  wrappers by hand (no API cost), keep Roundtable's copy script, and record the gap. **Done:**
  both built and sent; please try the APK on your phone and the EXE on Windows.

- **Asked Fable: a Roundtable that reshapes itself for each kind of software?** Fable: the goal
  is right, but not by Roundtable rewriting its own code. Use **kinds**: a recipe card per sort
  of software (roles, models, prompts, tools, **proof that it works**, build targets, the Look
  step, a template, plugins, default questions). The planner proposes a kind, you tap to
  confirm; a project can mix kinds ("a game with a website") and add extras (APK, EXE).
  First five: web app, browser game, website, the APK/EXE extras, Minecraft/Java mod. All of it,
  with the full list of kinds of software, is in **plans/kinds.md**; the self-repairing
  harness is written down in **plans/self-repair.md** for later.

- **Roundtable's new look: A, Candlelit Oak** (your choice from three looks Roundtable
  designed for itself, $0.15). The design file is ready; the restyle of the desktop app and
  the phone starts once the tap-to-answer cards are finished, because both change the same
  screens.
- **Being built now, side by side:** the plugin system (the token saver becomes the first
  plugin; anyone can add more) and tap-to-answer cards everywhere Roundtable asks you
  something (with an Other box for typing).

- **The restyle is finished** (your choices: accept step 2 from the pictures, do step 3). Step 3
  (tests and guide) used its whole $0.50 limit and stopped just before its check; the work
  itself passed 396 tests and the guide is right, so I accepted it. **The restyle cost about
  $4.18 in all**, more than the $3.45 of building the whole app; most of it went on
  Roundtable faults that are now fixed (a reviewer rejecting good work, leftover scripts,
  Claude without its cache).
- **APK and EXE** (your choice: both, web kept): building through Roundtable with a $1.50 limit.

- **The restyle went past the money you agreed.** Steps 2 and 3 were agreed at $1.50; step 2
  alone used $1.78 (Claude Sonnet through OpenRouter, one attempt). The cause: Claude was
  paying full price on every step, because Roundtable didn't mark what Claude may re-use
  through OpenRouter. Fixed and checked (the same call now costs a twelfth). I stopped there
  and spent nothing more; what step 2 made is shown in the chat.

- **The restyle stopped again, as Fable said it should.** The first restyle task was rejected
  twice more ($0.78): once for a gap in its own new tests, then – after the checker said
  "the product work checks out", 390 tests passing – because a throwaway check script left
  in the folder by an earlier attempt contained colour codes. That's Roundtable's fault, not
  the work's: workers now put throwaway scripts in `.harness/scratch/` (never committed or
  checked), and the design check ignores check scripts. The restyle has cost $1.81 so far;
  the first of its three tasks is done in the files but not accepted. **Waiting for you**,
  as Fable advised; my suggestion is in the chat.

- **Asked Fable: carry on with the music player's restyle after $1.03 was spent with nothing
  finished?** Fable: carry on once, with a tight limit, because the owner already chose the
  look and the stop was Roundtable's fault, not a change of mind. Skip the duplicate restyle
  task; undo the favicon colour change (that rejection was fair); GLM-5.3 codes the token and
  test tasks, Claude Sonnet 5.5 the visual styling; GPT-6.1 Terra reviews; $1.50 real-money
  limit, one retry per task; if a task is rejected again for another task's work, stop at
  once. **Done:** all of that, plus four Roundtable changes Fable suggested (below). With
  this run the restyle will have cost about $2.50, against $3.45 for the whole app.
- **Roundtable changes from Fable's advice:** reviewers are told which later tasks exist
  and judge only the task in front of them; after one rejection the next, stronger reviewer
  model gives the verdict; a run stops when half its money is spent with nothing finished.
  Not done yet (in plans/gaps.md): a rejection must quote the line of the task it breaks;
  split tasks say what's left for the next one; a model that runs out of steps hands its
  partial work on; "spent with nothing finished" shown in the run summary.

- **Model switches are now automatic.** Roundtable looks at every finished run and switches the
  order of models when the numbers clearly say so (for example a cheap model that keeps running
  out of steps while its backup finishes the job for less). Each switch is written in the
  journal with the reason and how to undo it. Settings: `improve: {after_each_run: true,
  auto_apply: low}` in harness.yaml.
