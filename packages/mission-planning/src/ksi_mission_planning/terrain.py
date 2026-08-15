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

## 고도변화율을 왜 "수평거리 대비 비율"로 표현하는가

이 저장소 어디에도 상승·하강률(m/s) 제약이 없고, 이 계층은 속도 데이터를 갖지
않는다(``WaylineParams.autoFlightSpeedMs`` 는 수평 속도다). 시간 기반 제약을
흉내 내려면 속도 가정을 지어내야 하므로, 대신 기하학적으로 검증 가능한 값
(수평거리 대비 고도변화 비율)을 쓴다 — ADR-KSI-011 D3 의 간격 상한과 같은 지위의
**정책값**이다(물리 증명이 아니라 보수적 시작점).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_geo_core.frames import great_circle_distance_m

from ksi_mission_planning.geometry import GeoPoint

if TYPE_CHECKING:
    from ksi_mission_contracts.models import FlightEnvelope


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
    """웨이포인트 1개의 계산 결과 — 값과 판정 근거를 함께 들고 다닌다."""

    waypoint: GeoPoint
    terrain_elevation_m: float | None
    #: 지형고도 + 목표 지상고 + 안전여유. status 가 OK 일 때만 값이 있다.
    commanded_altitude_m: float | None
    #: commanded_altitude_m - surface_elevation_m. DSM 이 없으면 None.
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
    target_agl_m: float,
    safety_margin_m: float,
    max_altitude_change_ratio: float,
    envelope: FlightEnvelope,
    provenance: str,
) -> TerrainAltitudeProfile:
    """경로의 각 지점에서 안전한 지형추종 고도를 계산한다 — 순수 함수.

    Raises:
        ValueError: ``samples`` 가 비었거나, ``target_agl_m``/``max_altitude_change_ratio``
            가 양수가 아니거나, ``safety_margin_m`` 이 음수일 때.
    """
    if not samples:
        raise ValueError("samples 는 비어 있을 수 없다 — 빈 경로의 고도 계획은 정의되지 않는다")
    if target_agl_m <= 0.0:
        raise ValueError(f"target_agl_m 은 양수여야 한다: {target_agl_m}")
    if safety_margin_m < 0.0:
        raise ValueError(f"safety_margin_m 은 음수일 수 없다: {safety_margin_m}")
    if max_altitude_change_ratio <= 0.0:
        raise ValueError(
            f"max_altitude_change_ratio 는 양수여야 한다: {max_altitude_change_ratio}"
        )

    segments: list[WaypointAltitudePlan] = []
    previous: WaypointAltitudePlan | None = None

    for sample in samples:
        if sample.terrain_elevation_m is None:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=None,
                commanded_altitude_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.TERRAIN_DATA_MISSING,
                rationale=("이 지점의 지형고도를 모른다 — 값을 지어내지 않는다",),
            )
            segments.append(segment)
            previous = segment
            continue

        commanded = sample.terrain_elevation_m + target_agl_m + safety_margin_m

        if commanded < envelope.min_altitude_m or commanded > envelope.max_altitude_m:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=sample.terrain_elevation_m,
                commanded_altitude_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.ENVELOPE_VIOLATION,
                rationale=(
                    f"계산된 고도 {commanded:.1f}m 가 비행 봉투 "
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
            and previous.commanded_altitude_m is not None
        ):
            horizontal_m = great_circle_distance_m(
                previous.waypoint.lat_deg,
                previous.waypoint.lon_deg,
                sample.waypoint.lat_deg,
                sample.waypoint.lon_deg,
            )
            altitude_delta_m = abs(commanded - previous.commanded_altitude_m)
            if (
                horizontal_m > 0.0
                and altitude_delta_m / horizontal_m > max_altitude_change_ratio
            ):
                segment = WaypointAltitudePlan(
                    waypoint=sample.waypoint,
                    terrain_elevation_m=sample.terrain_elevation_m,
                    commanded_altitude_m=None,
                    clearance_m=None,
                    status=AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED,
                    rationale=(
                        f"이전 지점 대비 고도변화 {altitude_delta_m:.1f}m / 수평거리 "
                        f"{horizontal_m:.1f}m 가 상한 {max_altitude_change_ratio} 를 넘는다",
                    ),
                )
                segments.append(segment)
                previous = segment
                continue

        clearance = (
            commanded - sample.surface_elevation_m
            if sample.surface_elevation_m is not None
            else None
        )
        segment = WaypointAltitudePlan(
            waypoint=sample.waypoint,
            terrain_elevation_m=sample.terrain_elevation_m,
            commanded_altitude_m=commanded,
            clearance_m=clearance,
            status=AltitudeSegmentStatus.OK,
            rationale=(
                f"지형고도 {sample.terrain_elevation_m:.1f}m + 목표 지상고 "
                f"{target_agl_m:.1f}m + 안전여유 {safety_margin_m:.1f}m = {commanded:.1f}m",
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
    "WaypointAltitudePlan",
    "WaypointTerrainSample",
    "compute_altitude_profile",
]
