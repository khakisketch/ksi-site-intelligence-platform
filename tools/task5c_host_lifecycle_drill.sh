#!/bin/bash
# Task 5c host lifecycle drills — run as root ON the approved sandbox host.
#
# Self-contained: writes its own driver + generates its own GeoTIFF inputs with
# the runtime venv, then runs two real lifecycle drills against the running
# inspector daemon:
#
#   D1 cancellation — drive a real attempt, SIGKILL the driver at
#      CONTAINER_BOUND (full peer loss), and prove the daemon cancels the exact
#      runtime, cleans every resource and writes a durable CLEANED record with
#      measured end-to-end latency (no daemon restart involved).
#
#   D2 orphan recovery — drive a real attempt, SIGKILL the daemon at
#      CONTAINER_BOUND leaving a live orphan (container, attempt slice,
#      staging), verify the orphan exists, restart the daemon and prove startup
#      recovery removes exactly those resources, reopens admission and serves.
#
# Every check prints PASS/FAIL.  Exit 0 only when every check passed.
set -u

# --- fixed approved-host assets -------------------------------------------------
PY=/srv/ksi-data-sandbox/runtime/venv/bin/python
J=/var/lib/ksi-external-runtime/launcher/journal/attempts.jsonl
STAGING=/var/lib/ksi-external-runtime/launcher/input-staging
WORK=/tmp/ksi-task5c-drill
SMALL=$WORK/drill-small.tif
SLOW=$WORK/drill-slow.tif
DRIVER=$WORK/drive_inspection_v2.py
INSPECT_ENV="XDG_RUNTIME_DIR=/run/user/997 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/997/bus"
SERVICE=ksi-external-inspector.service

FAILED=0
ok()  { echo "PASS  $1  $2"; }
bad() { echo "FAIL  $1  $2"; FAILED=1; }
insp() { sudo -u ksi-inspector env XDG_RUNTIME_DIR=/run/user/997 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/997/bus "$@"; }
insp_docker() { sudo -u ksi-inspector env DOCKER_HOST=unix:///run/user/997/docker.sock XDG_RUNTIME_DIR=/run/user/997 docker "$@"; }
journal_since() { tail -n +$(($1 + 1)) "$J" 2>/dev/null | grep -F "\"attemptNonce\":\"$2\""; }
wait_phase() {  # $1=since $2=nonce $3=phase $4=timeout_ns
  local deadline=$(( $(date +%s%N) + $4 ))
  while [ "$(date +%s%N)" -lt "$deadline" ]; do
    journal_since "$1" "$2" | grep -q "\"phase\":\"$3\"" && return 0
    sleep 0.02
  done
  return 1
}
runtime_id_of() { journal_since "$1" "$2" | grep '"phase":"CONTAINER_BOUND"' | tail -1 | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["runtimeId"])'; }

mkdir -p "$WORK"
chmod 777 "$WORK"

# --- driver ---------------------------------------------------------------------
cat > "$DRIVER" <<'DRIVER_EOF'
"""Drive one real inspection attempt through the inspector daemon (as ksi-validator)."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, socket, sys, uuid
from datetime import datetime, timezone
from io import BytesIO

sys.path.insert(0, "/srv/ksi-data-sandbox/runtime/ksisrc")
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionRequestV1, ExternalValidationPolicyV1, PolicyStatus,
    ResourceEnvelopeV1, SealedExternalSubjectV1,
)
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_protocol import (
    InspectorLaunchRequestV1, InspectorOperation, LocalLeaseFenceV1, ProtocolLimitsV1,
    SealedByteBindingV1, read_launch_result, write_launch_request,
)

BASE = pathlib.Path("/etc/ksi-external-runtime/inspector")
SOCKET = "/run/ksi-external-runtime/launcher/inspection.sock"
ENVELOPE = {
    "maxInputBytes": 1073741824, "maxStreamedBytes": 1073741824, "maxTiffDirectories": 16,
    "maxTiffEntries": 4096, "maxPixels": 250000000, "maxBands": 8, "maxBlocks": 65536,
    "maxDecompressedBytes": 536870912, "maxSampleBytes": 1073741824, "maxGeometryVertices": 4096,
    "maxCpuSeconds": 300.0, "maxMemoryBytes": 4294967296, "maxWorkspaceBytes": 3221225472,
    "maxOutputBytes": 134217728, "maxTenantConcurrency": 4, "maxQueueDepth": 8,
    "maxDeadlineSeconds": 3600.0, "leaseDurationSeconds": 60.0, "maxRetryAttempts": 3,
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    manifest = json.loads((BASE / "execution-manifest.json").read_text())
    envelope = ResourceEnvelopeV1(**ENVELOPE).sealed()
    policy = ExternalValidationPolicyV1(
        policy_id="ksi-acceptance-inspection-policy", version=1, status=PolicyStatus.ACTIVE,
        parser_build_digest=manifest["signature"]["digest"],
        grammar_digest=external_geotiff_profile_digest_v1(),
        resource_envelope=envelope, resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest="sha256:" + "1" * 64,
        inspection_rule_ids=("ksi-acceptance-inspect",), evidence_rule_ids=(),
        compatibility_mapping_digests=(), synthetic_test_only=True,
    ).sealed()
    subject = SealedExternalSubjectV1(
        organization_id="org-a", site_id="f03-flow-site", work_order_id="obs-work-00000014",
        submission_id="ers-v1-task5c-drill", revision=1,
        submission_digest="sha256:" + "2" * 64, manifest_digest="sha256:" + "3" * 64,
    )
    request = ExternalArtifactInspectionRequestV1(
        request_id=f"ksi-task5c-{args.nonce}", subject=subject,
        inspection_policy_id=policy.policy_id, inspection_policy_version=policy.version,
        inspection_policy_digest=policy.policy_digest,
        issued_at=datetime.now(timezone.utc), idempotency_key=f"ksi-task5c-{args.nonce}",
    )
    artifact = pathlib.Path(args.input).read_bytes()
    binding = SealedByteBindingV1(
        artifact_id="task5c-drill-dsm",
        observed_sha256="sha256:" + hashlib.sha256(artifact).hexdigest(),
        observed_size_bytes=len(artifact),
    )
    fence = LocalLeaseFenceV1(worker_instance_id=str(uuid.uuid4()),
                              lease_acquisition_id=str(uuid.uuid4()), lease_generation=1)
    launch = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.INSPECT, request=request, fence=fence, subject=subject,
        sealed_byte_binding=binding, policy=policy, attempt_nonce=args.nonce,
    )
    limits = ProtocolLimitsV1(max_header_bytes=65536, max_chunk_bytes=1048576,
                              max_input_bytes=1073741824, max_output_bytes=268435456,
                              max_wire_duration_millis=900000)
    print(f"driver ready nonce={args.nonce} input_bytes={len(artifact)}", flush=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(900)
        connection.connect(SOCKET)
        print("connected", flush=True)
        write_launch_request(connection, launch, BytesIO(artifact), limits)
        print("request written", flush=True)
        first = read_launch_result(connection, limits)
        print("frame1:", json.dumps(first.model_dump(by_alias=True, mode="json")), flush=True)
        terminal = read_launch_result(connection, limits)
        print("frame2:", json.dumps(terminal.model_dump(by_alias=True, mode="json")), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
DRIVER_EOF
chmod 755 "$DRIVER"

# --- inputs (idempotent; generated with the runtime venv) -----------------------
if [ ! -s "$SMALL" ]; then
  $PY - "$SMALL" <<'GEN_SMALL' || bad "generate small GeoTIFF" ""
import sys
import numpy as np, rasterio
from rasterio.transform import from_origin
profile = dict(driver="GTiff", dtype="float32", count=1, width=64, height=64,
               crs="EPSG:7850", transform=from_origin(382350, 6467750, 0.05, 0.05), nodata=-9999.0)
data = np.linspace(10.0, 20.0, 64 * 64, dtype="float32").reshape(64, 64)
data[0:4, 0:4] = -9999.0
with rasterio.open(sys.argv[1], "w", **profile) as dst:
    dst.write(data, 1)
GEN_SMALL
fi
if [ ! -s "$SLOW" ]; then
  $PY - "$SLOW" <<'GEN_SLOW' || bad "generate slow GeoTIFF" ""
import sys
import numpy as np, rasterio
from rasterio.transform import from_origin
SIZE = 8192
data = np.random.default_rng(7).uniform(0.0, 100.0, SIZE * SIZE).astype("float32").reshape(SIZE, SIZE)
data[0:8, 0:8] = -9999.0
profile = dict(driver="GTiff", dtype="float32", count=1, width=SIZE, height=SIZE,
               crs="EPSG:7850", transform=from_origin(382350.0, 6467750.0, 0.05, 0.05),
               nodata=-9999.0, tiled=True, blockxsize=256, blockysize=256, compress="deflate")
with rasterio.open(sys.argv[1], "w", **profile) as dst:
    dst.write(data, 1)
GEN_SLOW
fi
[ -s "$SMALL" ] && [ -s "$SLOW" ] && ok "D0 drill inputs ready" "small+slow GeoTIFFs" || { bad "D0 drill inputs ready" ""; exit 1; }
chmod 644 "$SMALL" "$SLOW"

serve_check() {  # $1 = label
  local log=$WORK/serve-check.log
  sudo -u ksi-validator timeout 180 $PY "$DRIVER" --input "$SMALL" --nonce "t5c-serve-$(date -u +%H%M%S%N)" > "$log" 2>&1
  if [ $? -eq 0 ] && grep -q '"result": "COMPLETED"' "$log" && grep -q '"outcome": "MEASURED"' "$log"; then
    ok "$1" "fresh attempt COMPLETED/MEASURED"
  else
    bad "$1" "$(tail -2 "$log")"
  fi
}

# ================================ D1 cancellation ===============================
echo "--- D1 cancellation drill ---"
BEFORE=$(wc -l < "$J")
NONCE="t5c-cancel-$(date -u +%H%M%S)"
DPID=$(sudo -u ksi-validator sh -c "nohup $PY $DRIVER --input $SLOW --nonce $NONCE > $WORK/cancel-driver.log 2>&1 & echo \$!")
[ -n "$DPID" ] && ok "D1 driver started" "nonce=$NONCE pid=$DPID" || { bad "D1 driver started" ""; exit 1; }
if wait_phase "$BEFORE" "$NONCE" CONTAINER_BOUND 300000000000; then
  ok "D1 attempt reached CONTAINER_BOUND" "runtimeId=$(runtime_id_of "$BEFORE" "$NONCE" | cut -c1-12)…"
else
  bad "D1 attempt reached CONTAINER_BOUND" "timeout"; exit 1
fi
RUNTIME_ID=$(runtime_id_of "$BEFORE" "$NONCE")
KILL_AT=$(date +%s.%N)
sudo kill -9 "$DPID" 2>/dev/null
ok "D1 driver killed (full peer loss)" "pid=$DPID"
if wait_phase "$BEFORE" "$NONCE" CLEANED 180000000000; then
  CLEANED_AT=$(date +%s.%N)
  LATENCY=$(python3 -c "print(f'{$CLEANED_AT - $KILL_AT:.3f}')")
  ok "D1 durable CLEANED after cancellation" "latency=${LATENCY}s"
else
  bad "D1 durable CLEANED after cancellation" "timeout"
fi
DISPOSITION=$(journal_since "$BEFORE" "$NONCE" | grep '"phase":"CLEANUP_REQUIRED"' | tail -1 | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("disposition",""))')
[ "$DISPOSITION" = "MONITOR_CANCELLED" ] && ok "D1 monitor cancellation disposition" "$DISPOSITION" || bad "D1 monitor cancellation disposition" "$DISPOSITION"
CSTATE=$(insp_docker ps -a --no-trunc --format '{{.ID}}' 2>/dev/null | grep -c "${RUNTIME_ID:0:12}")
[ "$CSTATE" = "0" ] && ok "D1 exact container removed" "" || bad "D1 exact container removed" "still present"
SLICES=$(insp systemctl --user list-units --all --no-legend 'ksi-inspector-a*' 2>/dev/null | grep -c .)
[ "$SLICES" = "0" ] && ok "D1 attempt slice gone" "" || bad "D1 attempt slice gone" "$SLICES remain"
STAGE=$(sudo ls -A "$STAGING" 2>/dev/null | grep -c .)
[ "$STAGE" = "0" ] && ok "D1 staging clean" "" || bad "D1 staging clean" "$STAGE entries"
SERVICE_STATE=$(insp systemctl --user show -p ActiveState $SERVICE | cut -d= -f2)
[ "$SERVICE_STATE" = "active" ] && ok "D1 daemon served through cancellation" "ActiveState=$SERVICE_STATE" || bad "D1 daemon served through cancellation" "$SERVICE_STATE"
serve_check "D1 post-cancellation serve check"

# ================================ D2 orphan recovery ============================
echo "--- D2 orphan recovery drill ---"
BEFORE=$(wc -l < "$J")
NONCE="t5c-orphan-$(date -u +%H%M%S)"
MAINPID=$(insp systemctl --user show -p MainPID $SERVICE | cut -d= -f2)
[ "$MAINPID" != "0" ] && ok "D2 daemon running before drill" "MainPID=$MAINPID" || { bad "D2 daemon running before drill" ""; exit 1; }
DPID=$(sudo -u ksi-validator sh -c "nohup $PY $DRIVER --input $SLOW --nonce $NONCE > $WORK/orphan-driver.log 2>&1 & echo \$!")
[ -n "$DPID" ] && ok "D2 driver started" "nonce=$NONCE pid=$DPID" || { bad "D2 driver started" ""; exit 1; }
if wait_phase "$BEFORE" "$NONCE" CONTAINER_BOUND 480000000000; then
  ok "D2 attempt reached CONTAINER_BOUND" "runtimeId=$(runtime_id_of "$BEFORE" "$NONCE" | cut -c1-12)…"
else
  bad "D2 attempt reached CONTAINER_BOUND" "timeout"; exit 1
fi
RUNTIME_ID=$(runtime_id_of "$BEFORE" "$NONCE")
sudo kill -9 "$MAINPID" 2>/dev/null
sleep 0.5
MAIN_AFTER=$(insp systemctl --user show -p MainPID $SERVICE | cut -d= -f2)
[ "$MAIN_AFTER" = "0" ] && ok "D2 daemon SIGKILLed mid-attempt" "" || bad "D2 daemon SIGKILLed mid-attempt" "MainPID=$MAIN_AFTER"
CSTATE=$(insp_docker ps -a --no-trunc --format '{{.ID}} {{.State}}' 2>/dev/null | grep "${RUNTIME_ID:0:12}")
[ -n "$CSTATE" ] && ok "D2 orphan container present" "${CSTATE:0:60}" || bad "D2 orphan container present" "absent"
ORPHAN_SLICES=$(insp systemctl --user list-units --all --no-legend 'ksi-inspector-a*' 2>/dev/null | grep -c .)
[ "$ORPHAN_SLICES" != "0" ] && ok "D2 orphan attempt slice present" "$ORPHAN_SLICES unit(s)" || bad "D2 orphan attempt slice present" ""
ORPHAN_STAGE=$(sudo ls -A "$STAGING" 2>/dev/null | grep -c .)
[ "$ORPHAN_STAGE" != "0" ] && ok "D2 orphan staging present" "$ORPHAN_STAGE entry(s)" || bad "D2 orphan staging present" ""
insp systemctl --user reset-failed $SERVICE >/dev/null 2>&1
insp systemctl --user start $SERVICE
ok "D2 daemon restarted" "unit start issued"
if wait_phase "$BEFORE" "$NONCE" CLEANED 180000000000; then
  ok "D2 startup recovery wrote durable CLEANED" "nonce=$NONCE"
else
  bad "D2 startup recovery wrote durable CLEANED" "timeout"
fi
RECOVERY_DISPOSITION=$(journal_since "$BEFORE" "$NONCE" | grep '"phase":"CLEANUP_REQUIRED"' | tail -1 | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("disposition",""))')
[ "$RECOVERY_DISPOSITION" = "STARTUP_RECOVERY" ] && ok "D2 recovery disposition" "$RECOVERY_DISPOSITION" || bad "D2 recovery disposition" "$RECOVERY_DISPOSITION"
CSTATE=$(insp_docker ps -a --no-trunc --format '{{.ID}}' 2>/dev/null | grep -c "${RUNTIME_ID:0:12}")
[ "$CSTATE" = "0" ] && ok "D2 exact container removed by recovery" "" || bad "D2 exact container removed by recovery" "still present"
SLICES=$(insp systemctl --user list-units --all --no-legend 'ksi-inspector-a*' 2>/dev/null | grep -c .)
[ "$SLICES" = "0" ] && ok "D2 attempt slice gone" "" || bad "D2 attempt slice gone" "$SLICES remain"
STAGE=$(sudo ls -A "$STAGING" 2>/dev/null | grep -c .)
[ "$STAGE" = "0" ] && ok "D2 staging clean" "" || bad "D2 staging clean" "$STAGE entries"
serve_check "D2 post-recovery serve check"

echo "DRILLS $([ $FAILED -eq 0 ] && echo OK || echo FAILED)"
exit $FAILED
