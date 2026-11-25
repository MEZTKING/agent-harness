# Roadmap

## ✅ Phase 1: Core + Hub
Agent registry, permission policy, file and git storage, project cards, messaging, change notifications, MCP server, CLI.

## ✅ Phase 2: Harness (multi-provider project runner)
- **Provider adapters** behind one interface (messages, tools, usage, cost):
  - Anthropic (native SDK, to keep prompt caching, tool use and thinking)
  - OpenAI-compatible (DeepSeek, OpenRouter, Groq, Together, local Ollama/vLLM…)
  - OpenAI (including the images API)
  - Google Gemini
- **Roles → models in config**, with fallback chains:
  ```yaml
  roles:
    orchestrator: {provider: anthropic, model: claude-fable-5-2}
    manager:      {provider: anthropic, model: claude-opus-5-5}
    coder:        {provider: deepseek,  model: deepseek-chat, fallback: [anthropic/claude-sonnet-5-5]}
    image:        {provider: openai,    model: gpt-image-1}
    reviewer:     {provider: anthropic, model: claude-sonnet-5-5}
  ```
- **Orchestrator loop:** plan → tasks with roles → route → review against a "done" check → retry or re-route.
- **Workspace:** a git-backed project folder, task board and decisions log, with file, shell and test tools offered the same way to every provider.
- **Guardrails:** cost cap per task and per project, max steps, loop detection, human approval points.
- The harness's own agents join the **Hub**, so harness projects and your existing repo agents can talk.

Done: adapters (Anthropic native, OpenAI-compatible, OpenAI images), roles with fallback chains, planner, review/retry loop, git-backed workspace, budget, approval gate, resume, hub reporting, per-attempt metrics.
Possible later: run independent tasks in parallel; per-task budgets; live Gemini-native adapter.

## ✅ Phase 3: Self-improvement loop
Done: metrics + reviewer feedback + owner ratings → rule-based and LLM-analyst proposals (routing, prompts, options) and owner proposals → replay tests on real past tasks (current vs candidate, same judge) → manual or policy-based auto-apply → versioned learned overlay with exact rollback.
Possible later: cross-provider "new model scouting" (benchmark a newly released model on your past tasks automatically); larger benchmark sets with statistical confidence; per-task-type routing (e.g. frontend vs backend coding).

## Phase 4: Dashboard and real-time
- Web dashboard: agents, cards, threads, tasks, spend, improvement proposals.
- Optional hosted real-time hub (same API, server-backed store) when git polling isn't fast enough.
- A2A protocol bridge for third-party agents.
