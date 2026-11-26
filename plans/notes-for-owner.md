# Notes for the owner

What was decided while you were away, so you can read it later. The owner's rule (26 November
2026): switch freely without asking; anything super important goes to Fable for advice first,
and is noted here – the question, Fable's advice, and what was done. Newest first.

Roundtable's own model switches are in the hub journal as decisions ("Switched by Roundtable:
… Why: …", each with its undo command).

## 2026-11-26

- **Model switches are now automatic.** Roundtable looks at every finished run and switches the
  order of models when the numbers clearly say so (for example a cheap model that keeps running
  out of steps while its backup finishes the job for less). Each switch is written in the
  journal with the reason and how to undo it. Settings: `improve: {after_each_run: true,
  auto_apply: low}` in harness.yaml.
