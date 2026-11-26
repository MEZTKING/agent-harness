# TEST signing key – public on purpose

**This is a TEST key. Both halves are in git, so anyone can sign with it. It proves nothing.**

It signs the phone runtime's `manifest.json` when the repository has no `RUNTIME_SIGNING_KEY`
secret, so test builds of Roundtable Mobile can install a runtime before the real key exists.
Every manifest signed with it says `"channel": "test"`. It is the documented exception to
"no keys in the repository", exactly like `mobile/test-key/` for test APKs.

| File | What |
|---|---|
| `private.pem` | Ed25519 private key, PKCS#8 PEM (TEST – public) |
| `public.pem` | the public half, SubjectPublicKeyInfo PEM |
| `public.b64` | the public half as the app embeds it: the raw 32 bytes, base64 |
| `key-id.txt` | `signing.keyId`: the first 16 hex digits of SHA-256 of the raw 32 bytes |

The official phone release must not accept this key. It needs a real key: generate one offline
(`python runtime/sign_manifest.py --new-key DIR`), keep the private half out of git, add it as
the repository secret `RUNTIME_SIGNING_KEY` (the PEM text), and build the release app with the
real public key instead of this one.
