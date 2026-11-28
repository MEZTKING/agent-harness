<!-- The README's "What's new" sections, bundled with the app for its "What's new" card. Written by `python -m roundtable.updater --whatsnew-bundle`; edit the README instead. -->

### What's new in 1.4.0

It catches up: everything the two harnesses it was compared with can do, it can do too (the list is in
`plans/parity.md`).

- **A board for every project**: each task as a card – To do, Building, Waiting for you, Stuck, Done. Leave one
  out or do one again by hand, put your projects in your own order, and open one task full screen (**Focus**).
  Answer several questions at once with what's recommended.
- **Words as they are written**: you see a model's reply (and its thinking) while it writes. Type `/` in the
  message box for commands, ask a finished task a follow-up, see the messages waiting for the next task, and
  **Talk** to the planner instead of typing.
- **What each job may do**: Careful (the default), Ask every time, Free or Read only, for each job and each
  project (Settings → Builders, Models, a project's Settings). Under Careful, a tool server's first use, the
  first page on a new website and anything that deletes now wait for your tap.
- **Change a file yourself** (Files): save, undo, the full history and its branches, Word, Excel and PowerPoint
  previews, video, find in a file, and a **Browser** for the app you are building.
- **Work that starts from outside**: GitHub events, an address you name, or a program on this computer can
  start an idea – it always waits for your OK. A stand-up line each hour while something builds, CI beside
  each project, one list of every service, more tool servers to add with a tick, and **Move my data**.
- **Proof**: a picture of a Windows app's window when it starts, and Android apps opened and pictured on a test
  phone the harness starts (it offers to make one first).
- **The phone**: an update that fails puts the previous one back by itself, every failure says what to do,
  clone or import projects on This phone, a Browser tab, and the fold of a foldable phone is used.

Beta notes: the window pictures, the test phone, the phone's new parts and Talk in the Windows app are still to
be tried on your own PC and phone. The phone shows the board, the words as they are written and the rest only
from the next update.

### What's new in 1.3.0

It learns: the harness gets better from its own work, within money you set, and you can undo anything it
changed.

- **Learning by itself, on its own weekly money**: you choose an allowance (Settings → Spending; off until you
  do). Once a week it tests the changes it suggests and uses the small ones that pass. It stops at the
  allowance and says so: "Learning has used this week's $2; it carries on next week."
- **Practice tasks**: every suggested change is tried on a fixed set of small made-up tasks with checks that
  can't be argued with, beside a few of your earlier tasks. Changes to the checker's instructions can be tested
  at last.
- **Watched, and undone by itself**: after a change, the next tasks are compared with before. If the work
  clearly gets worse, the change is undone by itself and you are told in one line, with Put back.
- **What it learned** (Models): one plain line per change, each with Undo; what waits for your yes; and what it
  can never change by itself (the safety gate, your keys, money, who may see a project, plug-ins' permissions,
  your house style). The phone shows the lines too, with Undo.
- **Your house style** (Settings → How agents write): how every agent writes to you. Short and plain unless
  you say otherwise.
- **Plug-ins in their own box**: every plug-in you add runs apart from the app, with no internet, no other
  programs and only its own folder unless you allowed more. A list of plug-ins and skills under Tools, and
  **Make one**: a plug-in from one sentence, tested in its box before it is offered.
- **Ask about anything** (Search): "what did we decide about the colours?" finds the answer across your plans,
  memory, journal and **your own documents**, even in other words; Ask answers with quotes, the price shown
  first. Agents look your documents up instead of guessing (a "Never leaves this computer" tick keeps one to
  you). **Who knows what** draws which agents built and checked what.
- **Shared between your machines**: what it learned, its weekly spending and your house style travel through
  your private hub; an undo on any machine wins everywhere. Never project names, code or anyone's words.
- **Fixes to itself** (off until you say yes): when the same fault in the harness's own code happens three
  times, it can offer to try a fix for up to $1.50, as a draft pull request it never merges.

Beta notes: real learning costs real money: the first weekly cycle on your allowance shows what a test truly
costs, so watch Settings → Spending the first week. On Windows the plug-in box stops a plug-in that tries to go
online or outside its folder, but it is not proof against one written on purpose to break out (other programs
are blocked by Windows itself); only add plug-ins from people you trust.

### What's new in 1.2.0

Every model at once: several makers' models now build, check and plan together, and you choose how much.

- **Checking: Lean, Balanced or Maximum**, one choice per project, with each price shown on the plan before
  anything is built. New plans start at Balanced: tasks the planner marks hard get two builders and two
  checkers, risky ones two checkers. Maximum asks first and shows what it adds. Plans made before 1.2.0 stay
  Lean. The extra checking has its own share of the money you agreed; when that is used, the rest is built
  the usual way.
- **Best of two**: on a hard task two models from different makers build it side by side; the tests and a
  checker from a third maker pick the better one. The other is kept, with the reason, until you clear it on
  the Tidy card.
- **Checked by another maker**: work is checked by a model from a different company than the one that built
  it. A rejection only counts when it quotes the line of the task it breaks.
- **Each task to the model that does it best**: tasks are tagged by kind of work (game logic, layout,
  shaders…), and the harness learns which model wins each kind. See it under Models → Strengths.
- **Rival plans** under Maximum: two or three planners each plan the idea and your planner merges them. The
  plan shows where they disagreed.
- **Named agents**: one per job, with a name, your notes and what they learn (Models → Agents). Share one as
  a file; nothing is brought in before you have read all of it.
- **Limits per service and per job**, what each service has used this month (Settings → Spending), and who
  has seen each project (its Settings).
- **Privacy**: "Only models made by these companies" for a project, honoured by every part of the harness and
  by the lab's replays.
- **Beta until a real run**: the real cost of the extra checking, and how often a checker has to be asked
  again to quote the line, are only known after a real run with two makers. Each task shows who built it
  and who checked it, so you can see it as it happens.

### What's new in 1.1.0

Finished, not just built: the harness now checks the thing works before it calls it done.

- **"Done when"**: every plan has a short list of what you can do with the finished thing ("You can start a
  game, lose and start again"). It isn't called finished while one of them fails. Add your own lines on the
  plan page.
- **It tries what it built**: at the end it starts the app, uses it as a person would, and turns what's
  broken into fix tasks, at most two rounds. Only then does it ask you, with one card: try fixing again,
  accept it as it is, or stop.
- **Stages**: plans start with a small slice that already works, then build on it. Each task says which files
  it changes, so two tasks never fight over the same file.
- **Stuck tasks are worked out**: a model from another maker looks at why a task keeps failing and retries
  it with advice, splits it, plans around it or puts it aside. You get one card at the end, not one per task.
- **No surprises with money**: a run that would cost well past what you agreed (a quarter more, at least
  50 cents) stops and asks. Autopilot's spending limit now binds the runs it starts. Picture models get a
  price in the estimate, and the estimate shows the cost of checking and fixing.
- **The App tab can start an app** that runs with a command (Start it, Stop it), on this PC only.
- **Games are played**: a model that can see plays a browser game for a minute and says what broke.
- **New kinds**: Godot games and native Android apps (on trial); Java mods move to trial. An EXE, APK or mod
  is really built at the end, checked and started once. What this computer can't build is shown as not
  checked, with the reason, and never stops the project.
- **Beta until tried on your PC**: playing a real Godot game, building a real EXE, APK or mod, and walking an
  app in a real browser on Windows have only run against stand-ins so far.

### What's new in 1.0.0

Roundtable Hold is now Darkness Harness. Everything you have stays.

- **A new name**: Darkness Harness on the PC, Darkness on the phone. Your projects, keys, hub, settings and
  phone pairing are kept exactly where they were.
- **A new look, Eclipse**: Home is a ring of lights round an eclipse, one light for each project; the one
  that needs you flares orange. Three themes under **Settings → Look**: Eclipse, Pitch (true black) and
  Ash (light). New letters (Space Grotesk, Inter and JetBrains Mono) and new art, icon and emblem.
- **A taskbar pin you made yourself keeps working**: the old app file now just opens the new one.
- **The phone through the firewall**: after this silent update, Windows may ask once to let the phone reach
  the PC. Press **Yes**. It only asks on PCs that had the old firewall rules.
- **The phone app updates in place** and stays paired: same app, new name and look.
- **Windows SmartScreen may ask again** ("Windows protected your PC"), because the app's file name changed.
  Click **More info → Run anyway**, as before.

### What's new in 0.12.0

- **Kinds**: Roundtable knows what sort of thing you're making – a website, a web app, a browser game or
  something else – and plans, builds and checks it to suit. The plan's first card asks "This looks like a
  website. Right?"; the choice is fixed once you approve.
- **Gallery** (new tab, and on the phone): everything finished, with its pictures and checks, and what
  Roundtable can make. Hiding never deletes; "Make another like this" starts a new one.
- **Proof for every task**: pictures before and after, the tests before and after, and one line from a
  model that can see (advice for the reviewer, at most 5 cents a task, counted in the estimate).
- **Undo a task**: see the files first, then undo it or go back to before it; "Put it back" undoes the undo
  for 30 days. **Try another way** makes a separate copy from any task. Never for work already on GitHub.
- **Web search for builders**: they can look up real documentation instead of guessing (6 searches a task
  at most; off for projects kept to some providers). Switch and engine on the Tools page.
- **Command line** (a project's new tab, this PC only): type commands in its folder. A task's command
  shows as it prints, with a Stop for that one command.
- **Pounds**: costs also show as "≈ £" beside the dollars (Settings → Spending; the bank's daily rate).
- **Phone comfort** (beta until tried on your phone): accent colour, true black, text size, buzz, pinned
  and put-away projects, what you sent, how much Watch shows, a battery checklist, and two panes on a
  tablet or an open foldable.
- **The phone finds your PC on the Wi-Fi** (beta until tried at home): "Look for my PC" when pairing, and
  "Look for it" when the PC's address changed. The installer lets the phone in on private networks only.
