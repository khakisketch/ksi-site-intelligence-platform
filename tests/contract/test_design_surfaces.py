"""설계 기준면 원장 계약 (M4-A 6단계 — 등록·봉인·관측 대조).

초점 다섯:

1. **SEALED 는 사실이 아니라 주장이다** — 봉인은 스토리지를 읽지 않고, 그 상태의
   설계면은 비교 입력 자격이 없다. 관측은 SEALED 에서만 받는다(순서 강제).
2. **판정은 Core 가 한다** — 워커는 잰 값만 보내고 "검증됨"을 보낼 수 없다.
   거부 사유 8종이 전부 typed verdict 로 나온다.
3. **모르는 수직 CRS 를 조용히 넘기지 않는다** — ``vertical_datum_from_epsg`` 가
   던지는 예외를 삼키면 정표고 도면이 타원체고로 둔갑해 20~30m 가 섞인다.
4. **재생도 같은 대조를 다시 태운다** — journal 의 판정을 손으로 고쳐도 측정값이
   선언과 어긋나면 기동이 거부된다.
5. **워커에게 정답을 주지 않는다** — 검증 대기 목록에 신고 sha256·CRS 가 없다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.design_surfaces import (
    _OBSERVATION_STATUS,
    _REGISTER_STATUS,
    _SEAL_STATUS,
    DesignSurfaceObservationVerdict,
    DesignSurfaceRecoveryError,
    DesignSurfaceRegisterVerdict,
    DesignSurfaceRejectionReason,
    DesignSurfaceSealVerdict,
    DesignSurfaceStore,
    build_design_surface_canonical_object_key,
    build_design_surface_object_key,
    evaluate_observation,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.sites import SiteFrame, SiteStore
from ksi_event_contracts.design_surface import (
    KSI_LANDXML_TIN_PARSER_VERSION,
    DesignSurface,
    DesignSurfaceDeclared,
    DesignSurfaceObserved,
    DesignSurfaceStatus,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_geo_spatial.tin_surface import CANONICAL_TIN_NORMALIZATION_PROFILE

_SITE_ID = "site-001"
_OTHER_SITE_ID = "site-002"
_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)
_NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
_LATER = _NOW + timedelta(minutes=5)
_MEASURED_AT = _NOW + timedelta(minutes=10)

_ADMIN_TOKEN = "design-surface-admin"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "design-surface-viewer"  # noqa: S105
_WORKER_TOKEN = "design-surface-worker"  # noqa: S105
_OTHER_ORG_ADMIN_TOKEN = "design-surface-other-org-admin"  # noqa: S105
_OTHER_ORG_VIEWER_TOKEN = "design-surface-other-org-viewer"  # noqa: S105
_OTHER_ORG_WORKER_TOKEN = "design-surface-other-org-worker"  # noqa: S105

_SHA = hashlib.sha256(b"design-surface-bytes").hexdigest()
_OTHER_SHA = hashlib.sha256(b"other-bytes").hexdigest()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="op-1", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
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
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1", kind=PrincipalKind.PROCESSING_WORKER, role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_ORG_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="other-op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_ORG_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="other-vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OTHER_ORG_WORKER_TOKEN),
                principal=Principal(
                    principal_id="other-worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                    organization_id="org-2",
                ),
            ),
        ]
    )


def _vertical(datum: VerticalDatum = VerticalDatum.ELLIPSOIDAL) -> VerticalReference:
    return VerticalReference(
        datum=datum,
        basis="설계사 제공 도면 표제부에 타원체고 명시",
        source=VerticalReferenceSource.USER_DECLARED,
    )


def _declared(
    *, sha256: str = _SHA, crs: str = "EPSG:5186", **overrides: Any
) -> DesignSurfaceDeclared:
    base: dict[str, Any] = {
        "crs": crs,
        "sha256": sha256,
        "vertical_reference": _vertical(),
    }
    return DesignSurfaceDeclared(**{**base, **overrides})


def _observed(**overrides: Any) -> DesignSurfaceObserved:
    base: dict[str, Any] = {
        "sha256": _SHA,
        "crs": "EPSG:5186",
        "width": 100,
        "height": 80,
        "band_count": 1,
        "dtype": "float32",
        "pixel_size_x_m": 0.5,
        "pixel_size_y_m": 0.5,
        "transform": (0.5, 0.0, 200000.0, 0.0, -0.5, 500000.0),
        "bounds_min_x": 200000.0,
        "bounds_min_y": 499960.0,
        "bounds_max_x": 200050.0,
        "bounds_max_y": 500000.0,
        "finite_cell_count": 8000,
        "measured_at": _MEASURED_AT,
        "measured_by": "worker-1",
    }
    return DesignSurfaceObserved(**{**base, **overrides})


def _site_store(tmp_path: Path, *, tag: str = "1") -> SiteStore:
    """현장 2곳이 등록된 SiteStore.

    ``tag`` 로 저널 파일을 가르는 이유: ``DurableJournal`` 은 단일 writer 락을
    잡으므로, 재생 테스트가 같은 tmp_path 에서 두 번째 store 를 열 때 같은
    ``sites.jsonl`` 을 다시 열면 락 충돌로 죽는다(테스트가 검증하려는 것과
    무관한 실패).
    """
    return _site_store_with_journal(tmp_path, tag=tag)[0]


def _site_store_with_journal(
    tmp_path: Path, *, tag: str
) -> tuple[SiteStore, DurableJournal]:
    journal = DurableJournal(tmp_path / f"sites-{tag}.jsonl")
    store = SiteStore(journal)
    for site_id in (_SITE_ID, _OTHER_SITE_ID):
        assert (
            store.register(
                site_id, "테스트 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
            ).verdict.value
            == "REGISTERED"
        )
    return store, journal


@pytest.fixture
def store(tmp_path: Path) -> DesignSurfaceStore:
    return DesignSurfaceStore(
        DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=_site_store(tmp_path)
    )


def _registered(store: DesignSurfaceStore, **overrides: Any) -> str:
    result = store.register(
        overrides.pop("site_id", _SITE_ID),
        overrides.pop("name", "A공구 계획고"),
        overrides.pop("revision", "Rev.C"),
        overrides.pop("declared", _declared()),
        registered_by="op-1",
        now=_NOW,
    )
    assert result.verdict is DesignSurfaceRegisterVerdict.REGISTERED
    assert result.surface is not None
    return result.surface.design_surface_id


def _sealed(store: DesignSurfaceStore, **overrides: Any) -> str:
    design_surface_id = _registered(store, **overrides)
    assert (
        store.seal(design_surface_id, sealed_by="op-1", now=_LATER).verdict
        is DesignSurfaceSealVerdict.SEALED
    )
    return design_surface_id


# ── 객체 키·식별자 ───────────────────────────────────────────────────────


def test_object_key_is_built_from_validated_parts() -> None:
    key = build_design_surface_object_key(site_id=_SITE_ID, design_surface_id="site-001-ds1")
    assert key == "sites/site-001/design-surfaces/site-001-ds1"


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "", ".hidden"])
def test_path_escaping_identifiers_are_refused_by_object_key_builder(bad_id: str) -> None:
    with pytest.raises(ValueError, match="경로-안전"):
        build_design_surface_object_key(site_id=_SITE_ID, design_surface_id=bad_id)
    with pytest.raises(ValueError, match="경로-안전"):
        build_design_surface_object_key(site_id=bad_id, design_surface_id="site-001-ds1")


# ── 등록 ────────────────────────────────────────────────────────────────


def test_registration_records_the_declaration_and_nothing_else(store: DesignSurfaceStore) -> None:
    """등록 직후의 상태는 REGISTERED 다 — 파일에 대해 아는 것이 아직 없다."""
    design_surface_id = _registered(store)
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.REGISTERED
    assert surface.observed is None
    assert surface.sealed_at is None and surface.verified_at is None
    assert surface.is_usable_for_conformance is False


def test_unknown_site_is_refused(store: DesignSurfaceStore) -> None:
    result = store.register(
        "site-does-not-exist", "계획고", "Rev.A", _declared(), registered_by="op-1", now=_NOW
    )
    assert result.verdict is DesignSurfaceRegisterVerdict.UNKNOWN_SITE


def test_same_declaration_resubmitted_is_idempotent_reissue(store: DesignSurfaceStore) -> None:
    first = _registered(store)
    again = store.register(
        _SITE_ID, "A공구 계획고", "Rev.C", _declared(), registered_by="op-1", now=_LATER
    )
    assert again.verdict is DesignSurfaceRegisterVerdict.REGISTERED
    assert again.surface is not None
    assert again.surface.design_surface_id == first
    assert len(store.list_for_site(_SITE_ID)) == 1


def test_same_revision_with_different_declaration_is_conflict(store: DesignSurfaceStore) -> None:
    """같은 개정 표기가 두 내용을 가리키면 '어느 판 기준인가'에 답할 수 없다."""
    _registered(store)
    conflict = store.register(
        _SITE_ID,
        "A공구 계획고",
        "Rev.C",
        _declared(sha256=_OTHER_SHA),
        registered_by="op-1",
        now=_LATER,
    )
    assert conflict.verdict is DesignSurfaceRegisterVerdict.DECLARATION_CONFLICT
    assert len(store.list_for_site(_SITE_ID)) == 1


def test_declared_vertical_reference_must_be_a_user_claim() -> None:
    """파이프라인 귀속은 업로더 주장 자리에 앉을 수 없다(계약이 강제)."""
    with pytest.raises(ValueError, match="user_declared"):
        DesignSurfaceDeclared(
            crs="EPSG:5186",
            sha256=_SHA,
            vertical_reference=VerticalReference(
                datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
                basis="ODM 이 RTK 타원체고를 그대로 출력",
                source=VerticalReferenceSource.PIPELINE_DECLARED,
            ),
        )


# ── 봉인 ────────────────────────────────────────────────────────────────


def test_seal_moves_to_pending_queue_without_reading_storage(store: DesignSurfaceStore) -> None:
    design_surface_id = _sealed(store)
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.SEALED
    assert surface.sealed_at == _LATER
    # 봉인은 "검증됐다"가 아니다 — 비교 입력 자격은 여전히 없다.
    assert surface.is_usable_for_conformance is False
    assert [s.design_surface_id for s in store.list_pending_verification()] == [design_surface_id]


def test_sealing_twice_is_idempotent(store: DesignSurfaceStore) -> None:
    design_surface_id = _sealed(store)
    again = store.seal(design_surface_id, sealed_by="op-1", now=_MEASURED_AT)
    assert again.verdict is DesignSurfaceSealVerdict.ALREADY_SEALED
    assert again.surface is not None and again.surface.sealed_at == _LATER


def test_sealing_a_judged_surface_is_refused(store: DesignSurfaceStore) -> None:
    design_surface_id = _sealed(store)
    store.record_observation(design_surface_id, _observed(), now=_MEASURED_AT)
    result = store.seal(design_surface_id, sealed_by="op-1", now=_MEASURED_AT)
    assert result.verdict is DesignSurfaceSealVerdict.ALREADY_JUDGED


def test_unknown_design_surface_cannot_be_sealed(store: DesignSurfaceStore) -> None:
    result = store.seal("nope", sealed_by="op-1", now=_LATER)
    assert result.verdict is DesignSurfaceSealVerdict.UNKNOWN_DESIGN_SURFACE


# ── 관측 대조 ────────────────────────────────────────────────────────────


def test_matching_observation_verifies_the_surface(store: DesignSurfaceStore) -> None:
    design_surface_id = _sealed(store)
    result = store.record_observation(design_surface_id, _observed(), now=_MEASURED_AT)
    assert result.verdict is DesignSurfaceObservationVerdict.VERIFIED
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.VERIFIED
    assert surface.verified_at == _MEASURED_AT
    assert surface.observed is not None and surface.observed.sha256 == _SHA
    assert surface.is_usable_for_conformance is True


def test_observation_before_seal_is_refused(store: DesignSurfaceStore) -> None:
    """**잘못된 순서 거부** — 봉인 전에는 대조 대상 내용이 확정되지 않았다."""
    design_surface_id = _registered(store)
    result = store.record_observation(design_surface_id, _observed(), now=_MEASURED_AT)
    assert result.verdict is DesignSurfaceObservationVerdict.NOT_SEALED
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.REGISTERED
    assert surface.observed is None


def test_second_observation_is_refused_without_rewriting_the_verdict(
    store: DesignSurfaceStore,
) -> None:
    design_surface_id = _sealed(store)
    store.record_observation(design_surface_id, _observed(), now=_MEASURED_AT)
    again = store.record_observation(
        design_surface_id, _observed(sha256=_OTHER_SHA), now=_MEASURED_AT
    )
    assert again.verdict is DesignSurfaceObservationVerdict.ALREADY_JUDGED
    surface = store.get(design_surface_id)
    assert surface is not None and surface.status is DesignSurfaceStatus.VERIFIED


def test_observation_for_unknown_surface_is_refused(store: DesignSurfaceStore) -> None:
    result = store.record_observation("nope", _observed(), now=_MEASURED_AT)
    assert result.verdict is DesignSurfaceObservationVerdict.UNKNOWN_DESIGN_SURFACE


# 거부 사유 전수 — (사유, 선언, 관측). 아래 커버리지 테스트가 이 목록이
# enum 전 멤버(UNREADABLE_RASTER 제외)를 덮는지 강제한다.
_RejectionCase = tuple[DesignSurfaceRejectionReason, DesignSurfaceDeclared, DesignSurfaceObserved]
_REJECTION_CASES: list[_RejectionCase] = [
    (
        DesignSurfaceRejectionReason.DIGEST_MISMATCH,
        _declared(),
        _observed(sha256=_OTHER_SHA),
    ),
    (
        DesignSurfaceRejectionReason.CRS_DECLARATION_MISMATCH,
        _declared(crs="EPSG:5187"),
        _observed(crs="EPSG:5186"),
    ),
    (
        # 선언·관측이 일치해도 지원 밖이면 거부한다(구 측지계 혼입 차단).
        DesignSurfaceRejectionReason.UNSUPPORTED_CRS,
        _declared(crs="EPSG:5174"),
        _observed(crs="EPSG:5174"),
    ),
    (
        # 계약이 이미 meter 만 허용하지만(Literal), 그 계약이 넓어져도 store 가
        # 다시 막는다 — model_construct 로 계약 검증을 우회해 그 가드를 직접 본다.
        DesignSurfaceRejectionReason.UNSUPPORTED_UNIT,
        DesignSurfaceDeclared.model_construct(
            crs="EPSG:5186",
            length_unit="usFoot",
            sha256=_SHA,
            vertical_reference=_vertical(),
        ),
        _observed(),
    ),
    (
        DesignSurfaceRejectionReason.UNSUPPORTED_BAND_COUNT,
        _declared(),
        _observed(band_count=3),
    ),
    (
        DesignSurfaceRejectionReason.NO_FINITE_CELLS,
        _declared(),
        _observed(finite_cell_count=0),
    ),
    (
        # 파일이 한국 정표고(KVD1964)를 들고 있는데 선언은 타원체고다.
        DesignSurfaceRejectionReason.VERTICAL_DECLARATION_CONTRADICTED,
        _declared(),
        _observed(vertical_crs_epsg=5193),
    ),
]


@pytest.mark.parametrize(
    ("reason", "declared", "observed"),
    [pytest.param(*case, id=case[0].value) for case in _REJECTION_CASES],
)
def test_each_mismatch_produces_its_typed_verdict(
    tmp_path: Path,
    reason: DesignSurfaceRejectionReason,
    declared: DesignSurfaceDeclared,
    observed: DesignSurfaceObserved,
) -> None:
    """8종 중 7종(대조 판정)이 각각 REJECTED + 자기 사유로 끝난다."""
    assert evaluate_observation(declared, observed) is reason

    if reason is DesignSurfaceRejectionReason.UNSUPPORTED_UNIT:
        # 이 조합은 원장에 **들어올 수 없다** — 계약이 lengthUnit 을 meter 로
        # 못박아, 등록 자체가 거부된다(위 순수 판정 대조로 가드의 존재만 확인).
        # 계약이 넓어지는 날 이 분기를 지우면 store 경로도 함께 검증된다.
        return

    store = DesignSurfaceStore(
        DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=_site_store(tmp_path)
    )
    design_surface_id = _sealed(store, declared=declared)
    result = store.record_observation(design_surface_id, observed, now=_MEASURED_AT)
    assert result.verdict is DesignSurfaceObservationVerdict.REJECTED
    assert result.rejection_reason is reason
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.REJECTED
    assert surface.rejection_reason == reason.value
    assert surface.verified_at is None
    assert surface.is_usable_for_conformance is False


def test_rejection_cases_cover_every_comparison_verdict() -> None:
    """새 사유를 추가하고 케이스를 안 만들면 여기서 드러난다."""
    covered = {reason for reason, _, _ in _REJECTION_CASES}
    assert covered == set(DesignSurfaceRejectionReason) - {
        DesignSurfaceRejectionReason.UNREADABLE_RASTER,
        # 이 둘은 GeoTIFF 선언/관측 비교가 아니라 LandXML 정규화 경로가 Core에
        # 고정 사유로 기록한다. 별도 LandXML 계약 테스트가 그 경로를 덮는다.
        DesignSurfaceRejectionReason.SOURCE_LINEAGE_INVALID,
        DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED,
    }


def test_unrecognised_vertical_crs_is_refused_not_swallowed(store: DesignSurfaceStore) -> None:
    """**모르는 수직 CRS 를 조용히 넘기지 않는다.**

    EPSG:3855(EGM2008)는 ``vertical_datum_from_epsg`` 가 예외로 거부하는 코드다.
    그 예외를 삼키면 세계 지오이드 기준 도면이 "선언대로 타원체고"로 통과하고,
    그 순간 20~30m 가 잔량 숫자에 조용히 들어간다.
    """
    design_surface_id = _sealed(store)
    result = store.record_observation(
        design_surface_id, _observed(vertical_crs_epsg=3855), now=_MEASURED_AT
    )
    assert result.verdict is DesignSurfaceObservationVerdict.REJECTED
    assert (
        result.rejection_reason
        is DesignSurfaceRejectionReason.VERTICAL_DECLARATION_CONTRADICTED
    )


def test_matching_vertical_crs_family_passes(store: DesignSurfaceStore) -> None:
    """EPSG:5019(타원체 기준 높이)는 ellipsoidal 선언과 같은 계열이라 통과한다."""
    design_surface_id = _sealed(store)
    result = store.record_observation(
        design_surface_id, _observed(vertical_crs_epsg=5019), now=_MEASURED_AT
    )
    assert result.verdict is DesignSurfaceObservationVerdict.VERIFIED


def test_absent_vertical_crs_neither_confirms_nor_contradicts(store: DesignSurfaceStore) -> None:
    """대부분의 DEM 은 수직 CRS 를 들고 있지 않다 — 그 부재로 거부하지 않는다."""
    design_surface_id = _sealed(store)
    result = store.record_observation(
        design_surface_id, _observed(vertical_crs_epsg=None), now=_MEASURED_AT
    )
    assert result.verdict is DesignSurfaceObservationVerdict.VERIFIED


def test_unreadable_raster_is_reported_through_its_own_path(store: DesignSurfaceStore) -> None:
    design_surface_id = _sealed(store)
    result = store.report_verification_failure(
        design_surface_id, detail="TIFF 헤더가 깨졌다", reported_by="worker-1", now=_MEASURED_AT
    )
    assert result.verdict is DesignSurfaceObservationVerdict.REJECTED
    assert result.rejection_reason is DesignSurfaceRejectionReason.UNREADABLE_RASTER
    surface = store.get(design_surface_id)
    assert surface is not None
    assert surface.status is DesignSurfaceStatus.REJECTED
    # 파일을 열지 못했으면 관측 자체가 없다 — null 이 정상이다.
    assert surface.observed is None


def test_verification_failure_before_seal_is_refused(store: DesignSurfaceStore) -> None:
    design_surface_id = _registered(store)
    result = store.report_verification_failure(
        design_surface_id, detail=None, reported_by="worker-1", now=_MEASURED_AT
    )
    assert result.verdict is DesignSurfaceObservationVerdict.NOT_SEALED


# ── 대기 큐 ─────────────────────────────────────────────────────────────


def test_pending_queue_contains_only_sealed_and_is_fifo(store: DesignSurfaceStore) -> None:
    first = _sealed(store, name="A공구", revision="Rev.A")
    second = _registered(store, name="B공구", revision="Rev.A")
    assert (
        store.seal(second, sealed_by="op-1", now=_LATER + timedelta(minutes=1)).verdict
        is DesignSurfaceSealVerdict.SEALED
    )
    _registered(store, name="C공구", revision="Rev.A")  # 봉인 안 함 — 큐에 없다
    verified = _sealed(store, name="D공구", revision="Rev.A")
    store.record_observation(verified, _observed(), now=_MEASURED_AT)

    assert [s.design_surface_id for s in store.list_pending_verification()] == [first, second]
    assert [s.design_surface_id for s in store.list_pending_verification(limit=1)] == [first]


# ── 재생 ────────────────────────────────────────────────────────────────


@contextmanager
def _opened(tmp_path: Path, *, tag: str) -> Iterator[DesignSurfaceStore]:
    """설계면 store 를 열고 **반드시 닫는다** — ``DurableJournal`` 은 단일 writer 다.

    ``DesignSurfaceStore`` 생성자는 재생 실패 시 자기 저널을 닫아 주므로, 여기서
    책임지는 것은 site 저널과 정상 생성된 설계면 저널이다(``test_source_media``
    의 replay 테스트 관습).
    """
    site_store, site_journal = _site_store_with_journal(tmp_path, tag=tag)
    journal = DurableJournal(tmp_path / "design-surfaces.jsonl")
    try:
        store = DesignSurfaceStore(journal, site_store=site_store)
    except DesignSurfaceRecoveryError:
        site_journal.close()
        raise
    try:
        yield store
    finally:
        journal.close()
        site_journal.close()


def _journal_lines(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "design-surfaces.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rewrite_journal(tmp_path: Path, records: list[dict[str, Any]]) -> None:
    path = tmp_path / "design-surfaces.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def _status_of(store: DesignSurfaceStore, design_surface_id: str) -> DesignSurface:
    surface = store.get(design_surface_id)
    assert surface is not None, design_surface_id
    return surface


def test_replay_restores_every_terminal_state(tmp_path: Path) -> None:
    with _opened(tmp_path, tag="a") as store:
        verified = _sealed(store, name="A공구", revision="Rev.A")
        store.record_observation(verified, _observed(), now=_MEASURED_AT)
        rejected = _sealed(store, name="B공구", revision="Rev.A")
        store.record_observation(rejected, _observed(sha256=_OTHER_SHA), now=_MEASURED_AT)
        unreadable = _sealed(store, name="C공구", revision="Rev.A")
        store.report_verification_failure(
            unreadable, detail="열 수 없다", reported_by="worker-1", now=_MEASURED_AT
        )
        pending = _sealed(store, name="D공구", revision="Rev.A")

    with _opened(tmp_path, tag="b") as replayed:
        assert _status_of(replayed, verified).status is DesignSurfaceStatus.VERIFIED
        assert _status_of(replayed, verified).observed is not None
        assert _status_of(replayed, rejected).status is DesignSurfaceStatus.REJECTED
        assert (
            _status_of(replayed, rejected).rejection_reason
            == DesignSurfaceRejectionReason.DIGEST_MISMATCH.value
        )
        assert (
            _status_of(replayed, unreadable).rejection_reason
            == DesignSurfaceRejectionReason.UNREADABLE_RASTER.value
        )
        assert [s.design_surface_id for s in replayed.list_pending_verification()] == [pending]


def test_replay_refuses_verdict_forged_to_verified(tmp_path: Path) -> None:
    """원장의 판정을 손으로 고쳐도 재대조가 다시 매긴다."""
    with _opened(tmp_path, tag="a") as store:
        design_surface_id = _sealed(store)
        store.record_observation(
            design_surface_id, _observed(sha256=_OTHER_SHA), now=_MEASURED_AT
        )

    records = _journal_lines(tmp_path)
    assert records[-1]["kind"] == "design-surface-observed"
    records[-1]["status"] = DesignSurfaceStatus.VERIFIED.value
    records[-1]["rejectionReason"] = None
    _rewrite_journal(tmp_path, records)

    with pytest.raises(DesignSurfaceRecoveryError, match="재대조와 불일치"), _opened(
        tmp_path, tag="b"
    ):
        pass  # pragma: no cover - 생성자에서 이미 실패한다


def test_replay_refuses_observation_edited_to_match(tmp_path: Path) -> None:
    """측정값을 선언에 맞춰 고치면 판정이 뒤집혀 기록된 사유와 어긋난다."""
    with _opened(tmp_path, tag="a") as store:
        design_surface_id = _sealed(store)
        store.record_observation(
            design_surface_id, _observed(sha256=_OTHER_SHA), now=_MEASURED_AT
        )

    records = _journal_lines(tmp_path)
    records[-1]["observed"]["sha256"] = _SHA
    _rewrite_journal(tmp_path, records)

    with pytest.raises(DesignSurfaceRecoveryError, match="재대조와 불일치"), _opened(
        tmp_path, tag="b"
    ):
        pass  # pragma: no cover


def test_replay_refuses_observation_before_seal(tmp_path: Path) -> None:
    with _opened(tmp_path, tag="a") as store:
        design_surface_id = _sealed(store)
        store.record_observation(design_surface_id, _observed(), now=_MEASURED_AT)

    records = _journal_lines(tmp_path)
    # 봉인 레코드를 지운다 — REGISTERED 에서 VERIFIED 로 가는 전이는 없다.
    _rewrite_journal(tmp_path, [r for r in records if r["kind"] != "design-surface-sealed"])

    with pytest.raises(DesignSurfaceRecoveryError, match="허용되지 않은 전이"), _opened(
        tmp_path, tag="b"
    ):
        pass  # pragma: no cover


def test_replay_refuses_worker_authored_core_verdict(tmp_path: Path) -> None:
    """검증실패 레코드가 실을 수 있는 사유는 UNREADABLE_RASTER 하나뿐이다."""
    with _opened(tmp_path, tag="a") as store:
        design_surface_id = _sealed(store)
        store.report_verification_failure(
            design_surface_id, detail=None, reported_by="worker-1", now=_MEASURED_AT
        )

    records = _journal_lines(tmp_path)
    records[-1]["reason"] = DesignSurfaceRejectionReason.NO_FINITE_CELLS.value
    _rewrite_journal(tmp_path, records)

    with pytest.raises(DesignSurfaceRecoveryError, match="UNREADABLE_RASTER"), _opened(
        tmp_path, tag="b"
    ):
        pass  # pragma: no cover


def test_replay_refuses_duplicate_registration(tmp_path: Path) -> None:
    with _opened(tmp_path, tag="a") as store:
        _registered(store)
    records = _journal_lines(tmp_path)
    _rewrite_journal(tmp_path, [*records, records[0]])
    with pytest.raises(DesignSurfaceRecoveryError, match="중복 등록"), _opened(
        tmp_path, tag="b"
    ):
        pass  # pragma: no cover


# ── 상태 코드 표 ─────────────────────────────────────────────────────────


def test_status_maps_cover_every_verdict() -> None:
    """새 verdict 를 추가하고 표를 안 고치면 라우터가 KeyError 로 죽는다."""
    assert set(_REGISTER_STATUS) == set(DesignSurfaceRegisterVerdict)
    assert set(_SEAL_STATUS) == set(DesignSurfaceSealVerdict)
    assert set(_OBSERVATION_STATUS) == set(DesignSurfaceObservationVerdict)


# ── HTTP ────────────────────────────────────────────────────────────────


class _StubStorage:
    """포트 계약만 만족하는 스텁 — presigned URL 을 결정적으로 만들어 준다."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.put_keys: list[str] = []

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del ttl
        if self.fail:
            raise EvidenceStorageError("스토리지 없음")
        self.put_keys.append(f"{object_key}|{content_type}")
        return f"https://storage.example/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        if self.fail:
            raise EvidenceStorageError("스토리지 없음")
        return f"https://storage.example/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError

    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _app(
    tmp_path: Path,
    *,
    storage: Any | None = None,
    landxml_ingress_enabled: bool = False,
) -> TestClient:
    site_store = _site_store(tmp_path)
    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        design_surface_store=DesignSurfaceStore(
            DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=site_store
        ),
        evidence_storage=storage if storage is not None else _StubStorage(),
        landxml_ingress_enabled=landxml_ingress_enabled,
    )
    return TestClient(app)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _declared_payload(*, sha256: str = _SHA, crs: str = "EPSG:5186") -> dict[str, Any]:
    return {
        "crs": crs,
        "lengthUnit": "meter",
        "sha256": sha256,
        "verticalReference": {
            "datum": "ellipsoidal",
            "basis": "도면 표제부에 타원체고 명시",
            "source": "user_declared",
        },
    }


def _observation_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sha256": _SHA,
        "crs": "EPSG:5186",
        "verticalCrsEpsg": None,
        "width": 100,
        "height": 80,
        "bandCount": 1,
        "dtype": "float32",
        "nodata": None,
        "nodataIsNan": False,
        "pixelSizeXM": 0.5,
        "pixelSizeYM": 0.5,
        "transform": [0.5, 0.0, 200000.0, 0.0, -0.5, 500000.0],
        "boundsMinX": 200000.0,
        "boundsMinY": 499960.0,
        "boundsMaxX": 200050.0,
        "boundsMaxY": 500000.0,
        "finiteCellCount": 8000,
    }
    return {**base, **overrides}


def _register_over_http(client: TestClient, **kwargs: Any) -> Any:
    payload = {
        "name": kwargs.pop("name", "A공구 계획고"),
        "revision": kwargs.pop("revision", "Rev.C"),
        "declared": kwargs.pop("declared", _declared_payload()),
        **kwargs,
    }
    return client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces",
        headers=_headers(_ADMIN_TOKEN),
        json=payload,
    )


def test_full_journey_over_http(tmp_path: Path) -> None:
    """등록 → 봉인 → (워커) 대기 목록 → 관측 보고 → VERIFIED."""
    client = _app(tmp_path)
    registered = _register_over_http(client)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    design_surface_id = body["designSurfaceId"]
    assert body["uploadUrl"].endswith(
        f"sites/{_SITE_ID}/design-surfaces/{design_surface_id}"
    )
    assert body["surface"]["status"] == "REGISTERED"

    sealed = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    assert sealed.status_code == 201
    assert sealed.json()["surface"]["status"] == "SEALED"

    pending = client.get("/v1/design-surfaces", headers=_headers(_WORKER_TOKEN))
    assert pending.status_code == 200
    surfaces = pending.json()["surfaces"]
    assert [s["designSurfaceId"] for s in surfaces] == [design_surface_id]
    # **워커에게 정답을 주지 않는다** — 신고 sha256·CRS 가 응답 어디에도 없다.
    assert "sha256" not in json.dumps(surfaces)
    assert "EPSG" not in json.dumps(surfaces)

    observed = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(),
    )
    assert observed.status_code == 201, observed.text
    assert observed.json()["verdict"] == "VERIFIED"
    surface = observed.json()["surface"]
    assert surface["status"] == "VERIFIED"
    # measuredBy 는 워커가 주장한 값이 아니라 인증된 principal 이다.
    assert surface["observed"]["measuredBy"] == "worker-1"


def test_landxml_ingress_is_flagged_and_preserves_raw_to_canonical_lineage(
    tmp_path: Path,
) -> None:
    disabled_path = tmp_path / "disabled"
    disabled_path.mkdir()
    disabled = _app(disabled_path)
    blocked = _register_over_http(
        disabled, sourceFormat="landxml", surfaceSelector="Plan"
    )
    assert blocked.status_code == 403
    assert blocked.json()["verdict"] == "LANDXML_INGRESS_DISABLED"

    storage = _StubStorage()
    enabled_path = tmp_path / "enabled"
    enabled_path.mkdir()
    client = _app(
        enabled_path,
        storage=storage,
        landxml_ingress_enabled=True,
    )
    registered = _register_over_http(
        client, sourceFormat="landxml", surfaceSelector="Plan"
    )
    assert registered.status_code == 201, registered.text
    body = registered.json()
    design_surface_id = body["designSurfaceId"]
    raw_key = build_design_surface_object_key(
        site_id=_SITE_ID, design_surface_id=design_surface_id
    )
    canonical_key = build_design_surface_canonical_object_key(
        site_id=_SITE_ID, design_surface_id=design_surface_id
    )
    assert body["objectKey"] == raw_key
    assert body["canonicalObjectKey"] == canonical_key
    assert raw_key != canonical_key

    sealed = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    assert sealed.status_code == 201
    pending = client.get("/v1/design-surfaces", headers=_headers(_WORKER_TOKEN))
    candidate = pending.json()["surfaces"][0]
    assert candidate["sourceFormat"] == "landxml"
    assert candidate["surfaceSelector"] == "Plan"
    assert candidate["declaredCrs"] == "EPSG:5186"
    assert candidate["downloadUrl"].endswith(raw_key)
    assert candidate["normalizationUploadUrl"].endswith(canonical_key)

    observed = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(
            sha256=_OTHER_SHA,
            sourceLineage={
                "sourceFormat": "landxml",
                "sourceSha256": _SHA,
                "surfaceSelector": "Plan",
                "parserVersion": KSI_LANDXML_TIN_PARSER_VERSION,
                "normalizationProfile": CANONICAL_TIN_NORMALIZATION_PROFILE,
                "canonicalSha256": _OTHER_SHA,
            },
        ),
    )
    assert observed.status_code == 201, observed.text
    surface = observed.json()["surface"]
    assert surface["status"] == "VERIFIED"
    assert surface["declared"]["sha256"] == _SHA
    assert surface["observed"]["sha256"] == _OTHER_SHA
    assert surface["sourceLineage"]["canonicalSha256"] == _OTHER_SHA


def test_landxml_observation_rejects_noncanonical_parser_lineage(tmp_path: Path) -> None:
    client = _app(tmp_path, landxml_ingress_enabled=True)
    registered = _register_over_http(
        client, sourceFormat="landxml", surfaceSelector="Plan"
    )
    design_surface_id = registered.json()["designSurfaceId"]
    client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )

    response = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(
            sha256=_OTHER_SHA,
            sourceLineage={
                "sourceFormat": "landxml",
                "sourceSha256": _SHA,
                "surfaceSelector": "Plan",
                "parserVersion": "ksi-landxml-tin-v0",
                "normalizationProfile": CANONICAL_TIN_NORMALIZATION_PROFILE,
                "canonicalSha256": _OTHER_SHA,
            },
        ),
    )

    assert response.status_code == 422
    assert response.json()["rejectionReason"] == "SOURCE_LINEAGE_INVALID"


def test_mismatched_observation_is_422_with_typed_reason(tmp_path: Path) -> None:
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    response = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(sha256=_OTHER_SHA),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "REJECTED"
    assert response.json()["rejectionReason"] == "DIGEST_MISMATCH"


def test_observation_on_unsealed_surface_is_409(tmp_path: Path) -> None:
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    response = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(),
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == "NOT_SEALED"


def test_self_contradictory_measurement_is_typed_not_500(tmp_path: Path) -> None:
    """유효셀 수가 전체 셀 수보다 크다 — 계약이 막고 라우터가 typed 로 옮긴다."""
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    response = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(finiteCellCount=999_999),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "INVALID_MEASUREMENT"


def test_verification_failure_over_http(tmp_path: Path) -> None:
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    response = client.post(
        f"/v1/design-surfaces/{design_surface_id}/verification-failure",
        headers=_headers(_WORKER_TOKEN),
        json={"detail": "GeoTIFF 가 아니다"},
    )
    assert response.status_code == 201
    assert response.json()["rejectionReason"] == "UNREADABLE_RASTER"


def test_pending_list_refuses_other_statuses(tmp_path: Path) -> None:
    client = _app(tmp_path)
    response = client.get(
        "/v1/design-surfaces", headers=_headers(_WORKER_TOKEN), params={"status": "VERIFIED"}
    )
    assert response.status_code == 422


def test_permissions_are_separated_between_uploader_and_worker(tmp_path: Path) -> None:
    """설계면을 올린 주체가 자기 신고값을 스스로 검증할 수 없다."""
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    # 사람(ADMIN) 은 PROCESSING_WORK 을 갖지 않는다.
    assert (
        client.post(
            f"/v1/design-surfaces/{design_surface_id}/observations",
            headers=_headers(_ADMIN_TOKEN),
            json=_observation_payload(),
        ).status_code
        == 403
    )
    # 워커는 SITES_WRITE 를 갖지 않는다.
    assert (
        client.post(
            f"/v1/sites/{_SITE_ID}/design-surfaces",
            headers=_headers(_WORKER_TOKEN),
            json={"name": "x", "revision": "y", "declared": _declared_payload()},
        ).status_code
        == 403
    )
    # 열람 전용 사용자는 등록할 수 없지만 목록은 볼 수 있다.
    assert _register_over_http_as(client, _VIEWER_TOKEN).status_code == 403
    assert (
        client.get(
            f"/v1/sites/{_SITE_ID}/design-surfaces", headers=_headers(_VIEWER_TOKEN)
        ).status_code
        == 200
    )


def _register_over_http_as(client: TestClient, token: str) -> Any:
    return client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces",
        headers=_headers(token),
        json={"name": "A공구", "revision": "Rev.Z", "declared": _declared_payload()},
    )


def test_seal_through_a_foreign_site_path_is_404(tmp_path: Path) -> None:
    client = _app(tmp_path)
    design_surface_id = _register_over_http(client).json()["designSurfaceId"]
    response = client.post(
        f"/v1/sites/{_OTHER_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    assert response.status_code == 404


def test_design_surfaces_are_isolated_by_parent_site_organization(tmp_path: Path) -> None:
    """설계면·worker 대기열까지 부모 Site 조직 경계를 상속한다(INV-060)."""
    site_store = SiteStore(DurableJournal(tmp_path / "org-sites.jsonl"))
    assert (
        site_store.register(
            _SITE_ID,
            "다른 조직 현장",
            _SITE_FRAME,
            data_residency=None,
            organization_id="org-2",
            actor="other-op-1",
            now=_NOW,
        ).verdict.value
        == "REGISTERED"
    )
    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        design_surface_store=DesignSurfaceStore(
            DurableJournal(tmp_path / "org-design-surfaces.jsonl"), site_store=site_store
        ),
        evidence_storage=_StubStorage(),
    )
    client = TestClient(app)
    registered = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces",
        headers=_headers(_OTHER_ORG_ADMIN_TOKEN),
        json={"name": "A공구", "revision": "Rev.A", "declared": _declared_payload()},
    )
    assert registered.status_code == 201, registered.text
    design_surface_id = registered.json()["designSurfaceId"]
    assert client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_OTHER_ORG_ADMIN_TOKEN),
    ).status_code == 201

    foreign_list = client.get(
        f"/v1/sites/{_SITE_ID}/design-surfaces", headers=_headers(_VIEWER_TOKEN)
    )
    assert foreign_list.status_code == 404
    foreign_seal = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=_headers(_ADMIN_TOKEN),
    )
    assert foreign_seal.status_code == 404
    foreign_pending = client.get("/v1/design-surfaces", headers=_headers(_WORKER_TOKEN))
    assert foreign_pending.json()["surfaces"] == []

    owner_pending = client.get(
        "/v1/design-surfaces", headers=_headers(_OTHER_ORG_WORKER_TOKEN)
    )
    assert owner_pending.status_code == 200
    assert [surface["designSurfaceId"] for surface in owner_pending.json()["surfaces"]] == [
        design_surface_id
    ]
    foreign_observation = client.post(
        f"/v1/design-surfaces/{design_surface_id}/observations",
        headers=_headers(_WORKER_TOKEN),
        json=_observation_payload(),
    )
    assert foreign_observation.status_code == 404


def test_storage_failure_keeps_the_registration(tmp_path: Path) -> None:
    """원장 등록은 durable 하다 — 같은 선언 재전송으로 URL 을 다시 받는다."""
    storage = _StubStorage(fail=True)
    client = _app(tmp_path, storage=storage)
    response = _register_over_http(client)
    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"
    assert response.json()["designSurfaceId"] is not None

    storage.fail = False
    again = _register_over_http(client)
    assert again.status_code == 201
    assert again.json()["uploadUrl"]


def test_upload_url_is_signed_for_a_non_interpretable_content_type(tmp_path: Path) -> None:
    """브라우저가 해석하는 타입으로 서명하지 않는다(업로더가 고를 수도 없다)."""
    storage = _StubStorage()
    client = _app(tmp_path, storage=storage)
    _register_over_http(client)
    assert storage.put_keys and storage.put_keys[0].endswith("|application/octet-stream")


def test_routes_absent_without_storage(tmp_path: Path) -> None:
    site_store = _site_store(tmp_path)
    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        design_surface_store=DesignSurfaceStore(
            DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=site_store
        ),
    )
    paths = set(app.openapi()["paths"])
    assert not any("design-surfaces" in path for path in paths)


def test_store_without_site_store_refuses_assembly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="design_surface_store"):
        create_app(
            auth_registry=_registry(),
            design_surface_store=DesignSurfaceStore(
                DurableJournal(tmp_path / "design-surfaces.jsonl"),
                site_store=_site_store(tmp_path),
            ),
        )
