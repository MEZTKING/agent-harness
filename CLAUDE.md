# Working on Roundtable Hold

The owner's own system for running AI agents across makers and repositories: the
**hub** (agents, messages, the shared journal; data in the private repository
`MEZTKING/agent-hub-data`), the **harness** (an idea becomes a living plan, then tasks
routed by role to any model, each reviewed), **self-improvement** (routing and prompts
learned from real runs), the **Windows desktop app** (the command centre) and
**Roundtable Mobile** (Android, `mobile/`). Python package `roundtable`, MIT.

The owner's goal, in their words: "you should be able to create entire application,
entire games etc with the maximum possible performance using the combinations of all
the api model in tandem. All I'm doing is writing the initial plan/idea." They decide;
everyone else builds. Every task must be easy to see.

Read first: [HANDOFF.md](HANDOFF.md) (where the last session left off),
[PLAN.md](PLAN.md) (decisions and the releases), the newest entries of
[DEVLOG.md](DEVLOG.md), [README.md](README.md) (how to install and run everything),
[plans/owner-todo.md](plans/owner-todo.md) (what waits for the owner) 
[plans/gaps.md](plans/gaps.md) (what Roundtable couldn't do yet) and
[plans/workflow.md](plans/workflow.md) (the owner's whole workflow, step by step: the target).

## Ground rules

- **Use Roundtable to do the work, and grow Roundtable where it falls short** (owner,
  26 November 2026). When a job meant for Roundtable needs something it can't do – a
  step done by hand, a script outside it, a check nobody runs – don't just work around
  it: add the missing piece to Roundtable itself (with a test), or, if it's too big for
  now, write it in `plans/gaps.md` with what happened and which release it belongs to.
  A one-off fix to the owner's project data (a plan, the hub) is fine, but the cause is
  fixed in the code too.
- **Keep the devlog**: every iteration adds an entry at the top of DEVLOG.md – the date,
  what was asked, what was done (files and functions), what was decided or undone and
  why, what's still open. End a long piece of work with an updated HANDOFF.md.
- **Commits** have no attribution lines (no Co-Authored-By, no session links) and no
  model names. Model ids appear in files only where Roundtable needs them to work
  (configs, pricing, the catalog, tests), never in prose about who did the work.
- **Branches:** develop on the session's branch; `main` is what's installed (`pip
  install git+…@main` and the app's updater follow it). Merge through a pull request
  once CI is green; never force-push; merge instead of rebasing pushed work.
- **Switch freely; ask Fable about the big things, and write them down** (owner,
  26 November 2026: "You can switch freely, you don't have to ask questions, however
  anything super important ask Fable and note them down so I can read it later").
  Model and routing switches, fixes and other reversible choices: just do them and log
  them. Anything super important (spending well past an estimate, deleting or
  publishing, a change of direction, a security or privacy question): ask Fable (a
  sub-agent on the strongest model) for advice, act on it, and note the question, the
  advice and what was done in [plans/notes-for-owner.md](plans/notes-for-owner.md),
  newest first. Roundtable does the same for its own switches
  (`improve.after_each_run`: decisions in the journal).
- **Money is the owner's.** A real run costs the owner's API credit. Show the estimate
  before a build, stop and ask when a run goes well past it, and check the provider's
  real balance when Roundtable's own count may be wrong.
- **Privacy:** the owner's email, hub data and other repositories' content stay private:
  never in a public issue, a test fixture or an outside service. Tests use made-up
  projects. The hub repository is private; nothing from it goes into this one.
- **Secrets** never go in a file, an environment variable you write or a command. Keys
  go through the credential form; the placeholder is `proxy-injected`. The Android
  release key stays out of git (`mobile/signing/` is ignored).
- **Wording the owner reads** (the app, the phone, plans, replies, errors): plain, short
  British English for someone who isn't a programmer; a tooltip on anything not
  obvious; errors say what to do next.
- **Short first, details on request** (owner, 27 November 2026: "Too much information everywhere –
  overload"). Every screen (desktop and phone) leads with the few things that matter – a short title,
  one plain sentence of where it stands, what waits for the owner – and folds everything else
  (technical briefs, specs, model ids, logs) behind "More". A goal or brief written for the builders is
  never the heading the owner reads.
- **Borrowed code is credited.** Code taken from another project (for now the owner's
  forks `MEZTKING/munder-difflin` and `MEZTKING/deepseek-harness-mobile`, both MIT; see
  `plans/inspiration.md`) keeps its licence and copyright line in
  `THIRD_PARTY_NOTICES.md`, and the devlog names the source file. Never copy art or
  anything not under an open licence.
- **The owner never leaves the app** (owner, 26 November 2026: "for the to-do list I'm not supposed to
  ever leave the app; you're meant to set up everything so all my agents do it – that's the whole
  point"). A to-do for the owner is a last resort: anything an agent or Roundtable can do (set-up,
  settings, keys through the app's own forms, GitHub settings through the GitHub tools, cloud
  environments through the environment tools, installs on the PC through Remote Control) is done by
  them, and what truly needs the owner is a one-tap card inside the app (desktop or phone), never
  "go to GitHub / type this command".
- **Who builds Roundtable** (owner, 26 November 2026: "rebuild the application from scratch using
  Claude Opus 5.5 medium"): helpers building Roundtable's own apps run on Opus at medium effort
  unless the owner says otherwise.
- **Test on the owner's PC what the cloud can't** (owner, 26 November 2026: "For whatever you
  can't test on the cloud, you should be controlling the person's computer and testing through
  that, as I have the hardware"). Unreal, Godot, Blender, the Windows app and a phone by USB are
  tested there through Remote Control (`list_computer_folders`, then `request_computer_folder`),
  not left to the owner. If no folder is shared, say so in one line and carry on with the rest.
- **Keep going until it does everything** (owner, 27 November 2026: "don't stop until this harness can
  do everything every other harness can do, especially from the links I gave you"). Work through
  `plans/parity.md` wave after wave, without waiting to be asked, until no row is missing. The harness
  is growing into **Darkness Harness** ("the magnum opus of all harnesses"): built on Roundtable, aimed
  at whole apps and games from one idea, every model in tandem, improving itself, and a darker look.
- **Specialised art for artwork** (owner, 27 November 2026: "I always use specialized art for artwork for
  important tasks"). Art – backgrounds, emblems, icons, app icons, the phone's art – is made by a
  specialised image model (OpenRouter's image models through `providers/chat_images.py`, Retro Diffusion
  for pixel art), never hand-drawn in SVG or CSS; code draws only the chrome (borders, gradients).
- **Nothing is released without the owner saying so** (they have said "you do
  everything" for merging and releasing the desktop app: see Releasing).

## The pieces

| Where | What |
|---|---|
| `src/roundtable/core/` | Models, config (`find_config`: `$HUB_CONFIG`, `./hub.yaml`, the saved pointer, the app's config, `~/.roundtable`, then nearby `agent-hub-data`), policy, file and git storage |
| `src/roundtable/hub/` | The hub service, the MCP server (`hub_*` tools), git helpers |
| `src/roundtable/harness/` | `config.py` (roles, fallbacks, pricing, limits, `critic_role`, `remote`), `tools.py` (the workspace tools), `agent.py` (the loop), `orchestrator.py` (plan, critique, revise, approve, run, review, retry), `plandoc.py` (the living plan document, carry-over, estimate, markdown) |
| `src/roundtable/improve/` | The lab: proposals, replay tests, the learned overlay, model health probes |
| `src/roundtable/providers/` | Anthropic, OpenAI-compatible (DeepSeek and others), images, Retro Diffusion, scripted (tests), the catalog |
| `src/roundtable/remote.py` | Commands through the hub: the owner's `roundtable:` requests (from the phone) done by the desktop app's auto-sync or `roundtable remote --watch` |
| `src/roundtable/phone.py` | The paired, pinned-TLS phone server (`PHONE_ROUTES`); pairing in the desktop's Settings → Your phone |
| `src/roundtable/onphone.py`, `runtime/` | Roundtable running on the phone itself ("This phone"): `roundtable phone serve --local`, the signed Linux download |
| `src/roundtable/sync.py`, `ui/syncapi.py` | The phone and the PC as one Roundtable: machine seats, claims, live sessions, shared settings, carry on |
| `src/roundtable/connect.py` | `roundtable connect`: Claude Code sessions in other repositories join the hub (MCP + SessionStart/Stop/SessionEnd hooks) |
| `src/roundtable/ui/` | The desktop command centre: `server.py` (JSON API, jobs), `roundtable.py` + `hall.py` (seats, Needs you, feed, auto-sync), `static/` (vanilla JS modules, no build step; design in `docs/desktop-design.md`) |
| `mobile/` | Roundtable Mobile (Kotlin, Compose): Hub mode through the GitHub API with a fine-grained token; PC mode over the phone server (not yet tried on a real PC) |
| `packaging/` | The Windows build (PyInstaller spec, installer); `.github/workflows/app.yml` builds and, with a `release_tag`, publishes |
| `tests/` | `python -m pytest tests` – no network, no keys (scripted providers) |
| `plans/` | `owner-todo.md`, `gaps.md`, and design notes |

## Tests

```
pip install -e ".[dev]"
python -m pytest tests -q
cd mobile && ./gradlew testDebugUnitTest assembleDebug   # Android SDK at /opt/android-sdk
```

A real run (costs a little DeepSeek credit): a lab with a `harness.yaml` using DeepSeek
for every role, `roundtable new` / `plan` / `approve` / `run`, and the hub config of
`agent-hub-data`. Check the real balance before and after
(`https://api.deepseek.com/user/balance`).

## Releasing

The owner has given standing permission to merge and release the desktop app.

1. Raise `version` in `pyproject.toml` (the phone app reads it too) **and** `__version__` in
   `src/roundtable/__init__.py` (the installer checks it; a test keeps them equal); a line in
   DEVLOG.md and the README's notes.
2. Pull request from the session's branch to `main`; wait for CI green; merge.
3. Run `.github/workflows/app.yml` by hand with `release_tag: v<version>`: it builds the
   installer and makes the release `RoundtableHold-Setup-<version>.exe`.
4. Check the run succeeded and the release exists; tell the owner what's new, plainly.

Each release also carries the phone **test** APK (`RoundtableMobile-<version>-test.apk`), built by
the workflow's `android-apk` job and signed with `mobile/test-key/` (a public test key, so test builds
install over each other). The official phone release needs a real signing key as a repository secret
first (plans/owner-todo.md).

## Working with sub-agents

One agent per job, each in its own worktree and branch off the session's branch, with
the files it owns named so two never edit the same file; no pushes or merges from an
agent – the coordinating session merges, runs everything again and pushes. Hardest
design: the strongest model; careful coding and UI: Opus; bounded mechanical work:
Sonnet. A brief states the goal, the owner's words, the files, what not to touch, the
tests, and asks for a plain report with commit ids.
