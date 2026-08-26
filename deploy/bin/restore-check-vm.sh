#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || "$1" != /* || "$1" == "/" ]]; then
  echo "usage: $0 /absolute/ksi-vm-backup-bundle" >&2
  exit 2
fi
command -v docker >/dev/null

bundle_dir="${1%/}"
for item in SHA256SUMS core-data.tgz objects.tgz signing-keys.tgz; do
  [[ -f "$bundle_dir/$item" ]] || { echo "missing $item" >&2; exit 1; }
done
(
  cd "$bundle_dir"
  sha256sum -c SHA256SUMS
)

suffix="${RANDOM}-$$"
data_volume="ksi-restorecheck-data-$suffix"
objects_volume="ksi-restorecheck-objects-$suffix"
keys_dir="$(mktemp -d)"
cleanup() {
  docker volume rm -f "$data_volume" "$objects_volume" >/dev/null 2>&1 || true
  rm -rf -- "$keys_dir"
}
trap cleanup EXIT

docker volume create "$data_volume" >/dev/null
docker volume create "$objects_volume" >/dev/null
docker run --rm -v "$data_volume":/restore -v "$bundle_dir":/backup:ro \
  alpine:3.22 tar -C /restore -xzf /backup/core-data.tgz
docker run --rm -v "$objects_volume":/restore -v "$bundle_dir":/backup:ro \
  alpine:3.22 tar -C /restore -xzf /backup/objects.tgz
docker run --rm -v "$keys_dir":/restore -v "$bundle_dir":/backup:ro \
  alpine:3.22 sh -c \
  "tar -C /restore -xzf /backup/signing-keys.tgz && chown -R $(id -u):$(id -g) /restore"

docker run --rm -v "$data_volume":/restore:ro alpine:3.22 \
  sh -c 'test -n "$(find /restore -type f -print -quit)"'
docker run --rm -v "$objects_volume":/restore:ro alpine:3.22 \
  sh -c 'test -n "$(find /restore -type f -print -quit)"'
test -f "$keys_dir/keys.json"

echo "restore check passed: isolated volumes contained journals, objects, and keys.json"
