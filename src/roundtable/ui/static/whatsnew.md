<!-- The README's "What's new" sections, bundled with the app for its "What's new" card. Written by `python -m roundtable.updater --whatsnew-bundle`; edit the README instead. -->

### What's new in 1.1.0

Finished, not just built: the harness now checks the thing works before it calls it done.

- **"Done when"**: every plan has a short list of what you can do with the finished thing ("You can start a
  game, lose and start again"). It isn't called finished while one of them fails. Add your own lines on the
  plan page.
- **It tries what it built**: at the end it starts the app, uses it as a person would, and turns what's
  broken into fix tasks, at most two rounds. Only then does it ask you, with one card: try fixing again,
  accept it as it is, or stop.
- **Stages**: plans start with a small slice that already works, then build on it. Each task says which files
  it changes, so two tasks never fight over the same file.
- **Stuck tasks are worked out**: a model from another maker looks at why a task keeps failing and retries
  it with advice, splits it, plans around it or puts it aside. You get one card at the end, not one per task.
- **No surprises with money**: a run that would cost well past what you agreed (a quarter more, at least
  50 cents) stops and asks. Autopilot's spending limit now binds the runs it starts. Picture models get a
  price in the estimate, and the estimate shows the cost of checking and fixing.
- **The App tab can start an app** that runs with a command (Start it, Stop it), on this PC only.
- **Games are played**: a model that can see plays a browser game for a minute and says what broke.
- **New kinds**: Godot games and native Android apps (on trial); Java mods move to trial. An EXE, APK or mod
  is really built at the end, checked and started once. What this computer can't build is shown as not
  checked, with the reason, and never stops the project.
- **Beta until tried on your PC**: playing a real Godot game, building a real EXE, APK or mod, and walking an
  app in a real browser on Windows have only run against stand-ins so far.

### What's new in 1.0.0

Roundtable Hold is now Darkness Harness. Everything you have stays.

- **A new name**: Darkness Harness on the PC, Darkness on the phone. Your projects, keys, hub, settings and
  phone pairing are kept exactly where they were.
- **A new look, Eclipse**: Home is a ring of lights round an eclipse, one light for each project; the one
  that needs you flares orange. Three themes under **Settings → Look**: Eclipse, Pitch (true black) and
  Ash (light). New letters (Space Grotesk, Inter and JetBrains Mono) and new art, icon and emblem.
- **A taskbar pin you made yourself keeps working**: the old app file now just opens the new one.
- **The phone through the firewall**: after this silent update, Windows may ask once to let the phone reach
  the PC. Press **Yes**. It only asks on PCs that had the old firewall rules.
- **The phone app updates in place** and stays paired: same app, new name and look.
- **Windows SmartScreen may ask again** ("Windows protected your PC"), because the app's file name changed.
  Click **More info → Run anyway**, as before.

### What's new in 0.12.0

- **Kinds**: Roundtable knows what sort of thing you're making – a website, a web app, a browser game or
  something else – and plans, builds and checks it to suit. The plan's first card asks "This looks like a
  website. Right?"; the choice is fixed once you approve.
- **Gallery** (new tab, and on the phone): everything finished, with its pictures and checks, and what
  Roundtable can make. Hiding never deletes; "Make another like this" starts a new one.
- **Proof for every task**: pictures before and after, the tests before and after, and one line from a
  model that can see (advice for the reviewer, at most 5 cents a task, counted in the estimate).
- **Undo a task**: see the files first, then undo it or go back to before it; "Put it back" undoes the undo
  for 30 days. **Try another way** makes a separate copy from any task. Never for work already on GitHub.
- **Web search for builders**: they can look up real documentation instead of guessing (6 searches a task
  at most; off for projects kept to some providers). Switch and engine on the Tools page.
- **Command line** (a project's new tab, this PC only): type commands in its folder. A task's command
  shows as it prints, with a Stop for that one command.
- **Pounds**: costs also show as "≈ £" beside the dollars (Settings → Spending; the bank's daily rate).
- **Phone comfort** (beta until tried on your phone): accent colour, true black, text size, buzz, pinned
  and put-away projects, what you sent, how much Watch shows, a battery checklist, and two panes on a
  tablet or an open foldable.
- **The phone finds your PC on the Wi-Fi** (beta until tried at home): "Look for my PC" when pairing, and
  "Look for it" when the PC's address changed. The installer lets the phone in on private networks only.

### What's new in 0.11.0

- **Several tasks at once is on**: new setups run up to three tasks side by side (`limits.max_parallel: 3`).
- **Memory**: Roundtable remembers what worked, what you turned down and your answers, and tells the planner
  and the builders next time.
- **Search** (the box at the top, and on the phone): plans, tasks, the journal and letters in one place.
- **Files**: see a project's files – pictures, PDFs, text – on the desktop and the phone.
- **The message box**: add pictures and files when you talk to the planner, add a goal or start a new
  idea; drafts are kept, and you can speak instead of typing.
- **Coding helpers on your PC** (Claude Code and similar) can be a role's model, like any other service.
- **Long tasks keep their head**: when a helper's conversation grows too long it is summed up, so it
  carries on instead of failing.
- **Watch shows timings**: how long each step and each wait took, and the tokens used.
- **Tidy-up**: old logs and copies are cleared once a day (Settings → Advanced); **What's new** shows after
  an update.

### What's new in 0.10.0

- **A safety switch for stuck helpers**: the same step over and over, error after error, huge output, too
  many tokens or no progress – Roundtable warns the helper, then blocks it for a step, then stops the task
  (`breaker:` in harness.yaml). Every step records how long it took.
- **Ask me first**: risky commands (deleting outside the project, sending code to GitHub, installing from
  the internet, administrator rights…) wait for your tap – Allow once, Always allow in this project, or
  Don't allow – on the desktop, the phone and through the hub. "all" asks for every command; "off" never.
- **Several tasks at once** (`limits.max_parallel`, default still 1; wave 2 turns it to 3): each task in
  its own copy of the project, merged back in order; a clash becomes a small fix-up task.
- **Notifications**: finished, needs you, failed, money, idle – never twice; answer buttons on the phone's
  notifications; a bell and pop-ups on the desktop (Settings → Notifications).
- **Automations** (Settings → Automations): schedules, GitHub issues with a label, failed checks – they
  plan by themselves and build only with your OK (or within a spending limit you set).
- **Tools** (new tab): what this computer has for building – Git, Node, Python, Godot, Unreal, Blender,
  Claude Code… – with Install buttons, and the tool servers (Unreal, Godot, Blender) your helpers use.

### What's new in 0.9.2

- **Your keys are kept away from the AI helpers' commands**: anything a helper runs (commands, tests,
  Godot, tool servers) gets a cleaned environment with no API keys, no hub token and no saved GitHub
  login; keys live only inside the parts of Roundtable that call the AI services. A command still runs
  as you, so the full protection (a sandbox) comes later; "Ask me first" comes next.
