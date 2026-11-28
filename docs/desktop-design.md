# The desktop command centre: how it is laid out

The owner writes the idea and decides; agents build. The desktop app exists so that every
decision is one tap away and every piece of work can be watched, without leaving the app.
Look: **Eclipse** (black with a thin ring of light; each project is a light on the ring, and the one
that needs you flares ember-orange at the top). Words: plain British English, no ids, file paths, variable names or role jargon; a
tooltip on anything not obvious; every empty page says what to do next.

## The rooms (top bar)

| Room | What's there |
|---|---|
| **Home** | The Ring: every project as a light on the ring with its card outside it (picture, friendly name, state in words, what waits). A project that is building pulses slowly; the one that needs you flares and moves to the top. "+ New idea" is the unlit point. Beside it the first thing that needs you, answered on the card; "My notes" as a small entry under the ring. More than ten projects (or a narrow window): the ring shrinks into the heading and the cards become a grid, so twenty fit. |
| **Needs you** (count) | Everything that waits, grouped by project, then questions and decisions → money and stopped work → to-dos → letters. Each card is answered where it is: an option, your own answer, accept or turn down an idea, approve a plan (here, or through the hub for a project on another computer), try again or skip, done, read and reply. |
| **Projects** | Every project in one list with filters (Needs you, Building, Finished, Elsewhere), and **+ New project**. |
| **Letters** | Letters from projects and agents as sentences ("Pixel Pond asks: …"), reply in place, read ones folded. Write to any project. |
| **Activity** | Minutes from every project in plain words, filterable by project; **Background work** (what the app is doing now, each with its log). |
| **Models** | **Who does what**: every job (Planner, Coder, Reviewer…) with its model and backups, for each set (Budget, Balanced, Quality) and the base choice; change any of them from a list; which set is used unless a project picks one. **Health check** and **Learning** (Roundtable's own suggestions) as tabs. |
| **Settings** | Keys (by maker, with Test), AI services, the recommended setup, spending limits every machine shares, the hub, your phone (pairing and Your computers), backups, plugins, updates, look, and an Advanced part. |

The header also carries today's spending, the running work (opens Background work) and the
Autopilot switch with what it did.

The phone and the PC are one Roundtable (sync.py): a project card says which machine builds it ("Building on
your phone"), Home shows Your computers, a build on another machine is watched line by line on the
project's Watch tab, Carry on reaches the machine that has the files, and the base model choices, the
default set and the spending limits are shared with every machine. All of it lives in `machines.js`
(and Settings → Spending), and is only asked for when this copy has those routes (`/api/features`).

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

1. **Start a project from an idea** – Home → **+ New idea** on the ring (or Projects → **+ New project**) →
   tap the answers (what, the idea, like what, which set, looks) → **Make the plan** → the project
   page opens on its Plan tab while the planner works.
2. **Answer what waits** – the flaring light on Home, or **Needs you** → tap an option on the card (or
   Other… and type) → done; the next card moves up. Several in a row without leaving the page.
3. **Approve and watch a build** – Needs you's plan card → **Approve and start** (or Read the plan
   first) → project page → **Watch** follows each step live; the Overview shows tasks and money
   against the estimate; **App** shows the app itself.
4. **Change who does a job** – Models → the job's row → **Change** → pick the main model and its
   backups from the list (and how hard it thinks) → Save. It applies to the set shown; the default
   set is marked. A project can pick its own set on its Settings tab.
5. **Fix a key** – a model without a key is marked in Models with **Add the key**, which opens
   Settings → Keys at that maker → paste → **Save** → **Test** says in words whether it works.

## The office (1.5.0)

Home has a **Ring | Office** switch once the office has its pictures (`ui/static/office.js` `officeSwitch`); until
then the Ring stays and no switch shows. The office is drawn from what the harness already knows
(`office.py` `scene`: which agent works on what, who waits for the owner, who is resting): each agent walks to the
desk, the shelf, the terminal or the mailbox, with a small bubble for a question, a tick, a warning, a letter or
money. It only places pictures made by a picture model (`docs/art.md`), crisp at any scale, still for reduced
motion. The office art's sample card (Make the rest, Try again, Stop here) shows in Needs you on the PC only.

## How it's built

Vanilla JavaScript modules, no build step (`src/roundtable/ui/static/*.js`, all in one folder so the
package data and the Windows build pick them up). `core.js` holds the shared helpers (elements,
the API, words for states, jobs and models), `asks.js` the answer card, one module per room, and
`app.js` the shell and the router. Every element is built with `h()` (text, never HTML), because
journal entries, letters and logs contain model output.

## The look: Eclipse

Chosen by the owner from three concept boards (Eclipse, Obsidian Forge, Abyss) on 27 November 2026.

**Three themes** (Settings → Look; `theme.js` sets `data-theme` on `<html>` before the page draws, stored in
`rt-theme`; the old "dark" becomes Eclipse and "light" becomes Ash):

| Theme | What it is |
|---|---|
| **Eclipse** (the usual one) | Near-black `#0a0a0f`, surfaces `#14141c`, corona-violet accent `#a78bfa`, ember flare `#ff9d4d` for what needs you |
| **Pitch** | True black `#000000` for OLED screens; otherwise Eclipse |
| **Ash** | Light, for bright rooms and sunlight; never the default. Accent `#5b3fd6`, flare `#b3480a` |

**Tokens.** Every colour lives in one block at the top of `static/style.css`, between `tokens: start` and
`tokens: end`: `:root` is Eclipse, `:root[data-theme="pitch"]` and `:root[data-theme="ash"]` override it. Names:
`--color-background`, `-surface`, `-sunken`, `-raised`, `-text`, `-muted`, `-accent`, `-accent-text`, `-accent-soft`,
`-flare` (needs you), `-good`, `-bad`, `-warn` (each with `-soft`), `-line` (decorative), `-line-strong` (input and
control borders), `-paper` (behind pages and QR codes that must stay white), `-scrim` (under text that sits over the
backdrop art) and `-backdrop-peak` (the brightest the art may be under that text); `--term-*` for the session
transcript, dark in every theme. The older names (`--color-oak-line`, `--color-candle-glow`, `--color-ok` …) are
gone: every page module uses the new ones, and a test keeps it so. `tests/test_contrast.py` checks every text colour at 4.5:1 on
each background it sits on, control borders at 3:1, text over the backdrop on its scrim, in all three themes, and
that no colour is written outside the block.

**Type.** Display: Space Grotesk (600–700, tracking −0.02em). Body: Inter. Mono: JetBrains Mono. All SIL Open Font
Licence, bundled as `.woff2` from the `@fontsource-variable` 5.3.0 packages; nothing is loaded from outside.
Corners: 10px (cards), 8px (fields, pictures).

**Art and chrome.** Artwork is made by image models (see `docs/art.md`): `eclipse.webp` (the wide backdrop behind
the Ring), `ring.webp` (the ring, layered over it), `emblem.png` (the header mark), `icon.png`, `wordmark.webp`
(the name in the middle of the ring). Code draws only chrome: borders, gradients, the lights, their pulse and flare.
Until a picture is there the page still looks right: a near-black radial gradient stands in for the backdrop, a thin
violet line of light for the ring (`hall.js` checks for `ring.webp` and adds `.art` when it loads), and the name in
Space Grotesk for the wordmark.

**Motion.** Slow and sparse: the ring breathes on a 6-second cycle (`--breathe`), building lights pulse on the same
cycle, a flare takes 400 ms (`--flare-in`), pages fade in over 160 ms. Glow only on what needs you and on the main
button. Everything stops under `prefers-reduced-motion`.

**State is never colour alone**: every light has its card with the state in words.
