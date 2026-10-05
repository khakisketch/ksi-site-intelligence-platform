#!/usr/bin/env python3
"""Step-4 driver: one external-reconstruction revision -> seal -> inspection over HTTP.

Deployment scope only. Drives the RUNNING candidate's real API with an OPERATOR
token: site/work-area/work-order -> context -> submission v2 -> upload grants ->
SigV4 PUT -> seal -> sealed-subject digest -> inspection read.  Writes a JSON
receipt for each phase so the operator can inspect digests before continuing.

Nothing here is product code; no store internals are touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/event-contracts/src", "packages/domain/src"):
    sys.path.insert(0, str(REPO_ROOT / _p))

import httpx  # noqa: E402

from ksi_event_contracts.external_artifact_validation import (  # noqa: E402
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_reconstruction import (  # noqa: E402
    ExternalArtifactDeclarationV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
    ExternalReconstructionSubmissionV2,
)

SITE_FRAME = {
    "crs": "EPSG:7850",
    "verticalDatum": "AHD",
    "unit": "meter",
    "transformVersion": "v1",
}


def _now_wire() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _receipt_path(args: argparse.Namespace) -> Path:
    return Path(args.out)


def _load_receipt(args: argparse.Namespace) -> dict:
    path = _receipt_path(args)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_receipt(args: argparse.Namespace, receipt: dict) -> None:
    path = _receipt_path(args)
    path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    path.chmod(0o600)


def _print_step(name: str, response: httpx.Response, limit: int = 300) -> None:
    print(f"--- {name}: HTTP {response.status_code}")
    print(response.text[:limit])


def _artifact(args: argparse.Namespace) -> ExternalArtifactDeclarationV1:
    path = Path(args.dsm)
    data = path.read_bytes()
    return ExternalArtifactDeclarationV1(
        artifact_id=args.artifact_id,
        kind=args.artifact_kind,
        file_name=path.name,
        format="GeoTIFF",
        content_type=args.content_type,
        declared_sha256=hashlib.sha256(data).hexdigest(),
        declared_size_bytes=len(data),
        declared_crs=args.declared_crs,
        declared_vertical_reference=None,
        declared_gsd_m=args.gsd,
    )


def _submission_body(args: argparse.Namespace, epoch_id: str) -> dict:
    capture_start = datetime.fromisoformat(args.capture_start.replace("Z", "+00:00"))
    body = ExternalReconstructionSubmissionV2(
        submission_id=args.submission_id,
        revision=args.revision,
        organization_id=args.organization_id,
        site_id=args.site_id,
        observation_epoch_id=epoch_id,
        submitted_at=datetime.fromisoformat(args.submitted_at.replace("Z", "+00:00")),
        submitted_by=args.submitted_by,
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name=args.producer_software,
            software_version=args.producer_version,
            build_identifier=None,
            producer_run_identifier=None,
            configuration_digest=None,
            completed_at=None,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=None,
            image_count=None,
            capture_started_at=capture_start,
            capture_ended_at=capture_start + timedelta(minutes=10),
        ),
        artifacts=(_artifact(args),),
    )
    digest = body.canonical_digest()
    sealed = body.model_copy(update={"submission_digest": digest}, deep=True)
    return json.loads(sealed.model_dump_json(by_alias=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://dgx-spark-1.tailda9552.ts.net:10102")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--phase", default="all",
                        choices=["site", "order", "context", "submit", "grants", "seal", "subject", "inspect", "all"])
    parser.add_argument("--site-id", default="site-a")
    parser.add_argument("--site-name", default="Step-4 Floreat site")
    parser.add_argument("--work-area-id", default="wa-a")
    parser.add_argument("--work-area-name", default="Floreat-f4 area")
    parser.add_argument("--work-order-name", default="step4 external reconstruction smoke")
    parser.add_argument("--organization-id", default="org-a")
    parser.add_argument("--submitted-by", default="external-operator-step4")
    parser.add_argument("--producer-software", default="Customer photogrammetry (declared)")
    parser.add_argument("--producer-version", default="2022.08")
    parser.add_argument("--capture-start", default="2022-08-24T00:00:00Z")
    parser.add_argument("--submitted-at", default="2026-10-05T00:00:00Z")
    parser.add_argument("--dsm", required=True)
    parser.add_argument("--artifact-id", default="dsm-step4")
    parser.add_argument("--artifact-kind", default="dsm", choices=["dsm", "ortho"])
    parser.add_argument("--content-type", default="application/octet-stream")
    parser.add_argument("--declared-crs", default="EPSG:7850")
    parser.add_argument("--gsd", type=float, default=0.05)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip()
    client = httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
    )
    receipt = _load_receipt(args)
    phases = {"site", "order", "context", "submit", "grants", "seal", "subject", "inspect"} \
        if args.phase == "all" else {args.phase}

    def do(phase: str) -> bool:
        return phase in phases or args.phase == "all"

    try:
        if do("site"):
            r = client.post("/v1/sites", json={
                "siteId": args.site_id,
                "name": args.site_name,
                "siteFrame": SITE_FRAME,
            })
            receipt["site"] = {"status": r.status_code, "body": r.text[:400]}
            _print_step("site", r)
            if r.status_code not in (200, 201, 409):
                return 1
            r = client.post(f"/v1/sites/{args.site_id}/work-areas", json={
                "name": args.work_area_name,
                "crs": SITE_FRAME["crs"],
                "polygon": {
                    "type": "Polygon",
                    "coordinates": [[
                        [382282.15, 6467491.25], [382539.65, 6467491.25],
                        [382539.65, 6467931.65], [382282.15, 6467931.65],
                        [382282.15, 6467491.25],
                    ]],
                },
            })
            receipt["workArea"] = {"status": r.status_code, "body": r.text[:400]}
            _print_step("work-area", r)
            if r.status_code not in (200, 201, 409):
                return 1
            if r.status_code in (200, 201):
                wa_body = r.json().get("workArea") or {}
                receipt["workAreaId"] = wa_body.get("workAreaId") or args.work_area_id
            if not receipt.get("workAreaId"):
                r2 = client.get(f"/v1/sites/{args.site_id}/work-areas")
                items = r2.json().get("items") or r2.json().get("workAreas") or []
                for item in items:
                    if item.get("name") == args.work_area_name:
                        receipt["workAreaId"] = item.get("workAreaId")

        if do("order"):
            r = client.post(
                f"/v1/sites/{args.site_id}/observation-work-orders",
                json={
                    "name": args.work_order_name,
                    "workAreaIds": [receipt.get("workAreaId") or args.work_area_id],
                    "executionMode": "EXTERNAL_RECONSTRUCTION",
                },
                headers={"Idempotency-Key": f"step4-{args.submission_id}"},
            )
            receipt["workOrder"] = {"status": r.status_code, "body": r.text[:600]}
            _print_step("work-order", r, 600)
            if r.status_code in (200, 201):
                body = r.json()
                receipt["workOrderId"] = body.get("workOrderId") or body.get("work_order_id")
            elif r.status_code == 409:
                # find the existing work order by name
                r2 = client.get("/v1/observation-work-orders")
                items = r2.json().get("items") or r2.json().get("workOrders") or []
                for item in items:
                    if item.get("name") == args.work_order_name:
                        receipt["workOrderId"] = item.get("workOrderId") or item.get("work_order_id")
            if not receipt.get("workOrderId"):
                print("work order id unresolved")
                return 1

        work_order_id = receipt.get("workOrderId")
        if do("context"):
            r = client.get(f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-context")
            receipt["context"] = {"status": r.status_code, "body": r.text[:600]}
            _print_step("context", r, 600)
            if r.status_code != 200:
                return 1
            body = r.json()
            receipt["epochId"] = body.get("expectedEpochId") or body.get("expected_epoch_id")
            if not receipt.get("epochId"):
                return 1

        if do("submit"):
            body = _submission_body(args, receipt["epochId"])
            receipt["submissionBody"] = body
            r = client.post(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v2",
                json=body,
            )
            receipt["submission"] = {"status": r.status_code, "body": r.text[:600]}
            _print_step("submission", r, 600)
            if r.status_code not in (200, 201):
                return 1
            response = r.json()
            receipt["submissionRef"] = (
                response.get("submissionRef") or response.get("submissionId")
                or response.get("submission_ref") or args.submission_id
            )

        submission_ref = receipt.get("submissionRef") or args.submission_id
        revision = args.revision
        if do("grants"):
            r = client.post(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
                f"{submission_ref}/revisions/{revision}/upload-grants"
            )
            receipt["grants"] = {"status": r.status_code, "body": r.text[:800]}
            _print_step("upload-grants", r, 800)
            if r.status_code not in (200, 201):
                return 1
            grants = r.json().get("grants") or []
            if len(grants) != 1:
                print(f"expected exactly one grant, got {len(grants)}")
                return 1
            grant = grants[0]
            data = Path(args.dsm).read_bytes()
            put = httpx.put(grant["uploadUrl"], content=data,
                            headers={k: v for k, v in grant["requiredHeaders"].items()},
                            timeout=600.0)
            receipt["put"] = {"status": put.status_code, "body": put.text[:300]}
            _print_step("object PUT", put)
            if put.status_code not in (200, 201):
                return 1

        if do("seal"):
            r = client.post(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
                f"{submission_ref}/revisions/{revision}/seal"
            )
            receipt["seal"] = {"status": r.status_code, "body": r.text[:1200]}
            _print_step("seal", r, 1200)
            if r.status_code not in (200, 201):
                return 1
            view = r.json()
            submission = view.get("submission") or {}
            manifest = view.get("manifest") or {}
            receipt["submissionDigest"] = submission.get("submissionDigest") or submission.get("submission_digest")
            receipt["manifestDigest"] = manifest.get("manifestDigest") or manifest.get("manifest_digest")

        if do("subject"):
            subject = SealedExternalSubjectV1(
                organization_id=args.organization_id,
                site_id=args.site_id,
                work_order_id=work_order_id,
                submission_id=args.submission_id,
                revision=revision,
                submission_digest=receipt["submissionDigest"],
                manifest_digest=receipt["manifestDigest"],
            )
            receipt["subject"] = json.loads(subject.model_dump_json(by_alias=True))
            receipt["subjectDigest"] = subject.canonical_digest()
            subjects_path = _receipt_path(args).with_suffix(".subjects.json")
            subjects_path.write_text(json.dumps([receipt["subject"]], indent=1) + "\n")
            subjects_path.chmod(0o600)
            print("--- sealed subject:")
            print(json.dumps({"subject": receipt["subject"], "subjectDigest": receipt["subjectDigest"]}, indent=1))
            print(f"subjects file: {subjects_path}")

        if do("inspect"):
            r = client.get(
                f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
                f"{submission_ref}/revisions/{revision}/inspection"
            )
            receipt["inspection"] = {"status": r.status_code, "body": r.text[:2000]}
            _print_step("inspection", r, 2000)

        _save_receipt(args, receipt)
        print(f"receipt: {_receipt_path(args)}")
        return 0
    finally:
        _save_receipt(args, receipt)
        client.close()


if __name__ == "__main__":
    sys.exit(main())
