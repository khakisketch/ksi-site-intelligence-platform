"""체적 리포트 테스트가 공유하는 조립 헬퍼.

``test_volume_reports_api`` 와 ``test_volume_change_end_to_end`` 가 같은 현장·
임무·산출물 조립을 쓴다. 한쪽에 두고 flat import 로 끌어오면 ruff/mypy 가 그
경로를 해석하지 못해(테스트 디렉터리는 패키지가 아니다), 조립을 복제하거나
게이트를 우회하게 된다 — ``_site_lifecycle.py`` 와 같은 자리에 둔다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    ArtifactSpec,
    JobSpec,
    ProcessingJobStatus,
    ProcessingJobStore,
    ProcessingJobVerdict,
)
from ksi_core.sites import SiteFrame, SiteStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaStore
from ksi_event_contracts.processing_artifact import LineageAuthority, ProcessingArtifactKind
from ksi_event_contracts.processing_job import ExecutionLocus, LicenseBasis, ProcessingProvider

_WORKER_TOKEN = "processing-worker-token"  # noqa: S105 — 테스트 고정값
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_MISSION_ID = "mission-vc-1"
_SITE_ID = "site-vc-001"
_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)
_NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _mission_store(tmp_path: Path, *, path: str = "missions.jsonl") -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="BASELINE_MAPPING",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="op-1",
            )
        ).value
        == "RECORDED"
    )
    return store


def _sealed_bundles(tmp_path: Path) -> SourceMediaStore:
    # journal 은 단일 writer 잠금이라 임무 원장을 별도 경로로 연다
    # (test_change_detection_api.py 와 같은 관용구).
    store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"),
        mission_store=_mission_store(tmp_path, path="m-source.jsonl"),
    )
    claims = [
        SourceMediaClaim(
            media_id=f"img-{i:03d}.jpg",
            sha256=hashlib.sha256(f"img-{i}".encode()).hexdigest(),
            size_bytes=1_000_000,
            width=4000,
            height=3000,
            content_type="image/jpeg",
        )
        for i in range(3)
    ]
    assert (
        store.register_batch(_MISSION_ID, claims, registered_by="op-1", now=_NOW).verdict.value
        == "PROCESSED"
    )
    assert store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    return store


def _job_store(tmp_path: Path, journal: DurableJournal) -> ProcessingJobStore:
    sites = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert (
        sites.register(
            _SITE_ID, "테스트 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
        ).verdict.value
        == "REGISTERED"
    )
    return ProcessingJobStore(
        journal, source_media_store=_sealed_bundles(tmp_path), site_store=sites
    )


def _job_spec() -> JobSpec:
    return JobSpec(
        provider=ProcessingProvider.ODM,
        engine_version="3.5.4",
        engine_digest="sha256:" + "a" * 64,
        execution_locus=ExecutionLocus.KSI_SERVER_GPU,
        license_basis=LicenseBasis(
            license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
        ),
        processing_params={"quality": "high"},
    )


def _artifact_spec(
    artifact_id: str, *, kind: ProcessingArtifactKind = ProcessingArtifactKind.DSM
) -> ArtifactSpec:
    raster = kind in {
        ProcessingArtifactKind.DSM,
        ProcessingArtifactKind.DTM,
        ProcessingArtifactKind.ORTHO,
    }
    return ArtifactSpec(
        artifact_id=artifact_id,
        kind=kind,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        digest="sha256:" + hashlib.sha256(artifact_id.encode()).hexdigest(),
        format="tif" if raster else "laz",
        crs="EPSG:5186",
        gsd=0.05 if raster else None,
        accuracy=None,
    )


def _job_with_artifacts(jobs: ProcessingJobStore, *artifact_specs: ArtifactSpec) -> str:
    record = jobs.issue(_MISSION_ID, _job_spec(), issued_by="op-1", now=_NOW).record
    assert record is not None
    assert jobs.acquire_lease(record.job_id, worker_id="w-1", now=_NOW).verdict in {
        ProcessingJobVerdict.LEASED,
        ProcessingJobVerdict.LEASE_RENEWED,
    }
    assert (
        jobs.transition(
            record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    for spec in artifact_specs:
        result = jobs.register_artifact(record.job_id, spec, registered_by="w-1", now=_NOW)
        assert result.verdict is ProcessingJobVerdict.ARTIFACT_REGISTERED, result
    return record.job_id
