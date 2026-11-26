# What Roundtable couldn't do yet

The owner's rule (26 November 2026): when a job meant for Roundtable needs something it
can't do, add it to Roundtable, or write it here with what happened and where it
belongs. Newest first. Move an item to "Fixed" with the commit when it's done.

## Open

- **The estimate's defaults are guesses.** With no history it assumes 60,000 input and
  8,000 output tokens per attempt. In real money the music player's estimate was about
  right once the cost count was fixed (below), but the defaults should come from real
  runs (steps × context) and be checked after each one. → release 2.
- **Nothing proves the work runs.** The coder can't open a browser and has no sample
  files, so a task's "done when" (open the page, import three songs) is never checked;
  the critic said so on every version of the music player plan. → release 2 (build,
  test, start, screenshot, a model that can see).
- **Tasks are planned too big.** Splitting after the fact now works (below), but the
  planner should size tasks up front (a rough step budget each). → release 2.
- **Commands from the phone need a running Roundtable.** In a cloud session the watcher
  stops after two hours; with the desktop app closed, nothing answers. → release 3 (say
  on the phone when no Roundtable is listening, and when it last was).
- **Running one task, or until a point, isn't in the app.** `run(max_tasks=1)` exists in
  code; the app and the phone can only run everything. → release 2 (a "do one task"
  button, useful while costs are being checked).
- **The critique can be about an older version.** It's now labelled with its version;
  the critic should look again after a revision that changes many tasks. → release 2.

## Fixed

- **Self-improvement missed a cheap model that mostly failed** (26 November): it compared
  cost per attempt and wanted 5 tries of the fallback. It now also compares the cost per
  finished task and spots a fallback that keeps rescuing the primary.

- **Every app looks the same** (26 November): an app with screens now gets a Look step in
  its plan – three different looks with pictures, the chosen one written as
  `design/DESIGN.md` and `design/tokens.css` that every task and review follows, a check
  for colours and fonts outside it, and never the look of another project unless asked.
- **A task too big for one attempt failed the run** (26 November): the music player's
  tasks 9 and 10 ran out of 60 steps twice each. A task whose every attempt ran out of
  steps is now split by the planner into 2–4 smaller tasks, once
  (`Orchestrator._split_if_too_big`, `limits.split_stuck_tasks`).
- **The cost count was about ten times too high** (26 November): text a model had
  already seen was charged at the full input price. Task 2 of the music player was
  counted at $0.27; the DeepSeek balance went down by about 2–3 cents. Cache hits are now
  charged at a tenth of the input price unless the pricing says otherwise, and every run
  notes the real balance at its start and end (`.harness/balance.jsonl`, the
  `real_cost` event, `roundtable balance`) for providers that report one (DeepSeek).
- **A revision forgot the owner's answers and offered turned-down ideas again**
  (26 November, `01219e3`): settled choices, answers and decided ideas stay on the page;
  a reworded copy of a turned-down idea is dropped.
- **New ideas were marked as accepted** because they reused an old idea's id
  (25 November): items are matched by wording.
- **A task that ran out of steps with no fallback model ended the run** (26 November,
  `2e1b1ba`): it now carries on once, from the files it already wrote.
