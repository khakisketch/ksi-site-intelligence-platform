#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 1 || "$1" != /* || "$1" == "/" ]]; then
  echo "usage: $0 /absolute/backup-output-directory" >&2
  exit 2
fi
command -v docker >/dev/null

backup_root="$1"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
bundle_dir="${backup_root%/}/ksi-vm-${timestamp}"
mkdir -p "$bundle_dir"

data_volume="${KSI_BACKUP_DATA_VOLUME:-ksi_ksi-data}"
objects_volume="${KSI_BACKUP_OBJECTS_VOLUME:-ksi_ksi-objects}"
for volume in "$data_volume" "$objects_volume"; do
  [[ "$volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
    echo "invalid Docker volume name: $volume" >&2
    exit 2
  }
  docker volume inspect "$volume" >/dev/null
done

docker run --rm \
  -v "$data_volume":/source:ro \
  -v "$bundle_dir":/backup \
  alpine:3.22 tar -C /source -czf /backup/core-data.tgz .

docker run --rm \
  -v "$objects_volume":/source:ro \
  -v "$bundle_dir":/backup \
  alpine:3.22 tar -C /source -czf /backup/objects.tgz .

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deploy_dir="$(cd -- "$script_dir/.." && pwd)"
signing_keys_dir="${KSI_BACKUP_SIGNING_KEYS_DIR:-$deploy_dir/signing-keys}"
if [[ "$signing_keys_dir" != /* || "$signing_keys_dir" == "/" || ! -d "$signing_keys_dir" ]]; then
  echo "missing or unsafe signing key directory: $signing_keys_dir" >&2
  exit 1
fi
docker run --rm \
  -v "$signing_keys_dir":/source:ro \
  -v "$bundle_dir":/backup \
  alpine:3.22 tar -C /source -czf /backup/signing-keys.tgz .

(
  cd "$bundle_dir"
  sha256sum core-data.tgz objects.tgz signing-keys.tgz > SHA256SUMS
)
echo "$bundle_dir"
