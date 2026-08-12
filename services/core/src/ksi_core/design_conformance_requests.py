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
2. **수직기준 계열이 다르면 여기서 거부한다.** 타원체고와 정표고를 그냥 빼면
   한국에서 20~30m 가 조용히 섞이고 결과는 여전히 숫자다. 계산 엔진도 자기
   입구에서 같은 판정을 하지만(``run_design_conformance``), 요청 생성 시점에
   막아야 사용자가 **몇 분 뒤 FAILED** 가 아니라 **즉시 사유**를 받는다.
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

## 객체 키는 결정적이다 — 재시도가 orphan 을 쌓지 않는다

``build_design_conformance_raster_object_key(site_id, design_conformance_id)`` 이고
``design_conformance_id`` 는 ``request_id`` 에서 결정적으로 도출된다
(:func:`design_conformance_id_of` — 지금은 같은 문자열이다). 그래서 같은 요청의
재시도는 **같은 자리를 덮어쓴다**. 입력이 불변이고 래스터 쓰기가 결정적이므로
(``diff_raster.write_diff_geotiff`` + 그 결정성 테스트) 덮어쓴 바이트는 이전과
동일하다 — 이미 기록된 리포트의 digest 가 무효해지지 않는다.

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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Response
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy, current_comparison_policy
from ksi_event_contracts.design_surface import DesignSurfaceStatus
from ksi_event_contracts.processing_artifact import ProcessingArtifact, ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus
from ksi_event_contracts.vertical_reference import (
    VerticalDatumIncompatibleError,
    VerticalReference,
    assert_comparable_vertical,
)
from pydantic import Field

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.comparison_requests import zone_fingerprint
from ksi_core.design_surfaces import (
    DESIGN_SURFACE_CONTENT_TYPE,
    build_design_surface_object_key,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.identifiers import is_path_safe_identifier
from ksi_core.leasing import JobLease, LeaseDenialReason, check_lease, is_claimable, next_lease
from ksi_core.metrics import DESIGN_CONFORMANCE_REQUEST_TRANSITIONS
from ksi_core.processing_jobs import (
    DEFAULT_LEASE_TTL,
    ProcessingJobStore,
    build_processing_artifact_object_key,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.design_surfaces import DesignSurfaceStore
    from ksi_core.mission_records import MissionStore

logger = logging.getLogger(__name__)

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
    #: 설계면과 현재 작업이 다른 현장이다 — 다른 현장의 계획고와 비교할 수 없다.
    SITE_MISMATCH = "SITE_MISMATCH"
    #: 현재 작업에 dsm 산출물이 없다 — 표면 함수가 없으면 적분할 것이 없다.
    NO_DSM_ARTIFACT = "NO_DSM_ARTIFACT"
    #: 구역이 확정되지 않았다. 설계 대비 잔량은 "어느 범위의" 잔량인지 없이 성립하지 않는다.
    ZONES_REQUIRED = "ZONES_REQUIRED"
    #: 현재 DSM 이 수직기준을 밝히지 않는다(수직기준 기록 이전의 산출물) — 재처리하면 된다.
    VERTICAL_REFERENCE_UNKNOWN = "VERTICAL_REFERENCE_UNKNOWN"
    #: 설계면과 현재 DSM 의 수직기준 계열이 다르다 — 변환 없이 비교하지 않는다.
    VERTICAL_DATUM_INCOMPATIBLE = "VERTICAL_DATUM_INCOMPATIBLE"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    REQUEST_NOT_ACTIVE = "REQUEST_NOT_ACTIVE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

    # ── lease ────────────────────────────────────────────────────────────
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    LEASE_REQUIRED = "LEASE_REQUIRED"

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


_STATUS: dict[DesignConformanceRequestVerdict, int] = {
    DesignConformanceRequestVerdict.CREATED: 201,
    DesignConformanceRequestVerdict.ALREADY_REQUESTED: 200,
    DesignConformanceRequestVerdict.UNKNOWN_MISSION: 404,
    DesignConformanceRequestVerdict.UNKNOWN_JOB: 422,
    DesignConformanceRequestVerdict.JOB_NOT_SUCCEEDED: 422,
    DesignConformanceRequestVerdict.MISSION_MISMATCH: 422,
    DesignConformanceRequestVerdict.UNKNOWN_DESIGN_SURFACE: 404,
    DesignConformanceRequestVerdict.DESIGN_SURFACE_NOT_VERIFIED: 409,
    DesignConformanceRequestVerdict.SITE_MISMATCH: 422,
    DesignConformanceRequestVerdict.NO_DSM_ARTIFACT: 422,
    DesignConformanceRequestVerdict.ZONES_REQUIRED: 422,
    DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN: 422,
    DesignConformanceRequestVerdict.VERTICAL_DATUM_INCOMPATIBLE: 422,
    DesignConformanceRequestVerdict.UNKNOWN_REQUEST: 404,
    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE: 409,
    DesignConformanceRequestVerdict.STORE_UNAVAILABLE: 503,
    DesignConformanceRequestVerdict.LEASED: 201,
    DesignConformanceRequestVerdict.LEASE_RENEWED: 200,
    DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER: 409,
    DesignConformanceRequestVerdict.LEASE_REQUIRED: 409,
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
    *, site_id: str, design_conformance_id: str
) -> str:
    """차분 래스터가 놓이는 자리 — **서버가 만든다**(``build_design_surface_object_key`` 대칭).

    구성요소를 전부 재검증한다: 호출부가 이미 검증했더라도 이 함수가 경로 탈출을
    막는 마지막 지점이다. 결정적이라 **재시도가 같은 자리를 덮어쓴다**(모듈
    docstring §객체 키) — orphan 이 쌓이지 않는다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(design_conformance_id):
        raise ValueError(f"경로-안전하지 않은 designConformanceId: {design_conformance_id!r}")
    return f"sites/{site_id}/design-conformance/{design_conformance_id}"


def recompute_diff_raster_digest(
    storage: EvidenceStorage, object_key: str
) -> tuple[str, int]:
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


@dataclass(frozen=True, slots=True)
class DiffRasterVerification:
    """Core 가 재해싱해 확인한 사실 — 워커의 자기보고가 아니다."""

    digest: str
    size_bytes: int
    verified_at: datetime
    verified_by: str


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


class DesignConformanceRequestStore:
    """``DurableJournal`` 위의 설계 대비 요청 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
        design_surface_store: DesignSurfaceStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        self._design_surface_store = design_surface_store
        self._lock = threading.Lock()
        self._requests: dict[str, DesignConformanceRequestRecord] = {}
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
        verdict, detail, resolved = self._resolve(
            mission_id=raw["missionId"],
            design_surface_id=raw["designSurfaceId"],
            current_job_id=raw["currentJobId"],
            zones=zones,
            zone_crs=raw["zoneCrs"],
        )
        if verdict is not DesignConformanceRequestVerdict.CREATED or resolved is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 기록될 수 없는 요청({verdict.value}: {detail}) — requestId={request_id}"
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
        )
        self._project(record)
        sequence = int(request_id.rsplit("-dcf", 1)[-1])
        self._sequence[record.mission_id] = max(
            self._sequence.get(record.mission_id, 0), sequence
        )

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
        self._requests[request_id] = replace(
            record,
            lease=JobLease(
                worker_id=raw["workerId"],
                granted_at=_require_aware_iso(raw["ts"], "ts", request_id),
                expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", request_id),
            ),
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise DesignConformanceRequestRecoveryError(
                f"재생: 미지 requestId 전이 레코드 — {request_id}"
            )
        after = ProcessingJobStatus(raw["targetStatus"])
        assert_design_conformance_transition(record.status, after)
        self._requests[request_id] = replace(
            record,
            status=after,
            detail=raw.get("detail"),
            updated_at=_require_aware_iso(raw["ts"], "ts", request_id),
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
        self._requests[request_id] = replace(
            record,
            diff_raster=DiffRasterVerification(
                digest=raw["digest"],
                size_bytes=int(raw["sizeBytes"]),
                verified_at=_require_aware_iso(raw["ts"], "ts", request_id),
                verified_by=raw["verifiedBy"],
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
    ) -> tuple[DesignConformanceRequestVerdict, str | None, _Resolved | None]:
        """"이 지시가 계산 가능한가" — 순서에 뜻이 있다(값싼 것부터, 수직기준이 마지막).

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
        dsm = _find_dsm(job.artifacts)
        if dsm is None:
            return (
                DesignConformanceRequestVerdict.NO_DSM_ARTIFACT,
                f"작업 {current_job_id!r} 에 dsm 산출물이 없다 — 설계 대비 잔량은 표면 "
                "함수 z=f(x,y) 의 적분이다",
                None,
            )
        if dsm.vertical_reference is None:
            return (
                DesignConformanceRequestVerdict.VERTICAL_REFERENCE_UNKNOWN,
                "이 산출물은 수직기준이 기록되기 전에 등록됐다 — 설계면과의 비교는 "
                "'어느 기준의 높이인가'를 모른 채로는 숫자를 낼 수 없다. 재처리하면 "
                "비교할 수 있다",
                None,
            )
        try:
            assert_comparable_vertical(dsm.vertical_reference, surface.declared.vertical_reference)
        except VerticalDatumIncompatibleError as exc:
            return (
                DesignConformanceRequestVerdict.VERTICAL_DATUM_INCOMPATIBLE,
                str(exc),
                None,
            )
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
            ),
        )

    # ── live 경로 ────────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

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
    ) -> DesignConformanceRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
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
            return self._requests.get(request_id)

    def get_by_design_conformance_id(
        self, design_conformance_id: str
    ) -> DesignConformanceRequestRecord | None:
        """리포트가 가리키는 요청 — 도출이 한 곳에만 있게 하는 관문.

        리포트에는 ``requestId`` 가 없다(:func:`design_conformance_id_of`) —
        리포트 원장이 자기만의 되짚기 규칙을 갖지 않도록 여기로 물어본다.
        """
        return self.get(design_conformance_id)

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
            (a for a in job.artifacts if a.artifact_id == record.current.artifact_id), None
        )
        return artifact.vertical_reference if artifact is not None else None

    def list_for_mission(self, mission_id: str) -> list[DesignConformanceRequestRecord]:
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
            records = [
                r for r in self._requests.values() if is_claimable(r.status, r.lease, now)
            ]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id))[:limit]

    @staticmethod
    def _check_lease_locked(
        record: DesignConformanceRequestRecord, *, worker_id: str, now: datetime
    ) -> tuple[DesignConformanceRequestVerdict, str] | None:
        denial = check_lease(record.lease, worker_id=worker_id, now=now)
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
        return None

    def acquire_lease(
        self,
        request_id: str,
        *,
        worker_id: str,
        now: datetime,
        ttl: timedelta = DEFAULT_LEASE_TTL,
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
            if record is None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 잡을 수 없다",
                )
            current = record.lease
            denial = check_lease(current, worker_id=worker_id, now=now)
            renewing = current is not None and denial is None
            if denial is LeaseDenialReason.HELD_BY_ANOTHER:
                assert current is not None  # noqa: S101
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.LEASE_HELD_BY_ANOTHER,
                    detail=(
                        f"다른 워커({current.worker_id})가 {iso_utc(current.expires_at)} 까지 "
                        "이 요청을 쥐고 있다 — 만료 후 다시 시도한다"
                    ),
                    record=record,
                )
            new_lease = next_lease(
                worker_id=worker_id,
                now=now,
                ttl=ttl,
                granted_at=current.granted_at if renewing and current else None,
            )
            raw = {
                "kind": "design-conformance-request-leased",
                "ts": iso_utc(now),
                "requestId": request_id,
                "workerId": worker_id,
                "expiresAt": iso_utc(new_lease.expires_at),
                "renewal": renewing,
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
            return DesignConformanceRequestResult(
                DesignConformanceRequestVerdict.LEASE_RENEWED
                if renewing
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
    ) -> DesignConformanceRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            record = self._requests.get(request_id)
            if record is None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            denied = self._check_lease_locked(record, worker_id=actor, now=now)
            if denied is not None:
                verdict, detail_msg = denied
                return DesignConformanceRequestResult(
                    verdict, detail=detail_msg, record=record
                )
            try:
                assert_design_conformance_transition(record.status, target)
            except IllegalDesignConformanceTransitionError as exc:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.ILLEGAL_TRANSITION,
                    detail=str(exc),
                    record=record,
                )
            raw = {
                "kind": "design-conformance-request-transitioned",
                "ts": iso_utc(now),
                "requestId": request_id,
                "targetStatus": target.value,
                "detail": detail,
                "actor": actor,
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
            if record is None:
                return DesignConformanceRequestResult(
                    DesignConformanceRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.diff_raster is not None and record.diff_raster.digest == digest:
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
                diff_raster=DiffRasterVerification(
                    digest=digest,
                    size_bytes=size_bytes,
                    verified_at=now,
                    verified_by=worker_id,
                ),
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
    """

    design_surface_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
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
    detail: str | None = None


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
        diff_raster_digest=(
            record.diff_raster.digest if record.diff_raster is not None else None
        ),
        diff_raster_verified_at=(
            record.diff_raster.verified_at if record.diff_raster is not None else None
        ),
    )


def build_design_conformance_requests_router(
    store: DesignConformanceRequestStore, storage: EvidenceStorage
) -> APIRouter:
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
        """"이 설계면과 이 지형을 비교하라"는 지시 접수 — **사람이 발급**한다.

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
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceRequestMutationResponse:
        result = store.acquire_lease(
            request_id, worker_id=principal.principal_id, now=datetime.now(UTC)
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
        "/v1/design-conformance-requests/{request_id}/input",
        response_model=DesignConformanceInputResponse,
    )
    def get_design_conformance_input(
        request_id: str,
        response: Response,
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
        denied = DesignConformanceRequestStore._check_lease_locked(
            record, worker_id=principal.principal_id, now=datetime.now(UTC)
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
            design_url = storage.presigned_get(
                build_design_surface_object_key(
                    site_id=record.site_id, design_surface_id=record.design_surface_id
                ),
                ttl=DEFAULT_VIEW_TTL,
            )
            current_url = storage.presigned_get(
                _artifact_object_key(record), ttl=DEFAULT_VIEW_TTL
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
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DesignConformanceRequestMutationResponse:
        """워커만 전이한다 — RUNNING/SUCCEEDED/FAILED 는 계산을 돌린 주체만 아는 사실이다."""
        result = store.transition(
            request_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
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

    @router.post(
        "/v1/design-conformance-requests/{request_id}/diff-raster-upload-url",
        response_model=DiffRasterUploadUrlResponse,
        status_code=201,
    )
    def issue_diff_raster_upload_url(
        request_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DiffRasterUploadUrlResponse:
        """차분 래스터를 올릴 자리 — **워커가 객체 키를 고르지 않는다.**

        키는 요청에서 결정적으로 유도된다(모듈 docstring §객체 키) — 재시도가 같은
        자리를 덮어써 orphan 이 쌓이지 않는다. 종료된 요청에는 발급하지 않는다:
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
                    f"요청이 {record.status.value} 상태다 — 끝난 요청의 래스터는 "
                    "다시 쓰지 않는다"
                ),
            )
        denied = DesignConformanceRequestStore._check_lease_locked(
            record, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return DiffRasterUploadUrlResponse(verdict=verdict.value, detail=detail)
        now = datetime.now(UTC)
        object_key = build_design_conformance_raster_object_key(
            site_id=record.site_id, design_conformance_id=record.design_conformance_id
        )
        try:
            upload_url = storage.presigned_put(
                object_key, content_type=DIFF_RASTER_CONTENT_TYPE, ttl=DEFAULT_UPLOAD_TTL
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
            upload_url=upload_url,
            content_type=DIFF_RASTER_CONTENT_TYPE,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
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
        denied = DesignConformanceRequestStore._check_lease_locked(
            record, worker_id=principal.principal_id, now=now
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return DiffRasterVerificationResponse(verdict=verdict.value, detail=detail)
        object_key = build_design_conformance_raster_object_key(
            site_id=record.site_id, design_conformance_id=record.design_conformance_id
        )
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
                detail=(
                    "올렸다는 자리의 객체를 읽지 못했다 — 확인 없이 리포트를 받지 않는다"
                ),
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


def _artifact_object_key(record: DesignConformanceRequestRecord) -> str:
    """현재 DSM 산출물이 놓인 자리 — ``processing_jobs`` 의 유도 함수를 그대로 쓴다."""
    return build_processing_artifact_object_key(
        site_id=record.site_id,
        job_id=record.current.job_id,
        artifact_id=record.current.artifact_id,
    )


def mount_design_conformance_requests(
    app: FastAPI, store: DesignConformanceRequestStore, storage: EvidenceStorage
) -> None:
    app.include_router(build_design_conformance_requests_router(store, storage))


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
