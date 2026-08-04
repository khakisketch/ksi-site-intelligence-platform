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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import MissionType
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from ksi_mission_planning import (
    AreaOfInterest,
    DroneProfile,
    KmzBuildError,
    RouteGenerationError,
    WaylineMissionConfig,
    build_kmz,
    lawnmower_route,
    perimeter_route,
)
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.mission_issuance import MissionIssuanceRequest, issue_mission_contract
from ksi_core.mission_records import (
    MissionRecord,
    MissionRecordVerdict,
    MissionStore,
    precheck_issuance,
    raise_for_mission_record_verdict,
    reject_lone_surrogates,
)

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


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class RouteParams(_CamelModel):
    """경로 생성 파라미터 — 고도는 계약 FlightEnvelope 로 생성기가 재게이트한다.

    고도의 수직기준은 이륙점 상대(relativeToStartPoint) — 2026-07-29 대표자 확정,
    계약 스키마 flightEnvelope.altitudeReference 로 명문화.
    ``sweep_direction_deg`` 는 수학 규약(동=0·반시계) — 나침반 방위가 아니다.
    """

    altitude_m: float
    spacing_m: float | None = Field(default=None, description="lawnmower 전용 스캔선 간격(m)")
    capture_interval_m: float | None = Field(
        default=None,
        description=(
            "lawnmower 전용 진행방향 촬영 간격(m) — 스캔선 위 촬영 지점 간격. "
            "없으면 스캔선당 사진이 양 끝 2장뿐이라 전방 중첩이 0 이 되어 "
            "정사영상·3D 재구성이 성립하지 않는다"
        ),
    )
    sweep_direction_deg: float | None = None


class DroneProfileParams(_CamelModel):
    drone_enum_value: int
    drone_sub_enum_value: int
    payload_enum_value: int
    payload_position_index: int = 0


class WaylineParams(_CamelModel):
    auto_flight_speed_ms: float
    takeoff_security_height_m: float
    global_transitional_speed_ms: float


class MissionPlanRequest(_CamelModel):
    """계약 발급 요청 + 구역 + 경로/기체 파라미터 — 한 요청이 두 산출물의 단일 근원."""

    contract: MissionIssuanceRequest
    aoi: AreaOfInterest
    route: RouteParams
    drone: DroneProfileParams
    wayline: WaylineParams


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


def build_mission_plan(
    request: MissionPlanRequest,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """경로 생성 → 서명 계약 → 짝 식별자 동봉 KMZ 발급. 실패는 typed 예외로 전파된다.

    ``issued_at``: 멱등 재발급(:func:`_regenerate_pair_artifact`)이 원 레코드의
    ``issued_at`` 을 그대로 넘겨, 재서명된 계약의 ``validity`` 창이 원본과
    달라지지 않게 한다(생략 시 :func:`issue_mission_contract` 가 현재 시각을 쓴다).
    """
    mission_type = request.contract.mission_type
    envelope = request.contract.flight_envelope

    _require_wayline_takeoff_height_compatible(
        request.wayline.takeoff_security_height_m, envelope
    )

    route: list[RouteWaypoint]
    coverage_ratio: float | None = None
    if mission_type in _LAWNMOWER_TYPES:
        if request.route.spacing_m is None:
            raise RouteGenerationError(
                f"{mission_type.value} 는 lawnmower 패턴 — route.spacingM 이 필요하다"
            )
        if request.route.capture_interval_m is None:
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
            spacing_m=request.route.spacing_m,
            altitude_m=request.route.altitude_m,
            envelope=envelope,
            sweep_direction_deg=request.route.sweep_direction_deg,
            capture_interval_m=request.route.capture_interval_m,
        )
        route = lawnmower_result.waypoints
        coverage_ratio = lawnmower_result.coverage_ratio
        pattern = "lawnmower"
        # 같은 요청이 계약에 서명해 넣는 커버 약속(accessibleGeneralCoverage,
        # 최대 1.0)과 실측 커버를 대조한다 — 생성기 고정 하한(0.95)만 보면
        # "일반영역 100% 를 약속한 서명 계약 + 실측 0.9x KMZ" 어긋난 쌍이 조용히
        # 발급된다(재검증 P2, 이륙고도 게이트와 동일 클래스). 1e-9 는 정확 계산의
        # 부동소수 잔차 허용치다.
        if coverage_ratio + 1e-9 < request.contract.accessible_general_coverage:
            raise RouteGenerationError(
                "COVERAGE_BELOW_CONTRACT_PROMISE — 실측 커버 비율 "
                f"{coverage_ratio:.4f} 가 계약이 약속하는 accessibleGeneralCoverage "
                f"{request.contract.accessible_general_coverage} 미만이다. spacing·"
                "sweep 을 조정하거나 약속 값을 실측 이하로 낮춰 발급하라"
            )
    elif mission_type in _PERIMETER_TYPES:
        route = perimeter_route(
            request.aoi, altitude_m=request.route.altitude_m, envelope=envelope
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
        request.contract, private_key=private_key, key_id=key_id, issued_at=issued_at
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
            payload_position_index=request.drone.payload_position_index,
        ),
        config=WaylineMissionConfig(
            auto_flight_speed_ms=request.wayline.auto_flight_speed_ms,
            takeoff_security_height_m=request.wayline.takeoff_security_height_m,
            global_transitional_speed_ms=request.wayline.global_transitional_speed_ms,
        ),
        # 매핑 계열은 웨이포인트별 nadir 촬영이 기본(2026-07-29 대표자 승인) —
        # 격자만 날고 사진 0장인 산출물(자율 재검토 F9)을 만들지 않는다.
        capture_at_waypoints=(pattern == "lawnmower"),
        pair_manifest=pair_manifest,
    )

    return {
        "contract": contract_payload,
        "kmzBase64": base64.b64encode(kmz).decode("ascii"),
        "kmzSha256": hashlib.sha256(kmz).hexdigest(),
        "routePattern": pattern,
        "waypointCount": len(route),
        "coverageRatio": coverage_ratio,
    }


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
    result = build_mission_plan(
        stored_request, private_key=private_key, key_id=key_id, issued_at=record.issued_at
    )
    if result["kmzSha256"] != record.kmz_sha256:
        logger.warning(
            "mission_id=%s 짝 재생성 바이트가 원본과 다르다(결정성 가정 위반 의심) — "
            "재생성 산출물을 그대로 반환한다",
            record.mission_id,
        )
    return result


def build_mission_plans_router(
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    site_frame_lookup: Callable[[str], dict[str, Any] | None],
) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

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
        contract_request_payload = request.contract.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )
        reject_lone_surrogates(contract_request_payload)

        plan_request_payload = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        request_digest = _request_digest(plan_request_payload)

        verdict = precheck_issuance(
            mission_store=mission_store,
            site_frame_lookup=site_frame_lookup,
            site_id=request.contract.site_id,
            mission_id=request.contract.mission_id,
            requested_site_frame=contract_request_payload["siteFrame"],
        )
        if verdict is MissionRecordVerdict.MISSION_ID_CONFLICT:
            existing = mission_store.get(request.contract.mission_id)
            if (
                existing is not None
                and existing.artifact_kind == "pair"
                and existing.plan_request_digest == request_digest
            ):
                response.status_code = 200
                return _regenerate_pair_artifact(
                    existing, private_key=private_key, key_id=key_id
                )
        if verdict is not None:
            raise_for_mission_record_verdict(verdict)

        # issued_at 을 한 번만 뽑아 계약 서명(validity.notBefore)과 레코드에 동일하게
        # 쓴다 — 둘이 별개 datetime.now() 호출이면 멱등 재발급(_regenerate_pair_artifact
        # 가 record.issued_at 을 재서명 시각으로 재사용)이 원본과 다른 바이트를 낸다.
        issued_at = datetime.now(UTC)
        try:
            result = build_mission_plan(
                request, private_key=private_key, key_id=key_id, issued_at=issued_at
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
            coverage_ratio=result["coverageRatio"],
            issued_at=issued_at,
            issued_by=principal.principal_id,
            plan_request=plan_request_payload,
            plan_request_digest=request_digest,
        )
        raise_for_mission_record_verdict(mission_store.record_issuance(record))
        return result

    return router


def mount_mission_plans(
    app: FastAPI,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    site_frame_lookup: Callable[[str], dict[str, Any] | None],
) -> None:
    """앱에 임무 계획(짝 발급) 라우터를 장착한다.

    인증·site 등록 대조(존재+siteFrame 일치)·durable 기록이 강제되는 경로
    하나뿐이다(ADR-KSI-008 §3 — 무인증·미기록 발급이 가능한 조립은 성립하지
    않는다. mission_issuance.py 모듈 docstring과 동형).
    """
    app.include_router(
        build_mission_plans_router(
            private_key=private_key,
            key_id=key_id,
            mission_store=mission_store,
            site_frame_lookup=site_frame_lookup,
        )
    )
