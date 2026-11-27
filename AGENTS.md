# Instructions for any coding agent (the short version)

This is Darkness Harness (Roundtable Hold before 1.0.0; the `roundtable` package and command keep
the old name).

Full rules: [CLAUDE.md](CLAUDE.md). Where things stand: [HANDOFF.md](HANDOFF.md). Plan:
[PLAN.md](PLAN.md). The newest work is at the top of [DEVLOG.md](DEVLOG.md).

1. **Read** HANDOFF.md, CLAUDE.md, PLAN.md, `plans/owner-todo.md` and `plans/gaps.md`
   before changing anything.
2. **Use the harness, and grow it.** If the harness can't do something the work needs, add
   it to the harness (with a test) or write it in `plans/gaps.md`. Don't leave a
   workaround as the answer.
3. **The owner is not a programmer.** Anything they read: plain, short British English;
   errors say what to do next.
4. **Money:** real runs spend the owner's credit. Estimate first; stop and ask when a run
   goes well past it.
5. **Privacy and secrets:** hub data, other repositories and the owner's details stay
   private. Never write a key into a file, a command or an environment variable.
6. **Commits** have no attribution lines and no model names. Work on a branch; no force
   pushes; merge instead of rebasing pushed work.
7. **Tests** before every commit: `python -m pytest tests -q`; for `mobile/`,
   `./gradlew testDebugUnitTest`.
8. **Keep the devlog:** a new entry at the top of DEVLOG.md for every change.
9. **Several agents at once:** one worktree and branch each, files assigned, no pushes or
   merges by the workers.
