# The desktop command centre: how it is laid out

The owner writes the idea and decides; agents build. The desktop app exists so that every
decision is one tap away and every piece of work can be watched, without leaving the app.
Look: **Candlelit Oak** (a warm hall, a carved round table, the seat that needs you lit by a
candle). Words: plain British English, no ids, file paths, variable names or role jargon; a
tooltip on anything not obvious; every empty page says what to do next.

## The rooms (top bar)

| Room | What's there |
|---|---|
| **Hall** | The round table: every project as a seat (picture, friendly name, state in words, what waits). The seat that needs you glows. Beside it the first thing that needs you, answered on the card; "My notes" as a small entry under the table. More than ten seats: the table becomes a heading and the seats a grid, so twenty fit. |
| **Needs you** (count) | Everything that waits, grouped by project, then questions and decisions → money and stopped work → to-dos → letters. Each card is answered where it is: an option, your own answer, accept or turn down an idea, approve a plan (here, or through the hub for a project on another computer), try again or skip, done, read and reply. |
| **Projects** | Every project in one list with filters (Needs you, Building, Finished, Elsewhere), and **+ New project**. |
| **Letters** | Letters from projects and agents as sentences ("Pixel Pond asks: …"), reply in place, read ones folded. Write to any project. |
| **Activity** | Minutes from every project in plain words, filterable by project; **Background work** (what the app is doing now, each with its log). |
| **Models** | **Who does what**: every job (Planner, Coder, Reviewer…) with its model and backups, for each set (Budget, Balanced, Quality) and the base choice; change any of them from a list; which set is used unless a project picks one. **Health check** and **Learning** (Roundtable's own suggestions) as tabs. |
| **Settings** | Keys (by maker, with Test), AI services, the recommended setup, the hub, backups, plugins, updates, phone (hidden until its release), look, and an Advanced part. |

The header also carries today's spending, the running work (opens Background work) and the
Autopilot switch with what it did.

## The project page

Heading: the project's name, its state in words, where it runs, the goal, and the one button that
moves it on (Approve and start, Try again, Carry on, Raise the limit, Add to it). Tabs:

- **Overview** – what waits for you here (answered in place), the tasks with their state, money so
  far against the estimate, the newest picture, talk to the planner (ask a question or give an
  instruction for the next tasks), the final report.
- **Plan** – the living plan: the estimate and the set of models, your input cards, what it should be
  like, the looks, the second opinion, scope and rules, each part with its tasks, the history. A
  project on another computer shows its published plan with its cards, answered through the hub.
- **Watch** – the session: each task's steps as they happen (what each model said, read, changed and
  ran; changes in colour; pictures), and the files it made; the models used and the full log folded.
- **App** – the real app running live (computer or phone width) and the pictures after every task.
- **Journal** – the project's notes, to-dos, plans and decisions; add one; what other agents read
  about it.
- **Settings** – the project's own settings in plain words (its set of models, limits, checks, look,
  pictures, notes), and "never on autopilot".

## The five most common jobs

1. **Start a project from an idea** – Hall → **+ New project** (or the empty chair at the table) →
   tap the answers (what, the idea, like what, which set, looks) → **Make the plan** → the project
   page opens on its Plan tab while the planner works.
2. **Answer what waits** – the glowing seat, or **Needs you** → tap an option on the card (or
   Other… and type) → done; the next card moves up. Several in a row without leaving the page.
3. **Approve and watch a build** – Needs you's plan card → **Approve and start** (or Read the plan
   first) → project page → **Watch** follows each step live; the Overview shows tasks and money
   against the estimate; **App** shows the app itself.
4. **Change who does a job** – Models → the job's row → **Change** → pick the main model and its
   backups from the list (and how hard it thinks) → Save. It applies to the set shown; the default
   set is marked. A project can pick its own set on its Settings tab.
5. **Fix a key** – a model without a key is marked in Models with **Add the key**, which opens
   Settings → Keys at that maker → paste → **Save** → **Test** says in words whether it works.

## How it's built

Vanilla JavaScript modules, no build step (`src/roundtable/ui/static/*.js`, all in one folder so the
package data and the Windows build pick them up). `core.js` holds the shared helpers (elements,
the API, words for states, jobs and models), `asks.js` the answer card, one module per room, and
`app.js` the shell and the router. Every element is built with `h()` (text, never HTML), because
journal entries, letters and logs contain model output.
