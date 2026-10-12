"""F-04 rehearsal orchestration: same-Site t0/t1 external-artifact cycles.

Runs the two-cycle sequence through the public Core API and reports each step's
state, failing closed at environment gates (inspection policy/parser, analysis
activation, measurement lane). It composes existing endpoints only; it owns no
product policy and makes no accuracy, settlement or acceptance claim.

Per cycle (t0, t1):
  work order (idempotent) -> external-reconstruction context -> register the
  v1 submission candidate (client-side canonical digest) -> upload grants ->
  PUT the artifact bytes -> seal -> inspection state.

Then, unless ``--skip-analysis``:
  POST /v2/sites/{site}/work-areas/{area}/analyses with the two sealed
  selectors and report 202 or the named activation gate.

Usage:
  uv run --locked python scripts/rehearse_two_cycle_external_flow.py \
    --core-url http://127.0.0.1:8041 --token-file /path/to/token \
    --site-id f03-flow-site --work-area-id wa-f03-flow-site-0001 \
    --ortho-t0 t0-ortho.tif --dsm-t0 t0-dsm.tif \
    --ortho-t1 t1-ortho.tif --dsm-t1 t1-dsm.tif \
    --capture-t0 2026-10-12T09:00:00Z/2026-10-12T09:30:00Z \
    --capture-t1 2026-10-12T10:00:00Z/2026-10-12T10:30:00Z

Exit codes: 0 = every step reached; 2 = blocked at a named gate; 1 = unexpected
failure. The bearer token is read from the token file and never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BLOCKED = 2

GATE_STATES = {
    "INSPECTION_PENDING_POLICY": "inspection policy/authority is not configured for this epoch",
    "INSPECTION_PENDING": "inspection awaits the sandboxed parser lane",
}


def canonical_digest(candidate: dict) -> str:
    """Same canonicalization as the F-02/F-03 rehearsal scripts and the Console."""
    body = {key: value for key, value in candidate.items() if key != "submissionDigest"}
    body["artifacts"] = sorted(body["artifacts"], key=lambda item: item["artifactId"])
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def artifact(kind: str, data: bytes, *, crs: str, file_name: str) -> dict:
    return {
        "artifactId": kind,
        "kind": kind,
        "fileName": file_name,
        "format": "GeoTIFF",
        "contentType": "application/octet-stream",
        "declaredSha256": hashlib.sha256(data).hexdigest(),
        "declaredSizeBytes": len(data),
        "declaredCrs": crs,
        "declaredVerticalReference": None,
        "declaredGsdM": None,
    }


def parse_capture(value: str) -> tuple[str, str]:
    start, _, end = value.partition("/")
    if not start or not end:
        raise argparse.ArgumentTypeError("expected START/END ISO-8601 UTC instants")
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--work-area-id", required=True)
    parser.add_argument("--organization-id", default="org-a")
    parser.add_argument("--ortho-t0", required=True, type=Path)
    parser.add_argument("--dsm-t0", type=Path)
    parser.add_argument("--ortho-t1", required=True, type=Path)
    parser.add_argument("--dsm-t1", type=Path)
    parser.add_argument("--capture-t0", required=True, type=parse_capture)
    parser.add_argument("--capture-t1", required=True, type=parse_capture)
    parser.add_argument("--declared-crs", default="EPSG:5186")
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cycles = {
        "t0": (args.ortho_t0, args.dsm_t0, args.capture_t0),
        "t1": (args.ortho_t1, args.dsm_t1, args.capture_t1),
    }
    for label, (ortho, dsm, _) in cycles.items():
        for path in (ortho, dsm):
            if path is not None and not path.is_file():
                print(f"[{label}] missing artifact file: {path}", file=sys.stderr)
                return EXIT_FAILURE

    if args.dry_run:
        for label, (ortho, dsm, capture) in cycles.items():
            print(f"[{label}] order+register+upload+seal dry plan: ortho={ortho.name}"
                  f" dsm={dsm.name if dsm else '-'} capture={capture[0]}..{capture[1]}")
        plan = "pair request" if not args.skip_analysis else "skipped"
        print(f"[analysis] dry plan: {plan}")
        return EXIT_OK

    token = args.token_file.read_text(encoding="utf-8").strip()
    if not token:
        print(f"empty token file: {args.token_file}", file=sys.stderr)
        return EXIT_FAILURE
    headers = {"Authorization": f"Bearer {token}"}
    client = httpx.Client(timeout=60)
    whoami = client.get(f"{args.core_url}/v1/auth/whoami", headers=headers)
    if whoami.status_code != 200:
        print(f"whoami failed: {whoami.status_code} {whoami.text[:200]}", file=sys.stderr)
        return EXIT_FAILURE
    submitted_by = whoami.json().get("principalId") or whoami.json().get("principal_id")
    if not submitted_by:
        print("whoami did not return a principal id", file=sys.stderr)
        return EXIT_FAILURE
    summary: dict[str, object] = {"site": args.site_id, "workArea": args.work_area_id, "cycles": {}}
    blocked: list[str] = []

    def step(label: str, response: httpx.Response) -> httpx.Response:
        print(f"[{label}] {response.status_code} {response.text[:300]}")
        return response

    for label, (ortho, dsm, capture) in cycles.items():
        data = {"ortho": ortho.read_bytes()}
        if dsm is not None:
            data["dsm"] = dsm.read_bytes()
        order = step(
            f"{label} work-order",
            client.post(
                f"{args.core_url}/v1/sites/{args.site_id}/observation-work-orders",
                headers={**headers, "Idempotency-Key": f"f04-2cycle-{args.site_id}-{label}"},
                json={
                    "name": f"F-04 two-cycle {label} (synthetic)",
                    "workAreaIds": [args.work_area_id],
                    "executionMode": "EXTERNAL_RECONSTRUCTION",
                },
            ),
        )
        if order.status_code >= 300:
            print(f"[{label}] work order create failed", file=sys.stderr)
            return EXIT_FAILURE
        work_order_id = order.json()["workOrderId"]
        context = step(
            f"{label} context",
            client.get(
                f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                "/external-reconstruction-context",
                headers=headers,
            ),
        )
        if context.status_code != 200:
            print(f"[{label}] context read failed", file=sys.stderr)
            return EXIT_FAILURE
        epoch = context.json()["expectedEpochId"]
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        candidate = {
            "contractVersion": "external-reconstruction-submission.v1",
            "submissionId": f"f04-2cycle-{label}-submission",
            "revision": 1,
            "organizationId": args.organization_id,
            "siteId": args.site_id,
            "observationEpochId": epoch,
            "submittedAt": now,
            "submittedBy": submitted_by,
            "executionResponsibility": "customer_operator",
            "executionLocus": "customer_workstation",
            "producerDeclaration": {
                "softwareName": "F-04 two-cycle rehearsal (synthetic)",
                "softwareVersion": "0.0.1",
                "buildIdentifier": None,
                "producerRunIdentifier": None,
                "configurationDigest": None,
                "completedAt": None,
            },
            "inputDeclaration": {
                "rawMediaStoredByKsi": False,
                "originalRetentionLocus": "customer_workstation",
                "localInputManifestDigest": None,
                "imageCount": None,
                "captureStartedAt": capture[0],
                "captureEndedAt": capture[1],
            },
            "artifacts": [
                *[artifact("ortho", data["ortho"], crs=args.declared_crs, file_name=ortho.name)],
                *(
                    [artifact("dsm", data["dsm"], crs=args.declared_crs, file_name=dsm.name)]
                    if dsm is not None
                    else []
                ),
            ],
        }
        candidate["submissionDigest"] = canonical_digest(candidate)
        registered = step(
            f"{label} register",
            client.post(
                f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                "/external-reconstruction-submissions",
                headers=headers,
                json=candidate,
            ),
        )
        reused_sealed = False
        if registered.status_code == 201:
            submission_ref = registered.json()["submissionRef"]
        elif registered.status_code in (200, 409):
            existing = client.get(
                f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                "/external-reconstruction-submissions",
                headers=headers,
            )
            prior = next(
                (
                    item
                    for item in existing.json()["submissions"]
                    if item["submission"].get("submissionId") == candidate["submissionId"]
                    and item["submission"].get("revision") == 1
                ),
                None,
            )
            if prior is None:
                print(
                    f"[{label}] register conflict without an existing submission",
                    file=sys.stderr,
                )
                return EXIT_FAILURE
            submission_ref = prior["submissionRef"]
            reused_sealed = prior["state"] == "SEALED"
            print(f"[{label}] register reuse {submission_ref} state={prior['state']}")
        else:
            print(f"[{label}] register failed", file=sys.stderr)
            return EXIT_FAILURE
        if reused_sealed:
            sealed_state = "SEALED"
            print(f"[{label}] seal reuse (already SEALED)")
        else:
            grants = step(
                f"{label} upload-grants",
                client.post(
                    f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                    f"/external-reconstruction-submissions/{submission_ref}"
                    "/revisions/1/upload-grants",
                    headers=headers,
                ),
            )
            if grants.status_code != 200:
                print(f"[{label}] upload grants failed", file=sys.stderr)
                return EXIT_FAILURE
            for grant in grants.json()["grants"]:
                put = client.put(
                    grant["uploadUrl"],
                    content=data[grant["artifactId"]],
                    headers=grant["requiredHeaders"],
                )
                print(f"[{label} upload {grant['artifactId']}] {put.status_code}")
                if put.status_code >= 300:
                    print(f"[{label}] upload failed", file=sys.stderr)
                    return EXIT_FAILURE
            sealed = step(
                f"{label} seal",
                client.post(
                    f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                    f"/external-reconstruction-submissions/{submission_ref}/revisions/1/seal",
                    headers=headers,
                ),
            )
            if sealed.status_code != 200:
                print(f"[{label}] seal failed", file=sys.stderr)
                return EXIT_FAILURE
            sealed_state = sealed.json().get("state")
        inspection = step(
            f"{label} inspection",
            client.get(
                f"{args.core_url}/v1/observation-work-orders/{work_order_id}"
                f"/external-reconstruction-submissions/{submission_ref}/revisions/1/inspection",
                headers=headers,
            ),
        )
        payload = inspection.json() if inspection.status_code == 200 else {}
        state = (payload.get("inspection") or {}).get("state")
        if state in GATE_STATES:
            blocked.append(f"{label}: {state} — {GATE_STATES[state]}")
        summary["cycles"][label] = {  # type: ignore[index]
            "workOrderId": work_order_id,
            "submissionRef": submission_ref,
            "seal": sealed_state,
            "inspection": state,
        }

    if not args.skip_analysis:
        t0 = summary["cycles"]["t0"]  # type: ignore[index]
        t1 = summary["cycles"]["t1"]  # type: ignore[index]
        analysis = step(
            "analysis pair",
            client.post(
                f"{args.core_url}/v2/sites/{args.site_id}/work-areas/{args.work_area_id}/analyses",
                headers={**headers, "Idempotency-Key": f"f04-2cycle-pair-{args.site_id}"},
                json={
                    "baseline": {
                        "workOrderId": t0["workOrderId"],
                        "submissionRef": t0["submissionRef"],
                        "revision": 1,
                    },
                    "current": {
                        "workOrderId": t1["workOrderId"],
                        "submissionRef": t1["submissionRef"],
                        "revision": 1,
                    },
                },
            ),
        )
        if analysis.status_code == 202:
            summary["analysis"] = analysis.json().get("analysisId")
        elif analysis.status_code == 503:
            detail = analysis.json().get("detail", "ANALYSIS_ACTIVATION_UNAVAILABLE")
            blocked.append(f"analysis: 503 {detail} — analysis activation is not current")
            summary["analysis"] = f"BLOCKED:{detail}"
        else:
            summary["analysis"] = f"FAILED:{analysis.status_code}"

    summary["blocked"] = blocked
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return EXIT_BLOCKED if blocked else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
