#!/usr/bin/env bash
# Applies only the reviewed account/rootless-Docker preparation after preflight.
# It preserves the existing ksi-phase2-staging deployment and its volumes.
set -euo pipefail
umask 077

library_only="${KSI_EXTERNAL_RUNTIME_BOOTSTRAP_LIBRARY_ONLY:-0}"
is_sourced=0
[[ "${BASH_SOURCE[0]}" != "$0" ]] && is_sourced=1
if [[ "$library_only" == 1 && "$is_sourced" == 1 ]]; then
  runtime_base="${KSI_EXTERNAL_RUNTIME_BASE:?set test runtime base}"
  ledger_dir="${KSI_EXTERNAL_RUNTIME_PREFLIGHT_DIR:?set test preflight directory}"
  subuid_file="${KSI_EXTERNAL_RUNTIME_SUBUID_FILE:?set test subuid file}"
  subgid_file="${KSI_EXTERNAL_RUNTIME_SUBGID_FILE:?set test subgid file}"
  trusted_owner_uid="${KSI_EXTERNAL_RUNTIME_TRUSTED_OWNER_UID:?set test trusted owner uid}"
else
  runtime_base=/var/lib/ksi-external-runtime
  ledger_dir=/var/lib/ksi-external-runtime-preflight
  subuid_file=/etc/subuid
  subgid_file=/etc/subgid
  trusted_owner_uid=0
fi
bootstrap_marker="$runtime_base/.external-runtime-bootstrap.v1.json"
accounts_marker="$runtime_base/.external-runtime-bootstrap.accounts.v1.json"
maps_marker="$runtime_base/.external-runtime-bootstrap.maps.v1.json"
rootless_marker="$runtime_base/.external-runtime-bootstrap.rootless.v1.json"
readonly required_templates=(
  dbus.socket.private.conf
  docker.service.private.conf
  ksi-external-runtime-directories.service
  ksi-external-runtime-socket-acl.service
  ksi-external-validation-worker.service
  bin/ksi-external-runtime-socket-acl
  user/ksi-external-inspector.socket
  user/ksi-external-inspector.service
  user/ksi-external-measurement.socket
  user/ksi-external-measurement.service
  user/ksi-inspector.slice
  user/ksi-measurement.slice
)

usage() {
  echo "usage: $0 --preflight-ledger /var/lib/ksi-external-runtime-preflight/name.json --template-root /absolute/systemd-templates --template-manifest /absolute/systemd-manifest.sha256 --template-manifest-sha256 sha256:..." >&2
  exit 2
}

ledger=
template_root=
template_manifest=
template_manifest_sha256=

mode_without_group_or_other_write() {
  local mode="$1"
  (( (8#$mode & 8#022) == 0 ))
}

root_owned_private_directory() {
  local path="$1" mode
  [[ -d "$path" && ! -L "$path" && "$(stat --format=%u -- "$path")" == "$trusted_owner_uid" ]] || return 1
  mode="$(stat --format=%a -- "$path")"
  mode_without_group_or_other_write "$mode"
}

root_owned_private_file() {
  local path="$1" mode
  [[ -f "$path" && ! -L "$path" && "$(stat --format=%u -- "$path")" == "$trusted_owner_uid" ]] || return 1
  mode="$(stat --format=%a -- "$path")"
  mode_without_group_or_other_write "$mode"
}

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

inspector_uid_or_absent() {
  if getent passwd ksi-inspector >/dev/null; then id -u ksi-inspector; else printf 'ABSENT'; fi
}

inspector_bus_or_absent() {
  local inspector_uid="$1"
  [[ "$inspector_uid" != ABSENT ]] || { printf 'ABSENT'; return; }
  stat_or_absent "/run/user/${inspector_uid}/bus"
}

runtime_root_or_absent() {
  local inspector_uid="$1"
  [[ "$inspector_uid" != ABSENT ]] || { printf 'ABSENT'; return; }
  stat_or_absent "/run/user/${inspector_uid}"
}

ledger_value() { jq -er "$1" "$ledger"; }

require_fresh_complete_ledger() {
  local observed epoch now current_inspector_uid
  jq -e '
    .schema == "external-runtime-preflight.v1"
    and .status == "PREPARED, NOT APPLIED"
    and (.observedAt | type == "string")
    and (.accounts.validator | type == "string")
    and (.accounts.inspector | type == "string")
    and (.subordinateMaps.validatorSubuid | type == "string")
    and (.subordinateMaps.validatorSubgid | type == "string")
    and (.subordinateMaps.inspectorSubuid | type == "string")
    and (.subordinateMaps.inspectorSubgid | type == "string")
    and (.subordinateMaps.subuidSha256 | type == "string")
    and (.subordinateMaps.subgidSha256 | type == "string")
    and (.preserved.rootfulDockerSocket | type == "string")
    and (.preserved.inspectorUid | type == "string")
    and (.preserved.inspectorBus | type == "string")
    and (.preserved.inspectorRuntimeRoot | type == "string")
    and (.preserved.runtimeRoot | type == "string")
  ' "$ledger" >/dev/null || { echo "a complete external-runtime-preflight.v1 ledger is required" >&2; return 1; }
  observed="$(ledger_value '.observedAt')"
  epoch="$(date --date="$observed" +%s 2>/dev/null)" || { echo "preflight timestamp is invalid" >&2; return 1; }
  now="$(date +%s)"
  (( epoch <= now + 60 && now - epoch <= 900 )) || { echo "preflight ledger is older than fifteen minutes or clock-skewed; collect a new ledger" >&2; return 1; }
  [[ "$(ledger_value '.accounts.validator')" == "$(account_or_absent ksi-validator)" ]] || { echo "validator account drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.accounts.inspector')" == "$(account_or_absent ksi-inspector)" ]] || { echo "inspector account drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.validatorSubuid')" == "$(subordinate_or_absent "$subuid_file" ksi-validator)" ]] || { echo "validator subuid drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.validatorSubgid')" == "$(subordinate_or_absent "$subgid_file" ksi-validator)" ]] || { echo "validator subgid drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.inspectorSubuid')" == "$(subordinate_or_absent "$subuid_file" ksi-inspector)" ]] || { echo "inspector subuid drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.inspectorSubgid')" == "$(subordinate_or_absent "$subgid_file" ksi-inspector)" ]] || { echo "inspector subgid drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.subuidSha256')" == "$(sha256_or_state "$subuid_file")" ]] || { echo "subuid map drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.subordinateMaps.subgidSha256')" == "$(sha256_or_state "$subgid_file")" ]] || { echo "subgid map drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.preserved.rootfulDockerSocket')" == "$(stat_or_absent /var/run/docker.sock)" ]] || { echo "rootful Docker socket drifted after preflight; stop" >&2; return 1; }
  current_inspector_uid="$(inspector_uid_or_absent)"
  [[ "$(ledger_value '.preserved.inspectorUid')" == "$current_inspector_uid" ]] || { echo "inspector UID drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.preserved.inspectorBus')" == "$(inspector_bus_or_absent "$current_inspector_uid")" ]] || { echo "inspector D-Bus drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.preserved.inspectorRuntimeRoot')" == "$(runtime_root_or_absent "$current_inspector_uid")" ]] || { echo "inspector runtime root drifted after preflight; stop" >&2; return 1; }
  [[ "$(ledger_value '.preserved.runtimeRoot')" == "$(stat_or_absent "$runtime_base")" ]] || { echo "runtime root drifted after preflight; stop" >&2; return 1; }
}

validate_existing_marker() {
  local marker="$1" schema="$2" payload="$3"
  root_owned_private_file "$marker" || return 1
  [[ "$(stat --format=%a -- "$marker")" == 600 ]] || return 1
  jq -e --arg schema "$schema" --argjson expected "$payload" '.schema == $schema and . == $expected' "$marker" >/dev/null
}

write_marker() {
  local marker="$1" schema="$2" payload="$3" temporary
  jq -e --arg schema "$schema" '.schema == $schema' <<<"$payload" >/dev/null || return 1
  if [[ -e "$marker" || -L "$marker" ]]; then
    validate_existing_marker "$marker" "$schema" "$payload" || { echo "existing marker differs from exact staged payload; stop" >&2; return 1; }
    return 0
  fi
  temporary="$(mktemp "$runtime_base/.external-runtime-bootstrap.marker.XXXXXX")" || return 1
  if ! printf '%s\n' "$payload" >"$temporary" || ! chmod 0600 -- "$temporary"; then
    rm -f -- "$temporary"
    return 1
  fi
  if ln -- "$temporary" "$marker"; then
    rm -f -- "$temporary"
    return 0
  fi
  rm -f -- "$temporary"
  validate_existing_marker "$marker" "$schema" "$payload" || { echo "marker creation raced with different state; stop" >&2; return 1; }
}

known_runtime_entry() {
  case "$1" in
    worker|launcher|.external-runtime-bootstrap.v1.json|.external-runtime-bootstrap.accounts.v1.json|.external-runtime-bootstrap.maps.v1.json|.external-runtime-bootstrap.rootless.v1.json) return 0 ;;
    *) return 1 ;;
  esac
}

is_marker_temporary() {
  [[ "$1" == .external-runtime-bootstrap.marker.* ]]
}

require_safe_runtime_base() {
  local entry entry_name
  [[ ! -e "$runtime_base" || -d "$runtime_base" ]] || { echo "runtime base is not a directory; stop" >&2; return 1; }
  [[ ! -e "$runtime_base" ]] && return 0
  while IFS= read -r -d '' entry; do
    entry_name="$(basename -- "$entry")"
    if is_marker_temporary "$entry_name"; then
      if ! root_owned_private_file "$entry" || [[ "$(stat --format=%a -- "$entry")" != 600 ]]; then
        echo "marker temporary is not a private root-owned regular file; stop" >&2; return 1;
      fi
      rm -f -- "$entry"
      continue
    fi
    known_runtime_entry "$entry_name" || { echo "runtime base contains unknown state; stop without deleting it" >&2; return 1; }
  done < <(find "$runtime_base" -mindepth 1 -maxdepth 1 -print0)
}

validate_template_manifest() {
  local actual_manifest_sha256 hash relative extra file actual_hash
  declare -A declared_hashes=()
  root_owned_private_directory "$template_root" || { echo "template root must be root-owned and not group/other writable" >&2; return 1; }
  root_owned_private_directory "$template_root/user" || { echo "template user directory must be root-owned and not group/other writable" >&2; return 1; }
  root_owned_private_directory "$template_root/bin" || { echo "template bin directory must be root-owned and not group/other writable" >&2; return 1; }
  root_owned_private_file "$template_manifest" || { echo "template manifest must be root-owned private regular file" >&2; return 1; }
  actual_manifest_sha256="sha256:$(sha256sum -- "$template_manifest" | awk '{print $1}')"
  [[ "$actual_manifest_sha256" == "$template_manifest_sha256" ]] || { echo "template manifest SHA256 differs from approved value" >&2; return 1; }
  while IFS=' ' read -r hash relative extra; do
    [[ "$hash" =~ ^[0-9a-f]{64}$ && -n "$relative" && -z "$extra" && "$relative" != /* && "$relative" != *".."* ]] || { echo "template manifest line is invalid" >&2; return 1; }
    [[ -z "${declared_hashes[$relative]:-}" ]] || { echo "template manifest repeats $relative" >&2; return 1; }
    declared_hashes["$relative"]="$hash"
  done <"$template_manifest"
  for relative in "${required_templates[@]}"; do
    hash="${declared_hashes[$relative]:-}"
    [[ "$hash" =~ ^[0-9a-f]{64}$ ]] || { echo "template manifest omits $relative" >&2; return 1; }
    file="$template_root/$relative"
    root_owned_private_file "$file" || { echo "template is not a root-owned private regular file: $relative" >&2; return 1; }
    actual_hash="$(sha256sum -- "$file" | awk '{print $1}')"
    [[ "$actual_hash" == "$hash" ]] || { echo "template hash differs: $relative" >&2; return 1; }
  done
  [[ "${#declared_hashes[@]}" -eq "${#required_templates[@]}" ]] || { echo "template manifest has unreviewed entries" >&2; return 1; }
}

verify_service_account() {
  local name="$1" home="$2" passwd_record groups recorded_home shell
  passwd_record="$(getent passwd "$name")" || return 1
  IFS=: read -r _ _ _ _ _ recorded_home shell _ <<<"$passwd_record"
  [[ "$recorded_home" == "$home" && "$shell" == /usr/sbin/nologin && "$(id -u "$name")" != 0 ]] || return 1
  groups=" $(id -nG "$name") "
  [[ "$groups" != *' docker '* && "$groups" != *' sudo '* ]]
}

ensure_service_account() {
  local name="$1" home="$2"
  if getent passwd "$name" >/dev/null; then
    verify_service_account "$name" "$home" || { echo "existing $name does not match the reviewed account shape; stop" >&2; return 1; }
  else
    /usr/sbin/useradd --system --create-home --home-dir "$home" --shell /usr/sbin/nologin "$name"
    verify_service_account "$name" "$home" || { echo "new $name proof failed; stop" >&2; return 1; }
  fi
  install -d -m 0700 -o "$name" -g "$name" "$home"
}

map_range() { awk -F: '$1 == "ksi-inspector" { print $2 ":" $3 }' "$1"; }
valid_range() { [[ "$1" =~ ^[0-9]+:65536$ ]]; }

validate_map_structure() {
  local file="$1" account start count extra end
  while IFS=: read -r account start count extra || [[ -n "$account$start$count$extra" ]]; do
    [[ -n "$account" && "$account" =~ ^[A-Za-z0-9_.-]+$ && "$start" =~ ^[0-9]+$ && "$count" =~ ^[1-9][0-9]*$ && -z "$extra" ]] || { echo "invalid subordinate allocation in $file; stop" >&2; return 1; }
    end=$((start + count))
    (( end > start )) || { echo "subordinate allocation overflows in $file; stop" >&2; return 1; }
  done <"$file"
}

interval_overlaps_other_allocation() {
  local file="$1" candidate="$2" candidate_start candidate_count candidate_end account start count extra end
  valid_range "$candidate" || return 1
  candidate_start="${candidate%:*}"
  candidate_count="${candidate#*:}"
  candidate_end=$((candidate_start + candidate_count))
  while IFS=: read -r account start count extra || [[ -n "$account$start$count$extra" ]]; do
    [[ "$account" == ksi-inspector ]] && continue
    end=$((start + count))
    if (( candidate_start < end && start < candidate_end )); then
      echo "proposed ksi-inspector range overlaps $account in $file; stop" >&2
      return 0
    fi
  done <"$file"
  return 1
}

ensure_subordinate_maps() {
  local subuid_range subgid_range candidate
  exec 9<>"$subuid_file"
  exec 8<>"$subgid_file"
  flock -x 9
  flock -x 8
  validate_map_structure "$subuid_file"
  validate_map_structure "$subgid_file"
  subuid_range="$(map_range "$subuid_file")"
  subgid_range="$(map_range "$subgid_file")"
  [[ -z "$subuid_range" || "$(wc -l <<<"$subuid_range")" -eq 1 ]] || { echo "multiple subuid ranges; stop" >&2; return 1; }
  [[ -z "$subgid_range" || "$(wc -l <<<"$subgid_range")" -eq 1 ]] || { echo "multiple subgid ranges; stop" >&2; return 1; }
  [[ -z "$subuid_range" ]] || valid_range "$subuid_range" || { echo "existing subuid range is invalid; stop" >&2; return 1; }
  [[ -z "$subgid_range" ]] || valid_range "$subgid_range" || { echo "existing subgid range is invalid; stop" >&2; return 1; }
  if [[ -n "$subuid_range" && -n "$subgid_range" ]]; then
    [[ "$subuid_range" == "$subgid_range" ]] || { echo "subuid/subgid ranges differ; stop" >&2; return 1; }
    candidate="$subuid_range"
  else
    candidate="$subuid_range"
    [[ -n "$candidate" ]] || candidate="$subgid_range"
    if [[ -z "$candidate" ]]; then
    candidate="$(awk -F: 'BEGIN { max = 165536 } $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ { end = $2 + $3; if (end > max) max = end } END { print int((max + 65535) / 65536) * 65536 ":65536" }' "$subuid_file" "$subgid_file")"
    fi
  fi
  valid_range "$candidate" || { echo "could not allocate subordinate range; stop" >&2; return 1; }
  interval_overlaps_other_allocation "$subuid_file" "$candidate" && return 1
  interval_overlaps_other_allocation "$subgid_file" "$candidate" && return 1
  [[ -n "$subuid_range" ]] || printf 'ksi-inspector:%s\n' "$candidate" >>"$subuid_file"
  [[ -n "$subgid_range" ]] || printf 'ksi-inspector:%s\n' "$candidate" >>"$subgid_file"
}

private_socket_identity() {
  local socket_path="$1" expected_uid="$2" identity device inode owner_uid owner_gid mode links file_type
  [[ -S "$socket_path" && ! -L "$socket_path" ]] || return 1
  identity="$(LC_ALL=C stat --format='%d:%i:%u:%g:%a:%h:%F' -- "$socket_path")" || return 1
  IFS=: read -r device inode owner_uid owner_gid mode links file_type <<<"$identity"
  [[ -n "$device" && -n "$inode" && "$owner_uid" == "$expected_uid" && "$owner_gid" =~ ^[0-9]+$ && "$mode" == 600 && "$links" == 1 && "$file_type" == socket ]] || return 1
  printf '%s' "$identity"
}

run_as_inspector() {
  local inspector_uid="$1" runtime_dir
  shift
  runtime_dir="/run/user/${inspector_uid}"
  /usr/sbin/runuser -u ksi-inspector -- env XDG_RUNTIME_DIR="$runtime_dir" DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime_dir}/bus" "$@"
}

main() {
[[ $# -eq 8 ]] || usage
[[ "$1" == --preflight-ledger && "$3" == --template-root && "$5" == --template-manifest && "$7" == --template-manifest-sha256 ]] || usage
ledger="$2"
template_root="$4"
template_manifest="$6"
template_manifest_sha256="$8"
[[ "$ledger" == "$ledger_dir"/* && "$(dirname -- "$ledger")" == "$ledger_dir" && "$ledger" != *".."* ]] || {
  echo "preflight ledger must be in $ledger_dir" >&2; exit 2;
}
[[ "$template_root" == /* && "$template_root" != *".."* && "$template_manifest" == /* && "$template_manifest" != *".."* ]] || {
  echo "template paths must be absolute" >&2; exit 2;
}
[[ "$template_manifest_sha256" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "template manifest hash must be SHA256" >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo "bootstrap requires a root operator" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required for the ledger" >&2; exit 1; }
command -v flock >/dev/null || { echo "flock is required for subordinate-map serialization" >&2; exit 1; }

if ! root_owned_private_directory "$ledger_dir" || [[ "$(stat --format=%a -- "$ledger_dir")" != 700 ]]; then
  echo "preflight ledger directory must be root-owned mode 0700" >&2
  exit 1
fi
if ! root_owned_private_file "$ledger" || [[ "$(stat --format=%a -- "$ledger")" != 600 ]]; then
  echo "preflight ledger must be root-owned mode 0600" >&2
  exit 1
fi
validate_template_manifest
require_fresh_complete_ledger
require_safe_runtime_base
install -d -m 0711 -o root -g root "$runtime_base"
exec 7>/run/lock/ksi-external-runtime-bootstrap.lock
flock -n 7 || { echo "another external-runtime bootstrap holds the lock; stop" >&2; exit 1; }

ensure_service_account ksi-validator "$runtime_base/worker"
ensure_service_account ksi-inspector "$runtime_base/launcher"
write_marker "$accounts_marker" external-runtime-bootstrap.accounts.v1 "$(jq -n --arg validator "$(getent passwd ksi-validator)" --arg inspector "$(getent passwd ksi-inspector)" '{schema: "external-runtime-bootstrap.accounts.v1", validator: $validator, inspector: $inspector}')"
ensure_subordinate_maps
write_marker "$maps_marker" external-runtime-bootstrap.maps.v1 "$(jq -n --arg subuid "$(map_range "$subuid_file")" --arg subgid "$(map_range "$subgid_file")" '{schema: "external-runtime-bootstrap.maps.v1", subuid: $subuid, subgid: $subgid}')"

inspector_uid="$(id -u ksi-inspector)"
launcher_home="$runtime_base/launcher"
user_unit_dir="$launcher_home/.config/systemd/user"
install -d -m 0700 -o ksi-inspector -g ksi-inspector "$user_unit_dir" "$user_unit_dir/dbus.socket.d" "$user_unit_dir/docker.service.d"
install -m 0600 -o ksi-inspector -g ksi-inspector "$template_root/dbus.socket.private.conf" "$user_unit_dir/dbus.socket.d/private.conf"
install -m 0600 -o ksi-inspector -g ksi-inspector "$template_root/docker.service.private.conf" "$user_unit_dir/docker.service.d/private.conf"
for unit in ksi-external-inspector.socket ksi-external-inspector.service ksi-external-measurement.socket ksi-external-measurement.service ksi-inspector.slice ksi-measurement.slice; do
  install -m 0644 -o ksi-inspector -g ksi-inspector "$template_root/user/$unit" "$user_unit_dir/$unit"
done
install -d -m 0755 /etc/systemd/system
install -m 0644 "$template_root/ksi-external-runtime-directories.service" /etc/systemd/system/ksi-external-runtime-directories.service
install -m 0644 "$template_root/ksi-external-runtime-socket-acl.service" /etc/systemd/system/ksi-external-runtime-socket-acl.service
install -m 0644 "$template_root/ksi-external-validation-worker.service" /etc/systemd/system/ksi-external-validation-worker.service
install -d -m 0755 -o root -g root /usr/local/lib/ksi-external-runtime/bin
install -m 0755 -o root -g root "$template_root/bin/ksi-external-runtime-socket-acl" /usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl
/usr/bin/systemctl daemon-reload

/usr/bin/loginctl enable-linger ksi-inspector
/usr/bin/systemctl start "user@${inspector_uid}.service"
inspector_runtime_dir="/run/user/${inspector_uid}"
bus_path="$inspector_runtime_dir/bus"
bus_identity_before="$(private_socket_identity "$bus_path" "$inspector_uid")" || { echo "inspector D-Bus must be an owned single-link non-symlink mode-0600 socket; stop" >&2; exit 1; }
run_as_inspector "$inspector_uid" /usr/bin/systemctl --user daemon-reload
run_as_inspector "$inspector_uid" /usr/bin/dockerd-rootless-setuptool.sh install
run_as_inspector "$inspector_uid" /usr/bin/systemctl --user daemon-reload

rootless_socket="$inspector_runtime_dir/docker.sock"
[[ -S "$rootless_socket" && ! -L "$rootless_socket" && "$(stat --format=%u:%a -- "$rootless_socket")" == "${inspector_uid}:600" ]] || { echo "private rootless Docker socket proof failed; stop" >&2; exit 1; }
bus_identity_after="$(private_socket_identity "$bus_path" "$inspector_uid")" || { echo "inspector D-Bus became broader or changed; stop" >&2; exit 1; }
[[ "$bus_identity_after" == "$bus_identity_before" ]] || { echo "inspector D-Bus identity changed during rootless setup; stop" >&2; exit 1; }
[[ "$(stat_or_absent /var/run/docker.sock)" == "$(ledger_value '.preserved.rootfulDockerSocket')" ]] || { echo "rootful Docker socket changed during bootstrap; stop" >&2; exit 1; }

write_marker "$rootless_marker" external-runtime-bootstrap.rootless.v1 "$(jq -n --arg runtimeDir "$inspector_runtime_dir" --arg bus "$(stat_or_absent "$inspector_runtime_dir/bus")" --arg socket "$(stat_or_absent "$rootless_socket")" '{schema: "external-runtime-bootstrap.rootless.v1", runtimeDir: $runtimeDir, bus: $bus, socket: $socket}')"
write_marker "$bootstrap_marker" external-runtime-bootstrap.v1 "$(jq -n --arg validatorUid "$(id -u ksi-validator)" --arg inspectorUid "$inspector_uid" --arg inspectorSubuid "$(map_range "$subuid_file")" --arg inspectorSubgid "$(map_range "$subgid_file")" --arg rootlessSocket "$rootless_socket" '{schema: "external-runtime-bootstrap.v1", validatorUid: $validatorUid, inspectorUid: $inspectorUid, inspectorSubuid: $inspectorSubuid, inspectorSubgid: $inspectorSubgid, rootlessDockerSocket: $rootlessSocket}')"
printf '%s\n' "$bootstrap_marker"
}

if [[ "$is_sourced" == 1 ]]; then
  [[ "$library_only" == 1 ]] || { echo "bootstrap may be sourced only in explicit test-library mode" >&2; return 2; }
elif [[ "$library_only" == 1 ]]; then
  echo "test-library mode is unavailable during direct bootstrap execution" >&2
  exit 2
else
  main "$@"
fi
