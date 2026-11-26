"""Sign the phone runtime's manifest.json with Ed25519 (and check a signature).

The signature covers the manifest's exact bytes and is written, base64, to manifest.json.sig
(DSH Mobile's ManifestVerifier reads the same). Before signing, `signing.keyId` (the first 16 hex
digits of SHA-256 of the raw public key) and `channel` are filled in.

The key comes from the environment variable named by --key-env (the workflow passes the
repository secret RUNTIME_SIGNING_KEY: the PEM text, or the raw 32-byte seed in base64). When
that is empty and --test-fallback is given, the public TEST key in runtime/test-key/ signs
instead and the manifest says "channel": "test".

    python runtime/sign_manifest.py out/manifest.json --key-env RUNTIME_SIGNING_KEY --test-fallback
    python runtime/sign_manifest.py out/manifest.json --verify runtime/test-key/public.b64
    python runtime/sign_manifest.py --new-key DIR       # a new key pair (keep the private half offline)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HERE = Path(__file__).resolve().parent
TEST_KEY = HERE / "test-key" / "private.pem"


def load_private(text: str) -> Ed25519PrivateKey:
    text = text.strip()
    if text.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(text.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("the signing key is not an Ed25519 key")
        return key
    seed = base64.b64decode(text, validate=True)
    if len(seed) != 32:
        raise ValueError("the signing key must be a PEM or a base64 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(seed)


def raw_public(key: Ed25519PrivateKey | Ed25519PublicKey) -> bytes:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def sign(manifest_path: Path, key: Ed25519PrivateKey, channel: str) -> tuple[bytes, str]:
    """Fill in keyId and channel, rewrite the manifest, and write manifest.json.sig next to it."""
    sys.path.insert(0, str(HERE))
    from make_manifest import dump

    manifest = json.loads(manifest_path.read_bytes())
    manifest["channel"] = channel
    manifest.setdefault("signing", {})["keyId"] = key_id(raw_public(key))
    manifest["signing"]["algorithm"] = "Ed25519"
    data = dump(manifest)
    manifest_path.write_bytes(data)
    sig = base64.b64encode(key.sign(data)).decode() + "\n"
    sig_name = manifest["signing"].get("signatureFile") or "manifest.json.sig"
    (manifest_path.parent / sig_name).write_text(sig, encoding="ascii")
    return data, sig


def verify(manifest: bytes, signature_file: str | bytes, public_raw: bytes) -> bool:
    """The app's check: raw bytes, base64 signature (whitespace allowed), a 32-byte public key."""
    if isinstance(signature_file, bytes):
        signature_file = signature_file.decode("ascii", "replace")
    try:
        sig = base64.b64decode("".join(signature_file.split()), validate=True)
        if len(sig) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public_raw).verify(sig, manifest)
        return True
    except (InvalidSignature, ValueError):
        return False


def new_key(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(directory / "private.pem", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    raw = raw_public(key)
    (directory / "public.b64").write_text(base64.b64encode(raw).decode() + "\n", encoding="ascii")
    (directory / "key-id.txt").write_text(key_id(raw) + "\n", encoding="ascii")
    print(f"new key in {directory}: key id {key_id(raw)}. Keep private.pem out of git.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("manifest", nargs="?")
    p.add_argument("--key-env", default="RUNTIME_SIGNING_KEY", help="environment variable holding the key")
    p.add_argument("--key-file", help="a key file instead (PEM or base64 seed)")
    p.add_argument("--test-fallback", action="store_true", help="sign with the public TEST key when no key is given")
    p.add_argument("--verify", metavar="PUBLIC_B64_FILE", help="check manifest.json.sig instead of signing")
    p.add_argument("--new-key", metavar="DIR", help="make a new key pair in DIR")
    args = p.parse_args(argv)
    if args.new_key:
        new_key(Path(args.new_key))
        return 0
    if not args.manifest:
        p.error("the manifest is required")
    path = Path(args.manifest)
    if args.verify:
        public_raw = base64.b64decode(Path(args.verify).read_text(encoding="ascii").strip())
        m = json.loads(path.read_bytes())
        sig = (path.parent / m["signing"].get("signatureFile", "manifest.json.sig")).read_text(encoding="ascii")
        ok = verify(path.read_bytes(), sig, public_raw)
        print("signature OK" if ok else "signature does NOT match")
        return 0 if ok else 1
    text = Path(args.key_file).read_text(encoding="ascii") if args.key_file else os.environ.get(args.key_env, "")
    if text.strip():
        key, channel = load_private(text), "stable"
    elif args.test_fallback:
        key, channel = load_private(TEST_KEY.read_text(encoding="ascii")), "test"
        print("no signing key given: signed with the public TEST key (channel test)")
    else:
        print(f"no signing key: set {args.key_env} or pass --test-fallback", file=sys.stderr)
        return 2
    sign(path, key, channel)
    print(f"signed {path} (key id {key_id(raw_public(key))}, channel {channel})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
