#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "usage: $0 base.domain.example" >&2
  exit 2
fi
domain="$1"
curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 20)
if [[ -n "${KSI_SMOKE_CACERT:-}" ]]; then
  curl_args+=(--cacert "$KSI_SMOKE_CACERT")
fi

resolve=(--resolve "app.${domain}:443:127.0.0.1" --resolve "api.${domain}:443:127.0.0.1" --resolve "objects.${domain}:443:127.0.0.1")

curl "${curl_args[@]}" "${resolve[@]}" "https://app.${domain}/api/health" | grep -q '"status":"ok"'
curl "${curl_args[@]}" "${resolve[@]}" "https://api.${domain}/ready" | grep -q '"ready":true'
curl "${curl_args[@]}" "${resolve[@]}" "https://objects.${domain}/minio/health/ready" >/dev/null
curl "${curl_args[@]}" "${resolve[@]}" "https://app.${domain}/api/auth/providers" | grep -q 'ksi-oidc'

auth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "${resolve[@]}" "https://api.${domain}/v1/auth/whoami")"
session_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "${resolve[@]}" "https://app.${domain}/api/auth/session")"
[[ "$auth_status" == "401" ]] || { echo "unauthenticated Core expected 401, got $auth_status" >&2; exit 1; }
[[ "$session_status" == "404" ]] || { echo "browser Auth.js session expected 404, got $session_status" >&2; exit 1; }

echo "VM TLS/readiness/OIDC surface smoke passed"
