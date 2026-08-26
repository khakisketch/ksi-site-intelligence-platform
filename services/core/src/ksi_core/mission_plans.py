"""임무 계획 발급 — 이원 산출물(KMZ + Mission Contract)을 **한 번에 짝으로** (ADR-KSI-007).

구역(AOI)+임무타입 정의 한 번이 두 산출물을 낳는다: ① 기체용 WPML/KMZ 웨이라인
② Manifold 용 서명된 Mission Contract. 이 모듈이 그 짝 발급의 유일한 진입점이다 —
따로 발급하면 site_frame·정책 버전이 어긋난 산출물 쌍(사일런트 drift)이 생길 수
있으므로, 경로 생성과 계약 서명이 **같은 요청·같은 FlightEnvelope** 에서 나온다는
사실을 엔드포인트 구조로 강제한다.

임무 타입 → 경로 패턴 매핑(ADR-KSI-007 §결정):

- lawnmower(왕복 스캔): BASELINE_MAPPING·SPATIAL_REFRESH·SURVEY_GRADE_MAPPING·
  PROGRESS_CAPTURE·UNIFIED_SITE_SURVEY — 면 커버리지 계열
- perimeter(외곽 순회): AUTONOMOUS_PATROL·INCIDENT_SURVEY — 순찰·정찰 계열
- ASSET_INSPECTION 은 **미지원 거부**(fail-closed) — 구조물 근접 경로는 대상
  구조물 지오메트리·standoff 계산이 필요해 별도 구현 전까지 조용히 lawnmower 로
  퇴화시키지 않는다.

기체 enum(DroneProfile)은 요청이 명시한다 — M4D 의 droneEnumValue 는 실기(H4)
검증 전 서버가 추측하지 않는다(wpml.py 모듈 docstring 참조).

## 짝 manifest 포맷 (``wpmz/res/ksi-mission-pair.json``, format=ksi-mission-pair/v1)

KMZ 에 동봉되는 짝 식별자다. 해시 정규화는 이 repo 의 유일한 문서화 정규화인
ADR-KSI-002 §2/§3 을 그대로 재사용한다(:func:`canonical_payload_bytes` —
``signature`` 블록 제외·sort_keys·compact·ensure_ascii=False·allow_nan=False,
표기는 ``sha256:<hex>``). 별도 정규화를 만들지 않는 이유(재검증 P2): Manifold 등
비-Python 검증기가 ADR 문서만 보고 재현했을 때 한글 필드에서 불일치가 나는
정규화 분열을 차단한다.

- ``contractPayloadSha256``: 계약 **payload**(signature 제외)의 digest — 같은
  내용으로 재서명해도 짝 판정이 유지된다(짝의 단위는 서명이 아니라 내용).
- ``siteFrameSha256``: 요청 site_frame 의 동일 규약 digest.
- 나머지 키(missionId·siteId·정책 ID 4종)는 평문 식별자.

## 멱등 재발급 (재검토 P2 item③)

201 응답이 네트워크에서 유실되면(전송 중 유실·클라이언트 타임아웃) 클라이언트는
missionId 소각(재시도 시 409)과 KMZ 영구 소실을 동시에 겪는다 — KMZ 바이트
자체는 journal 에 넣지 않기 때문이다(용량). 그래서 짝 레코드는 KMZ 를
**재생성 가능한 입력**(``MissionPlanRequest`` 전문 + 원 ``issued_at``)을 함께
영속하고, 같은 missionId 로 **동일 요청 digest**(``_request_digest`` —
ADR-KSI-002 정규화 재사용)가 재도착하면 :func:`_regenerate_pair_artifact` 가
저장된 입력으로 KMZ 를 다시 만들어 그대로 재반환한다(200, 새 journal 레코드는
만들지 않는다). ``build_kmz``/경로 생성기 계열에 시각·난수·UUID 의존이 없어
(패키지 전수 확인) 같은 입력+같은 issued_at 이면 바이트 동일성이 보장된다 —
이 결정성은 ``tests/contract/test_mission_records.py`` 의
``test_identical_retry_of_pair_issuance_is_idempotent`` 가 실 바이트 비교로
증명한다. **다른** digest 로 같은 missionId 를 재사용하면 여전히 409
``MISSION_ID_CONFLICT`` 다 — 멱등 재반환은 '같은 요청의 재시도'로만 한정된다.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import MissionType
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
)
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from ksi_mission_planning import (
    AreaOfInterest,
    CameraSpec,
    CameraSpecError,
    DroneProfile,
    GridSpacing,
    KmzBuildError,
    RouteGenerationError,
    WaylineMissionConfig,
    build_kmz,
    compute_grid_spacing,
    lawnmower_route,
    perimeter_route,
)
from ksi_mission_planning.camera import DEFAULT_FRONT_OVERLAP, DEFAULT_SIDE_OVERLAP
from pydantic import Field, ValidationError

from ksi_core.acquisition.coordination import (
    AcquisitionCoordinationConflictError,
    AcquisitionCoordinationStore,
)
from ksi_core.api_base import CamelModel
from ksi_core.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
    require_permission_any,
)
from ksi_core.durable_journal import JournalSealedError
from ksi_core.evidence import EvidenceStorage, EvidenceStorageError
from ksi_core.identifiers import is_path_safe_identifier
from ksi_core.mission_issuance import MissionIssuanceRequest, issue_mission_contract
from ksi_core.mission_records import (
    MISSION_NOT_FOUND_DETAIL,
    MissionIssuanceSequenceStore,
    MissionRecord,
    MissionRecordVerdict,
    MissionStore,
    SiteLookupResult,
    precheck_issuance,
    raise_for_mission_record_verdict,
    reject_lone_surrogates,
)
from ksi_core.observation_work_orders import ObservationWorkOrderStore

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import FastAPI
    from ksi_mission_planning import RouteWaypoint

logger = logging.getLogger(__name__)

# WPML takeOffSecurityHeight 유효범위 하한 — 공식 스펙 [1.2, 1500]m (wpml.py 가
# raw 표에서 확인한 값과 동일 근거).
_MIN_TAKEOFF_SECURITY_HEIGHT_M = 1.2

_LAWNMOWER_TYPES = frozenset(
    {
        MissionType.BASELINE_MAPPING,
        MissionType.SPATIAL_REFRESH,
        MissionType.SURVEY_GRADE_MAPPING,
        MissionType.PROGRESS_CAPTURE,
        MissionType.UNIFIED_SITE_SURVEY,
    }
)
_PERIMETER_TYPES = frozenset({MissionType.AUTONOMOUS_PATROL, MissionType.INCIDENT_SURVEY})


class RouteParams(CamelModel):
    """경로 생성 파라미터 — 고도는 계약 FlightEnvelope 로 생성기가 재게이트한다.

    고도의 수직기준은 이륙점 상대(relativeToStartPoint) — 2026-07-29 대표자 확정,
    계약 스키마 flightEnvelope.altitudeReference 로 명문화.
    ``sweep_direction_deg`` 는 수학 규약(동=0·반시계) — 나침반 방위가 아니다.
    """

    altitude_m: float
    camera: CameraParams | None = Field(
        default=None,
        description=(
            "주면 서버가 카메라·고도·중복도로 spacingM·captureIntervalM 을 계산한다"
            "(권장, lawnmower·AUTONOMOUS_PATROL/INCIDENT_SURVEY(perimeter) 모두). "
            "이때 두 값을 함께 주면 422 — 어느 쪽이 진짜인지 서버가 고르지 않는다"
        ),
    )
    spacing_m: float | None = Field(default=None, description="lawnmower 전용 스캔선 간격(m)")
    capture_interval_m: float | None = Field(
        default=None,
        description=(
            "진행방향 촬영 간격(m, camera 를 안 주면 직접 지정). lawnmower 계열은 "
            "스캔선 위 촬영 지점 간격 — 없으면 스캔선당 사진이 양 끝 2장뿐이라 "
            "전방 중첩이 0 이 되어 정사영상·3D 재구성이 성립하지 않는다. "
            "AUTONOMOUS_PATROL(perimeter)은 이 값(또는 camera)이 Spatial Refresh "
            "Backbone(MASTER_PRD §15.2) 자체이므로 필수다 — 없으면 순찰 중 3D "
            "갱신용 사진이 전혀 수집되지 않는다. camera 를 권장한다: 고정값은 "
            "고도에 따라 전방 중복도가 MIN_FRONT_OVERLAP(0.6) 아래로 내려갈 수 "
            "있다. INCIDENT_SURVEY(perimeter)는 선택 — 없으면 순수 항법 경로다"
        ),
    )
    sweep_direction_deg: float | None = None


class CameraParams(CamelModel):
    """매핑 카메라 스펙 + 원하는 중복도 — 주면 서버가 격자 간격을 **계산**한다.

    이걸 주는 쪽이 권장 경로다(ADR-KSI-011 D2). 간격을 직접 적으면 서버는 그 값이
    적정한지 판단할 근거가 없어, 커버리지 계산이 요청자가 준 가정 위에 서게 된다.

    ``imageWidthPx`` 는 across-track(라인 간격 결정), ``imageHeightPx`` 는
    along-track(사진 간격 결정)이다 — nadir·landscape 표준 배치 가정.
    """

    sensor_width_mm: float
    focal_length_mm: float
    image_width_px: int
    image_height_px: int
    front_overlap: float = DEFAULT_FRONT_OVERLAP
    side_overlap: float = DEFAULT_SIDE_OVERLAP


class DroneProfileParams(CamelModel):
    drone_enum_value: int
    drone_sub_enum_value: int
    payload_enum_value: int
    #: WPML payload sub-profile.  Keep it explicit at the Core boundary so the
    #: generated KMZ cannot silently fall back to a library default when a
    #: device-specific sub-profile is required.
    payload_sub_enum_value: int = 0
    payload_position_index: int = 0


class WaylineParams(CamelModel):
    auto_flight_speed_ms: float
    takeoff_security_height_m: float
    global_transitional_speed_ms: float


class MissionDerivation(CamelModel):
    """이 임무가 어느 분석 결과에서 나왔는가 — **서명 계약의 일부가 아니다.**

    ``assigned_device_id``·``kmz_sha256`` 과 같은 지위의 운영 메타데이터다
    (``MissionRecord`` 참조). 계약에 넣으면 Manifold 가 받는 신뢰 경계 안으로
    서버측 분석 산출물이 들어가고, mission-contract 스키마 자체가 바뀐다 —
    계보를 아는 것은 Core 의 일이지 기체의 일이 아니다.

    이 필드는 ``MissionPlanRequest`` 최상위에 있고 ``request.contract``
    (``MissionIssuanceRequest``, 서명 대상)와는 완전히 분리된 형제 필드다 —
    :func:`build_mission_plan` 이 서명 계약을 조립할 때 ``request.contract`` 만
    읽으므로 이 필드가 새어 들어갈 경로가 구조적으로 없다.

    값의 실재를 발급 시점에 대조하지 **않는다**: 변화영역 리포트는 회전·보관
    정책을 따로 타므로 나중에 없을 수 있고, 그때 계보 기록이 무효가 되면
    안 된다(``coverage_reports`` 가 재생 시 임무 대조를 다시 하지 않는 것과
    같은 이유).
    """

    source_mission_id: str = Field(min_length=1)
    change_region_set_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    #: 초안이 제안한 등급. 운영자가 값을 고쳐도 이 필드는 "무엇을 제안받았나"로 남는다.
    capture_grade: str | None = None


class MissionPlanRequest(CamelModel):
    """계약 발급 요청 + 구역 + 경로/기체 파라미터 — 한 요청이 두 산출물의 단일 근원."""

    contract: MissionIssuanceRequest
    aoi: AreaOfInterest
    route: RouteParams
    drone: DroneProfileParams
    wayline: WaylineParams
    #: 승인된 WorkOrder 회차와의 운영 계보. 서명 계약에는 포함되지 않는다.
    work_order_id: str | None = Field(default=None, min_length=1, max_length=200)
    #: 재관측 임무의 계보(ADR-KSI-019 G5). 최초 매핑 임무는 없다 — 선택 필드다.
    derived_from: MissionDerivation | None = None


def _require_wayline_takeoff_height_compatible(
    takeoff_security_height_m: float, envelope: FlightEnvelope
) -> None:
    """이륙 안전고도가 같은 요청의 비행 봉투와 어긋나지 않는지 게이트한다(P1).

    KMZ 는 서명이 없다 — 이 계층에서 막지 않으면 takeoffSecurityHeightM 이
    envelope.maxAltitudeM 을 넘는(또는 WPML 하한 밖인) 어긋난 계약+KMZ 쌍이
    조용히 발급된다.
    """
    if not math.isfinite(takeoff_security_height_m):
        # NaN 은 아래 두 부등식이 모두 False 라 게이트를 그냥 지나간다 — 하류
        # (WaylineMissionConfig)의 isfinite 에 기대지 않고 게이트 자신이 막는다
        # (재검증 P3: 방어가 게이트 밖에 있으면 호출 순서 변경에 조용히 뚫린다).
        raise RouteGenerationError(
            f"TAKEOFF_HEIGHT_BELOW_MINIMUM: takeoffSecurityHeightM 은 finite 여야 "
            f"한다 (got {takeoff_security_height_m!r})"
        )
    if takeoff_security_height_m < _MIN_TAKEOFF_SECURITY_HEIGHT_M:
        raise RouteGenerationError(
            "TAKEOFF_HEIGHT_BELOW_MINIMUM: takeoffSecurityHeightM"
            f"({takeoff_security_height_m}) < {_MIN_TAKEOFF_SECURITY_HEIGHT_M}m"
        )
    if takeoff_security_height_m > envelope.max_altitude_m:
        raise RouteGenerationError(
            "TAKEOFF_HEIGHT_EXCEEDS_ENVELOPE: takeoffSecurityHeightM"
            f"({takeoff_security_height_m}) > maxAltitudeM({envelope.max_altitude_m})"
        )


def _pair_digest(payload: dict[str, Any]) -> str:
    """짝 식별자 digest — ADR-KSI-002 정규화(canonical_payload_bytes)를 그대로 재사용.

    독자 정규화(ensure_ascii 기본값·signature 포함) 금지 — 비-Python 검증기가 ADR
    문서 규약으로 재현할 때 한글 계약에서 항상 불일치가 나던 분열(재검증 P2) 방지.
    """
    return sha256_digest(canonical_payload_bytes(payload))


def _request_digest(plan_request_payload: dict[str, Any]) -> str:
    """멱등 재발급 대조용 요청 digest — ``_pair_digest`` 와 동일 정규화 재사용.

    ``canonical_payload_bytes`` 는 ``signature`` 키만 제외하는데, 요청 payload 엔
    그 키가 없으므로 전체가 그대로 정규화된다(무해한 재사용, 재검토 P2 item③).
    """
    return _pair_digest(plan_request_payload)


def _grid_from_camera(camera: Any, *, altitude_m: float) -> GridSpacing:
    """카메라 스펙으로 격자 간격을 계산한다 — lawnmower/perimeter 공통 물리식.

    두 패턴이 같은 계산을 공유해야 한다는 것은 우연이 아니라 명시적 결정이다
    (ADR-KSI-011 D3, ``test_patrol_camera_computes_capture_interval``: "AUTONOMOUS_PATROL
    도 route.camera 를 주면 lawnmower 와 동일하게... 동일 물리식·동일 카메라"). 이
    변환 실패의 문구(``str(exc)``)는 두 분기가 이미 동일하게 썼다 — 분기별로 다른
    것은 그 앞뒤의 "camera 와 spacing 을 함께 줄 수 없다"류 검증뿐이고, 그건 각
    호출부에 그대로 남아 있다.
    """
    try:
        return compute_grid_spacing(
            CameraSpec(
                sensor_width_mm=camera.sensor_width_mm,
                focal_length_mm=camera.focal_length_mm,
                image_width_px=camera.image_width_px,
                image_height_px=camera.image_height_px,
            ),
            altitude_m=altitude_m,
            front_overlap=camera.front_overlap,
            side_overlap=camera.side_overlap,
        )
    except CameraSpecError as exc:
        raise RouteGenerationError(str(exc)) from exc


def build_mission_plan(
    request: MissionPlanRequest,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    issued_at: datetime | None = None,
    contract_schema_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    site_sequence: int | None = None,
) -> dict[str, Any]:
    """경로 생성 → 서명 계약 → 짝 식별자 동봉 KMZ 발급. 실패는 typed 예외로 전파된다.

    ``issued_at``: 멱등 재발급(:func:`_regenerate_pair_artifact`)이 원 레코드의
    ``issued_at`` 을 그대로 넘겨, 재서명된 계약의 ``validity`` 창이 원본과
    달라지지 않게 한다(생략 시 :func:`issue_mission_contract` 가 현재 시각을 쓴다).
    """
    mission_type = request.contract.mission_type
    envelope = request.contract.flight_envelope

    _require_wayline_takeoff_height_compatible(request.wayline.takeoff_security_height_m, envelope)

    route: list[RouteWaypoint]
    planned_coverage_ratio: float | None = None
    grid: GridSpacing | None = None
    if mission_type in _LAWNMOWER_TYPES:
        spacing_m = request.route.spacing_m
        capture_interval_m = request.route.capture_interval_m
        if request.route.camera is not None:
            if spacing_m is not None or capture_interval_m is not None:
                # 두 출처가 있으면 어느 쪽이 진짜인지 서버가 고르게 된다 —
                # 그 선택을 조용히 하면 요청자가 본 값과 실제 경로가 갈라진다.
                raise RouteGenerationError(
                    "route.camera 와 spacingM/captureIntervalM 을 함께 줄 수 없다 — "
                    "카메라를 주면 서버가 계산한다"
                )
            grid = _grid_from_camera(request.route.camera, altitude_m=request.route.altitude_m)
            spacing_m, capture_interval_m = grid.spacing_m, grid.capture_interval_m

        if spacing_m is None:
            raise RouteGenerationError(
                f"{mission_type.value} 는 lawnmower 패턴 — route.camera 를 주거나"
                " route.spacingM 을 직접 지정해야 한다"
            )
        if capture_interval_m is None:
            # lawnmower 계열은 전부 촬영이 목적이다(아래에서 capture_at_waypoints=True).
            # 진행방향 간격이 없으면 스캔선당 사진 2장 → 전방 중첩 0 → 사진측량
            # 산출물이 성립하지 않는다(원장 risk mapping-forward-overlap-zero).
            # 카메라 종속 기본값을 서버가 추측하지 않고 fail-closed 로 막는다 —
            # "격자는 날았는데 지도가 안 나온다"가 비행 후에야 드러나는 것보다 낫다.
            raise RouteGenerationError(
                f"{mission_type.value} 는 lawnmower 패턴 — route.captureIntervalM 이 "
                "필요하다(없으면 전방 중첩이 0 이라 정사영상·3D 재구성이 성립하지 않는다)"
            )
        lawnmower_result = lawnmower_route(
            request.aoi,
            spacing_m=spacing_m,
            altitude_m=request.route.altitude_m,
            envelope=envelope,
            sweep_direction_deg=request.route.sweep_direction_deg,
            capture_interval_m=capture_interval_m,
            spacing_is_camera_derived=grid is not None,
        )
        route = lawnmower_result.waypoints
        planned_coverage_ratio = lawnmower_result.coverage_ratio
        pattern = "lawnmower"
        # 계약이 요구하는 커버(accessibleGeneralCoverage)를 **계획이 애초에
        # 겨냥하고 있는가**를 발급 전에 본다. 이건 사전 점검이지 커버 보증이
        # 아니다 — 실제 달성 여부는 비행 후 CoverageReport 가 판정한다
        # (MASTER_PRD §15.5, INV-010). 계획조차 목표 미만이면 그 임무는 성공할
        # 수 없으므로 여기서 끊는다. 1e-9 는 정확 계산의 부동소수 잔차 허용치다.
        if planned_coverage_ratio + 1e-9 < request.contract.accessible_general_coverage:
            raise RouteGenerationError(
                "COVERAGE_BELOW_CONTRACT_PROMISE — 계획 커버 추정치 "
                f"{planned_coverage_ratio:.4f} 가 계약이 요구하는 accessibleGeneralCoverage "
                f"{request.contract.accessible_general_coverage} 미만이다. spacing·"
                "sweep 을 조정하거나 약속 값을 실측 이하로 낮춰 발급하라"
            )
    elif mission_type in _PERIMETER_TYPES:
        capture_interval_m = request.route.capture_interval_m
        capture_interval_is_camera_derived = request.route.camera is not None
        if request.route.camera is not None:
            if capture_interval_m is not None:
                raise RouteGenerationError(
                    "route.camera 와 captureIntervalM 을 함께 줄 수 없다 — 카메라를 "
                    "주면 서버가 계산한다"
                )
            grid = _grid_from_camera(request.route.camera, altitude_m=request.route.altitude_m)
            # spacing_m(across-track 라인 간격)은 perimeter 에 스캔선 개념이 없어
            # 무의미하다 — capture_interval_m(along-track 촬영 간격)만 쓴다. 계산
            # 자체는 lawnmower 와 동일 물리식이라 MIN_FRONT_OVERLAP(0.6) 미만은
            # compute_grid_spacing 이 이미 거부한다(리뷰 P1-b — 고정 상수는 고도에
            # 따라 이 하한 아래로 내려갈 수 있어 "3D 갱신용" 이라는 목적 자체가
            # 성립하지 않는 밀도로 찍힐 수 있었다).
            capture_interval_m = grid.capture_interval_m
        if mission_type is MissionType.AUTONOMOUS_PATROL and capture_interval_m is None:
            # 순찰의 기본 경로는 Spatial Refresh Backbone 을 포함한다(MASTER_PRD
            # §15.2) — 선택 사항이 아니다. lawnmower 계열이 captureIntervalM 을
            # fail-closed 로 요구하는 것과 동일 철학: 카메라 종속 기본값을 서버가
            # 추측하지 않고, "격자는 날았는데 3D 갱신용 사진이 없다"가 비행 후에야
            # 드러나는 것보다 발급 전 거부가 낫다.
            raise RouteGenerationError(
                "AUTONOMOUS_PATROL 은 route.camera 또는 route.captureIntervalM 이 "
                "필요하다 — 순찰의 기본 경로는 3D 갱신에 필요한 Spatial Refresh "
                "Backbone(MASTER_PRD §15.2, 광각 재구성용 사진을 일정 간격으로 "
                "수집)을 포함해야 한다"
            )
        route = perimeter_route(
            request.aoi,
            altitude_m=request.route.altitude_m,
            envelope=envelope,
            capture_interval_m=capture_interval_m,
            capture_interval_is_camera_derived=capture_interval_is_camera_derived,
        )
        pattern = "perimeter"
    else:
        raise RouteGenerationError(
            f"{mission_type.value} 경로 패턴은 아직 미지원이다 — 조용한 퇴화 대신 거부한다"
        )

    # 발급 순서: 계약 먼저(ADR-KSI-007 '동일 site_frame·policy_version 짝'의 실체화).
    # KMZ 는 그 계약의 canonical sha256 을 포함한 pair_manifest 를 동봉해, 두
    # 산출물이 사후에도(전송·저장 경로가 갈리더라도) 짝임을 검증 가능하게 한다.
    contract = issue_mission_contract(
        request.contract,
        private_key=private_key,
        key_id=key_id,
        issued_at=issued_at,
        schema_version=contract_schema_version,
        issuer_id=issuer_id,
        site_sequence=site_sequence,
    )
    contract_payload = contract.model_dump(by_alias=True, mode="json", exclude_none=True)
    site_frame_payload = request.contract.site_frame.model_dump(
        by_alias=True, mode="json", exclude_none=True
    )
    pair_manifest: dict[str, str] = {
        "format": "ksi-mission-pair/v1",
        "missionId": request.contract.mission_id,
        "siteId": request.contract.site_id,
        "contractPayloadSha256": _pair_digest(contract_payload),
        "viewpointPolicyId": request.contract.viewpoint_policy_id,
        "riskPolicyPackId": request.contract.risk_policy_pack_id,
        "fallbackPolicyId": request.contract.fallback_policy_id,
        "capturePolicyId": request.contract.capture_policy_id,
        "siteFrameSha256": _pair_digest(site_frame_payload),
    }

    kmz = build_kmz(
        route,
        drone=DroneProfile(
            drone_enum_value=request.drone.drone_enum_value,
            drone_sub_enum_value=request.drone.drone_sub_enum_value,
            payload_enum_value=request.drone.payload_enum_value,
            payload_sub_enum_value=request.drone.payload_sub_enum_value,
            payload_position_index=request.drone.payload_position_index,
        ),
        config=WaylineMissionConfig(
            auto_flight_speed_ms=request.wayline.auto_flight_speed_ms,
            takeoff_security_height_m=request.wayline.takeoff_security_height_m,
            global_transitional_speed_ms=request.wayline.global_transitional_speed_ms,
        ),
        # 매핑 계열은 웨이포인트별 nadir 촬영이 기본(2026-07-29 대표자 승인) —
        # 격자만 날고 사진 0장인 산출물(자율 재검토 F9)을 만들지 않는다. perimeter
        # 계열은 (직접 지정이든 camera 유도든) 실제로 해석된 capture_interval_m 이
        # 있을 때만 촬영한다(AUTONOMOUS_PATROL 은 위에서 이미 필수화했으므로 사실상
        # 항상 True, INCIDENT_SURVEY 는 선택) — request.route.capture_interval_m
        # (원 요청 필드)이 아니라 위에서 camera 로부터 재해석된 지역변수를 봐야
        # 한다: camera 로 계산된 경우 원 요청 필드는 여전히 None 이라 그걸 보면
        # 촬영 웨이포인트는 생성되는데 KMZ 촬영 액션은 빠지는 어긋난 산출물이 된다.
        capture_at_waypoints=(pattern == "lawnmower" or capture_interval_m is not None),
        pair_manifest=pair_manifest,
        # createTime/updateTime 은 **계약이 실제로 각인한 시각**에서 가져온다.
        # 여기서 현재 시각을 읽으면 멱등 재발급이 매번 다른 KMZ 바이트를 내고,
        # 그러면 서명된 봉투의 kmzSha256 짝이 깨진다(ADR-KSI-007). 계약의
        # validity.notBefore 는 원 issued_at 에서 왔고 재발급 때 그대로 재사용된다.
        created_at=datetime.fromisoformat(contract.validity.not_before.replace("Z", "+00:00")),
    )

    return {
        "contract": contract_payload,
        "kmzBase64": base64.b64encode(kmz).decode("ascii"),
        "kmzSha256": hashlib.sha256(kmz).hexdigest(),
        "routePattern": pattern,
        "waypointCount": len(route),
        "plannedCoverageRatio": planned_coverage_ratio,
        # **왜 이 간격이 나왔는가** — 카메라로 계산했을 때만 실린다. 숫자만 남기면
        # 다음 사람이 그 값을 다시 검증할 수 없다(계획 커버리지가 어디에 기대고
        # 있는지도 이걸로만 드러난다).
        "gridBasis": (
            None
            if grid is None
            else {
                "spacingM": grid.spacing_m,
                "captureIntervalM": grid.capture_interval_m,
                "gsdM": grid.gsd_m,
                "footprintAcrossM": grid.footprint_across_m,
                "footprintAlongM": grid.footprint_along_m,
            }
        ),
    }


def build_mission_kmz_object_key(*, site_id: str, mission_id: str) -> str:
    """발급 KMZ 의 보관 키 — 서버가 만든다(``build_source_media_object_key`` 관습).

    두 구성요소를 여기서 재검증한다: 이 함수가 경로 탈출을 막는 마지막 지점이다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(mission_id):
        raise ValueError(f"경로-안전하지 않은 missionId: {mission_id!r}")
    return f"sites/{site_id}/missions/{mission_id}/artifacts/{mission_id}.kmz"


def _regenerate_pair_artifact(
    record: MissionRecord, *, private_key: Ed25519PrivateKey, key_id: str
) -> dict[str, Any]:
    """저장된 ``plan_request`` 로 짝 산출물을 재생성한다(멱등 재발급, 모듈 docstring 참조).

    KMZ 바이트 자체는 journal 에 없으므로 재반환은 항상 재생성이다. 원 레코드의
    ``issued_at`` 을 그대로 넘겨 계약 재서명이 원본과 같은 ``validity`` 창을
    갖게 한다. 재생성 ``kmzSha256`` 이 저장된 값과 다르면(하류 로직 변경 등으로
    결정성이 깨진 경우) 예외로 막지 않고 재생성 산출물을 그대로 반환한다(최소
    폐쇄안, 모듈 docstring "멱등 재발급" 참조) — 대신 감사 로그를 남긴다.
    """
    assert record.plan_request is not None  # noqa: S101 -- artifact_kind=="pair" 불변식이 보장
    stored_request = MissionPlanRequest.model_validate(record.plan_request)
    schema_version = record.contract.get("schemaVersion", "1.2")
    if schema_version not in ("1.2", "1.3"):
        raise ValueError(f"재생성할 수 없는 Mission Contract 버전: {schema_version!r}")
    issuance = record.contract.get("issuance")
    issuer_id = issuance.get("issuerId") if isinstance(issuance, dict) else None
    site_sequence = issuance.get("siteSequence") if isinstance(issuance, dict) else None
    result = build_mission_plan(
        stored_request,
        private_key=private_key,
        key_id=key_id,
        issued_at=record.issued_at,
        contract_schema_version=schema_version,
        issuer_id=issuer_id,
        site_sequence=site_sequence,
    )
    if result["kmzSha256"] != record.kmz_sha256:
        logger.warning(
            "mission_id=%s 짝 재생성 바이트가 원본과 다르다(결정성 가정 위반 의심) — "
            "재생성 산출물을 그대로 반환한다",
            record.mission_id,
        )
    return result


def _kmz_response(mission_id: str, kmz_bytes: bytes) -> Response:
    """KMZ 바이트 응답 — 헤더 조립을 한 곳에만 둔다(경로 4개가 같은 응답을 낸다)."""
    return Response(
        content=kmz_bytes,
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": f'attachment; filename="{mission_id}.kmz"'},
    )


def _stored_kmz(storage: EvidenceStorage | None, record: MissionRecord) -> bytes | None:
    """발급 시 보관해둔 KMZ 바이트 — 없거나 스토리지 장애면 ``None``.

    이 함수는 **예외를 올리지 않는다.** 호출부는 이미 재생성에 실패했거나 재생성
    바이트가 원본과 다른 상황이고, 여기서 또 예외가 나면 원인이 뒤바뀐 오류가
    운영자에게 간다 — 보관본이 없으면 원래의 409 로 떨어지는 게 정확하다.
    """
    if storage is None:
        return None
    try:
        key = build_mission_kmz_object_key(site_id=record.site_id, mission_id=record.mission_id)
    except ValueError:
        return None
    try:
        return storage.get_bytes(key)
    except EvidenceStorageError:
        logger.warning(
            "mission_id=%s 보관된 KMZ 를 읽지 못했다 — 재생성 결과로 판정한다",
            record.mission_id,
        )
        return None


def _persist_kmz(
    storage: EvidenceStorage | None, record: MissionRecord, result: dict[str, Any]
) -> None:
    """발급 KMZ 바이트를 보관한다 (risk kmz-regeneration-determinism-timebomb).

    **발급을 막지 않는다.** durable 기록(mission_store)은 이미 끝났고 계약은 유효하다
    — 보관 실패로 201 을 거부하면 스토리지 장애가 임무 발급 자체를 멈춘다. 대신
    error 로 남긴다: 이 실패는 "나중에 그 임무의 KMZ 다운로드가 재생성에만 의존하게
    됐다"는 뜻이고, 그 사실을 아무도 모르면 정책이 바뀐 뒤에야 409 로 드러난다.

    ``storage`` 가 ``None`` 인 조립(오브젝트 스토리지 없는 배포)에서는 아무것도 하지
    않는다 — 그 배포는 지금까지처럼 재생성에만 의존하고, 그 사실이 조립에서 명시된다.
    """
    if storage is None:
        return
    try:
        storage.put_bytes(
            build_mission_kmz_object_key(site_id=record.site_id, mission_id=record.mission_id),
            base64.b64decode(result["kmzBase64"]),
            content_type="application/vnd.google-earth.kmz",
        )
    except (EvidenceStorageError, ValueError) as exc:
        logger.error(
            "mission_id=%s KMZ 바이트 보관 실패(%s) — 발급 자체는 유효하지만 이 임무의 "
            "다운로드는 앞으로 재생성에만 의존한다(서버 정책이 바뀌면 409 가 된다)",
            record.mission_id,
            type(exc).__name__,
        )


# risk kmz-download-regeneration-cost: 읽기 권한(MISSIONS_READ, VIEWER 포함 5개
# role 전부)만으로 재조회마다 경로생성+Ed25519 서명이 무제한 반복된다. build_kmz
# 계열은 결정론적이므로(모듈 docstring) 같은 mission_id·같은 kmz_sha256 에 대한
# 재계산은 항상 같은 바이트다 — 캐시가 정확성을 해치지 않는다. TTL 은 정확성이
# 아니라 메모리 상한을 위한 것이다.
_KMZ_CACHE_TTL_S = 300.0
_KMZ_CACHE_MAX_ENTRIES = 256

# KMZ 다운로드는 사람(``MISSIONS_READ``, 아무 임무)과 Edge 장비
# (``EDGE_MISSION_KMZ_READ``, 자기 배정 임무만)가 **같은 라우트**로 쓴다. 이
# 의존성은 "권한 있음"까지만 보장한다 — 범위 좁히기(그 임무가 자기 것인가)는
# 핸들러가 하고, 불일치는 404 로 접는다(``require_permission_any`` docstring).
_KMZ_DOWNLOAD_PERMISSION = require_permission_any(
    Permission.MISSIONS_READ, Permission.EDGE_MISSION_KMZ_READ
)


def build_mission_plans_router(
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    site_lookup: Callable[[str, str], SiteLookupResult | None],
    kmz_storage: EvidenceStorage | None = None,
    writer_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    sequence_store: MissionIssuanceSequenceStore | None = None,
    acquisition_readiness: Callable[[str, str, datetime], tuple[bool, str]] | None = None,
    observation_work_order_store: ObservationWorkOrderStore | None = None,
    acquisition_coordination_store: AcquisitionCoordinationStore | None = None,
) -> APIRouter:
    if writer_version == "1.3" and (not issuer_id or sequence_store is None):
        raise ValueError("Mission Contract v1.3 writer는 issuer_id와 sequence_store가 필요하다")
    router = APIRouter(prefix="/v1/missions", tags=["missions"])
    # (kmzSha256, kmz_bytes, expires_at_monotonic) — mission_id 키, LRU 크기상한.
    kmz_cache: OrderedDict[str, tuple[str, bytes, float]] = OrderedDict()
    kmz_cache_lock = threading.Lock()

    def _resolve_work_order(
        request: MissionPlanRequest,
        principal: Principal,
        *,
        require_approved: bool,
        ensure_run: bool = True,
        now: datetime,
    ) -> ObservationWorkOrder | None:
        if request.work_order_id is None:
            return None
        if observation_work_order_store is None or acquisition_coordination_store is None:
            raise HTTPException(
                status_code=503,
                detail="WorkOrder Mission lineage coordinator가 조립되지 않았다",
            )
        order = observation_work_order_store.get(
            request.work_order_id, organization_id=principal.organization_id
        )
        if order is None:
            raise HTTPException(status_code=404, detail="관측 작업을 찾을 수 없다")
        if order.site_id != request.contract.site_id:
            raise HTTPException(
                status_code=422,
                detail="WORK_ORDER_SITE_MISMATCH — WorkOrder와 Mission의 Site가 다르다",
            )
        if require_approved and order.status is not ObservationWorkOrderStatus.APPROVED:
            raise HTTPException(
                status_code=409,
                detail="WORK_ORDER_NOT_APPROVED — 승인된 현재 회차에만 Mission을 발급한다",
            )
        if ensure_run:
            try:
                acquisition_coordination_store.ensure_run(
                    order, actor=principal.principal_id, now=now
                )
            except JournalSealedError as exc:
                raise HTTPException(status_code=503, detail="STORE_UNAVAILABLE") from exc
        return order

    def _link_work_order(
        request: MissionPlanRequest,
        principal: Principal,
        order: ObservationWorkOrder | None,
        *,
        now: datetime,
    ) -> None:
        if order is None:
            return
        assert observation_work_order_store is not None  # noqa: S101 -- resolver checked
        assert acquisition_coordination_store is not None  # noqa: S101 -- resolver checked
        try:
            existing_run = acquisition_coordination_store.run_for_mission(
                request.contract.mission_id,
                organization_id=principal.organization_id,
            )
            linked_run = existing_run or acquisition_coordination_store.link_mission(
                order,
                request.contract.mission_id,
                actor=principal.principal_id,
                now=now,
            )
            observation_work_order_store.link_mission(
                order.work_order_id,
                organization_id=principal.organization_id,
                cycle_number=linked_run.cycle_number,
                mission_id=request.contract.mission_id,
                mission_site_id=request.contract.site_id,
                actor=principal.principal_id,
                now=now,
                require_approved=False,
            )
        except JournalSealedError as exc:
            # Mission issuance is already durable. A retry with the same request
            # re-enters this reconciliation path instead of creating a new Mission.
            raise HTTPException(status_code=503, detail="STORE_UNAVAILABLE") from exc
        except AcquisitionCoordinationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (LookupError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/plans", status_code=201)
    def issue_mission_plan_recorded(
        request: MissionPlanRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> dict[str, Any]:
        """구역+임무타입 → KMZ+서명 계약 짝 발급·durable 기록 (ADR-KSI-007/ADR-KSI-008 §3).

        발급 레코드가 durable 기록되기 전에는 201 을 반환하지 않는다(고아 발급 금지)
        — site 미존재·siteFrame 불일치·mission_id 충돌은 서명·KMZ 생성 **전에**
        거부한다(SITE_FRAME_MISMATCH — 등록 좌표계와 어긋난 짝 발급 차단).

        같은 missionId 로 **동일 요청**(정규화 digest 일치)이 재도착하면 멱등
        200 으로 저장된 산출물을 재생성해 그대로 반환한다(모듈 docstring "멱등
        재발급" 참조) — 다른 요청이면 여전히 409 ``MISSION_ID_CONFLICT``.
        """
        plan_request_payload = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        reject_lone_surrogates(plan_request_payload)

        contract_request_payload = request.contract.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )
        request_digest = _request_digest(plan_request_payload)
        request_now = datetime.now(UTC)

        verdict = precheck_issuance(
            mission_store=mission_store,
            site_lookup=site_lookup,
            organization_id=principal.organization_id,
            site_id=request.contract.site_id,
            mission_id=request.contract.mission_id,
            mission_type=request.contract.mission_type,
            requested_site_frame=contract_request_payload["siteFrame"],
        )
        if verdict is MissionRecordVerdict.MISSION_ID_CONFLICT:
            existing = mission_store.get(request.contract.mission_id)
            if (
                existing is not None
                and existing.artifact_kind == "pair"
                and existing.plan_request_digest == request_digest
            ):
                existing_run = (
                    acquisition_coordination_store.run_for_mission(
                        request.contract.mission_id,
                        organization_id=principal.organization_id,
                    )
                    if acquisition_coordination_store is not None
                    else None
                )
                order = _resolve_work_order(
                    request,
                    principal,
                    require_approved=False,
                    ensure_run=existing_run is None,
                    now=request_now,
                )
                try:
                    regenerated = _regenerate_pair_artifact(
                        existing, private_key=private_key, key_id=key_id
                    )
                except (ValidationError, RouteGenerationError, KmzBuildError) as exc:
                    # 저장된 요청이 **현재** 규칙을 더는 만족하지 않는 경우다
                    # (독립 재검토 P2-7). 예: 규제 고도 상한이 낮아진 뒤의 옛
                    # 봉투, 또는 촬영 간격 필수화 이전에 발급된 매핑 요청. 그대로
                    # 두면 재시도가 500 이 되어 "서버 버그"처럼 보인다 — 실제로는
                    # 정책이 바뀐 것이므로 그 사실을 typed 로 알린다.
                    #
                    # error 레벨(risk kmz-regeneration-determinism-timebomb): 아래
                    # sha256 불일치 분기와 같은 근본원인 클래스다 — 서버 상수·경로
                    # 생성기 정책이 바뀌면 그 이전 발급분 재발급(멱등 재시도)이
                    # 전량 이 분기로 떨어진다. phase-2 Spatial Refresh Backbone(
                    # captureIntervalM 필수화)이 이 경로를 실제로 발화시켰다
                    # (PHASE_REGISTRY.yaml phase-2 residual_risks).
                    logger.error(
                        "mission_id=%s 짝 재생성이 현재 정책에서 실패(%s) — 발급 당시 "
                        "이후 서버 상수·경로생성기 정책이 바뀌었을 가능성. 같은 정책 "
                        "변경 전에 발급된 다른 레코드도 동시에 영향받을 수 있다",
                        existing.mission_id,
                        type(exc).__name__,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "이미 기록된 임무지만 현재 정책으로는 산출물을 다시 만들 수 "
                            f"없다(발급 당시 규칙과 달라졌다): {exc}. 새 missionId 로 "
                            "발급하라"
                        ),
                    ) from exc
                _link_work_order(request, principal, order, now=request_now)
                response.status_code = 200
                return regenerated
        if verdict is not None:
            raise_for_mission_record_verdict(verdict)

        # issued_at 을 한 번만 뽑아 계약 서명(validity.notBefore)과 레코드에 동일하게
        # 쓴다 — 둘이 별개 datetime.now() 호출이면 멱등 재발급(_regenerate_pair_artifact
        # 가 record.issued_at 을 재서명 시각으로 재사용)이 원본과 다른 바이트를 낸다.
        issued_at = request_now
        order = _resolve_work_order(
            request,
            principal,
            require_approved=True,
            now=issued_at,
        )
        if acquisition_readiness is not None:
            ready, detail = acquisition_readiness(
                request.contract.site_id, principal.organization_id, issued_at
            )
            if not ready:
                raise HTTPException(
                    status_code=409,
                    detail=f"ACQUISITION_NOT_READY — {detail}",
                )
        site_sequence: int | None = None
        if writer_version == "1.3":
            assert issuer_id is not None  # noqa: S101 -- 조립 시 검증
            assert sequence_store is not None  # noqa: S101 -- 조립 시 검증
            try:
                site_sequence = sequence_store.reserve(
                    issuer_id=issuer_id,
                    site_id=request.contract.site_id,
                    reserved_at=issued_at,
                )
            except JournalSealedError as exc:
                raise HTTPException(status_code=503, detail="STORE_UNAVAILABLE") from exc
        try:
            result = build_mission_plan(
                request,
                private_key=private_key,
                key_id=key_id,
                issued_at=issued_at,
                contract_schema_version=writer_version,
                issuer_id=issuer_id,
                site_sequence=site_sequence,
            )
        except (RouteGenerationError, KmzBuildError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = MissionRecord(
            mission_id=request.contract.mission_id,
            site_id=request.contract.site_id,
            mission_type=request.contract.mission_type.value,
            artifact_kind="pair",
            contract=result["contract"],
            kmz_sha256=result["kmzSha256"],
            route_pattern=result["routePattern"],
            waypoint_count=result["waypointCount"],
            planned_coverage_ratio=result["plannedCoverageRatio"],
            issued_at=issued_at,
            issued_by=principal.principal_id,
            organization_id=principal.organization_id,
            plan_request=plan_request_payload,
            plan_request_digest=request_digest,
            assigned_device_id=request.contract.assigned_device_id,
        )
        raise_for_mission_record_verdict(mission_store.record_issuance(record))
        _persist_kmz(kmz_storage, record, result)
        _link_work_order(request, principal, order, now=issued_at)
        return result

    def _resolve_kmz_bytes(record: MissionRecord) -> bytes:
        """ "발급 당시 그 파일"을 얻는 **유일한** 해석 경로 — 4단 폴백 전부.

        캐시 → 재생성 → 재생성 sha256 대조 → 발급 시 보관본. 이 순서와 그 안의
        판정들이 이 저장소에서 "KMZ 다운로드"의 정의다. 장비 경로(Edge companion)
        를 열면서 두 번째 해석 경로를 만들지 않는 이유가 여기 있다 — 폴백 하나가
        한쪽에만 있으면 같은 임무의 KMZ 가 사람이 받을 때와 기체가 받을 때 서로
        다른 바이트가 되거나, 한쪽만 영구 409 가 된다.

        경로별 대칭 인가(자기 것인가)는 호출부가 이미 끝냈다고 가정한다 — 이
        함수는 "무엇을 내려줄 것인가"만 답한다.
        """
        cache_key = record.mission_id
        now = time.monotonic()
        with kmz_cache_lock:
            cached = kmz_cache.get(cache_key)
            if cached is not None:
                cached_sha, cached_bytes, expires_at = cached
                if expires_at > now and cached_sha == record.kmz_sha256:
                    kmz_cache.move_to_end(cache_key)
                    return cached_bytes
                del kmz_cache[cache_key]
        try:
            regenerated = _regenerate_pair_artifact(record, private_key=private_key, key_id=key_id)
        except (ValidationError, RouteGenerationError, KmzBuildError) as exc:
            # error 레벨(risk kmz-regeneration-determinism-timebomb) — 아래
            # sha256 불일치 분기와 같은 근본원인 클래스: 정책이 바뀐 뒤 이전
            # 발급분의 다운로드가 전량 이 분기로 떨어질 수 있다.
            logger.error(
                "mission_id=%s KMZ 재생성이 현재 정책에서 실패(%s) — 발급 당시 이후 "
                "서버 상수·경로생성기 정책이 바뀌었을 가능성. 같은 정책 변경 전에 "
                "발급된 다른 레코드도 동시에 영향받을 수 있다",
                record.mission_id,
                type(exc).__name__,
            )
            stored = _stored_kmz(kmz_storage, record)
            if stored is not None:
                # 발급 시점의 **그 바이트**가 보관돼 있으면 정책 변경과 무관하게
                # 그걸 내려준다 — 이 엔드포인트가 약속하는 것은 "발급 당시 그
                # 파일"이고, 재생성은 그걸 얻는 수단이었지 목적이 아니다.
                logger.info(
                    "mission_id=%s 재생성 실패했지만 발급 시 보관된 KMZ 로 응답한다",
                    record.mission_id,
                )
                return stored
            raise HTTPException(
                status_code=409,
                detail=(
                    "이미 기록된 임무지만 현재 정책으로는 KMZ 를 다시 만들 수 "
                    f"없다(발급 당시 규칙과 달라졌다): {exc}. 발급 시 바이트도 "
                    "보관돼 있지 않다"
                ),
            ) from exc
        if regenerated["kmzSha256"] != record.kmz_sha256:
            # _regenerate_pair_artifact 는 이 상황(모듈 docstring "결정성 가정
            # 위반 의심")을 이미 warning 으로 로그하고 재생성 산출물을 그대로
            # 돌려준다 — POST /plans 재발급 경로는 그걸로 충분하다(요청자가 방금
            # 보낸 요청의 재시도이므로 최신 산출물이 낫다). 하지만 이 다운로드는
            # "발급 당시 그 파일"을 약속하는 경로라 기준이 다르다 — 다른 바이트를
            # 같은 파일이라고 내려주지 않는다.
            #
            # error 레벨로 별도 기록하는 이유(risk kmz-regeneration-determinism-
            # timebomb): 이 분기는 서버 상수 한 줄이 바뀌면 그 이전 발급분 전량이
            # 영구 409 가 되는 지점이다. _regenerate_pair_artifact 의 warning 은
            # "달라졌다"만 남기고 이 라우트가 실제로 다운로드를 막았다는 사실 자체는
            # 기록하지 않았다 — 운영자가 이 로그 없이는 대량 409 발생을 알 방법이
            # 없었다.
            stored = _stored_kmz(kmz_storage, record)
            if stored is not None:
                logger.info(
                    "mission_id=%s 재생성 바이트가 원본과 다르지만(재생성 sha256=%s, "
                    "기록 %s) 발급 시 보관된 KMZ 로 응답한다",
                    record.mission_id,
                    regenerated["kmzSha256"],
                    record.kmz_sha256,
                )
                return stored
            logger.error(
                "mission_id=%s KMZ 다운로드가 결정성 위반으로 영구 거부됐다 "
                "(재생성 sha256=%s, 기록된 kmzSha256=%s) — 이 발급 시점 이후 서버 "
                "상수·경로생성기가 바뀌었을 가능성. 같은 정책 변경 전에 발급된 다른 "
                "레코드도 동시에 영향받을 수 있다. 발급 시 바이트가 보관돼 있었다면 "
                "이 거부는 일어나지 않았다(오브젝트 스토리지 없는 조립)",
                record.mission_id,
                regenerated["kmzSha256"],
                record.kmz_sha256,
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "재생성한 KMZ 의 sha256 이 발급 당시 기록된 kmzSha256 과 다르다"
                    "(하류 로직 변경으로 원본 파일을 더 이상 재현할 수 없다) — 다른"
                    " 파일을 발급된 파일로 잘못 내려주지 않기 위해 거부한다"
                ),
            )
        kmz_bytes = base64.b64decode(regenerated["kmzBase64"])
        with kmz_cache_lock:
            kmz_cache[cache_key] = (
                regenerated["kmzSha256"],
                kmz_bytes,
                time.monotonic() + _KMZ_CACHE_TTL_S,
            )
            kmz_cache.move_to_end(cache_key)
            while len(kmz_cache) > _KMZ_CACHE_MAX_ENTRIES:
                kmz_cache.popitem(last=False)
        return kmz_bytes

    @router.get("/{mission_id}/kmz")
    def download_mission_kmz(
        mission_id: str,
        principal: Principal = Depends(_KMZ_DOWNLOAD_PERMISSION),  # noqa: B008
    ) -> Response:
        """저장된 ``plan_request`` 로 KMZ 를 재생성해 바이트로 내려준다.

        발급 응답의 ``kmzBase64`` 는 그 순간 한 번만 있고 어디에도 저장되지
        않는다(모듈 docstring "멱등 재발급" — 바이트 자체는 journal 에 없다) —
        운영자가 위저드를 끝까지 눌러도 손에 파일이 없는 막다른 길이 되는 지점이
        이 엔드포인트다. 해석 경로 전부(:func:`_resolve_kmz_bytes`)는 사람과 기체가
        **같은 것 하나**를 쓴다.

        ## 두 종류의 주체가 같은 표면을 쓴다

        사람(``MISSIONS_READ``)은 아무 임무의 KMZ 를 받는다. 장비
        (``EDGE_MISSION_KMZ_READ``)는 **자기에게 배정된** 임무 하나만 받는다 —
        ``assigned_device_id`` 불일치는 403 이 아니라 **404** 다: 403 은 "그
        missionId 는 존재하지만 네 것이 아니다"를 알려주는 존재 오라클이고, 장비
        토큰 하나로 임무 식별자 공간을 훑을 수 있게 된다(edge_dispatch.py 의
        cross-device event 를 일반 404 로 접는 것과 같은 관습).

        별도의 ``/v1/edge-sync/...`` KMZ 라우터를 만들지 않는 이유: 캐시·서명키·
        보관 스토리지가 이 클로저 하나에 있어 두 번 배선하면 재생성 비용이 두 배가
        되고, 폴백 4단이 두 곳에서 갈릴 수 있다.
        """
        if not is_path_safe_identifier(mission_id):
            # 발급 경로가 이미 같은 검사를 통과한 값만 저장소 키로 쓰므로 정상
            # 경로에서는 도달하지 않는다. 그래도 여기서 한 번 더 막는 이유는 이
            # 값이 아래에서 Content-Disposition 헤더로 조립되기 때문이다 —
            # 원장이 손대어진 경우까지 헤더 조립 전에 끊는다(방어 심층).
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        record = mission_store.get(mission_id)
        if record is None:
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        if principal.kind is PrincipalKind.EDGE_DEVICE and (
            principal.device_id is None or record.assigned_device_id != principal.device_id
        ):
            # 미배정(assigned_device_id=None) 임무도 여기서 막힌다 — 배정 없는
            # 임무를 "아무 장비나 가져갈 수 있는 임무"로 읽지 않는 것은
            # EdgeDispatchStore.next_for_device 와 같은 판단(INV-011/012)이다.
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        if record.artifact_kind != "pair" or record.plan_request is None:
            raise HTTPException(
                status_code=404,
                detail="이 임무 레코드는 KMZ 산출물이 없다(계약 단독 발급)",
            )
        return _kmz_response(mission_id, _resolve_kmz_bytes(record))

    return router


def mount_mission_plans(
    app: FastAPI,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    site_lookup: Callable[[str, str], SiteLookupResult | None],
    kmz_storage: EvidenceStorage | None = None,
    writer_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    sequence_store: MissionIssuanceSequenceStore | None = None,
    acquisition_readiness: Callable[[str, str, datetime], tuple[bool, str]] | None = None,
    observation_work_order_store: ObservationWorkOrderStore | None = None,
    acquisition_coordination_store: AcquisitionCoordinationStore | None = None,
) -> None:
    """앱에 임무 계획(짝 발급) 라우터를 장착한다.

    ``kmz_storage`` 가 주어지면 발급 시 KMZ 바이트를 보관하고, 다운로드가 재생성에
    실패하거나 재생성 바이트가 원본과 다를 때 그 보관본을 내려준다 — 서버 안전상수
    한 줄이 바뀌면 그 이전 발급분 전량이 영구 409 가 되던 경로를 닫는다(risk
    kmz-regeneration-determinism-timebomb, phase-2 에서 실제로 발화). 없으면
    지금까지처럼 재생성에만 의존한다 — 그 조립의 한계가 조립에서 드러난다.

    인증·site 등록 대조(존재+siteFrame 일치+임무타입×현장상태 게이트, INV-052)·
    durable 기록이 강제되는 경로 하나뿐이다(ADR-KSI-008 §3 — 무인증·미기록
    발급이 가능한 조립은 성립하지 않는다. mission_issuance.py 모듈 docstring과
    동형).
    """
    app.include_router(
        build_mission_plans_router(
            private_key=private_key,
            key_id=key_id,
            mission_store=mission_store,
            site_lookup=site_lookup,
            kmz_storage=kmz_storage,
            writer_version=writer_version,
            issuer_id=issuer_id,
            sequence_store=sequence_store,
            acquisition_readiness=acquisition_readiness,
            observation_work_order_store=observation_work_order_store,
            acquisition_coordination_store=acquisition_coordination_store,
        )
    )
