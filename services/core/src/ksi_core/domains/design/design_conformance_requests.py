"""설계 대비 잔량 요청 원장 — "이 설계면과 이 지형을 비교하라"의 수신·lease·전이 (M4-A).

``comparison_requests.py`` 의 형제다. 골격(journal 위 append-only + live·재생 공유
게이트 + ``leasing`` 재사용 + ``/input`` 표면)은 그대로 복제하되, **묻는 질문이
다르다**: 저쪽은 두 epoch 를 비교하고 여기는 **바깥에서 들어온 설계면**과 지금
지형을 비교한다. 그 차이가 이 모듈에만 있는 게이트를 만든다.

## 계산 전에 막는 것들 (fail-closed)

1. **VERIFIED 설계면만 입력이다.** ``SEALED`` 는 "업로드했다고 클라이언트가
   주장했다"일 뿐이라(``design_surface`` 계약 docstring) 그 파일이 무엇인지 아무도
   모른다. 검증 안 된 자산으로 시작한 계산은 실패해도 **자산 결함인지 계산 결함인지**
   구분되지 않는다.
2. **수직기준을 이을 수 없으면 여기서 거부한다.** 타원체고와 정표고를 그냥 빼면
   한국에서 20~30m 가 조용히 섞이고 결과는 여전히 숫자다. 계산 엔진도 자기
   입구에서 같은 판정을 하지만(``run_design_conformance``), 요청 생성 시점에
   막아야 사용자가 **몇 분 뒤 FAILED** 가 아니라 **즉시 사유**를 받는다.

   다만 판정은 "계열이 같은가"가 아니라 **"이을 수 있는가"** 다
   (``assert_bridgeable_vertical``). 실무 설계도면은 거의 항상 정표고라, 계열
   불일치를 통째로 거부하면 한국 도면이 100% 막힌다. 지오이드 격자로 이을 수
   있는 조합은 통과시키고, **실제로 격자를 읽어 변환하는 일은 워커**가 한다 —
   격자는 워커의 환경(``KSI_GEOID_GRID``)에 붙어 있고 Core 는 pyproj·rasterio 를
   의존하지 않기 때문이다(``vertical_reference`` 모듈 docstring). 그래서 여기서
   내주는 답은 "된다"가 아니라 **"이을 수 있는 종류다"** 이고, 격자가 없어서 못
   하는 경우는 워커가 FAILED 사유로 구분해 돌려준다.
3. **현재 DSM 이 수직기준을 밝히지 않으면 거부한다**(``VERTICAL_REFERENCE_UNKNOWN``).
   두 epoch 비교는 같은 파이프라인 산출물끼리라 레거시 대체값이 실제로 맞지만
   (``comparison_worker._resolve_vertical_datum``), 설계면은 그 전제가 성립하지
   않는다 — 한쪽이 미상이면 어떤 숫자도 내지 않는다.

## 차분 래스터: 워커의 "올렸다"는 자기보고가 아니다

이 모듈은 워커에게 차분 래스터를 올릴 **자리만** 정해 주고(``diff-raster-upload-url``),
그 다음 ``diff-raster-verification`` 에서 **Core 가 스토리지 객체를 직접 읽어
자기 hashlib 으로 해시를 다시 계산한다**(:func:`recompute_diff_raster_digest`).
워커가 신고한 digest 와 같을 때만 그 사실이 원장에 남고, 그때 찍힌 시각이
``DesignConformanceReport.diffRaster.coreVerifiedDigestAt`` 에 실린다 — 그 필드가
"워커가 올렸다고 말한 시각"이 아니라 **Core 가 확인한 시각**인 근거가 여기다.

리포트 수신 경로(``design_conformance_reports.py``)는 이 확인을 **한 번 더** 한다.
중복이 아니라 다른 창을 막는다: 여기 확인은 리포트가 정직한 시각을 실을 수 있게
하고, 저기 확인은 **원장에 리포트가 굳는 그 순간** 스토리지 바이트가 여전히 그
digest 임을 보장한다(그 사이에 다른 바이트로 덮어썼을 수 있다).

## 객체 키는 lease generation에 귀속된다

``build_design_conformance_raster_object_key(site_id, design_conformance_id)`` 이고
``design_conformance_id`` 는 ``request_id`` 에서 결정적으로 도출되지만, mutable
candidate 객체 키는 ``lease_generation``과 acquisition까지 포함한다. 같은 시도의
exact retry만 같은 자리를 쓰고, takeover된 다음 generation은 다른 자리를 쓴다.
PUT은 신고 digest에 결속되며 authoritative report가 정확한 candidate key를 원장에
고정한다. 따라서 이전 generation의 아직 유효한 URL은 현재 결과를 덮지 못한다.

종료된(``SUCCEEDED``/``FAILED``) 요청에는 업로드 URL 도 검증도 내주지 않는다.
그래야 "리포트가 굳은 뒤 그 래스터가 다른 바이트로 바뀌는" 창이 영구히 닫힌다.

## zones·policy 는 참조가 아니라 값이다

``comparison_requests`` 와 같은 근거(대표자 확정, 2026-08-10) — 나중에 현장
경계나 시스템 기준값이 바뀌어도 이미 만든 요청·결과는 그때 무엇으로 쟀는지를
스스로 답한다. 설계면 해시(``design_surface_sha256``)도 같은 이유로 요청 시점의
값을 복사해 둔다: 리포트가 "어느 판 기준인가"를 되짚는 앵커다.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy, current_comparison_policy
from ksi_event_contracts.design_surface import DesignSurfaceStatus
from ksi_event_contracts.processing_artifact import ProcessingArtifact, ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus
from ksi_event_contracts.vertical_reference import (
    VerticalDatumIncompatibleError,
    VerticalReference,
    assert_bridgeable_vertical,
)
from ksi_geo_spatial.crs import UnsupportedCrsError, normalise_crs
from pydantic import Field

from ksi_core.domains.analytics.comparison_requests import assert_zones_are_usable, zone_fingerprint
from ksi_core.domains.artifacts.evidence import (
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.domains.design.design_surfaces import (
    DESIGN_SURFACE_CONTENT_TYPE,
    object_key_for_surface,
)
from ksi_core.domains.design.region_extraction_requests import RegionExtractionRequestStore
from ksi_core.domains.processing.civil_preflight import (
    AnalysisReadinessCheck,
    design_normalization_anchor,
    preflight_design_surface,
    preflight_single_epoch,
)
from ksi_core.domains.processing.processing_jobs import (
    DEFAULT_LEASE_TTL,
    ProcessingJobStore,
    authoritative_artifacts,
)
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.foundation.leasing import (
    JobLease,
    LeaseDenialReason,
    LeaseFence,
    LeaseMode,
    check_lease,
    is_claimable,
    lease_raw_fields,
    next_lease,
)
from ksi_core.foundation.metrics import DESIGN_CONFORMANCE_REQUEST_TRANSITIONS
from ksi_core.identity.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI

    from ksi_core.domains.design.design_surfaces import DesignSurfaceStore
    from ksi_core.domains.missions.mission_records import MissionStore
    from ksi_core.domains.sites.work_areas import WorkAreaStore

logger = logging.getLogger("ksi_core.design_conformance_requests")

_NOT_FOUND_DETAIL = "해당 설계 대비 잔량 요청을 찾을 수 없다"

#: 차분 래스터의 저장 MIME — 설계면과 같은 자리다(``DESIGN_SURFACE_CONTENT_TYPE``).
#: 브라우저가 해석하지 않는 바이너리이므로 ``evidence.ALLOWED_CONTENT_TYPES`` 의
#: ``application/octet-stream`` 을 그대로 쓴다.
DIFF_RASTER_CONTENT_TYPE = DESIGN_SURFACE_CONTENT_TYPE

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

# ``comparison_requests._ALLOWED_TRANSITIONS`` 와 같은 표다 — CANCELLED 는 여기도
# 없다(정체된 RUNNING 은 lease 만료로 회수되고, 설계 대비 계산은 분 단위다).
_ALLOWED_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.QUEUED: frozenset({ProcessingJobStatus.RUNNING}),
    ProcessingJobStatus.RUNNING: frozenset(
        {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset(),
}


class IllegalDesignConformanceTransitionError(ValueError):
    """전이표에 없는 설계 대비 요청 상태 전이."""


def assert_design_conformance_transition(
    before: ProcessingJobStatus, after: ProcessingJobStatus
) -> None:
    """전이 적법성 — live 경로와 재생 경로가 같은 함수를 쓴다."""
    if after not in _ALLOWED_TRANSITIONS[before]:
        suffix = (
            " — 종료된 요청의 결론은 고쳐 쓰지 않는다" if not _ALLOWED_TRANSITIONS[before] else ""
        )
        raise IllegalDesignConformanceTransitionError(
            f"설계 대비 요청 상태를 {before.value} 에서 {after.value} 로 바꿀 수 없다{suffix}"
        )


class DesignConformanceRequestVerdict(StrEnum):
    """생성/조회/lease/전이/래스터 판정 — 문자열 메시지로 분기하지 않는다."""

    CREATED = "CREATED"
    #: 같은 (설계면, 현재 작업, 구역) 지시가 이미 있다 — 재전송이 요청을 복제하지 않는다.
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_JOB = "UNKNOWN_JOB"
    JOB_NOT_SUCCEEDED = "JOB_NOT_SUCCEEDED"
    MISSION_MISMATCH = "MISSION_MISMATCH"
    UNKNOWN_DESIGN_SURFACE = "UNKNOWN_DESIGN_SURFACE"
    #: 설계면이 아직 검증되지 않았거나 거부됐다 — VERIFIED 만 입력 자격이다.
    DESIGN_SURFACE_NOT_VERIFIED = "DESIGN_SURFACE_NOT_VERIFIED"
    DESIGN_NORMALIZATION_MISMATCH = "DESIGN_NORMALIZATION_MISMATCH"
    ANALYSIS_NOT_READY = "ANALYSIS_NOT_READY"
    PROCESSING_PROFILE_UNKNOWN = "PROCESSING_PROFILE_UNKNOWN"
    SOURCE_LINEAGE_GAP = "SOURCE_LINEAGE_GAP"
    CRS_MISMATCH = "CRS_MISMATCH"
    VERTICAL_REFERENCE_MISMATCH = "VERTICAL_REFERENCE_MISMATCH"
    #: 설계면과 현재 작업이 다른 현장이다 — 다른 현장의 계획고와 비교할 수 없다.
    SITE_MISMATCH = "SITE_MISMATCH"
    #: 현재 작업에 dsm 산출물이 없다 — 표면 함수가 없으면 적분할 것이 없다.
    NO_DSM_ARTIFACT = "NO_DSM_ARTIFACT"
    #: 구역이 확정되지 않았다. 설계 대비 잔량은 "어느 범위의" 잔량인지 없이 성립하지 않는다.
    ZONES_REQUIRED = "ZONES_REQUIRED"
    #: 즉석 구역(zones)의 폴리곤을 쓸 수 없다 — 타입·닫힘·좌표·개수 상한 중 하나를
    #: 어겼다. 워커까지 보내지 않고 여기서 사람 말로 거부한다.
    ZONES_INVALID = "ZONES_INVALID"
    #: 고른 작업구역을 쓸 수 없다 — 없거나, 다른 현장이거나, 보관됐거나, 좌표계가
    #: 섞였거나, ``zones`` 와 동시에 지정됐다(M4-C). 사유는 detail 이 사람 말로 적는다.
    WORK_AREA_UNUSABLE = "WORK_AREA_UNUSABLE"
    #: 현재 DSM 이 수직기준을 밝히지 않는다(수직기준 기록 이전의 산출물) — 재처리하면 된다.
    VERTICAL_REFERENCE_UNKNOWN = "VERTICAL_REFERENCE_UNKNOWN"
    #: 설계면과 현재 DSM 의 수직기준을 **어떤 지오이드 격자로도 이을 수 없다**.
    #: "격자가 없어서 지금은 못 한다"와는 다른 사실이다 — 그쪽은 요청을 만들 수
    #: 있고 워커가 ``GeoidUnavailableError`` 로 FAILED 사유를 남긴다.
    VERTICAL_DATUM_INCOMPATIBLE = "VERTICAL_DATUM_INCOMPATIBLE"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    REQUEST_NOT_ACTIVE = "REQUEST_NOT_ACTIVE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

    # ── lease ────────────────────────────────────────────────────────────
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    LEASE_REQUIRED = "LEASE_REQUIRED"
    STALE_LEASE_ACQUISITION = "STALE_LEASE_ACQUISITION"
    STALE_LEASE_GENERATION = "STALE_LEASE_GENERATION"
    INVALID_LEASE_FENCE = "INVALID_LEASE_FENCE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"

    # ── 전이 ─────────────────────────────────────────────────────────────
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"

    # ── 입력·래스터 ──────────────────────────────────────────────────────
    INPUT_READY = "INPUT_READY"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    UPLOAD_READY = "UPLOAD_READY"
    #: Core 가 업로드된 바이트를 직접 다시 해싱해 신고 digest 와 같음을 확인했다.
    DIFF_RASTER_VERIFIED = "DIFF_RASTER_VERIFIED"
    #: 재해싱 결과가 신고와 다르다 — 워커의 자기보고를 사실로 승격하지 않는다.
    DIFF_RASTER_DIGEST_MISMATCH = "DIFF_RASTER_DIGEST_MISMATCH"
    #: 그 자리의 객체를 읽지 못했다(부재·스토리지 장애) — 확인 없이 통과시키지 않는다.
    DIFF_RASTER_UNREADABLE = "DIFF_RASTER_UNREADABLE"
    #: 이 요청에 리포트가 기록된 적이 없는데 성공을 주장했다. 성공은 결과가 있어야
    #: 성공이다 — 리포트 없는 SUCCEEDED 는 뒤따르는 자동 연동(구역 추출)을 존재하지
    #: 않는 결과 위에 쌓는다.
    NO_REPORT_RECORDED = "NO_REPORT_RECORDED"
    #: 이미 리포트가 이 id 로 기록됐다 — 그 리포트가 특정 digest 를 가리키고 있으므로
    #: 같은 자리의 래스터를 다시 쓰거나 다시 확인할 수 없다(기록된 숫자와 지도가
    #: 서로 다른 바이트를 가리키게 된다).
    REPORT_ALREADY_RECORDED = "REPORT_ALREADY_RECORDED"


_STATUS: dict[DesignConformanceRequestVerdict, int] = {
    DesignConformanceRequestVerdict.CREATED: 201,
    DesignConformanceRequestVerdict.ALREADY_REQUESTED: 200,
    DesignConformanceRequestVerdict.UNKNOWN_MISSION: 404,
    DesignConformanceRequestVerdict.UNKNOWN_JOB: 422,
    DesignConformanceRequestVerdict.JOB_NOT_SUCCEEDED: 422,
    DesignConformanceRequestVerdict.MISSION_MISMATCH: 422,
    DesignConformanceRequestVerdict.UNKNOWN_DESIGN_SURFACE: 404,
    DesignConformanceRequestVerdict.DESIGN_SURFACE_NOT_VERIFIED: 409,
    DesignConformanceRequestVerdict.DESIGN_NORMALIZATION_MISMATCH: 422,
    DesignConformanceRequestVerdict.ANALYSIS_NOT_READY: 422,
    DesignConformanceRequestVerdict.PROCESSING_PROFILE_UNKNOWN: 422,
    DesignConformanceRequestVerdict.SOURCE_LINEAGE_GAP: 422,
    DesignConformanceRequestVerdict.CRS_MISMATCH: 422,
    DesignConformanceRequestVerdict.VERTICAL_REFERENCE_MISMATCH: 422,
    DesignConformanceRequestVerdict.SITE_MISMATCH: 422,
    DesignConformanceRequestVerdict.NO_DSM_ARTIFACT: 422,
    DesignConformanceRequestVerdict.ZONES_REQUIRED: 422,
    DesignConformanceRequestVerdict.ZONES_INVALID: 422,
    DesignConformanceRequestVerdict.WORK_AREA_UNUSABLE: 422,
    DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN: 422,
    DesignConformanceRequestVerdict.VERTICAL_DATUM_INCOMPATIBLE: 422,
    DesignConformanceRequestVerdict.UNKNOWN_REQUEST: 404,
    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE: 409,
    DesignConformanceRequestVerdict.STORE_UNAVAILABLE: 503,
    DesignConformanceRequestVerdict.LEASED: 201,
    DesignConformanceRequestVerdict.LEASE_RENEWED: 200,
    DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER: 409,
    DesignConformanceRequestVerdict.LEASE_REQUIRED: 409,
    DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION: 409,
    DesignConformanceRequestVerdict.STALE_LEASE_GENERATION: 409,
    DesignConformanceRequestVerdict.INVALID_LEASE_FENCE: 422,
    DesignConformanceRequestVerdict.IDEMPOTENCY_CONFLICT: 409,
    DesignConformanceRequestVerdict.TRANSITIONED: 200,
    DesignConformanceRequestVerdict.ILLEGAL_TRANSITION: 409,
    DesignConformanceRequestVerdict.INPUT_READY: 200,
    DesignConformanceRequestVerdict.STORAGE_UNAVAILABLE: 503,
    DesignConformanceRequestVerdict.UPLOAD_READY: 201,
    DesignConformanceRequestVerdict.DIFF_RASTER_VERIFIED: 201,
    # 422 다 — 요청 형식은 옳고 **신고한 내용이 사실과 다르다**(``source_media``·
    # ``design_surfaces`` 의 MISMATCH 와 같은 자리). 재시도로 해결되지 않는다.
    DesignConformanceRequestVerdict.DIFF_RASTER_DIGEST_MISMATCH: 422,
    DesignConformanceRequestVerdict.DIFF_RASTER_UNREADABLE: 503,
    # 둘 다 워커의 요청 순서가 규약을 어긴 것이지 스토리지·입력 문제가 아니다.
    DesignConformanceRequestVerdict.NO_REPORT_RECORDED: 422,
    DesignConformanceRequestVerdict.REPORT_ALREADY_RECORDED: 409,
}


class DesignConformanceRequestRecoveryError(RuntimeError):
    """design-conformance-requests journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


def build_design_conformance_request_id(mission_id: str, sequence: int) -> str:
    """``{missionId}-dcf{n}`` — ``build_comparison_request_id`` 와 동형."""
    return f"{mission_id}-dcf{sequence}"


def design_conformance_id_of(request_id: str) -> str:
    """리포트 id 를 요청 id 에서 **결정적으로** 도출한다 — 지금은 같은 문자열이다.

    같게 둔 이유가 있다. :class:`~ksi_event_contracts.design_conformance_report.
    DesignConformanceReport` 에는 ``requestId`` 필드가 없다(리포트는 결과이지
    지시가 아니다). 그래서 Core 가 제출된 리포트를 **어느 요청의 것인지** 되짚는
    유일한 경로가 이 도출이고, 항등이면 그 되짚기가 문자열 조작 없이 끝난다
    (비교 워커가 ``volumeChangeId=requestId`` 로 제출하는 것과 같은 관습).

    함수로 감싸 두는 이유는 그 항등성이 **약속**임을 한 곳에 남기기 위해서다 —
    한쪽만 접두사를 붙이는 변경이 조용히 통과하지 않는다.
    """
    return request_id


def diff_raster_id_of(request_id: str) -> str:
    """차분 래스터 자산 id — 리포트 id 와 구분되어야 하므로 접미사를 붙인다."""
    return f"{request_id}-diff"


def build_design_conformance_raster_object_key(
    *,
    site_id: str,
    design_conformance_id: str,
    worker_instance_id: str | None = None,
    lease_acquisition_id: str | None = None,
    lease_generation: int | None = None,
) -> str:
    """차분 래스터가 놓이는 자리 — **서버가 만든다**.

    구성요소를 전부 재검증한다: 호출부가 이미 검증했더라도 이 함수가 경로 탈출을
    막는 마지막 지점이다. 새 fenced 시도는 generation/acquisition 별 candidate
    namespace를 쓴다. 인자가 전부 없는 호출만 과거 journal을 읽기 위한 legacy
    conventional key를 돌려준다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(design_conformance_id):
        raise ValueError(f"경로-안전하지 않은 designConformanceId: {design_conformance_id!r}")
    identity = (worker_instance_id, lease_acquisition_id, lease_generation)
    if identity == (None, None, None):
        return f"sites/{site_id}/design-conformance/{design_conformance_id}"
    if worker_instance_id is None or lease_acquisition_id is None or lease_generation is None:
        raise ValueError("generation-scoped diff raster key requires the complete lease fence")
    fence = LeaseFence(worker_instance_id, lease_acquisition_id, lease_generation)
    if not fence.is_well_formed():
        raise ValueError("generation-scoped diff raster key requires a valid lease fence")
    return (
        f"sites/{site_id}/design-conformance/{design_conformance_id}/attempts/"
        f"{lease_generation}/{worker_instance_id}/{lease_acquisition_id}/diff-raster"
    )


def recompute_diff_raster_digest(storage: EvidenceStorage, object_key: str) -> tuple[str, int]:
    """**Core 가 그 객체의 바이트를 직접 읽어 자기 hashlib 으로** digest·크기를 낸다.

    ``mission_plans`` 가 자기가 만든 KMZ 바이트를 ``hashlib.sha256(kmz).hexdigest()``
    로 직접 해싱하는 것과 같은 원칙이되, 여기는 **워커가 올린 바이트를 읽어 재계산**
    한다는 점이 다르다 — 그래서 이 함수의 반환값은 워커의 신고와 대조되는 기준이지
    워커가 준 값이 아니다.

    반환 표기는 ``sha256:`` 접두사가 붙은 산출물 참조용이다(``DiffRasterRef.digest``
    의 패턴). 크기는 스토리지 포트가 별도로 주지 않으므로(``EvidenceStorage`` 에
    크기 메서드가 없다) **읽은 바이트 길이**다.

    부재도 :class:`EvidenceStorageError` 다(포트 계약) — 호출자가 "없다"를 조용히
    통과시키지 않게 여기서 삼키지 않는다. 전량을 메모리에 올리는 것은
    ``get_bytes`` 포트의 성질이고(KMZ 경로와 같다), 차분 래스터는 원본 사진·점군과
    달리 격자 하나짜리라 이 경로를 견딘다.
    """
    data = storage.get_bytes(object_key)
    return f"sha256:{hashlib.sha256(data).hexdigest()}", len(data)


def _diff_raster_key_for(
    record: DesignConformanceRequestRecord, fence: LeaseFence | None
) -> str:
    if fence is None:
        return build_design_conformance_raster_object_key(
            site_id=record.site_id,
            design_conformance_id=record.design_conformance_id,
        )
    return build_design_conformance_raster_object_key(
        site_id=record.site_id,
        design_conformance_id=record.design_conformance_id,
        worker_instance_id=fence.worker_instance_id,
        lease_acquisition_id=fence.lease_acquisition_id,
        lease_generation=fence.lease_generation,
    )


@dataclass(frozen=True, slots=True)
class DiffRasterVerification:
    """Core 가 재해싱해 확인한 사실 — 워커의 자기보고가 아니다."""

    digest: str
    size_bytes: int
    verified_at: datetime
    verified_by: str
    # ``None`` only for historical pre-TASK-1B records.  New records bind the
    # exact candidate object and the lease generation that produced it.
    object_key: str | None = None
    content_type: str | None = None
    worker_instance_id: str | None = None
    lease_acquisition_id: str | None = None
    lease_generation: int | None = None

    @property
    def fence(self) -> LeaseFence | None:
        if (
            self.worker_instance_id is None
            or self.lease_acquisition_id is None
            or self.lease_generation is None
        ):
            return None
        return LeaseFence(
            self.worker_instance_id,
            self.lease_acquisition_id,
            self.lease_generation,
        )


@dataclass(frozen=True, slots=True)
class DesignConformanceRequestRecord:
    """설계 대비 요청 1건의 projection — 지시 + 요청 시점 스냅샷 + 운영 메타."""

    request_id: str
    mission_id: str
    site_id: str
    design_surface_id: str
    #: 요청 시점 VERIFIED 설계면의 **관측된** 해시(접두사 없는 16진).
    design_surface_sha256: str
    design_vertical_reference: VerticalReference
    current_job_id: str
    current: ArtifactRef
    zones: dict[str, dict[str, Any]]
    zone_crs: str
    policy: ComparisonPolicy
    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str
    updated_at: datetime
    # REQ-INT-104 / INV-053 compatibility anchors.  ``None`` appears only on
    # historical journal records created before ADR-KSI-030; those records stay
    # readable but cannot become a new progress-comparison basis.
    processing_profile_digest: str | None = None
    source_bundle_digest: str | None = None
    design_surface_revision: str | None = None
    design_normalization_profile: str | None = None
    design_normalization_digest: str | None = None
    detail: str | None = None
    lease: JobLease | None = None
    diff_raster: DiffRasterVerification | None = None

    @property
    def design_conformance_id(self) -> str:
        return design_conformance_id_of(self.request_id)

    @property
    def diff_raster_id(self) -> str:
        return diff_raster_id_of(self.request_id)


@dataclass(frozen=True, slots=True)
class DesignConformanceRequestResult:
    verdict: DesignConformanceRequestVerdict
    detail: str | None = None
    record: DesignConformanceRequestRecord | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _require_aware_iso(raw: Any, field_name: str, request_id: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise DesignConformanceRequestRecoveryError(
            f"재생: {field_name} 이 tz-naive 다 — requestId={request_id}"
        )
    return value


def _find_dsm(artifacts: tuple[ProcessingArtifact, ...]) -> ProcessingArtifact | None:
    return next((a for a in artifacts if a.kind is ProcessingArtifactKind.DSM), None)


@dataclass(frozen=True, slots=True)
class _Resolved:
    """생성 게이트를 통과한 요청의 파생값 — live 생성과 재생이 공유한다."""

    site_id: str
    design_surface_sha256: str
    design_vertical_reference: VerticalReference
    current: ArtifactRef
    current_vertical_reference: VerticalReference
    processing_profile_digest: str | None
    source_bundle_digest: str | None
    design_surface_revision: str | None
    design_normalization_profile: str | None
    design_normalization_digest: str | None


class DesignConformanceRequestStore:
    """``DurableJournal`` 위의 설계 대비 요청 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
        design_surface_store: DesignSurfaceStore,
        work_area_store: WorkAreaStore | None = None,
        report_exists: Callable[[str], bool] | None = None,
        analysis_readiness: AnalysisReadinessCheck | None = None,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        self._design_surface_store = design_surface_store
        self._analysis_readiness = analysis_readiness
        # "이 designConformanceId 로 리포트가 이미 기록됐나" — 리포트 원장에 직접
        # 의존하지 않고 술어만 주입받는다. 리포트 저장소가 이미 **이쪽**을 참조하므로
        # (``DesignConformanceStore._request_store``) 반대 방향 참조를 들이면 순환이
        # 된다. 미주입이면 두 게이트(리포트 없는 SUCCEEDED · 기록 후 래스터 재작성)가
        # 닫히지 않으므로 조립 표가 항상 넘긴다 — 테스트 픽스처만 생략한다.
        self._report_exists = report_exists
        # 작업구역 저장소가 없으면 ``workAreaIds`` 경로가 닫힌다(즉석 폴리곤은
        # 그대로 된다) — 조립 표가 동반을 강제하므로 프로덕션에서는 항상 있다.
        self._work_area_store = work_area_store
        # Result finalization holds this lock while the report journal appends.
        # RLock lets same-thread validation helpers reuse getters without
        # weakening the cross-thread authority boundary.
        self._lock = threading.RLock()
        self._requests: dict[str, DesignConformanceRequestRecord] = {}
        self._lease_acquisitions: dict[str, dict[str, JobLease]] = {}
        self._lease_acquisition_bindings: dict[str, tuple[str, JobLease]] = {}
        self._lease_generation_high_water: dict[str, int] = {}
        self._by_request_shape: dict[tuple[str, str, str], str] = {}
        self._sequence: dict[str, int] = {}
        try:
            self._replay(journal)
        except DesignConformanceRequestRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise DesignConformanceRequestRecoveryError(
                f"design-conformance-requests journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _visible_in_request(self, record: DesignConformanceRequestRecord) -> bool:
        """Mission 원장 조직 범위를 설계 대비 요청의 유일한 공개 경계로 쓴다."""

        return (
            current_request_organization_id() is None
            or self._mission_store.get(record.mission_id) is not None
        )

    def mission_is_visible(self, mission_id: str) -> bool:
        return self._mission_store.get(mission_id) is not None

    # ── 재생 ─────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "design-conformance-request-created":
                self._replay_created(raw)
            elif kind == "design-conformance-request-leased":
                self._replay_lease(raw)
            elif kind == "design-conformance-request-transitioned":
                self._replay_transition(raw)
            elif kind == "design-conformance-request-diff-raster-verified":
                self._replay_diff_raster(raw)
            else:
                raise DesignConformanceRequestRecoveryError(
                    f"알 수 없는 journal 레코드 kind: {kind!r}"
                )

    def _replay_created(self, raw: dict[str, Any]) -> None:
        """생성 레코드 재생 — **live 와 같은 게이트를 다시 태운다.**

        설계면이 그 사이 REJECTED 로 바뀌는 일은 없지만(VERIFIED 는 종단),
        journal 조작으로 "검증되지 않은 설계면을 가리키는 요청"이 되살아나는
        경로는 이 재검사가 막는다(``comparison_requests._replay_created`` 원칙).
        """
        request_id = raw["requestId"]
        zones = raw["zones"]
        anchor_keys = (
            "processingProfileDigest",
            "sourceBundleDigest",
            "designSurfaceRevision",
            "designNormalizationProfile",
            "designNormalizationDigest",
        )
        enforce_civil_preflight = any(key in raw for key in anchor_keys)
        verdict, detail, resolved = self._resolve(
            mission_id=raw["missionId"],
            design_surface_id=raw["designSurfaceId"],
            current_job_id=raw["currentJobId"],
            zones=zones,
            zone_crs=raw["zoneCrs"],
            enforce_civil_preflight=enforce_civil_preflight,
        )
        if verdict is not DesignConformanceRequestVerdict.CREATED or resolved is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 기록될 수 없는 요청({verdict.value}: {detail}) — requestId={request_id}"
            )
        if enforce_civil_preflight and (
            raw.get("processingProfileDigest") != resolved.processing_profile_digest
            or raw.get("sourceBundleDigest") != resolved.source_bundle_digest
            or raw.get("designSurfaceRevision") != resolved.design_surface_revision
            or raw.get("designNormalizationProfile") != resolved.design_normalization_profile
            or raw.get("designNormalizationDigest") != resolved.design_normalization_digest
        ):
            raise DesignConformanceRequestRecoveryError(
                "재생: civil compatibility anchor가 현재 immutable 입력 원장과 다르다 — "
                f"requestId={request_id}"
            )
        requested_at = _require_aware_iso(raw["ts"], "ts", request_id)
        record = DesignConformanceRequestRecord(
            request_id=request_id,
            mission_id=raw["missionId"],
            site_id=resolved.site_id,
            design_surface_id=raw["designSurfaceId"],
            design_surface_sha256=resolved.design_surface_sha256,
            design_vertical_reference=resolved.design_vertical_reference,
            current_job_id=raw["currentJobId"],
            current=resolved.current,
            zones=zones,
            zone_crs=raw["zoneCrs"],
            # **원장에 적힌 그 값**을 되살린다 — 여기서 current_comparison_policy()
            # 를 부르면 기준값을 바꾼 배포가 과거 요청의 기준까지 소급해 고쳐 쓴다
            # (comparison_requests 와 같은 근거).
            policy=ComparisonPolicy.model_validate(raw["policy"]),
            status=ProcessingJobStatus.QUEUED,
            requested_at=requested_at,
            requested_by=raw["requestedBy"],
            updated_at=requested_at,
            processing_profile_digest=raw.get("processingProfileDigest"),
            source_bundle_digest=raw.get("sourceBundleDigest"),
            design_surface_revision=raw.get("designSurfaceRevision"),
            design_normalization_profile=raw.get("designNormalizationProfile"),
            design_normalization_digest=raw.get("designNormalizationDigest"),
        )
        self._project(record)
        sequence = int(request_id.rsplit("-dcf", 1)[-1])
        self._sequence[record.mission_id] = max(self._sequence.get(record.mission_id, 0), sequence)

    def _replay_lease(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 미지 requestId lease 레코드 — {request_id}"
            )
        if record.status not in _ACTIVE_STATUSES:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 종료된 요청({record.status.value})에 lease 레코드가 있다 — {request_id}"
            )
        lease = JobLease(
            worker_id=raw.get("workerInstanceId", raw["workerId"]),
            granted_at=_require_aware_iso(raw.get("grantedAt", raw["ts"]), "grantedAt", request_id),
            expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", request_id),
            lease_acquisition_id=raw.get("leaseAcquisitionId"),
            lease_generation=int(raw.get("leaseGeneration", 0)),
            authenticated_actor_id=raw.get("authenticatedActorId"),
        )
        if "leaseGeneration" in raw:
            mode, renewal = raw.get("leaseMode"), raw.get("renewal")
            if (
                not isinstance(renewal, bool)
                or mode not in {LeaseMode.CLAIM.value, LeaseMode.RENEW.value}
                or renewal != (mode == LeaseMode.RENEW.value)
                or lease.fence is None
                or not lease.fence.is_well_formed()
                or lease.expires_at <= lease.granted_at
            ):
                raise DesignConformanceRequestRecoveryError("재생: malformed fenced lease")
            high_water, current = self._lease_generation_high_water.get(request_id, 0), record.lease
            if mode == LeaseMode.CLAIM.value:
                if (
                    lease.lease_generation != high_water + 1
                    or lease.lease_acquisition_id in self._lease_acquisition_bindings
                ):
                    raise DesignConformanceRequestRecoveryError(
                        "재생: CLAIM generation/acquisition 불일치"
                    )
            elif (
                current is None
                or current.fence != lease.fence
                or high_water != lease.lease_generation
                or current.granted_at != lease.granted_at
                or current.authenticated_actor_id != lease.authenticated_actor_id
            ):
                raise DesignConformanceRequestRecoveryError(
                    "재생: RENEW current fence/principal 불일치"
                )
        if lease.lease_acquisition_id is not None:
            global_prior = self._lease_acquisition_bindings.get(lease.lease_acquisition_id)
            if global_prior is not None and (
                global_prior[0] != request_id or global_prior[1].fence != lease.fence
            ):
                raise DesignConformanceRequestRecoveryError(
                    "재생: 전역 CLAIM acquisition binding 충돌"
                )
            self._lease_acquisition_bindings[lease.lease_acquisition_id] = (request_id, lease)
            bindings = self._lease_acquisitions.setdefault(request_id, {})
            prior = bindings.get(lease.lease_acquisition_id)
            if prior is not None and prior.fence != lease.fence:
                raise DesignConformanceRequestRecoveryError("재생: CLAIM acquisition binding 충돌")
            bindings[lease.lease_acquisition_id] = lease
        self._lease_generation_high_water[request_id] = max(
            self._lease_generation_high_water.get(request_id, 0), lease.lease_generation
        )
        self._requests[request_id] = replace(
            record,
            lease=lease,
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 미지 requestId 전이 레코드 — {request_id}"
            )
        transitioned_at = _require_aware_iso(raw["ts"], "ts", request_id)
        if record.lease is not None and record.lease.lease_generation > 0:
            fence_raw = raw.get("leaseFence")
            if not isinstance(fence_raw, dict):
                raise DesignConformanceRequestRecoveryError("재생: fenced 전이에 leaseFence가 없다")
            fence = LeaseFence(
                str(fence_raw["workerInstanceId"]),
                str(fence_raw["leaseAcquisitionId"]),
                int(fence_raw["leaseGeneration"]),
            )
            if check_lease(
                record.lease,
                fence=fence,
                authenticated_actor_id=raw.get("actor"),
                now=transitioned_at,
            ) is not None:
                raise DesignConformanceRequestRecoveryError(
                    "재생: fenced 전이가 당시 lease와 다르다"
                )
        after = ProcessingJobStatus(raw["targetStatus"])
        assert_design_conformance_transition(record.status, after)
        self._requests[request_id] = replace(
            record,
            status=after,
            detail=raw.get("detail"),
            updated_at=transitioned_at,
        )

    def _replay_diff_raster(self, raw: dict[str, Any]) -> None:
        """래스터 확인 레코드 재생 — **바이트를 다시 읽지는 않는다.**

        기동이 오브젝트 스토리지 가용성에 묶이면 스토리지 한 번 흔들릴 때 Core 가
        아예 못 뜬다. 원장에 남은 사실("Core 가 그때 읽어 이 digest 였다")을 그대로
        복원하고, **바이트가 지금도 그 digest 인지**는 리포트가 굳는 순간 다시
        확인된다(``design_conformance_reports`` 의 record 경로 — 그쪽이 이 사실을
        살아 있는 것으로 만드는 자리다).
        """
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 미지 requestId 래스터 확인 레코드 — {request_id}"
            )
        authority_version = raw.get("authorityVersion")
        fence: LeaseFence | None = None
        object_key: str | None = None
        content_type: str | None = None
        if authority_version is not None:
            if authority_version != 1:
                raise DesignConformanceRequestRecoveryError(
                    f"재생: 지원하지 않는 diff raster authorityVersion — {authority_version!r}"
                )
            try:
                fence = LeaseFence(
                    raw["workerInstanceId"],
                    raw["leaseAcquisitionId"],
                    int(raw["leaseGeneration"]),
                )
                object_key = raw["objectKey"]
                content_type = raw["contentType"]
            except (KeyError, TypeError, ValueError) as exc:
                raise DesignConformanceRequestRecoveryError(
                    "재생: generation-aware diff raster authority가 불완전하다"
                ) from exc
            if not fence.is_well_formed() or record.lease is None or record.lease.fence != fence:
                raise DesignConformanceRequestRecoveryError(
                    "재생: diff raster verification fence가 당시 current lease와 다르다"
                )
            expected_key = build_design_conformance_raster_object_key(
                site_id=record.site_id,
                design_conformance_id=record.design_conformance_id,
                worker_instance_id=fence.worker_instance_id,
                lease_acquisition_id=fence.lease_acquisition_id,
                lease_generation=fence.lease_generation,
            )
            if object_key != expected_key or content_type != DIFF_RASTER_CONTENT_TYPE:
                raise DesignConformanceRequestRecoveryError(
                    "재생: diff raster object authority가 canonical candidate와 다르다"
                )
        elif any(
            key in raw
            for key in (
                "objectKey",
                "contentType",
                "workerInstanceId",
                "leaseAcquisitionId",
                "leaseGeneration",
            )
        ):
            raise DesignConformanceRequestRecoveryError(
                "재생: authorityVersion 없는 부분적 diff raster authority"
            )
        self._requests[request_id] = replace(
            record,
            diff_raster=DiffRasterVerification(
                digest=raw["digest"],
                size_bytes=int(raw["sizeBytes"]),
                verified_at=_require_aware_iso(raw["ts"], "ts", request_id),
                verified_by=raw["verifiedBy"],
                object_key=object_key,
                content_type=content_type,
                worker_instance_id=fence.worker_instance_id if fence is not None else None,
                lease_acquisition_id=fence.lease_acquisition_id if fence is not None else None,
                lease_generation=fence.lease_generation if fence is not None else None,
            ),
        )

    def _project(self, record: DesignConformanceRequestRecord) -> None:
        self._requests[record.request_id] = record
        self._by_request_shape[_request_shape(record)] = record.request_id

    # ── 생성 게이트 (live·재생 공유) ─────────────────────────────────────

    def _resolve(
        self,
        *,
        mission_id: str,
        design_surface_id: str,
        current_job_id: str,
        zones: dict[str, dict[str, Any]] | None,
        zone_crs: str | None,
        enforce_civil_preflight: bool = True,
    ) -> tuple[DesignConformanceRequestVerdict, str | None, _Resolved | None]:
        """ "이 지시가 계산 가능한가" — 순서에 뜻이 있다(값싼 것부터, 수직기준이 마지막).

        수직기준을 마지막에 보는 이유: 그 판정은 두 입력이 **둘 다 확정된 뒤에만**
        성립한다. 앞의 게이트를 통과하지 못한 요청에 "수직기준이 다르다"고
        말하면 사용자가 엉뚱한 것을 고친다.
        """
        if self._mission_store.get(mission_id) is None:
            return (
                DesignConformanceRequestVerdict.UNKNOWN_MISSION,
                "발급된 적 없는 임무에는 설계 대비 요청을 만들 수 없다",
                None,
            )
        if not zones:
            return (
                DesignConformanceRequestVerdict.ZONES_REQUIRED,
                "비교 구역(zones)이 확정되지 않았다 — 설계 대비 잔량은 '어느 범위의' "
                "잔량인지 없이 성립하지 않는다",
                None,
            )
        if zone_crs is None:
            return (
                DesignConformanceRequestVerdict.ZONES_REQUIRED,
                "구역 폴리곤의 좌표계(zoneCrs)가 없다",
                None,
            )
        zones_error = assert_zones_are_usable(zones, zone_crs=zone_crs)
        if zones_error is not None:
            return (DesignConformanceRequestVerdict.ZONES_INVALID, zones_error, None)
        surface = self._design_surface_store.get(design_surface_id)
        if surface is None:
            return (
                DesignConformanceRequestVerdict.UNKNOWN_DESIGN_SURFACE,
                f"designSurfaceId={design_surface_id!r} 인 설계 기준면이 없다",
                None,
            )
        if surface.status is not DesignSurfaceStatus.VERIFIED or surface.observed is None:
            return (
                DesignConformanceRequestVerdict.DESIGN_SURFACE_NOT_VERIFIED,
                f"설계면이 {surface.status.value} 다 — 검증된(VERIFIED) 설계면만 비교 "
                "입력이 된다. 봉인만으로는 그 파일이 무엇인지 아무도 확인하지 않았다",
                None,
            )
        if enforce_civil_preflight:
            surface_compatibility = preflight_design_surface(surface)
            if not surface_compatibility.compatible:
                assert surface_compatibility.reason is not None  # noqa: S101
                return (
                    DesignConformanceRequestVerdict(surface_compatibility.reason.value),
                    surface_compatibility.detail,
                    None,
                )
        job = self._processing_job_store.get(current_job_id)
        if job is None:
            return (
                DesignConformanceRequestVerdict.UNKNOWN_JOB,
                f"currentJobId={current_job_id!r} 인 처리 작업이 없다",
                None,
            )
        if job.status is not ProcessingJobStatus.SUCCEEDED:
            return (
                DesignConformanceRequestVerdict.JOB_NOT_SUCCEEDED,
                f"현재 지형 작업이 {job.status.value} 다 — SUCCEEDED 작업만 비교 후보다",
                None,
            )
        if job.mission_id != mission_id:
            return (
                DesignConformanceRequestVerdict.MISSION_MISMATCH,
                f"currentJobId 는 임무 {job.mission_id!r} 소속인데 경로의 missionId 는 "
                f"{mission_id!r} 다",
                None,
            )
        if job.site_id != surface.site_id:
            return (
                DesignConformanceRequestVerdict.SITE_MISMATCH,
                f"설계면은 현장 {surface.site_id!r}, 현재 지형은 현장 {job.site_id!r} 다 — "
                "다른 현장의 계획고와는 비교할 수 없다",
                None,
            )
        dsm = _find_dsm(authoritative_artifacts(job))
        if dsm is None:
            return (
                DesignConformanceRequestVerdict.NO_DSM_ARTIFACT,
                f"작업 {current_job_id!r} 에 dsm 산출물이 없다 — 설계 대비 잔량은 표면 "
                "함수 z=f(x,y) 의 적분이다",
                None,
            )
        if enforce_civil_preflight:
            epoch_compatibility = preflight_single_epoch(
                job,
                analysis_readiness=self._analysis_readiness,
                artifacts=(dsm,),
            )
            if not epoch_compatibility.compatible:
                assert epoch_compatibility.reason is not None  # noqa: S101
                return (
                    DesignConformanceRequestVerdict(epoch_compatibility.reason.value),
                    epoch_compatibility.detail,
                    None,
                )
            if dsm.crs is None:
                return (
                    DesignConformanceRequestVerdict.CRS_MISMATCH,
                    "DSM 산출물의 CRS가 미상이다",
                    None,
                )
            try:
                dsm_crs = normalise_crs(dsm.crs)
                surface_crs = normalise_crs(surface.observed.crs)
            except UnsupportedCrsError as exc:
                return (
                    DesignConformanceRequestVerdict.CRS_MISMATCH,
                    f"DSM 또는 설계면 CRS를 해석할 수 없다: {exc}",
                    None,
                )
            if dsm_crs != surface_crs:
                return (
                    DesignConformanceRequestVerdict.CRS_MISMATCH,
                    f"DSM과 설계면 CRS가 다르다(current={dsm_crs}, design={surface_crs})",
                    None,
                )
        if dsm.vertical_reference is None:
            return (
                (
                    DesignConformanceRequestVerdict.VERTICAL_REFERENCE_MISMATCH
                    if enforce_civil_preflight
                    else DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN
                ),
                "이 산출물은 수직기준이 기록되기 전에 등록됐다 — 설계면과의 비교는 "
                "'어느 기준의 높이인가'를 모른 채로는 숫자를 낼 수 없다. 재처리하면 "
                "비교할 수 있다",
                None,
            )
        try:
            # "계열이 같은가"가 아니라 "이을 수 있는가" 다 — 격자로 이을 수 있는
            # 조합은 여기서 통과시키고, 격자 유무는 워커가 답한다(모듈 docstring).
            assert_bridgeable_vertical(dsm.vertical_reference, surface.declared.vertical_reference)
        except VerticalDatumIncompatibleError as exc:
            return (
                (
                    DesignConformanceRequestVerdict.VERTICAL_REFERENCE_MISMATCH
                    if enforce_civil_preflight
                    else DesignConformanceRequestVerdict.VERTICAL_DATUM_INCOMPATIBLE
                ),
                str(exc),
                None,
            )
        profile_digest: str | None = None
        source_digest: str | None = None
        design_revision: str | None = None
        normalization_profile: str | None = None
        normalization_digest: str | None = None
        if enforce_civil_preflight:
            profile_digest = job.processing_profile_digest
            source_digest = job.input.source_bundle_digest
            (
                design_revision,
                normalization_profile,
                normalization_digest,
            ) = design_normalization_anchor(surface)
        return (
            DesignConformanceRequestVerdict.CREATED,
            None,
            _Resolved(
                site_id=job.site_id,
                # **관측값이 정본이다.** VERIFIED 설계면은 계약이 observed.sha256 ==
                # declared.sha256 을 이미 강제하므로 두 값은 같지만, 여기서 읽는
                # 것은 "신뢰 경로가 바이트를 읽어 잰 값"이어야 한다 — 선언은 그
                # 대조를 통과한 주장일 뿐이고, 계약이 느슨해지는 날 잘못된 쪽을
                # 앵커로 쓰게 된다(``run_design_conformance.DesignSource`` 의
                # docstring 도 observed 를 가리킨다).
                design_surface_sha256=surface.observed.sha256,
                design_vertical_reference=surface.declared.vertical_reference,
                current=ArtifactRef(job_id=current_job_id, artifact_id=dsm.artifact_id),
                current_vertical_reference=dsm.vertical_reference,
                processing_profile_digest=profile_digest,
                source_bundle_digest=source_digest,
                design_surface_revision=design_revision,
                design_normalization_profile=normalization_profile,
                design_normalization_digest=normalization_digest,
            ),
        )

    # ── live 경로 ────────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _zones_from_work_areas(
        self,
        work_area_ids: list[str],
        *,
        current_job_id: str,
        zones: dict[str, dict[str, Any]] | None,
    ) -> tuple[dict[str, dict[str, Any]], str] | str:
        """작업구역 id → ``(zones, zoneCrs)`` **값**. 실패 시 사람이 읽는 사유 (M4-C).

        **현장 소속 검사는 여기서 하지 않는다.** 이 시점에는 현장을 모른다 — 현장은
        처리 작업이 알려주는데, 그 작업의 유효성 판정(``_resolve``)은 구역이 이미
        있어야 시작한다. 그래서 순서를 이렇게 둔다: 여기서 폴리곤만 풀고,
        ``_resolve`` 가 현장을 확정한 뒤 :meth:`_assert_work_areas_of_site` 가 대조한다.
        이렇게 하면 "작업이 없다"는 실패가 ``WORK_AREA_UNUSABLE`` 이 아니라 원래
        이름인 ``UNKNOWN_JOB`` 으로 나온다(같은 실패를 두 이름으로 부르지 않는다).
        """
        del current_job_id  # 현장 대조는 _resolve 이후로 미룬다(위 docstring)
        if zones:
            return (
                "workAreaIds 와 zones 를 동시에 줬다 — 어느 쪽이 진짜 지시인지 서버가 "
                "골라 주면 화면이 보낸 것과 계산에 쓴 것이 갈릴 수 있다. 하나만 준다"
            )
        if self._work_area_store is None:
            return (
                "이 배포에는 작업구역 저장소가 조립되지 않았다 — zones 로 직접 폴리곤을 "
                "주는 경로를 쓴다"
            )
        return self._work_area_store.resolve_zones(work_area_ids, site_id=None)

    def _assert_work_areas_of_site(self, work_area_ids: list[str], *, site_id: str) -> str | None:
        """고른 구역이 전부 이 현장 것인가 — 아니면 사람이 읽는 사유."""
        if self._work_area_store is None:  # pragma: no cover -- 호출부가 이미 걸렀다
            return None
        owners = self._work_area_store.site_of(work_area_ids)
        others = owners - {site_id}
        if others:
            return (
                f"고른 작업구역이 다른 현장 소속이다: {sorted(others)} — "
                f"이 비교의 현장은 {site_id!r} 다. 다른 현장의 구역으로는 잴 수 없다"
            )
        return None

    def create(
        self,
        mission_id: str,
        *,
        design_surface_id: str,
        current_job_id: str,
        zones: dict[str, dict[str, Any]] | None,
        zone_crs: str | None,
        requested_by: str,
        now: datetime,
        work_area_ids: list[str] | None = None,
    ) -> DesignConformanceRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            if work_area_ids is not None:
                resolved_zones = self._zones_from_work_areas(
                    work_area_ids, current_job_id=current_job_id, zones=zones
                )
                if isinstance(resolved_zones, str):
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.WORK_AREA_UNUSABLE,
                        detail=resolved_zones,
                    )
                zones, zone_crs = resolved_zones
            verdict, detail, resolved = self._resolve(
                mission_id=mission_id,
                design_surface_id=design_surface_id,
                current_job_id=current_job_id,
                zones=zones,
                zone_crs=zone_crs,
            )
            if verdict is not DesignConformanceRequestVerdict.CREATED or resolved is None:
                return DesignConformanceRequestResult(verdict, detail=detail)
            assert zones is not None  # noqa: S101 -- _resolve 가 빈 zones 를 이미 거부한다
            assert zone_crs is not None  # noqa: S101
            if work_area_ids is not None:
                # 현장은 이제 확정됐다(``_resolve`` 가 설계면·작업의 현장 일치까지
                # 이미 봤다) — 여기서 고른 구역의 소속을 대조한다.
                mismatch = self._assert_work_areas_of_site(work_area_ids, site_id=resolved.site_id)
                if mismatch is not None:
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.WORK_AREA_UNUSABLE, detail=mismatch
                    )

            existing_id = self._by_request_shape.get(
                (design_surface_id, current_job_id, zone_fingerprint(zones, zone_crs))
            )
            if existing_id is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.ALREADY_REQUESTED,
                    detail="같은 조합(설계면+현재 작업+구역)의 요청이 이미 있다",
                    record=self._requests[existing_id],
                )

            sequence = self._sequence.get(mission_id, 0) + 1
            request_id = build_design_conformance_request_id(mission_id, sequence)
            record = DesignConformanceRequestRecord(
                request_id=request_id,
                mission_id=mission_id,
                site_id=resolved.site_id,
                design_surface_id=design_surface_id,
                design_surface_sha256=resolved.design_surface_sha256,
                design_vertical_reference=resolved.design_vertical_reference,
                current_job_id=current_job_id,
                current=resolved.current,
                zones=zones,
                zone_crs=zone_crs,
                # 지금 이 배포의 기준값을 값으로 굳힌다 — 이후 이 요청은 시스템
                # 기준이 바뀌어도 자기 스냅샷으로만 계산된다.
                policy=current_comparison_policy(),
                status=ProcessingJobStatus.QUEUED,
                requested_at=now,
                requested_by=requested_by,
                updated_at=now,
                processing_profile_digest=resolved.processing_profile_digest,
                source_bundle_digest=resolved.source_bundle_digest,
                design_surface_revision=resolved.design_surface_revision,
                design_normalization_profile=resolved.design_normalization_profile,
                design_normalization_digest=resolved.design_normalization_digest,
            )
            raw = {
                "kind": "design-conformance-request-created",
                "ts": iso_utc(now),
                "requestId": request_id,
                "missionId": mission_id,
                "designSurfaceId": design_surface_id,
                "currentJobId": current_job_id,
                "zones": zones,
                "zoneCrs": zone_crs,
                "policy": record.policy.model_dump(by_alias=True, mode="json"),
                "requestedBy": requested_by,
                "processingProfileDigest": record.processing_profile_digest,
                "sourceBundleDigest": record.source_bundle_digest,
                "designSurfaceRevision": record.design_surface_revision,
                "designNormalizationProfile": record.design_normalization_profile,
                "designNormalizationDigest": record.design_normalization_digest,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            self._project(record)
            self._sequence[mission_id] = sequence
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.CREATED, record=record
            )

    def get(self, request_id: str) -> DesignConformanceRequestRecord | None:
        with self._lock:
            record = self._requests.get(request_id)
        return record if record is not None and self._visible_in_request(record) else None

    def bind_report_existence(self, report_exists: Callable[[str], bool]) -> None:
        """리포트 존재 술어를 조립 후에 걸어준다.

        생성자로 못 받는 이유는 순환이다 — 리포트 원장이 이 저장소를 인자로 받아
        만들어지므로(``DesignConformanceStore(request_store=...)``) 이쪽이 그것을
        생성자에서 요구하면 서로를 먼저 요구하게 된다. 조립 표
        (:func:`ksi_core.app_assembly`)가 두 원장을 다 만든 뒤 한 번 호출한다.
        """
        self._report_exists = report_exists

    def report_already_recorded(self, design_conformance_id: str) -> bool:
        """이 id 로 리포트가 이미 기록됐나 — 주입된 술어에 위임한다.

        미주입(테스트 픽스처)이면 ``False`` 를 돌려 기존 동작을 유지한다. 조립 표는
        항상 주입하므로(:mod:`ksi_core.app`) 프로덕션에서는 실제 리포트 원장을 본다.
        """
        if self._report_exists is None:
            return False
        return self._report_exists(design_conformance_id)

    def get_by_design_conformance_id(
        self, design_conformance_id: str
    ) -> DesignConformanceRequestRecord | None:
        """리포트가 가리키는 요청 — 도출이 한 곳에만 있게 하는 관문.

        리포트에는 ``requestId`` 가 없다(:func:`design_conformance_id_of`) —
        리포트 원장이 자기만의 되짚기 규칙을 갖지 않도록 여기로 물어본다.
        """
        return self.get(design_conformance_id)

    @contextmanager
    def authoritative_result_guard(
        self,
        design_conformance_id: str,
        *,
        now: datetime,
        lease_fence: LeaseFence | None,
        legacy_worker_id: str | None = None,
        authenticated_actor_id: str | None = None,
    ) -> Iterator[DesignConformanceRequestResult]:
        """Hold the request authority boundary through a report journal append.

        The caller may acquire its report-store lock and append only while this
        context is open.  Therefore a takeover cannot occur between the final
        fence check and durable report creation.  ``legacy_worker_id`` is only
        accepted when the replayed lease itself predates fenced generations.
        """

        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                yield DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
                return
            record = self._requests.get(design_conformance_id)
            if record is None or not self._visible_in_request(record):
                yield DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST,
                    detail=_NOT_FOUND_DETAIL,
                )
                return
            if record.status not in _ACTIVE_STATUSES:
                yield DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 결과를 확정할 수 없다",
                    record=record,
                )
                return
            worker_id = (
                (legacy_worker_id or record.lease.worker_id)
                if lease_fence is None and record.lease is not None and record.lease.fence is None
                else None
            )
            denied = self._check_lease_locked(
                record,
                fence=lease_fence,
                worker_id=worker_id,
                authenticated_actor_id=authenticated_actor_id,
                now=now,
            )
            if denied is not None:
                verdict, detail = denied
                yield DesignConformanceRequestResult(verdict, detail=detail, record=record)
                return
            yield DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.INPUT_READY,
                record=record,
            )

    def has_recorded_lease_fence(
        self,
        design_conformance_id: str,
        fence: LeaseFence,
        *,
        authenticated_actor_id: str | None = None,
    ) -> bool:
        """Return whether durable lease history binds ``fence`` to this request."""

        with self._lock:
            lease = self._lease_acquisitions.get(design_conformance_id, {}).get(
                fence.lease_acquisition_id
            )
            return (
                lease is not None
                and lease.fence == fence
                and (
                    lease.authenticated_actor_id is None
                    or lease.authenticated_actor_id == authenticated_actor_id
                )
            )

    def vertical_reference_of_current(
        self, record: DesignConformanceRequestRecord
    ) -> VerticalReference | None:
        """현재 DSM 산출물이 선언한 수직기준 — 요청에 복사해 두지 않고 조회한다.

        ``ComparisonRequestStore.vertical_reference_of`` 와 같은 자리·같은 이유다:
        수직기준은 지시가 아니라 **산출물의 성질**이고, 지시에 복사해 두면 산출물
        쪽 사실과 두 벌이 된다. 생성 게이트가 ``None`` 을 이미 거부했으므로 정상
        경로에서 이 값은 항상 있다.
        """
        job = self._processing_job_store.get(record.current.job_id)
        if job is None:
            return None
        artifact = next(
            (
                a
                for a in authoritative_artifacts(job)
                if a.artifact_id == record.current.artifact_id
            ),
            None,
        )
        return artifact.vertical_reference if artifact is not None else None

    def list_for_mission(self, mission_id: str) -> list[DesignConformanceRequestRecord]:
        if (
            current_request_organization_id() is not None
            and self._mission_store.get(mission_id) is None
        ):
            return []
        with self._lock:
            records = [r for r in self._requests.values() if r.mission_id == mission_id]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id), reverse=True)

    def list_pending(
        self, *, now: datetime, limit: int = 50
    ) -> list[DesignConformanceRequestRecord]:
        """``QUEUED`` + lease 만료된 ``RUNNING`` — ``leasing.is_claimable`` 재사용."""
        if limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            records = [r for r in self._requests.values() if is_claimable(r.status, r.lease, now)]
        if current_request_organization_id() is not None:
            records = [r for r in records if self._visible_in_request(r)]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id))[:limit]

    @staticmethod
    def _check_lease_locked(
        record: DesignConformanceRequestRecord,
        *,
        now: datetime,
        fence: LeaseFence | None = None,
        worker_id: str | None = None,
        authenticated_actor_id: str | None = None,
    ) -> tuple[DesignConformanceRequestVerdict, str] | None:
        denial = check_lease(
            record.lease, fence=fence, worker_id=worker_id,
            authenticated_actor_id=authenticated_actor_id, now=now,
        )
        if denial is LeaseDenialReason.MISSING_OR_EXPIRED:
            return (
                DesignConformanceRequestVerdict.LEASE_REQUIRED,
                "이 요청의 lease 를 먼저 잡아야 한다",
            )
        if denial is LeaseDenialReason.HELD_BY_ANOTHER:
            assert record.lease is not None  # noqa: S101 -- HELD_BY_ANOTHER 는 lease 가 있을 때만
            return (
                DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({record.lease.worker_id})가 {iso_utc(record.lease.expires_at)} 까지 "
                "이 요청을 쥐고 있다 — 만료 후 다시 시도한다",
            )
        if denial is LeaseDenialReason.STALE_ACQUISITION:
            return (
                DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION,
                "이전 CLAIM acquisition 은 현재 lease 소유자가 아니다",
            )
        if denial is LeaseDenialReason.STALE_GENERATION:
            return (
                DesignConformanceRequestVerdict.STALE_LEASE_GENERATION,
                "이전 lease generation 은 현재 lease 를 변경할 수 없다",
            )
        if denial is LeaseDenialReason.INVALID_FENCE:
            return (
                DesignConformanceRequestVerdict.INVALID_LEASE_FENCE,
                "worker lease fence 가 유효하지 않다",
            )
        return None

    def acquire_lease(
        self,
        request_id: str,
        *,
        now: datetime,
        ttl: timedelta = DEFAULT_LEASE_TTL,
        worker_id: str | None = None,
        lease_fence: LeaseFence | None = None,
        worker_instance_id: str | None = None,
        lease_acquisition_id: str | None = None,
        lease_generation: int | None = None,
        lease_mode: LeaseMode = LeaseMode.CLAIM,
        authenticated_actor_id: str | None = None,
    ) -> DesignConformanceRequestResult:
        """요청 하나를 쥔다. 같은 워커의 재호출은 갱신(heartbeat)."""
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            record = self._requests.get(request_id)
            if record is None or not self._visible_in_request(record):
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 잡을 수 없다",
                )
            if (
                lease_fence is None
                and worker_instance_id is not None
                and lease_acquisition_id is not None
            ):
                lease_fence = LeaseFence(
                    worker_instance_id, lease_acquisition_id, lease_generation or 0
                )
            if lease_fence is None:
                if worker_id is None:
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.INVALID_LEASE_FENCE, record=record
                    )
                current_for_legacy = record.lease
                if current_for_legacy is not None and current_for_legacy.is_active(now):
                    if current_for_legacy.worker_instance_id != worker_id:
                        return DesignConformanceRequestResult(
                            DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER, record=record
                        )
                    lease_fence = LeaseFence(
                        worker_id,
                        current_for_legacy.lease_acquisition_id or worker_id,
                        current_for_legacy.lease_generation,
                    )
                    lease_mode = LeaseMode.RENEW
                else:
                    lease_fence = LeaseFence(worker_id, worker_id, 0)
            if worker_id is None and (
                not lease_fence.has_valid_ids()
                or (lease_mode is LeaseMode.RENEW and lease_fence.lease_generation < 1)
            ):
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.INVALID_LEASE_FENCE, record=record
                )
            current = record.lease
            if lease_mode is LeaseMode.CLAIM and worker_id is None:
                global_prior = self._lease_acquisition_bindings.get(
                    lease_fence.lease_acquisition_id
                )
                if global_prior is not None and global_prior[0] != request_id:
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.IDEMPOTENCY_CONFLICT, record=record
                    )
            if lease_mode is LeaseMode.CLAIM and worker_id is None:
                prior = self._lease_acquisitions.get(request_id, {}).get(
                    lease_fence.lease_acquisition_id
                )
                if prior is not None:
                    if (
                        prior.worker_instance_id != lease_fence.worker_instance_id
                        or prior.authenticated_actor_id != authenticated_actor_id
                    ):
                        return DesignConformanceRequestResult(
                            DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION, record=record
                        )
                    if (
                        current is not None
                        and current.lease_acquisition_id == prior.lease_acquisition_id
                        and current.is_active(now)
                    ):
                        return DesignConformanceRequestResult(
                            DesignConformanceRequestVerdict.LEASED, record=record
                        )
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION, record=record
                    )
            if (
                lease_mode is LeaseMode.CLAIM
                and current is not None
                and current.lease_acquisition_id == lease_fence.lease_acquisition_id
            ):
                if (
                    current.worker_instance_id != lease_fence.worker_instance_id
                    or current.authenticated_actor_id != authenticated_actor_id
                    or not current.is_active(now)
                ):
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION, record=record
                    )
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.LEASED, record=record
                )
            if lease_mode is LeaseMode.RENEW:
                denied = self._check_lease_locked(
                    record,
                    fence=None if worker_id is not None else lease_fence,
                    worker_id=worker_id,
                    authenticated_actor_id=authenticated_actor_id,
                    now=now,
                )
                if denied is not None:
                    verdict, detail = denied
                    return DesignConformanceRequestResult(verdict, detail=detail, record=record)
                assert current is not None
                generation, granted_at = current.lease_generation, current.granted_at
            else:
                denial = (
                    check_lease(current, fence=lease_fence, now=now)
                    if current is not None
                    else LeaseDenialReason.MISSING_OR_EXPIRED
                )
                if denial is LeaseDenialReason.HELD_BY_ANOTHER:
                    assert current is not None
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER,
                        detail=(
                            f"다른 워커({current.worker_id})가 "
                            f"{iso_utc(current.expires_at)} 까지 이 요청을 쥐고 있다 "
                            "— 만료 후 다시 시도한다"
                        ),
                        record=record,
                    )
                if current is not None and current.is_active(now):
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION,
                        detail="활성 lease 중에는 다른 acquisition 으로 다시 CLAIM 할 수 없다",
                        record=record,
                    )
                if (
                    current is not None
                    and current.lease_acquisition_id == lease_fence.lease_acquisition_id
                ):
                    return DesignConformanceRequestResult(
                        DesignConformanceRequestVerdict.STALE_LEASE_ACQUISITION, record=record
                    )
                generation, granted_at = (
                    (
                        0
                        if worker_id is not None
                        else self._lease_generation_high_water.get(request_id, 0) + 1
                    ),
                    None,
                )
            new_lease = next_lease(
                worker_instance_id=lease_fence.worker_instance_id,
                lease_acquisition_id=None
                if worker_id is not None
                else lease_fence.lease_acquisition_id,
                lease_generation=generation,
                authenticated_actor_id=(
                    current.authenticated_actor_id
                    if lease_mode is LeaseMode.RENEW and current is not None
                    else authenticated_actor_id
                ),
                now=now,
                ttl=ttl,
                granted_at=granted_at,
            )
            raw = {
                "kind": "design-conformance-request-leased",
                "ts": iso_utc(now),
                "requestId": request_id,
                "grantedAt": iso_utc(new_lease.granted_at),
                "expiresAt": iso_utc(new_lease.expires_at),
                **(
                    lease_raw_fields(lease=new_lease, mode=lease_mode)
                    if worker_id is None
                    else {"workerId": worker_id, "renewal": lease_mode is LeaseMode.RENEW}
                ),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            updated = replace(record, lease=new_lease)
            self._requests[request_id] = updated
            if new_lease.lease_acquisition_id is not None:
                self._lease_acquisitions.setdefault(request_id, {})[
                    new_lease.lease_acquisition_id
                ] = new_lease
                self._lease_acquisition_bindings[new_lease.lease_acquisition_id] = (
                    request_id,
                    new_lease,
                )
            self._lease_generation_high_water[request_id] = max(
                self._lease_generation_high_water.get(request_id, 0), new_lease.lease_generation
            )
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.LEASE_RENEWED
                if lease_mode is LeaseMode.RENEW
                else DesignConformanceRequestVerdict.LEASED,
                record=updated,
            )

    def transition(
        self,
        request_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
        lease_fence: LeaseFence | None = None,
    ) -> DesignConformanceRequestResult:
        _require_tz_aware(now, param="now")
        # **리포트 존재 확인은 우리 락 밖에서 한다 — 교착 방지.**
        #
        # 리포트 원장은 설계상 이 저장소를 참조한다(``record()`` 가 자기 락을 쥔 채
        # ``get_by_design_conformance_id`` 를 부른다: report-lock → request-lock).
        # 그런데 이 확인을 ``with self._lock:`` 안에서 하면 반대 방향
        # (request-lock → report-lock)이 생겨 AB-BA 교착이 닫힌다 — 라우트가 sync
        # ``def`` 라 FastAPI 가 스레드풀에서 돌리므로 실제로 동시에 뛴다(리포트를
        # 제출하는 워커와 다른 요청을 성공 전이시키는 워커). 2026-08-16 독립 검토가
        # 적발했고 락 순서만 흉내낸 재현으로 실재를 확인했다.
        #
        # 락 밖 확인의 TOCTOU 는 fail-closed 쪽으로만 틀린다: 리포트는 append-only 라
        # 술어는 False→True 로만 바뀐다. "없다"를 보고 거부한 직후 리포트가 들어오면
        # 그 워커는 다시 호출하면 되고(불필요한 1회 거부), "있다"를 본 뒤 사라지는
        # 일은 없다. designConformanceId 는 requestId 에서 순수 도출이라
        # (:func:`design_conformance_id_of`) 레코드를 읽지 않고도 구할 수 있다.
        if current_request_organization_id() is not None and self.get(request_id) is None:
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
            )
        report_missing_for_success = False
        if target is ProcessingJobStatus.SUCCEEDED and self._report_exists is not None:
            report_missing_for_success = not self._report_exists(
                design_conformance_id_of(request_id)
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            record = self._requests.get(request_id)
            if record is None or not self._visible_in_request(record):
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            denied = self._check_lease_locked(
                record, fence=lease_fence, worker_id=actor if lease_fence is None else None,
                authenticated_actor_id=actor if lease_fence is not None else None, now=now
            )
            if denied is not None:
                verdict, detail_msg = denied
                return DesignConformanceRequestResult(verdict, detail=detail_msg, record=record)
            try:
                assert_design_conformance_transition(record.status, target)
            except IllegalDesignConformanceTransitionError as exc:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.ILLEGAL_TRANSITION,
                    detail=str(exc),
                    record=record,
                )
            # **성공은 결과가 있어야 성공이다.** 전이표는 RUNNING→SUCCEEDED 를 항상
            # 허용하므로(상태기계만 보면 합법) lease 를 쥔 워커가 리포트를 한 번도
            # 올리지 않고 SUCCEEDED 만 선언할 수 있었다 — 그러면 요청 목록은 성공인데
            # 리포트 조회는 404 인 모순이 남고, 라우터의 자동 연동이 그 위에 구역
            # 추출 요청까지 발급한다(존재하지 않는 차분 위에 후속 작업이 쌓인다).
            # FAILED 에는 걸지 않는다 — 실패는 결과가 없는 것이 정상이다.
            # 판정 자체는 락 밖에서 이미 끝났다(위 주석 — 교착 방지).
            if report_missing_for_success:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.NO_REPORT_RECORDED,
                    detail=(
                        "이 요청으로 기록된 리포트가 없다 — 리포트를 먼저 제출해야 "
                        "성공으로 전이할 수 있다"
                    ),
                    record=record,
                )
            raw: dict[str, Any] = {
                "kind": "design-conformance-request-transitioned",
                "ts": iso_utc(now),
                "requestId": request_id,
                "targetStatus": target.value,
                "detail": detail,
                "actor": actor,
            }
            if lease_fence is not None:
                raw["leaseFence"] = {
                    "workerInstanceId": lease_fence.worker_instance_id,
                    "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                    "leaseGeneration": lease_fence.lease_generation,
                }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            updated = replace(record, status=target, detail=detail, updated_at=now)
            self._requests[request_id] = updated
            DESIGN_CONFORMANCE_REQUEST_TRANSITIONS.inc(target_status=target.value)
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.TRANSITIONED, record=updated
            )

    def record_diff_raster_verification(
        self,
        request_id: str,
        *,
        digest: str,
        size_bytes: int,
        worker_id: str,
        now: datetime,
        object_key: str | None = None,
        content_type: str = DIFF_RASTER_CONTENT_TYPE,
        lease_fence: LeaseFence | None = None,
    ) -> DesignConformanceRequestResult:
        """**Core 가 확인한** 래스터 사실을 원장에 남긴다 — 대조는 호출자가 이미 했다.

        여기 들어오는 ``digest``/``size_bytes`` 는 워커의 신고가 아니라
        :func:`recompute_diff_raster_digest` 가 **스토리지 바이트에서 직접 계산한**
        값이다(라우터가 그 대조를 통과시킨 뒤에만 부른다). 그래서 이 메서드는
        기록만 하고 판정하지 않는다.

        같은 digest 로 재호출하면 무기록 멱등이다(재시도가 원장을 부풀리지
        않는다). 다른 digest 면 새 확인을 남긴다 — 재계산이 다른 바이트를 냈다는
        사실 자체가 원장에 남아야 한다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            record = self._requests.get(request_id)
            if record is None or not self._visible_in_request(record):
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            denied = self._check_lease_locked(
                record,
                fence=lease_fence,
                worker_id=worker_id if lease_fence is None else None,
                authenticated_actor_id=worker_id,
                now=now,
            )
            if denied is not None:
                verdict, detail = denied
                return DesignConformanceRequestResult(verdict, detail=detail, record=record)
            expected_key = (
                build_design_conformance_raster_object_key(
                    site_id=record.site_id,
                    design_conformance_id=record.design_conformance_id,
                    worker_instance_id=lease_fence.worker_instance_id,
                    lease_acquisition_id=lease_fence.lease_acquisition_id,
                    lease_generation=lease_fence.lease_generation,
                )
                if lease_fence is not None
                else build_design_conformance_raster_object_key(
                    site_id=record.site_id,
                    design_conformance_id=record.design_conformance_id,
                )
            )
            if object_key is None and lease_fence is None:
                object_key = expected_key
            if object_key != expected_key or content_type != DIFF_RASTER_CONTENT_TYPE:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.INVALID_LEASE_FENCE,
                    detail="diff raster candidate identity가 current lease namespace와 다르다",
                    record=record,
                )
            candidate = DiffRasterVerification(
                digest=digest,
                size_bytes=size_bytes,
                verified_at=now,
                verified_by=worker_id,
                object_key=object_key if lease_fence is not None else None,
                content_type=content_type if lease_fence is not None else None,
                worker_instance_id=(
                    lease_fence.worker_instance_id if lease_fence is not None else None
                ),
                lease_acquisition_id=(
                    lease_fence.lease_acquisition_id if lease_fence is not None else None
                ),
                lease_generation=(
                    lease_fence.lease_generation if lease_fence is not None else None
                ),
            )
            if record.diff_raster is not None and (
                record.diff_raster.digest == candidate.digest
                and record.diff_raster.size_bytes == candidate.size_bytes
                and record.diff_raster.object_key == candidate.object_key
                and record.diff_raster.content_type == candidate.content_type
                and record.diff_raster.fence == candidate.fence
            ):
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.DIFF_RASTER_VERIFIED, record=record
                )
            raw = {
                "kind": "design-conformance-request-diff-raster-verified",
                "ts": iso_utc(now),
                "requestId": request_id,
                "digest": digest,
                "sizeBytes": size_bytes,
                "verifiedBy": worker_id,
                **(
                    {
                        "authorityVersion": 1,
                        "objectKey": object_key,
                        "contentType": content_type,
                        "workerInstanceId": lease_fence.worker_instance_id,
                        "leaseAcquisitionId": lease_fence.lease_acquisition_id,
                        "leaseGeneration": lease_fence.lease_generation,
                    }
                    if lease_fence is not None
                    else {}
                ),
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            updated = replace(
                record,
                diff_raster=candidate,
            )
            self._requests[request_id] = updated
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.DIFF_RASTER_VERIFIED, record=updated
            )


def _request_shape(record: DesignConformanceRequestRecord) -> tuple[str, str, str]:
    """멱등 판정 키 — **무엇을, 무엇과, 어느 범위로 비교하라는 지시인가**.

    임무·현장은 넣지 않는다(``comparison_requests._request_shape`` 와 같은 근거 —
    jobId 가 이미 그것들을 결정한다).
    """
    return (
        record.design_surface_id,
        record.current_job_id,
        zone_fingerprint(record.zones, record.zone_crs),
    )


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class DesignConformanceRequestCreateInput(CamelModel):
    """요청 생성 본문 — **무엇을 무엇과 비교할지**만 정한다.

    구역은 현장 AOI 를 자동으로 쓰지 않는다(``ComparisonRequestCreateInput`` 과
    같은 근거) — 대시보드가 사용자 확인을 거친 폴리곤 값을 여기 싣는다. 다만
    저쪽과 달리 **생략할 수 없다**: 구역 없는 설계 대비 잔량은 답이 아니라 질문의
    누락이다(``ZONES_REQUIRED``).

    구역을 주는 길은 둘이고 **동시에 쓸 수 없다**(M4-C):

    - ``workAreaIds`` — 등록된 작업구역을 고른다. Core 가 폴리곤을 값으로 풀어
      ``zones`` 에 넣는다. ``zoneId`` 가 ``workAreaId`` 라 다음 시점의 리포트와
      자동으로 이어진다(진척 계산의 전제).
    - ``zones``/``zoneCrs`` — 즉석 폴리곤. 한 번 보고 마는 비교에 남겨 둔 경로다.
      매번 좌표가 달라지므로 시계열로 이어지지 않는다.

    둘 다 주면 거부한다 — 어느 쪽이 진짜 지시인지 서버가 골라 주면, 화면이 보낸
    것과 계산에 쓴 것이 갈릴 수 있다.
    """

    design_surface_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
    work_area_ids: list[str] | None = None
    zones: dict[str, dict[str, Any]] | None = None
    zone_crs: str | None = None


class DesignConformanceRequestView(CamelModel):
    """요청 1건의 조회 표현 — 지시 + 요청 시점 스냅샷 + 운영 메타."""

    request_id: str
    design_conformance_id: str
    mission_id: str
    site_id: str
    design_surface_id: str
    design_surface_sha256: str
    processing_profile_digest: str | None
    source_bundle_digest: str | None
    design_surface_revision: str | None
    design_normalization_profile: str | None
    design_normalization_digest: str | None
    current: ArtifactRef
    zones: dict[str, dict[str, Any]]
    zone_crs: str
    policy: ComparisonPolicy
    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str
    updated_at: datetime
    detail: str | None
    lease_worker_id: str | None
    lease_expires_at: datetime | None
    #: Core 가 차분 래스터 바이트를 직접 재해싱해 확인한 digest — 아직 없으면 null.
    diff_raster_digest: str | None
    diff_raster_verified_at: datetime | None


class DesignConformanceRequestMutationResponse(CamelModel):
    verdict: str
    request: DesignConformanceRequestView | None = None
    detail: str | None = None


class DesignConformanceRequestListResponse(CamelModel):
    requests: list[DesignConformanceRequestView]


class PendingDesignConformanceRequestView(CamelModel):
    """워커가 다음에 잡을 후보 1건 — 최소 노출(``PendingComparisonRequestView`` 동형)."""

    request_id: str
    requested_at: datetime


class PendingDesignConformanceRequestListResponse(CamelModel):
    requests: list[PendingDesignConformanceRequestView]


class DesignConformanceTransitionRequest(CamelModel):
    target_status: ProcessingJobStatus
    detail: str | None = None


class DesignConformanceInputView(CamelModel):
    """워커가 실제로 계산하는 데 필요한 것 — presigned GET 2개 + 스냅샷.

    ``designSurfaceSha256`` 을 주는 것이 설계면 **검증** 워커와 다른 점이다.
    저쪽은 신고값을 알면 읽지 않고 되읊을 수 있어 주지 않지만(``design_surfaces``
    모듈 docstring), 여기서 이 값의 용도는 판정이 아니라 **"받아온 바이트가 그때
    검증된 그 파일인가"** 다 — 스토리지 교체·손상·잘못된 URL 을 값싸게 잡는
    확인이고(``run_design_conformance._assert_design_bytes_unchanged``), 이 값이
    없으면 그 확인 자체가 불가능하다.

    ``designConformanceId``/``diffRasterId`` 도 Core 가 준다 — id 도출 규칙이
    워커에 복제되면 한쪽만 바뀌는 날 리포트가 어느 요청의 것인지 되짚을 수 없다.
    """

    request_id: str
    mission_id: str
    status: ProcessingJobStatus
    policy: ComparisonPolicy
    design_conformance_id: str
    diff_raster_id: str
    design_surface_id: str
    design_surface_sha256: str
    design_surface_url: str
    design_vertical_reference: VerticalReference
    current: ArtifactRef
    current_url: str
    current_vertical_reference: VerticalReference
    zones: dict[str, dict[str, Any]]
    zone_crs: str


class DesignConformanceInputResponse(CamelModel):
    verdict: str
    input: DesignConformanceInputView | None = None
    detail: str | None = None


class DiffRasterUploadUrlResponse(CamelModel):
    verdict: str
    object_key: str | None = None
    upload_url: str | None = None
    content_type: str | None = None
    expires_at: datetime | None = None
    required_headers: dict[str, str] = Field(default_factory=dict)
    detail: str | None = None


class DiffRasterUploadUrlRequest(CamelModel):
    """Candidate bytes known before presigning, so PUT itself can bind digest."""

    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)


class DiffRasterVerificationRequest(CamelModel):
    """워커가 신고하는 값 — **Core 는 이것을 믿지 않고 대조 대상으로만 쓴다.**"""

    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)


class DiffRasterVerificationResponse(CamelModel):
    verdict: str
    #: Core 가 스토리지 바이트에서 **직접 계산한** digest(신고값이 아니다).
    digest: str | None = None
    size_bytes: int | None = None
    #: 리포트의 ``diffRaster.coreVerifiedDigestAt`` 에 그대로 실릴 값.
    verified_at: datetime | None = None
    detail: str | None = None


def _to_view(record: DesignConformanceRequestRecord) -> DesignConformanceRequestView:
    return DesignConformanceRequestView(
        request_id=record.request_id,
        design_conformance_id=record.design_conformance_id,
        mission_id=record.mission_id,
        site_id=record.site_id,
        design_surface_id=record.design_surface_id,
        design_surface_sha256=record.design_surface_sha256,
        processing_profile_digest=record.processing_profile_digest,
        source_bundle_digest=record.source_bundle_digest,
        design_surface_revision=record.design_surface_revision,
        design_normalization_profile=record.design_normalization_profile,
        design_normalization_digest=record.design_normalization_digest,
        current=record.current,
        zones=record.zones,
        zone_crs=record.zone_crs,
        policy=record.policy,
        status=record.status,
        requested_at=record.requested_at,
        requested_by=record.requested_by,
        updated_at=record.updated_at,
        detail=record.detail,
        lease_worker_id=record.lease.worker_id if record.lease is not None else None,
        lease_expires_at=record.lease.expires_at if record.lease is not None else None,
        diff_raster_digest=(record.diff_raster.digest if record.diff_raster is not None else None),
        diff_raster_verified_at=(
            record.diff_raster.verified_at if record.diff_raster is not None else None
        ),
    )


#: 설계 대비 잔량이 성공한 뒤 자동으로 잇는 변화 영역 추출 요청의 신고 주체.
#: 사람 principal 이 아니라 이 문자열로 남겨, 화면·감사 로그에서 "누가 눌렀나"가
#: 아니라 "설계 대비 성공이 자동으로 이었다"는 사실이 그대로 보이게 한다.
_AUTO_CHAIN_ACTOR = "system:design-conformance-auto-chain"


def build_design_conformance_requests_router(
    store: DesignConformanceRequestStore,
    storage: EvidenceStorage,
    *,
    region_extraction_store: RegionExtractionRequestStore | None = None,
) -> APIRouter:
    """``region_extraction_store`` 가 주어지면 잔량 계산 성공을 변화 영역
    추출로 자동으로 잇는다(대표자 결정 2026-08-15, region-extraction-ux-decision) —
    사람이 버튼을 한 번 더 누르지 않아도 "설계 대비 분석"이라는 하나의 상위
    작업 안에서 잔량 계산과 변화 영역 추출이 이어진다. 자동으로 잇지 **않는**
    것은 재관측 Mission 발급이다 — 변화 영역을 보고 재관측할지는 여전히
    사람이 지도에서 고른다(``region_extraction_reports.py`` 의
    ``getSpatialRefreshDraft`` 가 "임무를 발급하지 않는다"고 이미 밝힌 경계와
    같은 자리다).
    """
    router = APIRouter(tags=["design-conformance-requests"])

    @router.post(
        "/v1/missions/{mission_id}/design-conformance-requests",
        response_model=DesignConformanceRequestMutationResponse,
        status_code=201,
    )
    def create_design_conformance_request(
        mission_id: str,
        request: DesignConformanceRequestCreateInput,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> DesignConformanceRequestMutationResponse:
        """ "이 설계면과 이 지형을 비교하라"는 지시 접수 — **사람이 발급**한다.

        권한이 ``MISSIONS_ISSUE`` 인 것은 비교 요청 생성과 같은 자리다 — 계산해
        제출하는 것은 워커의 일이지만 "무엇을 무엇과 비교할지" 지목하는 것은
        사람의 결정이다.
        """
        result = store.create(
            mission_id,
            design_surface_id=request.design_surface_id,
            current_job_id=request.current_job_id,
            zones=request.zones,
            zone_crs=request.zone_crs,
            work_area_ids=request.work_area_ids,
            requested_by=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is DesignConformanceRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DesignConformanceRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/missions/{mission_id}/design-conformance-requests",
        response_model=DesignConformanceRequestListResponse,
    )
    def list_design_conformance_requests(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> DesignConformanceRequestListResponse:
        """그 임무의 설계 대비 요청 이력(최신 우선)."""
        if not store.mission_is_visible(mission_id):
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return DesignConformanceRequestListResponse(
            requests=[_to_view(r) for r in store.list_for_mission(mission_id)]
        )

    @router.get(
        "/v1/design-conformance-requests",
        response_model=PendingDesignConformanceRequestListResponse,
    )
    def list_pending_design_conformance_requests(
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> PendingDesignConformanceRequestListResponse:
        """워커 pull 표면 — ``QUEUED`` + lease 만료된 ``RUNNING``, 오래된 것부터(FIFO)."""
        return PendingDesignConformanceRequestListResponse(
            requests=[
                PendingDesignConformanceRequestView(
                    request_id=r.request_id, requested_at=r.requested_at
                )
                for r in store.list_pending(now=datetime.now(UTC), limit=limit)
            ]
        )

    @router.post(
        "/v1/design-conformance-requests/{request_id}/lease",
        response_model=DesignConformanceRequestMutationResponse,
        status_code=201,
    )
    def acquire_design_conformance_lease(
        request_id: str,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        lease_mode_header: str | None = Header(default=None, alias="X-KSI-Lease-Mode"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceRequestMutationResponse:
        try:
            mode = LeaseMode(lease_mode_header or "CLAIM")
            fence = (
                LeaseFence(
                    worker_instance_id or "", lease_acquisition_id or "", int(lease_generation or 0)
                )
                if worker_instance_id is not None and lease_acquisition_id is not None
                else None
            )
        except ValueError:
            mode, fence = LeaseMode.CLAIM, None
        result = store.acquire_lease(
            request_id,
            lease_fence=fence,
            lease_mode=mode,
            authenticated_actor_id=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.record is not None and result.record.lease is not None:
            lease = result.record.lease
            response.headers["X-KSI-Worker-Instance-Id"] = lease.worker_instance_id
            if lease.lease_acquisition_id is not None:
                response.headers["X-KSI-Lease-Acquisition-Id"] = lease.lease_acquisition_id
            response.headers["X-KSI-Lease-Generation"] = str(lease.lease_generation)
        if result.verdict is DesignConformanceRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DesignConformanceRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/design-conformance-requests/{request_id}/input",
        response_model=DesignConformanceInputResponse,
    )
    def get_design_conformance_input(
        request_id: str,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceInputResponse:
        """워커가 설계면·현재 DSM 바이트를 읽는 유일한 경로 — lease 를 쥔 워커만 통과한다."""
        record = store.get(request_id)
        if record is None:
            response.status_code = 404
            return DesignConformanceInputResponse(
                verdict=DesignConformanceRequestVerdict.UNKNOWN_REQUEST.value,
                detail=_NOT_FOUND_DETAIL,
            )
        try:
            fence = (
                LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
                if worker_instance_id is not None
                and lease_acquisition_id is not None
                and lease_generation is not None
                else None
            )
        except ValueError:
            fence = None
        denied = DesignConformanceRequestStore._check_lease_locked(
            record,
            fence=fence,
            authenticated_actor_id=principal.principal_id,
            worker_id=(
                principal.principal_id
                if fence is None and record.lease is not None and record.lease.fence is None
                else None
            ),
            now=datetime.now(UTC),
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return DesignConformanceInputResponse(verdict=verdict.value, detail=detail)

        current_vertical = store.vertical_reference_of_current(record)
        if current_vertical is None:
            # 생성 게이트가 이미 거부했어야 하는 상태다 — 그래도 여기서 조용히
            # 기본값을 채우지 않는다(그 순간 숫자가 가정 위에서 나온다).
            response.status_code = _STATUS[
                DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN
            ]
            return DesignConformanceInputResponse(
                verdict=DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN.value,
                detail="현재 DSM 산출물의 수직기준을 더 이상 읽을 수 없다",
            )
        try:
            design_surface = store._design_surface_store.get(record.design_surface_id)
            if design_surface is None:
                response.status_code = 404
                return DesignConformanceInputResponse(
                    verdict=DesignConformanceRequestVerdict.UNKNOWN_DESIGN_SURFACE.value,
                    detail="설계 기준면을 더 이상 읽을 수 없다",
                )
            design_url = storage.presigned_get(
                object_key_for_surface(design_surface),
                ttl=DEFAULT_VIEW_TTL,
            )
            current_url = storage.presigned_get(
                _artifact_object_key(store, record), ttl=DEFAULT_VIEW_TTL
            )
        except EvidenceStorageError:
            logger.warning("설계 대비 입력 URL 발급 실패: requestId=%s", request_id)
            response.status_code = _STATUS[DesignConformanceRequestVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return DesignConformanceInputResponse(
                verdict=DesignConformanceRequestVerdict.STORAGE_UNAVAILABLE.value,
                detail="입력 다운로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        return DesignConformanceInputResponse(
            verdict=DesignConformanceRequestVerdict.INPUT_READY.value,
            input=DesignConformanceInputView(
                request_id=record.request_id,
                mission_id=record.mission_id,
                status=record.status,
                policy=record.policy,
                design_conformance_id=record.design_conformance_id,
                diff_raster_id=record.diff_raster_id,
                design_surface_id=record.design_surface_id,
                design_surface_sha256=record.design_surface_sha256,
                design_surface_url=design_url,
                design_vertical_reference=record.design_vertical_reference,
                current=record.current,
                current_url=current_url,
                current_vertical_reference=current_vertical,
                zones=record.zones,
                zone_crs=record.zone_crs,
            ),
        )

    @router.post(
        "/v1/design-conformance-requests/{request_id}/transitions",
        response_model=DesignConformanceRequestMutationResponse,
    )
    def transition_design_conformance_request(
        request_id: str,
        request: DesignConformanceTransitionRequest,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceRequestMutationResponse:
        """워커만 전이한다 — RUNNING/SUCCEEDED/FAILED 는 계산을 돌린 주체만 아는 사실이다."""
        now = datetime.now(UTC)
        try:
            fence = (
                LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
                if worker_instance_id is not None
                and lease_acquisition_id is not None
                and lease_generation is not None
                else None
            )
        except ValueError:
            fence = None
        result = store.transition(
            request_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=now,
            lease_fence=fence,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is DesignConformanceRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        if (
            region_extraction_store is not None
            and result.verdict is DesignConformanceRequestVerdict.TRANSITIONED
            and result.record is not None
            and request.target_status is ProcessingJobStatus.SUCCEEDED
        ):
            # 잔량 계산 성공 → 변화 영역 추출을 자동으로 잇는다(모듈 docstring
            # region-extraction-ux-decision). 실패해도 이 응답(설계 대비 전이
            # 자체는 이미 성공)을 되돌리지 않는다 — 다음 폴링에서 사람이나
            # 재시도가 그 구멍을 메울 수 있어야 하고, 이미 굳은 성공을 이
            # 부가 작업 하나 때문에 취소할 이유는 없다.
            chain_result = region_extraction_store.create(
                result.record.mission_id,
                design_conformance_id=result.record.design_conformance_id,
                requested_by=_AUTO_CHAIN_ACTOR,
                now=now,
            )
            if chain_result.record is None:
                logger.warning(
                    "[%s] 변화 영역 추출 자동 연동 실패 — verdict=%s detail=%s",
                    request_id,
                    chain_result.verdict.value,
                    chain_result.detail,
                )
        return DesignConformanceRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.post(
        "/v1/design-conformance-requests/{request_id}/diff-raster-upload-url",
        response_model=DiffRasterUploadUrlResponse,
        status_code=201,
    )
    def issue_diff_raster_upload_url(
        request_id: str,
        response: Response,
        request: DiffRasterUploadUrlRequest | None = None,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DiffRasterUploadUrlResponse:
        """차분 래스터를 올릴 자리 — **워커가 객체 키를 고르지 않는다.**

        키는 요청과 current lease generation에서 유도된다(모듈 docstring §객체 키).
        같은 attempt의 exact retry만 같은 candidate를 쓰고 takeover는 다른 키를 쓴다.
        종료된 요청에는 발급하지 않는다:
        이미 굳은 리포트의 래스터가 나중에 다른 바이트로 바뀌는 창을 닫는다.
        """
        record = store.get(request_id)
        if record is None:
            response.status_code = 404
            return DiffRasterUploadUrlResponse(
                verdict=DesignConformanceRequestVerdict.UNKNOWN_REQUEST.value,
                detail=_NOT_FOUND_DETAIL,
            )
        # **종료 판정이 lease 판정보다 앞이다.** 끝난 요청에는 lease 를 새로 잡을
        # 수도 없으므로(``acquire_lease`` 가 REQUEST_NOT_ACTIVE), lease 를 먼저 보면
        # 워커가 받는 사유는 "lease 를 잡아라"가 되고 그건 잡을 수 없는 지시다.
        if record.status not in _ACTIVE_STATUSES:
            response.status_code = _STATUS[DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE]
            return DiffRasterUploadUrlResponse(
                verdict=DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE.value,
                detail=(
                    f"요청이 {record.status.value} 상태다 — 끝난 요청의 래스터는 다시 쓰지 않는다"
                ),
            )
        # 요청이 아직 RUNNING 이어도 **리포트가 이미 기록됐으면** 래스터를 다시 쓸 수
        # 없다. 같은 generation의 candidate URL도 report 확정 뒤 재발급하지 않는다;
        # 이미 발급된 URL은 digest-bound라 다른 바이트로 바꿀 수 없다.
        if store.report_already_recorded(record.design_conformance_id):
            response.status_code = _STATUS[DesignConformanceRequestVerdict.REPORT_ALREADY_RECORDED]
            return DiffRasterUploadUrlResponse(
                verdict=DesignConformanceRequestVerdict.REPORT_ALREADY_RECORDED.value,
                detail=(
                    "이 요청의 리포트가 이미 기록됐다 — 기록된 digest 가 가리키는 "
                    "래스터를 덮어쓸 수 없다"
                ),
            )
        try:
            fence = (
                LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
                if worker_instance_id is not None
                and lease_acquisition_id is not None
                and lease_generation is not None
                else None
            )
        except ValueError:
            fence = None
        denied = DesignConformanceRequestStore._check_lease_locked(
            record,
            fence=fence,
            authenticated_actor_id=principal.principal_id,
            worker_id=(
                principal.principal_id
                if fence is None and record.lease is not None and record.lease.fence is None
                else None
            ),
            now=datetime.now(UTC),
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return DiffRasterUploadUrlResponse(verdict=verdict.value, detail=detail)
        if request is None:
            response.status_code = 422
            return DiffRasterUploadUrlResponse(
                verdict=DesignConformanceRequestVerdict.INVALID_LEASE_FENCE.value,
                detail="digest와 sizeBytes가 있어야 digest-bound 업로드 URL을 발급한다",
            )
        now = datetime.now(UTC)
        object_key = _diff_raster_key_for(record, fence)
        try:
            if not isinstance(storage, DigestBoundEvidenceStorage):
                raise EvidenceStorageError("diff raster storage lacks digest-bound PUT support")
            capability = storage.presigned_put_bound_digest(
                object_key,
                content_type=DIFF_RASTER_CONTENT_TYPE,
                content_digest=request.digest,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError:
            logger.warning("차분 래스터 업로드 URL 발급 실패: requestId=%s", request_id)
            response.status_code = _STATUS[DesignConformanceRequestVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return DiffRasterUploadUrlResponse(
                verdict=DesignConformanceRequestVerdict.STORAGE_UNAVAILABLE.value,
                detail="업로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )
        return DiffRasterUploadUrlResponse(
            verdict=DesignConformanceRequestVerdict.UPLOAD_READY.value,
            object_key=object_key,
            upload_url=capability.upload_url,
            content_type=DIFF_RASTER_CONTENT_TYPE,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
            required_headers=capability.required_headers,
        )

    @router.post(
        "/v1/design-conformance-requests/{request_id}/diff-raster-verification",
        response_model=DiffRasterVerificationResponse,
        status_code=201,
    )
    def verify_diff_raster(
        request_id: str,
        request: DiffRasterVerificationRequest,
        response: Response,
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DiffRasterVerificationResponse:
        """**Core 가 방금 올라온 객체를 직접 읽어 해시를 다시 계산한다.**

        워커가 "올렸다, 해시는 이거다"라고 말한 것만으로는 아무 일도 일어나지
        않는다 — 이 경로가 그 주장을 사실로 바꾸는(또는 반박하는) 유일한 자리이고,
        일치할 때 찍힌 시각만이 리포트의 ``coreVerifiedDigestAt`` 이 될 수 있다.
        """
        record = store.get(request_id)
        if record is None:
            response.status_code = 404
            return DiffRasterVerificationResponse(
                verdict=DesignConformanceRequestVerdict.UNKNOWN_REQUEST.value,
                detail=_NOT_FOUND_DETAIL,
            )
        now = datetime.now(UTC)
        # 업로드 URL 발급과 같은 순서다(그 라우트 주석 참조).
        if record.status not in _ACTIVE_STATUSES:
            response.status_code = _STATUS[DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE]
            return DiffRasterVerificationResponse(
                verdict=DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE.value,
                detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 다시 확인하지 않는다",
            )
        # 업로드 URL 발급과 같은 이유다(그 라우트 주석 참조) — 리포트가 이미 특정
        # digest 를 가리키고 있으면 재확인으로 그 값을 갈아끼울 수 없다.
        if store.report_already_recorded(record.design_conformance_id):
            response.status_code = _STATUS[DesignConformanceRequestVerdict.REPORT_ALREADY_RECORDED]
            return DiffRasterVerificationResponse(
                verdict=DesignConformanceRequestVerdict.REPORT_ALREADY_RECORDED.value,
                detail=(
                    "이 요청의 리포트가 이미 기록됐다 — 기록된 digest 를 다른 "
                    "바이트로 다시 확인할 수 없다"
                ),
            )
        try:
            fence = (
                LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
                if worker_instance_id is not None
                and lease_acquisition_id is not None
                and lease_generation is not None
                else None
            )
        except ValueError:
            fence = None
        denied = DesignConformanceRequestStore._check_lease_locked(
            record,
            fence=fence,
            authenticated_actor_id=principal.principal_id,
            worker_id=(
                principal.principal_id
                if fence is None and record.lease is not None and record.lease.fence is None
                else None
            ),
            now=now,
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return DiffRasterVerificationResponse(verdict=verdict.value, detail=detail)
        object_key = _diff_raster_key_for(record, fence)
        try:
            digest, size_bytes = recompute_diff_raster_digest(storage, object_key)
        except EvidenceStorageError:
            logger.warning(
                "차분 래스터를 읽지 못했다: requestId=%s objectKey=%s", request_id, object_key
            )
            response.status_code = _STATUS[DesignConformanceRequestVerdict.DIFF_RASTER_UNREADABLE]
            response.headers["Retry-After"] = "30"
            return DiffRasterVerificationResponse(
                verdict=DesignConformanceRequestVerdict.DIFF_RASTER_UNREADABLE.value,
                detail=("올렸다는 자리의 객체를 읽지 못했다 — 확인 없이 리포트를 받지 않는다"),
            )
        if digest != request.digest or size_bytes != request.size_bytes:
            response.status_code = _STATUS[
                DesignConformanceRequestVerdict.DIFF_RASTER_DIGEST_MISMATCH
            ]
            return DiffRasterVerificationResponse(
                verdict=DesignConformanceRequestVerdict.DIFF_RASTER_DIGEST_MISMATCH.value,
                digest=digest,
                size_bytes=size_bytes,
                detail=(
                    "올라온 바이트를 Core 가 다시 해싱한 결과가 신고와 다르다 — "
                    f"신고 {request.digest}({request.size_bytes}B), 실제 {digest}({size_bytes}B)"
                ),
            )
        result = store.record_diff_raster_verification(
            request_id,
            digest=digest,
            size_bytes=size_bytes,
            worker_id=principal.principal_id,
            now=now,
            object_key=object_key,
            content_type=DIFF_RASTER_CONTENT_TYPE,
            lease_fence=fence,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is DesignConformanceRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
            return DiffRasterVerificationResponse(
                verdict=result.verdict.value, detail=result.detail
            )
        assert result.record is not None  # noqa: S101 -- VERIFIED 는 store 가 항상 채운다
        assert result.record.diff_raster is not None  # noqa: S101
        verification = result.record.diff_raster
        return DiffRasterVerificationResponse(
            verdict=result.verdict.value,
            digest=verification.digest,
            size_bytes=verification.size_bytes,
            verified_at=verification.verified_at,
        )

    return router


def _artifact_object_key(
    store: DesignConformanceRequestStore, record: DesignConformanceRequestRecord
) -> str:
    """Resolve accepted bytes from the durable manifest, never a guessed key."""
    resolved = store._processing_job_store.resolve_artifact(
        record.current.job_id, record.current.artifact_id
    )
    if resolved is None:
        raise EvidenceStorageError("accepted authoritative DSM 을 찾을 수 없다")
    return resolved.object_key


def mount_design_conformance_requests(
    app: FastAPI,
    store: DesignConformanceRequestStore,
    storage: EvidenceStorage,
    *,
    region_extraction_store: RegionExtractionRequestStore | None = None,
) -> None:
    app.include_router(
        build_design_conformance_requests_router(
            store, storage, region_extraction_store=region_extraction_store
        )
    )


__all__ = [
    "DIFF_RASTER_CONTENT_TYPE",
    "DesignConformanceInputResponse",
    "DesignConformanceInputView",
    "DesignConformanceRequestCreateInput",
    "DesignConformanceRequestListResponse",
    "DesignConformanceRequestMutationResponse",
    "DesignConformanceRequestRecord",
    "DesignConformanceRequestRecoveryError",
    "DesignConformanceRequestResult",
    "DesignConformanceRequestStore",
    "DesignConformanceRequestVerdict",
    "DesignConformanceRequestView",
    "DesignConformanceTransitionRequest",
    "DiffRasterUploadUrlResponse",
    "DiffRasterVerification",
    "DiffRasterVerificationRequest",
    "DiffRasterVerificationResponse",
    "IllegalDesignConformanceTransitionError",
    "PendingDesignConformanceRequestListResponse",
    "PendingDesignConformanceRequestView",
    "assert_design_conformance_transition",
    "build_design_conformance_raster_object_key",
    "build_design_conformance_request_id",
    "build_design_conformance_requests_router",
    "design_conformance_id_of",
    "diff_raster_id_of",
    "mount_design_conformance_requests",
    "recompute_diff_raster_digest",
]
