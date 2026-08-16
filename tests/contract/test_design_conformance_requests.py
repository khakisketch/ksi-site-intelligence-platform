"""설계 대비 잔량 **요청** 계약 (M4-A 7단계 — 생성 게이트·lease·입력·래스터 확인).

초점 넷:

**① 계산 전에 막는다.** 검증되지 않은 설계면, 수직기준 계열 불일치, 수직기준
미상 산출물, 구역 없음 — 전부 요청 생성 시점에 typed 거부다. 몇 분 뒤 FAILED 가
아니라 즉시 사유가 나와야 사용자가 무엇을 고칠지 안다.

**② 워커의 "올렸다"는 사실이 아니다.** ``diff-raster-verification`` 은 Core 가
스토리지 객체를 **직접 읽어 자기 hashlib 으로** 해시를 다시 계산하는 자리다 —
신고와 다르면 원장에 아무것도 남지 않는다.

**③ 객체 키는 결정적이다.** 같은 요청의 재시도는 같은 자리를 덮어쓴다(orphan 이
쌓이지 않는다). 종료된 요청에는 업로드 URL 도 확인도 내주지 않는다.

**④ lease 는 발명하지 않고 재사용한다.** ``leasing.py`` 의 만료 판정이 그대로
동작하는지를 경계값(직전·정확히·직후)으로 고정한다.

green≠작동: 처리 작업은 실제로 발급→lease→RUNNING→산출물 등록→SUCCEEDED 까지
진행하고(test_comparison_requests.py 의 픽스처를 그대로 재사용), 설계면도 실제로
등록→봉인→관측 대조를 거쳐 VERIFIED 로 만든다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_requests import (
    DesignConformanceRequestRecord,
    DesignConformanceRequestRecoveryError,
    DesignConformanceRequestStore,
    DesignConformanceRequestVerdict,
    build_design_conformance_raster_object_key,
    design_conformance_id_of,
    mount_design_conformance_requests,
    recompute_diff_raster_digest,
)
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.processing_jobs import ProcessingJobStatus
from ksi_event_contracts.design_surface import (
    DesignSurfaceDeclared,
    DesignSurfaceObserved,
    DesignSurfaceStatus,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)

# tests/contract 는 rootdir 기반 수집이라 같은 디렉터리 모듈을 직접 import 한다
# (test_runner.py 가 test_worker/test_comparison_worker 를 쓰는 것과 같은 관용구).
# 처리 작업 픽스처(발급→lease→RUNNING→산출물→SUCCEEDED)를 복제하지 않는다.
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _NOW,
    _OTHER_MISSION_ID,
    _OTHER_SITE_ID,
    _SITE_ID,
    _VIEWER_TOKEN,
    _WORKER_TOKEN,
    _artifact_spec,
    _job_store_impl,
    _mission_store,
    _registry,
    _site_store,
    _succeeded_job,
)

_ZONES: dict[str, dict[str, Any]] = {
    "zone-a": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
}
_ZONE_CRS = "EPSG:4326"

_DESIGN_BYTES = b"design-surface-geotiff-bytes"
_DESIGN_SHA = hashlib.sha256(_DESIGN_BYTES).hexdigest()

_RASTER_BYTES = b"diff-raster-geotiff-bytes"
_RASTER_DIGEST = f"sha256:{hashlib.sha256(_RASTER_BYTES).hexdigest()}"

_DSM_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)
_DESIGN_VERTICAL = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL,
    basis="설계사 제공 도면 표제부에 타원체고 명시",
    source=VerticalReferenceSource.USER_DECLARED,
)
#: 격자를 갖고 있지 **않은** 모델로 선언된 정표고 — 계열이 맞아도 이을 수 없다.
_ORTHOMETRIC_DESIGN_VERTICAL = VerticalReference(
    datum=VerticalDatum.ORTHOMETRIC_KNGEOID2018,
    basis="설계사가 국가 수준점 기준 정표고로 작성했다고 표기",
    source=VerticalReferenceSource.USER_DECLARED,
)
#: 실무 도면의 정상 경로 — 우리가 격자를 가진 모델로 선언된 해발 높이.
_ORTHOMETRIC_2024_DESIGN_VERTICAL = VerticalReference(
    datum=VerticalDatum.ORTHOMETRIC_KNGEOID2024,
    basis="설계사 제공 도면 표제부에 인천 평균해면 기준 표고 명시",
    source=VerticalReferenceSource.USER_DECLARED,
)


class FakeStorage:
    """메모리 오브젝트 스토리지 — presigned URL 은 문자열, 바이트는 진짜다.

    ``get_bytes`` 가 실제 바이트를 돌려주는 것이 이 파일에서 중요한 전부다:
    Core 의 재해싱 게이트가 **진짜로** 그 바이트를 읽는지를 시험하려면 여기서
    가짜를 돌려주면 안 된다.
    """

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.fail_get: bool = False

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://storage.invalid/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://storage.invalid/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        del content_type
        self.blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        if self.fail_get:
            raise EvidenceStorageError(f"스토리지 장애(테스트 강제): {object_key}")
        blob = self.blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        self.blobs.pop(object_key, None)


def _declared(
    *, sha256: str = _DESIGN_SHA, vertical: VerticalReference = _DESIGN_VERTICAL
) -> DesignSurfaceDeclared:
    return DesignSurfaceDeclared(crs="EPSG:5186", sha256=sha256, vertical_reference=vertical)


def _observed(*, sha256: str = _DESIGN_SHA) -> DesignSurfaceObserved:
    return DesignSurfaceObserved(
        sha256=sha256,
        crs="EPSG:5186",
        width=100,
        height=80,
        band_count=1,
        dtype="float32",
        pixel_size_x_m=0.5,
        pixel_size_y_m=0.5,
        transform=(0.5, 0.0, 200000.0, 0.0, -0.5, 500000.0),
        bounds_min_x=200000.0,
        bounds_min_y=499960.0,
        bounds_max_x=200050.0,
        bounds_max_y=500000.0,
        finite_cell_count=8000,
        measured_at=_NOW + timedelta(minutes=10),
        measured_by="worker-1",
    )


class Fixture:
    """VERIFIED 설계면 + SUCCEEDED DSM 작업 + 두 store 를 갖춘 실제 조립.

    ``design_vertical``/``dsm_vertical`` 을 바꿔 수직기준 게이트를 시험한다.
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        design_vertical: VerticalReference = _DESIGN_VERTICAL,
        dsm_vertical: VerticalReference | None = _DSM_VERTICAL,
        seal_only: bool = False,
        with_dsm: bool = True,
        design_sha256: str = _DESIGN_SHA,
    ) -> None:
        self.tmp_path = tmp_path
        # 종단 시험은 **진짜 GeoTIFF** 의 해시로 검증된 설계면을 만든다 — 그래야
        # 워커가 내려받은 바이트와 원장의 앵커가 실제로 같은 파일을 가리킨다.
        self.design_sha256 = design_sha256
        self.missions = _mission_store(tmp_path)
        self.sites = _site_store(tmp_path)
        self.jobs, self.source_media = _job_store_impl(tmp_path, self.missions, self.sites)
        artifacts = [_artifact_spec("point-cloud")]
        if with_dsm:
            artifacts.append(
                _artifact_spec(
                    "dsm",
                    kind=ProcessingArtifactKind.DSM,
                    vertical_reference=dsm_vertical,
                )
            )
        self.current_job_id = _succeeded_job(
            self.jobs, self.source_media, _CURRENT_MISSION_ID, *artifacts
        )
        self.other_site_job_id = _succeeded_job(
            self.jobs,
            self.source_media,
            _OTHER_MISSION_ID,
            _artifact_spec(
                "dsm", kind=ProcessingArtifactKind.DSM, vertical_reference=_DSM_VERTICAL
            ),
        )
        self.surfaces = DesignSurfaceStore(
            DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=self.sites
        )
        self.design_surface_id = self._design_surface(design_vertical, seal_only=seal_only)
        self.storage = FakeStorage()
        self.journal = DurableJournal(tmp_path / "design-conformance-requests.jsonl")
        self.requests = DesignConformanceRequestStore(
            self.journal,
            mission_store=self.missions,
            processing_job_store=self.jobs,
            design_surface_store=self.surfaces,
        )

    def _design_surface(self, vertical: VerticalReference, *, seal_only: bool) -> str:
        result = self.surfaces.register(
            _SITE_ID,
            "A공구 계획고",
            "Rev.C",
            _declared(sha256=self.design_sha256, vertical=vertical),
            registered_by="op-1",
            now=_NOW,
        )
        assert result.surface is not None
        design_surface_id = result.surface.design_surface_id
        self.surfaces.seal(design_surface_id, sealed_by="op-1", now=_NOW)
        if not seal_only:
            observation = self.surfaces.record_observation(
                design_surface_id,
                _observed(sha256=self.design_sha256),
                now=_NOW + timedelta(minutes=10),
            )
            assert observation.surface is not None
            assert observation.surface.status is DesignSurfaceStatus.VERIFIED, observation
        return design_surface_id

    def create(self, **overrides: Any) -> Any:
        payload: dict[str, Any] = {
            "design_surface_id": self.design_surface_id,
            "current_job_id": self.current_job_id,
            "zones": _ZONES,
            "zone_crs": _ZONE_CRS,
            "requested_by": "op-1",
            "now": _NOW,
        }
        payload.update(overrides)
        mission_id = payload.pop("mission_id", _CURRENT_MISSION_ID)
        return self.requests.create(mission_id, **payload)

    def created(self, **overrides: Any) -> DesignConformanceRequestRecord:
        result = self.create(**overrides)
        assert result.verdict is DesignConformanceRequestVerdict.CREATED, result
        assert result.record is not None
        return result.record

    def leased(self, request_id: str, *, worker_id: str = "worker-1") -> None:
        """HTTP 경로는 서버 시계를 쓰므로 lease 도 **실제 지금**으로 잡는다 —
        고정 시각(_NOW)으로 잡으면 라우터가 그 lease 를 만료로 본다."""
        result = self.requests.acquire_lease(
            request_id, worker_id=worker_id, now=datetime.now(UTC)
        )
        assert result.verdict is DesignConformanceRequestVerdict.LEASED, result

    def running(self, request_id: str, *, worker_id: str = "worker-1") -> None:
        result = self.requests.transition(
            request_id,
            ProcessingJobStatus.RUNNING,
            detail=None,
            actor=worker_id,
            now=datetime.now(UTC),
        )
        assert result.verdict is DesignConformanceRequestVerdict.TRANSITIONED, result

    def close(self) -> None:
        self.journal.close()

    def upload_raster(
        self, record: DesignConformanceRequestRecord, data: bytes = _RASTER_BYTES
    ) -> str:
        """워커의 presigned PUT 을 흉내 낸다 — 키는 Core 가 정한 그 자리다."""
        object_key = build_design_conformance_raster_object_key(
            site_id=record.site_id, design_conformance_id=record.design_conformance_id
        )
        self.storage.put_bytes(object_key, data, content_type="application/octet-stream")
        return object_key

    def app(self) -> FastAPI:
        app = FastAPI()
        mount_auth(app, _registry())
        mount_design_conformance_requests(app, self.requests, self.storage)
        return app


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 생성 게이트 ───────────────────────────────────────────────────────────


def test_created_request_snapshots_the_verified_surface_hash(fixture: Fixture) -> None:
    """요청은 설계면의 **관측된** 해시를 값으로 복사해 둔다 — 리포트의 앵커다."""
    record = fixture.created()
    surface = fixture.surfaces.get(fixture.design_surface_id)
    assert surface is not None and surface.observed is not None
    assert record.design_surface_sha256 == surface.observed.sha256
    assert record.status is ProcessingJobStatus.QUEUED
    assert record.current.artifact_id == "dsm"
    assert record.zones == _ZONES and record.zone_crs == _ZONE_CRS
    # policy 는 요청 시점 스냅샷이다(참조가 아니라 값).
    assert record.policy.volume_threshold_m > 0
    # 리포트 id 는 요청 id 에서 결정적으로 도출된다.
    assert record.design_conformance_id == design_conformance_id_of(record.request_id)


def test_sealed_but_unverified_surface_is_refused(tmp_path: Path) -> None:
    """봉인만으로는 그 파일이 무엇인지 아무도 확인하지 않았다 — 비교 입력 자격이 없다."""
    fixture = Fixture(tmp_path, seal_only=True)
    result = fixture.create()
    assert result.verdict is DesignConformanceRequestVerdict.DESIGN_SURFACE_NOT_VERIFIED
    assert fixture.requests.list_for_mission(_CURRENT_MISSION_ID) == []


def test_orthometric_design_that_a_geoid_grid_can_bridge_is_accepted(
    tmp_path: Path,
) -> None:
    """[핵심] 해발 도면 × 타원체고 DSM — **요청을 만든다**(실무 도면의 정상 경로).

    Core 는 "이을 수 있는 종류인가"만 답한다. 격자가 그 배포에 실제로 붙어 있는지는
    워커의 환경(``KSI_GEOID_GRID``)이라 Core 가 알 수 없는 사실이고, 여기서 미리
    막으면 격자를 붙여 둔 배포에서도 한국 도면이 전부 거부된다.
    """
    fixture = Fixture(tmp_path, design_vertical=_ORTHOMETRIC_2024_DESIGN_VERTICAL)
    result = fixture.create()
    assert result.verdict is DesignConformanceRequestVerdict.CREATED
    record = result.record
    assert record is not None
    # 요청은 **선언된 그대로**를 싣는다 — 변환은 워커가 하고, 지시가 그 사실을
    # 미리 고쳐 쓰지 않는다(그러면 무엇을 변환했는지 되짚을 수 없다).
    assert record.design_vertical_reference.datum is VerticalDatum.ORTHOMETRIC_KNGEOID2024
    assert fixture.requests.list_pending(now=_NOW) == [record]


def test_incompatible_vertical_datum_is_refused_before_any_computation(tmp_path: Path) -> None:
    """[핵심][음성] 격자를 가진 적 없는 모델(KNGeoid18)로 선언된 정표고는 즉시 거부.

    격자를 확보한 뒤에도 이 거부는 남아야 한다 — 되돌릴 격자는 그 선언이 말하는
    **모델의** 격자여야 하고, 다른 모델로 대신 변환하면 리포트가 말하는 기준과
    실제로 쓴 기준이 갈라진다.
    """
    fixture = Fixture(tmp_path, design_vertical=_ORTHOMETRIC_DESIGN_VERTICAL)
    result = fixture.create()
    assert result.verdict is DesignConformanceRequestVerdict.VERTICAL_DATUM_INCOMPATIBLE
    assert result.detail is not None and "20~30m" in result.detail
    # 원장에 아무것도 남지 않는다 — 워커가 집어갈 요청 자체가 없다.
    assert fixture.requests.list_pending(now=_NOW) == []


def test_dsm_without_vertical_reference_is_refused(tmp_path: Path) -> None:
    """수직기준이 기록되기 전에 등록된 산출물 — 설계 대비는 fail-closed 다."""
    fixture = Fixture(tmp_path, dsm_vertical=None)
    result = fixture.create()
    assert result.verdict is DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN
    assert result.detail is not None and "재처리" in result.detail


def test_missing_zones_is_refused(fixture: Fixture) -> None:
    assert (
        fixture.create(zones=None).verdict is DesignConformanceRequestVerdict.ZONES_REQUIRED
    )
    assert (
        fixture.create(zones={}).verdict is DesignConformanceRequestVerdict.ZONES_REQUIRED
    )
    assert (
        fixture.create(zone_crs=None).verdict
        is DesignConformanceRequestVerdict.ZONES_REQUIRED
    )


@pytest.mark.parametrize(
    "bad_polygon",
    [
        {"type": "Point", "coordinates": [1, 2]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},  # 3점(닫힌 것 포함)
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},  # 안 닫힘
        {"type": "Polygon", "coordinates": [[["a", "b"], [1, 0], [1, 1], ["a", "b"]]]},
        {"type": "Polygon"},  # coordinates 키 없음
        {"nonsense": True},
    ],
)
def test_ad_hoc_zone_geometry_is_validated_at_request_time(
    fixture: Fixture, bad_polygon: dict[str, object]
) -> None:
    """2026-08-13 프로젝트 두뇌 재감사 확정 발견의 회귀 방지.

    이 검사가 없으면 여섯 변형 전부 CREATED 로 통과해 durable 저널에 실렸고,
    실패는 몇 분 뒤 워커가 이해할 수 없는 예외로 대신 말했다. 등록된 작업구역
    경로는 이미 같은 검사를 받는다(WorkArea 계약) — 즉석 경로만 비어 있었다.
    """
    result = fixture.create(zones={"zone-a": bad_polygon})
    assert result.verdict is DesignConformanceRequestVerdict.ZONES_INVALID, result
    assert result.detail is not None and "zone-a" in result.detail


def test_ad_hoc_zone_count_is_capped(fixture: Fixture) -> None:
    many_zones = {
        f"zone-{i}": {
            "type": "Polygon",
            "coordinates": [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]],
        }
        for i in range(65)
    }
    result = fixture.create(zones=many_zones)
    assert result.verdict is DesignConformanceRequestVerdict.ZONES_INVALID, result
    assert result.detail is not None and "65" in result.detail


def test_job_without_dsm_is_refused(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, with_dsm=False)
    assert fixture.create().verdict is DesignConformanceRequestVerdict.NO_DSM_ARTIFACT


def test_design_surface_from_another_site_is_refused(fixture: Fixture) -> None:
    """다른 현장의 계획고와는 비교할 수 없다."""
    result = fixture.create(
        mission_id=_OTHER_MISSION_ID, current_job_id=fixture.other_site_job_id
    )
    assert result.verdict is DesignConformanceRequestVerdict.SITE_MISMATCH
    assert result.detail is not None and _OTHER_SITE_ID in result.detail


def test_unknown_design_surface_and_mission_are_refused(fixture: Fixture) -> None:
    assert (
        fixture.create(design_surface_id="nope").verdict
        is DesignConformanceRequestVerdict.UNKNOWN_DESIGN_SURFACE
    )
    assert (
        fixture.create(mission_id="mission-nope").verdict
        is DesignConformanceRequestVerdict.UNKNOWN_MISSION
    )


def test_mission_mismatch_is_refused(fixture: Fixture) -> None:
    """경로의 missionId 가 작업 소속과 다르면 장식이 아니라 거부 사유다."""
    result = fixture.create(mission_id=_OTHER_MISSION_ID)
    assert result.verdict is DesignConformanceRequestVerdict.MISSION_MISMATCH


def test_same_shape_is_idempotent_and_different_zones_make_a_new_request(
    fixture: Fixture,
) -> None:
    first = fixture.created()
    again = fixture.create()
    assert again.verdict is DesignConformanceRequestVerdict.ALREADY_REQUESTED
    assert again.record is not None and again.record.request_id == first.request_id

    other_zones = {"zone-b": _ZONES["zone-a"]}
    third = fixture.create(zones=other_zones)
    assert third.verdict is DesignConformanceRequestVerdict.CREATED
    assert third.record is not None and third.record.request_id != first.request_id


# ── lease (leasing.py 재사용 확인) ────────────────────────────────────────


def test_lease_expiry_boundary_is_exclusive(fixture: Fixture) -> None:
    """만료 **직전**엔 남의 것, **정확히 그 순간**부터 회수 가능(``JobLease.is_active``)."""
    record = fixture.created()
    ttl = timedelta(minutes=15)
    granted = fixture.requests.acquire_lease(
        record.request_id, worker_id="worker-1", now=_NOW, ttl=ttl
    )
    # QUEUED 는 lease 와 무관하게 늘 후보다(``is_claimable``) — 만료가 회수로
    # 이어지는 것을 보려면 RUNNING 이어야 한다(죽은 워커가 쥔 채 멈춘 작업).
    assert (
        fixture.requests.transition(
            record.request_id,
            ProcessingJobStatus.RUNNING,
            detail=None,
            actor="worker-1",
            now=_NOW,
        ).verdict
        is DesignConformanceRequestVerdict.TRANSITIONED
    )
    assert granted.record is not None and granted.record.lease is not None
    expires_at = granted.record.lease.expires_at

    just_before = expires_at - timedelta(seconds=1)
    just_after = expires_at + timedelta(seconds=1)

    # 회수 후보 판정(``leasing.is_claimable``) — 만료 시각이 경계다.
    assert fixture.requests.list_pending(now=just_before) == []
    assert [r.request_id for r in fixture.requests.list_pending(now=expires_at)] == [
        record.request_id
    ]
    assert [r.request_id for r in fixture.requests.list_pending(now=just_after)] == [
        record.request_id
    ]

    # 소유권 판정(``leasing.check_lease``) — 같은 경계를 같은 방향으로 본다.
    assert (
        fixture.requests.acquire_lease(
            record.request_id, worker_id="worker-2", now=just_before
        ).verdict
        is DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER
    )
    # 정확히 만료 시각부터는 남의 것이 아니다(``now < expires_at`` 이 활성 조건).
    assert (
        fixture.requests.acquire_lease(
            record.request_id, worker_id="worker-2", now=expires_at
        ).verdict
        is DesignConformanceRequestVerdict.LEASED
    )


def test_same_worker_release_is_a_renewal_that_keeps_granted_at(fixture: Fixture) -> None:
    record = fixture.created()
    first = fixture.requests.acquire_lease(record.request_id, worker_id="w-1", now=_NOW)
    later = _NOW + timedelta(minutes=1)
    renewed = fixture.requests.acquire_lease(record.request_id, worker_id="w-1", now=later)
    assert renewed.verdict is DesignConformanceRequestVerdict.LEASE_RENEWED
    assert first.record is not None and first.record.lease is not None
    assert renewed.record is not None and renewed.record.lease is not None
    assert renewed.record.lease.granted_at == first.record.lease.granted_at
    assert renewed.record.lease.expires_at > first.record.lease.expires_at


def test_transition_requires_the_lease(fixture: Fixture) -> None:
    record = fixture.created()
    assert (
        fixture.requests.transition(
            record.request_id,
            ProcessingJobStatus.RUNNING,
            detail=None,
            actor="w-1",
            now=_NOW,
        ).verdict
        is DesignConformanceRequestVerdict.LEASE_REQUIRED
    )
    fixture.leased(record.request_id, worker_id="w-1")
    assert (
        fixture.requests.transition(
            record.request_id,
            ProcessingJobStatus.RUNNING,
            detail=None,
            actor="w-1",
            now=_NOW,
        ).verdict
        is DesignConformanceRequestVerdict.TRANSITIONED
    )
    # 종료 상태에서 다시 전이하면 ILLEGAL_TRANSITION(끝난 결론은 고쳐 쓰지 않는다).
    fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail=None,
        actor="w-1",
        now=_NOW,
    )
    assert (
        fixture.requests.transition(
            record.request_id,
            ProcessingJobStatus.FAILED,
            detail=None,
            actor="w-1",
            now=_NOW,
        ).verdict
        is DesignConformanceRequestVerdict.ILLEGAL_TRANSITION
    )


# ── 차분 래스터: 자리 발급과 Core 의 재해싱 ───────────────────────────────


def test_raster_object_key_is_deterministic_and_retry_overwrites_it(
    fixture: Fixture,
) -> None:
    """[핵심 (c)] 같은 요청의 재시도는 같은 자리를 덮어쓴다 — orphan 이 쌓이지 않는다."""
    record = fixture.created()
    first_key = fixture.upload_raster(record, b"first-attempt")
    second_key = fixture.upload_raster(record, _RASTER_BYTES)
    assert first_key == second_key
    assert list(fixture.storage.blobs) == [first_key]
    assert fixture.storage.blobs[first_key] == _RASTER_BYTES


def test_raster_object_key_refuses_path_escaping_identifiers() -> None:
    with pytest.raises(ValueError, match="경로-안전"):
        build_design_conformance_raster_object_key(
            site_id="../escape", design_conformance_id="dcf-1"
        )
    with pytest.raises(ValueError, match="경로-안전"):
        build_design_conformance_raster_object_key(
            site_id=_SITE_ID, design_conformance_id="a/b"
        )


def test_core_recomputes_the_digest_from_storage_bytes(fixture: Fixture) -> None:
    """Core 는 워커의 신고가 아니라 **바이트**에서 digest 를 만든다."""
    record = fixture.created()
    object_key = fixture.upload_raster(record)
    digest, size = recompute_diff_raster_digest(fixture.storage, object_key)
    assert digest == _RASTER_DIGEST
    assert size == len(_RASTER_BYTES)


def test_verification_endpoint_records_only_when_the_bytes_agree(fixture: Fixture) -> None:
    """[핵심 ②] 신고와 실제가 다르면 원장에 아무것도 남지 않는다."""
    record = fixture.created()
    fixture.leased(record.request_id)
    fixture.upload_raster(record)
    client = TestClient(fixture.app())

    lying = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-verification",
        json={"digest": f"sha256:{'b' * 64}", "sizeBytes": len(_RASTER_BYTES)},
        headers=_auth(_WORKER_TOKEN),
    )
    assert lying.status_code == 422
    assert lying.json()["verdict"] == "DIFF_RASTER_DIGEST_MISMATCH"
    # Core 가 실제로 계산한 값을 되돌려 준다(워커가 무엇과 어긋났는지 알아야 한다).
    assert lying.json()["digest"] == _RASTER_DIGEST
    stored = fixture.requests.get(record.request_id)
    assert stored is not None and stored.diff_raster is None

    honest = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-verification",
        json={"digest": _RASTER_DIGEST, "sizeBytes": len(_RASTER_BYTES)},
        headers=_auth(_WORKER_TOKEN),
    )
    assert honest.status_code == 201, honest.json()
    assert honest.json()["verdict"] == "DIFF_RASTER_VERIFIED"
    verified = fixture.requests.get(record.request_id)
    assert verified is not None and verified.diff_raster is not None
    assert verified.diff_raster.digest == _RASTER_DIGEST
    assert verified.diff_raster.verified_by == "worker-1"


def test_size_mismatch_alone_is_refused(fixture: Fixture) -> None:
    """길이 대조도 곁들인다 — 스토리지 포트가 크기를 따로 주지 않으므로 읽은 길이로 본다."""
    record = fixture.created()
    fixture.leased(record.request_id)
    fixture.upload_raster(record)
    client = TestClient(fixture.app())
    response = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-verification",
        json={"digest": _RASTER_DIGEST, "sizeBytes": len(_RASTER_BYTES) + 1},
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "DIFF_RASTER_DIGEST_MISMATCH"


def test_missing_object_is_not_silently_accepted(fixture: Fixture) -> None:
    """올렸다는 자리에 아무것도 없으면 확인이 아니라 거부다."""
    record = fixture.created()
    fixture.leased(record.request_id)
    client = TestClient(fixture.app())
    response = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-verification",
        json={"digest": _RASTER_DIGEST, "sizeBytes": len(_RASTER_BYTES)},
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 503
    assert response.json()["verdict"] == "DIFF_RASTER_UNREADABLE"
    assert response.headers["Retry-After"] == "30"


def test_terminal_request_gets_no_upload_url_and_no_verification(fixture: Fixture) -> None:
    """끝난 요청의 래스터는 다시 쓰지 않는다 — 굳은 리포트의 지도가 바뀌는 창을 닫는다."""
    record = fixture.created()
    fixture.leased(record.request_id)
    fixture.running(record.request_id)
    assert (
        fixture.requests.transition(
            record.request_id,
            ProcessingJobStatus.SUCCEEDED,
            detail=None,
            actor="worker-1",
            now=datetime.now(UTC),
        ).verdict
        is DesignConformanceRequestVerdict.TRANSITIONED
    )
    client = TestClient(fixture.app())
    upload = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-upload-url",
        headers=_auth(_WORKER_TOKEN),
    )
    assert upload.status_code == 409
    assert upload.json()["verdict"] == "REQUEST_NOT_ACTIVE"
    verification = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-verification",
        json={"digest": _RASTER_DIGEST, "sizeBytes": len(_RASTER_BYTES)},
        headers=_auth(_WORKER_TOKEN),
    )
    assert verification.status_code == 409


def test_upload_url_and_verification_require_the_lease(fixture: Fixture) -> None:
    record = fixture.created()
    client = TestClient(fixture.app())
    upload = client.post(
        f"/v1/design-conformance-requests/{record.request_id}/diff-raster-upload-url",
        headers=_auth(_WORKER_TOKEN),
    )
    assert upload.status_code == 409
    assert upload.json()["verdict"] == "LEASE_REQUIRED"


# ── HTTP 표면 ─────────────────────────────────────────────────────────────


def test_input_gives_both_urls_and_ids_to_the_leaseholder(fixture: Fixture) -> None:
    record = fixture.created()
    fixture.leased(record.request_id)
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/design-conformance-requests/{record.request_id}/input",
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 200, response.json()
    payload = response.json()["input"]
    assert payload["designSurfaceSha256"] == _DESIGN_SHA
    assert payload["designConformanceId"] == record.design_conformance_id
    assert payload["diffRasterId"] == record.diff_raster_id
    assert "design-surfaces" in payload["designSurfaceUrl"]
    assert "processing-jobs" in payload["currentUrl"] or "jobs" in payload["currentUrl"]
    assert payload["currentVerticalReference"]["datum"] == "ellipsoidal_native"
    assert payload["designVerticalReference"]["datum"] == "ellipsoidal"
    assert payload["zones"] == _ZONES
    assert payload["status"] == "QUEUED"


def test_input_is_refused_without_the_lease(fixture: Fixture) -> None:
    record = fixture.created()
    client = TestClient(fixture.app())
    response = client.get(
        f"/v1/design-conformance-requests/{record.request_id}/input",
        headers=_auth(_WORKER_TOKEN),
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "LEASE_REQUIRED"


def test_worker_cannot_create_and_viewer_cannot_lease(fixture: Fixture) -> None:
    """사람이 지시하고 워커가 실행한다 — 두 표면의 권한이 겹치지 않는다."""
    client = TestClient(fixture.app())
    body = {
        "designSurfaceId": fixture.design_surface_id,
        "currentJobId": fixture.current_job_id,
        "zones": _ZONES,
        "zoneCrs": _ZONE_CRS,
    }
    assert (
        client.post(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
            json=body,
            headers=_auth(_WORKER_TOKEN),
        ).status_code
        == 403
    )
    created = client.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
        json=body,
        headers=_auth(_ADMIN_TOKEN),
    )
    assert created.status_code == 201, created.json()
    request_id = created.json()["request"]["requestId"]
    assert (
        client.post(
            f"/v1/design-conformance-requests/{request_id}/lease",
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 403
    )


def test_pending_queue_hides_everything_but_the_id(fixture: Fixture) -> None:
    record = fixture.created()
    client = TestClient(fixture.app())
    response = client.get("/v1/design-conformance-requests", headers=_auth(_WORKER_TOKEN))
    assert response.status_code == 200
    listed = response.json()["requests"]
    assert [item["requestId"] for item in listed] == [record.request_id]
    # requestId·requestedAt 말고는 아무것도 새지 않는다(최소권한).
    assert set(listed[0]) == {"requestId", "requestedAt"}


# ── 재생 ──────────────────────────────────────────────────────────────────


def _reopen(fixture: Fixture) -> DesignConformanceRequestStore:
    """같은 원장을 다시 연다 — ``DurableJournal`` 은 단일 writer 라 먼저 닫는다."""
    fixture.close()
    return DesignConformanceRequestStore(
        DurableJournal(fixture.tmp_path / "design-conformance-requests.jsonl"),
        mission_store=fixture.missions,
        processing_job_store=fixture.jobs,
        design_surface_store=fixture.surfaces,
    )


def test_replay_restores_request_lease_transition_and_verification(fixture: Fixture) -> None:
    record = fixture.created()
    assert (
        fixture.requests.acquire_lease(
            record.request_id, worker_id="worker-1", now=_NOW
        ).verdict
        is DesignConformanceRequestVerdict.LEASED
    )
    fixture.requests.transition(
        record.request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )
    fixture.requests.record_diff_raster_verification(
        record.request_id,
        digest=_RASTER_DIGEST,
        size_bytes=len(_RASTER_BYTES),
        worker_id="worker-1",
        now=_NOW + timedelta(minutes=2),
    )

    replayed = _reopen(fixture).get(record.request_id)
    assert replayed is not None
    assert replayed.status is ProcessingJobStatus.RUNNING
    assert replayed.lease is not None and replayed.lease.worker_id == "worker-1"
    assert replayed.diff_raster is not None
    assert replayed.diff_raster.digest == _RASTER_DIGEST
    assert replayed.diff_raster.verified_at == _NOW + timedelta(minutes=2)
    assert replayed.design_surface_sha256 == _DESIGN_SHA
    assert replayed.policy == record.policy


def test_replay_refuses_a_request_that_the_live_gate_would_reject(fixture: Fixture) -> None:
    """journal 에 심어진 "미지 설계면 요청"은 기동을 막는다(fail-closed)."""
    fixture.created()
    journal_path = fixture.tmp_path / "design-conformance-requests.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace(f'"{fixture.design_surface_id}"', '"ds-does-not-exist"')
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(DesignConformanceRequestRecoveryError, match="기록될 수 없는 요청"):
        _reopen(fixture)


def test_replay_refuses_an_unknown_record_kind(fixture: Fixture) -> None:
    fixture.created()
    journal_path = fixture.tmp_path / "design-conformance-requests.jsonl"
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "made-up", "requestId": "x"}\n')
    with pytest.raises(DesignConformanceRequestRecoveryError, match="알 수 없는 journal"):
        _reopen(fixture)


# ── 리포트 없는 SUCCEEDED · 리포트 기록 후 래스터 재작성 (2026-08-16 독립 검토) ──
#
# 두 게이트 다 리포트 원장을 봐야 판정되므로, 요청 저장소는 술어를 주입받는다
# (``bind_report_existence`` — 조립 표가 건다). 픽스처는 기본적으로 주입하지
# 않으므로 여기서 명시적으로 건다.


def test_succeeded_without_a_recorded_report_is_refused(fixture: Fixture) -> None:
    """[핵심] lease 를 쥔 워커가 리포트를 한 번도 올리지 않고 성공만 선언할 수 없다.

    막지 않으면 요청 목록은 SUCCEEDED 인데 리포트 조회는 404 인 모순이 남고,
    라우터의 자동 연동이 그 위에 구역 추출 요청까지 발급한다.
    """
    fixture.requests.bind_report_existence(lambda _dcid: False)
    record = fixture.created()
    assert (
        fixture.requests.acquire_lease(
            record.request_id, worker_id="worker-1", now=_NOW
        ).verdict
        is DesignConformanceRequestVerdict.LEASED
    )
    fixture.requests.transition(
        record.request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )

    result = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail="다 했다(주장)",
        actor="worker-1",
        now=_NOW,
    )
    assert result.verdict is DesignConformanceRequestVerdict.NO_REPORT_RECORDED, result
    # 상태가 실제로 안 넘어갔는지까지 본다 — verdict 만 바꾸고 넘기면 의미가 없다.
    still = fixture.requests.get(record.request_id)
    assert still is not None and still.status is ProcessingJobStatus.RUNNING


def test_succeeded_is_allowed_once_a_report_exists(fixture: Fixture) -> None:
    """게이트가 정상 경로를 막지 않는다 — 리포트가 있으면 그대로 성공한다."""
    fixture.requests.bind_report_existence(lambda _dcid: True)
    record = fixture.created()
    fixture.requests.acquire_lease(record.request_id, worker_id="worker-1", now=_NOW)
    fixture.requests.transition(
        record.request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )

    result = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail=None,
        actor="worker-1",
        now=_NOW,
    )
    assert result.verdict is DesignConformanceRequestVerdict.TRANSITIONED, result


def test_failed_does_not_require_a_report(fixture: Fixture) -> None:
    """실패는 결과가 없는 것이 정상이다 — FAILED 에까지 리포트를 요구하면
    워커가 실패를 보고할 길이 막힌다."""
    fixture.requests.bind_report_existence(lambda _dcid: False)
    record = fixture.created()
    fixture.requests.acquire_lease(record.request_id, worker_id="worker-1", now=_NOW)
    fixture.requests.transition(
        record.request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )

    result = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.FAILED,
        detail="지오이드 격자 없음",
        actor="worker-1",
        now=_NOW,
    )
    assert result.verdict is DesignConformanceRequestVerdict.TRANSITIONED, result


def test_report_existence_is_reported_through_the_public_predicate(
    fixture: Fixture,
) -> None:
    """래스터 두 라우트가 이 술어로 판정한다 — 미주입이면 기존 동작(False)."""
    record = fixture.created()
    assert fixture.requests.report_already_recorded(record.design_conformance_id) is False

    fixture.requests.bind_report_existence(
        lambda dcid: dcid == record.design_conformance_id
    )
    assert fixture.requests.report_already_recorded(record.design_conformance_id) is True
    assert fixture.requests.report_already_recorded("다른-id") is False


def test_report_existence_is_checked_outside_the_request_lock(fixture: Fixture) -> None:
    """[회귀] 교착 방지 — 요청 락을 쥔 채 리포트 원장을 부르지 않는다.

    리포트 원장은 설계상 이 저장소를 참조한다(``record()`` 가 report-lock 을 쥔 채
    ``get_by_design_conformance_id`` 를 부른다). 그래서 이쪽이 request-lock 을 쥔 채
    리포트 원장을 부르면 AB-BA 교착이 닫힌다 — 라우트가 sync ``def`` 라 FastAPI 가
    스레드풀에서 돌리므로 실제로 동시에 뛴다.

    술어 안에서 **요청 락을 다시 잡아본다**: 락 밖에서 불렸다면 즉시 잡히고,
    안에서 불렸다면 non-reentrant 라 잡히지 않는다(그때 이 테스트가 실패한다).
    """
    record = fixture.created()
    fixture.requests.acquire_lease(record.request_id, worker_id="worker-1", now=_NOW)
    fixture.requests.transition(
        record.request_id, ProcessingJobStatus.RUNNING, detail=None, actor="worker-1", now=_NOW
    )

    observed: dict[str, bool] = {}

    def predicate(_dcid: str) -> bool:
        # 요청 저장소의 락이 이 시점에 풀려 있어야 한다.
        acquired = fixture.requests._lock.acquire(blocking=False)
        observed["lock_free"] = acquired
        if acquired:
            fixture.requests._lock.release()
        return False

    fixture.requests.bind_report_existence(predicate)
    result = fixture.requests.transition(
        record.request_id,
        ProcessingJobStatus.SUCCEEDED,
        detail=None,
        actor="worker-1",
        now=_NOW,
    )

    assert observed.get("lock_free") is True, (
        "리포트 존재 술어가 요청 락을 쥔 채 불렸다 — 리포트 원장이 반대 방향으로 "
        "이 저장소를 부르므로 AB-BA 교착이 된다"
    )
    # 게이트 자체는 그대로 동작해야 한다(술어가 False 를 돌려줬다).
    assert result.verdict is DesignConformanceRequestVerdict.NO_REPORT_RECORDED, result
