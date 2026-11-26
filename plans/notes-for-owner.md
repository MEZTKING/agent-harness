# Notes for the owner

What was decided while you were away, so you can read it later. The owner's rule (26 November
2026): switch freely without asking; anything super important goes to Fable for advice first,
and is noted here – the question, Fable's advice, and what was done. Newest first.

Roundtable's own model switches are in the hub journal as decisions ("Switched by Roundtable:
… Why: …", each with its undo command).

## 2026-11-26

- **The restyle went past the money you agreed.** Steps 2 and 3 were agreed at $1.50; step 2
  alone used $1.78 (Claude Sonnet through OpenRouter, one attempt). The cause: Claude was
  paying full price on every step, because Roundtable didn't mark what Claude may re-use
  through OpenRouter. Fixed and checked (the same call now costs a twelfth). I stopped there
  and spent nothing more; what step 2 made is shown in the chat.

- **The restyle stopped again, as Fable said it should.** The first restyle task was rejected
  twice more ($0.78): once for a gap in its own new tests, then – after the checker said
  "the product work checks out", 390 tests passing – because a throwaway check script left
  in the folder by an earlier attempt contained colour codes. That's Roundtable's fault, not
  the work's: workers now put throwaway scripts in `.harness/scratch/` (never committed or
  checked), and the design check ignores check scripts. The restyle has cost $1.81 so far;
  the first of its three tasks is done in the files but not accepted. **Waiting for you**,
  as Fable advised; my suggestion is in the chat.

- **Asked Fable: carry on with the music player's restyle after $1.03 was spent with nothing
  finished?** Fable: carry on once, with a tight limit, because the owner already chose the
  look and the stop was Roundtable's fault, not a change of mind. Skip the duplicate restyle
  task; undo the favicon colour change (that rejection was fair); GLM-5.3 codes the token and
  test tasks, Claude Sonnet 5.5 the visual styling; GPT-6.1 Terra reviews; $1.50 real-money
  limit, one retry per task; if a task is rejected again for another task's work, stop at
  once. **Done:** all of that, plus four Roundtable changes Fable suggested (below). With
  this run the restyle will have cost about $2.50, against $3.45 for the whole app.
- **Roundtable changes from Fable's advice:** reviewers are told which later tasks exist
  and judge only the task in front of them; after one rejection the next, stronger reviewer
  model gives the verdict; a run stops when half its money is spent with nothing finished.
  Not done yet (in plans/gaps.md): a rejection must quote the line of the task it breaks;
  split tasks say what's left for the next one; a model that runs out of steps hands its
  partial work on; "spent with nothing finished" shown in the run summary.

- **Model switches are now automatic.** Roundtable looks at every finished run and switches the
  order of models when the numbers clearly say so (for example a cheap model that keeps running
  out of steps while its backup finishes the job for less). Each switch is written in the
  journal with the reason and how to undo it. Settings: `improve: {after_each_run: true,
  auto_apply: low}` in harness.yaml.
