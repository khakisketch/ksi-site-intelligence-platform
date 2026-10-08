"""지형추종 비행고도 계획 — 순수 함수 (ADR-KSI-019 G6, AOL-3 Unit 1).

## 왜 순수 함수이고 무엇을 모르는가

``reobservation.py`` 와 같은 이유로 이 패키지에 산다 — 판정 규칙은 Core 의
저장소·HTTP 표면과 무관하다. 게다가 여기는 **구조적으로 더 강하게** 그렇다:
``tests/contract/test_anti_circularity_gate.py`` 가 이 패키지 전체에서
Core 의 재구성 작업 원장·공간모델 판정·원본/파생 산출물 계보·포인트 구름
데이터를 가리키는 모듈 경로를 금지한다(ADR-KSI-019 D3 반순환 불변식 — 정확한
금지 문자열은 그 시험 파일 자체가 SSOT 다. 여기서 그 문자열을 그대로 적으면
이 docstring 이 스캔에 걸려 시험이 실패한다). 그래서 이 모듈은 "현장에
DTM 이 있는가"를 절대 스스로 묻지 않는다 — 호출자가 이미 읽어온 표고값
(:class:`WaypointTerrainSample`)만 받는다.

## 무엇을 하지 않는가

실제 비행 명령·KMZ 발급과 이어지지 않는다(``wpml.py`` 는 지금 웨이포인트마다
다른 고도를 거부하도록 이미 짜여 있다 — 그 파일은 이 계획의 범위 밖이다).
장애물 회피·동적 재계획도 아니다 — 이 계층의 출력은 사전 계획 데이터일 뿐이다.

> **2026-08-15 실측 정정.** 위 "wpml.py 가 거부한다"는 여전히 사실이지만, 그
> 거부의 *근거*로 적혀 있던 "per-point 높이는 ellipsoidHeight 가 필요한데 계산할
> 수 없다"는 **실행 파일에는 해당하지 않는다.** DJI 공식 샘플 KMZ
> (``edge/third_party/psdk/samples/.../waypoint_v3/waypoint_file/``)를 풀어보면
> 실제 실행 파일 ``waylines.wpml`` 에는 ``useGlobalHeight`` 도 ``ellipsoidHeight``
> 도 **없고** 웨이포인트마다 ``executeHeight`` 하나만 있다(그 두 태그는 편집용
> ``template.kml`` 쪽 개념이다). 즉 지형추종을 실행 파일로 내보내는 데 필요한 것은
> 균일고도 제약을 푸는 것뿐이고 지오이드는 관여하지 않는다. 배선은 FIELD-3.

## 고도변화율을 왜 "수평거리 대비 비율"로 표현하는가

이 저장소 어디에도 상승·하강률(m/s) 제약이 없고, 이 계층은 속도 데이터를 갖지
않는다(``WaylineParams.autoFlightSpeedMs`` 는 수평 속도다). 시간 기반 제약을
흉내 내려면 속도 가정을 지어내야 하므로, 대신 기하학적으로 검증 가능한 값
(수평거리 대비 고도변화 비율)을 쓴다 — ADR-KSI-011 D3 의 간격 상한과 같은 지위의
**정책값**이다(물리 증명이 아니라 보수적 시작점).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_geo_core.frames import great_circle_distance_m

from ksi_mission_planning.geometry import GeoPoint

if TYPE_CHECKING:
    from ksi_mission_contracts.models import FlightEnvelope

#: 이 계산기가 다루는 유일한 수직기준. ``FlightEnvelope.altitude_reference`` 와
#: WPML ``executeHeightMode`` 가 같은 값으로 고정돼 있다(ADR-KSI-011 D1, INV-020).
_EXPECTED_ALTITUDE_REFERENCE = "relativeToStartPoint"

#: 이 값 이하의 수평거리는 "같은 지점"으로 취급한다(``geometry.py`` 의 부동소수
#: 잡음 임계값과 동일). 이 이하에서 고도변화율은 수평거리로 나눌 수 없으므로
#: 비율이 아니라 무한대(=자동 위반)로 판정한다 — 조용히 건너뛰지 않는다.
_HORIZONTAL_EPSILON_M = 1e-6


class TerrainReferenceMismatch(ValueError):
    """봉투가 이 계산기와 다른 수직기준을 선언했다 — typed 실패(계산하지 않는다)."""


class AltitudeSegmentStatus(StrEnum):
    """세그먼트 1개(웨이포인트 1개)의 판정 — 네 가지뿐이다."""

    OK = "OK"
    #: 이 지점의 지형고도를 모른다(보간·추정하지 않는다).
    TERRAIN_DATA_MISSING = "TERRAIN_DATA_MISSING"
    #: 계산된 고도가 비행 봉투 [min,max] 밖 — 조용히 잘라내지 않고 거부한다.
    ENVELOPE_VIOLATION = "ENVELOPE_VIOLATION"
    #: 이전 지점 대비 고도변화가 수평거리 대비 상한을 넘는다.
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class WaypointTerrainSample:
    """웨이포인트 1개 + 이미 읽어온 표고값 — 이 모듈은 이 값을 어떻게 구했는지 모른다."""

    waypoint: GeoPoint
    #: DTM 표고(m). 그 지점을 몰라서 못 구했으면 None(0 이나 이웃값으로 채우지 않는다).
    terrain_elevation_m: float | None
    #: DSM 표고(m, 선택) — 있으면 여유값(clearance) 계산에 쓴다.
    surface_elevation_m: float | None = None


@dataclass(frozen=True, slots=True)
class WaypointAltitudePlan:
    """웨이포인트 1개의 계산 결과 — 값과 판정 근거를 함께 들고 다닌다.

    **높이 값이 두 개인 이유**(2026-08-15 결함 수정): 이 계층에는 수직기준이 두
    개 흐른다. DTM/DSM 표고는 **절대**(해당 산출물의 수직기준)이고, 기체가 받는
    WPML ``executeHeight`` 는 **이륙점 상대**(``executeHeightMode=relativeToStartPoint``,
    ``FlightEnvelope.altitude_reference`` 도 같은 값으로 고정 — ADR-KSI-011 D1).
    이전 구현은 절대표고 하나만 내고 그것을 비행 봉투와 직접 비교했다 — 두 기준을
    섞은 비교였고, 높은 현장에서는 조용히 통과하고(실제 지상고가 몇 배가 된다)
    표고 120m 이상 현장에서는 합법적인 30m 비행조차 영원히 거부했다.
    """

    waypoint: GeoPoint
    terrain_elevation_m: float | None
    #: **이륙점 상대** 높이 — WPML ``executeHeight`` 에 그대로 실리는 값이고,
    #: 비행 봉투 대조도 이 값으로 한다. status 가 OK 일 때만 값이 있다.
    commanded_height_m: float | None
    #: 같은 수직기준의 **절대** 표고 — DSM 여유값처럼 절대 도메인 계산에만 쓴다.
    #: 이 값을 기체 명령으로 쓰면 안 된다.
    absolute_elevation_m: float | None
    #: absolute_elevation_m - surface_elevation_m. DSM 이 없으면 None.
    clearance_m: float | None
    status: AltitudeSegmentStatus
    #: 사람이 읽는 근거 문장 — 실패도 성공도 이유 없이 나오지 않는다.
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainAltitudeProfile:
    """경로 전체의 계산 결과."""

    segments: tuple[WaypointAltitudePlan, ...]
    #: 이 표고값들이 어느 공간모델/작업물에서 왔는지 — 계산에 관여하지 않고 통과만 한다.
    provenance: str
    #: 전 세그먼트가 OK 일 때만 참 — 호출자가 즉시 판단할 수 있게.
    all_ok: bool


def compute_altitude_profile(
    *,
    samples: Sequence[WaypointTerrainSample],
    takeoff_terrain_elevation_m: float,
    target_agl_m: float,
    safety_margin_m: float,
    max_altitude_change_ratio: float,
    envelope: FlightEnvelope,
    provenance: str,
) -> TerrainAltitudeProfile:
    """경로의 각 지점에서 안전한 지형추종 고도를 계산한다 — 순수 함수.

    Args:
        takeoff_terrain_elevation_m: **이륙 지점의 지형 표고**(samples 와 같은 DTM·
            같은 수직기준). 기체 명령이 이륙점 상대이므로 이 기준점 없이는 명령값을
            만들 수 없다 — 호출자가 임의로 0 을 넣으면 안 되고, 모르면 계획을
            내지 않는 것이 맞다.

            **지오이드는 필요 없다.** 명령값이 두 표고의 *차이*라서 두 값이 같은
            수직기준이기만 하면 상수항이 소거된다(``docs/geo/GEOID_ACQUISITION.md``
            의 정표고 변환은 설계 대비 비교용이고 이 계산의 전제가 아니다).

    Raises:
        ValueError: ``samples`` 가 비었거나, ``target_agl_m``/``max_altitude_change_ratio``
            가 양수가 아니거나, ``safety_margin_m`` 이 음수이거나,
            ``takeoff_terrain_elevation_m`` 이 유한하지 않을 때.
        TerrainReferenceMismatch: 봉투가 이륙점 상대가 아닌 수직기준을 선언했을 때 —
            그 경우 봉투 대조가 무의미해지므로 계산을 시도하지 않는다.
    """
    if not samples:
        raise ValueError("samples 는 비어 있을 수 없다 — 빈 경로의 고도 계획은 정의되지 않는다")
    if not math.isfinite(takeoff_terrain_elevation_m):
        raise ValueError(
            f"takeoff_terrain_elevation_m 은 finite 여야 한다: {takeoff_terrain_elevation_m}"
        )
    if target_agl_m <= 0.0:
        raise ValueError(f"target_agl_m 은 양수여야 한다: {target_agl_m}")
    if safety_margin_m < 0.0:
        raise ValueError(f"safety_margin_m 은 음수일 수 없다: {safety_margin_m}")
    if max_altitude_change_ratio <= 0.0:
        raise ValueError(
            f"max_altitude_change_ratio 는 양수여야 한다: {max_altitude_change_ratio}"
        )

    declared_reference = getattr(envelope, "altitude_reference", None)
    if declared_reference is not None and declared_reference != _EXPECTED_ALTITUDE_REFERENCE:
        raise TerrainReferenceMismatch(
            f"봉투의 수직기준이 {declared_reference!r} 다 — 이 계산기는 "
            f"{_EXPECTED_ALTITUDE_REFERENCE!r} 만 다룬다. 기준이 다른 값을 비교하면 "
            "봉투 대조가 통과해도 실제 비행고도는 다른 값이 된다"
        )

    segments: list[WaypointAltitudePlan] = []
    previous: WaypointAltitudePlan | None = None

    for sample in samples:
        if sample.terrain_elevation_m is None:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=None,
                commanded_height_m=None,
                absolute_elevation_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.TERRAIN_DATA_MISSING,
                rationale=("이 지점의 지형고도를 모른다 — 값을 지어내지 않는다",),
            )
            segments.append(segment)
            previous = segment
            continue

        # 절대 도메인(DSM 여유값 계산용)과 명령 도메인(기체가 받는 값)을 분리한다.
        absolute = sample.terrain_elevation_m + target_agl_m + safety_margin_m
        # 이륙점 상대 = 두 표고의 차 + 목표 지상고 + 여유. 두 표고가 같은 수직기준이면
        # 그 기준의 상수항이 소거되므로 지오이드가 필요 없다.
        commanded = (
            sample.terrain_elevation_m - takeoff_terrain_elevation_m
        ) + target_agl_m + safety_margin_m

        if commanded < envelope.min_altitude_m or commanded > envelope.max_altitude_m:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=sample.terrain_elevation_m,
                commanded_height_m=None,
                absolute_elevation_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.ENVELOPE_VIOLATION,
                rationale=(
                    f"이륙점 상대 고도 {commanded:.1f}m 가 비행 봉투 "
                    f"[{envelope.min_altitude_m:.1f}, {envelope.max_altitude_m:.1f}]m 밖이다 — "
                    "지형 때문에 이 지점은 이 목표 지상고로 날 수 없다",
                ),
            )
            segments.append(segment)
            previous = segment
            continue

        if (
            previous is not None
            and previous.status is AltitudeSegmentStatus.OK
            and previous.commanded_height_m is not None
        ):
            horizontal_m = great_circle_distance_m(
                previous.waypoint.lat_deg,
                previous.waypoint.lon_deg,
                sample.waypoint.lat_deg,
                sample.waypoint.lon_deg,
            )
            altitude_delta_m = abs(commanded - previous.commanded_height_m)
            if horizontal_m <= _HORIZONTAL_EPSILON_M:
                # 수평거리가 (거의) 0 이면 비율을 나눌 수 없다 — 건너뛰지 않고
                # 고도변화가 있으면 무한대 비율(=자동 위반)로 판정한다.
                rate_exceeded = altitude_delta_m > _HORIZONTAL_EPSILON_M
                rate_rationale = (
                    f"이전 지점과 수평거리가 사실상 0m 인데 고도변화 "
                    f"{altitude_delta_m:.1f}m 가 있다 — 변화율이 무한대라 상한 "
                    f"{max_altitude_change_ratio} 를 넘는다",
                )
            else:
                rate_exceeded = altitude_delta_m / horizontal_m > max_altitude_change_ratio
                rate_rationale = (
                    f"이전 지점 대비 고도변화 {altitude_delta_m:.1f}m / 수평거리 "
                    f"{horizontal_m:.1f}m 가 상한 {max_altitude_change_ratio} 를 넘는다",
                )
            if rate_exceeded:
                segment = WaypointAltitudePlan(
                    waypoint=sample.waypoint,
                    terrain_elevation_m=sample.terrain_elevation_m,
                    commanded_height_m=None,
                    absolute_elevation_m=None,
                    clearance_m=None,
                    status=AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED,
                    rationale=rate_rationale,
                )
                segments.append(segment)
                previous = segment
                continue

        # 여유값은 절대 도메인끼리 뺀다 — DSM 표고는 이륙점 상대가 아니다.
        clearance = (
            absolute - sample.surface_elevation_m
            if sample.surface_elevation_m is not None
            else None
        )
        segment = WaypointAltitudePlan(
            waypoint=sample.waypoint,
            terrain_elevation_m=sample.terrain_elevation_m,
            commanded_height_m=commanded,
            absolute_elevation_m=absolute,
            clearance_m=clearance,
            status=AltitudeSegmentStatus.OK,
            rationale=(
                f"지형고도 {sample.terrain_elevation_m:.1f}m + 목표 지상고 "
                f"{target_agl_m:.1f}m + 안전여유 {safety_margin_m:.1f}m = 절대 "
                f"{absolute:.1f}m",
                f"이륙점 지형고도 {takeoff_terrain_elevation_m:.1f}m 기준 명령값 "
                f"{commanded:.1f}m (executeHeight, relativeToStartPoint)",
            ),
        )
        segments.append(segment)
        previous = segment

    return TerrainAltitudeProfile(
        segments=tuple(segments),
        provenance=provenance,
        all_ok=all(s.status is AltitudeSegmentStatus.OK for s in segments),
    )


__all__ = [
    "AltitudeSegmentStatus",
    "TerrainAltitudeProfile",
    "TerrainReferenceMismatch",
    "WaypointAltitudePlan",
    "WaypointTerrainSample",
    "compute_altitude_profile",
]
