<!-- The README's "What's new" sections, bundled with the app for its "What's new" card. Written by `python -m roundtable.updater --whatsnew-bundle`; edit the README instead. -->

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

### What's new in 0.9.1

- **Short first, details on request**: every plan has a short title and one sentence of where it
  stands; below it only what waits for you and the tasks, one line each; everything else folds under
  "More about this plan". Status, seat cards and Letters are shorter too.
- **Live on finished projects** shows the final pictures, or a **Take pictures now** button.
- **My notes** shows the documents kept in your hub (like your list of links), readable in the app.

### What's new in 0.9.0

- **A new desktop app**, rebuilt from scratch: the Hall shows every project as a seat with its own name
  and what it's doing in words; **Needs you** comes first and is answered with one tap; each project
  has Overview, Plan, Watch, App, Journal and Settings; **Models** lets you choose who does every job
  from a list; Settings covers keys (with a Test that really checks them), the recommended setup,
  spending, the hub, your phone, backups, plugins and updates – nothing sends you out of the app.
- **The phone and the PC as one Roundtable**: the phone is a seat of its own; one machine builds a
  project at a time; watch a build on either; spending limits, autopilot and who does which job are
  shared; "carry on" goes to the machine that has the project; pair the phone with the PC by QR code.
- **Claude Opus 5.5 codes by default** (medium effort), with DeepSeek V4 Flash as its backup.
- **Fixes**: keys for OpenRouter and Openference load at start; DeepSeek V4 Pro is switched to Flash;
  the hub's project list stays up to date on every computer.

### What's new in 0.8.0

- **Your existing apps** (first part of "your repositories"): point Roundtable at one of your apps'
  folders and it works on its own branch, follows the app's own CLAUDE.md, runs the app's tests
  before and after every change (a newly broken test sends the change back) and never pushes. Each
  project has a settings file (`.harness/project.yaml`, or `roundtable.yaml` in the app itself) you can
  change from the project page on the desktop or the phone. How: [docs/repositories.md](docs/repositories.md).
- **The phone, in plain words**: questions and ideas can always be tapped and answered on the card;
  Needs you is grouped by project and by what's most urgent; letters read as sentences; Roundtable's
  "done" receipts no longer count as needing you; Mark all read.
- **The phone updates itself**: Settings → About shows a new version with **Download and install**,
  and a banner on the Table.
- **This phone (beta)**: Roundtable can run on the phone itself, in a small Linux inside the app (the
  way DSH Mobile does), with no computer and no GitHub. Set up from the connect screen; about 100 MB to
  download once. First slice: set up, a DeepSeek key, idea → plan → approve → build. Syncing with the
  PC and the hub comes next.

### What's new in 0.7.3

- **Godot games**: after every approved task Roundtable starts a Godot 4 game itself (no editor
  needed), lists its script errors and takes three pictures of it running; the coder and reviewer
  get a **run_game** tool to test their own work. Godot and Blender can also be driven through
  their MCP plug-ins. How: [docs/godot.md](docs/godot.md).
