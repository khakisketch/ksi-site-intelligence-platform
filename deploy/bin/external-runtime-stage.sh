#!/usr/bin/env bash
# Candidate lifecycle wrapper. It never touches ksi-phase2-staging or its volumes.
set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
compose_file="$repo_dir/deploy/compose.external-reconstruction.yaml"

readonly runtime_image_pin_checker="$repo_dir/tools/check_runtime_image_pins.py"
readonly candidate_compose_path="deploy/compose.external-reconstruction.yaml"

usage() {
  echo "usage: $0 status|stop | prepare|verify|start --env-file /absolute/candidate.env" >&2
  exit 2
}

readonly required_keys=(
  KSI_EXTERNAL_RC_PROJECT_NAME
  KSI_EXTERNAL_RC_STATE_DIR
  KSI_EXTERNAL_RC_RELEASE_EVIDENCE
  KSI_EXTERNAL_RC_HOST_BINDING
  KSI_EXTERNAL_RC_OPERATOR_DIR
  KSI_EXTERNAL_RC_HOST
  KSI_EXTERNAL_RC_APP_PORT
  KSI_EXTERNAL_RC_IDENTITY_PORT
  KSI_EXTERNAL_RC_API_PORT
  KSI_EXTERNAL_RC_OBJECTS_PORT
  KSI_EXTERNAL_RC_MINIO_CONSOLE_PORT
  KSI_EXTERNAL_RC_MINIO_ROOT_USER
  KSI_EXTERNAL_RC_MINIO_ROOT_PASSWORD
  KSI_EXTERNAL_RC_PRINCIPAL_TOKENS_JSON
)

read_candidate_env() {
  local line line_number=0 key value required
  declare -A allowed=()
  for required in "${required_keys[@]}"; do
    allowed["$required"]=1
  done

  # Parse data, never execute it. The value is retained verbatim after the
  # first equals sign, so JSON and passwords are not interpreted as shell code.
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || {
      echo "candidate env line $line_number is not KEY=VALUE" >&2; return 1;
    }
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    [[ -n "${allowed[$key]:-}" ]] || {
      echo "candidate env line $line_number has an unapproved key" >&2; return 1;
    }
    [[ "$value" != *$'\r'* && "$value" != *$'\n'* ]] || {
      echo "candidate env line $line_number contains a control newline" >&2; return 1;
    }
    [[ ! -v "$key" ]] || {
      echo "candidate env line $line_number duplicates $key" >&2; return 1;
    }
    declare -gx "$key=$value"
  done <"$env_file"

  for required in "${required_keys[@]}"; do
    [[ -v "$required" && -n "${!required}" ]] || {
      echo "candidate env omits $required" >&2; return 1;
    }
  done
}

immutable_reference() {
  [[ "$1" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*(:[0-9]{1,5})?/)?[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$ ]]
}

pinned_external_runtime_reference() {
  immutable_reference "$1" || [[ "$1" == "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2" ]]
}

canonical_repository_digest() {
  local reference="$1" name_and_tag path_component repository digest
  if [[ "$reference" == "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2" ]]; then
    printf '%s\n' "$reference"
    return 0
  fi
  immutable_reference "$reference" || return 1
  name_and_tag="${reference%@sha256:*}"
  digest="sha256:${reference##*@sha256:}"
  path_component="${name_and_tag##*/}"
  repository="$name_and_tag"
  if [[ "$path_component" == *:* ]]; then
    repository="${name_and_tag%:*}"
  fi
  printf '%s@%s\n' "$repository" "$digest"
}

compose() {
  docker compose --project-name "$KSI_EXTERNAL_RC_PROJECT_NAME" --env-file "$env_file" -f "$compose_file" "$@"
}

runtime_image_reference_sets() {
  local entries
  command -v python3 >/dev/null || {
    echo "python3 is required to derive runtime image references" >&2; return 1;
  }
  entries="$(python3 "$runtime_image_pin_checker" --root "$repo_dir" --references-json)" || return 1
  jq -ce --arg candidate_compose_path "$candidate_compose_path" '
    select(type == "array"
    and all(.[];
      type == "object"
      and (keys | sort == ["line", "path", "reference"])
      and (.line | type == "number" and floor == . and . >= 1)
      and (.path | type == "string" and length > 0)
      and (.reference | type == "string" and length > 0)))
    | {
        canonical: ([.[].reference] | unique | sort),
        candidate: ([.[] | select(.path == $candidate_compose_path) | .reference] | unique | sort)
      }
    | . as $sets
    | select(($sets.candidate | length) == 3)
    | select([
        $sets.candidate[] as $reference
        | select(($sets.canonical | index($reference)) == null)
      ] | length == 0)
  ' <<<"$entries"
}

readonly socket_acl_helper="/usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl"

private_owner_mode() {
  local path="$1" expected_type="$2" metadata uid gid mode node_type
  [[ -e "$path" && ! -L "$path" ]] || return 1
  metadata="$(stat --format='%u:%g:%a:%F' -- "$path")" || return 1
  IFS=: read -r uid gid mode node_type <<<"$metadata"
  [[ "$node_type" == "$expected_type" ]] || return 1
  [[ "$uid" == 0 || "$uid" == 10001 ]] || return 1
  [[ "$gid" == 0 || "$gid" == 10001 ]] || return 1
  [[ "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 && (8#$mode & 0007) == 0 ))
}

protected_operator_parent() {
  # This root-owned ancestor is shared by isolated host accounts. Public
  # traversal is not access to the private operator child or its secrets.
  local path="$1" metadata uid gid mode node_type
  [[ -d "$path" && ! -L "$path" ]] || return 1
  metadata="$(stat --format='%u:%g:%a:%F' -- "$path")" || return 1
  IFS=: read -r uid gid mode node_type <<<"$metadata"
  [[ "$uid" == 0 && "$gid" == 0 && "$node_type" == directory && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 && (8#$mode & 0100) != 0 ))
}

validate_operator_directory() {
  local requested="${KSI_EXTERNAL_RC_OPERATOR_DIR:-}" canonical parent
  [[ "$requested" == /* && "$requested" != *".."* ]] || {
    echo "BLOCKED_OPERATOR_INPUT: operator directory must be an explicit absolute path" >&2; return 1;
  }
  canonical="$(readlink -f -- "$requested")" || {
    echo "BLOCKED_OPERATOR_INPUT: operator directory cannot be resolved" >&2; return 1;
  }
  [[ "$canonical" == "$requested" ]] || {
    echo "BLOCKED_OPERATOR_INPUT: operator directory must not traverse a symlink" >&2; return 1;
  }
  case "$canonical" in
    /etc/ksi-external-runtime/operator|/var/lib/ksi-external-runtime/operator) ;;
    *) echo "BLOCKED_OPERATOR_INPUT: operator directory is outside the dedicated candidate roots" >&2; return 1 ;;
  esac
  parent="${canonical%/operator}"
  protected_operator_parent "$parent" && private_owner_mode "$canonical" directory || {
    echo "BLOCKED_OPERATOR_INPUT: operator parent ownership or mode is unsafe" >&2; return 1;
  }
  local required path
  for required in workflow.json provider.json; do
    path="$canonical/$required"
    private_owner_mode "$path" "regular file" || {
      echo "BLOCKED_OPERATOR_INPUT: operator $required is missing or unsafe" >&2; return 1;
    }
  done
  for required in secrets signing; do
    path="$canonical/$required"
    private_owner_mode "$path" directory || {
      echo "BLOCKED_OPERATOR_INPUT: operator $required directory is missing or unsafe" >&2; return 1;
    }
  done
  operator_dir="$canonical"
}

verify_socket_acl_proof() {
  local metadata uid gid mode node_type proof
  [[ -f "$socket_acl_helper" && ! -L "$socket_acl_helper" ]] || {
    echo "BLOCKED_SOCKET_ACL: installed socket ACL helper is unavailable" >&2; return 1;
  }
  metadata="$(stat --format='%u:%g:%a:%F' -- "$socket_acl_helper")" || return 1
  IFS=: read -r uid gid mode node_type <<<"$metadata"
  [[ "$uid" == 0 && "$node_type" == "regular file" && "$mode" =~ ^[0-7]{3,4}$ ]] &&
    (( (8#$mode & 0022) == 0 && (8#$mode & 0100) != 0 )) || {
      echo "BLOCKED_SOCKET_ACL: installed socket ACL helper ownership or mode is unsafe" >&2; return 1;
    }
  proof="$(sudo -n -- "$socket_acl_helper" verify --json --untrusted-user nobody)" || {
    echo "BLOCKED_SOCKET_ACL: fresh socket ACL proof is unavailable" >&2; return 1;
  }
  jq -e '
    type == "object"
    and (keys | sort == ["clientConnect", "observedAtUtc", "schema", "serverPeerReceipts", "status", "validator"])
    and .schema == "external-runtime-socket-acl-proof.v2"
    and .status == "OBSERVED_SERVER_PEER_CREDENTIAL"
    and (.observedAtUtc | type == "string" and length > 0)
    and .validator == "ksi-validator"
    and (.clientConnect | type == "object" and (keys | sort == ["deniedOtherAccount", "validator"])
      and .deniedOtherAccount == "nobody"
      and .validator == ["/run/ksi-external-runtime/launcher/inspection.sock", "/run/ksi-external-runtime/launcher/measurement.sock"])
    and (.serverPeerReceipts | type == "array" and length == 2
      and ([.[].lane] | sort) == ["INSPECTION", "MEASUREMENT"]
      and all(.[];
        type == "object" and (keys | sort == ["lane", "server", "serverObservedWorker", "socket"])
        and (.socket | type == "string" and length > 0)
        and (.server | type == "object" and (keys | sort == ["gid", "pid", "uid"])
          and (.pid | type == "number" and . > 0)
          and (.uid | type == "number" and . >= 0)
          and (.gid | type == "number" and . >= 0))
        and (.serverObservedWorker | type == "object" and (keys | sort == ["gid", "pid", "uid"])
          and (.pid | type == "number" and . > 0)
          and (.uid | type == "number" and . >= 0)
          and (.gid | type == "number" and . >= 0))
      ))
  ' >/dev/null <<<"$proof" || {
    echo "BLOCKED_SOCKET_ACL: fresh proof lacks exact server peer credentials" >&2; return 1;
  }
}

validate_supplied_credentials_in_exact_core_image() {
  compose --profile candidate-preflight run --rm --no-deps --no-build --pull never \
    candidate-credential-validation >/dev/null || {
      echo "BLOCKED_EXTERNAL_CREDENTIALS: exact Core image rejected supplied credential material" >&2; return 1;
    }
}

preflight_authority_in_exact_core_image() {
  local proof
  proof="$(compose --profile candidate-preflight run --rm --no-deps --no-build --pull never \
    candidate-authority-preflight)" || {
      echo "BLOCKED_EXTERNAL_AUTHORITY_CONFIG: exact Core image preflight failed" >&2; return 1;
    }
  jq -e '
    type == "object"
    and (keys | sort == ["activationStatus", "organizationId", "quantitativeEligible", "status"])
    and .status == "CONFIG_VALIDATED"
    and .activationStatus == "NOT_ATTACHED"
    and (.organizationId | type == "string" and length > 0)
    and .quantitativeEligible == false
  ' >/dev/null <<<"$proof" || {
    echo "BLOCKED_EXTERNAL_AUTHORITY_CONFIG: Core preflight claimed an invalid status" >&2; return 1;
  }
}

activation_preflight() {
  require_release_evidence || return 1
  validate_operator_directory || return 1
  validate_supplied_credentials_in_exact_core_image || return 1
  verify_socket_acl_proof || return 1
  preflight_authority_in_exact_core_image || return 1
}

verify_live_provider() {
  local response
  response="$(compose exec -T core /app/.venv/bin/python -c '
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/ready/external-authority", timeout=3) as reply:
    print(reply.read().decode("utf-8"))
')" || {
    echo "BLOCKED_EXTERNAL_AUTHORITY_RUNTIME: running Core is not provider-ready" >&2; return 1;
  }
  jq -e '
    type == "object"
    and (keys | sort == ["status"])
    and .status == "PROVIDER_CONFIGURED"
  ' >/dev/null <<<"$response" || {
    echo "BLOCKED_EXTERNAL_AUTHORITY_RUNTIME: running Core returned an unavailable provider" >&2; return 1;
  }
}

core_is_running() {
  compose ps --status running --services | grep -Fx core >/dev/null
}

verify_started_compose_images() {
  local service image_variable expected_image_id actual_image_id
  local -a container_ids
  while read -r service image_variable; do
    expected_image_id="${!image_variable:-}"
    [[ "$expected_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "BLOCKED_RELEASE_EVIDENCE: $service has no verified image ID" >&2; return 1;
    }
    mapfile -t container_ids < <(compose ps --all --quiet "$service")
    [[ "${#container_ids[@]}" -eq 1 && -n "${container_ids[0]}" ]] || {
      echo "BLOCKED_RUNTIME_IMAGE: $service does not have exactly one created container" >&2; return 1;
    }
    actual_image_id="$(docker container inspect --format '{{.Image}}' "${container_ids[0]}")" || {
      echo "BLOCKED_RUNTIME_IMAGE: $service container image cannot be inspected" >&2; return 1;
    }
    [[ "$actual_image_id" == "$expected_image_id" ]] || {
      echo "BLOCKED_RUNTIME_IMAGE: $service container image differs from the verified image ID" >&2; return 1;
    }
  done <<'EOF'
init-state KSI_EXTERNAL_RC_CORE_IMAGE_ID
identity KSI_EXTERNAL_RC_CORE_IMAGE_ID
core KSI_EXTERNAL_RC_CORE_IMAGE_ID
dashboard KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID
minio KSI_EXTERNAL_RC_MINIO_IMAGE_ID
bucket-init KSI_EXTERNAL_RC_MC_IMAGE_ID
caddy KSI_EXTERNAL_RC_CADDY_IMAGE_ID
EOF
}

sha256_file() {
  local path="$1"
  [[ "$path" == /* && -f "$path" && -s "$path" && ! -L "$path" ]] || return 1
  printf 'sha256:%s\n' "$(sha256sum -- "$path" | awk '{print $1}')"
}

verify_image_binding() {
  local reference="$1" expected_id="$2" actual_id repo_digests canonical_digest
  pinned_external_runtime_reference "$reference" || return 1
  [[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  canonical_digest="$(canonical_repository_digest "$reference")" || return 1
  actual_id="$(docker image inspect --format '{{.Id}}' "$reference")" || return 1
  [[ "$actual_id" == "$expected_id" ]] || return 1
  repo_digests="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$reference")" || return 1
  grep -Fqx -- "$canonical_digest" <<<"$repo_digests"
}

verify_observed_repo_digests() {
  local lookup="$1" expected_digests="$2" canonical_digest="$3" actual_digests digest
  [[ "$expected_digests" =~ ^\[ ]] || return 1
  jq -e --arg canonical "$canonical_digest" '
    type == "array" and length >= 1 and index($canonical) != null
  ' <<<"$expected_digests" >/dev/null || return 1
  actual_digests="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$lookup")" || return 1
  grep -Fqx -- "$canonical_digest" <<<"$actual_digests" || return 1
  while IFS= read -r digest; do
    [[ -n "$digest" ]] || continue
    grep -Fqx -- "$digest" <<<"$actual_digests" || return 1
  done < <(jq -r '.[]' <<<"$expected_digests")
}

product_release_reference() {
  local component="$1" reference="$2" pattern
  immutable_reference "$reference" || return 1
  pattern="(^|/)ksi(-external-rc)?-${component}:"
  [[ "$reference" =~ $pattern ]]
}

verify_product_image_binding() {
  # The local tag is a Compose lookup handle only.  Source/image provenance is
  # carried by the product immutable release reference and host record.
  local component="$1" release_reference="$2" expected_id="$3" expected_digests="$4"
  local actual_id canonical_digest local_lookup
  case "$component" in
    core) local_lookup="ksi-external-rc-core:local" ;;
    dashboard) local_lookup="ksi-external-rc-dashboard:local" ;;
    inspector) local_lookup="ksi-external-rc-inspector:local" ;;
    measurement) local_lookup="ksi-external-rc-measurement:local" ;;
    *) return 1 ;;
  esac
  product_release_reference "$component" "$release_reference" || return 1
  [[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  canonical_digest="$(canonical_repository_digest "$release_reference")" || return 1
  actual_id="$(docker image inspect --format '{{.Id}}' "$local_lookup")" || return 1
  [[ "$actual_id" == "$expected_id" ]] || return 1
  verify_observed_repo_digests "$local_lookup" "$expected_digests" "$canonical_digest"
}

verify_artifact_binding() {
  local path="$1" expected="$2" expected_bytes="$3" expected_type="$4" strict_scanner_identity="${5:-0}"
  local expected_image_id="${6:-}"
  local require_linux_arm64="${7:-0}"
  local actual actual_bytes
  [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$expected_bytes" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ "$require_linux_arm64" == 0 || "$require_linux_arm64" == 1 ]] || return 1
  if [[ "$expected_type" == scanner-json && "$strict_scanner_identity" == 1 ]]; then
    # Read, hash and parse the same protected payload. Never equate an OCI index
    # or platform manifest ID with Grype's config ID: unequal identities block.
    local -a scanner_args=(
      python3 "$repo_dir/tools/verify_external_scanner_evidence.py"
      --path "$path" --sha256 "$expected" --bytes "$expected_bytes"
    )
    [[ -z "$expected_image_id" ]] || scanner_args+=(--image-id "$expected_image_id")
    [[ "$require_linux_arm64" != 1 ]] || scanner_args+=(--require-linux-arm64)
    "${scanner_args[@]}" >/dev/null
    return $?
  fi
  actual="$(sha256_file "$path")" || return 1
  [[ "$actual" == "$expected" ]] || return 1
  actual_bytes="$(stat --format=%s -- "$path")" || return 1
  [[ "$actual_bytes" == "$expected_bytes" ]] || return 1
  case "$expected_type" in
    cyclonedx-json)
      jq -e '
        type == "object"
        and .bomFormat == "CycloneDX"
        and (.specVersion | type == "string" and length > 0)
      ' "$path" >/dev/null
      ;;
    scanner-json)
      jq -e 'type == "object" and length > 0' "$path" >/dev/null
      ;;
    *) return 1 ;;
  esac
}

validate_canonical_release_evidence() {
  local evidence="$1" source_commit="$2" expected_external_references="$3"
  jq -e --arg commit "$source_commit" --argjson expected_external_references "$expected_external_references" '
    def digest: type == "string" and test("^sha256:[0-9a-f]{64}$");
    def artifact($kind):
      type == "object"
      and (keys | sort == ["bytes", "name", "sha256", "type"])
      and (.name | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"))
      and (.type == $kind)
      and (.bytes | type == "number" and floor == . and . >= 1)
      and (.sha256 | digest);
    def product_reference:
      type == "string"
      and test("^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*ksi-[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)(?=[A-Za-z0-9._-]*[0-9])[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$");
    def external_reference:
      type == "string"
      and (test("^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")
        or . == "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2");
    type == "object"
    and (keys | sort == ["externalRuntimeImages", "generatedAtUtc", "productImages", "schemaVersion", "source"])
    and .schemaVersion == "1.0"
    and (.generatedAtUtc | type == "string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
    and (.source | type == "object" and keys == ["gitCommitSha"] and .gitCommitSha == $commit)
    and (.productImages | type == "array" and length == 2)
    and ([.productImages[] | type == "object"
        and (keys | sort == ["reference", "sbom", "scanner"])
        and (.reference | product_reference)
        and (.sbom | artifact("cyclonedx-json"))
        and (.scanner | artifact("scanner-json"))] | all)
    and ([.productImages[].reference] as $refs | ($refs | unique | length) == ($refs | length))
    and (.externalRuntimeImages | type == "array")
    and ([.externalRuntimeImages[] | external_reference] | all)
    and ([.externalRuntimeImages[]] as $refs | ($refs | unique | length) == ($refs | length))
    and ([.externalRuntimeImages[]] | sort == $expected_external_references)
  ' "$evidence" >/dev/null
}

validate_host_binding() {
  local binding="$1" source_commit="$2" evidence_digest="$3" expected_external_references="$4"
  local host_version
  host_version="$(jq -er '.schemaVersion' "$binding")" || return 1
  [[ "$host_version" == external-runtime-host-binding.v1 || "$host_version" == external-runtime-host-binding.v2 ]] || return 1
  jq -e --arg host_version "$host_version" --arg commit "$source_commit" --arg evidence_digest "$evidence_digest" --argjson expected_external_references "$expected_external_references" '
    def digest: type == "string" and test("^sha256:[0-9a-f]{64}$");
    def artifact($kind):
      type == "object"
      and (keys | sort == ["bytes", "path", "sha256", "type"])
      and (if $host_version == "external-runtime-host-binding.v2" then
        (.path | type == "string" and startswith("/") and (test("(^|/)\\.\\.(/|$)") | not))
        else (.path | type == "string" and startswith("/") and contains("..") | not) end)
      and (.sha256 | digest)
      and (.bytes | type == "number" and floor == . and . >= 1)
      and .type == $kind;
    def unique_repos:
      if $host_version == "external-runtime-host-binding.v2"
      then (.repoDigests | length) == (.repoDigests | unique | length) else true end;
    def archive: artifact("oci-archive") and .bytes <= 1073741824;
    def image_id: type == "string" and test("^sha256:[0-9a-f]{64}$");
    def repo_digest: type == "string" and test("^(?:[A-Za-z0-9][A-Za-z0-9._-]*(?::[0-9]{1,5})?/)?[A-Za-z0-9][A-Za-z0-9._/-]*@sha256:[0-9a-f]{64}$");
    def product_reference:
      type == "string"
      and test("^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*ksi-[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)(?=[A-Za-z0-9._-]*[0-9])[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$");
    def external_reference:
      type == "string"
      and (test("^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")
        or . == "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2");
    def product:
      type == "object"
      and (keys | sort == ["component", "dockerImageId", "releaseReference", "repoDigests", "sbom", "scanner"])
      and (.component == "core" or .component == "dashboard")
      and (.releaseReference | product_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length))
      and (.sbom | artifact("cyclonedx-json"))
      and (.scanner | artifact("scanner-json"))
      and unique_repos;
    def runtime:
      type == "object"
      and (keys | sort == (if $host_version == "external-runtime-host-binding.v2"
        then ["dockerImageId", "ociArchive", "releaseReference", "repoDigests", "role", "sbom", "scanner"]
        else ["dockerImageId", "releaseReference", "repoDigests", "role", "sbom", "scanner"] end))
      and (.role == "inspector" or .role == "measurement")
      and (.releaseReference | product_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length))
      and (.sbom | artifact("cyclonedx-json"))
      and (.scanner | artifact("scanner-json"))
      and unique_repos
      and (if $host_version == "external-runtime-host-binding.v2" then (.ociArchive | archive) else true end);
    def external:
      type == "object"
      and (keys | sort == ["dockerImageId", "releaseReference", "repoDigests"])
      and (.releaseReference | external_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length))
      and unique_repos;
    type == "object"
    and (keys | sort == ["externalRuntimeImages", "productImages", "releaseEvidence", "runtimeProducts", "schemaVersion", "source"])
    and .schemaVersion == $host_version
    and (.releaseEvidence | type == "object" and keys == ["sha256"] and .sha256 == $evidence_digest)
    and (.source | type == "object" and keys == ["gitCommitSha"] and .gitCommitSha == $commit)
    and (.productImages | type == "array" and length == 2 and ([.[] | product] | all))
    and ([.productImages[].component] | sort == ["core", "dashboard"])
    and ([.productImages[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
    and (.runtimeProducts | type == "array" and length == 2 and ([.[] | runtime] | all))
    and ([.runtimeProducts[].role] | sort == ["inspector", "measurement"])
    and ([.runtimeProducts[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
    and (.externalRuntimeImages | type == "array" and ([.[] | external] | all))
    and ([.externalRuntimeImages[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
    and ([.externalRuntimeImages[].releaseReference] | sort == $expected_external_references)
  ' "$binding" >/dev/null
}

require_release_evidence() {
  local evidence="$KSI_EXTERNAL_RC_RELEASE_EVIDENCE"
  local binding="$KSI_EXTERNAL_RC_HOST_BINDING"
  local source_commit evidence_digest runtime_reference_sets canonical_runtime_references
  local candidate_runtime_references component role reference image_id repo_digests canonical_digest
  local sbom_path sbom_sha256 sbom_bytes sbom_type scanner_path scanner_sha256 scanner_bytes scanner_type
  local binding_version scanner_expected_id require_linux_arm64 archive_path archive_sha256 archive_bytes

  [[ -z "$(git -C "$repo_dir" status --porcelain --untracked-files=all)" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact source checkout must be clean" >&2; return 1;
  }
  [[ "$evidence" == /* && -f "$evidence" && ! -L "$evidence" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact private release evidence is required" >&2; return 1;
  }
  [[ "$(stat --format=%u -- "$evidence")" == "$(id -u)" && "$(stat --format=%a -- "$evidence")" == 600 ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: evidence must be current-operator owned and mode 0600" >&2; return 1;
  }
  [[ "$binding" == /* && -f "$binding" && ! -L "$binding" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact private host image binding is required" >&2; return 1;
  }
  [[ "$(stat --format=%u -- "$binding")" == "$(id -u)" && "$(stat --format=%a -- "$binding")" == 600 ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: host image binding must be current-operator owned and mode 0600" >&2; return 1;
  }
  command -v jq >/dev/null || { echo "jq is required for release evidence" >&2; return 1; }

  source_commit="$(git -C "$repo_dir" rev-parse HEAD)"
  evidence_digest="$(sha256_file "$evidence")" || {
    echo "BLOCKED_RELEASE_EVIDENCE: release evidence cannot be hashed" >&2; return 1;
  }
  runtime_reference_sets="$(runtime_image_reference_sets)" || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact source runtime image inventory is unavailable" >&2; return 1;
  }
  canonical_runtime_references="$(jq -ce '.canonical' <<<"$runtime_reference_sets")" || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact source runtime inventory is malformed" >&2; return 1;
  }
  candidate_runtime_references="$(jq -ce '.candidate' <<<"$runtime_reference_sets")" || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact source candidate runtime inventory is malformed" >&2; return 1;
  }
  validate_canonical_release_evidence "$evidence" "$source_commit" "$canonical_runtime_references" || {
    echo "BLOCKED_RELEASE_EVIDENCE: canonical release-evidence v1 is incomplete or substituted" >&2; return 1;
  }
  validate_host_binding "$binding" "$source_commit" "$evidence_digest" "$candidate_runtime_references" || {
    echo "BLOCKED_RELEASE_EVIDENCE: host image binding is incomplete or does not bind this evidence" >&2; return 1;
  }
  binding_version="$(jq -er '.schemaVersion' "$binding")" || return 1

  [[ "$(jq -c '[.productImages[].reference] | sort' "$evidence")" == "$(jq -c '[.productImages[].releaseReference] | sort' "$binding")" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: product image references differ between evidence and host binding" >&2; return 1;
  }
  jq -e --argjson candidate "$candidate_runtime_references" '
    [.externalRuntimeImages[]] as $inventory
    | [$candidate[] as $reference | select(($inventory | index($reference)) == null)]
    | length == 0
  ' "$evidence" >/dev/null || {
    echo "BLOCKED_RELEASE_EVIDENCE: candidate runtime dependencies are absent from canonical inventory" >&2; return 1;
  }
  jq -e --argjson candidate "$candidate_runtime_references" '
    [.externalRuntimeImages[].releaseReference] as $binding
    | [$candidate[] as $reference | select(($binding | index($reference)) == null)]
    | length == 0
  ' "$binding" >/dev/null || {
    echo "BLOCKED_RELEASE_EVIDENCE: host candidate runtime binding omits a Compose dependency" >&2; return 1;
  }

  for component in core dashboard; do
    reference="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .releaseReference' "$binding")"
    image_id="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .dockerImageId' "$binding")"
    repo_digests="$(jq -c --arg component "$component" '.productImages[] | select(.component == $component) | .repoDigests' "$binding")"
    product_release_reference "$component" "$reference" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component release reference does not identify the $component product image" >&2; return 1;
    }
    verify_product_image_binding "$component" "$reference" "$image_id" "$repo_digests" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component local image observation differs from host binding" >&2; return 1;
    }
    case "$component" in
      core) export KSI_EXTERNAL_RC_CORE_IMAGE_ID="$image_id" ;;
      dashboard) export KSI_EXTERNAL_RC_DASHBOARD_IMAGE_ID="$image_id" ;;
    esac
    sbom_path="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .sbom.path' "$binding")"
    sbom_sha256="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .sbom.sha256' "$binding")"
    sbom_bytes="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .sbom.bytes' "$binding")"
    sbom_type="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .sbom.type' "$binding")"
    scanner_path="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .scanner.path' "$binding")"
    scanner_sha256="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .scanner.sha256' "$binding")"
    scanner_bytes="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .scanner.bytes' "$binding")"
    scanner_type="$(jq -r --arg component "$component" '.productImages[] | select(.component == $component) | .scanner.type' "$binding")"
    [[ "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .sbom.sha256' "$evidence")" == "$sbom_sha256" && "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .sbom.bytes' "$evidence")" == "$sbom_bytes" && "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .sbom.type' "$evidence")" == "$sbom_type" ]] || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component SBOM metadata differs from canonical evidence" >&2; return 1;
    }
    [[ "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .scanner.sha256' "$evidence")" == "$scanner_sha256" && "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .scanner.bytes' "$evidence")" == "$scanner_bytes" && "$(jq -r --arg reference "$reference" '.productImages[] | select(.reference == $reference) | .scanner.type' "$evidence")" == "$scanner_type" ]] || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component scanner metadata differs from canonical evidence" >&2; return 1;
    }
    verify_artifact_binding "$sbom_path" "$sbom_sha256" "$sbom_bytes" "$sbom_type" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component SBOM artifact differs from host binding" >&2; return 1;
    }
    verify_artifact_binding "$scanner_path" "$scanner_sha256" "$scanner_bytes" "$scanner_type" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $component scanner artifact differs from host binding" >&2; return 1;
    }
  done

  for role in inspector measurement; do
    reference="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .releaseReference' "$binding")"
    image_id="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .dockerImageId' "$binding")"
    repo_digests="$(jq -c --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .repoDigests' "$binding")"
    product_release_reference "$role" "$reference" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $role release reference does not identify the $role product image" >&2; return 1;
    }
    verify_product_image_binding "$role" "$reference" "$image_id" "$repo_digests" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $role local image observation differs from host binding" >&2; return 1;
    }
    sbom_path="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .sbom.path' "$binding")"
    sbom_sha256="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .sbom.sha256' "$binding")"
    sbom_bytes="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .sbom.bytes' "$binding")"
    sbom_type="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .sbom.type' "$binding")"
    scanner_path="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .scanner.path' "$binding")"
    scanner_sha256="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .scanner.sha256' "$binding")"
    scanner_bytes="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .scanner.bytes' "$binding")"
    scanner_type="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .scanner.type' "$binding")"
    verify_artifact_binding "$sbom_path" "$sbom_sha256" "$sbom_bytes" "$sbom_type" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $role SBOM artifact differs from host binding" >&2; return 1;
    }
    scanner_expected_id="$image_id"
    require_linux_arm64=0
    if [[ "$binding_version" == external-runtime-host-binding.v2 ]]; then
      archive_path="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .ociArchive.path' "$binding")"
      archive_sha256="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .ociArchive.sha256' "$binding")"
      archive_bytes="$(jq -r --arg role "$role" '.runtimeProducts[] | select(.role == $role) | .ociArchive.bytes' "$binding")"
      scanner_expected_id="$(python3 "$repo_dir/tools/verify_external_oci_archive.py" \
        --path "$archive_path" --sha256 "$archive_sha256" --bytes "$archive_bytes" \
        --index-id "$image_id" --source-commit "$source_commit" --role "$role")" || {
        echo "BLOCKED_RELEASE_EVIDENCE: $role OCI archive identity link is unavailable" >&2; return 1;
      }
      [[ "$scanner_expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
        echo "BLOCKED_RELEASE_EVIDENCE: $role OCI archive verifier output is malformed" >&2; return 1;
      }
      require_linux_arm64=1
    fi
    verify_artifact_binding "$scanner_path" "$scanner_sha256" "$scanner_bytes" "$scanner_type" 1 "$scanner_expected_id" "$require_linux_arm64" || {
      echo "BLOCKED_RELEASE_EVIDENCE: $role scanner artifact differs from host binding" >&2; return 1;
    }
  done

  while IFS=$'\t' read -r reference image_id repo_digests; do
    canonical_digest="$(canonical_repository_digest "$reference")" || {
      echo "BLOCKED_RELEASE_EVIDENCE: external runtime reference is not immutable" >&2; return 1;
    }
    pinned_external_runtime_reference "$reference" && verify_image_binding "$reference" "$image_id" && verify_observed_repo_digests "$reference" "$repo_digests" "$canonical_digest" || {
      echo "BLOCKED_RELEASE_EVIDENCE: external runtime image differs from host binding" >&2; return 1;
    }
    case "$reference" in
      caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d)
        export KSI_EXTERNAL_RC_CADDY_IMAGE_ID="$image_id"
        ;;
      127.0.0.1:5000/ksi-minio-mc:037d636-r2@sha256:94c391a080f8011bb0572ae178c431247239990fef6c9ac8430810c260fd0297)
        export KSI_EXTERNAL_RC_MC_IMAGE_ID="$image_id"
        ;;
      127.0.0.1:5000/ksi-minio:037d636-r2@sha256:7d3932383a4eafa842067f3ff1d15cb5fdd1430d56ae9b7a916d9a4952d27d2d)
        export KSI_EXTERNAL_RC_MINIO_IMAGE_ID="$image_id"
        ;;
      *)
        echo "BLOCKED_RELEASE_EVIDENCE: unexpected external runtime image" >&2; return 1;
        ;;
    esac
  done < <(jq -r '.externalRuntimeImages[] | [.releaseReference, .dockerImageId, (.repoDigests | @json)] | @tsv' "$binding")
}

prepare() {
  [[ ! -e "$KSI_EXTERNAL_RC_STATE_DIR" ]] || { echo "candidate state already exists; preserve it" >&2; return 1; }
  install -d -m 0700 "$KSI_EXTERNAL_RC_STATE_DIR"
  install -m 0600 "$repo_dir/deploy/.env.external-reconstruction.example" "$KSI_EXTERNAL_RC_STATE_DIR/candidate.env.template"
  printf '%s\n' "$KSI_EXTERNAL_RC_STATE_DIR/candidate.env.template"
}

status() {
  docker container ls -a \
    --filter 'label=com.docker.compose.project=ksi-external-rc' \
    --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}'
}

verify() {
  activation_preflight || return 1
  compose config >/dev/null || return 1
  if core_is_running; then
    verify_started_compose_images || return 1
    verify_live_provider || return 1
    echo "PROVIDER_CONFIGURED: runtime attachment/currentness observed; no eligibility decision is reported"
    return 0
  fi
  echo "CONFIG_VALIDATED: provider configuration is not attached; no eligibility decision is reported"
}

start() {
  # Prove mutable release, credential, ACL, and authority inputs immediately
  # before the sole ordinary service start.
  activation_preflight || return 1
  compose config >/dev/null || return 1
  compose up -d --no-build --pull never --wait || return 1
  verify_started_compose_images || return 1
  verify_live_provider || return 1
}

stop() {
  local container_ids container_id observed_project
  container_ids="$(docker container ls -a \
    --filter 'label=com.docker.compose.project=ksi-external-rc' \
    --format '{{.ID}}')" || {
    echo "BLOCKED_CANDIDATE_STOP: candidate containers cannot be listed" >&2; return 1;
  }
  [[ -n "$container_ids" ]] || return 0

  while IFS= read -r container_id; do
    [[ "$container_id" =~ ^[0-9a-f]{12,64}$ ]] || {
      echo "BLOCKED_CANDIDATE_STOP: Docker returned an invalid candidate container ID" >&2; return 1;
    }
    observed_project="$(docker container inspect \
      --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container_id")" || {
      echo "BLOCKED_CANDIDATE_STOP: candidate container cannot be rechecked" >&2; return 1;
    }
    [[ "$observed_project" == ksi-external-rc ]] || {
      echo "BLOCKED_CANDIDATE_STOP: refusing a container outside ksi-external-rc" >&2; return 1;
    }
    docker container stop -- "$container_id" || {
      local stop_status=$?
      echo "BLOCKED_CANDIDATE_STOP: candidate container stop failed" >&2; return "$stop_status";
    }
  done <<<"$container_ids"
}

main() {
  [[ $# -ge 1 ]] || usage
  action="$1"
  case "$action" in
    status) [[ $# -eq 1 ]] || usage; status; return ;;
    stop) [[ $# -eq 1 ]] || usage; stop; return ;;
  esac
  [[ $# -eq 3 && "$2" == "--env-file" ]] || usage
  env_file="$3"
  [[ "$env_file" == /* && "$env_file" != *".."* && -f "$env_file" && ! -L "$env_file" ]] || {
    echo "candidate env must be an absolute regular file" >&2; return 2;
  }
  [[ "$(stat --format=%u -- "$env_file")" == "$(id -u)" ]] || {
    echo "candidate env must be owned by the current operator" >&2; return 1;
  }
  [[ "$(stat --format=%a -- "$env_file")" == 600 ]] || {
    echo "candidate env must be mode 0600" >&2; return 1;
  }
  read_candidate_env
  [[ "$KSI_EXTERNAL_RC_PROJECT_NAME" == ksi-external-rc ]] || {
    echo "candidate project must be exactly ksi-external-rc; refusing ksi-phase2-staging" >&2; return 1;
  }
  [[ "$KSI_EXTERNAL_RC_STATE_DIR" == /* && "$KSI_EXTERNAL_RC_STATE_DIR" != *".."* ]] || {
    echo "candidate state directory must be absolute" >&2; return 1;
  }
  [[ "$KSI_EXTERNAL_RC_HOST" == *.ts.net ]] || { echo "candidate host must be Tailnet MagicDNS" >&2; return 1; }
  case "$action" in
    prepare) prepare ;;
    verify) verify ;;
    start) start ;;
    *) usage ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
