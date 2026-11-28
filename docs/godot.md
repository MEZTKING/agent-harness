# Making a game in Godot (and Blender) with Darkness Harness

Godot suits the harness well. A Godot project is plain text files (scenes, scripts, settings),
so the harness's models can read and write it directly, and Godot runs without a screen, so
the harness can start the game itself to check it. Blender makes the 3D models; Godot reads
Blender's files as they are.

There are three ways for the models to work, and you can use all three together:

1. **Through the files.** Nothing to install for the models: they write scenes and GDScript
   like any other code. Works anywhere, including the cloud.
2. **Inside the open Godot editor**, through the Godot MCP plug-in: add nodes, run the game,
   send key presses, take screenshots, read errors. Your PC.
3. **Inside Blender**, through MCP for Blender: make and change models, look at the scene,
   bring in free assets. Your PC.

## 1. Install

- **Godot 4.7** (or at least 4.4) from godotengine.org. It's one file, no installer; put it
  somewhere fixed, such as `C:\Godot\`.
- **Blender** (any recent version) from blender.org.
- **Node.js** (the LTS version) from nodejs.org, for the Godot plug-in's helper.
- **uv**, for the Blender plug-in's helper. In PowerShell:
  `winget install --id=astral-sh.uv -e`, then open a new terminal.

## 2. Turn on the Godot plug-in

In your Godot project:

1. Open the **Asset Store** tab (Godot 4.7; in older versions **AssetLib**), search
   **Godlink**, and install **Godlink MCP** (in older versions: "Godot AI Assistant tools MCP").
2. **Project → Project Settings → Plugins**: tick **Godot MCP**.
3. The editor's corner shows **MCP: No Agent** (orange) until something connects, then
   **MCP: Agent Active** (green).

It's [tomyud1/godot-mcp](https://github.com/tomyud1/godot-mcp) (MIT, free, 69 tools). It talks to
the editor on port 6505 on this PC only. Ctrl+Z doesn't undo what the AI did; ask it to use its
own undo instead.

## 3. Turn on the Blender plug-in

In a terminal: `uvx mcp-for-blender@2.3.3 install-addon`. Then in Blender:

1. **Edit → Preferences → Add-ons**: tick **Interface: MCP for Blender**.
2. In the 3D view press **N**, open the **MCP for Blender** tab, press **Start MCP Server**.

It's [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) (MIT, free). Good to know:

- It can run any Python inside Blender. **Save your work first.**
- It sends anonymous usage numbers unless told not to; the settings below turn that off.
- Free models from **Poly Haven** need no account and no credit (CC0). **Poly Pizza** models
  mostly need a credit line in your game (CC-BY). Sketchfab and the AI model makers need their
  own paid keys.

## 4. Tell Darkness Harness about them

In `harness.yaml`:

```yaml
mcp_servers:
  godot:
    command: cmd                       # on Windows; on Mac or Linux: command: npx
    args: ["/c", "npx", "-y", "godot-mcp-server@0.6.1"]   # Mac or Linux: ["-y", "godot-mcp-server@0.6.1"]
    timeout: 180
  blender:
    command: uvx
    args: ["mcp-for-blender@2.3.3"]
    env: {DISABLE_TELEMETRY: "true"}
    timeout: 300

godot:
  path: C:\Godot\Godot_v4.7-stable_win64_console.exe   # so the harness can start the game to check it

roles:
  game_builder:
    model: openrouter/anthropic/claude-sonnet-5.5
    description: Builds the game in Godot (scenes, GDScript, levels)
    mcp: [godot]
  modeller:
    model: openrouter/anthropic/claude-sonnet-5.5
    description: Makes 3D models in Blender and exports them as .glb into the game's models/ folder
    mcp: [blender]
```

With Godot and Blender open, `roundtable mcp list` should show both answering. If `uvx` isn't
found, use its full path (`where uvx` shows it) as `command`.

## 5. From Blender to the game

Save or export models as **glTF (.glb)** straight into the Godot project's folder (for example
`models/`). Godot imports them by itself, and updates them when the file changes. The `modeller`
role above is told to do exactly that, so the `game_builder` can place them.

## How Darkness Harness checks a Godot game

When a project has a Godot 4 game (`project.godot` in the project's folder or one folder down,
such as `game/`), the harness checks it itself after every approved task. The editor needn't be
open.

1. It opens the project without a window and runs the main scene for a moment, noting every
   script or loading error with the file and line Godot gives.
2. It runs the game again with Godot's Movie Maker for a few seconds and keeps three pictures:
   early on, halfway and the end. You see them in Live, on the seat and on the phone, with any
   errors listed under them.
3. While building, the coder and the reviewer have a **run_game** tool: they start the game
   themselves and fix their own errors before you see them.

The harness never downloads Godot. It looks at the `godot: path` setting, then `GODOT`, then
`godot` or `godot4` on the computer, then the usual folders. On Windows, point it at the
**console** Godot program (it comes in the same zip) so the harness can read its messages:

```yaml
godot:
  path: C:\Godot\Godot_v4.7-stable_win64_console.exe
  frames: 90      # how much of the game is recorded (30 frames a second)
  timeout: 120    # seconds before a stuck game is stopped
  enabled: true   # false: never start Godot
```

If Godot isn't found the task still finishes and the harness says so. The main scene must be
set (**Project → Project Settings → Application → Run → Main Scene**), or there's nothing to start.

## Playing it for a minute (beta)

Pick **Godot game** when you start a project (the harness suggests it when your idea says "Godot"). On
top of the checks above, the harness then plays the game itself:

1. It reads the game's controls (the input actions in **Project → Project Settings → Input Map**,
   such as `move_left` or `jump`) and plans a minute of pressing them in turn.
2. It starts the game with a small helper script that presses them, kept in a temporary folder outside
   your project and deleted afterwards. Your project's files are never changed.
3. Godot's Movie Maker records the play, and twelve pictures from it are kept in
   `.harness/play/`. A model that can see looks at them with any errors Godot printed, and says
   what broke, what felt rough, and any ideas.

Anything broken (an error, a frozen picture, controls that do nothing) becomes a fix task. Rough
things and ideas are listed for you to choose from; nothing is built from them by itself. Each play
costs at most $0.30 (a 20-second start check, less), set in `harness.yaml`:

```yaml
playtest:
  enabled: auto   # off: never play it
  seconds: 60     # how long a play lasts
  turns: 12       # pictures kept from a play (browser games: inputs chosen one at a time)
  max_usd: 0.30   # the most one play may cost
```

Without a model that can see, without Godot or without a screen (on Linux: no display and no
`xvfb-run`), the game isn't played and the check stays "not checked", never ticked. The controls must
be input actions: a game that reads raw keys can't be played this way.

This is still in beta: it has been tried with a stand-in for Godot, not yet with a real Godot on your PC.

## If something goes wrong

- **Godot says "MCP: Disconnected" (red)**: the helper isn't running. Check `roundtable mcp list`,
  and that Node.js is installed (`node --version` in a terminal).
- **"spawn uvx ENOENT" or "uvx isn't recognised"**: open a new terminal after installing uv, or use
  the full path to `uvx`.
- **Blender doesn't answer**: press **Start MCP Server** again in the N panel. Only one program can
  use port 9876 at a time.

## Using Claude Code instead

In the Godot project's folder: `claude mcp add godot -- npx -y godot-mcp-server@0.6.1` and
`claude mcp add blender uvx mcp-for-blender@2.3.3`, then `claude`.
