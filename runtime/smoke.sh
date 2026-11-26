#!/usr/bin/env bash
# Local smoke test of the phone runtime (not run in CI): build the x86_64 layers, unpack both
# into one root file system as the phone app would, start `roundtable phone serve --local` in it
# with docker, and check /api/health, the launch token and the key store from inside.
#
#   runtime/smoke.sh                  # builds first
#   SKIP_BUILD=1 runtime/smoke.sh     # reuse runtime/out/
#   BASE_IMAGE=mirror.gcr.io/library/debian:bookworm-slim runtime/smoke.sh   # if Docker Hub refuses
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="$here/out"
abi=x86_64
port=18766
image=roundtable-runtime-smoke
[ -n "${SKIP_BUILD:-}" ] || "$here/build.sh" "$abi"

root="$(mktemp -d)"
trap 'docker rm -f "$image" >/dev/null 2>&1 || true; rm -rf "$root"' EXIT
tar -C "$root" -xJf "$out/roundtable-base-$abi.tar.xz"
tar -C "$root" -xJf "$out/roundtable-app-$abi.tar.xz"
tar -C "$root" -c . | docker import - "$image" >/dev/null

token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker rm -f "$image" >/dev/null 2>&1 || true
# the token goes in through the environment only, as the phone app passes it
docker run -d --name "$image" -e ROUNDTABLE_LAUNCH_TOKEN="$token" -e ROUNDTABLE_HOME=/root/.roundtable \
  -e ROUNDTABLE_WORKSPACES=/workspaces "$image" \
  /opt/roundtable/venv/bin/roundtable phone serve --local --port "$port" --home /root/.roundtable >/dev/null

for _ in $(seq 1 30); do
  docker logs "$image" 2>&1 | grep -q "Roundtable is ready on" && break
  sleep 1
done
docker logs "$image" 2>&1 | tail -3
ex() { docker exec "$image" "$@"; }
code() { ex curl -s -o /dev/null -w '%{http_code}' "$@"; }

health="$(ex curl -sf "http://127.0.0.1:$port/api/health")"
echo "health: $health"
[ "$(code "http://127.0.0.1:$port/api/projects")" = 401 ] || { echo "FAIL: no token was let in"; exit 1; }
[ "$(code -H 'Authorization: Bearer wrong-token-wrong-token' "http://127.0.0.1:$port/api/projects")" = 401 ] \
  || { echo "FAIL: a wrong token was let in"; exit 1; }
docker exec -e T="$token" "$image" sh -c "curl -sf -H \"Authorization: Bearer \$T\" http://127.0.0.1:$port/api/roles" \
  | grep -q deepseek-v4-flash || { echo "FAIL: roles"; exit 1; }
ex git --version
ex node --version
echo "smoke test passed"
