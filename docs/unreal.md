# Making a game in Unreal Engine with Darkness Harness

Unreal Engine 5.8 and later has a built-in plug-in, **Unreal MCP**, that lets AI tools work
inside the editor: place and change things in a level, build Blueprints and widgets, make
materials, import assets, run tests. The harness's models can use it, and so can Claude Code.

Everything here happens on **your Windows PC**: Unreal needs its graphics card, so a cloud
session can't run it. Unreal MCP is marked *Experimental* by Epic: things may change between
versions, and it sometimes drops connections.

## 1. Install Unreal Engine

1. Install the **Epic Games Launcher** from epicgames.com and sign in.
2. Go to **Unreal Engine → Library**, press **+** next to *Engine Versions*, choose **5.8**
   (or newer) and **Install**. It needs about 60 GB.
3. If you bought a kit on Fab (a Soulslike template, say), check its page says it works
   with your version, then **Add to project** from the Launcher's *Fab Library*.

## 2. Turn on Unreal MCP

Open your project, then:

1. **Edit → Plugins**, search **Unreal MCP**: it should already be ticked.
2. Search **All Toolsets** and tick it. Restart the editor when it asks.
3. **Edit → Editor Preferences → Agentic Workflows → Model Context Protocol**:
   - **Auto Start Server** on (it is by default).
   - Note the **Server Port Number** (8000 unless you changed it).

The editor now listens at `http://127.0.0.1:8000/mcp`, on this PC only. It has no password:
any program on your PC could use it, so close the editor when you're not working.

## 3. Use it with Claude Code (the quickest way)

1. In the same preferences page, under **MCP Client**, leave *Claude Code* chosen and press
   **Generate Client Config**. It writes `.mcp.json` into your project's folder.
2. Open a terminal in your project's folder and run `claude`.
3. Try: *"What actors do I have selected?"*, then *"Make a Blueprint door that opens when the
   player walks up to it."*

To have the session appear on the harness's Hall too, run `roundtable connect` in that folder
once (see the README).

## 4. Use it from Darkness Harness

The harness's own models (DeepSeek, GLM, Claude and the rest) can drive the editor once your
`harness.yaml` names the server and gives it to a role:

```yaml
mcp_servers:
  unreal:
    url: http://127.0.0.1:8000/mcp   # the port your editor shows
    timeout: 300                      # Unreal can take a while to build things

roles:
  unreal_builder:
    model: openrouter/anthropic/claude-sonnet-5.5
    description: Builds the game in the Unreal editor (Blueprints, levels, assets)
    mcp: [unreal]
```

Check it works with `roundtable mcp list` while the editor is open: it shows each server,
whether it answers and its tools. The details of `mcp_servers` are in [mcp.md](mcp.md).

Then write your idea as usual (`roundtable new`, `plan`, `approve`, `run`). Tasks for the
`unreal_builder` role are done inside the open editor; keep it open while the run goes.

## If something goes wrong

- **"Unreal isn't answering"**: the editor is closed, the project is still loading, or the
  port is different. Open the project, check the port in the preferences, and try again.
- **It connects, then drops at once**: a known problem with the experimental server. Restart
  the editor; if it keeps happening, type `ModelContextProtocol.StartServer` in the editor's
  console (the `~` key) to start it by hand.
- **Port 8000 is taken by something else**: change *Server Port Number*, press *Generate
  Client Config* again, and change the `url` in `harness.yaml` to match.

Epic's own page: [Unreal MCP in Unreal Editor](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-mcp-in-unreal-editor).
