"""원본 사진 번들 입구 (3D 파이프라인의 첫 관문).

기존 evidence 업로드(``events.py``)는 이미 존재하는 Event 에 종속된다(객체 키가
``sites/{siteId}/events/{deviceId}/{eventId}/{artifactId}``) — 매핑 원본 수천
장에는 매달 사건이 없다. 이 모듈은 **Mission** 에 종속된 별도 입구를 연다.

## sourceBundleDigest 는 Core 가 계산한다 — 요청이 자기 증명서를 쓰지 못한다

``contracts/schemas/processing-job.v1.json`` 의 ``input.sourceBundleDigest`` 가
이 모듈이 만들어야 할 값이다. 클라이언트가 준 값을 그대로 싣지 않는다 — Core 가
정규 정렬된 매니페스트에서 직접 계산한다(:func:`compute_source_bundle_digest`).
정규화는 이 저장소의 유일한 문서화 정규화인
``ksi_mission_contracts.signing.canonical_payload_bytes`` 관습을 그대로
재사용한다(ADR-KSI-002 §2/§3, ``mission_plans.py`` 의 ``_pair_digest`` 와 동일
구성 — ``sha256_digest(canonical_payload_bytes(payload))``). 그 함수는 dict 의
**키**만 정렬하므로(``sort_keys=True``), 파일 리스트 순서 자체는 여기서
``mediaId`` 기준으로 먼저 정렬해 고정한다 — 그래야 같은 파일 집합을 다른 순서로
올려도 같은 digest 가 나온다.

## 업로더의 신고값은 주장이다 — 등록 시점에는 검증하지 않는다

파일마다 ``sha256``·``bytes``·``width``·``height`` 를 신고받지만, 등록 시점에는
서버가 재계산해 대조하지 않는다. ``mediaId`` 는 호출자가 정한다(``evidence.py``
의 ``artifactId`` 관습과 동일) — 같은 mediaId·같은 claim 재전송은 멱등 재발급
(새 presigned URL)이고, 같은 mediaId·다른 claim 은 ``CLAIM_CONFLICT`` 로
거부한다.

## 대조는 Core 가 한다 — 워커는 **잰 값**만 보고한다

:meth:`SourceMediaStore.verify` 가 봉인된 번들의 신고값과 워커의 측정값을
대조한다. 워커가 보내는 것은 :class:`SourceMediaMeasurement` — "내가 읽어서
재보니 sha256 이 X, 4000×3000 이더라"뿐이고, **"검증됐다"는 판정을 보낼 수
없다**. 일치 여부는 Core 가 :func:`compare_measurements` 로 판정하고, 그
함수를 재생 경로가 그대로 다시 탄다.

**측정 집합이 등록 집합과 정확히 같아야 한다.** 빠진 것도 남는 것도 거부한다
(``COVERAGE_INCOMPLETE``) — 일부만 읽고 "검증했다"가 되면 그 필드가 뜻하는
바가 사라진다.

### 워커에게 신고값을 주지 않는다 — 되읊기가 불가능하도록

이 대조가 형식적이지 않은 이유는 **워커가 정답을 모른다**는 데 있다.
``GET /v1/processing-jobs/{jobId}/input``(``processing_jobs.py``)이 워커에게
주는 것은 ``mediaId`` 와 다운로드 URL 뿐이고, 업로더가 신고한 sha256·해상도는
**응답에 실리지 않는다**. 워커에게는 ``MISSIONS_READ`` 도 없어 번들 조회로
우회할 수도 없다(``auth.py``).

그래서 ``VERIFIED`` 를 받으려면 워커는 실제로 바이트를 읽어 sha256 을 계산해야
한다 — 게으른 워커는 통과하지 못하고, 악의적인 워커도 통과하려면 결국 읽어야
한다. "읽지 않고 신고값을 되읊는" 경로가 구조적으로 없다.

**막는 것:** 업로더가 자기 신고값을 스스로 검증하는 것. 올리는 쪽은
``MISSIONS_ISSUE``, 재는 쪽은 ``PROCESSING_WORK`` 이고 **어느 사람 역할도
후자를 갖지 않는다**. 해상도를 부풀려 과금 근거를 만들려면 워커까지 손에
넣어야 하고, 손에 넣어도 파일을 읽어야 한다.

**남는 것:** Core 는 객체 바이트를 중계하지 않으므로(ADR-KSI-010 §1) 서버가
직접 재확인하지는 않는다. 업로더와 워커가 **공모하면**(정답을 밖에서 주고받으면)
여전히 통과한다. 그래서 이 필드의 정확한 뜻은 "KSI 워커가 실측을 보고했고 그
값이 신고값과 일치했다"이지 "서버가 바이트를 봤다"가 아니다.

## 불일치는 기록하되 번들을 영구 오염시키지 않는다

하나라도 어긋나면 ``MISMATCH`` 로 원장에 영구 기록하고 ``verified_at`` 은
채우지 않는다. 번들을 되돌릴 수 없게 막지는 않는다 — 워커 버그로 생긴 오탐에
복구 경로가 없으면 정상 번들이 영구히 죽는다. 재검증은 열려 있고, 시도는
전부 원장에 남는다(``last_mismatch_at`` 으로 화면에도 보인다).

## 객체 키는 서버가 만든다

``sites/{siteId}/missions/{missionId}/source/{mediaId}`` — 세 구성요소 전부
:func:`~ksi_core.identifiers.is_path_safe_identifier` 로 검증한다(evidence.py
``build_object_key`` 관습 대칭).

## 봉인 후에는 거부한다

:meth:`SourceMediaStore.seal` 이후 추가 등록은 ``BUNDLE_SEALED`` 로 거부된다.
재생(``_replay``)도 live 와 같은 게이트를 다시 태운다 — journal 을 손으로 고쳐
봉인 상태·digest 를 위조할 수 없다(``coverage_reports._replay`` 와 동일 원칙).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_geo_spatial.crs import SUPPORTED_PROJECT_CRS, UnsupportedCrsError, normalise_crs
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import Field, model_validator

from ksi_core.domains.artifacts.evidence import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    current_request_organization_id,
    require_permission,
    require_permission_any,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.missions.mission_records import MissionStore

logger = logging.getLogger("ksi_core.source_media")

_NOT_FOUND_DETAIL = "해당 임무의 원본 미디어 번들을 찾을 수 없다"
# 한 요청당 상한 — 수백~수천 장이 몇 번의 요청으로 끝나되, 한 요청이 무한정
# 커져 journal 잠금을 오래 쥐는 것을 막는다.
MAX_BATCH_SIZE = 200
# 신고 해상도 상한 — `runtime_profile.py` 의 reference_width/height 와 같은 값.
# 크기 정책이 아니라 영구 장애 차단이 목적이다(아래 width/height 주석 참조).
_MAX_MEDIA_DIMENSION_PX = 16_384


class SourceMediaBatchVerdict(StrEnum):
    """배치 요청 **전체** 수준 판정. ``PROCESSED`` 면 개별 결과는 항목별로 갈린다."""

    PROCESSED = "PROCESSED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    BUNDLE_SEALED = "BUNDLE_SEALED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class GroundControlVerdict(StrEnum):
    """기준점 파일 등록 판정.

    ``UNSUPPORTED_CRS`` 는 이 표면의 존재 이유다 — 허용 목록 밖 좌표계를 받아
    두면 재구성은 성공하고 비교 단계에서야 거부돼, 몇 분짜리 재구성을 돌린 뒤에
    막힌다. 등록 시점에 막는 편이 훨씬 싸고 사유도 분명하다.
    """

    REGISTERED = "REGISTERED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    BUNDLE_SEALED = "BUNDLE_SEALED"
    UNSUPPORTED_CRS = "UNSUPPORTED_CRS"
    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class SourceMediaItemVerdict(StrEnum):
    """배치 안 파일 1건의 판정.

    ``STORAGE_UNAVAILABLE`` 은 store 가 아니라 **라우터**가 매긴다 — store 는
    스토리지를 모른다(원장 기록과 URL 발급을 분리하는 evidence.py 원칙과 동일).
    """

    REGISTERED = "REGISTERED"
    INVALID_MEDIA_ID = "INVALID_MEDIA_ID"
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
    # 같은 mediaId 가 **다른** claim 으로 이미 등록돼 있다 — 같은 claim 재전송은
    # 이 값이 아니라 REGISTERED(멱등 재발급)다.
    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    JOURNAL_UNAVAILABLE = "JOURNAL_UNAVAILABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class SourceBundleSealVerdict(StrEnum):
    SEALED = "SEALED"
    ALREADY_SEALED = "ALREADY_SEALED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    EMPTY_BUNDLE = "EMPTY_BUNDLE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class SourceBundleVerifyVerdict(StrEnum):
    """실측 대조 판정 — 워커는 이 값을 **보낼 수 없고** Core 가 매긴다."""

    VERIFIED = "VERIFIED"
    # 하나 이상 어긋났다. 원장에 영구 기록되고 번들은 미검증으로 남는다.
    MISMATCH = "MISMATCH"
    # 측정 집합이 등록 집합과 다르다 — 일부만 읽고 검증했다고 할 수 없다.
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    # 봉인 전에는 대조 대상 집합 자체가 아직 확정되지 않았다.
    BUNDLE_NOT_SEALED = "BUNDLE_NOT_SEALED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class CaptureTimeSource(StrEnum):
    """사진 바이트에서 얻은 촬영시각의 근거(우선순위 순)."""

    EXIF_GPS_UTC = "EXIF_GPS_UTC"
    EXIF_DATETIME_OFFSET = "EXIF_DATETIME_OFFSET"
    DJI_XMP_EXPLICIT = "DJI_XMP_EXPLICIT"
    NONE = "NONE"


class CaptureTimeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"


class CaptureWindowStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class CaptureTime:
    """파일 1장의 촬영시각 판정 — 로컬시각을 UTC로 추정하지 않는다."""

    captured_at: datetime | None
    source: CaptureTimeSource
    status: CaptureTimeStatus

    @classmethod
    def unavailable(cls) -> CaptureTime:
        return cls(None, CaptureTimeSource.NONE, CaptureTimeStatus.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class CaptureWindow:
    """한 처리 epoch가 실제로 관측한 시간 범위."""

    status: CaptureWindowStatus
    captured_from: datetime | None = None
    captured_to: datetime | None = None

    @classmethod
    def incomplete(cls) -> CaptureWindow:
        return cls(CaptureWindowStatus.INCOMPLETE)


def validate_capture_time(value: CaptureTime) -> CaptureTime:
    """wire/journal에서 온 파일별 촬영시각의 조합을 fail-closed 검증한다."""
    if value.status is CaptureTimeStatus.VERIFIED:
        if value.captured_at is None or value.captured_at.tzinfo is None:
            raise ValueError("VERIFIED captureTime은 tz-aware capturedAt이 필요하다")
        if value.source is CaptureTimeSource.NONE:
            raise ValueError("VERIFIED captureTime은 source=NONE일 수 없다")
        return replace(value, captured_at=value.captured_at.astimezone(UTC))
    if value.captured_at is not None or value.source is not CaptureTimeSource.NONE:
        raise ValueError(
            "UNAVAILABLE/CONFLICT captureTime은 capturedAt=null, source=NONE이어야 한다"
        )
    return value


def compute_capture_window(capture_times: Iterable[CaptureTime]) -> CaptureWindow:
    """파일별 판정 전량에서 번들 창을 계산한다 — 부분/충돌은 시각을 내지 않는다."""
    values = tuple(validate_capture_time(value) for value in capture_times)
    if any(value.status is CaptureTimeStatus.CONFLICT for value in values):
        return CaptureWindow(CaptureWindowStatus.CONFLICT)
    if not values or any(value.status is not CaptureTimeStatus.VERIFIED for value in values):
        return CaptureWindow.incomplete()
    captured = [value.captured_at for value in values]
    if any(value is None for value in captured):  # pragma: no cover - validator의 사후조건
        return CaptureWindow.incomplete()
    verified = [value for value in captured if value is not None]
    return CaptureWindow(
        CaptureWindowStatus.COMPLETE,
        captured_from=min(verified),
        captured_to=max(verified),
    )


def capture_time_wire(value: CaptureTime) -> dict[str, Any]:
    validated = validate_capture_time(value)
    return {
        "capturedAt": iso_utc(validated.captured_at) if validated.captured_at is not None else None,
        "source": validated.source.value,
        "status": validated.status.value,
    }


def capture_window_wire(value: CaptureWindow) -> dict[str, Any]:
    value = validate_capture_window(value)
    return {
        "status": value.status.value,
        "capturedFrom": iso_utc(value.captured_from) if value.captured_from is not None else None,
        "capturedTo": iso_utc(value.captured_to) if value.captured_to is not None else None,
    }


def validate_capture_window(value: CaptureWindow) -> CaptureWindow:
    if value.status is CaptureWindowStatus.COMPLETE:
        if (
            value.captured_from is None
            or value.captured_to is None
            or value.captured_from.tzinfo is None
            or value.captured_to.tzinfo is None
        ):
            raise ValueError("COMPLETE captureWindow은 tz-aware start/end가 필요하다")
        start = value.captured_from.astimezone(UTC)
        end = value.captured_to.astimezone(UTC)
        if end < start:
            raise ValueError("captureWindow.capturedTo는 capturedFrom보다 빠를 수 없다")
        return CaptureWindow(CaptureWindowStatus.COMPLETE, start, end)
    if value.captured_from is not None or value.captured_to is not None:
        raise ValueError("INCOMPLETE/CONFLICT captureWindow은 start/end가 null이어야 한다")
    return value


def capture_window_from_wire(raw: Any, *, context: str) -> CaptureWindow:
    if raw is None:
        return CaptureWindow.incomplete()
    if not isinstance(raw, dict):
        raise ValueError(f"{context}: captureWindow은 object여야 한다")

    def _parse(value: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    status_raw = raw.get("status")
    if not isinstance(status_raw, str):
        raise ValueError(f"{context}: captureWindow.status가 필요하다")
    return validate_capture_window(
        CaptureWindow(
            status=CaptureWindowStatus(status_raw),
            captured_from=_parse(raw.get("capturedFrom")),
            captured_to=_parse(raw.get("capturedTo")),
        )
    )


def capture_time_from_wire(raw: Any, *, context: str) -> CaptureTime:
    """새 wire 형식을 읽되, 필드가 통째로 없던 legacy는 UNAVAILABLE로 둔다."""
    if raw is None:
        return CaptureTime.unavailable()
    if not isinstance(raw, dict):
        raise ValueError(f"{context}: captureTime은 object여야 한다")
    captured_raw = raw.get("capturedAt")
    captured_at = None
    if captured_raw is not None:
        captured_at = datetime.fromisoformat(str(captured_raw).replace("Z", "+00:00"))
    source_raw = raw.get("source")
    status_raw = raw.get("status")
    if not isinstance(source_raw, str) or not isinstance(status_raw, str):
        raise ValueError(f"{context}: captureTime.source/status가 필요하다")
    return validate_capture_time(
        CaptureTime(
            captured_at=captured_at,
            source=CaptureTimeSource(source_raw),
            status=CaptureTimeStatus(status_raw),
        )
    )


_BATCH_STATUS: dict[SourceMediaBatchVerdict, int] = {
    SourceMediaBatchVerdict.PROCESSED: 201,
    SourceMediaBatchVerdict.UNKNOWN_MISSION: 404,
    SourceMediaBatchVerdict.BUNDLE_SEALED: 409,
    SourceMediaBatchVerdict.STORE_UNAVAILABLE: 503,
}

#: 기준점 파일의 저장 형식 — 텍스트지만 브라우저가 해석할 이유가 없어
#: octet-stream 으로 둔다(허용 목록 안, ``evidence.ALLOWED_CONTENT_TYPES``).
GROUND_CONTROL_CONTENT_TYPE = "application/octet-stream"

_GROUND_CONTROL_STATUS: dict[GroundControlVerdict, int] = {
    GroundControlVerdict.REGISTERED: 201,
    GroundControlVerdict.UNKNOWN_MISSION: 404,
    GroundControlVerdict.BUNDLE_SEALED: 409,
    GroundControlVerdict.CLAIM_CONFLICT: 409,
    # 422 — 요청 형식은 맞지만 그 값으로는 이 시스템이 할 일이 없다
    # (design_surfaces 의 좌표계 거부와 같은 코드).
    GroundControlVerdict.UNSUPPORTED_CRS: 422,
    GroundControlVerdict.STORE_UNAVAILABLE: 503,
}

_SEAL_STATUS: dict[SourceBundleSealVerdict, int] = {
    SourceBundleSealVerdict.SEALED: 201,
    SourceBundleSealVerdict.ALREADY_SEALED: 200,
    SourceBundleSealVerdict.UNKNOWN_MISSION: 404,
    SourceBundleSealVerdict.EMPTY_BUNDLE: 422,
    SourceBundleSealVerdict.STORE_UNAVAILABLE: 503,
}

_VERIFY_STATUS: dict[SourceBundleVerifyVerdict, int] = {
    SourceBundleVerifyVerdict.VERIFIED: 201,
    SourceBundleVerifyVerdict.ALREADY_VERIFIED: 200,
    # 422 다 — 요청 형식은 옳고 **내용이 사실과 다르다**. 재시도로 해결되지
    # 않는다는 뜻을 담는다(409 는 "지금 상태가 아니다"라 재시도 여지를 남긴다).
    SourceBundleVerifyVerdict.MISMATCH: 422,
    SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE: 422,
    SourceBundleVerifyVerdict.UNKNOWN_MISSION: 404,
    SourceBundleVerifyVerdict.BUNDLE_NOT_SEALED: 409,
    SourceBundleVerifyVerdict.STORE_UNAVAILABLE: 503,
}


class SourceMediaRecoveryError(RuntimeError):
    """source-media journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


def build_source_media_object_key(*, site_id: str, mission_id: str, media_id: str) -> str:
    """객체 키를 **서버가** 만든다(``evidence.build_object_key`` 관습 대칭).

    세 구성요소를 전부 재검증한다 — 호출부가 이미 검증했더라도, 이 함수가
    경로 탈출을 막는 마지막 지점이기 때문이다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(mission_id):
        raise ValueError(f"경로-안전하지 않은 missionId: {mission_id!r}")
    if not is_path_safe_identifier(media_id):
        raise ValueError(f"경로-안전하지 않은 mediaId: {media_id!r}")
    return f"sites/{site_id}/missions/{mission_id}/source/{media_id}"


#: 지상 기준점 파일의 고정 객체 이름 — 재구성 엔진(ODM)이 이 이름으로만 인식한다.
GROUND_CONTROL_FILENAME = "gcp_list.txt"


def build_ground_control_object_key(*, site_id: str, mission_id: str) -> str:
    """기준점 파일 자리 — 사진과 같은 폴더에 고정 이름으로 하나만 둔다.

    임무당 1건이라 식별자를 받지 않는다: 두 벌을 두면 "어느 것으로 재구성했나"가
    원장 밖 지식이 된다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(mission_id):
        raise ValueError(f"경로-안전하지 않은 missionId: {mission_id!r}")
    return f"sites/{site_id}/missions/{mission_id}/source/{GROUND_CONTROL_FILENAME}"


@dataclass(frozen=True, slots=True)
class GroundControlRecord:
    """이 임무의 지상 기준점 파일 — **좌표계를 신고와 함께** 원장에 남긴다.

    ## 왜 이 레코드가 필요한가

    재구성 엔진은 사진의 GPS 만으로는 그 지역의 UTM 좌표계로 결과를 낸다. 두
    시점 비교는 현행 한국 평면직각좌표계에서만 허용되므로(``ksi_geo_spatial.crs``
    화이트리스트, INV-020), **기준점 없이 찍은 조사는 비교 단계에 도달하지 못한다**
    (2026-08-18 실측: 사진 87장 재구성 2회가 모두 EPSG:32617 로 나와 거부됨).

    기준점 파일이 좌표계를 선언하면 엔진이 그 좌표계로 성과를 내고, 두 시점이
    같은 기준에 묶여 절대 표고 차이(같은 실측에서 0.29 m)도 사라진다.

    ## 신고와 내용을 누가 대조하나

    Core 는 바이트를 만지지 않는다(ADR-KSI-010 §1) — 여기서는 **신고된 좌표계가
    허용 목록 안인지**만 본다. 파일 첫 줄이 그 신고와 실제로 같은지는 파일을
    내려받는 워커가 대조하고, 어긋나면 그 작업을 실패로 끝낸다(사진의 sha256 을
    워커가 실측 대조하는 것과 같은 분담).
    """

    sha256: str
    size_bytes: int
    #: 이 파일이 선언하는 좌표계(예: ``EPSG:5186``) — 허용 목록 안이어야 등록된다.
    crs: str
    object_key: str
    registered_at: datetime
    registered_by: str


@dataclass(frozen=True, slots=True)
class SourceMediaClaim:
    """업로더가 신고한 파일 1건의 주장 — 이 단계는 검증하지 않는다.

    전 바이트를 읽는 워커(B3)가 재계산해 대조한다.
    """

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    content_type: str


@dataclass(frozen=True, slots=True)
class SourceMediaRecord:
    """원장에 등록된 파일 1건 — claim + 서버가 만든 객체 키 + 등록 메타."""

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    content_type: str
    object_key: str
    registered_at: datetime
    registered_by: str
    # 등록 시점에는 아직 바이트를 읽지 않았으므로 UNAVAILABLE. 워커 검증 레코드가
    # 성공적으로 재생된 뒤에만 실제 파일별 판정으로 교체된다.
    capture_time: CaptureTime = CaptureTime(
        None, CaptureTimeSource.NONE, CaptureTimeStatus.UNAVAILABLE
    )

    @property
    def claim(self) -> SourceMediaClaim:
        """등록 메타를 뺀 claim 부분 — 재전송 대조(같은 claim인지)에 쓴다."""
        return SourceMediaClaim(
            media_id=self.media_id,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            width=self.width,
            height=self.height,
            content_type=self.content_type,
        )


@dataclass(frozen=True, slots=True)
class SourceMediaMeasurement:
    """워커가 **실제로 읽어서 잰** 값 — 판정이 아니라 측정치다.

    ``content_type`` 이 없는 것이 의도다. 그건 업로드 시점의 선언이지 바이트를
    읽어 재는 값이 아니고, 여기 있으면 워커가 "이 파일은 사실 이 타입이다"를
    주장하는 통로가 된다 — 이 모듈이 워커에게 허용하는 것은 측정뿐이다.
    """

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    capture_time: CaptureTime = CaptureTime(
        None, CaptureTimeSource.NONE, CaptureTimeStatus.UNAVAILABLE
    )


@dataclass(frozen=True, slots=True)
class MeasurementComparison:
    """신고값 대 측정값 대조 결과 — live 와 재생이 같은 판정을 공유한다."""

    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        """측정 집합이 등록 집합과 정확히 같은가."""
        return not self.missing and not self.unexpected

    @property
    def is_match(self) -> bool:
        return self.is_complete and not self.mismatched


def compare_measurements(
    media: Iterable[SourceMediaRecord], measurements: Iterable[SourceMediaMeasurement]
) -> MeasurementComparison:
    """등록된 신고값과 워커 측정값을 대조한다 — **판정의 SSOT**.

    live 경로(:meth:`SourceMediaStore.verify`)와 재생 경로가 같은 함수를 쓴다.
    각자 조건문을 갖고 있으면 한쪽만 고쳐지는 순간 journal 이 거짓 검증을
    되살리는 경로가 열린다(``compute_source_bundle_digest`` 재계산과 같은 원칙).

    ``mediaId`` 중복 측정은 ``unexpected`` 로 잡힌다 — 같은 파일을 두 번 재서
    한 번만 맞히는 식으로 대조를 흐릴 수 없다.
    """
    claimed = {record.media_id: record for record in media}
    seen: set[str] = set()
    unexpected: list[str] = []
    mismatched: list[str] = []
    for measured in measurements:
        record = claimed.get(measured.media_id)
        if record is None or measured.media_id in seen:
            unexpected.append(measured.media_id)
            continue
        seen.add(measured.media_id)
        if (
            record.sha256 != measured.sha256
            or record.size_bytes != measured.size_bytes
            or record.width != measured.width
            or record.height != measured.height
        ):
            mismatched.append(measured.media_id)
    return MeasurementComparison(
        missing=tuple(sorted(set(claimed) - seen)),
        unexpected=tuple(sorted(unexpected)),
        mismatched=tuple(sorted(mismatched)),
    )


@dataclass(frozen=True, slots=True)
class SourceMediaBundle:
    """한 임무의 원본 미디어 번들 상태 — 등록된 미디어 + 봉인 + 실측 대조 여부."""

    mission_id: str
    site_id: str
    media: tuple[SourceMediaRecord, ...] = ()
    #: 이 조사에 붙은 지상 기준점 파일(있으면 1건). 봉인 전에만 붙일 수 있다.
    ground_control: GroundControlRecord | None = None
    sealed_at: datetime | None = None
    sealed_by: str | None = None
    source_bundle_digest: str | None = None
    # 워커가 전 바이트를 읽어 신고값과 일치함을 보고한 시각. 정확히는
    # "KSI 워커가 실측했다고 보고한 시각"이다(모듈 docstring).
    verified_at: datetime | None = None
    verified_by: str | None = None
    # 마지막 불일치 보고 — 검증을 막지는 않지만 화면에 드러난다.
    last_mismatch_at: datetime | None = None

    @property
    def is_sealed(self) -> bool:
        return self.sealed_at is not None

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def capture_window(self) -> CaptureWindow:
        """현재 projection의 파일별 판정에서 계산한 창 — 별도 그림자 상태가 아니다."""
        return compute_capture_window(record.capture_time for record in self.media)


def compute_source_bundle_digest_from_claims(
    mission_id: str,
    claims: Iterable[SourceMediaClaim],
    ground_control: GroundControlRecord | None = None,
) -> str:
    """등록 **전** 단계에서도 부를 수 있는 digest — 매니페스트 구성의 SSOT.

    :func:`compute_source_bundle_digest` 가 이 함수에 위임한다. 진입점이 둘인 이유는
    업로더(``tools/upload_source_bundle.py``)가 "내가 들고 있는 이 묶음이 이미 봉인된
    그 묶음인가"를 판정해야 하는데, 그 시점에는 아직 :class:`SourceMediaRecord`
    (객체 키·등록 시각)가 없기 때문이다. 업로더가 매니페스트를 자기 손으로 다시 짜면
    한쪽만 바뀌는 순간 그 대조가 조용히 무의미해진다 — 그래서 **같은 함수**를 부르게
    한다(``compare_measurements`` 를 live·재생 공용 판정으로 둔 것과 같은 이유).

    ``ground_control`` 도 같은 이유로 여기서 받는다: 기준점이 붙은 조사와 안 붙은
    조사는 서로 다른 입력이라, 두 진입점 중 한쪽만 그것을 세면 같은 묶음이 두 개의
    지문을 갖게 된다.
    """
    manifest: dict[str, Any] = {
        "missionId": mission_id,
        "media": sorted(
            (
                {
                    "mediaId": claim.media_id,
                    "sha256": claim.sha256,
                    "bytes": claim.size_bytes,
                    "width": claim.width,
                    "height": claim.height,
                    "contentType": claim.content_type,
                }
                for claim in claims
            ),
            key=lambda entry: entry["mediaId"],
        ),
    }
    # 기준점 파일은 **있을 때만** 매니페스트에 실린다. 없을 때 빈 키를 넣으면
    # 기존 번들의 digest 가 전부 바뀌어, 이미 봉인된 원장이 재생에서 불일치로
    # 거부된다(_replay_seal 의 재계산 대조).
    if ground_control is not None:
        manifest["groundControl"] = {
            "sha256": ground_control.sha256,
            "bytes": ground_control.size_bytes,
            "crs": ground_control.crs,
        }
    return sha256_digest(canonical_payload_bytes(manifest))


def compute_source_bundle_digest(
    mission_id: str,
    media: Iterable[SourceMediaRecord],
    ground_control: GroundControlRecord | None = None,
) -> str:
    return compute_source_bundle_digest_from_claims(
        mission_id, (record.claim for record in media), ground_control
    )


@dataclass(frozen=True, slots=True)
class SourceMediaItemResult:
    media_id: str
    verdict: SourceMediaItemVerdict
    object_key: str | None = None
    # REGISTERED 일 때만 채워진다 — 라우터가 presigned PUT 을 서명할 때 필요하다
    # (evidence.py 관습과 동일: ContentType 을 서명에 포함하지 않으면 업로더가
    # 임의 타입으로 올릴 수 있어 MIME allowlist 가 발급 시점 장식이 된다).
    content_type: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRegistrationResult:
    verdict: SourceMediaBatchVerdict
    detail: str | None = None
    items: tuple[SourceMediaItemResult, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundControlResult:
    verdict: GroundControlVerdict
    detail: str | None = None
    record: GroundControlRecord | None = None


@dataclass(frozen=True, slots=True)
class SealResult:
    verdict: SourceBundleSealVerdict
    detail: str | None = None
    bundle: SourceMediaBundle | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verdict: SourceBundleVerifyVerdict
    detail: str | None = None
    bundle: SourceMediaBundle | None = None
    # 어떤 파일이 어긋났는지 — 워커가 무엇을 다시 봐야 하는지 알 수 있게.
    comparison: MeasurementComparison | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _require_aware_iso(raw: Any, field_name: str, mission_id: str) -> datetime:
    """journal 의 ISO 시각을 tz-aware datetime 으로 — naive·비문자열은 기동 거부."""
    if not isinstance(raw, str):
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — missionId={mission_id}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — missionId={mission_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 naive datetime — missionId={mission_id}"
        )
    return parsed


class SourceMediaStore:
    """``DurableJournal`` 위의 원본 미디어 번들 저장소(``coverage_reports.py`` 형태 대칭).

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 판정+append+projection 을
    한 임계구역으로 묶는다(다른 저장소 관습 대칭).
    """

    def __init__(self, journal: DurableJournal, *, mission_store: MissionStore) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._lock = threading.Lock()
        self._bundles: dict[str, SourceMediaBundle] = {}
        try:
            self._replay(journal)
        except SourceMediaRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise SourceMediaRecoveryError(
                f"source-media journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw["kind"]
            mission_id = raw["missionId"]
            if kind == "source-media-registered":
                self._replay_registration(mission_id, raw)
            elif kind == "source-media-sealed":
                self._replay_seal(mission_id, raw)
            elif kind == "source-media-ground-control-registered":
                self._replay_ground_control(mission_id, raw)
            elif kind == "source-media-verified":
                self._replay_verification(mission_id, raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise SourceMediaRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_registration(self, mission_id: str, raw: dict[str, Any]) -> None:
        bundle = self._bundles.get(mission_id)
        if bundle is not None and bundle.is_sealed:
            # live 는 봉인된 번들에 등록을 절대 만들지 않는다 — 봉인 후 등록
            # 레코드가 있다는 것은 journal 조작이거나 쓰기 경로가 깨진 것이다.
            raise SourceMediaRecoveryError(
                f"재생: 봉인된 번들에 등록 레코드가 있다 — missionId={mission_id}"
            )
        media_id = raw["mediaId"]
        if not is_path_safe_identifier(media_id):
            raise SourceMediaRecoveryError(
                f"재생: mediaId 가 유효하지 않다({media_id!r}) — missionId={mission_id}"
            )
        if raw["contentType"] not in ALLOWED_CONTENT_TYPES:
            raise SourceMediaRecoveryError(
                f"재생: 허용되지 않은 contentType({raw['contentType']!r}) — missionId={mission_id}"
            )
        if bundle is not None and any(m.media_id == media_id for m in bundle.media):
            # live 는 같은 claim 재전송을 journal 에 다시 쓰지 않는다(멱등 재발급은
            # 무기록) — 그래서 재생에서 같은 mediaId 가 두 번 나오면 진짜 중복이다.
            raise SourceMediaRecoveryError(
                f"재생: mediaId 중복 등록({media_id!r}) — missionId={mission_id}"
            )
        record = SourceMediaRecord(
            media_id=media_id,
            sha256=raw["sha256"],
            size_bytes=raw["bytes"],
            width=raw["width"],
            height=raw["height"],
            content_type=raw["contentType"],
            object_key=raw["objectKey"],
            registered_at=_require_aware_iso(raw["ts"], "ts", mission_id),
            registered_by=raw["registeredBy"],
        )
        if bundle is None:
            bundle = SourceMediaBundle(mission_id=mission_id, site_id=raw["siteId"])
        self._bundles[mission_id] = replace(bundle, media=(*bundle.media, record))

    def _replay_ground_control(self, mission_id: str, raw: dict[str, Any]) -> None:
        """기준점 레코드 재생 — **기록된 좌표계를 다시 검증한다.**

        live 경로가 막는 것(허용 목록 밖 좌표계·봉인 후 등록·중복)을 재생에서도
        같은 강도로 막는다. journal 을 손으로 고쳐 UTM 기준점을 붙인 번들을
        되살리면, 그 조사로 만든 성과가 비교 단계에서 조용히 다른 좌표계로
        섞인다(_replay_seal 의 digest 재계산과 같은 정신).
        """
        bundle = self._bundles.get(mission_id)
        if bundle is not None and bundle.is_sealed:
            raise SourceMediaRecoveryError(
                f"재생: 봉인된 번들에 기준점 등록 레코드가 있다 — missionId={mission_id}"
            )
        if bundle is not None and bundle.ground_control is not None:
            raise SourceMediaRecoveryError(
                f"재생: 기준점이 두 번 등록됐다 — missionId={mission_id}"
            )
        crs = raw["crs"]
        try:
            normalised = normalise_crs(crs)
        except UnsupportedCrsError as exc:
            raise SourceMediaRecoveryError(
                f"재생: 해석할 수 없는 기준점 좌표계({crs!r}) — missionId={mission_id}: {exc}"
            ) from exc
        if normalised not in SUPPORTED_PROJECT_CRS:
            raise SourceMediaRecoveryError(
                f"재생: 허용 목록 밖 기준점 좌표계({normalised}) — missionId={mission_id}"
            )
        record = GroundControlRecord(
            sha256=raw["sha256"],
            size_bytes=raw["bytes"],
            crs=normalised,
            object_key=raw["objectKey"],
            registered_at=_require_aware_iso(raw["ts"], "ts", mission_id),
            registered_by=raw["registeredBy"],
        )
        if bundle is None:
            bundle = SourceMediaBundle(mission_id=mission_id, site_id=raw["siteId"])
        self._bundles[mission_id] = replace(bundle, ground_control=record)

    def _replay_seal(self, mission_id: str, raw: dict[str, Any]) -> None:
        bundle = self._bundles.get(mission_id)
        if bundle is None or not bundle.media:
            raise SourceMediaRecoveryError(
                f"재생: 미등록 미디어(0건)로 봉인된 레코드 — missionId={mission_id}"
            )
        if bundle.is_sealed:
            raise SourceMediaRecoveryError(
                f"재생: 이미 봉인된 번들의 중복 봉인 레코드 — missionId={mission_id}"
            )
        recomputed = compute_source_bundle_digest(mission_id, bundle.media, bundle.ground_control)
        if recomputed != raw["sourceBundleDigest"]:
            # 재생 게이트의 핵심 — journal 을 손으로 고쳐 매니페스트와 어긋난
            # digest 를 봉인 상태로 위조할 수 없다(coverage_reports._replay 대칭).
            raise SourceMediaRecoveryError(
                f"재생: 봉인 레코드의 digest 가 매니페스트 재계산과 불일치 — "
                f"missionId={mission_id} (기록={raw['sourceBundleDigest']!r}, "
                f"재계산={recomputed!r})"
            )
        self._bundles[mission_id] = replace(
            bundle,
            sealed_at=_require_aware_iso(raw["ts"], "ts", mission_id),
            sealed_by=raw["sealedBy"],
            source_bundle_digest=recomputed,
        )

    def _replay_verification(self, mission_id: str, raw: dict[str, Any]) -> None:
        """검증 레코드 재생 — **기록된 판정을 믿지 않고 다시 대조한다.**

        journal 에 남는 것은 워커의 측정값이고, 일치 여부는 재생 시점에
        :func:`compare_measurements` 가 다시 매긴다. 그래서 ``verdict`` 필드를
        VERIFIED 로 손으로 고쳐 넣어도 측정값이 신고값과 어긋나면 기동이
        거부된다(``_replay_seal`` 의 digest 재계산과 같은 원칙).
        """
        bundle = self._bundles.get(mission_id)
        if bundle is None or not bundle.is_sealed:
            raise SourceMediaRecoveryError(
                f"재생: 봉인되지 않은 번들에 검증 레코드가 있다 — missionId={mission_id}"
            )
        try:
            measurements = [
                SourceMediaMeasurement(
                    media_id=item["mediaId"],
                    sha256=item["sha256"],
                    size_bytes=item["bytes"],
                    width=item["width"],
                    height=item["height"],
                    capture_time=capture_time_from_wire(
                        item.get("captureTime"),
                        context=f"missionId={mission_id}, mediaId={item.get('mediaId')}",
                    ),
                )
                for item in raw["measurements"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceMediaRecoveryError(
                "재생: 검증 레코드의 측정값이 형식을 만족하지 않는다 — "
                f"missionId={mission_id}: {exc}"
            ) from exc

        comparison = compare_measurements(bundle.media, measurements)
        recorded = raw["verdict"]
        recomputed = (
            SourceBundleVerifyVerdict.VERIFIED
            if comparison.is_match
            else SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE
            if not comparison.is_complete
            else SourceBundleVerifyVerdict.MISMATCH
        )
        if recorded != recomputed.value:
            raise SourceMediaRecoveryError(
                f"재생: 검증 레코드의 판정이 재대조와 불일치 — missionId={mission_id} "
                f"(기록={recorded!r}, 재대조={recomputed.value!r})"
            )
        if bundle.is_verified:
            # live 는 이미 검증된 번들에 **어떤** 검증 레코드도 더 쓰지 않는다 —
            # verify() 가 대조 전에 ALREADY_VERIFIED 로 빠지고 journal 에 적지
            # 않는다(무기록 멱등). 그러니 여기 레코드가 있다는 것은 원장 조작이거나
            # 쓰기 경로가 깨진 것이다. VERIFIED 중복만 막고 MISMATCH 를 통과시키면
            # "검증됐는데 마지막 대조는 실패"라는, live 가 도달할 수 없는 상태를
            # 재생이 만들어낸다.
            raise SourceMediaRecoveryError(
                f"재생: 이미 검증된 번들에 추가 검증 레코드가 있다"
                f"({recomputed.value}) — missionId={mission_id}"
            )
        ts = _require_aware_iso(raw["ts"], "ts", mission_id)
        if recomputed is SourceBundleVerifyVerdict.VERIFIED:
            measured_by_id = {item.media_id: item for item in measurements}
            updated_media = tuple(
                replace(record, capture_time=measured_by_id[record.media_id].capture_time)
                for record in bundle.media
            )
            capture_window = compute_capture_window(
                record.capture_time for record in updated_media
            )
            recorded_window = raw.get("captureWindow")
            if recorded_window is not None and recorded_window != capture_window_wire(
                capture_window
            ):
                raise SourceMediaRecoveryError(
                    "재생: 기록된 captureWindow가 파일별 captureTime 재계산과 불일치 — "
                    f"missionId={mission_id}"
                )
            self._bundles[mission_id] = replace(
                bundle,
                media=updated_media,
                verified_at=ts,
                verified_by=raw["verifiedBy"],
            )
        else:
            self._bundles[mission_id] = replace(bundle, last_mismatch_at=ts)

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def register_batch(
        self,
        mission_id: str,
        claims: Sequence[SourceMediaClaim],
        *,
        registered_by: str,
        now: datetime,
        caller_device_id: str | None = None,
    ) -> BatchRegistrationResult:
        """배치 1건을 처리한다 — 요청 수준 게이트 통과 후 항목별로 typed 판정한다.

        요청 수준(``UNKNOWN_MISSION``/``BUNDLE_SEALED``/``STORE_UNAVAILABLE``)은
        배치 전체에 적용되고 개별 결과가 없다. 통과하면(``PROCESSED``) 항목마다
        독립 판정한다 — 한 파일의 claim 충돌이 나머지 파일의 등록을 막지 않는다.

        ``caller_device_id`` 는 Edge 장비 호출일 때만 넘긴다(사람 호출은
        ``None`` — 아무 mission 이나 허용). 값이 있는데 그 mission 의
        ``assigned_device_id`` 와 다르면 **``UNKNOWN_MISSION`` 과 같은 판정**을
        낸다 — "이 mission 은 존재하지만 네 것이 아니다"를 별도 코드로
        노출하면 다른 장비의 mission 존재 여부를 확인하는 열거 오라클이 된다
        (edge_dispatch.py 의 event 소유권 판정과 동일 관습).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            mission = self._mission_store.get(mission_id)
            if mission is None or (
                caller_device_id is not None and mission.assigned_device_id != caller_device_id
            ):
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            bundle = self._bundles.get(mission_id) or SourceMediaBundle(
                mission_id=mission_id, site_id=mission.site_id
            )
            if bundle.is_sealed:
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.BUNDLE_SEALED,
                    detail="번들이 이미 봉인됐다 — 추가 업로드를 받지 않는다",
                )

            items: list[SourceMediaItemResult] = []
            journal_sealed_mid_batch = False
            for claim in claims:
                if journal_sealed_mid_batch:
                    items.append(
                        SourceMediaItemResult(
                            claim.media_id,
                            SourceMediaItemVerdict.JOURNAL_UNAVAILABLE,
                            detail=JOURNAL_SEALED_DETAIL,
                        )
                    )
                    continue
                bundle, result, sealed = self._register_one_locked(
                    bundle, claim, registered_by=registered_by, now=now
                )
                items.append(result)
                journal_sealed_mid_batch = sealed

            self._bundles[mission_id] = bundle
            return BatchRegistrationResult(SourceMediaBatchVerdict.PROCESSED, items=tuple(items))

    def _register_one_locked(
        self,
        bundle: SourceMediaBundle,
        claim: SourceMediaClaim,
        *,
        registered_by: str,
        now: datetime,
    ) -> tuple[SourceMediaBundle, SourceMediaItemResult, bool]:
        """``claims`` 배치 안 한 항목의 등록. 반환: (갱신된 bundle, 결과, journal 봉인 여부)."""
        if not is_path_safe_identifier(claim.media_id):
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.INVALID_MEDIA_ID
            ), False
        if claim.content_type not in ALLOWED_CONTENT_TYPES:
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.UNSUPPORTED_CONTENT_TYPE
            ), False

        existing = next((m for m in bundle.media if m.media_id == claim.media_id), None)
        if existing is not None:
            if existing.claim == claim:
                # 같은 mediaId + 같은 claim 재전송 — 멱등 재발급(새 URL 은 라우터가
                # 발급한다). journal 에 다시 쓰지 않는다 — 새로 기록할 사실이 없다
                # (mission_plans.py "멱등 재발급" 관습과 동일 원칙).
                return bundle, SourceMediaItemResult(
                    claim.media_id, SourceMediaItemVerdict.REGISTERED,
                    object_key=existing.object_key, content_type=existing.content_type,
                ), False
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.CLAIM_CONFLICT,
                detail="같은 mediaId 가 다른 내용으로 이미 등록돼 있다",
            ), False

        try:
            object_key = build_source_media_object_key(
                site_id=bundle.site_id, mission_id=bundle.mission_id, media_id=claim.media_id
            )
        except ValueError:
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.INVALID_MEDIA_ID
            ), False

        journal_record = {
            "kind": "source-media-registered",
            "ts": iso_utc(now),
            "missionId": bundle.mission_id,
            "siteId": bundle.site_id,
            "mediaId": claim.media_id,
            "objectKey": object_key,
            "sha256": claim.sha256,
            "bytes": claim.size_bytes,
            "width": claim.width,
            "height": claim.height,
            "contentType": claim.content_type,
            "registeredBy": registered_by,
        }
        try:
            self._journal.append(journal_record)
        except JournalSealedError:
            return bundle, SourceMediaItemResult(
                claim.media_id,
                SourceMediaItemVerdict.JOURNAL_UNAVAILABLE,
                detail=JOURNAL_SEALED_DETAIL,
            ), True

        record = SourceMediaRecord(
            media_id=claim.media_id,
            sha256=claim.sha256,
            size_bytes=claim.size_bytes,
            width=claim.width,
            height=claim.height,
            content_type=claim.content_type,
            object_key=object_key,
            registered_at=now,
            registered_by=registered_by,
        )
        updated_bundle = replace(bundle, media=(*bundle.media, record))
        return updated_bundle, SourceMediaItemResult(
            claim.media_id,
            SourceMediaItemVerdict.REGISTERED,
            object_key=object_key,
            content_type=claim.content_type,
        ), False

    def register_ground_control(
        self,
        mission_id: str,
        *,
        sha256: str,
        size_bytes: int,
        crs: str,
        registered_by: str,
        now: datetime,
        caller_device_id: str | None = None,
    ) -> GroundControlResult:
        """이 조사의 기준점 파일 1건을 등록한다 — **봉인 전에만**.

        같은 내용 재전송은 멱등이다(새 URL 은 라우터가 다시 발급한다). 다른 내용을
        같은 임무에 붙이려 하면 ``CLAIM_CONFLICT`` — 조용히 덮어쓰면 이미 계산된
        재구성이 어느 기준점으로 나온 것인지 알 수 없게 된다.

        ``caller_device_id`` 의미는 :meth:`register_batch` 와 동일하다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return GroundControlResult(
                    GroundControlVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            mission = self._mission_store.get(mission_id)
            if mission is None or (
                caller_device_id is not None and mission.assigned_device_id != caller_device_id
            ):
                return GroundControlResult(
                    GroundControlVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            try:
                normalised = normalise_crs(crs)
            except UnsupportedCrsError as exc:
                return GroundControlResult(GroundControlVerdict.UNSUPPORTED_CRS, detail=str(exc))
            if normalised not in SUPPORTED_PROJECT_CRS:
                return GroundControlResult(
                    GroundControlVerdict.UNSUPPORTED_CRS,
                    detail=(
                        f"{normalised} 은 이 시스템이 비교에 쓰는 좌표계가 아니다 — 허용: "
                        f"{sorted(SUPPORTED_PROJECT_CRS)}. 기준점 성과를 현행 한국 "
                        "평면직각좌표계로 받아야 두 시점 비교가 성립한다"
                    ),
                )

            bundle = self._bundles.get(mission_id) or SourceMediaBundle(
                mission_id=mission_id, site_id=mission.site_id
            )
            if bundle.is_sealed:
                return GroundControlResult(
                    GroundControlVerdict.BUNDLE_SEALED,
                    detail="번들이 이미 봉인됐다 — 기준점은 봉인 전에만 붙일 수 있다",
                )

            existing = bundle.ground_control
            if existing is not None:
                same = (
                    existing.sha256 == sha256
                    and existing.size_bytes == size_bytes
                    and existing.crs == normalised
                )
                if same:
                    # 멱등 재전송 — journal 에 다시 쓰지 않는다(새로 기록할 사실이 없다).
                    return GroundControlResult(
                        GroundControlVerdict.REGISTERED, record=existing
                    )
                return GroundControlResult(
                    GroundControlVerdict.CLAIM_CONFLICT,
                    detail="이 임무에는 다른 내용의 기준점 파일이 이미 등록돼 있다",
                )

            try:
                object_key = build_ground_control_object_key(
                    site_id=bundle.site_id, mission_id=bundle.mission_id
                )
            except ValueError as exc:
                return GroundControlResult(
                    GroundControlVerdict.UNKNOWN_MISSION, detail=str(exc)
                )

            journal_record: dict[str, Any] = {
                "kind": "source-media-ground-control-registered",
                "ts": iso_utc(now),
                "missionId": bundle.mission_id,
                "siteId": bundle.site_id,
                "objectKey": object_key,
                "sha256": sha256,
                "bytes": size_bytes,
                "crs": normalised,
                "registeredBy": registered_by,
            }
            try:
                self._journal.append(journal_record)
            except JournalSealedError:
                return GroundControlResult(
                    GroundControlVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )

            record = GroundControlRecord(
                sha256=sha256,
                size_bytes=size_bytes,
                crs=normalised,
                object_key=object_key,
                registered_at=now,
                registered_by=registered_by,
            )
            self._bundles[mission_id] = replace(bundle, ground_control=record)
            return GroundControlResult(GroundControlVerdict.REGISTERED, record=record)

    def seal(
        self,
        mission_id: str,
        *,
        sealed_by: str,
        now: datetime,
        caller_device_id: str | None = None,
    ) -> SealResult:
        """번들을 봉인하고 :func:`compute_source_bundle_digest` 로 digest 를 굳힌다.

        이미 봉인된 번들의 재호출은 에러가 아니라 ``ALREADY_SEALED``(기존 digest
        재반환) — 재시도가 안전해야 한다. ``caller_device_id`` 의미는
        :meth:`register_batch` 와 동일(자기 mission 아니면 ``UNKNOWN_MISSION``
        과 같은 판정으로 접는다).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SealResult(
                    SourceBundleSealVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            mission = self._mission_store.get(mission_id)
            if mission is None or (
                caller_device_id is not None and mission.assigned_device_id != caller_device_id
            ):
                return SealResult(
                    SourceBundleSealVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            bundle = self._bundles.get(mission_id)
            if bundle is None or not bundle.media:
                return SealResult(
                    SourceBundleSealVerdict.EMPTY_BUNDLE,
                    detail="등록된 미디어가 0건이다 — 빈 번들은 봉인할 수 없다",
                )
            if bundle.is_sealed:
                return SealResult(SourceBundleSealVerdict.ALREADY_SEALED, bundle=bundle)

            digest = compute_source_bundle_digest(mission_id, bundle.media, bundle.ground_control)
            journal_record = {
                "kind": "source-media-sealed",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "sourceBundleDigest": digest,
                "mediaCount": len(bundle.media),
                "sealedBy": sealed_by,
            }
            try:
                self._journal.append(journal_record)
            except JournalSealedError:
                return SealResult(
                    SourceBundleSealVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            sealed_bundle = replace(
                bundle, sealed_at=now, sealed_by=sealed_by, source_bundle_digest=digest
            )
            self._bundles[mission_id] = sealed_bundle
            return SealResult(SourceBundleSealVerdict.SEALED, bundle=sealed_bundle)

    def verify(
        self,
        mission_id: str,
        measurements: Sequence[SourceMediaMeasurement],
        *,
        verified_by: str,
        now: datetime,
    ) -> VerificationResult:
        """워커의 측정값을 등록된 신고값과 대조한다 — **판정은 Core 가 한다.**

        호출자는 "검증됐다"를 보낼 수 없다(:class:`SourceMediaMeasurement` 에
        판정 필드가 없다). 일치 여부는 :func:`compare_measurements` 가 매기고,
        그 결과가 그대로 journal 에 남아 재생이 다시 대조한다.

        이미 검증된 번들의 재호출은 에러가 아니라 ``ALREADY_VERIFIED`` 이고
        journal 에 다시 쓰지 않는다 — 새로 기록할 사실이 없다(``seal`` 관습).
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return VerificationResult(
                    SourceBundleVerifyVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            # 원본 번들은 Mission 에 종속된 Artifact 다. request principal 의
            # organization scope를 MissionStore가 이미 강제하므로, 여기서도
            # 먼저 같은 권위에 물어야 한다. bundle dict만 바로 읽으면 다른
            # 조직의 PROCESSING_WORKER가 존재 여부를 알아내거나 검증 결과를
            # 기록할 수 있다(INV-060).
            if (
                current_request_organization_id() is not None
                and self._mission_store.get(mission_id) is None
            ):
                return VerificationResult(
                    SourceBundleVerifyVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            bundle = self._bundles.get(mission_id)
            if bundle is None:
                return VerificationResult(
                    SourceBundleVerifyVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            if not bundle.is_sealed:
                return VerificationResult(
                    SourceBundleVerifyVerdict.BUNDLE_NOT_SEALED,
                    detail=(
                        "번들이 아직 봉인되지 않았다 — 봉인 전에는 대조 대상 집합이 "
                        "확정되지 않아 '전부 일치'가 성립하지 않는다"
                    ),
                )
            if bundle.is_verified:
                return VerificationResult(
                    SourceBundleVerifyVerdict.ALREADY_VERIFIED, bundle=bundle
                )

            comparison = compare_measurements(bundle.media, measurements)
            if comparison.is_match:
                verdict = SourceBundleVerifyVerdict.VERIFIED
                detail = None
            elif not comparison.is_complete:
                verdict = SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE
                detail = (
                    f"측정 집합이 등록 집합과 다르다 — 누락 {len(comparison.missing)}건"
                    f"{list(comparison.missing[:5])}, 미등록·중복 "
                    f"{len(comparison.unexpected)}건{list(comparison.unexpected[:5])}"
                )
            else:
                verdict = SourceBundleVerifyVerdict.MISMATCH
                detail = (
                    f"신고값과 실측이 어긋난다 — {len(comparison.mismatched)}건"
                    f"{list(comparison.mismatched[:5])}"
                )

            journal_record: dict[str, Any] = {
                "kind": "source-media-verified",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "verdict": verdict.value,
                # 판정이 아니라 **측정값**이 원장의 사실이다 — 재생이 이걸로
                # 다시 대조하므로, verdict 만 고쳐 넣은 원장은 기동에서 걸린다.
                "measurements": [
                    {
                        "mediaId": m.media_id,
                        "sha256": m.sha256,
                        "bytes": m.size_bytes,
                        "width": m.width,
                        "height": m.height,
                        "captureTime": capture_time_wire(m.capture_time),
                    }
                    for m in measurements
                ],
                "mismatched": list(comparison.mismatched),
                "missing": list(comparison.missing),
                "unexpected": list(comparison.unexpected),
                "verifiedBy": verified_by,
            }
            if verdict is SourceBundleVerifyVerdict.VERIFIED:
                journal_record["captureWindow"] = capture_window_wire(
                    compute_capture_window(m.capture_time for m in measurements)
                )
            try:
                self._journal.append(journal_record)
            except JournalSealedError:
                return VerificationResult(
                    SourceBundleVerifyVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )

            if verdict is SourceBundleVerifyVerdict.VERIFIED:
                measured_by_id = {item.media_id: item for item in measurements}
                updated = replace(
                    bundle,
                    media=tuple(
                        replace(
                            record,
                            capture_time=validate_capture_time(
                                measured_by_id[record.media_id].capture_time
                            ),
                        )
                        for record in bundle.media
                    ),
                    verified_at=now,
                    verified_by=verified_by,
                )
            else:
                updated = replace(bundle, last_mismatch_at=now)
            self._bundles[mission_id] = updated
            return VerificationResult(
                verdict, detail=detail, bundle=updated, comparison=comparison
            )

    def get(self, mission_id: str) -> SourceMediaBundle | None:
        with self._lock:
            # HTTP 요청에서만 MissionStore의 request scope가 현재 조직 밖의
            # mission을 None으로 접는다. replay/복구 진단처럼 request scope가
            # 없는 내부 호출은 이 Artifact projection 자체를 검사할 수 있어야
            # 하므로 기존 동작을 유지한다.
            if (
                current_request_organization_id() is not None
                and self._mission_store.get(mission_id) is None
            ):
                return None
            return self._bundles.get(mission_id)

    def mission_is_visible(self, mission_id: str) -> bool:
        """현재 request scope에서 Mission이 읽을 수 있는가.

        ProcessingJob 같은 종속 Artifact 저장소가 자체 journal만 보고 jobId를
        조회하면 조직 경계를 잃는다. Mission 원장은 그 경계의 권위이므로, 좁은
        boolean 포트만 노출해 같은 판정을 재사용한다. request scope가 없을 때는
        internal replay/diagnostic 호출의 기존 동작을 보존한다.
        """
        with self._lock:
            return self._mission_store.get(mission_id) is not None

    def mission_is_visible_for_organization(
        self, mission_id: str, *, organization_id: str
    ) -> bool:
        """명시한 조직에서 Mission이 읽을 수 있는가.

        request scope가 없는 SiteWorkspace projection도 종속 Artifact를 조직
        경계 안에서 고를 수 있어야 한다. ambient scope를 대신하지 않고 별도
        포트로 둬, 호출자가 두 경계를 모두 적용하도록 한다(INV-060/061).
        """
        with self._lock:
            return (
                self._mission_store.get_scoped(
                    mission_id, organization_id=organization_id
                )
                is not None
            )

    def assigned_device_id(self, mission_id: str) -> str | None:
        """``mission_id`` 에 배정된 장비 ID(없거나 mission 부재면 None).

        Edge 장비 self-mission 범위 검증 전용 — ``register_batch``/``seal``
        의 ``caller_device_id`` 인자, 그리고 ``processing_jobs.ProcessingJobStore``
        가 같은 판정을 재사용한다.
        """
        with self._lock:
            mission = self._mission_store.get(mission_id)
        return mission.assigned_device_id if mission is not None else None


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class SourceMediaFileClaim(CamelModel):
    """업로더가 신고하는 파일 1건의 주장 — 이 시점에는 검증하지 않는다.

    ``mediaId`` 는 호출자가 정한다(``evidence.py`` 의 ``artifactId`` 관습과
    동일 — 재전송 시 멱등 키로 쓰인다).
    """

    media_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1)
    # 상한이 있어야 하는 이유는 크기 정책이 아니라 **영구 장애 차단**이다. 파이썬 int 는
    # 자리수 제한이 없어 10**200 같은 신고가 들어오는데, 그 값은 봉인(되돌릴 수 없다)을
    # 지난 뒤 processing-job 발급에서 width*height 로 곱해져 float 범위를 넘고
    # OverflowError 가 난다 — 그때부터 그 임무는 **완전히 정상인 요청으로도** 영원히
    # 500 이다(2026-08-18 실측: 등록 201 → 봉인 201 → 발급 500 영구).
    # 상한값은 runtime_profile.py 의 reference_width/height 관례를 그대로 쓴다.
    width: int = Field(ge=1, le=_MAX_MEDIA_DIMENSION_PX)
    height: int = Field(ge=1, le=_MAX_MEDIA_DIMENSION_PX)
    content_type: str = Field(min_length=1)


class SourceMediaBatchRequest(CamelModel):
    files: list[SourceMediaFileClaim] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class SourceMediaItemView(CamelModel):
    media_id: str
    verdict: str
    object_key: str | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None
    detail: str | None = None


class SourceMediaBatchResponse(CamelModel):
    verdict: str
    detail: str | None = None
    results: list[SourceMediaItemView]


class CaptureTimeView(CamelModel):
    captured_at: datetime | None = None
    source: CaptureTimeSource = CaptureTimeSource.NONE
    status: CaptureTimeStatus = CaptureTimeStatus.UNAVAILABLE

    @model_validator(mode="after")
    def validate_semantics(self) -> CaptureTimeView:
        self.to_domain()
        return self

    def to_domain(self) -> CaptureTime:
        return validate_capture_time(
            CaptureTime(
                captured_at=self.captured_at,
                source=self.source,
                status=self.status,
            )
        )


class CaptureWindowView(CamelModel):
    status: CaptureWindowStatus
    captured_from: datetime | None = None
    captured_to: datetime | None = None


def _to_capture_window_view(value: CaptureWindow) -> CaptureWindowView:
    return CaptureWindowView(
        status=value.status,
        captured_from=value.captured_from,
        captured_to=value.captured_to,
    )


class SourceMediaBundleView(CamelModel):
    """번들 상태·장수·digest — 미검증 상태를 그대로 노출한다."""

    mission_id: str
    status: str
    media_count: int
    source_bundle_digest: str | None
    sealed_at: datetime | None
    # **"KSI 워커가 전 바이트를 읽어 신고값과 일치함을 보고한 시각"**이다
    # (모듈 docstring "막는 것과 못 막는 것"). null 이면 아직 아무도 안 읽었다.
    verified_at: datetime | None
    # 마지막 불일치 보고 시각. verified_at 이 null 인데 이 값이 있으면 "아직
    # 안 쟀다"가 아니라 **"재봤는데 어긋났다"**다 — 화면이 둘을 구분해야 한다.
    last_mismatch_at: datetime | None
    # 이 조사에 기준점이 붙었는가와 그 좌표계. null 이면 안 붙은 것이고, 그 조사의
    # 성과로는 두 시점 비교를 할 수 없다(엔진이 UTM 으로 낸다) — 화면이 그 사실을
    # 미리 말할 수 있도록 목록·상세 응답에 함께 싣는다.
    ground_control_crs: str | None = None
    # 같은 좌표계라도 성과가 다르면 다른 기준점이다 — 재실행하는 도구가 "이미
    # 붙인 그 파일인가"를 정확히 판단할 수 있게 지문도 함께 낸다.
    ground_control_sha256: str | None = None
    capture_window: CaptureWindowView


class GroundControlRequest(CamelModel):
    """기준점 파일 등록 요청 — 내용이 아니라 **신고**다(Core 는 바이트를 안 읽는다)."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=64 * 1024 * 1024)
    #: 이 파일이 선언하는 좌표계. 허용 목록 밖이면 등록 자체가 거부된다.
    crs: str = Field(min_length=1, max_length=64)


class GroundControlResponse(CamelModel):
    verdict: str
    detail: str | None = None
    object_key: str | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None
    crs: str | None = None


class SourceMediaSealResponse(CamelModel):
    verdict: str
    detail: str | None = None
    bundle: SourceMediaBundleView | None = None


class SourceMediaMeasurementItem(CamelModel):
    """워커가 실측한 파일 1건. **판정 필드가 없는 것이 이 모델의 요점이다.**"""

    media_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1)
    # 상한이 있어야 하는 이유는 크기 정책이 아니라 **영구 장애 차단**이다. 파이썬 int 는
    # 자리수 제한이 없어 10**200 같은 신고가 들어오는데, 그 값은 봉인(되돌릴 수 없다)을
    # 지난 뒤 processing-job 발급에서 width*height 로 곱해져 float 범위를 넘고
    # OverflowError 가 난다 — 그때부터 그 임무는 **완전히 정상인 요청으로도** 영원히
    # 500 이다(2026-08-18 실측: 등록 201 → 봉인 201 → 발급 500 영구).
    # 상한값은 runtime_profile.py 의 reference_width/height 관례를 그대로 쓴다.
    width: int = Field(ge=1, le=_MAX_MEDIA_DIMENSION_PX)
    height: int = Field(ge=1, le=_MAX_MEDIA_DIMENSION_PX)
    capture_time: CaptureTimeView = Field(default_factory=CaptureTimeView)


class SourceMediaVerifyRequest(CamelModel):
    """실측 보고 — 등록된 전 파일을 한 번에 준다(부분 검증은 검증이 아니다).

    등록(:class:`SourceMediaBatchRequest`)과 달리 ``max_length`` 가 **없다.**
    등록은 나눠 보낼 수 있어서 상한이 배치 크기를 제한할 뿐이지만, 검증은
    정의상 전량이라 상한을 두면 큰 번들이 영영 검증되지 못한다. 대신 항목이
    작다 — 3,000장이라도 요청 본문은 수백 KB 수준이고 journal append 는 한 번이다.
    """

    measurements: list[SourceMediaMeasurementItem] = Field(min_length=1)


class SourceMediaVerifyResponse(CamelModel):
    verdict: str
    detail: str | None = None
    bundle: SourceMediaBundleView | None = None
    # 어긋난·빠진·남는 mediaId — 워커가 무엇을 다시 봐야 하는지.
    mismatched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)


def _to_bundle_view(bundle: SourceMediaBundle) -> SourceMediaBundleView:
    return SourceMediaBundleView(
        mission_id=bundle.mission_id,
        status="SEALED" if bundle.is_sealed else "OPEN",
        media_count=len(bundle.media),
        source_bundle_digest=bundle.source_bundle_digest,
        sealed_at=bundle.sealed_at,
        verified_at=bundle.verified_at,
        last_mismatch_at=bundle.last_mismatch_at,
        ground_control_crs=(
            bundle.ground_control.crs if bundle.ground_control is not None else None
        ),
        ground_control_sha256=(
            bundle.ground_control.sha256 if bundle.ground_control is not None else None
        ),
        capture_window=_to_capture_window_view(bundle.capture_window),
    )


class SourceMediaViewResponse(CamelModel):
    """사진 1장의 열람 URL + 원장이 아는 화소수·digest.

    ``width``/``height`` 는 **업로더가 신고한 값**이다(전 바이트를 읽은 워커가
    대조하기 전까지는 주장이다 — 모듈 docstring). 결함 후보의 ``imageSize`` 는
    Core 가 이 값과 이미 대조했으므로(``defect_candidates.judge_candidate``),
    화면은 이 둘이 같다는 전제로 폴리곤 배율을 계산해도 된다.
    """

    media_id: str
    content_type: str
    view_url: str
    expires_at: datetime
    width: int
    height: int
    sha256: str
    capture_time: CaptureTimeView


# 모듈 수준 싱글턴 — B008(Depends 인자에서 함수 호출 금지) 회피 + 두 엔드포인트
# (register/seal)가 같은 권한 판정 객체를 공유한다.
_require_source_media_write = require_permission_any(
    Permission.MISSIONS_ISSUE, Permission.EDGE_SOURCE_MEDIA_WRITE
)


def build_source_media_router(store: SourceMediaStore, storage: EvidenceStorage) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["source-media"])

    def _to_item_view(item: SourceMediaItemResult, *, now: datetime) -> SourceMediaItemView:
        """store 판정을 응답으로 번역하고, REGISTERED 항목만 presigned PUT 을 시도한다.

        store 는 스토리지를 모른다(원장 기록과 URL 발급을 분리하는 evidence.py
        원칙) — presign 실패는 여기서 ``STORAGE_UNAVAILABLE`` 로 격하한다. 원장
        등록 자체는 이미 성공했으므로(durable), 같은 claim 을 재전송하면 다음
        시도에서 멱등 재발급으로 URL 을 다시 받을 수 있다.
        """
        if item.verdict is not SourceMediaItemVerdict.REGISTERED or item.object_key is None:
            return SourceMediaItemView(
                media_id=item.media_id, verdict=item.verdict.value, detail=item.detail
            )
        assert item.content_type is not None  # noqa: S101 -- REGISTERED 는 store 가 항상 채운다
        try:
            url = storage.presigned_put(
                item.object_key, content_type=item.content_type, ttl=DEFAULT_UPLOAD_TTL
            )
        except EvidenceStorageError:
            logger.warning("source-media presigned PUT 발급 실패: %s", item.object_key)
            return SourceMediaItemView(
                media_id=item.media_id,
                verdict=SourceMediaItemVerdict.STORAGE_UNAVAILABLE.value,
                object_key=item.object_key,
                detail="등록은 됐으나 URL 발급에 실패했다 — 같은 내용으로 재요청하면 재발급된다",
            )
        return SourceMediaItemView(
            media_id=item.media_id,
            verdict=item.verdict.value,
            object_key=item.object_key,
            upload_url=url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
        )

    @router.post(
        "/{mission_id}/source-media", response_model=SourceMediaBatchResponse, status_code=201
    )
    def register_source_media(
        mission_id: str,
        request: SourceMediaBatchRequest,
        response: Response,
        principal: Principal = Depends(_require_source_media_write),  # noqa: B008
    ) -> SourceMediaBatchResponse:
        now = datetime.now(UTC)
        claims = [
            SourceMediaClaim(
                media_id=f.media_id,
                sha256=f.sha256,
                size_bytes=f.bytes,
                width=f.width,
                height=f.height,
                content_type=f.content_type,
            )
            for f in request.files
        ]
        result = store.register_batch(
            mission_id,
            claims,
            registered_by=principal.principal_id,
            now=now,
            caller_device_id=(
                principal.device_id if principal.kind is PrincipalKind.EDGE_DEVICE else None
            ),
        )
        response.status_code = _BATCH_STATUS[result.verdict]
        if result.verdict is SourceMediaBatchVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return SourceMediaBatchResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            results=[_to_item_view(item, now=now) for item in result.items],
        )

    @router.post(
        "/{mission_id}/source-media/ground-control",
        response_model=GroundControlResponse,
        status_code=201,
    )
    def register_ground_control(
        mission_id: str,
        request: GroundControlRequest,
        response: Response,
        principal: Principal = Depends(_require_source_media_write),  # noqa: B008
    ) -> GroundControlResponse:
        """지상 기준점 파일을 이 조사에 붙인다(봉인 전에만, 임무당 1건).

        사진과 같은 방식이다 — Core 는 자리(objectKey)와 업로드 URL 만 내주고
        바이트는 스토리지로 직접 간다(ADR-KSI-010 §1). 다른 점 하나는 **좌표계를
        여기서 막는다**는 것이다: 허용 목록 밖 좌표계를 받아 두면 재구성이 끝난
        뒤 비교 단계에서야 거부돼, 몇 분을 버리고 사유도 멀리서 나타난다.
        """
        now = datetime.now(UTC)
        result = store.register_ground_control(
            mission_id,
            sha256=request.sha256,
            size_bytes=request.bytes,
            crs=request.crs,
            registered_by=principal.principal_id,
            now=now,
            caller_device_id=(
                principal.device_id if principal.kind is PrincipalKind.EDGE_DEVICE else None
            ),
        )
        response.status_code = _GROUND_CONTROL_STATUS[result.verdict]
        if result.verdict is GroundControlVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        if result.verdict is not GroundControlVerdict.REGISTERED or result.record is None:
            return GroundControlResponse(verdict=result.verdict.value, detail=result.detail)

        record = result.record
        try:
            url = storage.presigned_put(
                record.object_key,
                content_type=GROUND_CONTROL_CONTENT_TYPE,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except EvidenceStorageError:
            logger.warning("기준점 presigned PUT 발급 실패: %s", record.object_key)
            response.status_code = 503
            response.headers["Retry-After"] = "30"
            return GroundControlResponse(
                verdict=GroundControlVerdict.REGISTERED.value,
                object_key=record.object_key,
                crs=record.crs,
                detail="등록은 됐으나 URL 발급에 실패했다 — 같은 내용으로 재요청하면 재발급된다",
            )
        return GroundControlResponse(
            verdict=result.verdict.value,
            object_key=record.object_key,
            upload_url=url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
            crs=record.crs,
        )

    @router.post(
        "/{mission_id}/source-media/seal",
        response_model=SourceMediaSealResponse,
        status_code=201,
    )
    def seal_source_media(
        mission_id: str,
        response: Response,
        principal: Principal = Depends(_require_source_media_write),  # noqa: B008
    ) -> SourceMediaSealResponse:
        result = store.seal(
            mission_id,
            sealed_by=principal.principal_id,
            now=datetime.now(UTC),
            caller_device_id=(
                principal.device_id if principal.kind is PrincipalKind.EDGE_DEVICE else None
            ),
        )
        response.status_code = _SEAL_STATUS[result.verdict]
        if result.verdict is SourceBundleSealVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return SourceMediaSealResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            bundle=_to_bundle_view(result.bundle) if result.bundle is not None else None,
        )

    @router.post(
        "/{mission_id}/source-media/verify",
        response_model=SourceMediaVerifyResponse,
        status_code=201,
    )
    def verify_source_media(
        mission_id: str,
        request: SourceMediaVerifyRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> SourceMediaVerifyResponse:
        """Deprecated unfenced worker surface.

        Worker Correctness TASK-1 moved processing verification to
        ``POST /v1/processing-jobs/{jobId}/verify-input``.  This mission-only
        route cannot prove a current lease generation, so it must not mutate
        source authority after multi-worker fencing is enabled.
        """
        del mission_id, request, principal
        response.status_code = 409
        return SourceMediaVerifyResponse(
            verdict="LEASE_FENCE_REQUIRED",
            detail=(
                "unfenced mission verification is disabled; use the current "
                "processing-job lease endpoint"
            ),
        )

    @router.get("/{mission_id}/source-media", response_model=SourceMediaBundleView)
    def get_source_media(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> SourceMediaBundleView:
        del principal
        bundle = store.get(mission_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_bundle_view(bundle)

    @router.get(
        "/{mission_id}/source-media/{media_id}/view", response_model=SourceMediaViewResponse
    )
    def view_source_media(
        mission_id: str,
        media_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> SourceMediaViewResponse:
        """사진 1장의 단기 열람 URL — 결함 후보 폴리곤을 원본 위에 겹치기 위한 경로.

        업로드용 presigned PUT(``POST .../source-media``)과 달리 이건 **운영자가
        보는** 경로다. 화소수를 함께 내는 이유: 결함 후보의 폴리곤은 원본 픽셀
        좌표라, 화면이 축소해 그릴 때 배율을 계산하려면 원본 크기를 알아야 한다.
        그 값을 클라이언트가 이미지 로드 후 읽어 쓰면 로드 전에는 레이아웃을
        잡을 수 없고, 무엇보다 **등록된 화소수와 실제 이미지가 다를 때 그 불일치가
        조용히 묻힌다** — 서버가 원장 값을 그대로 내려주면 화면이 대조할 수 있다.

        객체가 아직 올라오지 않았어도 URL 은 발급된다(등록과 업로드는 별개 단계다)
        — 그 경우 URL 을 열면 스토리지가 404 를 준다. Core 가 오브젝트 존재를
        확인하려면 스토리지에 HEAD 를 걸어야 하는데, 그건 이 포트에 없는 동작이다.
        """
        del principal
        bundle = store.get(mission_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        record = next((m for m in bundle.media if m.media_id == media_id), None)
        if record is None:
            raise HTTPException(
                status_code=404, detail="해당 임무에 등록된 적 없는 mediaId 다"
            )
        try:
            url = storage.presigned_get(record.object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError as exc:
            # 스토리지 장애를 "사진 없음"으로 뭉개지 않는다(evidence.py 와 동일 원칙).
            raise HTTPException(status_code=503, detail="SOURCE_MEDIA_STORAGE_UNAVAILABLE") from exc
        return SourceMediaViewResponse(
            media_id=record.media_id,
            content_type=record.content_type,
            view_url=url,
            expires_at=expires_at(datetime.now(UTC), DEFAULT_VIEW_TTL),
            width=record.width,
            height=record.height,
            sha256=record.sha256,
            capture_time=CaptureTimeView(
                captured_at=record.capture_time.captured_at,
                source=record.capture_time.source,
                status=record.capture_time.status,
            ),
        )

    return router


def mount_source_media(app: FastAPI, store: SourceMediaStore, storage: EvidenceStorage) -> None:
    """앱에 원본 미디어 번들 라우터를 장착한다."""
    app.state.source_media_store = store
    app.include_router(build_source_media_router(store, storage))


__all__ = [
    "MAX_BATCH_SIZE",
    "BatchRegistrationResult",
    "CaptureTime",
    "CaptureTimeSource",
    "CaptureTimeStatus",
    "CaptureTimeView",
    "CaptureWindow",
    "CaptureWindowStatus",
    "CaptureWindowView",
    "MeasurementComparison",
    "SealResult",
    "SourceBundleSealVerdict",
    "SourceBundleVerifyVerdict",
    "SourceMediaBatchRequest",
    "SourceMediaBatchResponse",
    "SourceMediaBatchVerdict",
    "SourceMediaBundle",
    "SourceMediaBundleView",
    "SourceMediaClaim",
    "SourceMediaItemResult",
    "SourceMediaItemVerdict",
    "SourceMediaMeasurement",
    "SourceMediaRecord",
    "SourceMediaRecoveryError",
    "SourceMediaSealResponse",
    "SourceMediaStore",
    "SourceMediaVerifyRequest",
    "SourceMediaVerifyResponse",
    "SourceMediaViewResponse",
    "VerificationResult",
    "GROUND_CONTROL_CONTENT_TYPE",
    "GROUND_CONTROL_FILENAME",
    "GroundControlRecord",
    "GroundControlResult",
    "GroundControlVerdict",
    "build_ground_control_object_key",
    "build_source_media_object_key",
    "build_source_media_router",
    "compare_measurements",
    "compute_capture_window",
    "compute_source_bundle_digest",
    "compute_source_bundle_digest_from_claims",
    "mount_source_media",
]
