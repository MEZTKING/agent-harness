"""A made-up coding CLI for tests: speaks Claude Code's stream-json or Codex's exec --json.

It reads the prompt on stdin, writes a file in its folder, and prints a short stream.
FAKE_CLI_LOG (a path): it writes its argv and environment names there.
The prompt decides what it does: SLEEP (hang, for stop tests), FAIL (an error result),
NOLOGIN (a sign-in error), LOOP (the same tool call over and over).
Resuming the session "gone" fails as a lost conversation.
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
codex = "exec" in argv
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLI_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "env": sorted(os.environ), "prompt": prompt}) + "\n")


def say(obj):
    print(json.dumps(obj), flush=True)


resumed = "--resume" in argv or "resume" in argv
session = "sess-resumed" if resumed else "sess-1"
if "gone" in argv:  # a session id that no longer exists
    if codex:
        say({"type": "error", "message": "no session found"})
    else:
        say({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "No conversation found",
             "session_id": "", "num_turns": 0})
    sys.exit(1)

if "SLEEP" in prompt:
    say({"type": "system", "subtype": "init", "session_id": session, "model": "fake"} if not codex
        else {"type": "thread.started", "thread_id": session})
    with open("child.pid", "w") as f:
        f.write(str(os.getpid()))
    time.sleep(120)
    sys.exit(0)

if "NOLOGIN" in prompt:
    print("Error: not logged in. Please run /login", file=sys.stderr, flush=True)
    sys.exit(1)

if codex:
    say({"type": "thread.started", "thread_id": session})
    say({"type": "turn.started"})
    say({"type": "item.started", "item": {"id": "c1", "type": "command_execution", "command": "ls", "status": "in_progress"}})
    say({"type": "item.completed", "item": {"id": "c1", "type": "command_execution", "command": "ls",
                                            "aggregated_output": "readme.md\n", "exit_code": 0, "status": "completed"}})
    with open("hello.py", "w") as f:
        f.write("print('hello')\n")
    say({"type": "item.completed", "item": {"id": "f1", "type": "file_change", "status": "completed",
                                            "changes": [{"path": "hello.py", "kind": "add"}]}})
    if "FAIL" in prompt:
        say({"type": "turn.failed", "error": {"message": "the model gave up"}})
        sys.exit(1)
    say({"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "Added hello.py."}})
    say({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 200, "output_tokens": 80}})
    sys.exit(0)

say({"type": "system", "subtype": "init", "session_id": session, "model": "fake-model", "tools": ["Write", "Bash"]})
if "FAIL" in prompt:
    say({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "something broke",
         "session_id": session})
    sys.exit(1)
n = 30 if "LOOP" in prompt else 1
for i in range(n):
    say({"type": "assistant", "session_id": session, "message": {"content": [
        {"type": "text", "text": "I'll look first."},
        {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls"}}]}})
    say({"type": "user", "session_id": session, "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": "readme.md", "is_error": False}]}})
with open("hello.py", "w") as f:
    f.write("print('hello')\n" if not resumed else "print('hello again')\n")
say({"type": "assistant", "session_id": session, "message": {"content": [
    {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": "hello.py", "content": "print('hello')"}}]}})
say({"type": "user", "session_id": session, "message": {"content": [
    {"type": "tool_result", "tool_use_id": "w1", "content": [{"type": "text", "text": "File written"}]}]}})
say({"type": "result", "subtype": "success", "is_error": False, "result": "Added hello.py that prints hello.",
     "session_id": session, "num_turns": 3, "total_cost_usd": 0.0123,
     "usage": {"input_tokens": 900, "output_tokens": 60, "cache_read_input_tokens": 300,
               "cache_creation_input_tokens": 100}})
