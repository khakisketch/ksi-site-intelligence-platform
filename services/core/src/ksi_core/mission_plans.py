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
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from ksi_domain.enums import MissionType
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

from ksi_core.mission_issuance import MissionIssuanceRequest, issue_mission_contract

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import FastAPI
    from ksi_mission_planning import RouteWaypoint

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

    고도의 수직기준은 이륙점 상대(relativeToStartPoint) 잠정 규약이다 — 원장 risk
    ``route-altitude-vertical-reference`` (대표자 확정 대기) 참조.
    ``sweep_direction_deg`` 는 수학 규약(동=0·반시계) — 나침반 방위가 아니다.
    """

    altitude_m: float
    spacing_m: float | None = Field(default=None, description="lawnmower 전용 스캔선 간격(m)")
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


def build_mission_plan(
    request: MissionPlanRequest, *, private_key: Ed25519PrivateKey, key_id: str
) -> dict[str, Any]:
    """경로 생성 → KMZ + 서명 계약 짝 발급. 실패는 typed 예외로 전파된다."""
    mission_type = request.contract.mission_type
    envelope = request.contract.flight_envelope

    route: list[RouteWaypoint]
    if mission_type in _LAWNMOWER_TYPES:
        if request.route.spacing_m is None:
            raise RouteGenerationError(
                f"{mission_type.value} 는 lawnmower 패턴 — route.spacingM 이 필요하다"
            )
        route = lawnmower_route(
            request.aoi,
            spacing_m=request.route.spacing_m,
            altitude_m=request.route.altitude_m,
            envelope=envelope,
            sweep_direction_deg=request.route.sweep_direction_deg,
        )
        pattern = "lawnmower"
    elif mission_type in _PERIMETER_TYPES:
        route = perimeter_route(
            request.aoi, altitude_m=request.route.altitude_m, envelope=envelope
        )
        pattern = "perimeter"
    else:
        raise RouteGenerationError(
            f"{mission_type.value} 경로 패턴은 아직 미지원이다 — 조용한 퇴화 대신 거부한다"
        )

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
    )
    contract = issue_mission_contract(request.contract, private_key=private_key, key_id=key_id)

    return {
        "contract": contract.model_dump(by_alias=True, mode="json", exclude_none=True),
        "kmzBase64": base64.b64encode(kmz).decode("ascii"),
        "routePattern": pattern,
        "waypointCount": len(route),
    }


def build_mission_plans_router(*, private_key: Ed25519PrivateKey, key_id: str) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post("/plans", status_code=201)
    def issue_mission_plan(request: MissionPlanRequest) -> dict[str, Any]:
        """구역+임무타입 → KMZ(기체) + 서명 계약(Manifold) 짝 발급 (ADR-KSI-007)."""
        try:
            return build_mission_plan(request, private_key=private_key, key_id=key_id)
        except (RouteGenerationError, KmzBuildError) as exc:
            # 경로·산출물 생성 실패는 입력 문제의 typed 실패다 — 422 로 응답한다.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


def mount_mission_plans(app: FastAPI, *, private_key: Ed25519PrivateKey, key_id: str) -> None:
    """앱에 임무 계획(짝 발급) 라우터를 장착한다."""
    app.include_router(build_mission_plans_router(private_key=private_key, key_id=key_id))
