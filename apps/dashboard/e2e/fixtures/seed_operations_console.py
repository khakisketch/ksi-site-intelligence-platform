#!/usr/bin/env python3
"""Seed deterministic Operations Console E2E ledgers through domain stores.

The records below are browser-regression fixtures only. One synthetic,
contract-only Mission exists solely to render post-processing panels; it has
no executable route or KMZ. The fixture does not create a dispatch receipt,
processing result, spatial model, or DJI/device capability evidence. In
particular, no fixture is valid HIL or field evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore, EventVerdict, make_event_key
from ksi_core.evidence import EvidenceVerdict
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore, SiteVerdict
from ksi_core.work_areas import WorkAreaStore, WorkAreaVerdict
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus
from ksi_mission_contracts.models import SiteFrame
from ksi_mission_planning import AreaOfInterest

ORGANIZATION_ID = "org-local-pilot"
ACTOR = "operations-console-e2e-fixture"
EDGE_DEVICE_ID = "e2e-edge-fixture"
EVENT_ID = "event-open-with-evidence"
MISSION_ID = "e2e-civil-postprocessing-fixture"
SITE_IDS = (
    "e2e-site-workspace",
    "e2e-site-review",
    "e2e-site-progress",
    "e2e-site-result",
    "e2e-site-completed",
)

SITE_NAMES = {
    "e2e-site-workspace": "E2E 현장 작업공간",
    "e2e-site-review": "E2E 승인 검토 현장",
    "e2e-site-progress": "E2E 관측 진행 현장",
    "e2e-site-result": "E2E 결과 검토 현장",
    "e2e-site-completed": "E2E 관측 완료 현장",
}

SYNTHETIC_EVIDENCE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _event_bundle(*, status: str) -> dict[str, object]:
    fingerprint = "a" * 64
    return {
        "schemaVersion": "1.2",
        "eventId": EVENT_ID,
        "missionId": "e2e-nonflight-observation-fixture",
        "siteId": "e2e-site-workspace",
        "eventType": "PERSON_PRESENT",
        "occurredAt": "2026-08-25T00:40:00Z",
        "status": status,
        "severity": "MEDIUM",
        "entities": ["ent-e2e-001"],
        "spatialContext": {"zone": "E2E 작업구역 1"},
        "reasoning": {"fixture": "browser-regression-only"},
        "evidence": {},
        "lineage": {
            "edgeVersion": "e2e-fixture-1.0",
            "modelVersions": {"detector": "synthetic-not-verified"},
            "policyVersion": "e2e-fixture-policy-1",
            "calibrationProfileId": "e2e-fixture-calibration-1",
            "classification": {
                "ent-e2e-001": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": fingerprint,
                }
            },
        },
    }


def seed(
    data_dir: Path,
    *,
    enable_synthetic_ai_egress: bool = False,
    s3_endpoint: str | None = None,
    s3_bucket: str | None = None,
) -> None:
    if (s3_endpoint is None) != (s3_bucket is None):
        raise ValueError("s3_endpoint and s3_bucket must be configured together")
    data_dir.mkdir(parents=True, exist_ok=True)
    journal_paths = {
        "sites": data_dir / "sites.jsonl",
        "work_areas": data_dir / "work-areas.jsonl",
        "work_orders": data_dir / "observation-work-orders.jsonl",
        "events": data_dir / "events.jsonl",
        "missions": data_dir / "missions.jsonl",
    }
    occupied = [
        str(path)
        for path in journal_paths.values()
        if path.exists() and path.stat().st_size
    ]
    if occupied:
        raise RuntimeError(
            "E2E fixture seeding requires empty ledgers; refusing to mix with existing data: "
            + ", ".join(occupied)
        )

    journals = {name: DurableJournal(path) for name, path in journal_paths.items()}
    try:
        site_store = SiteStore(journals["sites"])
        work_area_store = WorkAreaStore(
            journals["work_areas"], site_exists=lambda site_id: site_store.get(site_id) is not None
        )
        work_order_store = ObservationWorkOrderStore(
            journals["work_orders"],
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
            work_areas_exist=lambda site_id, area_ids: all(
                (area := work_area_store.get(area_id)) is not None and area.site_id == site_id
                for area_id in area_ids
            ),
        )
        event_store = EventStore(journals["events"])
        mission_store = MissionStore(journals["missions"])

        started_at = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
        frame = SiteFrame(
            crs="EPSG:5186",
            vertical_datum="KNGeoid2018",
            unit="meter",
            transform_version="1.0.0",
        )

        work_area_ids: dict[str, str] = {}
        for index, site_id in enumerate(SITE_IDS):
            now = started_at + timedelta(minutes=index)
            origin = 127.0 + index * 0.01
            aoi = AreaOfInterest.model_validate(
                {
                    "vertices": [
                        {"latDeg": 37.5, "lonDeg": origin},
                        {"latDeg": 37.5, "lonDeg": origin + 0.001},
                        {"latDeg": 37.501, "lonDeg": origin + 0.001},
                        {"latDeg": 37.501, "lonDeg": origin},
                    ]
                }
            )
            site_result = site_store.register(
                site_id,
                SITE_NAMES[site_id],
                frame,
                aoi=aoi,
                ai_egress_allowed=(
                    enable_synthetic_ai_egress and site_id == "e2e-site-workspace"
                ),
                organization_id=ORGANIZATION_ID,
                actor=ACTOR,
                now=now,
            )
            assert site_result.verdict is SiteVerdict.REGISTERED

            area_result = work_area_store.register(
                site_id,
                name=f"E2E 작업구역 {index + 1}",
                crs="EPSG:4326",
                polygon={
                    "type": "Polygon",
                    "coordinates": [[
                        [origin, 37.5],
                        [origin + 0.001, 37.5],
                        [origin + 0.001, 37.501],
                        [origin, 37.501],
                        [origin, 37.5],
                    ]],
                },
                supersedes=None,
                actor=ACTOR,
                now=now + timedelta(seconds=5),
            )
            assert area_result.verdict is WorkAreaVerdict.REGISTERED
            assert area_result.work_area is not None
            work_area_ids[site_id] = area_result.work_area.work_area_id

            if site_id != "e2e-site-review":
                transition = site_store.transition(
                    site_id,
                    SiteStatus.BASELINE_MAPPING,
                    evidence="e2e-fixture://baseline-mapping-started",
                    reason="브라우저 회귀에서 초기 설정 이후 상태를 검증하는 합성 전이",
                    actor=ACTOR,
                    now=now + timedelta(seconds=10),
                )
                assert transition.verdict is SiteVerdict.TRANSITIONED

        # UI-only post-processing fixture. It deliberately has no route, KMZ,
        # dispatch, or device assignment and therefore cannot be executed.
        assert (
            mission_store.record_issuance(
                MissionRecord(
                    mission_id=MISSION_ID,
                    site_id="e2e-site-workspace",
                    mission_type="BASELINE_MAPPING",
                    artifact_kind="contract",
                    contract={"schemaVersion": "1.2", "missionId": MISSION_ID},
                    kmz_sha256=None,
                    route_pattern=None,
                    waypoint_count=None,
                    planned_coverage_ratio=None,
                    issued_at=started_at + timedelta(minutes=9),
                    issued_by=ACTOR,
                    organization_id=ORGANIZATION_ID,
                    assigned_device_id=None,
                )
            )
            is MissionRecordVerdict.RECORDED
        )

        order_statuses = (
            ("e2e-site-review", "E2E 작업 범위 승인", ObservationWorkOrderStatus.AWAITING_APPROVAL),
            ("e2e-site-progress", "E2E 승인된 관측 작업", ObservationWorkOrderStatus.APPROVED),
            ("e2e-site-result", "E2E 결과와 근거 검토", ObservationWorkOrderStatus.REVIEW_READY),
            ("e2e-site-completed", "E2E 완료된 관측 작업", ObservationWorkOrderStatus.COMPLETED),
        )
        monotonic_path = (
            ObservationWorkOrderStatus.DISPATCHED,
            ObservationWorkOrderStatus.START_REPORTED,
            ObservationWorkOrderStatus.MEDIA_RECEIVING,
            ObservationWorkOrderStatus.PROCESSING,
            ObservationWorkOrderStatus.REVIEW_READY,
            ObservationWorkOrderStatus.COMPLETED,
        )
        for index, (site_id, name, target) in enumerate(order_statuses):
            now = started_at + timedelta(minutes=10 + index)
            order = work_order_store.create_work_order(
                organization_id=ORGANIZATION_ID,
                site_id=site_id,
                name=name,
                work_area_ids=[work_area_ids[site_id]],
                schedule_id=None,
                actor=ACTOR,
                now=now,
            )
            if target is ObservationWorkOrderStatus.AWAITING_APPROVAL:
                continue
            order = work_order_store.approve(
                order.work_order_id,
                organization_id=ORGANIZATION_ID,
                expected_version=order.version,
                actor=ACTOR,
                now=now + timedelta(seconds=5),
            )
            if target is ObservationWorkOrderStatus.APPROVED:
                continue
            for step, status in enumerate(monotonic_path, start=1):
                order = work_order_store.record_status(
                    order.work_order_id,
                    organization_id=ORGANIZATION_ID,
                    status=status,
                    status_reason="합성 E2E 상태 전이이며 운영·장비 증거가 아님",
                    mission_ids=[],
                    processing_job_ids=[],
                    report_refs=[],
                    actor=ACTOR,
                    now=now + timedelta(seconds=5 + step),
                )
                if status is target:
                    break
            assert order.status is target

        received_at = started_at + timedelta(minutes=40)
        for expected, status in (
            (EventVerdict.PROJECTED, "CANDIDATE"),
            (EventVerdict.EVENT_UPDATED, "EVIDENCE_COLLECTION"),
            (EventVerdict.EVENT_UPDATED, "FINDING"),
        ):
            assert (
                event_store.project_bundle(
                    _event_bundle(status=status),
                    edge_device_id=EDGE_DEVICE_ID,
                    received_at=received_at,
                    organization_id=ORGANIZATION_ID,
                )
                is expected
            )
            received_at += timedelta(seconds=1)

        evidence_digest = (
            f"sha256:{hashlib.sha256(SYNTHETIC_EVIDENCE_BYTES).hexdigest()}"
            if s3_endpoint is not None
            else None
        )
        evidence = event_store.register_evidence(
            event_key=make_event_key(EDGE_DEVICE_ID, EVENT_ID),
            artifact_id="e2e-evidence-image-001",
            content_type="image/png",
            registered_by=ACTOR,
            now=received_at,
            content_digest=evidence_digest,
            organization_id=ORGANIZATION_ID,
        )
        assert evidence.verdict is EvidenceVerdict.REGISTERED
        assert evidence.artifact is not None
        if s3_endpoint is not None and s3_bucket is not None:
            import boto3  # noqa: PLC0415 -- only the S3-backed staging fixture needs it
            from botocore.config import Config  # noqa: PLC0415 -- same boundary as above

            client = boto3.client(
                "s3",
                endpoint_url=s3_endpoint,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            client.put_object(
                Bucket=s3_bucket,
                Key=evidence.artifact.object_key,
                Body=SYNTHETIC_EVIDENCE_BYTES,
                ContentType="image/png",
            )
    finally:
        for journal in journals.values():
            journal.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--enable-synthetic-ai-egress", action="store_true")
    parser.add_argument("--s3-endpoint")
    parser.add_argument("--s3-bucket")
    args = parser.parse_args()
    seed(
        args.data_dir.resolve(),
        enable_synthetic_ai_egress=args.enable_synthetic_ai_egress,
        s3_endpoint=args.s3_endpoint,
        s3_bucket=args.s3_bucket,
    )


if __name__ == "__main__":
    main()
