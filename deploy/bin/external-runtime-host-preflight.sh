#!/usr/bin/env bash
# Read-only inventory for the dedicated external-validation host boundary.
set -euo pipefail
umask 077

readonly ledger_dir=/var/lib/ksi-external-runtime-preflight

usage() {
  echo "usage: $0 --output /var/lib/ksi-external-runtime-preflight/name.json" >&2
  exit 2
}

[[ $# -eq 2 && "$1" == "--output" ]] || usage
output="$2"
[[ "${EUID}" -eq 0 ]] || { echo "preflight requires a root operator" >&2; exit 1; }
[[ "$output" == "$ledger_dir"/* && "$(dirname -- "$output")" == "$ledger_dir" && "$output" != *".."* ]] || { echo "output must be in $ledger_dir" >&2; exit 2; }
[[ ! -e "$output" ]] || { echo "preflight output already exists; preserve the prior ledger" >&2; exit 1; }
output_dir="$(dirname -- "$output")"
[[ -d "$output_dir" && ! -L "$output_dir" && "$(stat --format=%u:%a -- "$output_dir")" == 0:700 ]] || { echo "preflight ledger directory must be root-owned mode 0700" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required for the ledger" >&2; exit 1; }

stat_or_absent() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    stat --printf='%u:%g:%a:%F' -- "$path"
  else
    printf 'ABSENT'
  fi
}

sha256_or_state() {
  local path="$1"
  if [[ -r "$path" && -f "$path" && ! -L "$path" ]]; then
    printf 'sha256:%s' "$(sha256sum -- "$path" | awk '{print $1}')"
  else
    stat_or_absent "$path"
  fi
}

account_or_absent() {
  local name="$1"
  getent passwd "$name" || printf 'ABSENT'
}

subordinate_or_absent() {
  local path="$1" name="$2"
  if [[ -r "$path" ]]; then
    awk -F: -v name="$name" '$1 == name { print $0 }' "$path"
  else
    printf 'UNREADABLE'
  fi
}

inspector_uid=ABSENT
inspector_bus=ABSENT
inspector_runtime_root=ABSENT
if getent passwd ksi-inspector >/dev/null; then
  inspector_uid="$(id -u ksi-inspector)"
  inspector_bus="$(stat_or_absent "/run/user/${inspector_uid}/bus")"
  inspector_runtime_root="$(stat_or_absent "/run/user/${inspector_uid}")"
fi

tmp="$(mktemp "$output_dir/.external-runtime-preflight.XXXXXX")"
trap 'rm -f -- "$tmp"' EXIT

jq -n \
  --arg schema 'external-runtime-preflight.v1' \
  --arg status 'PREPARED, NOT APPLIED' \
  --arg observedAt "$(date --utc +%Y-%m-%dT%H:%M:%SZ)" \
  --arg validator "$(account_or_absent ksi-validator)" \
  --arg inspector "$(account_or_absent ksi-inspector)" \
  --arg validatorSubuid "$(subordinate_or_absent /etc/subuid ksi-validator)" \
  --arg validatorSubgid "$(subordinate_or_absent /etc/subgid ksi-validator)" \
  --arg inspectorSubuid "$(subordinate_or_absent /etc/subuid ksi-inspector)" \
  --arg inspectorSubgid "$(subordinate_or_absent /etc/subgid ksi-inspector)" \
  --arg subuidSha256 "$(sha256_or_state /etc/subuid)" \
  --arg subgidSha256 "$(sha256_or_state /etc/subgid)" \
  --arg rootfulDockerSocket "$(stat_or_absent /var/run/docker.sock)" \
  --arg inspectorUid "$inspector_uid" \
  --arg inspectorBus "$inspector_bus" \
  --arg inspectorRuntimeRoot "$inspector_runtime_root" \
  --arg runtimeRoot "$(stat_or_absent /var/lib/ksi-external-runtime)" \
  --arg existingStaging "$(stat_or_absent /var/lib/docker/volumes)" \
  --arg dockerGroup "$(getent group docker || true)" \
  --arg sudoGroup "$(getent group sudo || true)" \
  '{schema: $schema, status: $status, observedAt: $observedAt,
    accounts: {validator: $validator, inspector: $inspector},
    subordinateMaps: {validatorSubuid: $validatorSubuid, validatorSubgid: $validatorSubgid,
      inspectorSubuid: $inspectorSubuid, inspectorSubgid: $inspectorSubgid,
      subuidSha256: $subuidSha256, subgidSha256: $subgidSha256},
    preserved: {rootfulDockerSocket: $rootfulDockerSocket, inspectorUid: $inspectorUid,
      inspectorBus: $inspectorBus, inspectorRuntimeRoot: $inspectorRuntimeRoot,
      runtimeRoot: $runtimeRoot, dockerVolumesRoot: $existingStaging,
      dockerGroup: $dockerGroup, sudoGroup: $sudoGroup}}' >"$tmp"

chmod 0600 -- "$tmp"
mv -n -- "$tmp" "$output"
trap - EXIT
printf '%s\n' "$output"
