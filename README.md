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

One command, `roundtable`, does everything. (`agent-hub` and `harness` still work as aliases.)

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
| **Where was I** | Every project's last session and next steps, open todos (high priority first), plans and recent work. Add entries, close or drop todos, write a session handoff. |
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

### Connect an agent (Claude Code example)

Add this to the `.mcp.json` of each repo:

```json
{
  "mcpServers": {
    "roundtable": {
      "command": "roundtable",
      "args": ["mcp", "--agent", "backend"],
      "env": { "HUB_CONFIG": "/path/to/agent-hub-data/hub.yaml" }
    }
  }
}
```

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

Tip: add a line to each repo's `CLAUDE.md`: *"Use the agent-hub tools: check `hub_inbox` at the start of each task and post a `hub_update_card` change note after any change other repos depend on."*

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
                         designer: OpenAI images                   rejected → feedback → retry
                         manager: Claude                           provider down → fallback model
              │
              ▼
        final report (.harness/summary.md)
```

### How it works

1. **Plan.** The planner role (e.g. Claude Fable) reads the project and splits the goal into tasks. Each task has a role, standalone instructions, acceptance criteria and dependencies.
2. **Route.** Each task goes to the model configured for its role. Every chat model, whatever its provider, gets the same workspace tools: `read_file`, `write_file`, `edit_file`, `list_files`, `search`, `run_command`. Image roles call an image API and save the file into the project.
3. **Review.** The reviewer role reads the changes (the git diff and files), runs the tests, and approves or rejects with specific feedback.
4. **Retry and fall back.** A rejection goes back to the worker with the feedback. If a provider errors, refuses, or the same model is rejected twice, the next model in the role's `fallback` list takes over.
5. **Commit and continue.** Each approved task becomes a git commit. When every task is done, the planner writes a report.

Everything is saved in `<project>/.harness/`. A run can stop at any point (budget reached, plan waiting for approval, a failed task, Ctrl-C) and `roundtable run` resumes where it left off.

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
  designer:     {kind: image, model: openai_images/gpt-image-1, description: logos and illustrations}
```

The `description` tells the planner when to use a role. You can add any role, such as `writer`, `researcher` or `devops`, and give it its own prompt file through `prompts_dir`.

**Providers:**
- `anthropic`: Claude via the official SDK. Thinking, prompt caching, `effort` and refusal fallbacks are on.
- `openai_compat`: any OpenAI-compatible API (DeepSeek, OpenAI, Gemini, OpenRouter, Groq, local Ollama).
- `openai_images`: image generation through OpenAI's image API.
- `retrodiffusion`: **pixel-art game assets** ([Retro Diffusion](https://www.retrodiffusion.ai)). The planner picks a style per task (platformer, top-down, isometric, tiles, items, UI…), plus the size and a transparent background. The exact per-image charge is counted in the budget.

```bash
roundtable image designer --styles                                   # browse styles
roundtable image designer "a knight with a blue cape" --style rd_lite__platformer --size 64x64 --remove-bg --cost-only
roundtable image designer "a knight with a blue cape" --style rd_lite__platformer --size 64x64 --remove-bg --out knight.png
```

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
- `limits.max_cost_usd` pauses a project when reached; `roundtable run` continues after you raise it. Claude prices are built in. **Add `pricing:` for the other providers**, or their calls are counted as "unpriced" and don't count toward the budget.
- `run_command` executes model-written shell commands in the project directory. **It is not a sandbox.** Run the harness in a container or VM, or set `workspace.allow_shell: false`, if that matters for your machine.
- `hub:` in `harness.yaml` reports project progress to the Hub, so your repo agents can see what the harness is building.

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
  main.py         `roundtable` command (routes to the two below)
  cli.py          hub & journal commands (alias: `agent-hub`)
  harness_cli.py  project, model and improve commands (alias: `harness`)
```
