# Notes for the owner

What was decided while you were away, so you can read it later. The owner's rule (26 November
2026): switch freely without asking; anything super important goes to Fable for advice first,
and is noted here – the question, Fable's advice, and what was done. Newest first.

The harness's own model switches are in the hub journal as decisions ("Switched by the harness:
… Why: …", each with its undo command; older ones say "Switched by Roundtable:").


## 28 November 2026 – a chat in place of Letters, the DeepSeek key on the phone, and six letters already read

**The chat (your answers):** yes, build it. Each project gets a chat, and the Hall one for everything, on the PC
and the phone, in place of Letters; the answer writes itself out as it comes. It answers with DeepSeek V4 Flash
(never V4 Pro), about a tenth of a cent a message, with a limit of **$1 a day** (your figure, not the 50¢
suggested) that you can raise for the day with one confirmed tap. History and pictures are kept in your private
hub. Anything that spends or can't be undone is a card with its price and two buttons. Old letters stay, read
only, under "Earlier messages"; the Letters screens go. You drive the music player's five accepted ideas through
the chat (at most $2) before 1.5.0 is released. It comes in this release, after wave 9's merge.

**The question for Fable:** is it safe for the phone to keep a DeepSeek key, so it can answer when no computer is on?
**Fable's advice:** "The phone can safely keep a DeepSeek key, locked the same way as your GitHub token, and nothing
it reads can spend money or change anything without your tap. Because the phone's $1-a-day limit is only the
app's own count, keep a small balance on a DeepSeek account used just for this, and delete that key on DeepSeek's
site if you lose the phone." Your answer: yes.
**What the builders must do (Fable's list, all of it):**
1. Nothing of the app's goes to Google's cloud backup or a device transfer (with a test): the runtime folder,
   drafts and the local copy of the chat included.
2. The key only in the phone's locked store (Android's keystore, AES-256-GCM); a test that no hub write, log line,
   error, crash report or route ever holds it. The box shows only its last four characters, never copies it,
   has a Remove key button, and copies it to This phone's key form only on a tap.
3. Only `api.deepseek.com`, no redirects followed, no network logging in release builds.
4. The $1 a day reserved before each call; "Raise it for today" is a confirmed tap.
5. The model fixed to DeepSeek V4 Flash; anything like V4 Pro refused, with a test.
6. Anything that looks like a key or a password (sk-…, GitHub keys, private keys, .env lines) taken out before each
   DeepSeek call and before each hub write, and you are told in the box when that happened. Other projects'
   contents are never sent (the Hall gets one line per project), nor secret files, nor more about your machines
   than a name and when it last listened.
7. A card's title, price and command come from the app, never from the model's words; a card only answers a
   message typed on that device; nothing "free and undoable" runs by itself when the conversation held an agent's
   or a web page's words; every spend needs a tap. Lines not typed on the device are not trusted, even if they
   say they are from you.
8. No pictures or links from a model's answer are loaded; your pictures lose their location data; at most 1.5 MB a
   picture, with totals per chat and per day; old months folded.
9. `docs/phone-security.md` says it plainly, with the lost-phone steps (delete the DeepSeek key on DeepSeek's site
   as well as the GitHub key). Also written down in `plans/gaps.md`: a `roundtable:` command in the hub isn't yet
   checked to come from a tap, so anyone who could write to the hub could forge one.
**What was done:** the plan and the list are with the builders; `docs/phone-security.md` has the key's section and
the lost-phone step; the forged-command gap is in `plans/gaps.md`. **Built (28 November, the chat merged):** all
nine items are in the code and tested (backups and device transfer off with a test; the key only in the locked
store; only `api.deepseek.com`; the $1 a day reserved first; V4 Pro refused; secrets taken out before DeepSeek and
the hub; cards made by the app and only for this device's own message; no remote pictures or links; the security
page with what goes to DeepSeek and the three lost-phone steps). The forged-request gap is still open (a signed
request would close it), written in `plans/gaps.md`; what the chat adds is that a cancelled card's request is
skipped by every machine.

**Six of the music player's letters were read before the stop reached the helper.** While wave 9 was being built,
the helper working on Letters processed six of the eight letters you had sent about the music player before your
hold reached it: it marked them read, sent six short receipts, wrote your answer to its question (yes) and the five
ideas you accepted (I1 to I5) as changes waiting on the plan (the plan is still version 2, not revised), and
republished the plan's page ("paused · 1 of 4 tasks done"). **You chose to keep them.** Nothing was built and
nothing was spent on them (the DeepSeek balance was $3.65 before and after; the helper's own test calls came to
well under a cent). The changes wait for you to drive them through the new chat.

## 28 November 2026 – what 1.5 will spend, and your three answers

**Question:** which sound service, may the test build spend money, and may the app be translated?
**Fable's advice:** ElevenLabs for sound (better and far cheaper per effect; about $5 a month), with Stable Audio kept as the no-subscription choice; a real test build of a small game on the cheap DeepSeek model, up to $3; eleven machine-translated languages, labelled as such, about $1 once. The whole of 1.5 spends at most about $14.60 (likely about $7), plus the ElevenLabs plan.
**Your answers:** ElevenLabs; yes to the test build up to $3; yes to eleven languages.
**What was done:** 1.5's groundwork is merged and seven parts are being built. Nothing is spent until each part is merged and priced first. The office art waits for you to approve a sample sheet.

## 2026-11-27

- **Wave 8 (1.4.0): are saving files from the app, switching branch, the local hook and shared folders safe?**
  Asked Fable before release. *Advice, in short:* yes, with six fixes – never write through a link or into the
  harness's own files; check the file a put-back names; never switch branch while anything at all is working
  on the project or the hub can't be read; what comes from outside never starts building by itself; a hook
  only ever answers this computer, the same way for a wrong secret as for no hook, and never on the phone; and
  an install in a task's copy gets its own folders instead of writing into the project's. *Done, each with a
  test (`tests/test_wave8_safety.py`):*
  1. Saving and Undo refuse a file that is a link, or whose real place is hidden (`.git`, `.harness`, a
     dot-file) or looks like a key (`ui/filesapi.py` `writable_file`, used by `ui/editapi.py`).
  2. Putting a hand edit back checks the file named in the commit the same way (`harness/gitview.py`
     `undo_edit`).
  3. A branch switch waits while the project says it is planning or building, while tasks are unfinished and
     while task copies are kept, not only for this app's own jobs; and "another computer?" counts as "can't
     tell" when the hub can't be read (`ui/editapi.py` `_checkout_block`, `ui/rewindapi.py` `elsewhere`).
  4. A local hook, GitHub events and a watched address never start building by themselves: their plan always
     waits for your OK, and the tick-box is gone for them (`automation.py`, `ui/reachapi.py`,
     `ui/static/automation.js`).
  5. A hook is read on the desktop only, from the connection's own address (never a forwarded header), with
     one answer for "no such hook" and "wrong secret"; the phone server never serves one (`ui/server.py`,
     `reach.py`, `phone.py`). The secret is shown once and kept only as a hash, never on a page.
  6. An install (npm, pnpm, yarn, pip, uv, poetry, Gradle, Godot) in a task's copy whose folders are shared with
     the project first takes the link away, so the copy gets its own; then it goes through your usual
     approval (`harness/perms.py` `own_copy_first`). A task copy that still holds a link out of it is never
     removed (`harness/worktrees.py` `links_out`).
  Also checked: the phone may never save, undo, edit a file or switch branch.

- **Your answers for wave 9 (asked in the chat):** sound and music – yes, capped at $2 a project (Fable first
  compares two services on price and on whether you own what they make, then you pick one; until then sounds
  are made in code); Telegram or Slack – no; the animated office view – yes, up to $10 of our own pixel art
  (quoted first, you approve the sheet); a public tunnel into your PC – no.
- **Fable's advice followed without asking** (no money, nothing opened up): usage counts stay on your
  computer; OpenTelemetry only on your computer; on an iPhone the phone screens open as a page on your own
  Wi-Fi, through the paired link, not a real app; no command line into the PC from the phone; a running
  app's frame on the phone is view-only through the paired link; a maker's live voice and paid search stay off.
- **The two forks were re-read:** both are at the versions the parity list used; their newest notes add a
  Browser tab (DSH), keeping your place when the screen width changes (DSH) and task numbers on cards (MD) –
  added to wave 8.

- **Wave 7 (1.3.0, "it learns"): you chose a learning allowance of $2 a week.** It counts inside your daily
  limit, shows as its own line ("Learning: $0.42 of $2 this week"), unused money doesn't roll over, and you
  can change it any time. The first real cycle writes its true cost beside this figure.
- **Fable's advice on the rest, followed:**
  - *What it may change by itself:* model order and small option changes that passed a test. Builder
    instructions wait for your tap until three watched changes have been kept, then you're asked once.
    The reviewer's and planner's instructions, tools, kind tweaks and any new company always wait for you.
  - *Automatic undo:* always on. After a change, the next tasks are compared with before; a clear drop (a
    fifth less work passed, at least five tasks seen) undoes it, tells you in one line and offers "Put it
    back". A change it undid is never applied by itself again.
  - *Plug-ins in a box:* every installed plug-in runs boxed (no keys, no internet, only its own folder)
    unless you tap "Trusted" for one you wrote. On Windows the box is partly enforced inside Python, so a
    plug-in written on purpose to break out could; the in-app list only holds plug-ins we have read, pinned
    to a version.
  - *Learning shared between your machines* through the private hub: numbers, model names and scrubbed
    instruction text only – never project names, code, file names, task titles or checkers' words.
  - *A privacy hole found and fixed:* the analyst saw rejection text from every project; now only from
    projects that allow its company.
  - *Fixes to its own code:* asked first each time with the price (up to $1.50), a draft pull request only,
    never merged by itself, never touching the gate, keys, money, companies, the rules or the release files.
  - *Your own documents:* agents can look them up within each project's "who may see it" lists, with a
    "Never leaves this computer" tick. *Search by meaning* runs on your computer, free.
  - *Skills list:* about ten of our own; others' only where the licence is open, with credit.
  - *Nothing deletes;* the fixed safety lines add about 150 tokens to each model call.
- **1.2.0 ("every model at once") merged and releasing;** the six starter faces cost $0.40.

- **Wave 6 (1.2.0, "every model at once"): Fable's advice on its big questions, followed.**
  - *How much extra checking costs:* three levels – Lean (as today), Balanced (the default: a second
    builder on hard tasks and a second checker on hard and risky ones, about a fifth more, capped near a
    third more), Maximum (only by your own tap per project: about two to two and a half times, with both
    prices shown before you confirm). Extra checking gets its own share of the agreed money and falls back
    to the usual way when that is used. Autopilot never changes the level.
  - *Maximum's planning* (three planners and a chair) costs about three and a half times today's planning:
    shown where you choose Maximum, capped at $1.50 a plan.
  - *Trying models nobody has used yet:* easy tasks only, at most one task in ten and 50 cents a goal, only
    priced models no dearer than 1.5 times the usual one, with the usual model behind each try.
  - *Privacy – more companies see each project:* a new setting "Only models made by these companies",
    honoured by everything; two holes fixed now ("only these services" didn't limit the companies behind
    OpenRouter; replay tests ignored a project's list). Each project shows "Who has seen this project".
  - *Faces for named agents:* six starter faces from the picture model, capped at $3 in all.
  - *An agent's memory crosses projects:* on for ordinary projects, off for projects with an allowed list
    or your own repositories unless you switch it on there. An agent file from someone else: files only,
    text and pictures, its notes shown in full before you confirm, model choices never imported.
  - *A checker from the same company as the builder:* a warning, not a refusal (an all-DeepSeek set-up
    must still work). *A rejection that quotes nothing:* asked once to quote the line, then a second
    company decides; never turned into a pass by itself.
  - *Wording:* the model sets and the checking level are always labelled ("Models: Balanced · Checking:
    Balanced"). *Nothing deletes:* attempts not chosen keep their branch and a small patch; the Tidy page
    lists them with a Clear button only you press.

- **Darkness Harness 1.1.0 is put together and ready** (not released yet): the done list, stages, trying what
  it built and fixing what breaks, stuck tasks worked out, money limits, play-testing and real builds. Small
  choices made for you while putting it together, all reversible:
  - something this computer can't build (an EXE on a computer that isn't Windows, a mod with no Java) is shown
    as "not checked here" with the reason and never stops the project being called done;
  - the "check it works and fix" step only spends money fixing things on the list that must work, never a
    nice-to-have;
  - approving a project before it has a plan agrees no amount, so the "this will cost more" card only uses an
    estimate you actually saw;
  - "an Android app" on its own still means your web app wrapped as an APK; the new native Android kind is
    picked when you say "native Android", "Kotlin" or "Jetpack Compose".
- **Darkness Harness 1.0.0 is put together and ready** (not released yet). Roundtable Hold becomes
  Darkness Harness in the Eclipse look you picked, on the PC and the phone; your data, keys, hub, projects
  folder and phone pairing stay exactly where they are. Small choices made for you, all reversible:
  - the hidden settings folder `~/.roundtable` keeps its name (several parts read it; renaming one would
    split your settings);
  - the old `RoundtableHold.exe` stays as a tiny starter that opens the new app, so a taskbar pin you made
    keeps working; it goes in 1.2.0;
  - on Home the project lights now sit exactly on the painted ring; with no projects there's one eclipse,
    not two; in Ash (the light theme) the ring is drawn and the name typed, because the painted art is made
    for dark backgrounds;
  - the phone's eclipse picture is a little softer, so the drawn ring stands out.
- **Wave 5 (1.1.0, "finished, not just built"): Fable's advice on its big questions, followed.**
  - *Fixing things past the amount you approved:* yes, within limits it can't change itself – up to 25%
    over what you agreed (never less than 50 cents of room), at most two "check it works and fix" rounds
    and eight added tasks per goal, then it stops with one card. The estimate you approve already shows
    a line for checking and fixing. Autopilot never raises this and never chooses "accept as it is".
  - *Build and start commands that come with a kind of project:* built-in ones follow the usual command
    rules; one from a kind you imported asks you first, once per project, showing the exact command.
    Nothing is ever signed with a real key, installed on your phone, uploaded or published without you.
  - *Play-testing a game shows its pictures to a model that can see:* same service and rules as the
    proof pictures; games only, at most about 30 cents a play, counted in the estimate.
  - *Nothing in this wave deletes:* work planned around is kept in a file; play pictures are tidied
    like the other app pictures. **Your call later:** keep play pictures for ever?
  - *Your words stay yours:* your idea is tidied into a brief for the planner, but your own words stay
    the goal, on top; anything the brief adds is an idea you accept or not.
  - *Not yet:* sound and music need a new paid service and key – asked when the first game needs it.
- **The upgrade check passed first time:** GitHub installed Roundtable Hold, upgraded it to Darkness
  Harness, and found nothing lost (data, a saved key, shortcuts; an old taskbar pin still opens it).
- **The three looks were drawn** (samples, $0.20 in total): Eclipse, Obsidian Forge, Abyss. Waiting for
  your pick; the art budget (up to $15) and keeping the phone app the same underneath are agreed.

- **Darkness Harness: Fable's plan, followed.** Built on Roundtable; 1.0.0 is the new name and look
  only (your installed app updates into it; projects, keys, phone pairing and hub kept, nothing moved or
  deleted; a test on GitHub upgrades the old app before it ships). Then 1.1 finished apps and games,
  1.2 every model at once, 1.3 it improves itself, 1.4 and 1.5 everything else the other harnesses do.
  Names machines read stay as they are (the `roundtable` command, the data folder, the phone app's id), so
  nothing breaks. **Name check:** no app called "Darkness Harness" was found; a software company called
  Harness exists (different name). **Waiting for you:** the look (Eclipse, Obsidian Forge or Abyss), the
  art budget (up to $15 suggested) and keeping the phone app the same underneath (recommended, assumed
  until you say otherwise).

- **Asked Fable about wave 3's big questions (0.12.0).** Fable's advice, followed as given:
  - *Web search for builders* sends their search words to a search service: on for builders and the
    planner, at most 6 searches a task, anything that looks like a key removed first, off for projects
    limited to named services. It starts with the free engine; a paid one only if results are poor
    (its key goes through the app's key form).
  - *Undo a task / go back*: never deletes. A way back ("Put it back") is kept for 30 days, then the
    daily tidy-up may clear it. Never offered for work already sent to GitHub. **Your call later:
    30 days, or keep for ever?** (30 days for now.)
  - *Before-and-after proof*: a model that can see looks at the pictures, at most 5 cents a task,
    counted in the estimate you approve, and only as advice to the reviewer – it can't turn good
    work down by itself.
  - *Pounds*: "≈ £" beside dollars in four places. One request a day to the European Central Bank's
    public rates file (nothing about you in it). The bills stay in dollars.
  - *A command line in the desktop app*: desktop only, never from the phone, refused if the app is
    opened to the network, keys kept out. The phone only sees a task's command output and a Stop.
  - *The PC answering "who's there?" on Wi-Fi*: only when asked, private networks only, never the
    pairing code. The QR code stays the recommended first pairing; a typed code is checked against
    the PC's certificate before it's sent.
  - *Kinds of project*: a kind's "proven" badge is earned by a real build, never claimed; kinds from a
    file are yours alone (no public catalogue); a project's kind is fixed once you approve the plan.
    The gallery is private and never deletes.
  - *Left out on purpose*: a plug-in market (plug-ins can't yet be held to their permissions), a
    phone command line and spoken conversation.

- **Asked Fable: is it safe for Roundtable to tidy up old files by itself?** A helper built a daily tidy-up
  (old logs, old pictures, leftover working copies, old run records) so the disk doesn't fill. *Fable's
  advice, taken:* on by default, but only for things that can be rebuilt or are kept elsewhere. Files you
  send (photos, attachments) are never removed automatically; a project's history is packed into a small
  archive rather than cut, so old tasks stay visible and backed up; a task's working copy is removed only
  once that task is truly finished, never while a project is paused. You'll see one line in Activity when
  something was tidied, and a switch in Settings → Advanced with "Show what would be removed". *Done:* the
  helper is making those changes before it's merged (wave 2).

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
