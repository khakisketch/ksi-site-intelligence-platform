"""Phase 2 통합 여정 E2E (PHASE_REGISTRY.yaml phase-2 acceptance).

phase-2 완료기준 1번 — "현장 Onboarding→Baseline Processing→Verified Flight
Volume 상태 전이 실통과 (INV-010)" — 을 문자 그대로 증명한다.

## 왜 이 파일이 필요한가

``test_s2_e2e.py`` 는 Site 10상태 머신을 UNMAPPED→PATROL_READY 까지 왕복시키지만
``SiteStore.transition()`` 을 운영자 evidence 문자열만으로 호출한다 — 실제로
사진이 올라왔는지, 처리 작업이 성공했는지, 커버리지가 INV-010 을 통과했는지는
그 테스트가 검사하지 않는다(``sites.py`` ``set_aoi`` 모듈 docstring 이 이미
명시하듯, Site 상태전이 자체는 의도적으로 다른 저장소를 참조하지 않는 설계다 —
"AOI_LOCKED 는 이미 발급된 임무·누적 중인 커버리지와의 대조가 무너지는 것을
막는 게 아니다 — 그런 대조 자체가 코드에 없다").

반대로 ``test_processing_jobs.py``/``test_coverage_reports.py`` 는 각자의 저장소
(``ProcessingJobStore``/``CoverageReportStore``)를 단독으로 검증하고, 서로 다른
site_id/mission_id 픽스처를 쓴다 — 두 저장소가 **같은 site·mission 위에서**
실제로 조립되는 시나리오는 어느 파일도 통과시키지 않는다.

이 파일은 그 공백을 닫는다: 하나의 site_id·mission_id 위에서 (1) Onboarding
(site 등록 — 상태 머신은 UNMAPPED 시작), (2) 실제 원본 사진 번들 업로드·봉인·
실측 대조(B1), (3) 실제 처리 작업 발급·lease·RUNNING·원본 산출물 등록·SUCCEEDED
(B2/B3, INV-051), (4) 실제 CoverageReport 접수·INV-010 판정 — **정직하지 못한
완료 주장(사유 없는 미관찰 Cell 을 남긴 채 COMPLETED)은 먼저 거부되고, 그
다음에야 실제로 임계를 만족하는 보고가 RECORDED 된다** — 을 전부 실행한 뒤에야
Site 상태를 BASELINE_MAPPING→MODEL_PROCESSING→MODEL_VALIDATION→
PROVISIONAL_AUTONOMY→PATROL_READY("Verified Flight Volume")로 전이시킨다.
각 site 전이는 HTTP 계층(``mount_sites``)을 통과시켜 SITES_AUTONOMY_APPROVE
권한 게이트(ADR-KSI-015 D2 — 자율 시작·정식 순찰 승인은 FIELD_OPERATOR 로는
막힌다)도 이 시나리오 안에서 실제로 작동함을 함께 고정한다.

이 테스트는 **자동 결합을 주장하지 않는다** — Site 상태 전이가 ProcessingJob·
CoverageReport 저장소를 자동으로 조회해 막는 코드는 없다(설계상 그렇다, 위
docstring 참조). 증명하는 것은 "그 결합을 사람이 손으로 구성했을 때, 각 단계의
실제 게이트가 전부 살아서 작동하고, 최종 상태 전이 자체가 실제로 통과하는가"다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.coverage_reports import CoverageReportStore, CoverageReportVerdict
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict, MissionStore
from ksi_core.processing_jobs import ArtifactSpec, JobSpec, ProcessingJobStore, ProcessingJobVerdict
from ksi_core.sites import SiteStore, mount_sites
from ksi_core.source_media import (
    SourceBundleVerifyVerdict,
    SourceMediaClaim,
    SourceMediaMeasurement,
    SourceMediaStore,
)
from ksi_event_contracts.coverage_report import CoverageReport
from ksi_event_contracts.processing_artifact import LineageAuthority, ProcessingArtifactKind
from ksi_event_contracts.processing_job import (
    ExecutionLocus,
    LicenseBasis,
    ProcessingJobStatus,
    ProcessingProvider,
)
from ksi_mission_contracts.models import SiteFrame

_SITE_ID = "site-phase2-journey-001"
_MISSION_ID = "mission-phase2-journey-001"
_NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)

_ADMIN_TOKEN = "phase2-journey-admin"  # noqa: S105 -- 테스트 고정값
_FIELD_OPERATOR_TOKEN = "phase2-journey-field-operator"  # noqa: S105

_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="fo-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
        ]
    )


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _claim(media_id: str) -> SourceMediaClaim:
    return SourceMediaClaim(
        media_id=media_id,
        sha256=_sha(media_id),
        size_bytes=2_500_000,
        width=5472,
        height=3648,
        content_type="image/jpeg",
    )


def _job_spec() -> JobSpec:
    return JobSpec(
        provider=ProcessingProvider.ODM,
        engine_version="3.5.4",
        engine_digest="sha256:" + "b" * 64,
        execution_locus=ExecutionLocus.KSI_SERVER_GPU,
        license_basis=LicenseBasis(
            license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
        ),
        processing_params={"quality": "high"},
    )


def _coverage_report(
    *,
    completion: str,
    hazard: float,
    asset: float,
    general: float,
    cells: list[dict[str, object]],
) -> CoverageReport:
    return CoverageReport.model_validate(
        {
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "timestamp": "2026-08-06T02:30:00+00:00",
            "cells": cells,
            "summary": {
                "mandatoryHazardRatio": hazard,
                "mandatoryAssetRatio": asset,
                "accessibleGeneralRatio": general,
                "completionState": completion,
            },
        }
    )


def test_onboarding_through_baseline_processing_to_verified_flight_volume(
    tmp_path: Path,
) -> None:
    """phase-2 acceptance #1 — 상태 전이가 실제 산출물·보고 위에서 통과한다.

    각 단계에 "실제로 무슨 일이 있었는지"를 evidence 문자열에 남기고, 그
    evidence 가 그 단계에서 방금 만든 실제 산출물(job_id·artifact digest·
    coverage 판정)을 가리키게 해 종이 위 주장이 아님을 시각적으로도 고정한다.
    """
    # ── 조립: 도메인 표면 4개를 같은 site_id/mission_id 위에 구성한다 ──────
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    processing_job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    coverage_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )

    app = FastAPI()
    mount_auth(app, _auth_registry())
    mount_sites(app, site_store)
    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
    field_op_headers = {"Authorization": f"Bearer {_FIELD_OPERATOR_TOKEN}"}

    def transition(
        target: str, *, evidence: str, reason: str, headers: dict[str, str]
    ) -> Response:
        return client.post(
            f"/v1/sites/{_SITE_ID}/transitions",
            json={"targetStatus": target, "evidence": evidence, "reason": reason},
            headers=headers,
        )

    # ── 1) Onboarding — 현장 등록(HTTP, INV-050 반출선언 포함) ────────────
    register = client.post(
        "/v1/sites",
        json={
            "siteId": _SITE_ID,
            "name": "Phase 2 통합 여정 현장",
            "siteFrame": _SITE_FRAME.model_dump(by_alias=True, mode="json"),
            "dataResidency": {"egressAllowed": False, "jurisdiction": "KR"},
        },
        headers=field_op_headers,
    )
    assert register.status_code == 201, register.text
    assert register.json()["site"]["status"] == "UNMAPPED"

    # BASELINE_MAPPING 임무는 site 가 UNMAPPED 인 지금만 발급 가능하다(INV-052,
    # ksi_domain.mission_gating). 서명·KMZ 계층은 S1(mission-geometry-route)이
    # 이미 별도로 검증하므로 여기서는 record_issuance 로 영속만 재현한다
    # (test_processing_jobs.py/test_coverage_reports.py 의 공유 fixture 관습과
    # 동일 — mission_store 는 저 두 저장소의 게이트가 실제로 읽는 대상이다).
    assert (
        mission_store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="BASELINE_MAPPING",
                artifact_kind="pair",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256="deadbeefcafe",
                route_pattern="lawnmower",
                waypoint_count=64,
                planned_coverage_ratio=1.0,
                issued_at=_NOW,
                issued_by="fo-1",
            )
        )
        is MissionRecordVerdict.RECORDED
    )

    transitioned = transition(
        "BASELINE_MAPPING",
        evidence=f"BASELINE_MAPPING 임무 {_MISSION_ID} 발급 완료 — 현장 매핑 비행 개시",
        reason="최초 현장 매핑 개시(§6.1)",
        headers=field_op_headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["site"]["status"] == "BASELINE_MAPPING"

    # ── 2) Baseline Processing 전제 — 실제 원본 사진 번들(B1) ─────────────
    claims = [_claim(f"DJI_{i:04d}.JPG") for i in range(24)]
    registered = source_media_store.register_batch(
        _MISSION_ID, claims, registered_by="fo-1", now=_NOW
    )
    assert registered.verdict.value == "PROCESSED"
    sealed = source_media_store.seal(_MISSION_ID, sealed_by="fo-1", now=_NOW)
    assert sealed.verdict.value == "SEALED"

    bundle = source_media_store.get(_MISSION_ID)
    assert bundle is not None
    measurements = [
        SourceMediaMeasurement(
            media_id=m.media_id, sha256=m.sha256, size_bytes=m.size_bytes,
            width=m.width, height=m.height,
        )
        for m in bundle.media
    ]
    verified = source_media_store.verify(
        _MISSION_ID, measurements, verified_by="worker-1", now=_NOW
    )
    assert verified.verdict is SourceBundleVerifyVerdict.VERIFIED

    # ── 3) Baseline Processing 본체 — 실제 처리 작업(B2/B3, INV-051) ──────
    issued = processing_job_store.issue(_MISSION_ID, _job_spec(), issued_by="fo-1", now=_NOW)
    assert issued.verdict is ProcessingJobVerdict.ISSUED
    job = issued.record
    assert job is not None
    job_id = job.job_id

    assert processing_job_store.acquire_lease(
        job_id, worker_id="worker-1", now=_NOW
    ).verdict is ProcessingJobVerdict.LEASED
    assert processing_job_store.transition(
        job_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    ).verdict is ProcessingJobVerdict.TRANSITIONED

    artifact_digest = "sha256:" + "c" * 64
    registered_artifact = processing_job_store.register_artifact(
        job_id,
        ArtifactSpec(
            artifact_id="pointcloud",
            kind=ProcessingArtifactKind.POINT_CLOUD,
            authority=LineageAuthority.SOURCE,
            derived_from=(),
            digest=artifact_digest,
            format="laz",
            crs="EPSG:5186",
            gsd=None,
            accuracy=None,
        ),
        registered_by="worker-1",
        now=_NOW,
    )
    assert registered_artifact.verdict is ProcessingJobVerdict.ARTIFACT_REGISTERED

    succeeded = processing_job_store.transition(
        job_id, ProcessingJobStatus.SUCCEEDED, detail="ODM 재구성 완료", actor="worker-1", now=_NOW
    )
    assert succeeded.verdict is ProcessingJobVerdict.TRANSITIONED  # INV-051 게이트 실제 통과

    transitioned = transition(
        "MODEL_PROCESSING",
        evidence=(
            f"처리 작업 {job_id} 발급·실행 시작 — 원본 사진 {len(claims)}장 실측 대조 통과"
        ),
        reason="원본 사진 봉인 완료, 3D 재구성 개시",
        headers=field_op_headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["site"]["status"] == "MODEL_PROCESSING"

    # ── 4) Verified Flight Volume 전제 — 실제 CoverageReport(INV-010) ─────
    # 4a) 정직하지 못한 완료 주장(사유 없는 미관찰 Cell 을 남긴 COMPLETED)은
    #     실제로 거부된다 — "검증됐다"는 evidence 를 남기기 전에 INV-010 이
    #     그 주장 자체를 걸러낸다는 것을 이 시나리오 안에서 고정한다.
    dishonest = _coverage_report(
        completion="COMPLETED",
        hazard=1.0,
        asset=1.0,
        general=1.0,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "NOT_OBSERVED"},  # 사유 없는 미관찰
        ],
    )
    dishonest_result = coverage_store.record(dishonest, now=_NOW)
    assert dishonest_result.verdict is CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY
    assert coverage_store.latest(_MISSION_ID) is None  # 거부된 보고는 기록되지 않는다

    # 4b) 실제로 임계를 만족하고 미관찰 Cell 에 원인코드가 붙은 정직한 보고만
    #     RECORDED 된다 — 이 판정이 "Verified Flight Volume" 의 실제 근거다.
    honest = _coverage_report(
        completion="COMPLETED",
        hazard=1.0,
        asset=1.0,
        general=0.97,
        cells=[
            {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
            {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            {"cellId": "c-3", "state": "OCCLUDED"},  # 사유 있는 미관찰 — 완료를 막지 않는다
        ],
    )
    honest_result = coverage_store.record(honest, now=_NOW, reported_by="edge-001")
    assert honest_result.verdict is CoverageReportVerdict.RECORDED
    assert coverage_store.latest(_MISSION_ID) is not None

    transitioned = transition(
        "MODEL_VALIDATION",
        evidence=(
            f"처리 작업 {job_id} SUCCEEDED(원본 산출물 {artifact_digest}) — "
            "CoverageReport RECORDED(위험구역 1.0·자산 1.0·일반영역 0.97, INV-010 통과)"
        ),
        reason="3D 재구성 완료 + 비행후 커버리지 보고 접수, 품질 검증 개시",
        headers=field_op_headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["site"]["status"] == "MODEL_VALIDATION"

    # ── 5) 자율 승인 게이트(ADR-KSI-015 D2) — FIELD_OPERATOR 는 막힌다 ─────
    denied = transition(
        "PROVISIONAL_AUTONOMY",
        evidence="품질 검증 통과",
        reason="자율 시작 승인 시도(권한 없음)",
        headers=field_op_headers,
    )
    assert denied.status_code == 403, denied.text
    # 거부됐으므로 상태는 그대로다(부분 적용 없음).
    still_validation = client.get(f"/v1/sites/{_SITE_ID}", headers=field_op_headers)
    assert still_validation.json()["status"] == "MODEL_VALIDATION"

    approved = transition(
        "PROVISIONAL_AUTONOMY",
        evidence=f"CoverageReport RECORDED + 처리 작업 {job_id} SUCCEEDED 근거로 관리자 승인",
        reason="자율 시작 승인(ADR-KSI-015 D2)",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["site"]["status"] == "PROVISIONAL_AUTONOMY"

    # ── 6) Verified Flight Volume 도달 — PATROL_READY(정식 순찰 승인) ─────
    denied_final = transition(
        "PATROL_READY",
        evidence="시범 자율 운영 관찰 완료",
        reason="정식 순찰 승인 시도(권한 없음)",
        headers=field_op_headers,
    )
    assert denied_final.status_code == 403, denied_final.text

    patrol_ready = transition(
        "PATROL_READY",
        evidence=(
            f"현장 {_SITE_ID} — Baseline Mapping(임무 {_MISSION_ID}) → 처리 작업 {job_id} "
            f"SUCCEEDED → CoverageReport RECORDED(INV-010) 전 과정 실통과, 정식 순찰 승인"
        ),
        reason="정식 순찰 승인(ADR-KSI-015 D2) — Verified Flight Volume 도달",
        headers=admin_headers,
    )
    assert patrol_ready.status_code == 200, patrol_ready.text
    assert patrol_ready.json()["site"]["status"] == "PATROL_READY"

    # ── 최종 확인 — 저장소 재조회로도(HTTP 캐시가 아니라) 상태가 실제로 남았다.
    final = site_store.get(_SITE_ID)
    assert final is not None
    assert final.status.value == "PATROL_READY"
    final_job = processing_job_store.get(job_id)
    assert final_job is not None
    assert final_job.status is ProcessingJobStatus.SUCCEEDED
    assert coverage_store.latest(_MISSION_ID) is not None
