"""설계 기준면 자산 원장 — 등록(선언) → 봉인(주장) → 관측 대조(사실).

## 이 모듈이 지키는 한 문장

**"검증됐다"는 말은 신뢰 경로가 그 파일의 바이트를 읽어 잰 값이 업로더의 선언과
전부 맞았다는 뜻이다** — 그 밖의 어떤 사건도 그 말을 만들어내지 못한다.

``source_media.py`` 의 register → seal → verify 3단을 그대로 본뜬다. 다른 점은
대상이 배치가 아니라 **파일 하나**라는 것뿐이라, 배치 판정(``COVERAGE_INCOMPLETE``
같은 "집합이 같은가")이 없고 항목 단위 결과 리스트도 없다.

- :meth:`DesignSurfaceStore.register` — 선언만 원장에 넣고 presigned PUT 을 낸다.
- :meth:`DesignSurfaceStore.seal` — **스토리지를 한 바이트도 읽지 않는다.**
  "업로드를 마쳤다"는 클라이언트의 주장을 기록할 뿐이다(아래 §봉인).
- :meth:`DesignSurfaceStore.record_observation` — **여기가 실제 신뢰 경계다.**
  워커가 잰 값을 받아 Core 가 :func:`evaluate_observation` 으로 판정한다.

## 봉인(SEALED)은 검증된 사실이 아니다

``seal()`` 이 증명하는 것은 "더 이상 내용을 바꾸지 않기로 했다"는 **원장 쪽
사실**뿐이다. 파일이 스토리지에 실제로 있는지, 그 내용이 선언과 같은지는 이
시점에 아무도 확인하지 않았다 — Core 는 객체 바이트를 중계하지 않는다
(ADR-KSI-010 §1). 그래서 이 상태의 설계면은 비교 입력 자격이 없고
(``DesignSurface.is_usable_for_conformance``), 검증 대기 큐에 들어갈 뿐이다.

## 판정은 Core 가 한다 — 워커는 잰 값만 보낸다

워커가 보내는 것은 측정치뿐이고(:class:`DesignSurfaceObservationRequest` 에
판정 필드가 없다), 대조는 :func:`evaluate_observation` 이 한다. 재생 경로도
**같은 함수**를 다시 태운다 — journal 의 ``verdict`` 를 손으로 VERIFIED 로
고쳐도 측정값이 선언과 어긋나면 기동이 거부된다(``source_media._replay_
verification`` 과 같은 원칙).

워커에게 선언값(sha256·CRS)을 주지 않는 것도 그 모듈과 같다 — 검증 대기 목록
(``GET /v1/design-surfaces``)은 **다운로드 URL 만** 준다. 게으른 워커가 신고값을
되읊어 통과하는 경로를 구조적으로 없앤다.

## 열리지 않는 파일은 별도 경로다

``UNREADABLE_RASTER`` 는 "관측이 선언과 다르다"가 아니라 **관측 자체가 없다**는
보고다. 그래서 :meth:`DesignSurfaceStore.report_verification_failure` 로 분리했고,
그 경로가 실을 수 있는 사유는 이 하나뿐이다 — 워커가 ``NO_FINITE_CELLS`` 같은
Core 의 판정을 자기 입으로 만들어낼 수 없어야 한다.

## 재검증하지 않는다 — VERIFIED/REJECTED 는 종단

설계면은 현장 재사용 자산이라 비교할 때마다 다시 재지 않는다(계약 모듈
docstring "VERIFIED 는 한 번만"). 거부된 설계면의 복구 경로는 되돌리기가 아니라
**새 revision 으로 다시 등록**이다.

## lease 를 두지 않은 이유

검증은 멱등이고(같은 파일을 두 번 재도 같은 값이 나온다) 경쟁해도 원장이
흔들리지 않는다 — 먼저 도착한 관측이 판정을 굳히고, 뒤늦은 관측은
``ALREADY_JUDGED`` 로 무기록 거절된다. 비교·재구성 작업과 달리 계산이 비싸지도
않아(파일 하나 해시) 이중 작업 낭비도 미미하다. 그래서 ``leasing.JobLease`` 를
끌어오지 않았다 — 쓸 이유가 생기기 전에 붙이면 만료·회수라는 두 번째 상태축이
공짜로 늘어난다.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.design_surface import (
    KSI_LANDXML_TIN_PARSER_VERSION,
    SHA256_HEX_PATTERN,
    DesignSurface,
    DesignSurfaceDeclared,
    DesignSurfaceObserved,
    DesignSurfaceSourceLineage,
    DesignSurfaceStatus,
    can_transition,
)
from ksi_event_contracts.vertical_reference import (
    UnrecognizedVerticalCrsError,
    family_of,
    vertical_datum_from_epsg,
)
from ksi_geo_spatial.crs import SUPPORTED_PROJECT_CRS, UnsupportedCrsError, normalise_crs
from ksi_geo_spatial.tin_surface import CANONICAL_TIN_NORMALIZATION_PROFILE
from pydantic import Field, ValidationError

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.sites.sites import SiteStore

logger = logging.getLogger("ksi_core.design_surfaces")

_NOT_FOUND_DETAIL = "해당 설계 기준면을 찾을 수 없다"

#: 설계면 GeoTIFF 의 저장 MIME. **서버가 정한다** — 업로더가 고르게 두면
#: ``image/svg+xml`` 처럼 브라우저가 해석하는 타입이 열람 URL 로 나갈 수 있다
#: (``evidence.ALLOWED_CONTENT_TYPES`` 주석). GeoTIFF 는 브라우저가 해석하지
#: 않는 바이너리이므로 그 allowlist 의 ``application/octet-stream`` 자리다.
DESIGN_SURFACE_CONTENT_TYPE = "application/octet-stream"

#: 검증 대기 목록 1회 조회 상한 — 워커가 한 번에 훑는 후보 수.
MAX_PENDING_LIMIT = 200


class DesignSurfaceRejectionReason(StrEnum):
    """설계면이 비교 입력이 되지 못하는 typed 사유 — 화면이 한국어로 번역한다.

    ``UNREADABLE_RASTER`` 만 성질이 다르다. 나머지 일곱은 **관측과 선언을 대조한
    Core 의 판정**이고, 이것 하나는 **워커가 관측에 실패했다는 보고**다
    (:meth:`DesignSurfaceStore.report_verification_failure`).
    """

    #: 읽은 바이트의 해시가 신고 해시와 다르다 — 다른 파일이 올라왔거나 손상됐다.
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    #: 파일이 들고 있는 좌표계가 선언한 좌표계와 다르다.
    CRS_DECLARATION_MISMATCH = "CRS_DECLARATION_MISMATCH"
    #: 선언·관측이 일치하더라도 그 좌표계를 이 제품이 지원하지 않는다
    #: (``SUPPORTED_PROJECT_CRS`` — 구 측지계 혼입 차단).
    UNSUPPORTED_CRS = "UNSUPPORTED_CRS"
    #: 평면 길이 단위가 meter 가 아니다 — 피트 도면이 미터로 취급되면 체적이
    #: 조용히 35배 틀린다.
    UNSUPPORTED_UNIT = "UNSUPPORTED_UNIT"
    #: DEM 이 아니다(밴드가 1이 아니다) — 정사영상을 올린 전형적 실수.
    UNSUPPORTED_BAND_COUNT = "UNSUPPORTED_BAND_COUNT"
    #: 유효 표고 셀이 하나도 없다 — 열리기는 하지만 비교할 높이가 없다.
    NO_FINITE_CELLS = "NO_FINITE_CELLS"
    #: 파일이 들고 있는 수직 CRS 가 선언한 수직기준과 모순되거나, 해석할 수 없다.
    #: **모르는 수직 CRS 를 조용히 넘기지 않는다** — 타원체고와 정표고가 섞이면
    #: 한국에서 20~30m 가 결과에 그대로 들어간다.
    VERTICAL_DECLARATION_CONTRADICTED = "VERTICAL_DECLARATION_CONTRADICTED"
    #: LandXML 원본·선택 Surface·정규화 결과의 결속이 빠졌거나 서로 맞지 않는다.
    SOURCE_LINEAGE_INVALID = "SOURCE_LINEAGE_INVALID"
    #: 제한된 LandXML TIN 정규화가 거부됐다. 원본 bytes 는 그대로 보존된다.
    LANDXML_NORMALIZATION_FAILED = "LANDXML_NORMALIZATION_FAILED"
    #: 워커가 파일을 열지 못했다 — 관측 자체가 없다(Core 의 대조 판정이 아니다).
    UNREADABLE_RASTER = "UNREADABLE_RASTER"


class DesignSurfaceRegisterVerdict(StrEnum):
    REGISTERED = "REGISTERED"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    #: 같은 (name, revision) 이 **다른 선언**으로 이미 등록돼 있다. 같은 선언의
    #: 재전송은 이 값이 아니라 ``REGISTERED``(멱등 재발급)다.
    DECLARATION_CONFLICT = "DECLARATION_CONFLICT"
    INVALID_SITE_ID = "INVALID_SITE_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class DesignSurfaceSealVerdict(StrEnum):
    SEALED = "SEALED"
    ALREADY_SEALED = "ALREADY_SEALED"
    UNKNOWN_DESIGN_SURFACE = "UNKNOWN_DESIGN_SURFACE"
    #: 이미 판정이 끝난(VERIFIED·REJECTED) 설계면 — 봉인으로 되돌릴 수 없다.
    ALREADY_JUDGED = "ALREADY_JUDGED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class DesignSurfaceObservationVerdict(StrEnum):
    """관측 보고의 처리 결과 — ``VERIFIED``/``REJECTED`` 는 Core 의 판정이다."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNKNOWN_DESIGN_SURFACE = "UNKNOWN_DESIGN_SURFACE"
    #: 봉인 전에는 대조 대상 내용이 확정되지 않았다 — 관측을 받지 않는다.
    NOT_SEALED = "NOT_SEALED"
    #: 이미 VERIFIED·REJECTED 로 굳었다. 재보고는 무기록 거절(멱등).
    ALREADY_JUDGED = "ALREADY_JUDGED"
    #: 측정치 자체가 성립하지 않는다(예: 유효셀 수 > 전체 셀 수) — 계약이 막는다.
    INVALID_MEASUREMENT = "INVALID_MEASUREMENT"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_REGISTER_STATUS: dict[DesignSurfaceRegisterVerdict, int] = {
    DesignSurfaceRegisterVerdict.REGISTERED: 201,
    DesignSurfaceRegisterVerdict.UNKNOWN_SITE: 404,
    DesignSurfaceRegisterVerdict.DECLARATION_CONFLICT: 409,
    DesignSurfaceRegisterVerdict.INVALID_SITE_ID: 422,
    DesignSurfaceRegisterVerdict.STORE_UNAVAILABLE: 503,
}

_SEAL_STATUS: dict[DesignSurfaceSealVerdict, int] = {
    DesignSurfaceSealVerdict.SEALED: 201,
    DesignSurfaceSealVerdict.ALREADY_SEALED: 200,
    DesignSurfaceSealVerdict.UNKNOWN_DESIGN_SURFACE: 404,
    DesignSurfaceSealVerdict.ALREADY_JUDGED: 409,
    DesignSurfaceSealVerdict.STORE_UNAVAILABLE: 503,
}

_OBSERVATION_STATUS: dict[DesignSurfaceObservationVerdict, int] = {
    DesignSurfaceObservationVerdict.VERIFIED: 201,
    # 422 다 — 요청 형식은 옳고 **내용이 사실과 다르다**(``source_media`` 의
    # MISMATCH 와 같은 자리). 재시도로 해결되지 않는다는 뜻을 담는다.
    DesignSurfaceObservationVerdict.REJECTED: 422,
    DesignSurfaceObservationVerdict.UNKNOWN_DESIGN_SURFACE: 404,
    DesignSurfaceObservationVerdict.NOT_SEALED: 409,
    DesignSurfaceObservationVerdict.ALREADY_JUDGED: 200,
    DesignSurfaceObservationVerdict.INVALID_MEASUREMENT: 422,
    DesignSurfaceObservationVerdict.STORE_UNAVAILABLE: 503,
}


class DesignSurfaceRecoveryError(RuntimeError):
    """design-surface journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


def build_design_surface_object_key(*, site_id: str, design_surface_id: str) -> str:
    """객체 키를 **서버가** 만든다(``source_media.build_source_media_object_key`` 대칭).

    두 구성요소를 전부 재검증한다 — 호출부가 이미 검증했더라도 이 함수가 경로
    탈출을 막는 마지막 지점이기 때문이다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(design_surface_id):
        raise ValueError(f"경로-안전하지 않은 designSurfaceId: {design_surface_id!r}")
    return f"sites/{site_id}/design-surfaces/{design_surface_id}"


def build_design_surface_canonical_object_key(*, site_id: str, design_surface_id: str) -> str:
    """Immutable derived GeoTIFF location for a LandXML source.

    ``build_design_surface_object_key`` remains the original upload location;
    suffixing a separate key prevents a normalizer from overwriting evidence.
    """
    raw_key = build_design_surface_object_key(
        site_id=site_id, design_surface_id=design_surface_id
    )
    return f"{raw_key}/canonical.tif"


def object_key_for_surface(surface: DesignSurface) -> str:
    """Return the verified bytes consumers must read for this source type."""
    if surface.format == "landxml":
        return build_design_surface_canonical_object_key(
            site_id=surface.site_id, design_surface_id=surface.design_surface_id
        )
    return build_design_surface_object_key(
        site_id=surface.site_id, design_surface_id=surface.design_surface_id
    )


def build_design_surface_id(site_id: str, sequence: int) -> str:
    """``{siteId}-ds{n}`` — ``comparison_requests.build_request_id`` 와 동형.

    결정적이고 사람이 읽을 수 있으며, siteId 가 경로-안전하면 이 값도 경로-안전하다.
    """
    return f"{site_id}-ds{sequence}"


def evaluate_observation(
    declared: DesignSurfaceDeclared,
    observed: DesignSurfaceObserved,
    *,
    source_format: str = "geotiff",
    surface_selector: str | None = None,
    source_lineage: DesignSurfaceSourceLineage | None = None,
) -> DesignSurfaceRejectionReason | None:
    """선언과 관측을 대조한다 — **판정의 SSOT**. 통과면 ``None``.

    live 경로(:meth:`DesignSurfaceStore.record_observation`)와 재생 경로가 같은
    함수를 쓴다. 각자 조건문을 갖고 있으면 한쪽만 고쳐지는 순간 journal 이 거짓
    검증을 되살리는 경로가 열린다(``source_media.compare_measurements`` 와 같은
    원칙).

    **순서에 뜻이 있다.** 해시가 앵커다 — 다른 파일이 올라온 것이라면 CRS·밴드
    수가 어긋나는 것은 결과이지 원인이 아니고, 사용자에게 "다른 파일을 올렸다"고
    말해주는 편이 정확하다. 그 다음이 선언만으로 판정되는 단위, 이어서 파일
    자체의 성질(밴드·유효셀), 마지막이 좌표계·수직기준이다.

    ``UNREADABLE_RASTER`` 는 이 함수가 절대 반환하지 않는다 — 그건 대조 결과가
    아니라 "관측 자체가 없다"는 워커의 보고이고, 별도 경로로 들어온다
    (:meth:`DesignSurfaceStore.report_verification_failure`).
    """
    if source_format == "geotiff":
        if observed.sha256 != declared.sha256:
            return DesignSurfaceRejectionReason.DIGEST_MISMATCH
    elif source_format == "landxml":
        if (
            source_lineage is None
            or source_lineage.source_sha256 != declared.sha256
            or source_lineage.surface_selector != surface_selector
            or source_lineage.parser_version != KSI_LANDXML_TIN_PARSER_VERSION
            or source_lineage.normalization_profile
            != CANONICAL_TIN_NORMALIZATION_PROFILE
            or source_lineage.canonical_sha256 != observed.sha256
        ):
            return DesignSurfaceRejectionReason.SOURCE_LINEAGE_INVALID
    else:
        return DesignSurfaceRejectionReason.SOURCE_LINEAGE_INVALID
    if declared.length_unit != "meter":
        return DesignSurfaceRejectionReason.UNSUPPORTED_UNIT
    if observed.band_count != 1:
        return DesignSurfaceRejectionReason.UNSUPPORTED_BAND_COUNT
    if observed.finite_cell_count == 0:
        return DesignSurfaceRejectionReason.NO_FINITE_CELLS

    # CRS 대조는 정규화가 필요하다(``epsg:5186`` 과 ``EPSG:5186`` 은 같은
    # 좌표계다). 정규화·화이트리스트는 계산 엔진(``align_and_diff``)이 쓰는 것과
    # **같은 함수**를 쓴다 — Core 가 자기 규칙을 따로 가지면 "Core 는 받았는데
    # 엔진이 거부하는" 설계면이 생긴다.
    try:
        declared_crs = normalise_crs(declared.crs)
    except UnsupportedCrsError:
        # 선언 자체가 EPSG 권위 코드로 환원되지 않는다 — 대조할 기준이 없다.
        return DesignSurfaceRejectionReason.UNSUPPORTED_CRS
    try:
        observed_crs = normalise_crs(observed.crs)
    except UnsupportedCrsError:
        return DesignSurfaceRejectionReason.UNSUPPORTED_CRS
    if declared_crs != observed_crs:
        return DesignSurfaceRejectionReason.CRS_DECLARATION_MISMATCH
    if observed_crs not in SUPPORTED_PROJECT_CRS:
        return DesignSurfaceRejectionReason.UNSUPPORTED_CRS

    if observed.vertical_crs_epsg is not None:
        # 파일이 수직 CRS 를 들고 있다면 그것이 선언을 반박하는지 본다. **모르는
        # 코드는 넘기지 않는다** — ``vertical_datum_from_epsg`` 가 거부하면 그
        # 파일은 "선언이 맞는 파일"이 아니라 "선언을 확인할 수 없는 파일"이다.
        try:
            observed_datum = vertical_datum_from_epsg(observed.vertical_crs_epsg)
        except UnrecognizedVerticalCrsError:
            return DesignSurfaceRejectionReason.VERTICAL_DECLARATION_CONTRADICTED
        if family_of(observed_datum) is not family_of(declared.vertical_reference.datum):
            return DesignSurfaceRejectionReason.VERTICAL_DECLARATION_CONTRADICTED
    return None


class RegistrationResult(CamelModel):
    """등록 결과 — 응답 모델이 아니라 store 반환값이다(라우터가 URL 을 얹는다)."""

    model_config = CamelModel.model_config | {"arbitrary_types_allowed": True}

    verdict: DesignSurfaceRegisterVerdict
    detail: str | None = None
    surface: DesignSurface | None = None
    object_key: str | None = None
    canonical_object_key: str | None = None


class SealResult(CamelModel):
    verdict: DesignSurfaceSealVerdict
    detail: str | None = None
    surface: DesignSurface | None = None


class ObservationResult(CamelModel):
    verdict: DesignSurfaceObservationVerdict
    detail: str | None = None
    surface: DesignSurface | None = None
    rejection_reason: DesignSurfaceRejectionReason | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _require_aware_iso(raw: Any, field_name: str, design_surface_id: str) -> datetime:
    """journal 의 ISO 시각을 tz-aware datetime 으로 — naive·비문자열은 기동 거부."""
    if not isinstance(raw, str):
        raise DesignSurfaceRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — "
            f"designSurfaceId={design_surface_id}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DesignSurfaceRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — "
            f"designSurfaceId={design_surface_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise DesignSurfaceRecoveryError(
            f"재생: {field_name} 가 naive datetime — designSurfaceId={design_surface_id}"
        )
    return parsed


def _advanced(surface: DesignSurface, **changes: Any) -> DesignSurface:
    """전이된 새 레코드를 **계약 검증을 다시 태워** 만든다.

    ``model_copy(update=...)`` 를 쓰지 않는 것이 요점이다 — 그 메서드는 validator
    를 건너뛰므로 "VERIFIED 인데 observed 가 없다" 같은 조합이 조용히 만들어진다.
    여기서는 매번 ``model_validate`` 로 다시 지나가므로, 상태와 근거가 어긋나는
    레코드는 live 든 재생이든 **만들어지는 순간** 실패한다.
    """
    return DesignSurface.model_validate({**surface.model_dump(), **changes})


class DesignSurfaceStore:
    """``DurableJournal`` 위의 설계 기준면 저장소(``source_media.SourceMediaStore`` 대칭).

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 판정+append+projection 을
    한 임계구역으로 묶는다(다른 저장소 관습 대칭).
    """

    def __init__(self, journal: DurableJournal, *, site_store: SiteStore) -> None:
        self._journal = journal
        self._site_store = site_store
        self._lock = threading.Lock()
        self._surfaces: dict[str, DesignSurface] = {}
        try:
            self._replay(journal)
        except DesignSurfaceRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise DesignSurfaceRecoveryError(
                f"design-surface journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    # ── 재생 ────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw["kind"]
            design_surface_id = raw["designSurfaceId"]
            if kind == "design-surface-registered":
                self._replay_registration(design_surface_id, raw)
            elif kind == "design-surface-sealed":
                self._replay_seal(design_surface_id, raw)
            elif kind == "design-surface-observed":
                self._replay_observation(design_surface_id, raw)
            elif kind == "design-surface-verification-failed":
                self._replay_verification_failure(design_surface_id, raw)
            elif kind == "design-surface-normalization-failed":
                self._replay_normalization_failure(design_surface_id, raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise DesignSurfaceRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_registration(self, design_surface_id: str, raw: dict[str, Any]) -> None:
        if design_surface_id in self._surfaces:
            # live 는 같은 선언 재전송을 journal 에 다시 쓰지 않는다(무기록 멱등
            # 재발급) — 그러니 같은 id 가 두 번 나오면 진짜 중복이다.
            raise DesignSurfaceRecoveryError(
                f"재생: designSurfaceId 중복 등록 — designSurfaceId={design_surface_id}"
            )
        if not is_path_safe_identifier(design_surface_id):
            raise DesignSurfaceRecoveryError(
                f"재생: designSurfaceId 가 경로-안전하지 않다({design_surface_id!r})"
            )
        try:
            declared = DesignSurfaceDeclared.model_validate(raw["declared"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise DesignSurfaceRecoveryError(
                f"재생: 선언 블록이 계약을 만족하지 않는다 — "
                f"designSurfaceId={design_surface_id}: {exc}"
            ) from exc
        self._surfaces[design_surface_id] = DesignSurface(
            design_surface_id=design_surface_id,
            site_id=raw["siteId"],
            name=raw["name"],
            revision=raw["revision"],
            format=raw.get("sourceFormat", "geotiff"),
            surface_selector=raw.get("surfaceSelector"),
            declared=declared,
            status=DesignSurfaceStatus.REGISTERED,
            registered_at=_require_aware_iso(raw["ts"], "ts", design_surface_id),
            registered_by=raw["registeredBy"],
        )

    def _replay_seal(self, design_surface_id: str, raw: dict[str, Any]) -> None:
        surface = self._require_replayed(design_surface_id)
        self._require_transition(surface, DesignSurfaceStatus.SEALED)
        self._surfaces[design_surface_id] = _advanced(
            surface,
            status=DesignSurfaceStatus.SEALED,
            sealed_at=_require_aware_iso(raw["ts"], "ts", design_surface_id),
        )

    def _replay_observation(self, design_surface_id: str, raw: dict[str, Any]) -> None:
        """관측 레코드 재생 — **기록된 판정을 믿지 않고 다시 대조한다.**

        journal 에 남는 사실은 워커의 측정값이고, 통과 여부는 재생 시점에
        :func:`evaluate_observation` 이 다시 매긴다. 그래서 ``verdict`` 를
        VERIFIED 로 손으로 고쳐 넣어도 측정값이 선언과 어긋나면 기동이 거부된다.
        """
        surface = self._require_replayed(design_surface_id)
        try:
            observed = DesignSurfaceObserved.model_validate(raw["observed"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise DesignSurfaceRecoveryError(
                f"재생: 관측 블록이 계약을 만족하지 않는다 — "
                f"designSurfaceId={design_surface_id}: {exc}"
            ) from exc
        try:
            source_lineage = (
                DesignSurfaceSourceLineage.model_validate(raw["sourceLineage"])
                if raw.get("sourceLineage") is not None
                else None
            )
        except ValidationError as exc:
            raise DesignSurfaceRecoveryError(
                "재생: sourceLineage 가 계약을 만족하지 않는다 — "
                f"designSurfaceId={design_surface_id}: {exc}"
            ) from exc
        reason = evaluate_observation(
            surface.declared,
            observed,
            source_format=surface.format,
            surface_selector=surface.surface_selector,
            source_lineage=source_lineage,
        )
        recomputed = (
            DesignSurfaceStatus.VERIFIED if reason is None else DesignSurfaceStatus.REJECTED
        )
        recorded = raw["status"]
        if recorded != recomputed.value:
            raise DesignSurfaceRecoveryError(
                f"재생: 관측 레코드의 판정이 재대조와 불일치 — "
                f"designSurfaceId={design_surface_id} "
                f"(기록={recorded!r}, 재대조={recomputed.value!r})"
            )
        recorded_reason = raw.get("rejectionReason")
        if recorded_reason != (reason.value if reason is not None else None):
            raise DesignSurfaceRecoveryError(
                f"재생: 관측 레코드의 거부 사유가 재대조와 불일치 — "
                f"designSurfaceId={design_surface_id} (기록={recorded_reason!r})"
            )
        self._require_transition(surface, recomputed)
        self._surfaces[design_surface_id] = self._judged(
            surface,
            observed=observed,
            reason=reason,
            at=_require_aware_iso(raw["ts"], "ts", design_surface_id),
            source_lineage=source_lineage,
        )

    def _replay_verification_failure(self, design_surface_id: str, raw: dict[str, Any]) -> None:
        surface = self._require_replayed(design_surface_id)
        self._require_transition(surface, DesignSurfaceStatus.REJECTED)
        if raw["reason"] != DesignSurfaceRejectionReason.UNREADABLE_RASTER.value:
            # 이 경로가 실을 수 있는 사유는 하나뿐이다(모듈 docstring) — 다른
            # 값이 들어 있으면 워커가 Core 의 판정을 자기 입으로 만든 레코드다.
            raise DesignSurfaceRecoveryError(
                f"재생: 검증실패 레코드의 사유가 UNREADABLE_RASTER 가 아니다"
                f"({raw['reason']!r}) — designSurfaceId={design_surface_id}"
            )
        self._surfaces[design_surface_id] = self._judged(
            surface,
            observed=None,
            reason=DesignSurfaceRejectionReason.UNREADABLE_RASTER,
            at=_require_aware_iso(raw["ts"], "ts", design_surface_id),
        )

    def _replay_normalization_failure(self, design_surface_id: str, raw: dict[str, Any]) -> None:
        surface = self._require_replayed(design_surface_id)
        self._require_transition(surface, DesignSurfaceStatus.REJECTED)
        if (
            surface.format != "landxml"
            or raw.get("reason")
            != DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED.value
        ):
            raise DesignSurfaceRecoveryError(
                "재생: LandXML 정규화 실패 레코드가 아닌데 기록됐다 — "
                f"designSurfaceId={design_surface_id}"
            )
        self._surfaces[design_surface_id] = self._judged(
            surface,
            observed=None,
            reason=DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED,
            at=_require_aware_iso(raw["ts"], "ts", design_surface_id),
        )

    def _require_replayed(self, design_surface_id: str) -> DesignSurface:
        surface = self._surfaces.get(design_surface_id)
        if surface is None:
            raise DesignSurfaceRecoveryError(
                f"재생: 등록된 적 없는 설계면의 레코드 — designSurfaceId={design_surface_id}"
            )
        return surface

    def _require_transition(self, surface: DesignSurface, target: DesignSurfaceStatus) -> None:
        """재생도 live 와 **같은 전이표**를 태운다(``change_detection`` 재생 원칙).

        전이표는 계약이 소유한다(``design_surface.DESIGN_SURFACE_TRANSITIONS``) —
        store 가 자기 사본을 들면 둘이 갈라진다.
        """
        if not can_transition(surface.status, target):
            raise DesignSurfaceRecoveryError(
                f"재생: 허용되지 않은 전이 {surface.status.value}→{target.value} — "
                f"designSurfaceId={surface.design_surface_id}"
            )

    @staticmethod
    def _judged(
        surface: DesignSurface,
        *,
        observed: DesignSurfaceObserved | None,
        reason: DesignSurfaceRejectionReason | None,
        at: datetime,
        source_lineage: DesignSurfaceSourceLineage | None = None,
    ) -> DesignSurface:
        """판정 결과를 얹은 새 레코드 — live 와 재생이 같은 조립을 쓴다."""
        if reason is None:
            return _advanced(
                surface,
                status=DesignSurfaceStatus.VERIFIED,
                observed=observed,
                verified_at=at,
                source_lineage=source_lineage,
            )
        return _advanced(
            surface,
            status=DesignSurfaceStatus.REJECTED,
            observed=observed,
            rejection_reason=reason.value,
            source_lineage=source_lineage,
        )

    # ── live 경로 ───────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def site_is_visible(self, site_id: str) -> bool:
        """현재 요청이 이 설계면의 부모 현장을 볼 수 있는지 판정한다.

        설계면은 별도 organizationId를 복제하지 않고 Site 원장을 권위로 삼는다.
        ``SiteStore.get``은 인증된 요청 문맥에서 cross-organization site를 ``None``
        으로 접으므로, 이 한 관문을 list·get·worker pull·mutation 모두가 재사용한다
        (INV-060). 배치·재생에는 문맥이 없어 기존 trusted 동작을 유지한다.
        """

        return self._site_store.get(site_id) is not None

    def register(
        self,
        site_id: str,
        name: str,
        revision: str,
        declared: DesignSurfaceDeclared,
        *,
        source_format: str = "geotiff",
        surface_selector: str | None = None,
        registered_by: str,
        now: datetime,
    ) -> RegistrationResult:
        """선언을 원장에 넣는다 — **이 시점에는 아무것도 검증하지 않는다.**

        같은 현장의 같은 ``(name, revision)`` 재전송은 판단이 갈린다:
        선언이 같으면 멱등 재발급(journal 무기록, 새 presigned PUT 은 라우터가
        낸다), 선언이 다르면 ``DECLARATION_CONFLICT`` 다 — 같은 도면 개정 표기가
        두 개의 서로 다른 내용을 가리키면 리포트가 "어느 판 기준인가"에 답할 수
        없다(``source_media`` 의 ``CLAIM_CONFLICT`` 와 같은 자리).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            if self._site_store.get(site_id) is None:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.UNKNOWN_SITE,
                    detail="등록된 적 없는 현장이다",
                )
            if source_format not in {"geotiff", "landxml"}:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.INVALID_SITE_ID,
                    detail=f"unsupported sourceFormat: {source_format!r}",
                )
            if source_format == "landxml" and not (surface_selector or "").strip():
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.INVALID_SITE_ID,
                    detail="LandXML requires surfaceSelector",
                )
            if source_format == "geotiff" and surface_selector is not None:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.INVALID_SITE_ID,
                    detail="GeoTIFF must not include surfaceSelector",
                )
            existing = next(
                (
                    s
                    for s in self._surfaces.values()
                    if s.site_id == site_id and s.name == name and s.revision == revision
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.declared == declared
                    and existing.format == source_format
                    and existing.surface_selector == surface_selector
                ):
                    raw_key = build_design_surface_object_key(
                        site_id=site_id, design_surface_id=existing.design_surface_id
                    )
                    return RegistrationResult(
                        verdict=DesignSurfaceRegisterVerdict.REGISTERED,
                        surface=existing,
                        object_key=raw_key,
                        canonical_object_key=(
                            build_design_surface_canonical_object_key(
                                site_id=site_id, design_surface_id=existing.design_surface_id
                            )
                            if source_format == "landxml"
                            else None
                        ),
                    )
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.DECLARATION_CONFLICT,
                    detail=(
                        "같은 이름·개정의 설계면이 다른 선언으로 이미 등록돼 있다 — "
                        "내용이 바뀌었으면 새 revision 으로 등록한다"
                    ),
                    surface=existing,
                )

            sequence = sum(1 for s in self._surfaces.values() if s.site_id == site_id) + 1
            design_surface_id = build_design_surface_id(site_id, sequence)
            try:
                object_key = build_design_surface_object_key(
                    site_id=site_id, design_surface_id=design_surface_id
                )
            except ValueError as exc:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.INVALID_SITE_ID, detail=str(exc)
                )

            record = {
                "kind": "design-surface-registered",
                "ts": iso_utc(now),
                "designSurfaceId": design_surface_id,
                "siteId": site_id,
                "name": name,
                "revision": revision,
                "objectKey": object_key,
                "sourceFormat": source_format,
                "surfaceSelector": surface_selector,
                "declared": declared.model_dump(by_alias=True, mode="json"),
                "registeredBy": registered_by,
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return RegistrationResult(
                    verdict=DesignSurfaceRegisterVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            surface = DesignSurface(
                design_surface_id=design_surface_id,
                site_id=site_id,
                name=name,
                revision=revision,
                format=cast(Literal["geotiff", "landxml"], source_format),
                surface_selector=surface_selector,
                declared=declared,
                status=DesignSurfaceStatus.REGISTERED,
                registered_at=now,
                registered_by=registered_by,
            )
            self._surfaces[design_surface_id] = surface
            return RegistrationResult(
                verdict=DesignSurfaceRegisterVerdict.REGISTERED,
                surface=surface,
                object_key=object_key,
                canonical_object_key=(
                    build_design_surface_canonical_object_key(
                        site_id=site_id, design_surface_id=design_surface_id
                    )
                    if source_format == "landxml"
                    else None
                ),
            )

    def seal(
        self, design_surface_id: str, *, sealed_by: str, now: datetime
    ) -> SealResult:
        """"업로드를 마쳤다"는 **클라이언트의 주장**을 기록한다.

        이 메서드는 **스토리지를 읽지 않는다.** 파일이 실제로 올라왔는지, 그
        내용이 선언과 같은지는 여기서 확인되지 않으며 확인할 수단도 없다(Core 는
        객체 바이트를 중계하지 않는다, ADR-KSI-010 §1). 그래서 이 상태는 **검증된
        사실이 아니라 검증 대기 큐 진입**이다 — 비교 입력 자격은 여전히 없다.

        재호출은 에러가 아니라 ``ALREADY_SEALED`` 다(journal 무기록) — 재시도가
        안전해야 한다(``source_media.seal`` 관습).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SealResult(
                    verdict=DesignSurfaceSealVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            surface = self._surfaces.get(design_surface_id)
            if surface is None or not self.site_is_visible(surface.site_id):
                return SealResult(
                    verdict=DesignSurfaceSealVerdict.UNKNOWN_DESIGN_SURFACE,
                    detail=_NOT_FOUND_DETAIL,
                )
            if surface.status is DesignSurfaceStatus.SEALED:
                return SealResult(
                    verdict=DesignSurfaceSealVerdict.ALREADY_SEALED, surface=surface
                )
            if not can_transition(surface.status, DesignSurfaceStatus.SEALED):
                return SealResult(
                    verdict=DesignSurfaceSealVerdict.ALREADY_JUDGED,
                    detail=(
                        f"이미 판정이 끝난 설계면이다(status={surface.status.value}) — "
                        "내용을 바꾸려면 새 revision 으로 등록한다"
                    ),
                    surface=surface,
                )
            record = {
                "kind": "design-surface-sealed",
                "ts": iso_utc(now),
                "designSurfaceId": design_surface_id,
                "sealedBy": sealed_by,
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return SealResult(
                    verdict=DesignSurfaceSealVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            sealed = _advanced(surface, status=DesignSurfaceStatus.SEALED, sealed_at=now)
            self._surfaces[design_surface_id] = sealed
            return SealResult(verdict=DesignSurfaceSealVerdict.SEALED, surface=sealed)

    def record_observation(
        self,
        design_surface_id: str,
        observed: DesignSurfaceObserved,
        *,
        source_lineage: DesignSurfaceSourceLineage | None = None,
        now: datetime,
    ) -> ObservationResult:
        """워커의 실측을 선언과 대조한다 — **여기가 실제 신뢰 경계다.**

        ``SEALED`` 에서만 받는다. 봉인 전에는 대조 대상 내용이 확정되지 않았고
        (``REGISTERED`` 상태의 관측은 "무엇과 대조했는지"를 말할 수 없다), 판정이
        끝난 뒤에는 재판정하지 않는다(``ALREADY_JUDGED``, journal 무기록).

        ``observed`` 안의 ``measuredBy``/``measuredAt`` 은 **Core 가 채운 값**이다
        (라우터가 principal 과 서버 시계로 채운다) — 워커가 자기 신원이나 측정
        시각을 주장하게 두지 않는다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            surface = self._surfaces.get(design_surface_id)
            if surface is None or not self.site_is_visible(surface.site_id):
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.UNKNOWN_DESIGN_SURFACE,
                    detail=_NOT_FOUND_DETAIL,
                )
            if surface.status is DesignSurfaceStatus.REGISTERED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.NOT_SEALED,
                    detail=(
                        "아직 봉인되지 않은 설계면이다 — 봉인 전에는 대조 대상 내용이 "
                        "확정되지 않아 '선언과 일치한다'가 성립하지 않는다"
                    ),
                    surface=surface,
                )
            if surface.status is not DesignSurfaceStatus.SEALED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.ALREADY_JUDGED,
                    surface=surface,
                    rejection_reason=_reason_of(surface),
                )

            reason = evaluate_observation(
                surface.declared,
                observed,
                source_format=surface.format,
                surface_selector=surface.surface_selector,
                source_lineage=source_lineage,
            )
            status = (
                DesignSurfaceStatus.VERIFIED if reason is None else DesignSurfaceStatus.REJECTED
            )
            record = {
                "kind": "design-surface-observed",
                "ts": iso_utc(now),
                "designSurfaceId": design_surface_id,
                # 판정이 아니라 **측정값**이 원장의 사실이다 — 재생이 이걸로 다시
                # 대조하므로, status 만 고쳐 넣은 원장은 기동에서 걸린다.
                "observed": observed.model_dump(by_alias=True, mode="json"),
                "sourceLineage": (
                    source_lineage.model_dump(by_alias=True, mode="json")
                    if source_lineage is not None
                    else None
                ),
                "status": status.value,
                "rejectionReason": reason.value if reason is not None else None,
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            judged = self._judged(
                surface,
                observed=observed,
                reason=reason,
                at=now,
                source_lineage=source_lineage,
            )
            self._surfaces[design_surface_id] = judged
            return ObservationResult(
                verdict=(
                    DesignSurfaceObservationVerdict.VERIFIED
                    if reason is None
                    else DesignSurfaceObservationVerdict.REJECTED
                ),
                surface=judged,
                rejection_reason=reason,
                detail=None if reason is None else _REJECTION_DETAIL[reason],
            )

    def report_verification_failure(
        self, design_surface_id: str, *, detail: str | None, reported_by: str, now: datetime
    ) -> ObservationResult:
        """워커가 **파일을 열지 못했다**는 보고 — 관측이 아니라 관측의 부재다.

        이 경로가 실을 수 있는 사유는 ``UNREADABLE_RASTER`` 하나뿐이다. 워커가
        사유를 고를 수 있으면 ``NO_FINITE_CELLS`` 같은 Core 의 판정을 자기 입으로
        만들어낼 수 있고, 그러면 "누가 무엇을 확인했는가"가 무너진다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            surface = self._surfaces.get(design_surface_id)
            if surface is None or not self.site_is_visible(surface.site_id):
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.UNKNOWN_DESIGN_SURFACE,
                    detail=_NOT_FOUND_DETAIL,
                )
            if surface.status is DesignSurfaceStatus.REGISTERED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.NOT_SEALED,
                    detail="아직 봉인되지 않은 설계면이다 — 검증 대상이 아니다",
                    surface=surface,
                )
            if surface.status is not DesignSurfaceStatus.SEALED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.ALREADY_JUDGED,
                    surface=surface,
                    rejection_reason=_reason_of(surface),
                )
            record = {
                "kind": "design-surface-verification-failed",
                "ts": iso_utc(now),
                "designSurfaceId": design_surface_id,
                "reason": DesignSurfaceRejectionReason.UNREADABLE_RASTER.value,
                "detail": detail,
                "reportedBy": reported_by,
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            judged = self._judged(
                surface,
                observed=None,
                reason=DesignSurfaceRejectionReason.UNREADABLE_RASTER,
                at=now,
            )
            self._surfaces[design_surface_id] = judged
            return ObservationResult(
                verdict=DesignSurfaceObservationVerdict.REJECTED,
                surface=judged,
                rejection_reason=DesignSurfaceRejectionReason.UNREADABLE_RASTER,
                detail=detail
                or _REJECTION_DETAIL[DesignSurfaceRejectionReason.UNREADABLE_RASTER],
            )

    def report_normalization_failure(
        self, design_surface_id: str, *, detail: str | None, reported_by: str, now: datetime
    ) -> ObservationResult:
        """Record a trusted worker's LandXML parse/normalisation rejection."""
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            surface = self._surfaces.get(design_surface_id)
            if surface is None or not self.site_is_visible(surface.site_id):
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.UNKNOWN_DESIGN_SURFACE,
                    detail=_NOT_FOUND_DETAIL,
                )
            if surface.status is DesignSurfaceStatus.REGISTERED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.NOT_SEALED,
                    detail="아직 봉인되지 않은 설계면이다",
                    surface=surface,
                )
            if surface.status is not DesignSurfaceStatus.SEALED:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.ALREADY_JUDGED,
                    surface=surface,
                    rejection_reason=_reason_of(surface),
                )
            if surface.format != "landxml":
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.INVALID_MEASUREMENT,
                    detail="LandXML 정규화 실패 보고는 LandXML source 에만 허용된다",
                )
            record = {
                "kind": "design-surface-normalization-failed",
                "ts": iso_utc(now),
                "designSurfaceId": design_surface_id,
                "reason": DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED.value,
                "detail": detail,
                "reportedBy": reported_by,
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return ObservationResult(
                    verdict=DesignSurfaceObservationVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            judged = self._judged(
                surface,
                observed=None,
                reason=DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED,
                at=now,
            )
            self._surfaces[design_surface_id] = judged
            return ObservationResult(
                verdict=DesignSurfaceObservationVerdict.REJECTED,
                detail=(
                    detail
                    or _REJECTION_DETAIL[
                        DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED
                    ]
                ),
                rejection_reason=DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED,
                surface=judged,
            )

    def list_pending_verification(self, *, limit: int = 50) -> list[DesignSurface]:
        """검증 대기(``SEALED``) 목록 — 봉인 순서(FIFO)로 준다.

        lease 가 없다(모듈 docstring §lease) — 둘 이상의 워커가 같은 파일을 재도
        먼저 도착한 관측이 판정을 굳히고 나머지는 ``ALREADY_JUDGED`` 로 무기록
        거절된다.
        """
        if limit <= 0:
            raise ValueError(f"limit 은 양수여야 한다: {limit}")
        with self._lock:
            pending = [
                s for s in self._surfaces.values() if s.status is DesignSurfaceStatus.SEALED
            ]
        pending = [surface for surface in pending if self.site_is_visible(surface.site_id)]
        pending.sort(key=lambda s: (s.sealed_at or s.registered_at, s.design_surface_id))
        return pending[:limit]

    def get(self, design_surface_id: str) -> DesignSurface | None:
        with self._lock:
            surface = self._surfaces.get(design_surface_id)
        if surface is None or not self.site_is_visible(surface.site_id):
            return None
        return surface

    def list_for_site(self, site_id: str) -> list[DesignSurface]:
        """현장 1곳의 설계면 전부 — 등록 순서 결정적 목록."""
        if not self.site_is_visible(site_id):
            return []
        with self._lock:
            surfaces = [s for s in self._surfaces.values() if s.site_id == site_id]
        surfaces.sort(key=lambda s: (s.registered_at, s.design_surface_id))
        return surfaces


def _reason_of(surface: DesignSurface) -> DesignSurfaceRejectionReason | None:
    """이미 판정된 레코드의 거부 사유를 typed 로 돌려준다(없으면 None)."""
    if surface.rejection_reason is None:
        return None
    try:
        return DesignSurfaceRejectionReason(surface.rejection_reason)
    except ValueError:  # pragma: no cover - 원장에 없는 값은 재생이 이미 막는다
        return None


#: 사유별 사람 말 설명 — 화면의 한국어 문구는 대시보드가 소유하지만(labels.ts),
#: API 응답의 ``detail`` 은 워커 로그·CLI 에서 그대로 읽히므로 여기 둔다.
_REJECTION_DETAIL: dict[DesignSurfaceRejectionReason, str] = {
    DesignSurfaceRejectionReason.DIGEST_MISMATCH: (
        "올라온 파일의 해시가 신고한 해시와 다르다 — 다른 파일이 업로드됐거나 전송 중 손상됐다"
    ),
    DesignSurfaceRejectionReason.CRS_DECLARATION_MISMATCH: (
        "파일이 들고 있는 좌표계가 신고한 좌표계와 다르다"
    ),
    DesignSurfaceRejectionReason.UNSUPPORTED_CRS: (
        "이 제품이 지원하지 않는 좌표계다 — 현행 KGD2002 평면직각좌표계로 다시 만들어 올린다"
    ),
    DesignSurfaceRejectionReason.UNSUPPORTED_UNIT: (
        "평면 길이 단위가 미터가 아니다 — 피트 단위 도면은 받지 않는다"
    ),
    DesignSurfaceRejectionReason.UNSUPPORTED_BAND_COUNT: (
        "밴드가 1개가 아니다 — 표고 래스터(DEM)가 아니라 정사영상 등을 올린 것으로 보인다"
    ),
    DesignSurfaceRejectionReason.NO_FINITE_CELLS: (
        "유효한 표고 값이 하나도 없다 — 전부 nodata 이거나 빈 래스터다"
    ),
    DesignSurfaceRejectionReason.VERTICAL_DECLARATION_CONTRADICTED: (
        "파일이 들고 있는 수직기준이 신고한 수직기준과 맞지 않거나 해석할 수 없다 — "
        "타원체고와 정표고를 섞으면 20~30m 가 조용히 틀린다"
    ),
    DesignSurfaceRejectionReason.UNREADABLE_RASTER: (
        "파일을 열지 못했다 — GeoTIFF 가 아니거나 손상됐다"
    ),
    DesignSurfaceRejectionReason.SOURCE_LINEAGE_INVALID: (
        "LandXML 원본·선택 Surface·정규화 GeoTIFF의 계보가 없거나 해시가 맞지 않는다"
    ),
    DesignSurfaceRejectionReason.LANDXML_NORMALIZATION_FAILED: (
        "LandXML TIN을 안전한 KSI 표준 GeoTIFF로 정규화하지 못했다 — "
        "원본을 수정해 새 revision으로 다시 등록한다"
    ),
}

if set(_REJECTION_DETAIL) != set(DesignSurfaceRejectionReason):  # pragma: no cover - import 가드
    raise AssertionError("_REJECTION_DETAIL 이 DesignSurfaceRejectionReason 전 멤버를 덮지 않는다")


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class DesignSurfaceRegisterRequest(CamelModel):
    """설계면 1건의 등록 — ``declared`` 는 통째로 계약 모델을 그대로 받는다.

    계약 모델을 그대로 쓰면 "선언은 전부 업로더 주장"이라는 경계가 요청 스키마
    에서도 유지되고, ``source`` 가 ``user_declared`` 여야 한다는 규칙도 계약이
    한 번만 강제한다(요청 검증이 그 validator 를 그대로 탄다).
    """

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_format: str = Field(default="geotiff", pattern="^(geotiff|landxml)$")
    surface_selector: str | None = Field(default=None, min_length=1)
    declared: DesignSurfaceDeclared


class DesignSurfaceRegisterResponse(CamelModel):
    verdict: str
    detail: str | None = None
    design_surface_id: str | None = None
    object_key: str | None = None
    upload_url: str | None = None
    canonical_object_key: str | None = None
    expires_at: datetime | None = None
    surface: DesignSurface | None = None


class DesignSurfaceSealResponse(CamelModel):
    verdict: str
    detail: str | None = None
    surface: DesignSurface | None = None


class DesignSurfaceListResponse(CamelModel):
    surfaces: list[DesignSurface]


class PendingDesignSurfaceView(CamelModel):
    """검증 대기 1건 — **선언값이 없는 것이 이 모델의 요점이다.**

    워커에게 신고 sha256·CRS 를 주면 바이트를 읽지 않고 되읊어 통과할 수 있다.
    여기서 주는 것은 "어느 파일을 어디서 받아라"뿐이다(``source_media`` 의
    ``GET .../input`` 이 신고값을 싣지 않는 것과 같은 원칙).
    """

    design_surface_id: str
    site_id: str
    sealed_at: datetime | None
    download_url: str
    source_format: str = "geotiff"
    surface_selector: str | None = None
    declared_crs: str | None = None
    normalization_upload_url: str | None = None
    expires_at: datetime


class PendingDesignSurfaceListResponse(CamelModel):
    surfaces: list[PendingDesignSurfaceView]


class DesignSurfaceObservationRequest(CamelModel):
    """워커가 파일을 열어 잰 값 — **판정 필드도, 신원 필드도 없다.**

    ``measuredAt``/``measuredBy`` 가 없는 것이 의도다. 둘 다 Core 가 채운다
    (서버 시계 + 인증된 principal) — 워커가 "내가 아니라 저쪽이 쟀다"거나 "어제
    쟀다"를 주장할 통로를 만들지 않는다.
    """

    sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    crs: str = Field(min_length=1)
    vertical_crs_epsg: int | None = Field(default=None, gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    band_count: int = Field(ge=1)
    dtype: str = Field(min_length=1)
    nodata: float | None = None
    nodata_is_nan: bool = False
    pixel_size_x_m: float = Field(gt=0.0)
    pixel_size_y_m: float = Field(gt=0.0)
    transform: tuple[float, float, float, float, float, float]
    bounds_min_x: float
    bounds_min_y: float
    bounds_max_x: float
    bounds_max_y: float
    finite_cell_count: int = Field(ge=0)
    source_lineage: DesignSurfaceSourceLineage | None = None


class DesignSurfaceVerificationFailureRequest(CamelModel):
    """"열지 못했다"는 보고 — 사유는 고를 수 없고 상세만 남긴다(모듈 docstring)."""

    detail: str | None = Field(default=None, max_length=2000)


class DesignSurfaceNormalizationFailureRequest(CamelModel):
    """Trusted worker's LandXML normalisation failure; Core fixes the reason."""

    detail: str | None = Field(default=None, max_length=2000)


class DesignSurfaceObservationResponse(CamelModel):
    verdict: str
    detail: str | None = None
    rejection_reason: str | None = None
    surface: DesignSurface | None = None


def build_design_surface_router(
    store: DesignSurfaceStore, storage: EvidenceStorage, *, landxml_ingress_enabled: bool = False
) -> APIRouter:
    router = APIRouter(tags=["design-surfaces"])

    @router.post(
        "/v1/sites/{site_id}/design-surfaces",
        response_model=DesignSurfaceRegisterResponse,
        status_code=201,
    )
    def register_design_surface(
        site_id: str,
        request: DesignSurfaceRegisterRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> DesignSurfaceRegisterResponse:
        """설계면을 등록하고 업로드용 presigned PUT 을 발급한다.

        등록은 **선언의 기록**일 뿐이다 — 이 응답의 201 은 "파일이 좋다"가 아니라
        "어디에 올리면 되는지 정해졌다"는 뜻이다.
        """
        now = datetime.now(UTC)
        if request.source_format == "landxml" and not landxml_ingress_enabled:
            response.status_code = 403
            return DesignSurfaceRegisterResponse(
                verdict="LANDXML_INGRESS_DISABLED",
                detail="LandXML ingress is disabled until the feature flag is enabled",
            )
        result = store.register(
            site_id,
            request.name,
            request.revision,
            request.declared,
            source_format=request.source_format,
            surface_selector=request.surface_selector,
            registered_by=principal.principal_id,
            now=now,
        )
        response.status_code = _REGISTER_STATUS[result.verdict]
        if result.verdict is DesignSurfaceRegisterVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        if result.verdict is not DesignSurfaceRegisterVerdict.REGISTERED:
            return DesignSurfaceRegisterResponse(
                verdict=result.verdict.value,
                detail=result.detail,
                design_surface_id=(
                    result.surface.design_surface_id if result.surface is not None else None
                ),
                surface=result.surface,
            )

        assert result.surface is not None  # noqa: S101 -- REGISTERED 는 store 가 항상 채운다
        assert result.object_key is not None  # noqa: S101
        try:
            upload_url = storage.presigned_put(
                result.object_key,
                content_type=DESIGN_SURFACE_CONTENT_TYPE,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError:
            # 원장 등록은 이미 durable 하다 — 같은 선언을 재전송하면 멱등
            # 재발급으로 URL 을 다시 받는다(``source_media`` 관습).
            logger.warning("설계면 업로드 URL 발급 실패: %s", result.object_key)
            response.status_code = 503
            response.headers["Retry-After"] = "30"
            return DesignSurfaceRegisterResponse(
                verdict=DesignSurfaceRegisterVerdict.STORE_UNAVAILABLE.value,
                detail=(
                    "등록은 됐으나 업로드 URL 발급에 실패했다 — "
                    "같은 내용으로 재요청하면 재발급된다"
                ),
                design_surface_id=result.surface.design_surface_id,
                object_key=result.object_key,
                canonical_object_key=result.canonical_object_key,
                surface=result.surface,
            )
        return DesignSurfaceRegisterResponse(
            verdict=result.verdict.value,
            design_surface_id=result.surface.design_surface_id,
            object_key=result.object_key,
            canonical_object_key=result.canonical_object_key,
            upload_url=upload_url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
            surface=result.surface,
        )

    @router.post(
        "/v1/sites/{site_id}/design-surfaces/{design_surface_id}/seal",
        response_model=DesignSurfaceSealResponse,
        status_code=201,
    )
    def seal_design_surface(
        site_id: str,
        design_surface_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> DesignSurfaceSealResponse:
        """업로드 완료 **주장**을 기록하고 검증 대기 큐에 넣는다(파일을 읽지 않는다)."""
        existing = store.get(design_surface_id)
        if existing is not None and existing.site_id != site_id:
            # 다른 현장의 id 를 이 경로로 봉인할 수 없다 — 경로의 siteId 가
            # 장식이 되면 권한 검사가 가리키는 대상이 흐려진다.
            response.status_code = 404
            return DesignSurfaceSealResponse(
                verdict=DesignSurfaceSealVerdict.UNKNOWN_DESIGN_SURFACE.value,
                detail=_NOT_FOUND_DETAIL,
            )
        result = store.seal(
            design_surface_id, sealed_by=principal.principal_id, now=datetime.now(UTC)
        )
        response.status_code = _SEAL_STATUS[result.verdict]
        if result.verdict is DesignSurfaceSealVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DesignSurfaceSealResponse(
            verdict=result.verdict.value, detail=result.detail, surface=result.surface
        )

    @router.get(
        "/v1/sites/{site_id}/design-surfaces", response_model=DesignSurfaceListResponse
    )
    def list_site_design_surfaces(
        site_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> DesignSurfaceListResponse:
        """현장의 설계면 목록 — 선언·관측·상태·거부 사유를 그대로 노출한다.

        미검증 상태를 감추지 않는 것이 요점이다. 화면이 "무엇이 주장이고 무엇이
        확인된 사실인가"를 그리려면 두 블록이 다 보여야 한다.
        """
        del principal
        if not store.site_is_visible(site_id):
            raise HTTPException(status_code=404, detail="현장을 찾을 수 없다")
        return DesignSurfaceListResponse(surfaces=store.list_for_site(site_id))

    @router.get("/v1/design-surfaces", response_model=PendingDesignSurfaceListResponse)
    def list_pending_design_surfaces(
        response: Response,
        status: str = Query(default=DesignSurfaceStatus.SEALED.value),
        limit: int = Query(default=50, ge=1, le=MAX_PENDING_LIMIT),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008,E501
    ) -> PendingDesignSurfaceListResponse:
        """검증 대기 목록(워커 pull 표면) — ``SEALED`` 만 제공한다.

        다른 상태를 조회하는 표면이 아니다. ``REGISTERED`` 는 아직 파일이 없을
        수 있고, 판정이 끝난 것들은 워커가 할 일이 없다 — 그래서 필터를 넓히는
        대신 이 하나만 열어 둔다(현장 목록은 ``SITES_READ`` 경로가 준다).
        """
        del principal
        if status != DesignSurfaceStatus.SEALED.value:
            response.status_code = 422
            return PendingDesignSurfaceListResponse(surfaces=[])
        now = datetime.now(UTC)
        views: list[PendingDesignSurfaceView] = []
        for surface in store.list_pending_verification(limit=limit):
            object_key = build_design_surface_object_key(
                site_id=surface.site_id, design_surface_id=surface.design_surface_id
            )
            try:
                download_url = storage.presigned_get(object_key, ttl=DEFAULT_VIEW_TTL)
                normalization_upload_url = (
                    storage.presigned_put(
                        build_design_surface_canonical_object_key(
                            site_id=surface.site_id, design_surface_id=surface.design_surface_id
                        ),
                        content_type=DESIGN_SURFACE_CONTENT_TYPE,
                        ttl=DEFAULT_UPLOAD_TTL,
                    )
                    if surface.format == "landxml"
                    else None
                )
            except EvidenceStorageError:
                # 이 1건만 목록에서 빠진다 — 스토리지가 회복되면 다음 조회에
                # 다시 나온다. 전체를 503 으로 만들면 멀쩡한 후보들까지 멈춘다.
                logger.warning(
                    "설계면 다운로드 URL 발급 실패: %s", surface.design_surface_id
                )
                continue
            views.append(
                PendingDesignSurfaceView(
                    design_surface_id=surface.design_surface_id,
                    site_id=surface.site_id,
                    sealed_at=surface.sealed_at,
                    download_url=download_url,
                    source_format=surface.format,
                    surface_selector=surface.surface_selector,
                    declared_crs=surface.declared.crs if surface.format == "landxml" else None,
                    normalization_upload_url=normalization_upload_url,
                    expires_at=expires_at(now, DEFAULT_VIEW_TTL),
                )
            )
        return PendingDesignSurfaceListResponse(surfaces=views)

    @router.post(
        "/v1/design-surfaces/{design_surface_id}/observations",
        response_model=DesignSurfaceObservationResponse,
        status_code=201,
    )
    def record_design_surface_observation(
        design_surface_id: str,
        request: DesignSurfaceObservationRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008,E501
    ) -> DesignSurfaceObservationResponse:
        """워커가 실측을 보고하고 **Core 가** 선언과 대조한다.

        권한이 ``PROCESSING_WORK`` 인 것이 이 표면의 핵심이다 — 설계면을 올린
        주체(``SITES_WRITE``)가 자기 신고값을 스스로 검증할 수 없다.
        """
        now = datetime.now(UTC)
        try:
            observed = DesignSurfaceObserved(
                **request.model_dump(exclude={"source_lineage"}),
                measured_at=now,
                measured_by=principal.principal_id,
            )
        except ValidationError as exc:
            # 측정치가 스스로 모순이다(예: 유효셀 수 > 전체 셀 수). 500 이 아니라
            # typed 거부로 돌려준다 — 워커가 무엇을 잘못 쟀는지 알아야 한다.
            response.status_code = _OBSERVATION_STATUS[
                DesignSurfaceObservationVerdict.INVALID_MEASUREMENT
            ]
            return DesignSurfaceObservationResponse(
                verdict=DesignSurfaceObservationVerdict.INVALID_MEASUREMENT.value,
                detail=f"측정치가 성립하지 않는다: {exc.errors()[0]['msg']}",
            )
        result = store.record_observation(
            design_surface_id,
            observed,
            source_lineage=request.source_lineage,
            now=now,
        )
        response.status_code = _OBSERVATION_STATUS[result.verdict]
        if result.verdict is DesignSurfaceObservationVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DesignSurfaceObservationResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            rejection_reason=(
                result.rejection_reason.value if result.rejection_reason is not None else None
            ),
            surface=result.surface,
        )

    @router.post(
        "/v1/design-surfaces/{design_surface_id}/verification-failure",
        response_model=DesignSurfaceObservationResponse,
        status_code=201,
    )
    def report_design_surface_verification_failure(
        design_surface_id: str,
        request: DesignSurfaceVerificationFailureRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008,E501
    ) -> DesignSurfaceObservationResponse:
        """"파일을 열지 못했다"는 보고 — 사유는 ``UNREADABLE_RASTER`` 로 고정이다."""
        result = store.report_verification_failure(
            design_surface_id,
            detail=request.detail,
            reported_by=principal.principal_id,
            now=datetime.now(UTC),
        )
        # 이 경로에서 ``REJECTED`` 는 **성공적으로 기록된 결과**다 — 워커의 요청은
        # 형식도 내용도 옳았고 Core 가 판정을 굳혔다. 관측 경로의 422(=네가 보낸
        # 내용이 사실과 다르다)를 여기 그대로 쓰면, 정상 보고가 실패로 보여
        # 워커가 무한 재시도한다.
        response.status_code = (
            201
            if result.verdict is DesignSurfaceObservationVerdict.REJECTED
            else _OBSERVATION_STATUS[result.verdict]
        )
        if result.verdict is DesignSurfaceObservationVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DesignSurfaceObservationResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            rejection_reason=(
                result.rejection_reason.value if result.rejection_reason is not None else None
            ),
            surface=result.surface,
        )

    @router.post(
        "/v1/design-surfaces/{design_surface_id}/normalization-failure",
        response_model=DesignSurfaceObservationResponse,
        status_code=201,
    )
    def report_design_surface_normalization_failure(
        design_surface_id: str,
        request: DesignSurfaceNormalizationFailureRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008,E501
    ) -> DesignSurfaceObservationResponse:
        result = store.report_normalization_failure(
            design_surface_id,
            detail=request.detail,
            reported_by=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = (
            201
            if result.verdict is DesignSurfaceObservationVerdict.REJECTED
            else _OBSERVATION_STATUS[result.verdict]
        )
        return DesignSurfaceObservationResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            rejection_reason=(result.rejection_reason.value if result.rejection_reason else None),
            surface=result.surface,
        )

    return router


def mount_design_surfaces(
    app: FastAPI,
    store: DesignSurfaceStore,
    storage: EvidenceStorage,
    *,
    landxml_ingress_enabled: bool = False,
) -> None:
    """앱에 설계 기준면 라우터를 장착한다."""
    app.state.design_surface_store = store
    app.include_router(
        build_design_surface_router(
            store, storage, landxml_ingress_enabled=landxml_ingress_enabled
        )
    )


__all__ = [
    "DESIGN_SURFACE_CONTENT_TYPE",
    "MAX_PENDING_LIMIT",
    "DesignSurfaceListResponse",
    "DesignSurfaceNormalizationFailureRequest",
    "DesignSurfaceObservationRequest",
    "DesignSurfaceObservationResponse",
    "DesignSurfaceObservationVerdict",
    "DesignSurfaceRecoveryError",
    "DesignSurfaceRegisterRequest",
    "DesignSurfaceRegisterResponse",
    "DesignSurfaceRegisterVerdict",
    "DesignSurfaceRejectionReason",
    "DesignSurfaceSealResponse",
    "DesignSurfaceSealVerdict",
    "DesignSurfaceStore",
    "DesignSurfaceVerificationFailureRequest",
    "ObservationResult",
    "PendingDesignSurfaceListResponse",
    "PendingDesignSurfaceView",
    "RegistrationResult",
    "SealResult",
    "build_design_surface_id",
    "build_design_surface_canonical_object_key",
    "build_design_surface_object_key",
    "object_key_for_surface",
    "build_design_surface_router",
    "evaluate_observation",
    "mount_design_surfaces",
]
