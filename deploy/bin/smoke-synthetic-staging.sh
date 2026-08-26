#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 || ! "$1" =~ ^[A-Za-z0-9.-]+\.ts\.net$ ]]; then
  echo "usage: $0 host.ts.net app-port identity-port api-port objects-port" >&2
  exit 2
fi
host="$1"
app_port="$2"
identity_port="$3"
api_port="$4"
objects_port="$5"
for port in "$app_port" "$identity_port" "$api_port" "$objects_port"; do
  [[ "$port" =~ ^[0-9]+$ ]] && (( port > 0 && port <= 65535 )) || {
    echo "invalid port: $port" >&2
    exit 2
  }
done

curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 20)
curl "${curl_args[@]}" "https://${host}:${app_port}/api/health" | grep -q '"status":"ok"'
curl "${curl_args[@]}" "https://${host}:${identity_port}/healthz" | grep -q '"status":"ok"'
curl "${curl_args[@]}" "https://${host}:${api_port}/ready" | grep -q '"ready":true'
curl "${curl_args[@]}" "https://${host}:${objects_port}/minio/health/ready" >/dev/null
curl "${curl_args[@]}" "https://${host}:${identity_port}/.well-known/openid-configuration" \
  | grep -q "https://${host}:${identity_port}"
curl "${curl_args[@]}" "https://${host}:${app_port}/api/auth/providers" | grep -q 'ksi-oidc'

auth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "https://${host}:${api_port}/v1/auth/whoami")"
session_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "https://${host}:${app_port}/api/auth/session")"
[[ "$auth_status" == "401" ]] || { echo "Core expected 401, got $auth_status" >&2; exit 1; }
[[ "$session_status" == "404" ]] || { echo "session expected 404, got $session_status" >&2; exit 1; }

echo "synthetic staging TLS/readiness/OIDC/object surface smoke passed"
