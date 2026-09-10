#!/usr/bin/env bash
# Candidate lifecycle wrapper. It never touches ksi-phase2-staging or its volumes.
set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
compose_file="$repo_dir/deploy/compose.external-reconstruction.yaml"

usage() {
  echo "usage: $0 prepare|status|verify|start|stop --env-file /absolute/candidate.env" >&2
  exit 2
}

readonly required_keys=(
  KSI_EXTERNAL_RC_PROJECT_NAME
  KSI_EXTERNAL_RC_STATE_DIR
  KSI_EXTERNAL_RC_RELEASE_EVIDENCE
  KSI_EXTERNAL_RC_HOST_BINDING
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
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$ ]]
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
  local actual actual_bytes
  [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  actual="$(sha256_file "$path")" || return 1
  [[ "$actual" == "$expected" ]] || return 1
  [[ "$expected_bytes" =~ ^[1-9][0-9]*$ ]] || return 1
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
      if [[ "$strict_scanner_identity" == 1 ]]; then
        jq -e '
          type == "object"
          and (.scanner | type == "object")
          and (.scanner.name | type == "string" and length > 0)
          and (.scanner.schemaVersion | type == "string" and length > 0)
        ' "$path" >/dev/null
      else
        jq -e 'type == "object" and length > 0' "$path" >/dev/null
      fi
      ;;
    *) return 1 ;;
  esac
}

validate_canonical_release_evidence() {
  local evidence="$1" source_commit="$2"
  jq -e --arg commit "$source_commit" '
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
      and test("^(?:[a-z0-9][a-z0-9._/-]*/)*ksi-[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)(?=[A-Za-z0-9._-]*[0-9])[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$");
    def external_reference:
      type == "string"
      and (test("^(?:[a-z0-9][a-z0-9._/-]*/)*[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")
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
    and (.externalRuntimeImages | type == "array" and length >= 2)
    and ([.externalRuntimeImages[] | external_reference] | all)
    and ([.externalRuntimeImages[]] as $refs | ($refs | unique | length) == ($refs | length))
  ' "$evidence" >/dev/null
}

validate_host_binding() {
  local binding="$1" source_commit="$2" evidence_digest="$3"
  jq -e --arg commit "$source_commit" --arg evidence_digest "$evidence_digest" '
    def digest: type == "string" and test("^sha256:[0-9a-f]{64}$");
    def artifact($kind):
      type == "object"
      and (keys | sort == ["bytes", "path", "sha256", "type"])
      and (.path | type == "string" and startswith("/") and contains("..") | not)
      and (.sha256 | digest)
      and (.bytes | type == "number" and floor == . and . >= 1)
      and .type == $kind;
    def image_id: type == "string" and test("^sha256:[0-9a-f]{64}$");
    def repo_digest: type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._/-]*@sha256:[0-9a-f]{64}$");
    def product_reference:
      type == "string"
      and test("^(?:[a-z0-9][a-z0-9._/-]*/)*ksi-[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)(?=[A-Za-z0-9._-]*[0-9])[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$");
    def external_reference:
      type == "string"
      and (test("^(?:[a-z0-9][a-z0-9._/-]*/)*[a-z0-9][a-z0-9._-]*:(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")
        or . == "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2");
    def product:
      type == "object"
      and (keys | sort == ["component", "dockerImageId", "releaseReference", "repoDigests", "sbom", "scanner"])
      and (.component == "core" or .component == "dashboard")
      and (.releaseReference | product_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length))
      and (.sbom | artifact("cyclonedx-json"))
      and (.scanner | artifact("scanner-json"));
    def runtime:
      type == "object"
      and (keys | sort == ["dockerImageId", "releaseReference", "repoDigests", "role", "sbom", "scanner"])
      and (.role == "inspector" or .role == "measurement")
      and (.releaseReference | product_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length))
      and (.sbom | artifact("cyclonedx-json"))
      and (.scanner | artifact("scanner-json"));
    def external:
      type == "object"
      and (keys | sort == ["dockerImageId", "releaseReference", "repoDigests"])
      and (.releaseReference | external_reference)
      and (.dockerImageId | image_id)
      and (.repoDigests | type == "array" and length >= 1 and ([.[] | repo_digest] | all) and (unique | length == length));
    type == "object"
    and (keys | sort == ["externalRuntimeImages", "productImages", "releaseEvidence", "runtimeProducts", "schemaVersion", "source"])
    and .schemaVersion == "external-runtime-host-binding.v1"
    and (.releaseEvidence | type == "object" and keys == ["sha256"] and .sha256 == $evidence_digest)
    and (.source | type == "object" and keys == ["gitCommitSha"] and .gitCommitSha == $commit)
    and (.productImages | type == "array" and length == 2 and ([.[] | product] | all))
    and ([.productImages[].component] | sort == ["core", "dashboard"])
    and ([.productImages[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
    and (.runtimeProducts | type == "array" and length == 2 and ([.[] | runtime] | all))
    and ([.runtimeProducts[].role] | sort == ["inspector", "measurement"])
    and ([.runtimeProducts[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
    and (.externalRuntimeImages | type == "array" and length >= 2 and ([.[] | external] | all))
    and ([.externalRuntimeImages[].releaseReference] as $refs | ($refs | unique | length) == ($refs | length))
  ' "$binding" >/dev/null
}

require_release_evidence() {
  local evidence="$KSI_EXTERNAL_RC_RELEASE_EVIDENCE"
  local binding="$KSI_EXTERNAL_RC_HOST_BINDING"
  local source_commit evidence_digest component role reference image_id repo_digests canonical_digest
  local sbom_path sbom_sha256 sbom_bytes sbom_type scanner_path scanner_sha256 scanner_bytes scanner_type

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
  validate_canonical_release_evidence "$evidence" "$source_commit" || {
    echo "BLOCKED_RELEASE_EVIDENCE: canonical release-evidence v1 is incomplete or substituted" >&2; return 1;
  }
  validate_host_binding "$binding" "$source_commit" "$evidence_digest" || {
    echo "BLOCKED_RELEASE_EVIDENCE: host image binding is incomplete or does not bind this evidence" >&2; return 1;
  }

  [[ "$(jq -c '[.productImages[].reference] | sort' "$evidence")" == "$(jq -c '[.productImages[].releaseReference] | sort' "$binding")" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: product image references differ between evidence and host binding" >&2; return 1;
  }
  [[ "$(jq -c '[.externalRuntimeImages[]] | sort' "$evidence")" == "$(jq -c '[.externalRuntimeImages[].releaseReference] | sort' "$binding")" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: external runtime references differ between evidence and host binding" >&2; return 1;
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
    verify_artifact_binding "$scanner_path" "$scanner_sha256" "$scanner_bytes" "$scanner_type" 1 || {
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
  done < <(jq -r '.externalRuntimeImages[] | [.releaseReference, .dockerImageId, (.repoDigests | @json)] | @tsv' "$binding")
}

prepare() {
  [[ ! -e "$KSI_EXTERNAL_RC_STATE_DIR" ]] || { echo "candidate state already exists; preserve it" >&2; return 1; }
  install -d -m 0700 "$KSI_EXTERNAL_RC_STATE_DIR"
  install -m 0600 "$repo_dir/deploy/.env.external-reconstruction.example" "$KSI_EXTERNAL_RC_STATE_DIR/candidate.env.template"
  printf '%s\n' "$KSI_EXTERNAL_RC_STATE_DIR/candidate.env.template"
}

status() {
  compose ps
}

verify() {
  require_release_evidence
  compose config >/dev/null
  echo "BLOCKED_QUANTITATIVE_AUTHORITY: no real catalog, policy, evidence-currentness, and input-capability authority is wired by this candidate"
  return 1
}

start() {
  require_release_evidence
  compose config >/dev/null
  echo "BLOCKED_QUANTITATIVE_AUTHORITY: starting would misrepresent an absent external quantitative authority" >&2
  return 1
}

stop() {
  compose stop
}

main() {
  [[ $# -eq 3 && "$2" == "--env-file" ]] || usage
  action="$1"
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
    status) status ;;
    verify) verify ;;
    start) start ;;
    stop) stop ;;
    *) usage ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
