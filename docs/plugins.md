# Plugins

A plugin adds something to Darkness Harness without changing the harness itself: saving
tokens, logging costs, an extra tool for the workers, a command of its own. Two come with
it:

- **Token saver** (`token-saver`, on): big tool results are shortened before a model reads
  them; nothing is lost. Its settings are `token_saver:` in `harness.yaml`.
- **Cost log** (`cost-log`, off until you switch it on): every model call, its tokens and
  its cost go into `calls.csv` in the plugin's folder. It is also the example to copy.

## Using plugins

```
roundtable plugin list                     every plugin, on or off, and any problem
roundtable plugin add SOURCE               a folder, a git link or a pip package
roundtable plugin enable ID | disable ID   switch one on or off
roundtable plugin settings ID              show its settings
roundtable plugin settings ID key=value    change one (checked against its list)
roundtable plugin remove ID [--purge]      remove one you added (--purge: its data too)
roundtable plugin trust ID | untrust ID    let one you wrote run as the app itself, or box it again
roundtable ID COMMAND ...                  a command a plugin adds
```

`SOURCE` can be:

- **a folder** on this computer: it is copied into the harness's own folder, so it keeps
  working if you move or delete the original. `--link` uses it where it is instead (handy
  while you write one).
- **a git link** (`https://github.com/someone/my-plugin.git`): downloaded, then copied.
- **a pip package name**: downloaded and installed with pip. This needs Python on the
  computer (the Windows app has none of its own), so a folder or git link is simpler there.

Your choices (on or off, settings) are kept in `custom.yaml` next to `harness.yaml`, under
`plugins:`. Each plugin's own files go in `<app folder>/plugins/<id>/` (on Windows,
`%APPDATA%\RoundtableHold\plugins\<id>`), its code in `<app folder>/plugin-code/<id>/`.

## Its own box: read this before adding one

Every plugin you add runs **in its own box**: a separate program with no internet, no other
programs and only its own folder, unless you said yes to more. Your keys are never in it, and
the rest of the harness can't be reached from it. What it asks for (the permissions below) is
shown before anything is installed, and is then exactly what it's allowed. If it tries anything
else it's stopped, switched off until the run ends, and you're told what it tried. If a later
version asks for more, it stays off until you say yes again (`roundtable plugin enable ID`).

How strong the box is depends on the computer:

| Where | No internet | Only its own folder | No other programs |
|---|---|---|---|
| Linux with `bwrap` | the system | the system | the box* |
| Linux with `unshare` | the system | the box* | the box* |
| Windows | the box* | the box* | Windows itself (a Job Object: one process only) |
| The phone | the box* | the box* | the box* |

\* "the box" is a guard inside the plugin's own Python: it stops a plugin that tries, but it
isn't proof against one written on purpose to break out. So still add plugins only from people
you trust. A plugin with compiled parts (`.pyd`, `.so`, `.dll`, `.dylib`, `.exe`, also in its
`.deps`) is refused unless it asks to run programs, because the guard can't see inside them.

**Trusted.** A plugin you wrote yourself (or have read) can be marked Trusted in Settings >
Plugins or with `roundtable plugin trust ID`, after a warning. It then runs as the app itself,
outside its box, as all plugins did before 1.3.0. The built-in plugins are part of Darkness
Harness and always run that way.

What a boxed plugin sees differs from the table above in small ways:

- `roundtable.plugins.api` inside the box is a stand-alone copy (`boxapi.py`) with the same
  names; `api.BOXED` is `True` there. Nothing else of the harness can be imported, nor
  third-party packages unless they're in the plugin's own `.deps`.
- Everything crosses the box as plain data (JSON): `after_model_call` gets a `Response`
  (`text`, `tool_calls`, `stop_reason`, `model`) and a `Usage` (the token counts); `compact`'s
  `info` has no `cfg` and no `charge` (a boxed plugin can't call a model).
- `ctx.state` lives in the box; `ctx.shared` holds only what is plain data.
- Its prints go to `errors.log` in its folder; a command's prints are shown as before. Temporary
  files go in its folder's `tmp/`; its working folder is its own folder.
- Limits: 10 seconds a hook, 60 seconds a tool (`tool_timeout = 120` in the manifest asks for up
  to 300), 8 MB a message. Over a limit its box is stopped. After a crash it starts again once,
  then stays off until the next run.

If a plugin goes wrong during a run, the run carries on without it: the plugin is switched
off until that run ends, you see a short message, and the details go in `errors.log` in its
folder.

## Writing a plugin, step by step

1. **Make a folder**, e.g. `word-count/`.
2. **Write the manifest**, `word-count/roundtable-plugin.toml`:

   ```toml
   id = "word-count"                 # a-z, 0-9 and -, starting with a letter
   name = "Word count"
   version = "1.0.0"
   description = "Tells the run how many words each tool printed."
   author = "Your name"
   licence = "MIT"
   homepage = "https://example.org/word-count"
   entry = "word_count:WordCount"    # module:object
   api = 1                           # the plugin API version it needs
   hooks = ["on_tool_result"]        # only these are called
   permissions = []                  # see below

   [settings.min_words]
   type = "integer"                  # string, integer, number or boolean
   default = 100
   description = "Only mention results with at least this many words."
   ```

   (A Python package can put the same table under `[tool.roundtable.plugin]` in its
   `pyproject.toml` instead, and ship `roundtable-plugin.toml` inside its package folder so
   pip installs it too.)

3. **Write the code**, `word-count/word_count.py` (give the module a name no other plugin
   is likely to use):

   ```python
   from roundtable.plugins.api import Plugin

   class WordCount(Plugin):
       def on_tool_result(self, ctx, tool, args, text, is_error):
           words = len(text.split())
           if words >= ctx.settings["min_words"]:
               ctx.emit("counted", {"tool": tool, "words": words})
           return text  # what the model will read: unchanged here
   ```

4. **Add it**: `roundtable plugin add ./word-count --link`, then run a project.

The cost log (`src/roundtable/plugins/builtin/cost_log.py`) is a complete example with a
setting, a file in its own folder and an app route.

## The hooks (plugin API 1)

Each hook gets `ctx` first (except `commands` and `routes`). Declare the ones you use in
`hooks`; a hook that raises, or returns the wrong type, switches the plugin off for the rest
of the run.

| Hook | When | Gets | Returns |
|---|---|---|---|
| `on_tool_result` | each tool result, as it enters a model's conversation | `tool, args, text, is_error` | the text the model reads (a string) |
| `before_model_call` | before each model call | `role, model, system, messages` | `(system, messages)` to send |
| `after_model_call` | after each model call | `role, model, response, usage` | nothing |
| `tools` | once per conversation | – | a list of `Tool` for the model |
| `on_event` | each run event: `task_start`, `task_end`, `plan`, `approved`, `review`, `real_cost`, … | `kind, data` (a copy) | nothing |
| `commands` | `roundtable <id> COMMAND …` | – | `{name: fn(ctx, argv)}` |
| `routes` | the app calls `/api/plugins/<id>/<path>` | – | `{"GET path": fn(ctx, query, body)}`, each returning JSON-able data (or `(status, data)`) |

Notes:

- Plugins run in a fixed order and the **token saver is always first**, so the others see
  the text the model will see.
- `before_model_call` changes **what is sent this once**; the conversation kept for the next
  step isn't changed. Changing earlier messages costs money: providers cache the start of a
  conversation, and a change there misses the cache.
- A plugin's tool never replaces one of the harness's own tools with the same name.
- `on_event` never sees `plugin` or `plugin_error` events.
- A plugin's own commands and routes are only there while it's switched on.

`ctx` has:

| | |
|---|---|
| `ctx.settings` | the plugin's settings (defaults, then the owner's choices) |
| `ctx.data_dir` | its own folder, `<app folder>/plugins/<id>/` (made when first used) |
| `ctx.log` | a Python logger |
| `ctx.project_root` | the project's folder, when there is one (read it, don't write it) |
| `ctx.role` | the role this conversation is for, when known |
| `ctx.state` | a dict that lasts one conversation (one run for `on_event`) |
| `ctx.emit(kind, data)` | tell the activity feed something |
| `ctx.cost_of(model, usage)` | what a call cost in US dollars, or None |

## Permissions

| Permission | Means |
|---|---|
| `network` | Can go on the internet |
| `files` | Can read and change files on this computer outside its own folder |
| `shell` | Can run programs on this computer (and have compiled parts) |
| `project:read` | Can read the project it is helping with (never `.env`-like files, `.git` or `.harness`) |
| `secrets:<host>` | Can use your saved key for that host |

Each opens only its own door of the box. `secrets:<host>` works through `ctx.http(method, url,
headers=None, body=None)`: the harness sends the request to that host only (https, no
redirects), adds your saved key itself and takes it out of the answer, so the key never enters
the box. It answers `{"status", "headers", "body"}`. The key is the one a configured AI service
with that host uses.

## Versions

`roundtable.plugins.api.API_VERSION` is 1. A plugin says which it needs with `api = 1`; one
that needs a newer version than this copy has isn't loaded, and you're told to update.
A new hook can be added without raising the version; changing what an existing hook gets or
returns raises it.
