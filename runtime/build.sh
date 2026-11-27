#!/usr/bin/env bash
# Build the phone runtime's layers for one or more ABIs (aarch64, x86_64) into runtime/out/.
#
#   runtime/build.sh x86_64            # one ABI
#   runtime/build.sh aarch64 x86_64    # both (aarch64 needs qemu: docker run --privileged tonistiigi/binfmt --install arm64)
#
# Each ABI gives two archives: roundtable-base-<abi>.tar.xz (Debian, Python, git, Node) and
# roundtable-app-<abi>.tar.xz (/opt/roundtable/venv with Roundtable and its packages).
# BASE_IMAGE=mirror.gcr.io/library/debian:bookworm-slim uses a mirror of the same image.
# Then make_manifest.py and sign_manifest.py write and sign manifest.json (the workflow does).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
out="$here/out"
abis=("$@")
[ ${#abis[@]} -gt 0 ] || abis=(aarch64 x86_64)

mkdir -p "$out"
rm -rf "$out"/wheels-*
python3 -m pip wheel --no-deps --quiet -w "$out/wheels-app" "$repo"
printf '*\n!wheels-*\n' > "$out/.dockerignore"  # send only the wheels to docker
pyver="${PYTHON_VERSION:-3.11}"  # Debian bookworm's python3

for abi in "${abis[@]}"; do
  case "$abi" in
    aarch64) platform=linux/arm64 ;;
    x86_64) platform=linux/amd64 ;;
    *) echo "unknown ABI $abi (use aarch64 or x86_64)" >&2; exit 2 ;;
  esac
  wheels="$out/wheels-$abi"
  mkdir -p "$wheels"
  cp "$out"/wheels-app/*.whl "$wheels/"
  plats=()
  for t in manylinux2014 manylinux_2_17 manylinux_2_28 manylinux_2_31 manylinux_2_34 linux; do plats+=(--platform "${t}_$abi"); done
  echo "== $abi: wheels for Python $pyver"
  python3 -m pip download --quiet --only-binary=:all: --python-version "$pyver" --implementation cp \
    "${plats[@]}" -d "$wheels" "$wheels"/roundtable_hold-*.whl
  for target in base roundtable; do
    name=$([ "$target" = base ] && echo base || echo app)
    tarfile="$out/roundtable-$name-$abi.tar"
    echo "== $abi: $target layer"
    docker buildx build --platform "$platform" --target "$target" -f "$here/Dockerfile" \
      --build-arg "BASE_IMAGE=${BASE_IMAGE:-debian:bookworm-slim}" --build-arg "ABI=$abi" \
      --output "type=tar,dest=$tarfile" "$out"
    python3 "$here/flatten_tar.py" "$tarfile"   # the phone refuses hard links and pax headers
    rm -f "$tarfile.xz"
    xz -T0 -6 "$tarfile"
  done
  tar -xJOf "$out/roundtable-base-$abi.tar.xz" etc/roundtable-base.json > "$out/base-versions-$abi.json"
  echo "== $abi: $(cat "$out/base-versions-$abi.json")"
done
ls -l "$out"/*.tar.xz
