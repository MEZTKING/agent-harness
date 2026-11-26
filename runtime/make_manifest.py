"""Write the phone runtime's manifest.json from the built layer archives.

The format is DSH Mobile's runtime manifest, schema 1 (its RuntimeManifest.kt), with Roundtable's
names: product "roundtable", layers "base" and "roundtable", xz-compressed tar archives. The
manifest is signed afterwards by sign_manifest.py, which fills in `signing.keyId` and `channel`.

    python runtime/make_manifest.py --release-tag runtime-2026.11.26-1 --repo OWNER/REPO \
        --roundtable-version 0.7.3 --layer arm64-v8a:base:out/base-aarch64.tar.xz ... --out out/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
PRODUCT = "roundtable"
LAYER_BASE, LAYER_ROUNDTABLE = "base", "roundtable"
LAYER_ORDER = (LAYER_BASE, LAYER_ROUNDTABLE)
ROUNDTABLE_HOME = "/opt/roundtable"
ENTRYPOINT = f"{ROUNDTABLE_HOME}/venv/bin/roundtable"
READINESS_PREFIX = "Roundtable is ready on"  # onphone.READY
DEBIAN_ARCH = {"arm64-v8a": "arm64", "x86_64": "amd64"}  # Android ABI -> Debian's name
TAG = re.compile(r"^runtime-(\d{4})\.(\d{2})\.(\d{2})-(\d{1,3})$")


def sequence_from_tag(tag: str) -> int:
    """runtime-2026.11.26-1 -> 2026112601: later tags always have a higher sequence."""
    m = TAG.match(tag)
    if not m:
        raise ValueError(f"release tag {tag!r} must look like runtime-2026.11.26-1")
    y, mo, d, n = m.groups()
    if int(n) > 99:
        raise ValueError("at most 99 releases a day")
    return int(f"{y}{mo}{d}{int(n):02d}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tar_stats(path: Path) -> tuple[int, int]:
    """(unpacked bytes of regular files, number of entries) of a .tar.xz."""
    size = entries = 0
    with lzma.open(path) as raw, tarfile.open(fileobj=raw, mode="r|") as tar:
        for member in tar:
            entries += 1
            if member.isfile():
                size += member.size
    return size, entries


def layer_entry(abi: str, name: str, path: Path, ids: dict[str, str]) -> dict:
    if name not in LAYER_ORDER:
        raise ValueError(f"layer {name!r}: use {' or '.join(LAYER_ORDER)}")
    digest = sha256(path)
    unpacked, entries = tar_stats(path)
    entry = {
        "file": path.name, "size": path.stat().st_size, "sha256": digest, "name": name,
        "id": f"{ids[name]}-{digest[:12]}", "compression": "xz", "format": "tar",
        "unpackedSize": unpacked, "entries": entries,
    }
    if name == LAYER_ROUNDTABLE:
        entry["owns"] = [ROUNDTABLE_HOME]
    else:
        entry["excludes"] = [ROUNDTABLE_HOME]
    return entry


def build_manifest(*, release_tag: str, repo: str, roundtable_version: str, layers: list[tuple[str, str, Path]],
                   min_app_version: str = "0.8.0", python_version: str = "", node_version: str = "",
                   debian: str = "bookworm", created_at: str | None = None, previous: dict | None = None) -> dict:
    archs: dict[str, dict] = {}
    ids = {LAYER_BASE: f"debian-{debian}", LAYER_ROUNDTABLE: f"roundtable-{roundtable_version}"}
    for abi, name, path in layers:
        if abi not in DEBIAN_ARCH:
            raise ValueError(f"ABI {abi!r}: use {' or '.join(DEBIAN_ARCH)}")
        arch = archs.setdefault(abi, {"debianArch": DEBIAN_ARCH[abi], "proot": [], "layers": []})
        arch["layers"].append(layer_entry(abi, name, Path(path), ids))
    for abi, arch in archs.items():
        arch["layers"].sort(key=lambda layer: LAYER_ORDER.index(layer["name"]))
        if [x["name"] for x in arch["layers"]] != list(LAYER_ORDER):
            raise ValueError(f"{abi}: needs exactly one base and one roundtable layer")
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "product": PRODUCT,
        "channel": "test",  # sign_manifest.py sets "stable" when signed with the real key
        "releaseId": release_tag.removeprefix("runtime-"),
        "sequence": sequence_from_tag(release_tag),
        "createdAt": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minAppVersion": min_app_version,
        "signing": {"algorithm": "Ed25519", "keyId": "", "signatureFile": "manifest.json.sig"},
        "assetBaseUrl": f"https://github.com/{repo}/releases/download/{release_tag}/",
        "harness": {"package": "roundtable-hold", "version": roundtable_version},
        "python": {"version": python_version, "home": f"{ROUNDTABLE_HOME}/venv"},
        "node": {"version": node_version, "home": "/usr"},
        "debian": debian,
        "runtime": {
            "entrypoint": ENTRYPOINT,
            "args": ["phone", "serve", "--local", "--port", "{port}", "--home", "/root/.roundtable"],
            "env": {"ROUNDTABLE_HOME": "/root/.roundtable", "ROUNDTABLE_WORKSPACES": "/workspaces"},
            "launchTokenEnv": "ROUNDTABLE_LAUNCH_TOKEN",
            "readinessPrefix": READINESS_PREFIX,
            "healthPath": "/api/health",
            "workspaces": "/workspaces",
            "fakeProc": [],
            "resolvConf": "/etc/resolv.conf",
        },
        "archs": archs,
    }
    if previous:
        manifest["previous"] = previous
    return manifest


def dump(manifest: dict) -> bytes:
    """The exact bytes that are signed (and published)."""
    return (json.dumps(manifest, indent=2, sort_keys=False, ensure_ascii=True) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--release-tag", required=True)
    p.add_argument("--repo", required=True, help="OWNER/REPO the release is published in")
    p.add_argument("--roundtable-version", required=True)
    p.add_argument("--min-app-version", default="0.8.0")
    p.add_argument("--python-version", default="")
    p.add_argument("--node-version", default="")
    p.add_argument("--layer", action="append", default=[], metavar="ABI:NAME:PATH",
                   help="e.g. arm64-v8a:base:out/roundtable-base-aarch64.tar.xz (repeat)")
    p.add_argument("--previous", help="the previous release's signed manifest.json, to link back to")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    layers = []
    for spec in args.layer:
        abi, name, path = spec.split(":", 2)
        layers.append((abi, name, Path(path)))
    previous = None
    if args.previous:
        old = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        previous = {"releaseId": old["releaseId"], "harnessVersion": old["harness"]["version"],
                    "sequence": old["sequence"],
                    "manifestUrl": old["assetBaseUrl"] + "manifest.json"}
    m = build_manifest(release_tag=args.release_tag, repo=args.repo, roundtable_version=args.roundtable_version,
                       layers=layers, min_app_version=args.min_app_version, python_version=args.python_version,
                       node_version=args.node_version, previous=previous)
    Path(args.out).write_bytes(dump(m))
    print(f"wrote {args.out} (sequence {m['sequence']}, {', '.join(m['archs'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
