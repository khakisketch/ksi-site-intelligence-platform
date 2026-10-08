#!/usr/bin/env python3
"""Seed deterministic platform Site/WorkArea/WorkOrder fixtures for the Console e2e.

Browser-regression fixtures only: five synthetic sites and work areas cover the
surviving platform surfaces. Four explicitly historical managed-mode records
remain read-only fixtures for fail-closed detail coverage; one external
reconstruction work order covers the mounted registration and operations UI.
Nothing here is valid HIL, field, accuracy, settlement or operations evidence.

P4 cleanup: ``SiteFrame``/``AreaOfInterest`` come from the neutral owners and no
archived module is imported.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore, SiteVerdict
from ksi_core.work_areas import WorkAreaStore, WorkAreaVerdict
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrderExecutionMode,
    ObservationWorkOrderStatus,
)
from ksi_event_contracts.site_frame import SiteFrame
from ksi_geo_core.aoi import AreaOfInterest

ORGANIZATION_ID = "org-local-pilot"
ACTOR = "operations-console-e2e-fixture"
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


def seed(
    data_dir: Path,
    *,
    enable_synthetic_ai_egress: bool = False,
    s3_endpoint: str | None = None,
    s3_bucket: str | None = None,
) -> None:
    if (s3_endpoint is None) != (s3_bucket is None):
        raise ValueError("s3_endpoint and s3_bucket must be configured together")
    # S3 staging existed only for the retired event-evidence fixture; keep the
    # flags accepted so the local OIDC stack invocation stays compatible.
    del s3_endpoint, s3_bucket
    data_dir.mkdir(parents=True, exist_ok=True)
    journal_paths = {
        "sites": data_dir / "sites.jsonl",
        "work_areas": data_dir / "work-areas.jsonl",
        "work_orders": data_dir / "observation-work-orders.jsonl",
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

        order_statuses = (
            ("e2e-site-review", "E2E 과거 읽기 전용 · 작업 범위 승인", ObservationWorkOrderStatus.AWAITING_APPROVAL),
            ("e2e-site-progress", "E2E 과거 읽기 전용 · 승인 기록", ObservationWorkOrderStatus.APPROVED),
            ("e2e-site-result", "E2E 과거 읽기 전용 · 결과 검토 기록", ObservationWorkOrderStatus.REVIEW_READY),
            ("e2e-site-completed", "E2E 과거 읽기 전용 · 완료 기록", ObservationWorkOrderStatus.COMPLETED),
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

        # This is the only executable platform-flow fixture: the store creates an
        # APPROVED external order and its OPEN operations record atomically.
        # Do not call managed approve/record_status or fabricate a result.
        work_order_store.create_work_order(
            organization_id=ORGANIZATION_ID,
            site_id="e2e-site-workspace",
            name="E2E 외부 산출물 등록",
            work_area_ids=[work_area_ids["e2e-site-workspace"]],
            schedule_id=None,
            execution_mode=ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION,
            idempotency_key="operations-console-e2e-external-work-order-v1",
            actor=ACTOR,
            now=started_at + timedelta(minutes=20),
        )
    finally:
        for journal in journals.values():
            journal.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--enable-synthetic-ai-egress", action="store_true")
    parser.add_argument("--s3-endpoint", default=None)
    parser.add_argument("--s3-bucket", default=None)
    args = parser.parse_args()
    seed(
        args.data_dir,
        enable_synthetic_ai_egress=args.enable_synthetic_ai_egress,
        s3_endpoint=args.s3_endpoint,
        s3_bucket=args.s3_bucket,
    )


if __name__ == "__main__":
    main()
