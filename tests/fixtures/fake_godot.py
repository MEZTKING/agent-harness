"""A stand-in for Godot 4 in the tests: understands the flags Roundtable uses.

Markers in the project folder (given by --path) steer it:
* ``broken.gd``: prints a GDScript parse error the way Godot does;
* ``hang.marker``: sleeps far longer than any test's timeout;
* ``noframes.marker``: --write-movie writes nothing.
Each call's arguments are appended to $FAKE_GODOT_LOG (one line of JSON) when it is set.
"""

import json
import os
import struct
import sys
import time
import zlib


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30")) + chunk(b"IEND", b""))


def value(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")  # Godot writes UTF-8 whatever the computer's language
    log = os.environ.get("FAKE_GODOT_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(args) + "\n")
    project = value(args, "--path", ".")
    print("Godot Engine v4.4.stable.fake - https://godotengine.org")
    if os.path.exists(os.path.join(project, "hang.marker")):
        time.sleep(60)
    if os.path.exists(os.path.join(project, "broken.gd")):
        print('SCRIPT ERROR: Parse Error: Expected end of statement after expression, found "Identifier" instead.')
        print("          at: GDScript::reload (res://broken.gd:3)")
        print('ERROR: Failed to load script "res://broken.gd" with error "Parse error".')
        print("   at: load (modules/gdscript/gdscript.cpp:2936)")
        print('SCRIPT ERROR: Parse Error: Expected end of statement after expression, found "Identifier" instead.')
        print("          at: GDScript::reload (res://broken.gd:3)")
        print("Ünïcode in the output is fine: café")
    movie = value(args, "--write-movie")
    if movie and not os.path.exists(os.path.join(project, "noframes.marker")):
        base, _ext = os.path.splitext(movie)
        png = tiny_png()
        for i in range(int(value(args, "--quit-after", "10"))):
            with open(f"{base}{i:08d}.png", "wb") as f:
                f.write(png)
        with open(base + ".wav", "wb") as f:
            f.write(b"RIFF")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
