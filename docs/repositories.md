# Using Roundtable on one of your own apps

Roundtable can work on an app you already have – a last round of bug fixes, making it faster,
tidying it up – not only make new ones. It works like a careful helper who has been given a copy of
the keys: it keeps to its own branch, follows your app's own rules, runs your app's tests, and never
pushes anything.

## How to start

Point Roundtable at the app's folder (the one with your code in it, already under git):

```
roundtable new path/to/your-app "Fix the bugs left before I share it with friends" --approve
```

`--approve` makes it stop after planning, so you can read the plan before anything changes. You can
also give it your test command straight away:

```
roundtable new path/to/your-app "Make it start faster" --approve --test "python -m pytest tests -q"
```

Then `roundtable approve path/to/your-app` and `roundtable run path/to/your-app`, or use the desktop
app as for any project.

## What it does

- **Its own branch.** Before it changes anything it makes a branch called `roundtable/<the goal in a
  few words>` from where your app was, and works only there. It never commits on `main`, `master` or
  the branch you were on. If the branch already exists, it carries on with it.
- **It never pushes.** No pushing, no pull requests, no releases, no paid CI runs: your
  repository online stays as it was. (The AI models do read the code they work on: use
  `providers_allowed` below to choose which ones may.) You look at the branch and merge it yourself when you're happy (that may come to
  Roundtable later).
- **Your `.gitignore` is left alone.** Roundtable keeps its own notes in a `.harness` folder and hides
  it from git in `.git/info/exclude`, which is never shared.
- **It follows your app's rules.** It reads `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md`, and the
  newest entry of `HANDOFF.md` and `DEVLOG.md`, and gives them to every model that plans, checks,
  builds or reviews. Long files are shortened (all the headings are kept). Where your rules say to keep
  a devlog, the builders add the entry.
- **It plans changes, not a new app.** The planner is told this is an existing app: small, checkable
  changes that keep what works. The step where it offers looks to choose from, and the pictures after
  each task, stay off unless your app is a web page.
- **It runs your tests.** With a test command set, it runs it once before any change (the
  *baseline*). After each task it runs it again. A task that makes a test fail that passed before is
  sent back to be fixed. Tests that were already failing before it started are never blamed on a task:
  the reviewer only sees what's new.

If you had changes of your own that weren't committed, they stay in the folder and are saved on
Roundtable's branch with its first commit. It's tidier to commit or put them away first.

`roundtable status path/to/your-app` shows the branch and how the tests did before the first task.

## The settings file

Each project has its own settings in `.harness/project.yaml`. Roundtable writes the file the first
time, with a note above every setting. Change it in any text editor, in the desktop app (the
project's page, **Settings**), from the phone, or on the command line:

```
roundtable settings path/to/your-app                       # see them all, and where each comes from
roundtable set path/to/your-app test "python -m pytest tests -q"
roundtable set path/to/your-app env QT_QPA_PLATFORM=offscreen
roundtable set path/to/your-app providers_allowed deepseek
roundtable set path/to/your-app setup                      # empty: back to the default
```

| Setting | What it does |
|---|---|
| `test` | The command that checks the app, e.g. `python -m pytest tests -q`. |
| `env` | Settings for that command, such as `QT_QPA_PLATFORM: offscreen`. Never keys or passwords. |
| `setup` | A command run once before the first task, e.g. `pip install -e .[dev]`. |
| `timeout` | How many seconds the test or set-up command may take (900 unless you say). |
| `branch` | Where the work goes. Ending in `/` (the default `roundtable/`) adds a name from the goal; anything else is the exact branch. |
| `rules_files` | Which files hold your app's rules (the five above unless you say). |
| `rules_budget` | At most this many characters of those rules go to the models (12,000 unless you say). |
| `providers_allowed` | Only these AI providers may see the project, e.g. `[deepseek]` for a private app. A role with no model from them stops the run with a message saying what to do. |
| `profile` | Which set of models builds it (Budget, Balanced, Quality). |
| `limits` | Limits for this project only: `max_real_usd_per_run`, `max_cost_usd`, `max_attempts_per_task`, `max_steps_per_task`. |
| `look` | `auto`, `on` or `off`: offer looks to choose from before building. |
| `show_it` | `auto`, `on` or `off`: pictures of the app's screens after each task. |
| `notes` | Anything the planner should know, in your own words. |

An example:

```yaml
test: python -m pytest tests -q
env:
  QT_QPA_PLATFORM: offscreen
setup: pip install -e .[dev]
providers_allowed:
- deepseek
limits:
  max_real_usd_per_run: 2
```

### Settings you can share with the app

`.harness` isn't saved in git, so `.harness/project.yaml` is yours alone. To give everyone who runs
Roundtable on the app the same settings, put a `roundtable.yaml` in the app's top folder and commit it.
**`.harness/project.yaml` wins over `roundtable.yaml`, setting by setting**, and `roundtable.yaml` wins
over the defaults. `roundtable settings` says where each value came from.

A setting Roundtable doesn't know (from a newer version, say) is kept as it is and mentioned, never
thrown away. A setting with a mistake stops the run with a message saying what to fix.
