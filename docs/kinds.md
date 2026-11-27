# Kinds and the Gallery

The owner (26 November 2026): "Make Roundtable very modular, so it can change itself, or you can change it
at the press of a button … depending on what we need to make – a game, a website UI, a music player,
anything". The plan and the reasons are in `plans/kinds.md`; this page is how it works.

**The engine stays the same.** A kind is a folder of data. Nothing in a kind is code. A kind changes what
the builders are told, the shape of the plan, what is checked and what the owner reads. It never picks
models and never changes the harness's own code.

## A kind's folder

```
kinds/<id>/
  kind.yaml          schema kind@1 (below)
  prompts/<role>.md  appended to that role's own prompt, never replacing it
  card.md            a short note the owner can open under More
  template/          starting files (text and pictures only when shared)
```

Kinds are looked for in three places, later ones winning:

1. built in: `src/roundtable/kinds/builtin/`;
2. the owner's own: `<app folder>/kinds/` (an import goes here);
3. the project's frozen copy: `.harness/kind.json`, written when the plan is approved, so editing a kind
   later never changes a project already being built. **Use the newest recipe** replaces it on purpose.

An **extra** (`_extras/<id>/extra.yaml`, schema `extra@1`) stacks on a kind: `needs`, `targets`, `proof`,
`plan.dont`, `task` (a hint for the planner), `pc_only` and `ship`. The first two are `apk` and `exe`.

The built-in kinds: `website`, `web-app`, `browser-game`, `android-app` (native Kotlin, a debug APK),
`java-mod` (a Gradle mod, a `.jar`) and `other`.

## `kind.yaml`

```yaml
schema: kind@1
id: browser-game
name: Browser game
blurb: Something to play in the browser.
group: Browser games
status: trial                 # trial | not_yet; never proven (that is earned)
extends: web-app              # shared pieces are written once
match: [game, arcade, puzzle, play]       # words that propose this kind (free: no model call)
examples: ["a snake game with a high score"]
needs: [playwright]           # ids from prereq.py
roles:
  add: {artist: {kind: image, description: "Draws the game's pictures"}}
  prompts: {orchestrator: prompts/planner.md, coder: prompts/coder.md}
plan:
  has_ui: true
  skeleton_first: true        # the first task alone: layout, shared names, data shapes
  spec_sections: [Stack, Screens, Controls, Art style, Sound, How to run it]
  questions: [{id: controls, header: Controls, question: "How is it played?",
               options: [{id: keyboard, label: Keyboard}, {id: mouse, label: Mouse}], recommended: keyboard}]
  dont: [{text: "No game engine download", why: "It must open from one page"}]
look: art                     # on | off | art
proof:
  - {id: starts, how: page_opens, words: "It opens with no errors"}
  - {id: tests, how: command, command: "npm test", optional: true, words: "Its tests pass"}
  - {id: plays, how: play, seconds: 60, status: not_yet, words: "Played for a minute"}
pictures: [desktop, phone]
targets: [web]
extras_allowed: [apk, exe]
plugins: []
estimate: {tasks: [6, 12], usd: [1.5, 4.0], minutes: [30, 90]}   # "a guess" until real builds exist
```

## Building it to hand out: `ship` and `start`

A kind or an extra may say how its thing is built and checked at the end; a kind may say how it starts:

```yaml
ship:
  build: ./gradlew assembleDebug                 # one line; ./gradlew becomes gradlew.bat on Windows
  artefact: app/build/outputs/apk/debug/*.apk    # inside the project
  smoke: apk                                     # start | apk | mod | none | a command of its own
  needs: [java, android]                         # ids from prereq.py (default: the kind's needs)
  os: [windows, mac, linux]                      # where it can be built (default: all three)
  target: apk                                    # default: the extra's id, or the kind's first target
  timeout: 1800                                  # seconds, at most 7200
start: {command: npm start, port: 5173, ready: /}
```

At the end of a run (`harness/shipstage.py`, after the finishing step) each target is built once, the file is
checked (it is there, isn't empty, and starts with the right bytes: `PK` for apk, jar and zip, `MZ` for exe)
and started once: an EXE must still be running after 10 seconds and is then ended with everything it started;
an APK is checked with the SDK's own `aapt2` when it is there and installed only on an emulator that is
already running; a mod jar must hold its mod file (`fabric.mod.json`, `mods.toml`…). A command of its own
passes when it exits with 0 or is still running after 10 seconds. The result is the done-list item
`ship:<target>`. A failed build gets one fix task per target; after that it is a failed item for the done
gate. A target this machine can't build (no Windows here, Java missing) is "not checked", with the reason;
the planner is told the same beforehand. Never: signing with a real key, installing on a plugged-in phone,
uploading or publishing.

**Whose commands.** A built-in recipe runs under the project's own "Ask me first" rules. A recipe from the
owner's own or an imported kind always waits for the owner's Allow the first time in each project, with the
exact command shown, even when the project never asks. Adding a kind from a file lists these commands first.

A card with a mistake is refused, with the line named ("line 5: status can't say proven…"). The Gallery's
*What the harness can make* lists refused cards under a fold.

`extends` merges: settings replace, except `needs` (added up), `proof` (by id), `roles` (added up),
`plan.dont` (added up) and `plan.questions` (by id). Prompts along the chain are joined, parent first.
Proof `how`: `page_opens`, `command`, `play`, `picture`, `file_exists` (with `path`).

## How a kind is chosen

1. **The desktop wizard** offers `kinds.wizard_options()`: the kinds usable now, the ones not ready greyed
   under "Coming", and "Something else" (`other`). `kinds.from_wizard(chosen, other, idea)` turns the answer
   into `{kind, extras, by, why}` (the old answers web, game, android, windows still work).
2. **Any other start** (the phone's New idea, an automation, the command line): `propose` picks one and
   keeps it as the harness's guess: `meta["kind"] = {id, extras, by: "roundtable", why, confirmed: false}`.
3. **The first card on every plan**: "This looks like a browser game, because you said “play”. Right?" with
   the top three and Something else. Changing it before approval re-plans (the card says it costs about one
   plan); after approval the kind is fixed.

`meta["parts"] = [{id, name, kind, extras, folder}]` is kept from day one; version 1 builds one part.

## Honest status

The file says `trial` or `not_yet`. **Proven** is computed from the Gallery: at least one record built with
the kind where every proof line that counts passed. Optional lines and `not_yet` lines don't count; a line
nobody could check (`passed: null`) is not a pass. It is kept in `<app folder>/kinds/state.json` (rebuilt
from every record, hidden ones too). The words are "Proven (3 built)", "On trial" and "Not yet". Typical cost
and time are the real medians once something was built, else the file's range labelled "a guess".

## The Gallery

When a goal finishes, one record goes to `<app folder>/gallery/<project>/goal-<n>/entry.json` (and, without
the big pictures, to the private hub under `plans/gallery/…`). It is written once: a re-run of the same
goal keeps the first record and the owner's flags. It holds the title and summary, kind and extras, date,
tasks, cost (counted and real), minutes, which model did each job (under More), the proof lines, up to four
pictures of at most 200 KB, a cover of at most 60 KB sent inline, the outputs and the commit.

Hiding never deletes. The Gallery offers no deletion at all. **Make another like this** fills in the
wizard with the kind, extras and model set and copies no files.

## Sharing a kind

**Share** saves a `.rtkind` (a zip of the kind's folder: YAML, prompts, card, safe template files). It holds
no project content and refuses anything shaped like a key. **Add a kind from a file** first shows what the
kind would switch on (tools it needs, plug-ins, helpers, commands its checks run) and changes nothing until
the owner says yes. It refuses code and unknown file types, links, `..` or absolute paths, files over 5 MB,
more than 200 files or 20 MB in all, and key-shaped text. Imports are the owner's own for now: no public
catalogue, because a kind's prompts steer the builders.

## Code

| Where | What |
|---|---|
| `kinds/model.py` | `Kind`, `validate`, `parse_text`, `load_all`, `resolve`, `propose`, `propose_extras`, `overlay`, `apply_to_config`, `plan_brief`, `worker_brief`, `proof_plan`, `card`, `status_of`, `status_words`, `wizard_options`, `from_wizard`, `export`, `import_file` |
| `kinds/gallery.py` | `record`, `entries`, `one`, `hide`, `star`, `again`, `hub_files`, `refresh_state` |
| `harness/ship.py`, `harness/shipstage.py` | the recipes and checks (pure); `ShipStage`: `_ship_plan_part`, `_ship_estimate`, `_ship_step`, `ship_status` (`.harness/ship.json`) |
| `harness/kindstage.py` | `KindStage`: `_kind`, `_kind_cfg`, `_kind_propose`, `set_kind`, `_kind_freeze`, `kind_use_newest`, `_kind_doc`, `_kind_ask`, `_kind_plan_part`, `_kind_worker_part`, `_kind_proof`, `_kind_proof_plan`, `_gallery_record` |
| `ui/kindsapi.py` | `/api/kinds…` and `/api/gallery…` |
| `ui/static/kinds.js`, `gallery.js` | the plan's kind card, the Gallery room and *What the harness can make* |
| `mobile/…/data/Kinds.kt`, `ui/KindCard.kt`, `ui/GalleryScreen.kt` | the phone's twins |

## Adding a kind

Add a folder under `kinds/builtin/` (or the owner's own folder), start it `status: trial`, give it at least
one proof line that the harness can check by itself, and add it to the proposals test in `tests/test_kinds.py`.
Add a kind only when a project needs it.
