#!/usr/bin/env bash
set -euo pipefail
umask 077

command -v docker >/dev/null
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
suffix="${RANDOM}-$$"
data_volume="ksi-smoke-data-$suffix"
objects_volume="ksi-smoke-objects-$suffix"
smoke_root="$(mktemp -d /tmp/ksi-backup-restore-smoke-XXXXXX)"
signing_dir="$smoke_root/signing-keys"
mkdir -p "$signing_dir"

cleanup() {
  docker volume rm -f "$data_volume" "$objects_volume" >/dev/null 2>&1 || true
  rm -rf -- "$smoke_root"
}
trap cleanup EXIT

docker volume create "$data_volume" >/dev/null
docker volume create "$objects_volume" >/dev/null
docker run --rm -v "$data_volume":/target alpine:3.22 \
  sh -c 'mkdir -p /target/journals && printf "%s\n" synthetic-journal > /target/journals/sample.jsonl'
docker run --rm -v "$objects_volume":/target alpine:3.22 \
  sh -c 'mkdir -p /target/objects && printf "%s\n" synthetic-object > /target/objects/sample.bin'
printf '%s\n' '{"active":"smoke-key","keys":[{"keyId":"smoke-key","status":"ACTIVE"}]}' \
  > "$signing_dir/keys.json"

bundle_dir="$(
  KSI_BACKUP_DATA_VOLUME="$data_volume" \
  KSI_BACKUP_OBJECTS_VOLUME="$objects_volume" \
  KSI_BACKUP_SIGNING_KEYS_DIR="$signing_dir" \
    "$script_dir/backup-vm.sh" "$smoke_root/backups"
)"
"$script_dir/restore-check-vm.sh" "$bundle_dir"
echo "synthetic backup/restore smoke passed"
