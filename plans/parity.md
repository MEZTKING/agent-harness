# Parity: what Munder Difflin and DSH Mobile do that Roundtable doesn't yet

The owner (27 November 2026): "Munder Difflin – an 'office' of AI agents you can watch at work; DSH
Mobile – the DeepSeek Harness on a phone: look at these and then see what they have and see what we
don't have, and make sure we can do everything that these other harnesses can do."

Read from the owner's two forks (both MIT): `MEZTKING/munder-difflin` (version 0.6.0) and
`MEZTKING/deepseek-harness-mobile` (0.24.0, driving DeepSeek Harness 0.2.2). Every feature below was
checked in their code, not only their documents, and every "Have" was checked in Roundtable's code
(branch `ccr-fca0772b-7ma69z`, Roundtable 0.9.0). Ideas already picked from them are in
[inspiration.md](inspiration.md); this list is the full count.

**How to read the tables.** *Have*: Roundtable does it (where). *Partly*: some of it (what's missing).
*Missing*: not at all. *Not wanted*: left out on purpose (why). "Theirs" is where it lives in their
code, for builders.

## Summary

| Project | Features | Have | Partly | Missing | Not wanted |
|---|---|---|---|---|---|
| Munder Difflin | 92 | 50 | 25 | 9 | 8 |
| DSH Mobile + the DeepSeek Harness | 80 | 52 | 16 | 5 | 7 |
| **Both** | **172** | **102** | **41** | **14** | **15** |

*Statuses refreshed for 0.12.0 (27 November 2026), after waves 1–3; each changed row names its wave. When
this list was first written (0.9.0) the count was 47 have, 55 partly, 55 missing.*

In one sentence: Roundtable is ahead on planning, proof, money and the phone-and-PC link, and behind
on **working on many things at once**, **stopping a stuck or risky agent mid-task**, **seeing time and
context**, and the **"session" tools** (terminal, files, rewind, attachments, search, schedules).

One thing found while checking, and it matters now: **a worker's shell commands can read the API
keys.** The desktop app loads the keys into its environment at start (`desktop.py`), and
`run_command` (`harness/tools.py`) passes the whole environment to every command, so a model that
runs `env` sees them. Munder Difflin keeps keys away from agents with a broker. Slice 3 fixes this;
it's first in the ranking below.

---

## 1. Munder Difflin

### Agents and orchestration

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-01 | One orchestrator you talk to ("Michael") | You say what you want; it hands each piece to the right agent | `src/main/hive.ts`, `src/shared/godBoot.ts`, `godCommand.ts` | **Have**: the planner and the project chat with steer (`harness/orchestrator.py` `steer`, `chat_history`; `ui/static/project.js`) |
| MD-02 | Agents are real coding CLIs | Claude Code, Codex, Gemini CLI, Grok, Copilot, Cursor, OpenCode and more, each signed in with your own subscription | `src/shared/agentProvider.ts`, `engine.ts`, `src/main/pty.ts` | **Have**: Claude Code and Codex as workers on your own subscriptions (`providers/cli_engine.py`, wave 2) |
| MD-03 | Mix engines in one office | Each agent picks its own engine and model | `src/shared/engineOptions.ts` | **Have** (by API): each role has its own models and fallbacks (`harness/config.py`, `routing.py`) |
| MD-04 | API keys and local models | Ollama, LM Studio, vLLM, any key | `components/AiEnginesSettings.tsx` | **Have**: `providers/openai_compat.py`, `providers/catalog.py`, Settings → keys |
| MD-05 | Hire an agent: name, role, model, face | A person-like agent you can name and keep | `components/AddAgentModal.tsx`, `src/shared/hire.ts` | **Partly**: jobs (roles) with plain names in Models (`routing.py`); no agent that keeps a name, face and memory across projects |
| MD-06 | Agent Gallery and shareable hires | Ready-made agents to browse; share one as a file or link | `src/shared/hire.ts` (`hire@1` manifest, `munderdifflin://hire` link), `docs/hires/` | **Have** (on trial): kinds as folders of data, shared as `.rtkind` files, and the Gallery of finished work (`kinds/`, `static/gallery.js`, the phone's Gallery; wave 3) |
| MD-07 | Temps: an agent hired for one job | Spawned for a task, torn down after | `src/shared/tempAgent.ts` | **Have**: every task is a fresh model conversation (`harness/agent.py` `run_agent`) |
| MD-08 | A prep assistant ("Dwight") | Gathers repo context and rewrites your request before the orchestrator sees it | `src/shared/broadcast.ts`, CHANGELOG "Dwight" | **Partly**: the repo's rules, references and the critic (`harness/reporules.py`, `scout.py`, `orchestrator._critique`); nothing rewrites the idea first |
| MD-09 | Prefer an agent that already fits | Routes to an existing agent by name or fit before hiring | CHANGELOG "Orchestrator delegates opportunistically" | **Have**: tasks go to roles by kind of job (`harness/config.py` roles) |
| MD-10 | Agent-to-agent mail | Agents ask and tell each other things | `src/main/hive.ts` (outbox → inbox) | **Have**: hub messages (`hub/service.py`, MCP `hub_send`, `hub_reply`) |
| MD-11 | Message types, threads, hop cap, bounce | Stops two agents ping-ponging; mail to nobody comes back | `HIVE.md` §4, `src/shared/broadcast.ts`, test `hive-hop-cap` | **Partly**: kinds and threads (`hub/service.py`, `core/models.py`); no hop cap, no bounce |
| MD-12 | Broadcast to everyone | One message to all agents | `src/shared/broadcast.ts` | **Partly**: send to several agents at once (`/api/send`); no "everyone" |
| MD-13 | Shared board (blackboard) | One plan every agent reads and the orchestrator writes | `hive/board.md` | **Have**: the living plan (`harness/plandoc.py`) and project cards |
| MD-14 | Task board with dependencies | Todo, doing, blocked, done; assignee, priority, depends on | `components/TasksKanban.tsx`, `src/shared/taskLedger.ts` | **Partly**: task list with depends-on and status (`ui/static/plan.js`, `project.js`); no board view, no moving a card by hand |
| MD-15 | Task ids on every card | "bmt-12" to refer to | CHANGELOG "Tasks show their id" | **Have**: task numbers in the plan and Watch |
| MD-16 | Task hygiene | Fields kept when an agent rewrites, done cards archived, waiting-on-you never "stale" | `src/shared/taskHygiene.ts` | **Partly**: tasks live in `.harness/tasks.json`, written only by the orchestrator; no archive of old goals' tasks |
| MD-17 | Agents carry on by themselves | An agent that finishes reads its mail and keeps working | `HIVE.md` §5 (Stop hook) | **Have**: the run goes task after task (`orchestrator.run`); connected Claude Code sessions get hub mail at start and stop (`connect.py` hooks) |
| MD-18 | Idle agents sleep and wake | Saves resources; a Wake button | `components/SleepOverlay.tsx`, `src/main/workerWake.ts` | **Not wanted**: Roundtable keeps no idle processes; a task ends when it's done |
| MD-19 | Heartbeat and watchdog | Wakes an agent sitting on unread mail | `src/main/workerWake.ts`, `staleAgents.ts` | **Not wanted**: same reason; the desktop's one-minute auto-sync covers the hub |
| MD-20 | Each agent in its own git worktree | Agents on one repo never trip over each other's branches | `src/main/agentWorktree.ts`, `worktreeAdmin.ts` | **Have**: several tasks at once, each in its own git worktree (`harness/worktrees.py`, wave 1) |
| MD-21 | Safe worktree clean-up | A worktree with uncommitted work is kept, and says why | `src/shared/worktreeFate.ts`, `worktreeList.ts` | **Have**: a worktree goes only when merged and clean, with its reason kept (wave 1; the daily tidy-up, wave 2) |
| MD-22 | Dependencies linked into worktrees | A new worktree doesn't reinstall `node_modules` | `src/main/worktreeDeps.ts` | **Partly**: each worktree runs the project's setup (`worktrees._lane_baseline`, wave 1); nothing is linked in |
| MD-23 | Restore the team after a restart | One click brings every agent back where it was | `src/main/lastSessionSave.ts`, `src/shared/resumeStore.ts` | **Have**: a run resumes from `.harness/` exactly where it stopped (`orchestrator.py`) |
| MD-24 | Handoff per piece of work | Each agent writes what it did, so the next one picks up | `src/shared/handoff.ts`, `src/main/handoffJob.ts` | **Partly**: the hub journal's "where was I" and session-end hooks (`hub/journal.py`, `connect.py`), the repo's HANDOFF read (`reporules.py`); a task that splits doesn't leave a written handoff for the next |
| MD-25 | A clean start when work changes | Handoff, then clear, when an agent switches to other work | `src/shared/switchClear.ts` | **Have** by design: each task starts a new conversation |
| MD-26 | Compaction | Old turns summarised when a conversation gets big | `src/shared/contextTriggerDecide.ts`, `src/core/contextTriggerTimer.ts` | **Have**: a long task's older steps summed up (built-in plugin `compactor`, wave 2) |
| MD-27 | House response style, editable | Every agent answers short, factual, plain; you can edit the rules | `src/shared/responseStyle.ts`, `components/ResponseStyleSection.tsx` | **Partly**: prompts in code plus learned prompts (`improve/lab.py`); no "house style" box in Settings |
| MD-28 | Several floors (windows) | Separate groups of agents side by side | CHANGELOG "Multi-window floors" | **Have** (another form): every project is a seat in the Hall (`ui/hall.py`) |

### Watching the work

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-29 | The office floor in pixel art | Agents walk to the shelf, the terminal, the mailbox | `src/renderer/src/scene/office`, LimeZu tiles | **Not wanted**: the art isn't open (LICENSE-ASSETS); the Hall with its painted table is ours (`ui/static/hall.js`) |
| MD-30 | What each agent is doing, at a glance | Thinking, working, blocked, done | `SPEC.md` §4, `components/AgentCard.tsx` | **Have**: seat status in words (`ui/hall.py`, `ui/roundtable.py`) |
| MD-31 | "Looping" and "compacting" states | The floor shows when the safety layer steps in | CHANGELOG "New avatar states" | **Partly**: the breaker (wave 1) and compaction (wave 2) exist; Watch has no line for "compacted" yet |
| MD-32 | Live terminal for every agent | Watch the real output byte for byte, type into it | `components/PtyTerminalView.tsx`, `src/main/pty.ts` | **Have** (beta on Windows): a project's Command line tab on the PC, and each task's command as it prints with a Stop (`terminal.py`, `harness/livecmd.py`, wave 3) |
| MD-33 | Fleet grid | Every agent's state, tokens, cost in one grid | `src/core/fleet.ts`, `components/WorkersTab.tsx` | **Have**: the Hall and Today (`ui/roundtable.py`) |
| MD-34 | Tool-span waterfall | Which tool calls ran, in what order, for how long | `components/ToolWaterfall.tsx` | **Have**: where each task's time went, and the time of every step (Watch, waves 1 and 2) |
| MD-35 | Activity feed | Everything that happened, newest first | `hive/log.jsonl`, Activity tab | **Have**: `ui/static/activity.js`, `/api/activity`, `.harness/events.jsonl` |
| MD-36 | Threaded messages per agent | Conversations with reply chains and a reply box | `components/ThreadsPanel.tsx` | **Have**: Letters (`ui/static/letters.js`, `/api/thread`) |
| MD-37 | Clickable paths and markdown previews | A path in the output opens; plans read as formatted text | `src/shared/terminalPaths.ts`, `src/renderer/src/markdown` | **Partly**: markdown on the phone (`MarkdownView.kt`); paths in Watch don't open the file |
| MD-38 | Desktop notifications | A native pop-up when an agent finishes or needs you | CHANGELOG "Desktop notifications" | **Have**: the bell and pop-ups (`notify.py`, `static/notify.js`, wave 1) |
| MD-39 | Top bar with version, auto mode, limits, theme | The state of the whole app in one line | CHANGELOG "A top bar" | **Have**: Today, Autopilot, theme, settings (`ui/static/app.js`) |
| MD-40 | Focus and full-screen views | One agent's terminal full screen | `components/FullscreenTerminal.tsx` | **Partly**: a project page is full screen; no focus mode for one task |

### Approvals and safety

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-41 | "Ask me" queue | Questions with options, a recommendation and markdown, a bell and a badge | `components/AskMeTab.tsx`, `src/shared/askOptions.ts`, `humanAsk.ts` | **Have**: Needs you cards (`asks.py`, `ui/static/needs.js`, `mobile/.../ui/AskCard.kt`) |
| MD-42 | Answer several asks at once | Clear a pile of questions in one go | `components/askMeBulk.ts` | **Partly**: autopilot answers with the recommended choice (`autopilot.py`); no "answer these five" by hand |
| MD-43 | Only critical things reach you | Spend, deletion and scope changes ask; routine ones don't | `HIVE.md` §6 | **Have**: autopilot's rules and `confirm` on risky options (`autopilot.py`, `asks.py`) |
| MD-44 | Mid-run control through the CLI's hooks | Pause, refuse a tool, steer, stop cleanly, without typing into the terminal | `src/main/control.ts` | **Have**: Ask me first holds one command until you say (`harness/gate.py`) and the breaker stops a task mid-run (wave 1); an instruction can reach the task working now (wave 2) |
| MD-45 | Circuit breaker | Steer → limit → stop on loops, error storms, runaway spend | `src/main/breaker.ts` | **Have**: loops, error storms, huge output and no progress (`harness/breaker.py`, wave 1) |
| MD-46 | Token cap per agent | One agent can't run up the bill | `src/shared/tokenCaps.ts`, `tokenLimits.ts` | **Partly**: the breaker's token limit for a task (wave 1); no cap per job across tasks |
| MD-47 | Usage limits per engine | How much of your subscription is left | `src/main/usageLimits.ts`, `components/limits` | **Partly**: the real balance where a provider reports one (`providers/balance.py`, DeepSeek); none for others |
| MD-48 | Permission mode per agent | Default, accept edits, bypass, plan | `SPEC.md` §5, `src/shared/agentRole.ts` | **Partly**: Ask me first per project – off, risky or all (wave 1); not per job |
| MD-49 | One committer, retries, stale lock | Git never corrupts under many writers | `src/core/gitSafe.ts`, `src/main/hiveCommitQueue.ts` | **Have**: `core/store.py` GitStore, `sync.py` settling clashes file by file |
| MD-50 | One place that deletes | A retention sweep is the only thing that removes files | `src/main/retention.ts`, `src/shared/retention.ts` | **Have**: one daily tidy-up is the only thing that deletes (`retention.py`, wave 2; rewind's old ways back after 30 days, wave 3) |
| MD-51 | Stray processes cleaned up | Agents left running by a crash are found and stopped | `src/main/staleAgents.ts`, `procKill.ts` | **Have**: a task's commands are listed while they run and stopped after the run or with Stop (`harness/livecmd.py`, wave 3) |
| MD-52 | Keys through a broker | Agents call a local address and never see a key; a new key reaches running agents | `src/main/integrationBroker.ts`, `agentSecrets.ts` (`md-secret`) | **Have**: keys never reach the helpers' commands (`harness/safeenv.py`, 0.9.2) |
| MD-53 | Secrets hidden from output | Key-shaped text never shown | `src/shared/redactSecrets.ts` | **Have**: Watch and the hub hide key-shaped text (`harness/session.py`) |
| MD-54 | A locked-down window | Sandbox, no Node in the page, path-checked file access | `SECURITY.md`, `src/main/navigationGuard.ts` | **Have**: CSP, Host check, write header, files served from one folder (`ui/server.py`, `harness/showit.py` `safe_path`) |

### Memory

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-55 | Each agent's own memory | Read at start, added to as it learns | `hive/agents/<id>/memory.md`, `src/main/memory.ts` | **Partly**: a memory for each project and for this computer (`memory.py`, wave 2); none for a named agent |
| MD-56 | Shared semantic memory search | "What did we decide about X?" across everything | `src/main/memory.ts` (MemPalace) | **Missing** |
| MD-57 | Text search over plans, tasks and memory | Find any word in the office's files | `components/MemoryPanel.tsx` | **Have**: one search over plans, tasks, journal, letters, memory, notes and files (`search.py`, wave 2) |
| MD-58 | Memory kept small without a model | Old notes move word for word to an archive that's searched | `src/main/reflect.ts`, `memoryIndex.ts` | **Missing** |
| MD-59 | Memory graph | Who talks to whom, who knows what, as a picture | `components/MemoryGraphPanel.tsx`, `MEMORY_GRAPH_SPEC.md` | **Missing** |
| MD-60 | Knowledge base of your own documents | Agents look up your facts instead of guessing | `src/main/knowledge.ts`, `kg-core.cjs` | **Partly**: "Make it like this" reads links and repos (`harness/refstage.py`, `scout.py`); no store of your own documents |
| MD-61 | Choose where the data lives | Pick the folder, with a safe move | CHANGELOG "Configurable hive/memory home folder" | **Partly**: choose the hub and the projects folder in Settings; no "move it there" |

### Models, providers and costs

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-62 | New models without a release | The model list is fetched from one file | `src/main/modelCatalog.ts`, `docs/model-catalog.json` | **Have**: models found live from each provider (`providers/catalog.py`), OpenRouter prices fetched (`providers/prices.py`) |
| MD-63 | Real tokens and cost, for the app's lifetime | Per agent, per model | `src/main/costLifetime.ts`, `tokenUsage.ts` | **Have**: cost per step, spend, real balance, the cost log (`plugins/builtin/cost_log.py`) |
| MD-64 | OpenTelemetry collector | Usage fed in by the CLIs' own telemetry | CHANGELOG "Live OTel telemetry" | **Not wanted**: Roundtable makes the calls itself and counts them directly |
| MD-65 | Prerequisites page | Is git, Node, uv, each engine ready? Install buttons | `components/settings`, `src/main/cliReadiness.ts` | **Have**: the Tools page finds and installs what projects need (`prereq.py`, wave 1) |
| MD-66 | Engines install themselves | A missing CLI or Node is installed, checked against its signature | `src/main/cliInstall.ts`, `nodeInstall.ts` | **Missing** (comes with MD-02) |
| MD-67 | Change a model and keep the session | Switch model without losing the conversation | CHANGELOG "Changing an agent's model within the same provider resumes" | **Have**: routing changes apply to the next call (`routing.py`) |

### Proof, tests and git

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-68 | Before and after on every change | No merge without screenshots or a recording | `.github/workflows/pr-evidence.yml`, `test/pr-evidence-gate.test.cjs` | **Have**: pictures before and after, the tests before and after, and a model that can see as advice (`harness/proof.py`, wave 3) |
| MD-69 | Tests with fake engines | The whole app tested without a paid key | `test/`, `test/fixtures` | **Have**: scripted provider (`providers/scripted.py`), `tests/` |
| MD-70 | Git history in the app | Commit graph, diffs per file, branch compare, guarded checkout | `src/renderer/src/ide/GitPanes.tsx`, `components/GitTab.tsx` | **Partly**: a history of what each task changed, with Undo and Try another way (`harness/rewind.py`, wave 3); no full git log |
| MD-71 | GitHub issues become work | Pull open issues and give one to an agent in a click | `src/main/github.ts` (`gh issue list`) | **Have**: an issue with your label starts a plan (`automation.py`, wave 1) |
| MD-72 | CI status | Live pass/fail of GitHub Actions for each repo | `src/main/github.ts` (`gh run list`) | **Partly**: a failed check can start work (automations, wave 1); CI status isn't shown |
| MD-73 | Worktrees panel | Every worktree, its branch, what's uncommitted | `components/WorktreesPanel.tsx` | **Partly**: kept worktrees with their reason (wave 1); no panel |

### Files, editor and composer

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-74 | Files and an editor | Browse and edit an agent's folder (Monaco) | `components/FilesTab.tsx`, `src/renderer/src/ide/` | **Partly**: browse and open a project's files, save a copy (`ui/filesapi.py`, wave 2); no editor |
| MD-75 | Attach files and pictures to a message | Paste or drop a picture into what you send | `components/pasteAttachments.ts`, `MessageQueueComposer.tsx` | **Have**: the message box takes pictures and files (`attachments.py`, wave 2) |
| MD-76 | Message queue with "send now" | Your messages wait while the agent is busy; nothing overwrites a draft | `docs/message-queue.md`, `src/main/submitMessageFile.ts` | **Partly**: Next task or Now (wave 2); no queue you can see |

### Scheduling, automation and integrations

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-77 | Scheduled missions | "Every Monday at 9" or every hour, to an agent | `src/shared/weeklySchedule.ts`, `src/shared/triggers.ts` | **Have**: schedules (`automation.py`, wave 1) |
| MD-78 | Hourly stand-up | The orchestrator checks every agent and tidies their context | CHANGELOG "Hourly ops standup" | **Missing** |
| MD-79 | Triggers page | Every schedule and webhook, last and next run | `components/triggers`, `src/main/triggerHistory.ts` | **Have**: Settings → Automations: schedules, issues and failed checks (wave 1) |
| MD-80 | Inbound webhooks | GitHub, Linear, Telegram or your own start work | `src/main/webhook.ts`, `serviceWebhooks.ts` | **Missing** |
| MD-81 | A public tunnel | Webhooks reach your computer from the internet | `src/main/tunnel.ts` | **Not wanted**: an open door into the PC; the hub (GitHub) already carries commands in |
| MD-82 | Slack | Send work from a thread, the answer comes back there | `src/main/slack*.ts` | **Not wanted** for now: the phone and the hub do this for one owner (decision below) |
| MD-83 | Integrations registry | Each service's settings in one list, used by every agent | `src/shared/integrations.ts`, `components/integrations` | **Missing** (comes with MD-52) |

### Plugins, skills and MCP

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-84 | MCP servers per agent, from a catalog | Give an agent extra tools with a tick | `components/AgentMcpGrants.tsx`, `src/shared/mcpCatalog.ts` | **Partly**: the Tools page adds, tests and gives MCP servers to jobs (wave 1); no catalogue |
| MD-85 | Skills catalog | 227 skills to search, install and remove | `src/main/skills.ts`, `components/SkillsTab.tsx` | **Missing**: plugins are the nearest (`plugins/`) |
| MD-86 | Hooks from the CLIs | The app hears every tool call and stop | `src/core/hookServer.ts` | **Have** for Claude Code sessions joined to the hub (`connect.py` hooks) |
| MD-87 | Reach everything from the phone | `/remote-control` on the whole floor | `HIVE.md` §2 | **Have**: Roundtable Mobile and hub commands (`remote.py`, `phone.py`) |

### Voice, appearance, telemetry, updates

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| MD-88 | Talk to the orchestrator by voice | A spoken conversation that reads the floor and acts after you confirm | `src/renderer/src/realtime/`, `src/main/realtime*.ts` | **Missing** (decision below) |
| MD-89 | Light and dark | Follows the computer | `DESIGN.md`, `src/shared/grokTheme.ts` | **Have**: `ui/static/theme.js`, Candlelit Oak light and dark |
| MD-90 | Chinese and Arabic | The whole app in other languages, right to left | `src/renderer/src/i18n` | **Not wanted**: the owner reads British English (CLAUDE.md) |
| MD-91 | Anonymous usage counts | The makers learn what's used | `src/main/analytics.ts`, `TELEMETRY.md` | **Not wanted**: nothing goes to outside services (privacy rule) |
| MD-92 | Release drops: "what's new" page | A designed page of what changed, on first start | `src/shared/releaseDrop.ts`, `components/ReleaseDrop.tsx` | **Have**: What's new shows once after an update (`ui/whatsnewapi.py`, wave 2); also "Updates" (**Have**: `updater.py`, the Windows installer) |

(Setup wizard, one Save button, editable names and crash recovery are matched too: `ui/static/settings.js`
welcome steps, Settings, hub titles, the phone's safe mode `Crash.kt`. They're folded into the rows above.)

---

## 2. DSH Mobile and the DeepSeek Harness it drives

DSH Mobile is a phone app for a coding agent (the DeepSeek Harness). So most of its features are the
harness's: sessions, tools, subagents, plan mode, jobs, approvals, terminal, files, rewind. Its wire
calls are in `docs/PROTOCOL.md` (`session/*`, `subagents/*`, `job/*`, `terminal/attach`,
`workspaceFiles/*`, `schedule/*`, `pluginManager/*`, `userQuestions/*`). App code is under
`app/src/main/java/com/labteto/dshmobile/` (shortened below to `app/`).

### Connecting and running

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-01 | Connect by pasting one link | The link the harness prints signs you in | `app/connection/LoopbackSignIn.kt`, `ui/screens/connect` | **Have**: scan the QR code, paste the pairing link, or find the PC on the Wi-Fi and type its code (wave 3) |
| DS-02 | Same Wi-Fi | Talk to the computer directly | `app/connection/ConnectionManager.kt` | **Have**, safer: TLS always, pinned (`phone.py`, `PinnedTls.kt`) |
| DS-03 | Away from home | A relay with a password, encryption and pairing | sorsama/deepseek-harness-relay, `docs/PROTOCOL.md` "Relay" | **Have** (another form): Hub mode works anywhere through the private GitHub hub (`GitHubHub.kt`); Tailscale for PC mode |
| DS-04 | Find the computer on the network | Scan, or mDNS discovery | `app/connection/MdnsDiscovery.kt`, `DiscoveryEngine.kt` | **Have** (beta until tried at home): Look for my PC, and Look for it when its address changed (`discovery.py`, `net/Discovery.kt`, wave 3) |
| DS-05 | Your own HTTPS reverse proxy | Use your own proxy's address | `harness/README.md` | **Not wanted**: pinned TLS is built in |
| DS-06 | Termux mode | Run the harness in Termux, started by the app | `app/termux/` | **Not wanted**: This phone replaces it |
| DS-07 | The harness on the phone itself | No computer needed: a small Linux in the app, signed download | `app/runtime/`, `harness/ON-DEVICE.md` | **Have**: This phone (beta) (`onphone.py`, `runtime/`, `mobile/.../runtime/`, borrowed and credited) |
| DS-08 | Harness updates without an app update, with going back | A new version arrives on its own; a broken one rolls back | `app/runtime` (CHANGELOG 0.22.0) | **Partly**: runtime releases are found and installed (`ReleaseFinder.kt`); no automatic "previous one is back" |
| DS-09 | Keep connected in the background | A foreground service, plus a checklist for battery settings | `app/connection/ConnectionService.kt`, `KeepAliveWorker.kt` | **Partly**: This phone runs as a foreground service (`HarnessRuntimeService.kt`), Needs you checked every 15 minutes (`work/Watch.kt`); no battery checklist |
| DS-10 | Several harnesses remembered | Recent hosts, reachable or not | `app/connection/HostsStore.kt` | **Have**, more: several connections at once (`data/MultiBackend.kt`) |
| DS-11 | Every failure named, with one fix | "Pair again", "Not enough space…" | `harness/ON-DEVICE.md` troubleshooting | **Partly**: plain errors on the phone; not every failure has its own message and fix |
| DS-12 | Sign-in stored encrypted | The token is never in plain text | `app/connection/RelayCredentialStore.kt` | **Have**: `mobile/.../data/Store.kt` (Android Keystore) |

### Chat and sessions

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-13 | Chat with streaming replies | Words appear as written, with reasoning and code blocks | `ui/screens/main/ChatTranscript.kt` | **Partly**: chat with a project's planner and the live Watch view; replies arrive whole, the thinking isn't shown |
| DS-14 | Attach photos and files | Send a picture with your message | `ui/screens/main/Composer.kt`, `fileUploads/upload` | **Have**: pictures and files with a message or an idea (wave 2) |
| DS-15 | `@` references | Mention a file, folder or session in a message | `ui/screens/main/ReferencePicker.kt` | **Have**: @file in the message box (wave 2) |
| DS-16 | `/` commands and skills menu | Run a command from the message box | `ui/screens/main/SheetCommands.kt`, `commands/execute` | **Missing** |
| DS-17 | Press and hold for actions | Copy, edit and resend, mention a file | `ui/screens/main/HoldActions.kt` | **Have**: press and hold a sent message: copy, or edit and send again (wave 3) |
| DS-18 | Starter prompts | An empty project offers ideas to tap | CHANGELOG "Starter prompts" | **Have**: the wizard's cards, and each kind's example ideas in the Gallery (wave 3) |
| DS-19 | Sessions drawer: order, group, pin, archive, search | Keep the list your way | `ui/screens/main/ChatListDrawer.kt`, `SessionReorder.kt`, `SessionSearch.kt`, `ArchivedSessions.kt` | **Partly**: pin and put away projects (wave 3), search (wave 2); no reordering by hand |
| DS-20 | History of what you sent | Jump back to any prompt | `ui/screens/main/SessionHistory.kt` | **Have**: the last 50 messages per project, on the phone (`ui/SentHistory.kt`, wave 3) |
| DS-21 | Fork a session | Try another way from any point | `session/fork` | **Have**: Try another way: a separate copy from any task (`harness/rewind.py` `fork`, wave 3) |
| DS-22 | Rewind | Undo to a message: the conversation only, or the code too, with the files it will restore | dsh-rewind-plugin, CHANGELOG "A rewind picker" | **Have**: Undo this task or go back to before it, files shown first, Put it back for 30 days (wave 3) |
| DS-23 | Changed files card | "Changed 3 files" after a turn; tap to open | `ui/screens/main/ChangedFiles.kt` | **Have**: the files each task changed, folded (Watch, wave 2) |
| DS-24 | Tool calls read as what they did | "Read app.js", not JSON; raw on request | `ui/screens/main/ToolCardMapping.kt`, `ChatToolViews.kt` | **Have**: `harness/session.py` (● Read · ● Edit (+12 −3) · ● Run) |
| DS-25 | How much detail the chat shows | Compact, Standard, Detailed, Fully expanded | `ui/screens/main/WorkStepPresentation.kt` | **Have**: Compact, Standard or Detailed (phone Comfort, wave 3) |
| DS-26 | Drafts survive | A half-typed message is never lost | `ui/screens/main/DraftPrefill.kt`, `QuestionDrafts.kt` | **Have**: drafts are kept (wave 2) |
| DS-27 | Queue or steer while it works | "Next turn" or "into this turn", with a default | `app/connection/DeliveryMode.kt`, `ComposerDelivery.kt` | **Have**: Next task or Now (wave 2) |
| DS-28 | Goals | A goal the agent works towards; done or blocked | `/goal`, Details panel | **Have**: a project's goal, and "extend with a new goal" (`orchestrator.py`) |
| DS-29 | Plan mode and plan review | Read the plan before it starts; approve or decline | `ask_user_question` `plan-review` | **Have**, deeper: the living plan with choices, critique and estimate (`harness/plandoc.py`) |
| DS-30 | Todo list | What the agent will do next | Details panel, "todo lists" | **Have**: the task board (`ui/static/plan.js`) |
| DS-31 | Subagents: read them, send a follow-up | See what a helper did and tell it more | `ui/screens/main/SheetSubagents.kt`, `subagents/prompt` | **Partly**: every task's steps in Watch; no follow-up to one task's model |
| DS-32 | Agent teams (beta) | Teammates and a shared board: waits on, files each plans to change, who owns it, overlap warnings | `ui/screens/main/SheetAgentTeam.kt`, `docs/PROTOCOL.md` "Agent Teams" | **Partly**: roles, a task board with depends-on, several tasks at once (wave 1); no files-to-change per task |
| DS-33 | Background jobs: list, stop, follow | A long command runs apart; watch or stop it | `ui/screens/main/JobOutputSheet.kt`, `job/kill`, `job/follow` | **Have**: desktop Jobs with live logs, and a task's command followed and stopped (wave 3) |
| DS-34 | Where a turn's time went | Waiting for the first word, writing, tools, waiting for you | `ui/screens/main/TrajectoryOverview.kt`, `TrajectoryTab.kt` | **Have**: where each task's time went (wave 2) |
| DS-35 | Context and usage card | Tokens in and out, cache hit rate, context full | `ui/screens/main/UsageCard.kt` | **Have**: tokens, the context gauge and the cache share (wave 2) |
| DS-36 | Balance in a second currency | "$54.12 · ≈ £42" | `app/rates/ExchangeRateRepository.kt` | **Not wanted**: an outside rates service for a small convenience (decision below) |
| DS-37 | Feedback on a message | A note on what was good or bad | `ui/screens/main/FeedbackDialog.kt`, `messageFeedback/put` | **Have**: 👍/👎 on results feeds self-improvement (Runs page, `improve/analysis.py`) |
| DS-38 | Translate the thinking | Read reasoning in your language | `ui/screens/main/ReasoningTranslation.kt` | **Not wanted**: English only |
| DS-39 | Compact a long session | `/compact` summarises old turns | `commands/execute` `/compact` | **Have**: compaction (wave 2) |

### Approvals and safety

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-40 | Approve or reject a command, shown in full | Nothing risky runs without you | `approval/request`, `ui/screens/main/ModernQuestions.kt` | **Have**: Ask me first cards show the whole command (wave 1) |
| DS-41 | "Run it" or "Ask me first" | Choose per phone how commands run | `harness/ON-DEVICE.md` "Commands" | **Have**: off, risky or all (`harness/gate.py`, wave 1) |
| DS-42 | Permission presets | Auto review, ask, allow; a sandbox where there is one | `permissionPresets/catalog`, `SheetPermission.kt` | **Partly**: off, risky or all, per project (wave 1); no presets per job |
| DS-43 | Questions with options and your own words | Tap an answer or type one | `userQuestions/answer` | **Have**: `asks.py` (options, recommended, Other) |
| DS-44 | Timed questions | A countdown; editing holds it; late answers still count | `userQuestions/attachWait` | **Partly**: answers are bound to the question's version (`stamp`); no timers |
| DS-45 | Too long to show means not run | A command over 256 KB isn't asked, so isn't run | `harness/ON-DEVICE.md` | **Missing** (comes with DS-40) |
| DS-46 | Approval reasons in your language | Why it's asking, translated | `approval/request` `displayReason` | **Not wanted**: English only |

### Terminal, files and previews

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-47 | Terminal on the computer | A real shell, from the phone | `ui/screens/main/TerminalPanel.kt`, `terminal/attach` | **Partly**: a command line on the PC (wave 3); never from the phone (decided: the phone gets a task's output and a Stop) |
| DS-48 | Browse the workspace | Folders and files of the project | `ui/screens/main/WorkspacePanels.kt`, `workspaceFiles/list` | **Have**: the Files screen on the desktop and the phone (wave 2) |
| DS-49 | Search the workspace's files | Find a file by name or text | `ui/screens/main/WorkspaceSearch.kt` | **Have**: search covers the project's files (wave 2) |
| DS-50 | Full-screen preview of many file types | CSV tables, JSON trees, notebooks, PDFs, pictures, video, audio, archives, find in file | `ui/screens/main/preview/` | **Partly**: pictures (pinch to zoom), markdown, downloads of apk/zip/exe (`LiveTab.kt`, `watch.js`) |
| DS-51 | Markdown drawn like GitHub | Tables, badges, code with colours | `ui/screens/main/DocumentFrontmatter.kt`, CHANGELOG 0.20.0 | **Partly**: `MarkdownView.kt`, `data/Markdown.kt`; plain tables and code |
| DS-52 | Save a copy of any file | Put it on the phone | CHANGELOG "Save a copy" | **Have**: save a copy of any file (wave 2) |
| DS-53 | Browser tab for local addresses | Open `localhost:5173` the agent started | `ui/screens/main/browser/` | **Partly**: the Live tab runs the app from its folder (`ui/live.py`, `LiveTab.kt`); apps started with a command aren't shown yet |
| DS-54 | Office files to PDF | Open a Word or Excel file | `officeToPdf/render` | **Missing** |
| DS-55 | Projects on the phone | New, clone a repo (private with a token), import a folder or zip, share as zip, Files app | `app/runtime/workspace/` | **Partly**: This phone builds projects from an idea and syncs the hub; no clone, import or share |

### Models, settings, plugins and automation

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-56 | Models and keys in the app | Ready or Needs a key; paste and save | `ui/screens/models`, `credentials/set` | **Have**: Settings → keys with Test (desktop), the phone's first-start key |
| DS-57 | Provider account and balance | Sign in to DeepSeek; see the balance | `account/getState`, `ui/screens/main/BalanceEstimate.kt` | **Have**: real balance (`providers/balance.py`, `roundtable balance`) |
| DS-58 | Pick the model and effort | Per session, with reasoning effort | `ui/screens/main/SheetModels.kt`, `session/selectModel` | **Have**: Models page per job and set, effort option (`routing.py`, `providers/anthropic_provider.py`) |
| DS-59 | Agent presets, and what's in them | Ready-made agents; see their parts | `ui/screens/main/PresetCompositionPage.kt` | **Have**: Budget, Balanced and Quality, and kinds that say what they switch on (wave 3) |
| DS-60 | The harness's own settings | Web search, shell, subagents, loop, log | `ui/screens/harnesssettings` | **Partly**: Settings, project settings and web search's own settings (wave 3); no subagent settings |
| DS-61 | Web search for agents | The agent looks things up | Harness "Web search" setting | **Have**: web_search and web_read for the builders and the planner (`harness/websearch.py`, wave 3) |
| DS-62 | Plugin manager | List, install, switch on and off, remove | `ui/screens/main/PluginManagerScreen.kt` | **Have**: `plugins/manage.py`, Settings → Plugins |
| DS-63 | Plugin market | Browse and install from a list | `ui/screens/main/PluginMarketBrowser.kt` | **Missing** (plans/gaps.md) |
| DS-64 | Create a plugin | A session set up to make one | CHANGELOG "Create plugin" | **Missing** |
| DS-65 | Scheduled tasks | A list with rules and a record of every run; edit, pause, delete | `ui/screens/main/Automation*.kt`, `schedule/*` | **Have**: automations on a schedule (wave 1) |

### Notifications and the phone app itself

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-66 | Notifications for each kind of news | Turn finished, goal done or blocked, waiting for you; separate channels; a tap opens it | `app/notify/DshNotifications.kt`, `NotificationObserver.kt` | **Have**: finished, needs you, failed, money, idle (`notify.py`, wave 1) |
| DS-67 | Answer from the notification | Allow or reject without opening the app | inspiration.md (their four-line rule) | **Have**: answer buttons on the notification (wave 1) |
| DS-68 | The app updates itself | Downloaded, checked against checksum and signature, installed | `app/update/` | **Have**: `mobile/.../update/` (borrowed and credited) |
| DS-69 | Tablets, foldables, Chromebooks | The layout follows the window | `ui/adaptive/ShellPlan.kt`, `docs/ADAPTIVE.md` | **Partly** (beta): a rail or two panes by the screen's width (`ui/adaptive/`, wave 3); a foldable's hinge isn't read yet |
| DS-70 | iPhone | The same app on iOS | `iosApp/`, `docs/IOS.md` | **Not wanted**: the owner's phone is Android |
| DS-71 | A theme you tune | Accent colour, true black, text size | `ui/screens/settings`, `PRODUCT.md` | **Have**: accent colour, true black and text size (phone Comfort, wave 3) |
| DS-72 | Haptics | The phone confirms a tap | CHANGELOG "Haptic strength" | **Have**: off, light or strong (phone Comfort, wave 3) |
| DS-73 | Eleven languages, right to left | | `sharedUi/.../composeResources/values-*` | **Not wanted**: English only |
| DS-74 | Dictation | Speak a message into the box; nothing sent until you send | `ui/voice/`, `ComposerDictation.kt` | **Have**: Speak in the message box (wave 2) |
| DS-75 | One search field everywhere | Sessions, models, commands, plugins, schedules, files | CHANGELOG "One search field everywhere" | **Have**: one search field on the desktop and the phone (wave 2) |
| DS-76 | Pull down to reload | | CHANGELOG 0.21.0 | **Have**: the Table refreshes (`TableScreen.kt`) |

### Tests and security

| # | Feature | What it does for you | Theirs | Roundtable |
|---|---|---|---|---|
| DS-77 | Conformance against the real server | Every call the app makes, checked against a real harness | `conformance/` | **Have**: every phone call run against a real phone server in the tests (`tests/conformance/`, wave 3) |
| DS-78 | A fake server for tests, and recorded traffic | Tests without a computer; real traffic kept as fixtures | `mock-harness/`, `tools/capture/` | **Have**: the real server's answers kept as fixtures the phone's tests read (`ConformanceTest.kt`, wave 3) |
| DS-79 | Previews can't run code or reach the net | HTML and SVG drawn with no JavaScript or network | `docs/SECURITY.md` "Workspace Browser tab" | **Have**: the app runs on its own origin and can't reach Roundtable or the internet (`ui/live.py`) |
| DS-80 | What's stored and what it connects to, written down | One page for the owner | `docs/SECURITY.md` | **Have**: `docs/phone-security.md` (wave 3) |

---

## 3. The gaps, ranked

Ranked by what moves the owner's goal most: whole apps and games, many models at once, the owner only
writes the idea, every task easy to see. S = a day or less for one helper, M = a few days, L = a week or more.

| Rank | Gap | Why it matters to the goal | Size | Lives in Roundtable | Rows |
|---|---|---|---|---|---|
| 1 | **Keys out of the workers' shell** | A model can read the owner's keys today; must close before unattended runs | S | `harness/tools.py` (`run_command` with a cleaned environment), key placeholders | MD-52, MD-83 |
| 2 | **Several tasks at once, each in its own worktree** | "All the models in tandem": today one task at a time | L | `harness/orchestrator.py` run loop, new `harness/worktrees.py`, `limits.max_parallel` | MD-20–22, MD-73, DS-32 |
| 3 | **Circuit breaker per task** | Unattended runs stop wasting money on loops and error storms | M | new `harness/breaker.py`, checks in `harness/agent.py` | MD-31, MD-45, MD-46 |
| 4 | **Ask me first, and refuse or pause mid-task** | Risky commands wait for a tap; the phone's switch works | M | `harness/tools.py`, new `harness/gate.py`, `asks.py` kind `command`, `AskCard.kt` | MD-44, MD-48, DS-40–42, DS-45 |
| 5 | **Where the time went, and how full the context is** | "Every task easy to see": time per step, waiting for you, context gauge | S–M | `harness/agent.py` (durations), `harness/session.py`, `ui/static/watch.js`, phone `LiveTab.kt` | MD-34, DS-34, DS-35 |
| 6 | **Notifications that say finished, failed, needs you, money** | The owner only writes the idea, so news must find them; answer on the notification | M | `mobile/.../work/Watch.kt`, new `notify/` package, desktop `ui/static/notify.js` | MD-38, DS-66, DS-67 |
| 7 | **Coding CLIs as workers (Claude Code, Codex)** | Uses subscriptions the owner already pays for; more makers in tandem | L | new `providers/cli_engine.py`, catalog entries | MD-02, MD-66 |
| 8 | **Compaction for long tasks** | Big apps and games need long tasks without the cost climbing | M | plugin hook (`plugins/api.py`, `plugins/host.py`) + `plugins/builtin/compactor.py` | MD-26, DS-39 |
| 9 | **Rewind and fork a task** | Undo a bad task, try another way, without git by hand | M | new `harness/rewind.py`, `ui/rewindapi.py`, Watch buttons | DS-21, DS-22, DS-23 |
| 10 | **Schedules, GitHub issues and CI as work** | Work starts itself; CI failures become tasks (release 3) | M–L | new `automation.py`, `ui/automationapi.py`, `ui/static/automation.js` | MD-71, MD-72, MD-77–80, DS-65 |
| 11 | **Project memory and search everywhere** | Agents remember decisions; the owner finds anything | M | new `memory.py`, `search.py`, `ui/searchapi.py`, a search box on both | MD-55–58, DS-49, DS-75 |
| 12 | **Files, previews and a command log in the app** | See the code and outputs without leaving the app | M | new `ui/filesapi.py`, `ui/static/files.js`, phone `FilesScreen.kt` | MD-74, DS-48, DS-50, DS-52 |
| 13 | **A better message box: attachments, @ references, dictation, drafts, queue** | Ideas with pictures and voice, never lost | M | phone composer (new `ui/Composer.kt`), desktop `ui/static/compose.js`, `asks.py`/chat body | MD-75, MD-76, DS-14–17, DS-26, DS-27, DS-74 |
| 14 | **Tools page: MCP servers, skills, Prerequisites with Install** | Set up engines (Godot, Unreal, Playwright) from the app, never a command | M | new `prereq.py`, `ui/toolsapi.py`, `ui/static/tools.js` | MD-65, MD-84, MD-85 |
| 15 | **Kinds and a gallery of ready agents** | Reshape for a game, a site, a mod with one tap (plans/kinds.md) | L | `kinds/` folders, planner reading them | MD-06, DS-59 |
| 16 | **Web search for workers** | Workers check an API's real docs instead of guessing | S | `harness/tools.py` or an MCP server | DS-61 |
| 17 | **Before/after proof judged by a model** | Proof, not opinions (release 2) | M | `harness/showit.py`, reviewer prompt | MD-68 |
| 18 | **Phone polish: tablets, accent and text size, haptics, pin/archive, history, detail level** | Comfort | S each | `Theme.kt`, `TableScreen.kt`, `ProjectScreen.kt` | DS-19, DS-20, DS-25, DS-69, DS-71, DS-72 |
| 19 | **Retention: one place that deletes old runs and pictures** | Disk stays tidy; nothing else ever deletes | S | new `retention.py` | MD-50 |
| 20 | **Smaller ones** | Hop cap and bounce in the hub; plugin market and "make a plugin"; what's-new page; discovery on Wi-Fi; conformance run of the phone against a real server | S each | `hub/service.py`, `plugins/`, `updater.py`, `mobile/.../net/`, `tests/` | MD-11, DS-63, DS-64, MD-92, DS-04, DS-77, DS-78 |
| 21 | **Voice conversation with the planner** | Nice, not needed for the goal | L | later | MD-88 |

---

## 4. The build plan, in slices

The rules from CLAUDE.md: one helper per slice, each in its own worktree and branch off the session's
branch, owning the files named; no pushes or merges by a helper. **New API routes go in their own
`ui/<name>api.py`**, registered in `ui/server.py` with one line by the coordinator (as `ui/syncapi.py`
is), so no two slices edit `server.py`. The same for `ui/static/app.js` (one import line each) and the
phone's navigation (`MainActivity.kt`): the coordinator adds those lines when merging.

**Borrowing:** both projects are MIT. Any code taken from them, as it is or turned into Python or
Kotlin, keeps its copyright line in `THIRD_PARTY_NOTICES.md` (Munder Difflin: "Copyright (c) 2026
Chaitanya Giri" as in its LICENSE; DSH Mobile: "Copyright (c) 2026 DSH Mobile contributors"), the file
says where it came from at the top, and the devlog names the source file. Never Munder Difflin's
pixel art or portraits (LICENSE-ASSETS). Good sources to port: `breaker.ts` (MD), `control.ts` (MD),
`retention.ts` (MD), `weeklySchedule.ts` (MD), `ShellPlan.kt` (DS), `DshNotifications.kt` (DS),
`TrajectoryOverview.kt` (DS).

### Wave 1 (all at once)

| Slice | Goal | Owns | Must not touch | Tests | Proved by | Real PC or phone? |
|---|---|---|---|---|---|---|
| **1. Breaker and timings** | Each task checked: 8 identical tool calls in a row, 5 errors in a row, runaway output, a token cap per job, 5 minutes without progress → steer, then refuse tools, then stop. Every model call and tool call records how long it took | `harness/agent.py`, new `harness/breaker.py`, `tests/test_breaker.py` | `orchestrator.py` (the breaker returns the stop reasons it already handles), `tools.py` | scripted provider loops and error storms; each step trips once; quiet during a long command | a scripted run stops at the right step; events carry `ms` | No |
| **2. Keys out of the shell, and Ask me first** | `run_command` gets a cleaned environment (no key variables; `proxy-injected` placeholders where a tool needs one). With Ask me first, a command waits for an allow/deny card shown in full; over 256 KB is refused | `harness/tools.py`, new `harness/gate.py`, `asks.py` (kind `command`), `tests/test_tools_env.py`, `tests/test_gate.py` | `agent.py`, `orchestrator.py` (coordinator wires the gate in one line) | `env` inside a task shows no key; a card appears and its answer runs or refuses the command | a scripted task asks, the answer is applied | Phone: the card on the real phone (This phone and PC mode) |
| **3. Several tasks at once** | Tasks without unmet depends-on run together (default 3, `limits.max_parallel`), each in `.harness/worktrees/<task>` on its own branch; merged back in order; a conflict becomes a fix-up task; a worktree with uncommitted work is never removed without saying why | `harness/orchestrator.py`, new `harness/worktrees.py`, `harness/config.py`, `tests/test_parallel.py` | `agent.py`, `tools.py`, `session.py` | three scripted tasks run at once and merge; a clash makes a fix-up task; the money limit holds across all three | a scripted project finishes faster in steps, all tests pass | No |
| **4. Notifications** | One classifier: finished, needs you, failed, money, idle; a channel each and a key so news never comes twice; quiet when that project is on screen; Allow / Reject on short cards; desktop pop-ups | `mobile/.../work/Watch.kt`, new `mobile/.../notify/` package, new `ui/static/notify.js`, tests in `mobile/app/src/test/.../notify/` | `asks.py`, other screens | classifier unit tests; same news twice → one notification | notifications on the phone, a tap opens the project | **Phone** (by USB through the PC) |
| **5. Coding CLIs as workers** | A provider that runs `claude -p --output-format stream-json` or `codex exec --json` in the task's folder, reads its steps into Watch, counts its tokens; one table per engine (command, resume, install); missing CLI → one Install card | new `providers/cli_engine.py`, `providers/catalog.py` (entries only), `tests/test_cli_engine.py` with a fake CLI script | `agent.py`, `orchestrator.py` | the fake CLI's stream becomes steps and a result; a missing CLI says so | a real task done by Claude Code on the owner's PC | **PC** (Claude Code and Codex signed in there) |
| **6. Automation** | Schedules ("every weekday at 9"), GitHub issues with a label become ideas or tasks, a failed CI run becomes a fix task; a page listing each with its last and next run; polled through GitHub, no tunnel | new `automation.py`, `ui/automationapi.py`, `ui/static/automation.js`, `tests/test_automation.py` | `orchestrator.py`, `remote.py` | schedules fire once per slot after a restart; issue and CI fixtures turn into the right items | a made-up repo's failing run becomes a task | No (GitHub tools from the cloud) |
| **7. Tools page and Prerequisites** | One page: git, Node, Python, Playwright, Godot, Unreal, each found or not with an Install button (done through Remote Control on the PC); MCP servers added, tested and given to a job from the app | new `prereq.py`, `ui/toolsapi.py`, `ui/static/tools.js`, `tests/test_prereq.py` | `harness/mcp_tools.py` (read only), `settings.js` (coordinator links it) | found/missing on made-up paths; a server test that fails says what to do | the page on the owner's PC lists what's really there | **PC** (installs) |

### Wave 2 (after wave 1 is merged)

| Slice | Goal | Owns | Must not touch | Tests | Proved by | Real PC or phone? |
|---|---|---|---|---|---|---|
| **8. Time and context in Watch** | Per task: a bar of waiting for the first word, writing, tools, waiting for you (unrecorded time left out, never zero); context used; cache-hit rate; "Changed 3 files" folded | `harness/session.py`, `ui/static/watch.js`, `mobile/.../ui/LiveTab.kt`, `tests/test_session_time.py` | `agent.py` (slice 1 records the times) | made-up event logs give the right split | screenshots of Watch on both | Phone: a look on the real phone |
| **9. Compaction** | A conversation past about 120,000 tokens is summarised by a cheap model, keeping the task, the files changed and the last steps | `plugins/api.py`, `plugins/host.py`, new `plugins/builtin/compactor.py`, `tests/test_compactor.py`, one call in `harness/agent.py` | the rest of `agent.py` | a scripted long task stays under the limit and still finishes | cost per step stops climbing | No |
| **10. Rewind and fork** | Undo a task (its commit reverted, or the project put back to before it), with the files it will restore and a "Are you sure?"; fork a project from a task to try another way | new `harness/rewind.py`, `ui/rewindapi.py`, buttons in `ui/static/watch.js` (after slice 8), `tests/test_rewind.py` | `orchestrator.py` | rewind of a scripted project restores the files and the task list; never after a push | button on desktop and phone | No |
| **11. Memory and search** | A project memory file (rules that never move, pinned facts, recent notes; old lines archived word for word); one search over plans, tasks, journal, letters, memory and files | new `memory.py`, `search.py`, `ui/searchapi.py`, `ui/static/search.js`, `mobile/.../ui/SearchScreen.kt`, tests | `hub/journal.py` (read only) | search finds made-up entries; memory trims without losing a line | search from the top bar on both | Phone: a look |
| **12. Files in the app** | Browse a project's folder; open text, markdown, CSV, JSON, pictures, PDF; save a copy; the commands a task ran as a log | new `ui/filesapi.py`, `ui/static/files.js`, `mobile/.../ui/FilesScreen.kt`, tests | `harness/showit.py` (reuse `safe_path`, don't change it) | no `..`, no `.git`, `.harness` or `.env`; big files say so | open a file on both | Phone: a look |
| **13. The message box** | Pictures and files on ideas and chat; `@file` references; dictation on the phone; drafts kept; queue or steer with a default | new `mobile/.../ui/Composer.kt`, new `ui/static/compose.js`, `tests/test_attachments.py` | screens that use it (the coordinator swaps them over) | a picture reaches the planner; a draft survives closing the app | an idea with a photo planned from the phone | **Phone** (camera, microphone) |
| **14. Phone comfort** | Tablet and foldable layout, accent, true black, text size, haptics, pin and archive projects, history of what you sent, how much detail | `mobile/.../ui/Theme.kt`, new `mobile/.../ui/adaptive/`, `SettingsScreen.kt`, `TableScreen.kt` | `Composer.kt`, `FilesScreen.kt`, `SearchScreen.kt` | layout plans for each window size (pure function, as theirs) | screenshots at phone and tablet size | **Phone** |
| **15. Small ones** | Hop cap (12) and bounce in the hub; retention (one place that deletes, with a log); what's-new page after an update; Wi-Fi discovery; a conformance run of the phone's calls against `roundtable phone serve` | `hub/service.py`, new `retention.py`, `updater.py`, `mobile/.../net/Discovery.kt`, new `tests/conformance/` | everything else | each has its own test | the conformance run in CI | Phone: discovery on the real Wi-Fi |

Later, not sliced yet: kinds and the gallery (plans/kinds.md, its own plan), web search for workers
(small, after slice 2's cleaned environment), the plugin market, before/after proof judged by a model
(release 2's own plan), voice conversation.

---

## 5. For the owner to decide

One line each, with my recommendation.

1. **Use your Claude Code and Codex subscriptions as workers?** Yes, Claude Code first, as one more
   model a job can pick; it needs your PC to test.
2. **A real terminal into your PC from the phone?** No: a log of every command each task ran, and a
   "run the tests" button; a full shell only on the desktop.
3. **How many tasks at once?** Three by default, at most four (PLAN.md already says about four).
4. **Rewind code changes?** Yes, but only for work not yet pushed, and always showing the files first.
5. **Slack or Telegram?** No for now: the phone and the hub already reach you.
6. **A public tunnel for webhooks?** No: Roundtable asks GitHub instead, so nothing opens your PC.
7. **Voice?** Dictation into the message box yes; a spoken conversation later.
8. **An animated office of your own (like Munder Difflin's, with our own art)?** Not now: the Hall
   says the same in words; it could come with the games release using Retro Diffusion art.
9. **Show the balance in pounds too?** No: it needs an outside rates service; dollars match the bills.
10. **Other languages, anonymous usage counts, an iPhone app?** No, no and no.
11. **Keys out of the workers' shell** is a security fix, so the coordinating session should ask
    Fable and note it in plans/notes-for-owner.md; my recommendation: do it first, before any
    unattended run.

Also noticed: `plans/workflow.md` row 2 still says "No" for working in your existing repositories;
repository mode came in 0.8.0, so it's "Part" now (no push, pull request or CI yet).
