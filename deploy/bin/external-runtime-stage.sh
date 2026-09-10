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
  KSI_EXTERNAL_RC_CORE_IMAGE
  KSI_EXTERNAL_RC_DASHBOARD_IMAGE
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

canonical_repository_digest() {
  local reference="$1" name_and_tag path_component repository digest
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
  [[ "$path" == /* && -f "$path" && ! -L "$path" ]] || return 1
  printf 'sha256:%s\n' "$(sha256sum -- "$path" | awk '{print $1}')"
}

verify_image_binding() {
  local reference="$1" expected_id="$2" actual_id repo_digests canonical_digest
  immutable_reference "$reference" || return 1
  [[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  canonical_digest="$(canonical_repository_digest "$reference")" || return 1
  actual_id="$(docker image inspect --format '{{.Id}}' "$reference")" || return 1
  [[ "$actual_id" == "$expected_id" ]] || return 1
  repo_digests="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$reference")" || return 1
  grep -Fqx -- "$canonical_digest" <<<"$repo_digests"
}

verify_artifact_binding() {
  local path="$1" expected="$2" actual
  [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  actual="$(sha256_file "$path")" || return 1
  [[ "$actual" == "$expected" ]]
}

require_release_evidence() {
  local evidence="$KSI_EXTERNAL_RC_RELEASE_EVIDENCE"
  local source_commit core_reference core_image_id dashboard_reference dashboard_image_id
  local sbom_path sbom_sha256 scanner_path scanner_sha256 reference image_id

  [[ -z "$(git -C "$repo_dir" status --porcelain --untracked-files=all)" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact source checkout must be clean" >&2; return 1;
  }
  [[ "$evidence" == /* && -f "$evidence" && ! -L "$evidence" ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: exact private release evidence is required" >&2; return 1;
  }
  [[ "$(stat --format=%u -- "$evidence")" == "$(id -u)" && "$(stat --format=%a -- "$evidence")" == 600 ]] || {
    echo "BLOCKED_RELEASE_EVIDENCE: evidence must be current-operator owned and mode 0600" >&2; return 1;
  }
  command -v jq >/dev/null || { echo "jq is required for release evidence" >&2; return 1; }

  source_commit="$(git -C "$repo_dir" rev-parse HEAD)"
  jq -e --arg commit "$source_commit" --arg core "$KSI_EXTERNAL_RC_CORE_IMAGE" --arg dashboard "$KSI_EXTERNAL_RC_DASHBOARD_IMAGE" '
    .sourceCommit == $commit
    and .images.core.reference == $core
    and (.images.core.imageId | test("^sha256:[0-9a-f]{64}$"))
    and .images.dashboard.reference == $dashboard
    and (.images.dashboard.imageId | test("^sha256:[0-9a-f]{64}$"))
    and (.sbom.path | type == "string")
    and (.sbom.sha256 | test("^sha256:[0-9a-f]{64}$"))
    and (.scanner.path | type == "string")
    and (.scanner.sha256 | test("^sha256:[0-9a-f]{64}$"))
    and (.externalRuntimeImages | type == "array")
    and (.externalRuntimeImages | length > 0)
    and ([.externalRuntimeImages[] | (.reference | test("^[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")) and (.imageId | test("^sha256:[0-9a-f]{64}$"))] | all)
  ' "$evidence" >/dev/null || {
    echo "BLOCKED_RELEASE_EVIDENCE: source, immutable image, SBOM, or scanner binding is incomplete" >&2; return 1;
  }

  core_reference="$(jq -r '.images.core.reference' "$evidence")"
  core_image_id="$(jq -r '.images.core.imageId' "$evidence")"
  dashboard_reference="$(jq -r '.images.dashboard.reference' "$evidence")"
  dashboard_image_id="$(jq -r '.images.dashboard.imageId' "$evidence")"
  verify_image_binding "$core_reference" "$core_image_id" || {
    echo "BLOCKED_RELEASE_EVIDENCE: Core image ID or digest differs from evidence" >&2; return 1;
  }
  verify_image_binding "$dashboard_reference" "$dashboard_image_id" || {
    echo "BLOCKED_RELEASE_EVIDENCE: Dashboard image ID or digest differs from evidence" >&2; return 1;
  }

  sbom_path="$(jq -r '.sbom.path' "$evidence")"
  sbom_sha256="$(jq -r '.sbom.sha256' "$evidence")"
  scanner_path="$(jq -r '.scanner.path' "$evidence")"
  scanner_sha256="$(jq -r '.scanner.sha256' "$evidence")"
  verify_artifact_binding "$sbom_path" "$sbom_sha256" || {
    echo "BLOCKED_RELEASE_EVIDENCE: SBOM artifact hash differs from evidence" >&2; return 1;
  }
  verify_artifact_binding "$scanner_path" "$scanner_sha256" || {
    echo "BLOCKED_RELEASE_EVIDENCE: scanner artifact hash differs from evidence" >&2; return 1;
  }

  while IFS=$'\t' read -r reference image_id; do
    verify_image_binding "$reference" "$image_id" || {
      echo "BLOCKED_RELEASE_EVIDENCE: external runtime image differs from evidence" >&2; return 1;
    }
  done < <(jq -r '.externalRuntimeImages[] | [.reference, .imageId] | @tsv' "$evidence")
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
  immutable_reference "$KSI_EXTERNAL_RC_CORE_IMAGE" || {
    echo "Core image must be an immutable registry reference" >&2; return 1;
  }
  immutable_reference "$KSI_EXTERNAL_RC_DASHBOARD_IMAGE" || {
    echo "Dashboard image must be an immutable registry reference" >&2; return 1;
  }
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
