# A harness that repairs itself (future plan)

The owner (26 November 2026): "In future I want this harness to fix itself – a self-regenerating
harness. If there are any problems it can fix itself: an API model is down, or a model has been
changed silently or behaves differently, and the harness should figure that out." Not now; this
writes the plan down.

## What it should notice

- **A model is down or failing**: errors, timeouts, refusals, "out of credit" (partly done: a
  run pauses on an empty account and skips that provider).
- **A model changed silently**: same name, different behaviour – worse at the same tasks, more
  steps, more rejections, different output style, different price or speed.
- **A provider changed**: a renamed model, a new price, a removed feature (tool calls, caching),
  a changed error.
- **Roundtable itself broke**: a test fails after an update, a run keeps failing in the same
  place, a plugin errors.

## What it can already build on

- **Model health probes** (`roundtable probe`): fixed test tasks per model with scores – the
  regression and boost detector.
- **Self-improvement after each run**: switches the model order by the numbers and writes why
  in the journal.
- **Real-balance checks, out-of-credit pauses, fallbacks** on provider errors.

## The plan (Fable's advice: repair routing automatically; code only by proposal)

1. **Scheduled probes**: a small fixed set of test tasks per model in use, run daily and before
   big runs; compare with the last scores, speed and price.
2. **Drift alarm**: when a model is down or has clearly drifted, switch that role to its fallback
   at once, and tell the owner plainly what changed and why (journal, Needs you card), with an
   undo.
3. **Catalogue checks**: re-read the providers' model lists and prices; flag renamed or vanished
   models and changed prices.
4. **Code repairs are proposals, never automatic**: when Roundtable's own tests or runs show a
   fault in its code, it may write a fix on a branch with a test and a report; the owner (or the
   coordinating session) approves, and it ships through the normal release route. A harness that
   rewrites itself unchecked can break the very thing that would repair it.
