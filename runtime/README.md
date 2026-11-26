# The phone runtime

What Roundtable Mobile downloads once to run Roundtable on the phone itself, the way DSH Mobile
runs its harness: a small Debian with Python, git and Node, unpacked inside the app and run with
`proot`. Built and published by `.github/workflows/runtime.yml`.

| File | What |
|---|---|
| `Dockerfile` | the two layers: `base` (Debian bookworm-slim, python3, venv, git, curl, Node and npm, ripgrep) and `roundtable` (only `/opt/roundtable/venv`) |
| `build.sh ABI...` | builds `out/roundtable-base-<abi>.tar.xz` and `out/roundtable-app-<abi>.tar.xz` (`aarch64`, `x86_64`); every Python package is downloaded on the host as a wheel for that ABI (cryptography as a manylinux wheel), nothing is compiled under emulation |
| `make_manifest.py` | writes `manifest.json` (DSH's schema 1, Roundtable's names) |
| `sign_manifest.py` | signs it with Ed25519 (`manifest.json.sig`, base64) and checks a signature |
| `test-key/` | the public TEST key (see its README) |
| `smoke.sh` | local check with docker: build x86_64, unpack both layers, start the server, check it answers |

## How the app starts it

Inside proot, in the unpacked tree:

```
/opt/roundtable/venv/bin/roundtable phone serve --local --port <PORT> --home /root/.roundtable
```

with `ROUNDTABLE_LAUNCH_TOKEN` (new at every start) and `ROUNDTABLE_HOME=/root/.roundtable`
(`ROUNDTABLE_WORKSPACES=/workspaces` for the projects). It prints
`Roundtable is ready on http://127.0.0.1:<PORT>` when it is listening (`runtime.readinessPrefix`).

## The signature

`manifest.json.sig` is the Ed25519 signature of the exact bytes of `manifest.json`, base64. The
app checks it with the public key compiled into it before reading the manifest, then checks each
layer's size and SHA-256. `signing.keyId` is the first 16 hex digits of SHA-256 of the raw public
key. Without the `RUNTIME_SIGNING_KEY` secret the workflow signs with the TEST key and the
manifest says `"channel": "test"` (published as a pre-release).
