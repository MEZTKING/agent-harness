# agent-harness

A personal system for running AI agents across providers and repositories.

It has two parts that share one core:

| Part | What it does | Status |
|---|---|---|
| **1. Hub** | Lets agents working in different repos share what they're building and talk to each other, within the permissions you set. | ✅ Built (this release) |
| **2. Harness** | Runs whole projects: an orchestrator breaks the work into tasks and routes each one to the model you've assigned to that role (Claude, DeepSeek, OpenAI, Gemini…), reviews every result, and retries or falls back to another model. | ✅ Built |
| **3. Self-improvement** | Learns from the harness's metrics which models and prompts work best, and proposes tested changes. | 🔜 Next: see [ROADMAP.md](ROADMAP.md) |

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
agent-hub init               # writes a starter hub.yaml
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
3. In every session or machine whose agent should join, clone `agent-hub-data` and install `agentharness`.
4. Every hub write is committed and pushed, and every read pulls first. Each message is its own file, so agents writing at the same time don't conflict. You also get a full, auditable history in git.

### Connect an agent (Claude Code example)

Add this to the `.mcp.json` of each repo:

```json
{
  "mcpServers": {
    "agent-hub": {
      "command": "agent-hub",
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
agent-hub agents
agent-hub cards
agent-hub card show backend
agent-hub card set --status "checkout page done" --change "checkout now calls POST /orders"
agent-hub card set --depends-on backend
agent-hub card refresh-git --repo-path ~/code/bakery-web
agent-hub send backend "orders shape?" "What fields does GET /orders return?"
agent-hub inbox --mark-read
agent-hub reply <message-id> "thanks!"
agent-hub subscribe backend
```

### Data layout

```
cards/<agent>.json            project cards
inbox/<agent>/<msg-id>.json   one file per message
state/<agent>.json            read markers + subscriptions
```

Plain JSON, easy to read, diff and edit by hand.

### Notes on trust

This is built for **one owner** (you). An agent's identity comes from its config (`--agent`), not from cryptographic authentication: any process with access to the data repo can act as any agent. Permissions protect against agents *wandering*, not against a hostile actor with write access. Agents are told to treat hub messages as information from peers, not as instructions from you.

---

## Part 2: the Harness

```
harness new bakery "A bakery website with an order API, tests and a logo"
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

Everything is saved in `<project>/.harness/`. A run can stop at any point (budget reached, plan waiting for approval, a failed task, Ctrl-C) and `harness run` resumes where it left off.

### Setup

```bash
pip install -e .
harness init                     # writes harness.yaml: providers, roles, prices, limits
export ANTHROPIC_API_KEY=... DEEPSEEK_API_KEY=... OPENAI_API_KEY=...
harness roles                    # check the routing
harness ask coder "hello"        # check one role's model works
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
- `openai_images`: image generation.

### Commands

```bash
harness new DIR "goal" [--approve]    # --approve: stop after planning so you can check the plan
harness approve DIR && harness run DIR
harness status DIR                    # task board + spend
harness run DIR [--max-tasks N]       # resume / step through
harness retry DIR T3                  # re-open a failed task
harness skip DIR T3                   # mark a task done yourself
harness extend DIR "next goal"        # add features to an existing project
harness metrics DIR                   # success rate, cost and time per role/model
harness -v ...                        # show every model turn and tool call
```

### Budget and safety
- `limits.max_cost_usd` pauses a project when reached; `harness run` continues after you raise it. Claude prices are built in. **Add `pricing:` for the other providers**, or their calls are counted as "unpriced" and don't count toward the budget.
- `run_command` executes model-written shell commands in the project directory. **It is not a sandbox.** Run the harness in a container or VM, or set `workspace.allow_shell: false`, if that matters for your machine.
- `hub:` in `harness.yaml` reports project progress to the Hub, so your repo agents can see what the harness is building.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

```
src/agentharness/
  core/       models, config, policy, storage (file + git)   ← shared by Hub and Harness
  hub/        hub service, MCP server, git helpers
  providers/  anthropic, openai_compat (DeepSeek/OpenAI/Gemini/...), images, scripted (tests)
  harness/    config (roles), tools (workspace), agent loop, orchestrator
  prompts/    default role prompts (override with prompts_dir)
  cli.py          `agent-hub` command
  harness_cli.py  `harness` command
```
