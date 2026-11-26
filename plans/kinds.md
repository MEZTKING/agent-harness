# Kinds: Roundtable reshapes itself for each sort of software

The owner (26 November 2026): "Make Roundtable very modular, so it can change itself, or you
can change it at the press of a button, to rearrange its architectural layer depending on what
we need to make – a game, a website UI, a music player, anything. List all the genres of
software that are possible, and Roundtable changes itself to make its next thing … parallel
tasks at the same time. This should be very, very powerful."

Fable's advice (asked the same day; the owner's rule for big decisions) is the basis of this
plan. Decided: **kinds as recipe cards, not Roundtable rewriting its own code.**

## The idea

Roundtable's engine – plan, route, build, prove, review, merge – stays the same for everything.
A **kind** is a folder of settings that tells it how to behave this time. Changing kind is a
tap; adding a kind adds a folder, not code. The planner reads the idea, proposes a kind with
its reason, and the owner taps to confirm or change it: the first choice in every plan. An
"Other" kind (general, fewer checks) covers anything not listed.

### What a kind holds

- **Roles and models**: which roles it needs (a game adds a level designer and an artist; a
  mod adds an API scout) and its Budget / Balanced / Quality sets.
- **Prompts**: what each role must know about this sort of software.
- **Tools**: what tasks may run (a browser, a Java build, an Android build).
- **Proof** – the most important part: how Roundtable shows the thing works (it starts, tests
  pass, screenshots, a game runs a minute without crashing). Without proof a kind is only a
  prompt.
- **Build and packaging targets**: website, EXE, APK, mod jar.
- **The Look step**: on, off, or another form (an art style for a game).
- **A starting template and folder layout.**
- **Plugins** to switch on.
- **Default questions** for the owner, as tap-to-answer cards with a recommendation.
- **Typical cost and time**, for the estimate.
- **Honest status**: proven, trial, or not yet – shown in the app.

### Mixing

A project has **parts**, each with one kind ("a game with a website" = a browser-game part and
a website part). **Extras** stack on a kind: accounts, online play, payments, packaging as an
APK or an EXE (the music player already worked this way: a web app plus two packaging extras).

## Every kind of software, grouped

**First** = realistic now. **Later** = possible with more work. **No** = not for this sort of
system: Roundtable can't test it itself, or a mistake costs too much.

| Group | First | Later | No |
|---|---|---|---|
| Websites | Landing page, portfolio, blog, docs site | Shop with payments | |
| Web apps | Tools, dashboards, media players, editors, offline apps | Accounts and sync, live collaboration | Banking or medical systems |
| Browser games | 2D arcade, puzzle, card, platformer, idle, text games | Simple 3D, online multiplayer | |
| Desktop apps | A web app wrapped as an EXE, small utilities | Native apps, creative tools (pixel art, video) | Full office or pro video suites |
| Mobile apps | A web app wrapped as an APK | Native Android, store release | iPhone (needs a Mac and a paid account) |
| Mods and add-ons | | Minecraft mods and data packs, Forge card scripts, browser extensions, plugins for other apps | |
| Engine games | | Godot 2D, then small Unreal projects from Fab assets | AAA 3D, big online worlds |
| Services | Small APIs, bots (Discord), scrapers | Databases with real users, hosting | High-traffic systems |
| Command-line tools and libraries | Scripts, converters, small libraries | Published packages | |
| Data and AI | Reports, charts, data clean-up | AI helpers inside apps, agent tools | Training large models |
| Automation | File and workflow scripts, build pipelines | | |
| Hardware and systems | | Hobby boards (Arduino), tested by hand | Firmware, drivers, operating systems, anything safety-critical |

## The first five, in order

1. **Web app** – proven with the music player; turn what worked into the first kind. It sets
   the pattern for every other.
2. **Browser game** – the owner's stated interest, the same tools as web, cheap to prove (it
   runs, takes input, doesn't crash); adds art and sound roles.
3. **Website** – nearly free once web app exists; the Look step does most of it; the usual
   partner part.
4. **Packaging extras: Windows EXE and Android APK** – done by hand twice; make them a tap.
5. **Minecraft / Java mod** – the first kind with no browser, so it proves kinds really reshape
   Roundtable; it also serves the Forge card engine and the mod maker.

Then: desktop tools (pixel art, video), native Android, Godot, and Unreal last (huge projects,
an editor that's hard to drive without a person, Fab licences to check).

## Parallel work

Tasks the plan marks as independent run at once, each in its own copy of the project; one
merger joins them one at a time and runs the kind's proof after every join; a cap on tasks at
once, set by the money limit as well as speed. What must come first, or parallel work
multiplies mess:

1. a **skeleton task, alone**: folder layout, design file and shared names and data shapes,
   agreed before anything fans out;
2. **file ownership**: each task names the files it may touch, never shared;
3. **proof that runs by itself**;
4. **a clear screen**: every running task visible, with its cost;
5. **spending counted across all tasks**, with one stop button.

Parallel speeds up broad work (many screens, many levels), not the early deciding work.

## What not to do

- **Roundtable doesn't rewrite its own code at a tap.** It may change kinds, prompts and model
  choices (data, easy to undo); changes to its code go a branch, tests, a review, a release.
- **Don't build twenty kinds at once.** A kind is real once something has been built with it;
  add each when a project needs it.
- **Kinds don't copy each other**: shared pieces (the web base, packaging) are written once.
- **No kind without proof.**
- Risks: cost (parallel tasks on Quality spend fast: estimate per kind, stop when well past);
  kinds and plugins from outside can run anything (only the owner's own for now);
  over-promising (show proven / trial / not yet honestly).

## Where it sits

Release 2 (Proof) comes first: kinds stand on proof. Then the first kind (web app) is written
from the music player, the packaging extras next, and the rest one at a time as projects need
them. Parallel work (release 6, True tandem) follows the skeleton-and-ownership rules above.
