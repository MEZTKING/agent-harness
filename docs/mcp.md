# Tools from other programs (MCP servers)

Some programs can be driven by AI models through **MCP** (the Model Context Protocol). The program
runs a small "MCP server" that offers tools, such as "put this actor in the level" or "read this
blueprint". The harness can hand those tools to a role, so the models doing a task can use the
program directly. Unreal Engine 5.8's MCP plugin works this way, and so do many community servers
(for Blender, databases, browsers and more).

You set this up in `harness.yaml` in two steps: say where the server is, then say which roles may
use it.

## 1. Add the server

Under `mcp_servers:`, give each server a short name (letters, digits, `-` and `_`). There are two
kinds.

**A server that is already running and has an address** (Unreal Engine's editor is one):

```yaml
mcp_servers:
  unreal:
    url: "http://127.0.0.1:8000/mcp"
```

**A program the harness starts for you** and talks to directly (most community servers):

```yaml
mcp_servers:
  blender:
    command: uvx            # the program to run
    args: [blender-mcp]     # what to put after it
    env: {LOG_LEVEL: info}  # extra settings it reads (optional)
    cwd: C:/Projects/Game   # the folder to start it in (optional)
```

Every server can also have:

| Setting | What it does | If left out |
|---|---|---|
| `tools` | Only these tools are offered, e.g. `[get_*, spawn_actor]` (`*` matches anything) | every tool |
| `timeout` | How many seconds one tool may take before the harness gives up on it | 120 |
| `enabled` | `false` turns the server off without deleting it | `true` |
| `headers` | Extra lines sent with each request (only for servers with `url`) | none |

Never put an API key or password in `harness.yaml` (not in `env`, not in `headers`). If a server
needs a key, ask for it to be added through the credential form instead.

## 2. Let a role use it

A role sees a server's tools only when the server is listed under its `mcp:`. No other role sees
them, and the reviewer doesn't either unless the reviewer role lists the server too.

```yaml
roles:
  unreal_builder:
    model: deepseek/deepseek-v4-pro
    description: builds levels, actors and blueprints in the open Unreal editor
    mcp: [unreal]
```

In the task, the tools appear with the server's name in front, for example
`mcp__unreal__call_tool`, so you can always see in the Session view which program a step used.

## 3. Check it

```
roundtable mcp list
```

This shows each server, whether it answers, which roles use it, and the names of its tools. If one
isn't answering, the message says what to do (for example: open the program, then try again).

During a run, a server that doesn't start or doesn't answer never stops the run: you'll see a
**mcp_error** in the events saying what went wrong, and the role carries on without those tools.
Servers are started the first time a task needs them and closed when the run ends.

The lab's replay tests (`roundtable improve test`) never use MCP tools, so testing a change can't
alter anything in an editor you have open.

## Example: Unreal Engine 5.8

1. In the Unreal editor, turn on the **MCP** plugin (Edit > Plugins), restart the editor and leave it
   open with your project loaded. The editor shows the address of its MCP server.
2. Add it to `harness.yaml`. The address below is the usual one (check the port your editor shows):

   ```yaml
   mcp_servers:
     unreal:
       url: "http://127.0.0.1:8000/mcp"
       timeout: 300        # big imports and builds can take a while

   roles:
     unreal_builder:
       model: deepseek/deepseek-v4-pro
       description: builds levels, actors and blueprints in the open Unreal editor
       mcp: [unreal]
   ```

3. Run `roundtable mcp list` and check that `unreal` says **answers**.
4. Start a project as usual. The planner can now give tasks to `unreal_builder`.

Good to know about Unreal's server:

- It only listens on your own computer and has no password, so the editor must be open on the same
  PC that runs the harness.
- With **Enable Tool Search** on (the default), it offers only four tools: `list_toolsets`,
  `describe_toolsets`, `describe_tools` and `call_tool`. The model first looks up what is there,
  then runs the real tool through `call_tool`. That's expected, not a fault.
- The editor does one thing at a time, so the harness sends it one request at a time.
- Tools that only read (and change nothing) are marked "(read-only)" in their description.
