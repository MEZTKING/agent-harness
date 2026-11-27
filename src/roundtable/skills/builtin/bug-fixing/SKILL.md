---
name: Fixing a bug
when: "A task that is about something broken: an error, a wrong result, a crash."
tags: [bugfix, tests]
---
- First make the bug happen on purpose: find the smallest steps or input that show it, and write them down.
- Read the whole error and the place it points to before changing anything.
- Write a failing test that shows the bug, where the project has tests. It passes only once the bug is fixed, and stops it coming back.
- Find the cause, not the symptom: ask why the wrong value got there, and follow it back one step at a time.
- Fix it in the one place that causes it, with the smallest change that does; don't rewrite nearby code in the same task.
- Look for the same mistake elsewhere (search for the same pattern) and mention any you find.
- Run the project's tests, not only the new one.
- In your summary, say what caused it and how you checked the fix.
