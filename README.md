# Roundtable Hold

**The best AI models, working together, on all your projects.**

Every job goes to the model that's best at it: Claude for orchestration and review, DeepSeek for code, Retro Diffusion for pixel art, or any provider you like. Agents in different repos share what they're building, and every project keeps a journal, so you (and every session) always know where things stand. The system also tests, learns and improves which model does what.

```bash
pip install "git+https://github.com/MEZTKING/agent-harness"
roundtable init            # starter hub.yaml + harness.yaml
roundtable probe           # check every model works (and record its baseline)
roundtable where           # where was I? across all projects
roundtable new mygame "A pixel-art platformer in the browser" --approve
roundtable ui              # the same, in a web UI
```

### Windows app (easiest)

1. Download **`RoundtableHold-Setup-<version>.exe`** from the [Releases page](https://github.com/MEZTKING/agent-harness/releases/latest).
2. Run it. It installs for your user only (no admin needed), with a Start-menu entry and a desktop icon. If Windows SmartScreen says "Windows protected your PC", click **More info → Run anyway**. The app isn't code-signed yet, which is why it asks.
3. Roundtable Hold opens in its own window with a **setup** screen:
   - paste your API keys (saved in Windows Credential Manager);
   - optionally connect your `agent-hub-data` repo for sync (needs [Git for Windows](https://git-scm.com/download/win));
   - click **Start**.
4. Everything can be changed later under **Settings**: keys, the hub, which model does which role, prices and limits.

The app's look is **Candlelit Oak**: a warm oak hall where the seat that needs you is lit by a candle. It follows your computer's light or dark setting; pick one under **Settings → Look**.

The app tells you when a new version is out (**Settings → Updates**, or the banner) and installs it for you. Your data lives in `%APPDATA%\RoundtableHold` and is kept if you uninstall.

### What's new in 0.7.2

- **Tool servers (MCP) for your roles**: a role can use the tools of any MCP server, such as the
  Unreal Engine editor's own (Unreal 5.8 and later), so models can build Blueprints, levels and
  assets in the open editor. Add the server under `mcp_servers:` in `harness.yaml`, give it to a role
  with `mcp: [name]`, and check it with `roundtable mcp list`. How: [docs/mcp.md](docs/mcp.md);
  making a game in Unreal: [docs/unreal.md](docs/unreal.md).

### What's new in 0.7.1

- **See what's being made**: after every approved task Roundtable starts the app and takes pictures
  (computer, phone, dark); each project page has a **Live** tab (the app itself, running) and a
  **Session** tab that reads like a Claude Code session (every step, with the changes in colour and
  the outputs, pictures and files shown as they are); the Hall's seats show the app's picture; the
  phone has a Live tab too.
- **The phone app on every release**: the releases page now has `RoundtableMobile-<version>-test.apk`
  next to the Windows installer (a test build; it installs over the previous one).
- **Phone fix**: Roundtable Mobile no longer closes on start (Android's text-pattern engine); if it
  ever crashes again it opens in safe mode with "Send the details to my PC".

### What's new in 0.7.0

- **Answer by tapping**: everything Roundtable asks you is a card with ready answers (the
  recommended one first) and an Other box; a new-project wizard of cards.
- **A new look, Candlelit Oak**: the Hall round a painted table, light and dark.
- **A look of its own for every app you make** (the Look step), **"Make it like this"**
  (links and repos read by a scout), **plugins** (the token saver is the first),
  **backups** to Google Drive's folder, **picture models** (GPT Image, Nano Banana).
- **Budget / Balanced / Quality** per project, **OpenRouter** and **Openference**, exact costs
  and real balances, and many savings: the cheapest OpenRouter route, Claude's cache through
  gateways, big files read as an outline, DeepSeek's half-price hours (approve to start then).
- **Autopilot**: a button that answers Roundtable's cards with the recommended choice while you're
  away, within a spending cap and a time you set; it never raises limits, spends more, deletes or
  publishes, and logs every decision in "What autopilot did".
- **Safer runs**: real-money limits, pausing when an account is empty, stronger checks after a
  rejection, tasks split when too big, "accept as it is", and model switches learned after
  each run (written in the journal with the reason).

### From the terminal (any OS)

#### Try it on your computer (10 minutes)

You need Python 3.10+ and git.

```bash
# 1. Install (into its own virtual environment)
python3 -m venv ~/.roundtable-venv && source ~/.roundtable-venv/bin/activate   # Windows: .roundtable-venv\Scripts\activate
pip install "git+https://github.com/MEZTKING/agent-harness@main"

# 2. Your shared hub (private repo: git will ask you to log in to GitHub)
git clone https://github.com/MEZTKING/agent-hub-data ~/agent-hub-data

# 3. Config + keys (only the providers you use)
mkdir -p ~/.roundtable && cd ~/.roundtable && roundtable init      # writes hub.yaml + harness.yaml here
export HUB_CONFIG=~/agent-hub-data/hub.yaml HUB_AGENT=me HARNESS_CONFIG=~/.roundtable/harness.yaml
export ANTHROPIC_API_KEY=... DEEPSEEK_API_KEY=... RETRODIFFUSION_API_KEY=...

# 4. Go
roundtable probe       # first: checks every model + your keys, records baselines
roundtable where       # where was I? (your real journal)
roundtable ui          # opens the web UI at http://127.0.0.1:8765
```

Put the `export` lines in your shell profile (`~/.bashrc` / `~/.zshrc`) so they're set in every terminal. Update any time with `roundtable update`.

One command, `roundtable`, does everything. (`agent-hub` and `harness` still work as aliases.)

**Staying up to date:**

```bash
roundtable version          # what's installed, from where, which commit
roundtable update --check   # is there a newer version? (exit code 1 if yes)
roundtable update           # install it and list what changed
roundtable update --ref main   # follow another branch or tag
```

The updater works with both kinds of install:
- **From GitHub** (`pip install git+…`): reinstalls from the same URL and branch.
- **From a local checkout** (`pip install -e .`): runs `git pull --ff-only` and reinstalls, so new dependencies and commands are picked up. It refuses if you have uncommitted changes.

Any `roundtable` command checks for updates at most once a day (2-second timeout) and prints a one-line notice. Turn this off with `ROUNDTABLE_NO_UPDATE_CHECK=1`. The web UI shows an **Update now** banner. After an update, restart any running `roundtable ui` or `mcp` servers.

### Backups

Roundtable Hold can back up everything that would be hard to make again, in one file:

- **your settings**: which model does what, providers, prices and limits (`harness.yaml`, `custom.yaml`), the hub's settings (not a GitHub hub's data: that's on GitHub already; a hub kept only on this computer is included) and the app's own settings;
- **what Roundtable has learned**: learned settings, suggestions, versions and model check history (files over 20 MB are left out and listed);
- **every project's plan and history**: the plan, tasks, costs, events and pictures in its `.harness` folder (not the rebuildable `spill`, `scratch` and `references` folders). Add **with code** to include the project's own files too (off by default: projects can be big);
- **the list of paired phones**.

**Never in a backup:** API keys and passwords. Every file is checked first; one that looks like it holds a key is left out, and the backup says which. The phone connection's private key isn't included either.

**Where backups go:** if you have [Google Drive for desktop](https://www.google.com/drive/download/), Roundtable finds its **My Drive** folder (on Windows usually `G:\My Drive`) and puts backups in `My Drive\Roundtable backups`, so they're in your Google Drive with no extra setup. Any other folder works too: OneDrive, a USB stick, another disk.

In the app: **Settings → Backups**. Back up now, see the last backup, back up every day (once a day while the app is open, never while a project is running), keep the newest 10, and lock backups with a **passphrase** (recommended: a backup holds your plans; the passphrase is never saved, and a backup can't be opened without it). A backup is also made just before the app installs an update.

```bash
roundtable backup where                     # which Google Drive folder it found
roundtable backup now [--to FOLDER] [--with-code] [--passphrase]
roundtable backup list
roundtable backup restore FILE [--yes]      # asks for the passphrase if the backup is locked
roundtable backup settings --daily on --keep 10 --encrypt on
```

**Restoring** (Settings → Backups → Restore…, or `roundtable backup restore`) shows what's in the backup and what it would replace, and asks first. It saves what's there now as a safety backup next to it, then puts everything back; projects whose folders are gone are made again. Afterwards **type your API keys again** (Settings → API keys) and **pair your phones again**.

### See what's being made

Every project's page has three tabs: **Overview** (the tasks, costs and files), **Live** and
**Session**.

- **Live** shows the app itself, running from its folder inside the page (**Computer** or
  **Phone** width, **Reload**, **Open in browser**), and pictures of it. After every task the
  reviewer approves, Roundtable opens the app's page (`index.html`, at the top of the project or in
  `public/`, `www/`, `dist/` and the like) on a small web server of its own and takes pictures: a
  computer screen (1280×800), a phone (390×844) and, when the app follows the computer's dark
  mode, a dark one. Errors the page reports while loading are listed. Earlier tasks' pictures sit
  in a strip underneath; click any picture to see it full size. Pictures need Playwright (the
  same as the looks); without it everything else still works.
- **Session** reads like watching a Claude Code session: the model's words, then each step as one
  line (● Read js/app.js · ● Edit css/styles.css (+12 −3) · ● Run `node --test` · passed). Click a
  line to see the change in colour, the command's output or the lines read. The reviewer's
  verdict, the cost of each step and the pictures follow, and while a task runs the tab follows it
  live. **Outputs** lists the pictures and files the project made (shown as pictures; apk, zip and
  exe files as downloads), as if sent in a chat.
- The Hall's seat for a project shows its newest picture.
- On the phone, the project's **Live** tab shows the newest pictures (tap to see one full size,
  pinch to zoom) and the latest task's steps. In Hub mode they come from the hub
  (`plans/shots/<project>/`: the newest set, one picture per finished task up to 20, and
  `session.json` with short lines only, never file contents); in PC mode from the PC.

The app runs in its frame from a separate local address, so it can't reach Roundtable's own pages
or the internet; only files inside the project are served (never `.git`, `.harness`, `.env` or a
link that leads outside). Anything shaped like a key is hidden in the Session view and the hub.
Turn the pictures off with `show_it: off` in `harness.yaml`. Apps that start with a command
(`npm start`) are shown from their page as it is for now.

### Autopilot

**Autopilot** answers what waits for you while you're away from the screen, with the recommended
answers, and writes down every choice. Turn it on with the **Autopilot** button at the top of the
app, next to *Today* (on the phone: the same button on the Table). Pick until when (**Off when I'm
back**, **1 hour**, **Tonight**: until 8am, or a time of your own) and a **spend limit** (default
$2.00, for all projects together). While it's on the button glows amber ("until 8am · $0.40 of
$2.00") and the seats it looks after carry a small *autopilot* mark. A project can be kept away from
it: **Never on autopilot** on the project's panel in the Hall.

What it decides, through the same cards you tap:

- **Plan choices, questions, the look, the setting and ideas**: the recommended answer. A question
  with no recommended answer, or an idea the planner didn't recommend, waits for you. Then it asks
  the planner to update the plan with those answers (at most 3 times a project).
- **Approving a plan**: only when the plan's estimate fits what's left of autopilot's spend limit
  and the project's own limit. When the plan's cost isn't known (a picture model with no price) it
  waits for you. If "start at half price" is offered and that time comes before autopilot stops,
  it picks that.
- **A failed task**: tried once more with the same models. Never the stronger model, never
  "accept as it is", never "skip".

What it never does: raise a limit or spend more after a money pause or an empty account, pick
anything that asks "Are you sure?", or delete, publish, release or merge anything. It turns itself
off when its time is up or the spend limit is reached (real money, checked against your providers'
balances where they report one, else Roundtable's own count), and says why. A run it started
carries on within its project's own limits.

**What autopilot did:** the button's card lists every choice and everything it left for you,
newest first, with links to the projects. The same log is in the app's folder
(`autopilot-log.md`), and each choice is also a *decision* in the project's journal. Answers on a
plan can still be changed until the plan is approved.

```bash
roundtable autopilot on --until 08:00 --cap 2   # or --until 1h / tonight; no --until: until you turn it off
roundtable autopilot status | log | off
roundtable autopilot never PROJECT [--undo]
roundtable autopilot --watch 60                 # keep answering without the desktop app
```

The desktop app does this every minute while it's open; `roundtable remote --watch` does it too.
From the phone in Hub mode the switch is a hub command (`roundtable: {"action": "autopilot",
"state": "on", "until": "tonight", "cap": 2}`), done by the PC.

| Part | What it does |
|---|---|
| **1. Hub & journal** | Lets agents working in different repos share what they're building and talk to each other, within the permissions you set. Each project keeps a journal: done, todo, plans, decisions, session handoffs. |
| **2. Harness** | Runs whole projects: an orchestrator breaks the work into tasks and routes each one to the model you've assigned to that role (Claude, DeepSeek, OpenAI, Gemini, Retro Diffusion…), reviews every result, and retries or falls back to another model. |
| **3. Self-improvement** | Learns from every run which models, prompts and settings work best, tests proposed changes by replaying real past tasks, and applies them with your approval (or automatically, per your policy). Every change is versioned and can be rolled back. Health probes catch models that regress. |
| **Web UI** | All of the above in a browser. |

---

## Web UI

Everything below also works from a browser:

```bash
export HUB_CONFIG=~/agent-hub-data/hub.yaml HARNESS_CONFIG=~/harness.yaml
roundtable ui                 # → http://127.0.0.1:8765  (or: roundtable ui)
```

| Page | What you can do |
|---|---|
| **Roundtable** (main screen) | Every project at the table with its live status (running and on which task/model, waiting for you and why, idle, done) and progress. **Needs you** puts approvals, failed tasks, budget stops, urgent todos and unread messages first, with one-click actions. For the selected project: its **task tree**, **chat with its orchestrator** (ask questions, or steer it; instructions reach every later task), and the **live minutes** of what every agent is doing, plus model health, today's spend and auto-sync. |
| **Projects** | All hub projects at a glance. Per project: full journal history by kind, and the editable project card that other agents read. |
| **Messages** | Any agent's inbox, threads, reply, and send to one or more agents. |
| **Runs** | Harness projects with status and spend. Start a new project (optionally approving the plan first), approve, resume, run one task, extend with a new goal, retry or skip failed tasks, 👍/👎 results (feeds self-improvement), live run log, completion report, models used. |
| **Models & health** | Role routing (learned changes marked), run health probes, probe history per model. |
| **Improve** | Analyze history (free or with the analyst model), suggest changes, replay-test, apply (health-checked first) or reject, see what's been learned, roll back any version. |
| **Jobs** | Long actions run in the background with live logs, so the page never blocks. |

The UI reads and writes through the same code as the CLI, so both always show the same data.

**Security:**
- Listens on `127.0.0.1` only, and refuses foreign `Host` headers (DNS rebinding).
- Writes need a custom header, which blocks cross-site form posts.
- A strict Content-Security-Policy is set, and every page is built from DOM nodes, never `innerHTML`, because pages display model output.
- `--host 0.0.0.0` prints a one-time token link. **Anyone with that link can run models and shell commands**, so only share it on networks you trust.

---

## Part 1: the Hub

Each agent (usually one per repo) gets:

- **A project card**: summary, goal, status, **interfaces** (APIs, schemas, contracts other repos rely on), what it depends on, recent changes and recent commits.
- **An inbox**: other agents can `ask`, `notify` or `request`, and it can reply. Conversations are threaded.
- **Change notifications**: when an agent updates its card with a change note ("renamed `total` → `total_cents`"), every agent that depends on it or subscribes to it gets a notice automatically.
- **Permissions**: `hub.yaml` rules decide who can read whose card and who can message whom.

Agents use it through **MCP** (Claude Code and any other MCP-capable agent, with no custom integration) or the **`agent-hub` CLI**.

### Install

```bash
pip install -e ".[dev]"      # from this repo
# or, from another machine/repo:
pip install "git+https://github.com/MEZTKING/agent-harness"
```

### Configure

```bash
roundtable init               # writes a starter hub.yaml
```

```yaml
storage:
  type: git                  # "file" = local folder, "git" = shared via a GitHub repo
  path: .                    # where the data lives (relative to hub.yaml)

default_policy: deny         # used when no rule matches

agents:
  backend:  {repo: you/bakery-api, role: coder, description: REST API + DB}
  frontend: {repo: you/bakery-web, role: coder, description: Website}
  manager:  {role: manager, description: Coordinates work}

rules:                       # checked in order, LAST match wins
  - {from: "*", to: "*", allow: [read_card]}
  - {from: backend,  to: frontend, allow: [message]}
  - {from: frontend, to: backend,  allow: [message]}
  - {from: "*", to: manager, allow: [message]}
  - {from: manager, to: "*", allow: [message]}
```

Actions are `read_card` and `message`. Agents can always edit **only their own** card, and can always **reply** to a message they received.

### Sharing across repos: the "hub data repo"

The recommended setup needs no server:

1. Create a private GitHub repo, e.g. `agent-hub-data`.
2. Put your `hub.yaml` at its root with `storage: {type: git, path: .}`.
3. In every session or machine whose agent should join, clone `agent-hub-data` and install Roundtable Hold.
4. Every hub write is committed and pushed, and every read pulls first. Each message is its own file, so agents writing at the same time don't conflict. You also get a full, auditable history in git.

### Connect Claude Code sessions: `roundtable connect`

Claude Code sessions can talk to each other through the hub, whether they run on your PC (the `claude` CLI) or in the cloud (claude.ai/code). Every message and journal entry is a git commit in `agent-hub-data`, so all sessions see them within seconds.

```
 Claude Code CLI (your PC)        Claude Code (cloud session)        Roundtable Hold app
   repo: webshop                     repo: agent-harness                (Windows)
        └──────── hub_send / hub_inbox / hub_log ── agent-hub-data (GitHub) ──┘
```

**Once per machine:** install Roundtable Hold (`pip install "git+https://github.com/MEZTKING/agent-harness@main"`) and clone your hub next to your repos or in your home folder (`git clone https://github.com/MEZTKING/agent-hub-data ~/agent-hub-data`).

**Once per repo**, run this inside the repo, then commit the two files it writes:

```bash
roundtable connect            # project id = the folder name; or --agent ID --description "..."
git add .mcp.json .claude/settings.json && git commit -m "Join the Roundtable Hold hub"
```

It does three things:

1. adds the project to `hub.yaml` if it's new (committed and pushed);
2. writes `.mcp.json` so Claude Code starts the `roundtable` MCP server as this project (approve it the first time Claude Code asks);
3. adds three Claude Code hooks to `.claude/settings.json`:
   - **Session start:** Claude gets the project's briefing (last session, next steps, todos) and unread messages.
   - **Once the session has changed files:** Claude is reminded, once per session, to log a handoff with `hub_session_end`.
   - **Session end:** if a session changed files but never logged a handoff, a short note listing the changed files is logged for it.

The files hold nothing machine-specific. The hub is found through `$HUB_CONFIG`, then the hub this computer last connected with, the desktop app's hub, `~/agent-hub-data`, or an `agent-hub-data` checkout next to the repo. Hooks never block a session: if the hub can't be reached, Claude is told so and carries on. Use `--no-hooks` to install only the MCP server.

**Cloud sessions** start on a fresh machine each time. Two things make them join automatically:

- **The environment's setup script** installs the `roundtable` command. `roundtable connect --cloud-script` prints the script.
- **The `agent-hub-data` repository** must be added to the session alongside the project repo. It is checked out next to the project, which is where the hub is found.

Limits: messages travel through git, so they arrive in seconds, not instantly. A running session doesn't get interrupted when a message arrives: it sees it at its next session start, or when it calls `hub_inbox`.

**By hand** (other MCP clients): run `roundtable mcp --agent ID` as a stdio server, with `HUB_CONFIG` set if the hub isn't in one of the places above.

The agent then has these tools:

| Tool | Purpose |
|---|---|
| `hub_whoami` | Your id and card |
| `hub_list_agents` | All agents and what you may do with each |
| `hub_list_cards` / `hub_read_card` | See what other repos are building and what they expose |
| `hub_update_card` | Update your card; a `change_note` notifies dependents |
| `hub_send` / `hub_inbox` / `hub_reply` / `hub_thread` | Messaging |
| `hub_subscribe` | Follow another agent's changes |

The server also sends the agent usage instructions: check the inbox at the start of a task, read cards before relying on another repo's API, and post change notes after breaking changes.

Tip: `roundtable connect` covers the session start and end automatically. You can also add a line to a repo's `CLAUDE.md`: *"Post a `hub_update_card` change note after any change other repos depend on."*

### CLI

```bash
export HUB_CONFIG=~/agent-hub-data/hub.yaml HUB_AGENT=frontend
roundtable agents
roundtable cards
roundtable card show backend
roundtable card set --status "checkout page done" --change "checkout now calls POST /orders"
roundtable card set --depends-on backend
roundtable card refresh-git --repo-path ~/code/bakery-web
roundtable send backend "orders shape?" "What fields does GET /orders return?"
roundtable inbox --mark-read
roundtable reply <message-id> "thanks!"
roundtable subscribe backend
```

### Project journal: "where was I?"

When you juggle several projects across sessions and machines, each project keeps a journal in the hub. It records what was **done**, what's **todo** (with priority), future **plans**, **decisions** and why, **notes**, and **session** handoffs: what a session was doing and its next steps. It lives in the shared hub data repo, so every session on every machine sees the same history.

```bash
roundtable where                       # briefing for ALL your projects, most recent first
roundtable where backend               # full briefing for one project
roundtable log todo "add auth to /orders" --priority high
roundtable log done "order endpoints"
roundtable log plan "move to Postgres in v2"
roundtable log decision "JWT, not sessions: the mobile app needs it"
roundtable todo --plans                # open todos and plans, with ids
roundtable close 3fa2c1                # finish a todo (or --drop it)
roundtable session "built order endpoints; auth is next" --next "JWT middleware" --next "test auth"
roundtable history backend --kind session
```

```
== backend (you/bakery-api)  - last activity 2h ago
Last session (2h ago): built order endpoints; auth is next
   next: JWT middleware
Open todos (2):
  ![3fa2c1] add auth to /orders
   [9b04e7] write API docs
Plans: 1 open
Recently done:
   - order endpoints (3h ago)
```

- **On GitHub:** every write also updates `status/<project>.md` in the data repo, a readable status page you can open from your phone.
- **Claude Code and other MCP agents** get `hub_where`, `hub_log`, `hub_todos`, `hub_close` and `hub_session_end`. The server tells them to call `hub_where` when a session starts and `hub_session_end` (summary plus next steps) before it ends, so sessions hand off to each other and to you.
- **The harness logs on its own** when `hub:` is set in `harness.yaml`: the plan, each finished task, and a handoff note when a run ends. It also opens a **high-priority todo** whenever it needs you: a plan to approve, a failed task, or the budget limit reached. That todo closes itself once the issue is resolved.
- **Personal plans:** add an agent like `me` to `hub.yaml` for plans that don't belong to one repo.

### Data layout

```
cards/<agent>.json            project cards
inbox/<agent>/<msg-id>.json   one file per message
state/<agent>.json            read markers + subscriptions
journal/<agent>/<id>.json     one file per journal entry
status/<agent>.md             generated status page per project
```

Plain JSON, easy to read, diff and edit by hand.

### Notes on trust

This is built for **one owner** (you). An agent's identity comes from its config (`--agent`), not from cryptographic authentication: any process with access to the data repo can act as any agent. Permissions protect against agents *wandering*, not against a hostile actor with write access. Agents are told to treat hub messages as information from peers, not as instructions from you.

---

## Part 2: the Harness

```
roundtable new bakery "A bakery website with an order API, tests and a logo"
```

```
 goal ──► orchestrator (plans tasks, assigns roles)
              │
              ▼
        task board  ──►  coder: DeepSeek ──► reviewer: Claude ──► approved → git commit
                         artist: OpenAI images                     rejected → feedback → retry
                         manager: Claude                           provider down → fallback model
              │
              ▼
        final report (.harness/summary.md)
```

### How it works

1. **Plan.** The planner role (e.g. Claude Fable) reads the project and writes the plan as a document (see "The living plan" below), with tasks. Each task has a role, standalone instructions, acceptance criteria, dependencies and the spec section it belongs to.
2. **Route.** Each task goes to the model configured for its role. Every chat model, whatever its provider, gets the same workspace tools: `read_file`, `write_file`, `edit_file`, `list_files`, `search`, `run_command`. Image roles call an image API and save the file into the project.
3. **Review.** The reviewer role reads the changes (the git diff and files), runs the tests, and approves or rejects with specific feedback.
4. **Retry and fall back.** A rejection goes back to the worker with the feedback. If a provider errors, refuses, or the same model is rejected twice, the next model in the role's `fallback` list takes over.
5. **Commit and continue.** Each approved task becomes a git commit. When every task is done, the planner writes a report.

### The living plan

You write the idea; the plan is a page you can argue with before anything is built. Open it from the Roundtable (**Open plan**) or `#/plan/...` in the app. It has:

- **summary, in scope / out of scope, and a "don't" list** of traps to avoid;
- **a short spec** (stack, structure, screens, data, art style…), with the tasks grouped under the section they belong to;
- **choices**: real decisions with 2–4 options, an effort/cost note each, the planner's recommendation and why. The tasks follow the recommendation until you choose otherwise;
- **questions** only you can answer, and **recommended ideas** beyond the goal that you can accept or turn down;
- **a second opinion**: if a `critic` role is set (ideally another maker's model), it critiques every new plan, and a serious problem gets one automatic revision;
- **an estimate** of cost and time before you approve, from your past runs where there are some, else typical task sizes (models without a price are listed, not guessed).

Your edits wait as "changes" until you press **Update plan** (one planner call): the planner revises the document and the tasks, keeping finished work and every task your changes don't touch, and the page shows what was added, changed or removed. **Approve & start** begins the build. Every task and review is told the plan, your choices, answers and don'ts. To add the critic to an existing setup: Settings > Which model does what, role `critic`, any model (a different maker from your planner works best).

#### Answer by tapping

Roundtable asks you things the way a good assistant does: one card per question, with a short label at the top, the question, two to four answers to tap (the one it recommends comes first, marked **(Recommended)**), and **Other…** when you'd rather type. Where more than one answer fits you tick them and press **Done**. On a computer, number keys pick and Enter sends.

The same cards are everywhere: **Needs you** on the Roundtable shows the next one for each project, the plan page shows them all (the answered ones fold away under **Answered**, where you can change an answer until you approve), and the phone shows them on its Needs you list and the project's Plan tab. They cover the plan's choices, its questions (the planner now offers likely answers), its ideas, the look, the setting (Budget, Balanced or Quality, each with its estimate), approving the plan, a task that failed (Retry, Retry with the stronger model, Accept as it is, Skip it) and a run paused for money (Carry on with $X more, Stop here, Switch to the Budget setting). Anything that would spend beyond the estimate shows a second card first: **Are you sure?** **Not now** leaves a card for later.

**+ New project** is a few cards too: what you want to make (web app, game, Android app, Windows app or something else), your idea in a few words, something to make it like, the setting, and whether to see three looks. Then the planner makes the plan, with its own questions for you. From the phone in Hub mode a card's answer goes through the hub as the `answer` command (`id`, `chosen`, `other`, `confirmed`); the cards themselves are written next to the plan as `plans/<project>.asks.json`.

#### A look of its own

So that every app you make looks like itself, an app with screens gets a **Look** step in its plan. A designer (the `designer` role: a model that can see pictures) makes three clearly different looks, each with a name, a mood, light and dark colours, fonts, shapes, one signature detail and a list of things it must never do, plus a picture of the app's main screen in that look (on a computer and on a phone). They're never the same as the looks you chose for your other projects, unless you ask. Give a starting point if you like ("like an old record shop") and press **Make new looks** for another three.

Press **Choose this look** (you can add a note, such as "warmer"), then **Update plan**. Roundtable writes the look into the project as `design/DESIGN.md` (in plain words) and `design/tokens.css` (the colours, fonts and corners for light and dark), and every task and review follows it: a check finds colours or fonts written into the code instead of taken from the design file, and the reviewer sends that work back. If screens are already built, a task "Restyle the app in the chosen look" is added. Choosing a look never blocks **Approve & start**; an unchosen look shows under Needs you. From the phone: `look` (choose, with `id` and an optional `note`) and `looks` (new ones). Set `look_stage: off` in harness.yaml to make looks only when you ask. The pictures need Playwright (`pip install playwright && playwright install chromium`); without it you still get the looks and their pages.

#### Make it like this

If something like your idea already exists, give it to Roundtable: a web link (an app, a game page, a website, a forum post), a GitHub repository (`owner/name` or its address), or a plain description ("the queue from Spotify"). Put them in the **Make it like this** box when you start a project (one per line), add them later in **Like these** on the plan page, from the terminal with `roundtable new DIR "goal" --like ADDRESS_OR_TEXT` (repeat it for more), or from the phone (`reference_add` with `text`, `reference_remove` with `id`).

Before planning, a `scout` role (any cheap, capable chat model; without one the planner does it) reads each one and writes a short report: what it is, its features, how the parts worth borrowing work, its look in words, its licence, what to borrow for your project and what to avoid. The plan shows the reports under **Like these**, the planner builds on them, the designer starts its looks from them, and every task sees a short form. One you add later is read when you press **Update plan**. Each reading costs a little and counts in the budget. Many sites refuse automated readers (Reddit does): the report then says plainly what couldn't be read, and nothing is made up.

**Similar, never a copy.** Your project borrows the kind of thing it is, how it works and its general style, never another product's name, characters, story, art, music, sounds, levels, logos or text, and it is never presented as that product. Pictures, sounds, fonts and models are never copied. Code is used only when its licence is clearly open (MIT, BSD, Apache, ISC, zlib, MPL); Roundtable decides that from the licence itself, and such code is credited in the project's `THIRD_PARTY_NOTICES.md`.

Everything is saved in `<project>/.harness/` (`plan.json` and a readable `plan.md` included). A run can stop at any point (budget reached, plan waiting for approval, a failed task, Ctrl-C) and `roundtable run` resumes where it left off.

### Setup

```bash
pip install -e .
roundtable init                     # writes harness.yaml: providers, roles, prices, limits
export ANTHROPIC_API_KEY=... DEEPSEEK_API_KEY=... RETRODIFFUSION_API_KEY=...   # only the providers you use
roundtable roles                    # check the routing
roundtable probe                    # check every model works, and record its baseline (see Part 3)
```

**Roles are just config.** To make Gemini your writer or move coding to Claude, edit one line:

```yaml
roles:
  orchestrator: {model: anthropic/claude-fable-5-2, fallback: [anthropic/claude-opus-5-5], options: {effort: high}}
  coder:        {model: deepseek/deepseek-v4-pro, fallback: [anthropic/claude-sonnet-5-5], description: writes and tests code}
  reviewer:     {model: anthropic/claude-opus-5-5}
  artist:       {kind: image, model: openai_images/gpt-image-1, description: logos and illustrations}
```

The `description` tells the planner when to use a role. You can add any role, such as `writer`, `researcher` or `devops`, and give it its own prompt file through `prompts_dir`.

**Providers:**
- `anthropic`: Claude via the official SDK. Thinking, prompt caching, `effort` and refusal fallbacks are on.
- `openai_compat`: any OpenAI-compatible API (DeepSeek, OpenAI, Gemini, OpenRouter, Groq, local Ollama).
- `openai_images`: image generation through OpenAI's image API.
- `retrodiffusion`: **pixel-art game assets** ([Retro Diffusion](https://www.retrodiffusion.ai)). The planner picks a style per task (platformer, top-down, isometric, tiles, items, UI…), plus the size and a transparent background. The exact per-image charge is counted in the budget.

```bash
roundtable image artist --styles                                   # browse styles
roundtable image artist "a knight with a blue cape" --style rd_lite__platformer --size 64x64 --remove-bg --cost-only
roundtable image artist "a knight with a blue cape" --style rd_lite__platformer --size 64x64 --remove-bg --out knight.png
```

### The recommended split: Openference plus DeepSeek

One [Openference](https://openference.com) key reaches Claude, GPT, Gemini, GLM, Kimi, Qwen and
more, so each check can be done by a different maker. Bulk coding stays on a direct DeepSeek key,
which is much cheaper than DeepSeek through Openference.

| Job | Model | Why |
|---|---|---|
| Planner | Claude Opus 5.5 (Openference), DeepSeek V4 Pro if that fails | the best plans |
| Critic | GPT-6.1 Terra (Openference), GLM-5.3 if that fails | a second opinion from another maker |
| Designer | Claude Sonnet 5.5 (Openference), GLM-5.3 if that fails | designs the looks and can see pictures |
| Coder | DeepSeek V4 Flash (direct), V4 Pro when it gets stuck | cheap for the bulk of the work |
| Reviewer | GPT-6 Luna (Openference), Claude Haiku 5.5 if that fails | cheap, and a different maker from the coder |

```bash
roundtable providers add openference          # then set OPENFERENCE_API_KEY
roundtable assign orchestrator "openference/Claude Opus 5.5" deepseek/deepseek-v4-pro
roundtable assign critic "openference/GPT-6.1 Terra" openference/GLM-5.3
roundtable assign designer "openference/Claude Sonnet 5.5" openference/GLM-5.3
roundtable assign coder deepseek/deepseek-v4-flash deepseek/deepseek-v4-pro
roundtable assign reviewer "openference/GPT-6 Luna" "openference/Claude Haiku 5.5"
```

Good to know: Claude through Openference is paid from your credit there and needs at least $1
kept on the account; don't use its "bring your own key" mode for agents (it adds $0.01 to every
request, and an agent makes one per step); turn on ZDR mode for the key if you want makers not to
keep your prompts. Openference shows no balance through its API, so `roundtable balance` can't
check its real cost yet.

### Budget, Balanced, Quality

A project can switch between named sets of models (`profiles:` in `harness.yaml`). The plan shows
what each would cost, and you switch on the plan page, from the phone (`profile` command) or with
`roundtable` in a script. Only the tasks still to do use the new setting.

- **Budget:** open models (DeepSeek, GLM, GPT-6 Luna) for everything.
- **Balanced** (the default): Claude plans and designs, other makers check, DeepSeek codes.
- **Quality:** Claude Opus plans and designs, Claude Sonnet codes, GPT checks, all through
  OpenRouter. It costs roughly ten to twenty times as much as Balanced for the coding.

OpenRouter models need no `pricing:` lines: Roundtable reads OpenRouter's published prices, the exact
cost of every call, and the account balance (`roundtable balance`).

### Adding any provider

**In the app:** Settings → **AI providers** → pick one → paste the key → **Add provider**. It's tested right away, and **Models** lists everything that provider offers. Then use **Which model does what** to give any role any model, with fallbacks.

**From the terminal:**

```bash
roundtable providers presets                  # ~20 built in: OpenAI, Gemini, xAI, Mistral, DeepSeek, OpenRouter,
                                              # Groq, Together, Fireworks, Cerebras, Cohere, Qwen, Kimi, Perplexity,
                                              # Ollama/LM Studio (local), Retro Diffusion, OpenAI images...
roundtable providers add groq                 # then set GROQ_API_KEY (or paste it in the app)
roundtable providers test groq                # checks the key and lists the provider's models
roundtable providers models openrouter        # every model a provider offers
roundtable assign coder groq/<model> deepseek/deepseek-v4-pro   # primary, then fallbacks
```

**Anything else:**
- **Any OpenAI-compatible API** (vLLM, LiteLLM, a company gateway, Azure OpenAI…):

  ```bash
  roundtable providers add custom --id mygw --base-url https://gw.example.com/v1
  roundtable providers add custom --id azure --base-url https://RES.openai.azure.com/openai/v1/ \
      --auth-header api-key --query api-version=preview
  ```
  `--header NAME=VALUE` adds extra headers. Values can use `${ENV_VAR}`.
- **Anthropic-compatible APIs:** use `type: anthropic` with a `base_url`.
- **Completely different APIs:** write a small plugin and put it in `plugins/` next to `harness.yaml` (in the app: `%APPDATA%\RoundtableHold\config\plugins`):

  ```python
  # plugins/myapi.py
  from roundtable.providers.base import ChatResponse, Provider, Usage

  class MyAPI(Provider):
      def __init__(self, name, endpoint="https://..."):
          self.name, self.endpoint = name, endpoint
      def list_models(self):
          return ["my-model"]
      def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None):
          ...  # call your API, return ChatResponse(text=..., usage=Usage(in_tokens, out_tokens))
  ```
  Then run `roundtable providers add plugin --id myapi --class myapi.py:MyAPI`. Image APIs subclass `ImageProvider` and implement `generate()`. Plugins are your own code and run with full access.

Everything added this way goes into **`custom.yaml`** next to `harness.yaml`, which is never rewritten. Delete a line there to undo it.

### Commands

```bash
roundtable new DIR "goal" [--approve]    # --approve: stop after planning so you can check the plan
roundtable approve DIR && roundtable run DIR
roundtable status DIR                    # task board + spend
roundtable run DIR [--max-tasks N]       # resume / step through
roundtable retry DIR T3                  # re-open a failed task
roundtable skip DIR T3                   # mark a task done yourself
roundtable extend DIR "next goal"        # add features to an existing project
roundtable metrics DIR                   # success rate, cost and time per role/model
roundtable -v ...                        # show every model turn and tool call
```

### Budget and safety

Roundtable counts each run's cost from the tokens used and the pricing table. To check that count
against your bill, a run notes the provider's real balance at its start and end where the provider
reports one (DeepSeek does): see `.harness/balance.jsonl` in the project, or run `roundtable balance`.
Text a model has already seen (a cache hit) is counted at a tenth of the input price unless you set
`cache_read` in `pricing:`.

- `limits.max_cost_usd` pauses a project when reached; `roundtable run` continues after you raise it. Claude prices are built in. **Add `pricing:` for the other providers**, or their calls are counted as "unpriced" and don't count toward the budget.
- `run_command` executes model-written shell commands in the project directory. **It is not a sandbox.** Run the harness in a container or VM, or set `workspace.allow_shell: false`, if that matters for your machine.
- `hub:` in `harness.yaml` reports project progress to the Hub, so your repo agents can see what the harness is building.
- **A real-money limit per run**: `limits.max_real_usd_per_run` (e.g. `1.0`) pauses a run once your
  providers' real balances fell by that much since it started, checked between tasks and inside long
  ones. A run also pauses at half its limit if nothing has passed yet, and when an account says it's
  out of credit (the task goes back in the queue; a "money" card asks you to top up).
- **Cheaper hours**: DeepSeek charges half outside its peak hours (reported as 01:00–04:00 and
  06:00–10:00 UTC). Roundtable counts the right price at each hour, and when you approve a plan during
  peak hours the card offers "Approve, start at HH:MM UTC"; the desktop app starts it then.
- **Cheaper routes**: through OpenRouter, Roundtable asks for the cheapest company that runs the model
  (`routing: throughput | latency | none` on the provider changes that); Claude through any gateway
  uses its cache; files over 400 lines are read as an outline plus the parts needed, not whole.
- **When a task goes wrong**: a task that keeps running out of steps is split into smaller ones by the
  planner (once); after a rejection a stronger reviewer model gives the next verdict; reviewers are
  told what later tasks will do; and you can **accept a task as it is** (`accept` on the failed-task
  card, or the hub command) when the work is right but was rejected for the wrong reason.
- **Learning after each run**: with `improve: {after_each_run: true, auto_apply: low}`, Roundtable
  looks at the numbers after every run and switches the order of models when they clearly say so
  (for example a cheap model that keeps failing while its backup finishes for less per task). Each
  switch is written in the hub journal with the reason and the undo command.
- **Pictures**: an image role (`kind: image`) can use picture models through OpenRouter
  (`type: chat_images`: GPT Image 2, Nano Banana) with the exact cost of each picture, or Retro
  Diffusion for pixel art.

#### Token saver

Every message a model reads costs money, and the biggest part is often what its tools
print: long tables, big lists of data, test logs. The token saver slims those before the
model reads them, for every model and maker:

- a list of data with the same fields on every line is rewritten as a compact table –
  shorter, but with nothing taken out;
- a long table keeps its first and last rows and a sample of the middle with line numbers;
- a long log keeps its start, its end and every line that looks like an error;
- the same output twice within a minute and a half is shown once.

Nothing is lost: the full text is saved first in the project's `.harness/spill/` folder,
and the shortened version tells the model how to get it back (the `expand_output` tool).
If the full text can't be saved, or the short version wouldn't really be cheaper, the
model gets the full text as before. `roundtable status` shows roughly how many tokens it
saved, and each task's line in `.harness/metrics.jsonl` has `saved_tokens_est`.

To turn it off, put `token_saver: false` in `harness.yaml`. Its settings (when to step in
and how much to keep) go under `token_saver:` – see `THIRD_PARTY_NOTICES.md` for where it
comes from.

#### Plugins

Plugins add things to Roundtable without changing it: token saving, cost logs, extra tools
for the workers, commands of their own. Two come built in: the **token saver** (above; on)
and **cost log** (each model call's tokens and cost in a CSV file; off until you switch it
on).

```
roundtable plugin list
roundtable plugin add ./my-plugin          # or a git link, or a pip package
roundtable plugin enable cost-log
roundtable plugin settings token-saver min_bytes=2000
roundtable plugin remove my-plugin
```

Choices are kept in `custom.yaml` under `plugins:`. **A plugin is someone's program and runs
with Roundtable's full access**: Roundtable shows what it says it will do and asks before
adding it, but can't hold it to that, so only add plugins from people you trust. A plugin
that goes wrong is switched off for the rest of the run, and the run carries on. How to
write one, the hooks and the permissions: [docs/plugins.md](docs/plugins.md).

### Tool servers (MCP)

A role can also use the tools of an MCP server: a program, often inside another app, that
offers tools to AI models (Unreal Engine's editor, Blender, a database). List the server under
`mcp_servers:` in `harness.yaml`, add `mcp: [its name]` to the roles that should use it, and
run `roundtable mcp list` to see that it answers. A server that isn't running never stops a
run: its tools are left out and the run's events say why. Details: [docs/mcp.md](docs/mcp.md);
Unreal Engine: [docs/unreal.md](docs/unreal.md).

---

## Part 3: Self-improvement

The harness learns from its own history. It never rewrites `harness.yaml`. What it learns goes into `.harness-lab/` (next to `harness.yaml`) and is layered on top, so you can always see and undo exactly what changed.

```
 every run ──► metrics: role, model, approved?, first try?, cost, time
                + reviewer rejection feedback + your ratings (roundtable feedback)
                         │
                         ▼
   analyze ──►  rules:  data-backed routing ("the fallback model is approved 40% more often: promote it")
                LLM:    analyst model reads stats, rejections and ratings → prompt / routing / option changes
                you:    roundtable improve propose ...
                         │
                         ▼
   test   ──►  replay real past tasks from their original git state:
                current setup vs proposed setup, same reviewer judges both
                         │
                         ▼
   apply  ──►  you approve (or auto_apply policy) → versioned → `roundtable improve rollback`
```

### Model health probes (regression and boost detector)

Providers update models silently. `roundtable probe` runs a 1-minute suite of auto-graded checks on every model in your config: tool calling, strict JSON, following formatting instructions, a small reasoning problem, and fixing a real bug in a file. It then compares each model with **its own recent history**:

```
model                                      score  usual  time s  usual  tokens   cost $  status
deepseek/deepseek-v4-pro                   5/5     100%    28.4     37    1124   0.0000  ok
deepseek/deepseek-flash                    5/5     100%     9.1     11     827   0.0000  ok
retrodiffusion/rd_lite__default            1/1     100%     0.2      1       0   0.0000  ok
```

| Status | Meaning |
|---|---|
| `REGRESSION` | A probe it reliably passed now fails, or its score dropped |
| `DOWN` | Every probe failed with a provider error |
| `BOOST` | A probe it reliably failed now passes, or its score rose |
| `slow` / `fast` / `verbose` | Time or output length is ≥2× / ≤½ its usual |
| `new` | First run: this becomes the baseline |

```bash
roundtable probe                         # all models (image APIs get a free reachability check)
roundtable probe --role coder --details  # one role, every probe result
roundtable probe --images                # also generate one real test image per image model (costs a few cents)
```

- **Exit code:** 1 when anything is `REGRESSION` or `DOWN`, so you can use it in scripts and cron jobs.
- **Gating:** `roundtable improve apply` and `cycle` probe the models a change involves first, and hold the change back if one of them is acting up. Use `--skip-probe` to bypass, or `--force` to apply anyway.
- **Your own probes:** add them in a YAML file set as `improve.probes_file`:

```yaml
- name: capital
  prompt: "What is the capital of Australia? One word."
  expect_contains: Canberra        # or expect_exact / expect_regex / expect_json
```

**First run with a new provider:** run `roundtable probe` before anything else. It confirms the key and adapter work, and it records the model's baseline.

### Commands

```bash
roundtable feedback myproject T3 --bad "UI ignores the brand colours"   # your ratings are training signal
roundtable improve analyze            # stats + data-backed proposals (no model call, no cost)
roundtable improve analyze --llm      # also ask the analyst model to study failures and propose changes
roundtable improve propose coder --models anthropic/claude-sonnet-5-5,deepseek/deepseek-v4-pro
roundtable improve propose coder --prompt-file my-coder-prompt.md
roundtable improve list / show P1a2b3c
roundtable improve test P1a2b3c --samples 3 --max-cost 2   # replay; spends real tokens, capped
roundtable improve apply P1a2b3c      # needs a passed test (or a rule-based routing change) unless --force
roundtable improve status             # effective routing, learned prompts, history
roundtable improve rollback [VERSION] # exact restore of the state before that version
roundtable improve cycle --llm --test # analyze + test + apply whatever the policy allows
```

### Keeping it always improving

Set the policy in `harness.yaml`, then run `roundtable improve cycle` after projects or on a schedule (e.g. a nightly cron job):

```yaml
improve:
  auto_apply: low       # none (default) | low | medium
  min_samples: 5        # judged attempts before metrics-based routing changes
```

**Guardrails:**
- LLM-proposed changes are only auto-applied after **passing a replay test**.
- Rule-based routing changes may apply untested, because they come straight from production metrics.
- A rewritten prompt must **beat** the current one in replay, not just tie it.
- The reviewer can't be tested by replay, since it is the judge; change it manually.
- Replay tests cost real money: `--max-cost` caps them. With only a few samples, results are noisy, and the report shows how many tasks were compared.
- Cost comparisons need `pricing:` for every model. Without prices, only quality is compared.

---

## Examples

- [`examples/knightgame`](examples/knightgame): a browser platformer built from one sentence. DeepSeek planned it and wrote the code, Retro Diffusion made the pixel art, and it cost $0.16. See [HOW_IT_WAS_MADE.md](examples/knightgame/HOW_IT_WAS_MADE.md).

---

## Naming and compatibility

This project was first built as "agent-harness". The rename to **Roundtable Hold** changed the package (`roundtable`), the command (`roundtable`), the UI and the MCP server name. Deliberately **unchanged**, so existing setups keep working:
- the `agent-hub` and `harness` commands (aliases)
- the `HUB_CONFIG` and `HARNESS_CONFIG` environment variables
- on-disk state: `.harness/` in projects and `.harness-lab/` for learned settings
- the hub data format

Config files are also looked up in `~/.roundtable/` before the old `~/.agent-hub/` and `~/.agent-harness/` locations.

## Development

```bash
pip install -e ".[dev]"
pytest
```

```
src/roundtable/
  core/       models, config, policy, storage (file + git)   ← shared by Hub and Harness
  hub/        hub service, MCP server, git helpers
  providers/  anthropic, openai_compat (DeepSeek/OpenAI/Gemini/...), images, scripted (tests)
  harness/    config (roles), tools (workspace), agent loop, orchestrator
  improve/    lab (proposals, learned overlay, versions), analysis, replay evaluation, cycle, probes
  prompts/    default role prompts (override with prompts_dir)
  ui/         web UI: server.py (JSON API + background jobs), static/ (vanilla JS, no build step)
  main.py         `roundtable` command (routes to the two below) + init/update/version
  updater.py      built-in updater (git or editable installs) and the daily update notice
  cli.py          hub & journal commands (alias: `agent-hub`)
  harness_cli.py  project, model and improve commands (alias: `harness`)
```
