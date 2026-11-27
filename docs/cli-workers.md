# Claude Code and Codex as helpers

You can let Claude Code or Codex do building tasks, using the subscriptions you already pay for.
Each one runs on your computer, in the task's own folder, and its steps show in Watch like any other
helper's. It is off until a role names it.

## Switching it on

Give a building role (for example `coder`) one of these as its model, or as a fallback:

| Model | What runs |
|---|---|
| `cli/claude-code` | Claude Code |
| `cli/claude-code@opus` | Claude Code with a model of your choice (after `@`) |
| `cli/codex` | Codex |
| `cli/codex@<model>` | Codex with a model of your choice |

and add the helper once under `providers` in `harness.yaml`:

```yaml
providers:
  cli: {type: cli}
roles:
  coder: {model: cli/claude-code, fallback: [deepseek/deepseek-v4-flash]}
```

Both must be installed and signed in on this computer. The **Tools** page installs them (Claude Code,
Codex → Install); open each one once and sign in with your subscription. If one is missing, the task
says so and points you to the Tools page, and the next model in the chain carries on.

They can only build. Planning, reviewing and looking stay with the chat models.

## What it may do

- **Claude Code** runs with `--permission-mode acceptEdits`: it may read and change the project's
  files, and run the usual tests and builds (`pytest`, `npm test`, `npm run build`, `cargo test`,
  `go test`, `gradlew build`, `git status` and `git diff` …). No web, no `curl` or `wget`, no
  `git push`, no `rm -rf`, no `sudo`, no installs. Anything else is refused, as nobody is there to say yes.
- **Codex** runs in its own sandbox (`workspace-write`): it may change files only inside the task's
  folder, and has no network.
- Neither gets your API keys, the hub's token or your GitHub sign-in: it starts with the same cleaned
  settings as every command a helper runs. It keeps its own sign-in (its folder in your home folder).

## Money and limits

- With a subscription nothing is charged to the run's budget: Watch shows the cost the helper
  reports, for comparison. If you pay Claude Code by API key instead, set `bill: api`
  (`providers: cli: {type: cli, bill: api}`) and its cost counts towards the run's money limit.
- A task may take at most 30 minutes (`workers: {cli_time_limit_minutes: 30}`). The safety check
  stops it when it repeats itself or uses too many tokens, and the run's money limit and Stop stop it
  too: the helper and everything it started are closed.
- A retry carries on the same conversation (`--resume`), with the reviewer's notes, so it doesn't start over.

## What it can't do yet

- **Ask me first can't see inside it.** The helper runs its own allowed commands without asking you.
  With Ask me first set to *every command*, Claude Code gets no commands at all, only file changes.
- Watch shows its steps and, afterwards, each changed file with its changes. It can't be paused in
  the middle of a step.
- Tried with a made-up helper so far; a real run needs your PC, where Claude Code and Codex are signed in.
