# What Roundtable couldn't do yet

The owner's rule (26 November 2026): when a job meant for Roundtable needs something it
can't do, add it to Roundtable, or write it here with what happened and where it
belongs. Newest first. Move an item to "Fixed" with the commit when it's done.

## Open

- **Every app looks the same.** The music player came out in a generic "clean" style
  (system font, plain blue), because nothing in the plan says what this app should look
  like. The owner (26 November 2026): "I want the UI to be unique for whatever
  application I make." → release 2: a Look stage in the plan (three mockups to choose
  from), a design file per project that every task follows, a check of the screenshots
  against it, and no two projects with the same look unless asked.

- **The estimate's defaults are guesses.** With no history it assumes 60,000 input and
  8,000 output tokens per attempt. In real money the music player's estimate was about
  right once the cost count was fixed (below), but the defaults should come from real
  runs (steps × context) and be checked after each one. → release 2.
- **Nothing proves the work runs.** The coder can't open a browser and has no sample
  files, so a task's "done when" (open the page, import three songs) is never checked;
  the critic said so on every version of the music player plan. → release 2 (build,
  test, start, screenshot, a model that can see).
- **Tasks can be too big for one attempt.** The music player's core-logic task (over
  1,300 lines) ran out of 40 steps. The planner should size tasks (a rough line or step
  budget each) and split big ones. → release 2.
- **Commands from the phone need a running Roundtable.** In a cloud session the watcher
  stops after two hours; with the desktop app closed, nothing answers. → release 3 (say
  on the phone when no Roundtable is listening, and when it last was).
- **Running one task, or until a point, isn't in the app.** `run(max_tasks=1)` exists in
  code; the app and the phone can only run everything. → release 2 (a "do one task"
  button, useful while costs are being checked).
- **The critique can be about an older version.** It's now labelled with its version;
  the critic should look again after a revision that changes many tasks. → release 2.

## Fixed

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
