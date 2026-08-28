"""비교 요청 계약 — "이 두 작업을 비교하라"는 지시의 수신·발견·lease·전이 (W2, ADR-KSI-016 D3).

초점 다섯:

**① 생성 게이트가 실제 원장을 대조한다.** 두 작업이 SUCCEEDED 이고 같은 현장에
속하는지, point_cloud/dsm 산출물이 실재하는지를 서버가 대조한다 — 어느 쪽도
없으면 계산할 것이 없는 요청을 원장에 남기지 않는다(NOTHING_TO_COMPARE).

**② lease 가 원자적이고 죽은 워커의 요청을 회수한다.** ``ProcessingJobStore`` 와
같은 알고리즘(W1 이 이미 실기동으로 검증한 패턴)을 재구현했다는 것을 같은
성질의 테스트로 다시 고정한다.

**③ 워커가 자기 요청이 가리키는 산출물만 읽는다.** ``/input`` 이 최소권한을
지키는지 — 이 요청과 무관한 산출물이 새지 않는지.

**④ 구역(zones)은 값이지 참조가 아니다.** store 는 SiteStore 를 아예 의존하지
않는다 — 구조적으로 site.aoi 를 읽을 수 없다(대표자 확정, 2026-08-10).

**⑤ 멱등·권한 경계.** 같은 조합 재요청은 원장을 늘리지 않고, 결과 제출과 같은
이유로 사람은 이 표면의 워커 전용 부분(발견·lease·입력·전이)을 쓸 수 없다.

green≠작동: 두 작업을 실제로 발급하고 lease → RUNNING → 산출물 등록까지 진행한
뒤 그 jobId 로 비교 요청을 만든다 — 픽스처가 산출물 실재를 우회하지 않는다
(test_change_detection_api.py 와 동일 원칙).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.comparison_requests import (
    ComparisonRequestRecoveryError,
    ComparisonRequestStore,
    ComparisonRequestVerdict,
    mount_comparison_requests,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import (
    ArtifactSpec,
    ProcessingJobStatus,
    ProcessingJobStore,
    ProcessingJobVerdict,
)
from ksi_core.processing_profiles import KSI_ODM_CIVIL_V1_ID
from ksi_core.sites import SiteFrame, SiteStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaMeasurement, SourceMediaStore
from ksi_event_contracts.comparison_request import ComparisonRequest
from ksi_event_contracts.processing_artifact import (
    ArtifactAccuracy,
    LineageAuthority,
    ProcessingArtifactKind,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "comparison-request.v1.json"

_ADMIN_TOKEN = "cmp-admin-token"  # noqa: S105 -- 테스트 고정값
_WORKER_TOKEN = "cmp-worker-token"  # noqa: S105
_VIEWER_TOKEN = "cmp-viewer-token"  # noqa: S105
_OTHER_ORG_VIEWER_TOKEN = "cmp-other-org-viewer-token"  # noqa: S105 -- 조직 격리 회귀 고정값
_OTHER_ORG_WORKER_TOKEN = "cmp-other-org-worker-token"  # noqa: S105 -- 조직 격리 회귀 고정값
_SITE_ID = "site-cmp-001"
_BASELINE_MISSION_ID = "mission-cmp-baseline"
_CURRENT_MISSION_ID = "mission-cmp-current"
_OTHER_SITE_ID = "site-cmp-002"
_OTHER_MISSION_ID = "mission-cmp-other"
_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)
_NOW = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)
_DSM_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="ODM fixed-profile output uses the source ellipsoidal height",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)

_ZONES = {
    "zone-0": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
}
_ZONE_CRS = "EPSG:4326"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-1", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1", kind=PrincipalKind.PROCESSING_WORKER, role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1", kind=PrincipalKind.OPERATOR, role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_ORG_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="other-org-viewer",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_ORG_WORKER_TOKEN),
                principal=Principal(
                    principal_id="other-org-worker",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
        ]
    )


def _site_store(tmp_path: Path, *, path: str = "sites.jsonl") -> SiteStore:
    store = SiteStore(DurableJournal(tmp_path / path))
    for site_id in (_SITE_ID, _OTHER_SITE_ID):
        assert (
            store.register(
                site_id, "테스트 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
            ).verdict.value
            == "REGISTERED"
        )
    return store


def _mission_store(tmp_path: Path, *, path: str = "missions.jsonl") -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    for mission_id, site_id in (
        (_BASELINE_MISSION_ID, _SITE_ID),
        (_CURRENT_MISSION_ID, _SITE_ID),
        (_OTHER_MISSION_ID, _OTHER_SITE_ID),
    ):
        assert (
            store.record_issuance(
                MissionRecord(
                    mission_id=mission_id,
                    site_id=site_id,
                    mission_type="BASELINE_MAPPING",
                    artifact_kind="contract",
                    contract={"schemaVersion": "1.2", "missionId": mission_id},
                    kmz_sha256=None,
                    route_pattern=None,
                    waypoint_count=None,
                    planned_coverage_ratio=None,
                    issued_at=_NOW,
                    issued_by="op-1",
                    organization_id="org-2" if mission_id == _OTHER_MISSION_ID else "legacy",
                )
            ).value
            == "RECORDED"
        )
    return store


def _job_store_impl(
    tmp_path: Path, missions: MissionStore, sites: SiteStore
) -> tuple[ProcessingJobStore, SourceMediaStore]:
    """세 임무(baseline·current·other-site) 모두의 봉인된 번들을 아는 하나의
    SourceMediaStore 위에 ProcessingJobStore 를 세운다."""
    source_media = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=missions
    )
    for mission_id in (_BASELINE_MISSION_ID, _CURRENT_MISSION_ID, _OTHER_MISSION_ID):
        claims = [
            SourceMediaClaim(
                media_id=f"img-{i:03d}.jpg",
                sha256=hashlib.sha256(f"{mission_id}-{i}".encode()).hexdigest(),
                size_bytes=1_000_000 + i,
                width=4000,
                height=3000,
                content_type="image/jpeg",
            )
            for i in range(3)
        ]
        assert (
            source_media.register_batch(
                mission_id, claims, registered_by="op-1", now=_NOW
            ).verdict.value
            == "PROCESSED"
        )
        assert (
            source_media.seal(mission_id, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
        )
    jobs = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media,
        site_store=sites,
    )
    return jobs, source_media


_RASTER_KINDS = frozenset(
    {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM, ProcessingArtifactKind.DTM}
)


def _artifact_spec(
    artifact_id: str,
    *,
    kind: ProcessingArtifactKind = ProcessingArtifactKind.POINT_CLOUD,
    vertical_reference: VerticalReference | None = None,
    accuracy: ArtifactAccuracy | None = None,
) -> ArtifactSpec:
    # 래스터 계열(ortho/dsm/dtm)은 gsd 가 필수다(계약 위반 게이트) — 나머지는 null.
    return ArtifactSpec(
        artifact_id=artifact_id,
        kind=kind,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        digest="sha256:" + hashlib.sha256(artifact_id.encode()).hexdigest(),
        format="laz",
        crs="EPSG:5186",
        gsd=0.05 if kind in _RASTER_KINDS else None,
        accuracy=accuracy,
        # 기본값이 None 인 것이 기본 fixture 를 "수직기준 개념 이전에 등록된
        # 산출물"로 만든다 — 그 경로가 계속 살아 있는지가 이 파일의 회귀 대상이다.
        vertical_reference=vertical_reference,
    )


def _verify_bundle(source_media: SourceMediaStore, mission_id: str) -> None:
    """등록된 신고값과 정확히 같은 실측값을 보고한다 — SUCCEEDED 게이트(INV-051)의
    두 조건 중 하나(입력 검증)를 충족시킨다(test_change_detection_api.py 와 동형)."""
    bundle = source_media.get(mission_id)
    assert bundle is not None
    measurements = [
        SourceMediaMeasurement(
            media_id=m.media_id, sha256=m.sha256, size_bytes=m.size_bytes,
            width=m.width, height=m.height,
        )
        for m in bundle.media
    ]
    result = source_media.verify(mission_id, measurements, verified_by="w-1", now=_NOW)
    assert result.verdict.value in {"VERIFIED", "ALREADY_VERIFIED"}, result


_SOURCE_ELIGIBLE_KINDS = frozenset(
    {ProcessingArtifactKind.POINT_CLOUD, ProcessingArtifactKind.CAMERA_POSES}
)


def _succeeded_job(
    jobs: ProcessingJobStore,
    source_media: SourceMediaStore,
    mission_id: str,
    *artifact_specs: ArtifactSpec,
) -> str:
    """발급 → lease → RUNNING → 산출물 등록 → 입력 검증 → SUCCEEDED 까지 실제로
    진행한 jobId.

    호출부가 넘긴 artifact_specs 중 source-eligible kind(POINT_CLOUD/CAMERA_POSES,
    INV-051)가 하나도 없으면 이 헬퍼가 CAMERA_POSES 필러를 하나 더 등록한다 —
    SUCCEEDED 게이트(assert_succeeded_is_backed)를 정직하게 통과시키기 위함이지,
    호출부가 실제로 검증하려는 artifact 구성(예: point_cloud 없이 dsm 만 있는 경우의
    비교 가능성)을 바꾸지 않는다. CAMERA_POSES 는 change_detection_eligible(point_cloud
    존재 여부)·volume_change_eligible(dsm 존재 여부) 어느 쪽도 건드리지 않아 중립적이다
    (test_nothing_to_compare_is_rejected 가 이미 같은 패턴을 쓰고 있었다)."""
    record = jobs.issue(
        mission_id,
        jobs.resolve_processing_profile(KSI_ODM_CIVIL_V1_ID),
        issued_by="op-1",
        now=_NOW,
    ).record
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
    all_specs = list(artifact_specs)
    if not any(spec.kind in _SOURCE_ELIGIBLE_KINDS for spec in all_specs):
        all_specs.append(
            _artifact_spec(
                f"filler-camera-poses-{record.job_id}",
                kind=ProcessingArtifactKind.CAMERA_POSES,
            )
        )
    for spec in all_specs:
        result = jobs.register_artifact(record.job_id, spec, registered_by="w-1", now=_NOW)
        assert result.verdict is ProcessingJobVerdict.ARTIFACT_REGISTERED, result
    _verify_bundle(source_media, mission_id)
    assert (
        jobs.transition(
            record.job_id, ProcessingJobStatus.SUCCEEDED, detail="산출물 등록됨",
            actor="w-1", now=_NOW,
        ).verdict
        is ProcessingJobVerdict.TRANSITIONED
    )
    return record.job_id


def _running_job(jobs: ProcessingJobStore, mission_id: str) -> str:
    """SUCCEEDED 로 끝나지 않은(RUNNING) 작업 — JOB_NOT_SUCCEEDED 시험용."""
    record = jobs.issue(
        mission_id,
        jobs.resolve_processing_profile(KSI_ODM_CIVIL_V1_ID),
        issued_by="op-1",
        now=_NOW,
    ).record
    assert record is not None
    jobs.acquire_lease(record.job_id, worker_id="w-1", now=_NOW)
    jobs.transition(record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_NOW)
    return record.job_id


class _Fixture:
    """(비교 요청 저장소, 처리 작업 저장소, 미리 만든 SUCCEEDED baseline/current jobId)."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        dsm_vertical_reference: VerticalReference | None = _DSM_VERTICAL,
        dsm_accuracy: ArtifactAccuracy | None = None,
    ) -> None:
        self.missions = _mission_store(tmp_path)
        self.sites = _site_store(tmp_path)
        self.jobs, self.source_media = _job_store_impl(tmp_path, self.missions, self.sites)
        self.baseline_job_id = _succeeded_job(
            self.jobs,
            self.source_media,
            _BASELINE_MISSION_ID,
            _artifact_spec("point-cloud"),
            _artifact_spec(
                "dsm",
                kind=ProcessingArtifactKind.DSM,
                vertical_reference=dsm_vertical_reference,
                accuracy=dsm_accuracy,
            ),
        )
        self.current_job_id = _succeeded_job(
            self.jobs,
            self.source_media,
            _CURRENT_MISSION_ID,
            _artifact_spec("point-cloud"),
            _artifact_spec(
                "dsm",
                kind=ProcessingArtifactKind.DSM,
                vertical_reference=dsm_vertical_reference,
                accuracy=dsm_accuracy,
            ),
        )
        self.store = ComparisonRequestStore(
            DurableJournal(tmp_path / "comparison-requests.jsonl"),
            mission_store=self.missions,
            processing_job_store=self.jobs,
            analysis_readiness=lambda _mission_id: (True, None),
        )

    def create(self, **overrides: Any) -> Any:
        kwargs: dict[str, Any] = {
            "mission_id": _CURRENT_MISSION_ID,
            "baseline_job_id": self.baseline_job_id,
            "current_job_id": self.current_job_id,
            "zones": _ZONES,
            "zone_crs": _ZONE_CRS,
            "requested_by": "op-1",
            "now": _NOW,
        }
        kwargs.update(overrides)
        return self.store.create(kwargs.pop("mission_id"), **kwargs)


@pytest.fixture
def fx(tmp_path: Path) -> _Fixture:
    return _Fixture(tmp_path)


class _FakeStorage:
    """포트 계약만 만족하는 가짜 스토리지 — presigned GET 호출을 기록한다."""

    def __init__(self) -> None:
        self.presigned_get_calls: list[str] = []
        self.fail = False

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        if self.fail:
            raise EvidenceStorageError("테스트 강제 실패")
        self.presigned_get_calls.append(object_key)
        return f"https://fake-storage/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError

    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _client(
    store: ComparisonRequestStore, *, token: str = _ADMIN_TOKEN, storage: Any = None
) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_comparison_requests(app, store, storage or _FakeStorage())
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


# ── 생성 게이트 ──────────────────────────────────────────────────────────


def test_creates_when_both_jobs_succeeded_same_site(fx: _Fixture) -> None:
    result = fx.create()
    assert result.verdict is ComparisonRequestVerdict.CREATED
    assert result.record is not None
    assert result.record.change_detection_eligible is True
    assert result.record.volume_change_eligible is True
    assert result.record.request_id == f"{_CURRENT_MISSION_ID}-cmp1"


def test_self_comparison_is_rejected(fx: _Fixture) -> None:
    result = fx.create(current_job_id=fx.baseline_job_id)
    assert result.verdict is ComparisonRequestVerdict.SELF_COMPARISON


def test_unknown_baseline_job_is_rejected(fx: _Fixture) -> None:
    result = fx.create(baseline_job_id="no-such-job")
    assert result.verdict is ComparisonRequestVerdict.UNKNOWN_JOB


def test_unknown_current_job_is_rejected(fx: _Fixture) -> None:
    result = fx.create(current_job_id="no-such-job")
    assert result.verdict is ComparisonRequestVerdict.UNKNOWN_JOB


def test_baseline_not_succeeded_is_rejected(fx: _Fixture) -> None:
    running = _running_job(fx.jobs, _BASELINE_MISSION_ID)
    result = fx.create(baseline_job_id=running)
    assert result.verdict is ComparisonRequestVerdict.JOB_NOT_SUCCEEDED


def test_different_site_is_rejected(fx: _Fixture) -> None:
    other_job = _succeeded_job(
        fx.jobs, fx.source_media, _OTHER_MISSION_ID, _artifact_spec("point-cloud")
    )
    result = fx.create(baseline_job_id=other_job)
    assert result.verdict is ComparisonRequestVerdict.SITE_MISMATCH


def test_mission_path_must_match_current_jobs_mission(fx: _Fixture) -> None:
    result = fx.create(mission_id=_BASELINE_MISSION_ID)
    assert result.verdict is ComparisonRequestVerdict.MISSION_MISMATCH


def test_missing_point_cloud_still_allows_volume_change_only(fx: _Fixture) -> None:
    """[핵심] point_cloud 가 없어도 dsm+zones 만 있으면 체적 비교는 시도된다 —
    '비교 불가'가 전부-아니면-전무가 아니다."""
    baseline_no_pc = _succeeded_job(
        fx.jobs,
        fx.source_media,
        _BASELINE_MISSION_ID,
        _artifact_spec(
            "dsm",
            kind=ProcessingArtifactKind.DSM,
            vertical_reference=_DSM_VERTICAL,
        ),
    )
    result = fx.create(baseline_job_id=baseline_no_pc)
    assert result.verdict is ComparisonRequestVerdict.CREATED
    record = result.record
    assert record is not None
    assert record.change_detection_eligible is False
    assert record.change_detection_ineligible_reason is not None
    assert "baseline" in record.change_detection_ineligible_reason
    assert record.volume_change_eligible is True


def test_missing_dsm_still_allows_change_detection_only(fx: _Fixture) -> None:
    baseline_no_dsm = _succeeded_job(
        fx.jobs, fx.source_media, _BASELINE_MISSION_ID, _artifact_spec("point-cloud")
    )
    result = fx.create(baseline_job_id=baseline_no_dsm)
    assert result.verdict is ComparisonRequestVerdict.CREATED
    record = result.record
    assert record is not None
    assert record.change_detection_eligible is True
    assert record.volume_change_eligible is False
    assert record.volume_change_ineligible_reason is not None


def test_zones_without_crs_disables_volume_change(fx: _Fixture) -> None:
    result = fx.create(zone_crs=None)
    assert result.verdict is ComparisonRequestVerdict.CREATED
    record = result.record
    assert record is not None
    assert record.volume_change_eligible is False
    assert record.change_detection_eligible is True


def test_nothing_to_compare_is_rejected(fx: _Fixture) -> None:
    """point_cloud·dsm 둘 다 없는 두 작업 — 비교할 것이 아무것도 없다."""
    bare_baseline = _succeeded_job(
        fx.jobs,
        fx.source_media,
        _BASELINE_MISSION_ID,
        _artifact_spec("camera-poses", kind=ProcessingArtifactKind.CAMERA_POSES),
    )
    bare_current = _succeeded_job(
        fx.jobs,
        fx.source_media,
        _CURRENT_MISSION_ID,
        _artifact_spec("camera-poses", kind=ProcessingArtifactKind.CAMERA_POSES),
    )
    result = fx.create(baseline_job_id=bare_baseline, current_job_id=bare_current)
    assert result.verdict is ComparisonRequestVerdict.NOTHING_TO_COMPARE


@pytest.mark.parametrize(
    "bad_polygon",
    [
        {"type": "Point", "coordinates": [1, 2]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},  # 안 닫힘
        {"type": "Polygon", "coordinates": [[["a", "b"], [1, 0], [1, 1], ["a", "b"]]]},
        {"type": "Polygon"},
        {"nonsense": True},
    ],
)
def test_ad_hoc_zone_geometry_is_validated_at_request_time(
    fx: _Fixture, bad_polygon: dict[str, object]
) -> None:
    """2026-08-13 프로젝트 두뇌 재감사 확정 발견의 회귀 방지 — comparison_requests 쪽.

    design_conformance_requests.py 와 같은 검사(assert_zones_are_usable)를 공유한다.
    """
    result = fx.create(zones={"zone-a": bad_polygon})
    assert result.verdict is ComparisonRequestVerdict.ZONES_INVALID, result
    assert result.detail is not None and "zone-a" in result.detail


def test_ad_hoc_zone_count_is_capped(fx: _Fixture) -> None:
    many_zones = {
        f"zone-{i}": {
            "type": "Polygon",
            "coordinates": [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]],
        }
        for i in range(65)
    }
    result = fx.create(zones=many_zones)
    assert result.verdict is ComparisonRequestVerdict.ZONES_INVALID, result
    assert result.detail is not None and "65" in result.detail


def test_idempotent_resubmit_returns_existing_request(fx: _Fixture) -> None:
    first = fx.create()
    assert first.verdict is ComparisonRequestVerdict.CREATED
    second = fx.create()
    assert second.verdict is ComparisonRequestVerdict.ALREADY_REQUESTED
    assert second.record is not None
    assert second.record.request_id == first.record.request_id


def test_resubmit_with_a_confirmed_zone_is_a_new_request_not_a_replay(fx: _Fixture) -> None:
    """[핵심][회귀] 구역 없이 한 번 요청한 뒤 구역을 확정해 다시 제출하면 **새
    요청**이어야 한다.

    예전 멱등 키는 (baselineJobId, currentJobId) 뿐이라, 구역 없이 만든 첫 요청이
    영원히 돌아왔다 — 그 두 시점의 부피 비교를 받을 방법이 아예 없었고, 화면이
    "구역이나 시점을 바꿔 다시 요청할 수 있다"고 안내하는 것과도 어긋났다.
    """
    without_zone = fx.create(zones=None, zone_crs=None)
    assert without_zone.verdict is ComparisonRequestVerdict.CREATED
    assert without_zone.record.volume_change_eligible is False

    with_zone = fx.create()
    assert with_zone.verdict is ComparisonRequestVerdict.CREATED
    assert with_zone.record.request_id != without_zone.record.request_id
    assert with_zone.record.volume_change_eligible is True


def test_resubmit_with_the_same_zone_is_still_idempotent(fx: _Fixture) -> None:
    """구역까지 똑같으면 여전히 같은 요청이다 — 네트워크 재시도가 요청을 복제하지
    않는다는 원래 성질은 그대로다."""
    first = fx.create()
    second = fx.create()
    assert second.verdict is ComparisonRequestVerdict.ALREADY_REQUESTED
    assert second.record.request_id == first.record.request_id


def test_idempotency_key_survives_a_restart(tmp_path: Path) -> None:
    """[핵심][회귀] 재기동(원장 재생) 뒤에도 같은 재전송이 중복을 만들지 않는다.

    멱등 키는 생성 시점(요청 원문)과 재생 시점(레코드)에 **같은 값**이어야 한다.
    ``_resolve`` 가 부피 비적격이면 zones 를 떨구므로, 요청 원문으로 키를 만들면
    두 시점의 키가 갈려 재기동 후 같은 재전송이 새 요청을 만든다. 그 갈림을
    고정한다 — 부피가 안 되는 조합(dsm 없는 작업)을 일부러 쓴다.
    """
    missions = _mission_store(tmp_path)
    sites = _site_store(tmp_path)
    jobs, source_media = _job_store_impl(tmp_path, missions, sites)
    # dsm 없이 point-cloud 만 — zones 를 줘도 부피는 비적격이라 정규화로 떨궈진다.
    baseline = _succeeded_job(
        jobs, source_media, _BASELINE_MISSION_ID, _artifact_spec("point-cloud")
    )
    current = _succeeded_job(
        jobs, source_media, _CURRENT_MISSION_ID, _artifact_spec("point-cloud")
    )

    def _new_store() -> ComparisonRequestStore:
        return ComparisonRequestStore(
            DurableJournal(tmp_path / "comparison-requests.jsonl"),
            mission_store=missions,
            processing_job_store=jobs,
            analysis_readiness=lambda _mission_id: (True, None),
        )

    def _submit(store: ComparisonRequestStore) -> Any:
        return store.create(
            _CURRENT_MISSION_ID,
            baseline_job_id=baseline,
            current_job_id=current,
            zones=_ZONES,
            zone_crs=_ZONE_CRS,
            requested_by="op-1",
            now=_NOW,
        )

    store = _new_store()
    first = _submit(store)
    assert first.verdict is ComparisonRequestVerdict.CREATED
    assert first.record.zones is None  # 정규화로 떨궈졌다 — 이 테스트의 전제
    store._journal.close()  # noqa: SLF001 -- 같은 경로를 다시 열기 위해

    replayed = _new_store()
    again = _submit(replayed)
    assert again.verdict is ComparisonRequestVerdict.ALREADY_REQUESTED
    assert again.record.request_id == first.record.request_id
    replayed._journal.close()  # noqa: SLF001 -- 테스트 정리


def test_zones_are_stored_as_a_value_not_a_site_reference(fx: _Fixture) -> None:
    """[핵심] store 는 SiteStore 를 의존하지 않는다 — 구조적으로 site.aoi 를 읽을
    수 없으므로 zones 는 항상 요청 시점에 넘긴 값 그대로다(대표자 확정)."""
    result = fx.create()
    assert result.record is not None
    assert result.record.zones == _ZONES
    # ComparisonRequestStore 생성자가 site_store 를 받지 않는다는 것 자체가
    # "site.aoi 를 참조할 수 없다"는 불변식의 구조적 근거다.
    import inspect

    params = inspect.signature(ComparisonRequestStore.__init__).parameters
    assert "site_store" not in params


# ── 기준값 스냅샷 (W2-3) ────────────────────────────────────────────────────


def test_policy_is_snapshotted_at_creation(fx: _Fixture) -> None:
    """생성 시점의 시스템 기준값이 요청에 값으로 굳는다 — 화면·워커가 같은 값을 본다."""
    from ksi_event_contracts.comparison_policy import current_comparison_policy

    result = fx.create()
    assert result.record is not None
    assert result.record.policy == current_comparison_policy()


def test_existing_request_keeps_its_policy_when_system_thresholds_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] 시스템 기준값을 바꿔도 **이미 만들어진 요청의 스냅샷은 그대로**다.

    zones 가 site.aoi 를 참조하지 않는 것과 같은 성질(대표자 확정) — 참조였다면
    기준값을 바꾼 배포가 과거 결과의 해석까지 소급해 바꿔버리고, "그때 무슨
    기준으로 쟀나"에 답할 수 없게 된다. 재생 경로도 원장에 적힌 값을 되살리는지
    함께 고정한다(여기서 current_comparison_policy() 를 부르면 이 테스트가 깨진다).
    """
    import ksi_core.comparison_requests as module
    from ksi_event_contracts.comparison_policy import ComparisonPolicy

    fx = _Fixture(tmp_path)
    journal_path = tmp_path / "comparison-requests.jsonl"
    before = fx.create()
    assert before.record is not None
    original = before.record.policy

    # 배포가 기준값을 바꾼 상황을 흉내낸다.
    changed = ComparisonPolicy(
        policy_version="comparison-policy-v99",
        distance_threshold_m=0.99,
        volume_threshold_m=0.98,
        revisit_ratio_threshold=0.97,
    )
    monkeypatch.setattr(module, "current_comparison_policy", lambda: changed)

    # 살아있는 store 의 기존 레코드는 그대로다.
    assert fx.store.get(before.record.request_id) is not None
    assert fx.store.get(before.record.request_id).policy == original  # type: ignore[union-attr]

    # 재기동(재생) 후에도 그대로여야 한다 — 원장에 적힌 값을 되살리는지 확인.
    fx.store._journal.close()  # noqa: SLF001 -- 같은 경로를 다시 열기 위해
    replayed = ComparisonRequestStore(
        DurableJournal(journal_path),
        mission_store=fx.missions,
        processing_job_store=fx.jobs,
        analysis_readiness=lambda _mission_id: (True, None),
    )
    restored = replayed.get(before.record.request_id)
    assert restored is not None
    assert restored.policy == original, "재생이 현재 정책으로 과거 요청을 덮어썼다"

    # 반면 **새** 요청은 바뀐 값을 쓴다(스냅샷이 화석이 아니라는 것).
    fresh = replayed.create(
        _BASELINE_MISSION_ID,  # 방향을 뒤집었으므로 current 쪽 임무도 바뀐다
        baseline_job_id=fx.current_job_id,
        current_job_id=fx.baseline_job_id,
        zones=_ZONES,
        zone_crs=_ZONE_CRS,
        requested_by="op-1",
        now=_NOW,
    )
    assert fresh.record is not None
    assert fresh.record.policy == changed
    replayed._journal.close()  # noqa: SLF001 -- 테스트 정리


# ── 계약 스키마 정합 ────────────────────────────────────────────────────────


def test_model_output_satisfies_contract_schema(fx: _Fixture) -> None:
    result = fx.create()
    assert result.record is not None
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    wire = result.record.to_contract().model_dump(by_alias=True, mode="json", exclude_none=False)
    errors = sorted(validator.iter_errors(wire), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]
    assert ComparisonRequest.model_validate(wire) == result.record.to_contract()


# ── lease 원자성·회수 ────────────────────────────────────────────────────


def test_list_pending_only_shows_queued(fx: _Fixture) -> None:
    result = fx.create()
    assert result.record is not None
    assert [
        r.request_id for r in fx.store.list_pending(now=_NOW)
    ] == [result.record.request_id]


def test_lease_is_atomic_second_worker_gets_held_by_another(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    first = fx.store.acquire_lease(request_id, worker_id="worker-a", now=_NOW)
    assert first.verdict is ComparisonRequestVerdict.LEASED
    second = fx.store.acquire_lease(request_id, worker_id="worker-b", now=_NOW)
    assert second.verdict is ComparisonRequestVerdict.LEASE_HELD_BY_ANOTHER


def test_lease_renewal_by_same_worker(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-a", now=_NOW)
    renewed = fx.store.acquire_lease(
        request_id, worker_id="worker-a", now=_NOW + timedelta(minutes=5)
    )
    assert renewed.verdict is ComparisonRequestVerdict.LEASE_RENEWED


def test_list_pending_includes_running_with_expired_lease(fx: _Fixture) -> None:
    """[핵심] 워커가 계산 도중 죽어도 다른 워커가 다시 집을 수 있다(W1 정체작업회수와 동형)."""
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-a", now=_NOW)
    fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-a", now=_NOW
    )
    still_active = fx.store.list_pending(now=_NOW)
    assert still_active == []  # lease 살아있는 동안은 후보가 아니다

    after_expiry = _NOW + timedelta(minutes=16)  # DEFAULT_LEASE_TTL(15분) 초과
    orphaned = fx.store.list_pending(now=after_expiry)
    assert [r.request_id for r in orphaned] == [request_id]

    reclaimed = fx.store.acquire_lease(request_id, worker_id="worker-b", now=after_expiry)
    assert reclaimed.verdict is ComparisonRequestVerdict.LEASED


def test_list_pending_expiry_boundary_is_exclusive(fx: _Fixture) -> None:
    """[경계] 만료 시각 그 순간부터 후보다 — 1초 전은 아직 아니다.

    ``ProcessingJobStore`` 쪽 대칭 테스트
    (``test_processing_jobs.py::test_store_list_pending_expiry_boundary_is_exclusive``)와
    같은 규칙을 검증한다 — 둘 다 ``ksi_core.leasing`` 의 같은 순수 함수를 쓴다.
    """
    result = fx.create()
    request_id = result.record.request_id
    leased = fx.store.acquire_lease(request_id, worker_id="worker-a", now=_NOW)
    assert leased.record is not None
    assert leased.record.lease is not None
    expires_at = leased.record.lease.expires_at
    fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-a", now=_NOW
    )

    just_before = expires_at - timedelta(seconds=1)
    assert fx.store.list_pending(now=just_before) == []

    assert [r.request_id for r in fx.store.list_pending(now=expires_at)] == [request_id]
    reclaimed = fx.store.acquire_lease(request_id, worker_id="worker-b", now=expires_at)
    assert reclaimed.verdict is ComparisonRequestVerdict.LEASED


# ── 입력 조회 최소권한 ───────────────────────────────────────────────────


def test_input_returns_urls_only_for_this_requests_artifacts(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    storage = _FakeStorage()
    client = _client(fx.store, token=_WORKER_TOKEN, storage=storage)
    # HTTP 핸들러는 실제 벽시계(datetime.now(UTC))로 lease 만료를 판정한다 — 여기서도
    # 같은 시계를 써야 한다(고정된 _NOW 로 잡으면 실행 시각에 따라 이미 만료로 보인다).
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=datetime.now(UTC))

    response = client.get(f"/v1/comparison-requests/{request_id}/input")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["verdict"] == "INPUT_READY"
    assert body["input"]["pointCloudBaselineUrl"] is not None
    assert body["input"]["dsmBaselineUrl"] is not None
    # 이 요청이 가리키는 산출물(baseline/current 의 point-cloud·dsm) 정확히 4건만
    # presign 됐다 — 다른 산출물(camera-poses 등)이나 다른 작업은 등장하지 않는다.
    assert len(storage.presigned_get_calls) == 4
    assert all(
        fx.baseline_job_id in key or fx.current_job_id in key
        for key in storage.presigned_get_calls
    )
    # missionId·jobId+artifactId 참조도 함께 온다 — 워커가 ChangeDetectionResult/
    # VolumeChangeReport 를 제출하려면 URL 뿐 아니라 "어느 (작업, 산출물)" 인지도
    # 알아야 한다(URL 만으로는 결과 계약을 구성할 수 없다).
    assert body["input"]["missionId"] == _CURRENT_MISSION_ID
    assert body["input"]["status"] == "QUEUED"
    assert body["input"]["pointCloudBaseline"] == {
        "jobId": fx.baseline_job_id, "artifactId": "point-cloud"
    }
    assert body["input"]["pointCloudCurrent"] == {
        "jobId": fx.current_job_id, "artifactId": "point-cloud"
    }
    assert body["input"]["dsmBaseline"] == {"jobId": fx.baseline_job_id, "artifactId": "dsm"}
    assert body["input"]["dsmCurrent"] == {"jobId": fx.current_job_id, "artifactId": "dsm"}


def _leased_input(fx: _Fixture) -> dict[str, Any]:
    """lease 를 잡고 ``/input`` 을 받아 온 ``input`` 본문."""
    request_id = fx.create().record.request_id
    client = _client(fx.store, token=_WORKER_TOKEN, storage=_FakeStorage())
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=datetime.now(UTC))
    response = client.get(f"/v1/comparison-requests/{request_id}/input")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()["input"]
    return body


def test_input_carries_the_vertical_reference_the_dsms_declared(tmp_path: Path) -> None:
    """[핵심] 워커가 리포트에 실을 수직기준의 출처는 **산출물이 등록 시 선언한
    값**이다 — Core 는 그 값을 전달만 한다(읽지도, 채우지도 않는다).

    요청 레코드에 복사해 두지 않고 입력 발급 시점에 조회하므로(presigned URL 과
    같은 자리), 요청 계약(``ComparisonRequest``)은 한 세대도 갈라지지 않는다.
    """
    declared = VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
        basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )
    body = _leased_input(_Fixture(tmp_path, dsm_vertical_reference=declared))

    expected = {
        "datum": "ellipsoidal_native",
        "basis": "ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
        "source": "pipeline_declared",
    }
    assert body["dsmBaselineVerticalReference"] == expected
    assert body["dsmCurrentVerticalReference"] == expected


def test_new_quantitative_request_rejects_unknown_vertical_reference(tmp_path: Path) -> None:
    """INV-053: historical null remains readable, but cannot seed a new number."""

    fx = _Fixture(tmp_path, dsm_vertical_reference=None)
    result = fx.create()
    assert result.verdict is ComparisonRequestVerdict.VERTICAL_REFERENCE_MISMATCH


def test_input_carries_the_checkpoint_rmse_the_dsms_declared(tmp_path: Path) -> None:
    """[핵심·INV-024] 워커가 오차한계 계산에 쓸 값은 **독립 검사점 잔차**뿐이다.

    수직기준과 같은 관례 — 요청 레코드에 복사하지 않고 입력 발급 시점에 산출물
    원장에서 조회한다. **``accuracy.rmse``(GCP 피팅 잔차)는 절대 싣지 않는다** —
    그걸 흘리면 "검증 없는 수치가 진짜 오차한계처럼 실리는" INV-024 위반을 이
    배선이 그대로 재도입한다.
    """
    verified = ArtifactAccuracy(
        gcp_count=12,
        rmse=0.03,
        report_uri="s3://r/1.pdf",
        checkpoint_count=8,
        checkpoint_rmse_m=0.042,
    )
    body = _leased_input(_Fixture(tmp_path, dsm_accuracy=verified))

    assert body["dsmBaselineCheckpointRmseM"] == 0.042
    assert body["dsmCurrentCheckpointRmseM"] == 0.042


def test_input_leaves_checkpoint_rmse_null_when_only_fit_rmse_exists(tmp_path: Path) -> None:
    """[회귀] 검사점 없는 정확도(GCP 피팅 잔차만)는 ``null`` 로 온다.

    ``rmse=0.03`` 이 있어도 그것은 절대정확도가 아니므로 오차한계 입력이 될 수
    없다 — Core 가 그 값을 대신 흘리면 INV-024 재도입이다.
    """
    fit_only = ArtifactAccuracy(gcp_count=12, rmse=0.03, report_uri="s3://r/1.pdf")
    body = _leased_input(_Fixture(tmp_path, dsm_accuracy=fit_only))

    assert body["dsmBaselineCheckpointRmseM"] is None
    assert body["dsmCurrentCheckpointRmseM"] is None


def test_input_leaves_checkpoint_rmse_null_without_any_accuracy(fx: _Fixture) -> None:
    """[회귀] 정확도 신고가 아예 없는 산출물(ODM 경로)도 ``null`` — 기본값을 지어내지 않는다."""
    body = _leased_input(fx)
    assert body["dsmBaselineCheckpointRmseM"] is None
    assert body["dsmCurrentCheckpointRmseM"] is None


def test_input_requires_lease(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    client = _client(fx.store, token=_WORKER_TOKEN)
    response = client.get(f"/v1/comparison-requests/{request_id}/input")
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_REQUIRED"


def test_input_denies_worker_without_the_lease(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-a", now=datetime.now(UTC))
    client = _client(fx.store, token=_WORKER_TOKEN)  # principal_id="worker-1" != "worker-a"
    response = client.get(f"/v1/comparison-requests/{request_id}/input")
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_HELD_BY_ANOTHER"


# ── 전이 ─────────────────────────────────────────────────────────────────


def test_transition_running_then_succeeded(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=_NOW)
    running = fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )
    assert running.verdict is ComparisonRequestVerdict.TRANSITIONED
    succeeded = fx.store.transition(
        request_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="worker-1", now=_NOW
    )
    assert succeeded.verdict is ComparisonRequestVerdict.TRANSITIONED
    assert succeeded.record is not None
    assert succeeded.record.status is ProcessingJobStatus.SUCCEEDED


def test_illegal_transition_is_rejected(fx: _Fixture) -> None:
    """QUEUED 에서 SUCCEEDED 로 직행할 수 없다 — RUNNING 을 거쳐야 한다."""
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=_NOW)
    illegal = fx.store.transition(
        request_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="worker-1", now=_NOW
    )
    assert illegal.verdict is ComparisonRequestVerdict.ILLEGAL_TRANSITION


def test_transition_requires_lease(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    denied = fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )
    assert denied.verdict is ComparisonRequestVerdict.LEASE_REQUIRED


def test_failed_transition_preserves_detail(fx: _Fixture) -> None:
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=_NOW)
    fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )
    failed = fx.store.transition(
        request_id,
        ProcessingJobStatus.FAILED,
        detail="DSM 다운로드 실패",
        actor="worker-1",
        now=_NOW,
    )
    assert failed.verdict is ComparisonRequestVerdict.TRANSITIONED
    assert failed.record is not None
    assert failed.record.detail == "DSM 다운로드 실패"


# ── HTTP 권한 경계 ───────────────────────────────────────────────────────


def test_http_create_requires_missions_issue(fx: _Fixture) -> None:
    client = _client(fx.store, token=_VIEWER_TOKEN)
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
            "zones": _ZONES,
            "zoneCrs": _ZONE_CRS,
        },
    )
    assert response.status_code == 403


def test_http_worker_cannot_create_request(fx: _Fixture) -> None:
    """워커는 '무엇을 비교할지'를 스스로 지목할 수 없다 — 사람의 결정이다."""
    client = _client(fx.store, token=_WORKER_TOKEN)
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
        },
    )
    assert response.status_code == 403


def test_http_preflight_reuses_create_gate_without_mutating_the_journal(
    fx: _Fixture,
) -> None:
    client = _client(fx.store, token=_VIEWER_TOKEN)
    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-preflight",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
            "zones": _ZONES,
            "zoneCrs": _ZONE_CRS,
        },
    )
    assert response.status_code == 200
    assert response.json() == {"compatible": True, "reason": None, "detail": None}
    assert fx.store.list_for_mission(_CURRENT_MISSION_ID) == []


def test_http_preflight_returns_typed_analysis_readiness_blocker(tmp_path: Path) -> None:
    fx = _Fixture(tmp_path)
    blocked_store = ComparisonRequestStore(
        DurableJournal(tmp_path / "blocked-comparison-requests.jsonl"),
        mission_store=fx.missions,
        processing_job_store=fx.jobs,
        analysis_readiness=lambda _mission_id: (False, "capture quality gap"),
    )
    client = _client(blocked_store, token=_VIEWER_TOKEN)

    response = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-preflight",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
            "zones": _ZONES,
            "zoneCrs": _ZONE_CRS,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "compatible": False,
        "reason": "ANALYSIS_NOT_READY",
        "detail": "baseline epoch: capture quality gap",
    }
    assert blocked_store.list_for_mission(_CURRENT_MISSION_ID) == []


def test_http_create_succeeds_and_lists(fx: _Fixture) -> None:
    client = _client(fx.store)
    created = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
            "zones": _ZONES,
            "zoneCrs": _ZONE_CRS,
        },
    )
    assert created.status_code == 201, created.json()
    assert created.json()["verdict"] == "CREATED"

    listed = client.get(f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests")
    assert listed.status_code == 200
    assert len(listed.json()["requests"]) == 1


def test_http_operator_cannot_list_pending(fx: _Fixture) -> None:
    client = _client(fx.store, token=_ADMIN_TOKEN)
    response = client.get("/v1/comparison-requests")
    assert response.status_code == 403


def test_http_worker_can_list_pending_minimal_fields(fx: _Fixture) -> None:
    fx.create()
    client = _client(fx.store, token=_WORKER_TOKEN)
    response = client.get("/v1/comparison-requests")
    assert response.status_code == 200
    body = response.json()["requests"]
    assert len(body) == 1
    assert set(body[0]) == {"requestId", "requestedAt"}


def test_http_unknown_request_is_404(fx: _Fixture) -> None:
    client = _client(fx.store)
    assert client.get("/v1/comparison-requests/no-such-request").status_code == 404


def test_http_other_organization_cannot_read_or_lease_foreign_comparison_request(
    fx: _Fixture,
) -> None:
    """Request id, Mission path, worker queue 모두 Mission의 org scope를 상속한다."""

    result = fx.create()
    assert result.record is not None
    request_id = result.record.request_id

    viewer = _client(fx.store, token=_OTHER_ORG_VIEWER_TOKEN)
    assert (
        viewer.get(f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests").status_code == 404
    )
    assert viewer.get(f"/v1/comparison-requests/{request_id}").status_code == 404

    worker = _client(fx.store, token=_OTHER_ORG_WORKER_TOKEN)
    assert worker.get("/v1/comparison-requests").json()["requests"] == []
    assert worker.post(f"/v1/comparison-requests/{request_id}/lease").status_code == 404
    assert worker.get(f"/v1/comparison-requests/{request_id}/input").status_code == 404


# ── 종단 사슬: 접수 API → 실제 워커(HttpCoreClient) → 결과 조회 ─────────────
#
# 위 테스트들은 각 경계(생성 게이트, lease, /input, /transitions)를 개별로
# 고정한다. 이 테스트는 그 경계들을 실제로 이어 부르는가를 본다 — 접수 API
# POST 로 시작해, ksi_processing_controller 가 프로덕션에서 쓰는 그 HttpCoreClient
# (가짜가 아니다)로 comparison_worker.run_comparison_request(가짜가 아니다)를
# 돌려 SUCCEEDED 까지 가고, 결과 조회 API 로 되짚는다. 어느 단계도 최종 상태를
# 손으로 넣지 않는다 — QUEUED 는 접수 API가, RUNNING/SUCCEEDED 는 워커가 실제
# HTTP 전이 호출로 만든다.


def test_full_chain_from_submission_api_through_worker_to_result(
    fx: _Fixture, tmp_path: Path
) -> None:
    import httpx
    import laspy
    import numpy as np
    import rasterio
    from ksi_core.change_detection import ChangeDetectionStore, mount_change_detection
    from ksi_core.processing_jobs import build_processing_artifact_object_key
    from ksi_core.volume_reports import VolumeChangeStore, mount_volume_reports
    from ksi_geo_spatial.crs import reproject_point
    from ksi_processing_controller.comparison_worker import run_comparison_request
    from ksi_processing_controller.core_client import HttpCoreClient
    from pyproj import CRS
    from rasterio.transform import from_origin

    origin_x, origin_y = 200_000.0, 550_000.0

    def _grid(n: int, *, z: float = 0.0) -> np.ndarray:
        return np.array([[float(i), 0.0, z] for i in range(n)])

    def _write_laz(path: Path, points: np.ndarray) -> Path:
        header = laspy.LasHeader(point_format=3, version="1.2")
        header.offsets = [0.0, 0.0, 0.0]
        header.scales = [0.001, 0.001, 0.001]
        header.add_crs(CRS.from_user_input("EPSG:5186"))
        las = laspy.LasData(header)
        las.x, las.y, las.z = points[:, 0], points[:, 1], points[:, 2]
        las.write(str(path))
        return path

    def _write_dsm(path: Path, value: float) -> Path:
        with rasterio.open(
            path, "w", driver="GTiff", height=10, width=10, count=1, dtype="float64",
            crs="EPSG:5186", transform=from_origin(origin_x, origin_y, 1.0, 1.0),
        ) as dataset:
            dataset.write(np.full((10, 10), value, dtype=np.float64), 1)
        return path

    def _wgs84_square(size_m: float) -> dict[str, Any]:
        corners_xy = [
            (origin_x, origin_y), (origin_x + size_m, origin_y),
            (origin_x + size_m, origin_y - size_m), (origin_x, origin_y - size_m),
            (origin_x, origin_y),
        ]
        ring = [
            list(reproject_point(x, y, from_crs="EPSG:5186", to_crs="EPSG:4326"))
            for x, y in corners_xy
        ]
        return {"type": "Polygon", "coordinates": [ring]}

    # ── 실제 바이트: 두 점군(하나는 점 하나가 이동), 두 DSM(고도가 다르다) ──
    baseline_cloud = _grid(20)
    current_cloud = _grid(20)
    current_cloud[10] = [10.0, 5.0, 0.0]  # 손계산 가능한 단일 변화
    files = {
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=fx.baseline_job_id, artifact_id="point-cloud"
        ): _write_laz(tmp_path / "pc-baseline.laz", baseline_cloud),
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=fx.current_job_id, artifact_id="point-cloud"
        ): _write_laz(tmp_path / "pc-current.laz", current_cloud),
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=fx.baseline_job_id, artifact_id="dsm"
        ): _write_dsm(tmp_path / "dsm-baseline.tif", 100.0),
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=fx.current_job_id, artifact_id="dsm"
        ): _write_dsm(tmp_path / "dsm-current.tif", 101.5),
    }

    class _RealBytesStorage:
        """presigned GET 이 실제 로컬 파일을 가리키는 URL 을 낸다 — 다른 임의
        object_key 는 404(다른 산출물이 새지 않는지도 이 스토리지가 자연히 검증)."""

        def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
            raise NotImplementedError

        def presigned_get(self, object_key: str, *, ttl: Any) -> str:
            if object_key not in files:
                raise EvidenceStorageError(f"없다: {object_key}")
            return f"http://storage.test/{object_key}"

        def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
            raise NotImplementedError

        def get_bytes(self, object_key: str) -> bytes:
            raise NotImplementedError

        def delete(self, object_key: str) -> None:
            raise NotImplementedError

    def _storage_handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.lstrip("/")
        path = files.get(key)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    # ── 실제 Core 앱: 비교 요청 + 변화탐지 + 체적 표면을 전부 장착 ──
    change_detection_store = ChangeDetectionStore(
        DurableJournal(tmp_path / "change-detection.jsonl"),
        mission_store=fx.missions, processing_job_store=fx.jobs,
    )
    volume_change_store = VolumeChangeStore(
        DurableJournal(tmp_path / "volume-changes.jsonl"),
        mission_store=fx.missions, processing_job_store=fx.jobs,
    )
    app = FastAPI()
    mount_auth(app, _registry())
    mount_comparison_requests(app, fx.store, _RealBytesStorage())
    mount_change_detection(app, change_detection_store)
    mount_volume_reports(app, volume_change_store)

    # ── ① 접수 API — 사람(MISSIONS_ISSUE)이 실제 POST 로 QUEUED 를 만든다 ──
    human_client = TestClient(app)
    human_client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    created = human_client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/comparison-requests",
        json={
            "baselineJobId": fx.baseline_job_id,
            "currentJobId": fx.current_job_id,
            "zones": {"zone-a": _wgs84_square(5.0)},
            "zoneCrs": "EPSG:4326",
        },
    )
    assert created.status_code == 201, created.json()
    request_id = created.json()["request"]["requestId"]
    assert created.json()["request"]["status"] == "QUEUED"
    assert created.json()["request"]["changeDetectionEligible"] is True
    assert created.json()["request"]["volumeChangeEligible"] is True

    # ── ② 실제 워커 — 프로덕션과 동일한 HttpCoreClient(ASGI 로 이 앱에 붙인다) ──
    # httpx 0.28 의 ASGITransport 는 비동기 전용이라 HttpCoreClient(동기)와 못
    # 붙는다 — TestClient 자체가 httpx.Client 서브클래스이자 동기↔ASGI 브리지라
    # 그대로 주입한다(진짜 소켓은 없지만 진짜 ASGI 앱을 실제로 부른다).
    worker_http = TestClient(app)
    core_client = HttpCoreClient(
        "http://core.test", token=_WORKER_TOKEN, client=worker_http
    )
    storage_http = httpx.Client(transport=httpx.MockTransport(_storage_handler))
    try:
        run_comparison_request(
            request_id, core=core_client, work_dir=tmp_path, http_client=storage_http,
            now_message=lambda _msg: None,
        )
    finally:
        # ASGITransport 는 동기 close() 를 지원하지 않는다(httpx 0.28) — worker_http
        # 자체는 with 블록 없이 함수 종료 시 GC 된다(테스트 스코프, 실제 워커 프로세스는
        # HttpCoreClient.close() 를 정상 호출한다 — HttpCoreClient 는 실제 TCP
        # 소켓(httpx.HTTPTransport)에서만 close() 가 필요하고 이 테스트는 그 경로가
        # 아니다).
        storage_http.close()

    # ── ③ 결과 조회 — 사람 토큰으로 GET, 전이·결과 모두 실제 경로로 만들어졌다 ──
    final_request = human_client.get(f"/v1/comparison-requests/{request_id}")
    assert final_request.status_code == 200
    assert final_request.json()["request"]["status"] == "SUCCEEDED"

    cd = human_client.get(f"/v1/missions/{_CURRENT_MISSION_ID}/change-detection")
    assert cd.status_code == 200, cd.json()
    assert cd.json()["latest"]["changeDetectionId"] == request_id
    assert cd.json()["latest"]["candidateCount"] == 1  # 점 하나만 이동시켰다(손계산)
    assert cd.json()["latest"]["pointCount"] == 20

    vol = human_client.get(f"/v1/missions/{_CURRENT_MISSION_ID}/volume-changes")
    assert vol.status_code == 200, vol.json()
    assert vol.json()["reportCount"] == 1
    assert vol.json()["reports"][0]["report"]["volumeChangeId"] == request_id


# ── 재생 ─────────────────────────────────────────────────────────────────


def test_replay_reproduces_created_leased_and_transitioned_state(tmp_path: Path) -> None:
    fx = _Fixture(tmp_path)
    result = fx.create()
    request_id = result.record.request_id
    fx.store.acquire_lease(request_id, worker_id="worker-1", now=_NOW)
    fx.store.transition(
        request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )
    fx.store.transition(
        request_id, ProcessingJobStatus.SUCCEEDED, detail=None, actor="worker-1", now=_NOW
    )
    fx.store._journal.close()  # flock 해제 — 재기동을 흉내내려면 이전 writer 를 닫아야 한다.

    reopened = ComparisonRequestStore(
        DurableJournal(tmp_path / "comparison-requests.jsonl"),
        mission_store=fx.missions,
        processing_job_store=fx.jobs,
        analysis_readiness=lambda _mission_id: (True, None),
    )
    record = reopened.get(request_id)
    assert record is not None
    assert record.status is ProcessingJobStatus.SUCCEEDED
    assert record.change_detection_eligible is True
    assert record.volume_change_eligible is True
    assert record.processing_profile_digest == result.record.processing_profile_digest
    assert (
        record.baseline_source_bundle_digest
        == result.record.baseline_source_bundle_digest
    )
    assert (
        record.current_source_bundle_digest
        == result.record.current_source_bundle_digest
    )


def test_replay_refuses_request_whose_reference_no_longer_validates(tmp_path: Path) -> None:
    """journal 에 다른 현장을 가리키게 손으로 조작한 레코드가 있으면 재생이 거부한다."""
    fx = _Fixture(tmp_path)
    fx.create()
    fx.store._journal.close()

    journal_path = tmp_path / "comparison-requests.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    tampered = []
    for line in lines:
        raw = json.loads(line)
        if raw.get("kind") == "comparison-request-created":
            raw["request"]["currentJobId"] = "forged-job-id"
        tampered.append(json.dumps(raw))
    journal_path.write_text("\n".join(tampered) + "\n", encoding="utf-8")

    with pytest.raises(ComparisonRequestRecoveryError):
        ComparisonRequestStore(
            DurableJournal(journal_path),
            mission_store=fx.missions,
            processing_job_store=fx.jobs,
            analysis_readiness=lambda _mission_id: (True, None),
        )
