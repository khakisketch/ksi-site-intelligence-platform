"""Track 관측 집합 → WorldEntity 조립 (P1-2).

여러 프레임에서 관찰된 같은 대상(같은 ``track_id``)의 :class:`Observation` 들을 하나의
:class:`WorldEntity` 로 합친다. Phase 1의 "다중 시점 세계좌표 융합" 수용기준에서
계약 계층이 담당하는 부분이다 — 융합 산술 자체는 ``ksi_geo_core.fusion`` 이 한다.

## 레이어 방향

이 모듈은 ``ksi_event_contracts`` 안에 있지만 ``ksi_geo_core`` 를 import한다. geo-core는
계약 패키지를 모르고(단방향), 계약 계층이 geo-core를 쓰는 방향이다 — 조립은 "계약
모델을 만드는 일"이므로 계약 쪽에 두는 것이 자연스럽다.

## localization_state 판정

융합된 불확실성 크기로 :class:`WorldEntity` 의 ``localization_state`` 를 정한다.
INV-021("불확실성을 포함해도 위험이 유지될 때만 Confirmed")의 **입력**이 되는 값이며,
이 판정 자체가 이벤트 확정을 뜻하지는 않는다 — 이벤트 승격은 상위 상태머신의 일이다.

문턱값은 현장 실측 전 **보수적 임시값**이다(PRD_AMBIGUITY_REGISTER의 "위치불확실성
중단상한"이 Geo Calibration Test로 확정될 파라미터). 여기 하드코딩된 값을 실측
검증된 값으로 오인하면 안 되며, 그래서 호출자가 주입할 수 있게 열어 뒀다.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ksi_geo_core.fusion import (
    FusionObservation,
    FusionStatus,
    covariance_trace,
    fuse_observations,
)

from ksi_event_contracts.observation import Observation
from ksi_event_contracts.world_entity import WorldEntity

# 보수적 임시 문턱 — 실측 미검증(위 docstring 참고). 단위: m² (공분산 trace).
# trace 는 세 축 분산의 합이라 √(trace/3) 가 대략적인 축당 표준편차다.
# 0.75 m² → 축당 ~0.5m, 12.0 m² → 축당 ~2m 수준의 보수적 구분점.
DEFAULT_CONFIRMED_TRACE_MAX = 0.75
DEFAULT_LIKELY_TRACE_MAX = 12.0


class AssemblyStatus(StrEnum):
    """조립 결과 상태. 실패는 typed로 반환한다(INV-023 동형)."""

    OK = "ok"
    NO_OBSERVATIONS = "no_observations"
    TRACK_ID_MISMATCH = "track_id_mismatch"  # 서로 다른 track을 한 Entity로 합칠 수 없다
    MISSING_TRACK_ID = "missing_track_id"  # track 없는 관측은 Entity로 승격 불가
    FUSION_FAILED = "fusion_failed"  # geo-core 융합 단계 실패(사유는 detail)
    INVALID_THRESHOLDS = "invalid_thresholds"  # 문턱값이 비유한·음수·순서 역전


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """조립 결과. ``status``가 OK일 때만 ``entity`` 가 채워진다."""

    status: AssemblyStatus
    entity: WorldEntity | None = None
    fusion_status: FusionStatus | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is AssemblyStatus.OK


def _localization_state(
    trace: float,
    *,
    confirmed_trace_max: float,
    likely_trace_max: float,
    observation_count: int,
    distinct_viewpoints: int | None,
) -> str:
    """융합 불확실성 + 관측 수 + 시점 다양성으로 localization state를 정한다.

    두 단계로 확신을 제한한다:

    1. 관측이 1건뿐이면 아무리 공분산이 작아도 ``INSUFFICIENT_OBSERVATION`` 이다 —
       단일 시점 깊이 추정을 신뢰하지 않는다는 PRD §10.9 원칙(작은 공분산이 곧 다중
       시점 검증을 뜻하지는 않는다).
    2. 관측이 여러 건이어도 **서로 다른 관측점 2개 이상의 증거가 없으면**
       ``CONFIRMED`` 로 올리지 않고 최대 ``LIKELY`` 로 제한한다. 같은 관측점에서 찍은
       여러 프레임은 시차(parallax)가 없어 깊이를 독립적으로 검증하지 못하므로,
       관측 수만 늘어난 것을 다중 시점 검증으로 오인하면 안 된다(2차 반증 리뷰).
       ``viewpoint_id`` 를 제공하지 못하는 소스는 ``distinct_viewpoints=None`` 이며,
       그 경우에도 시점 다양성을 **주장하지 않는다**(모르면 확신하지 않는다).
    """
    if observation_count < 2:
        return "INSUFFICIENT_OBSERVATION"

    has_view_diversity = distinct_viewpoints is not None and distinct_viewpoints >= 2
    if trace <= confirmed_trace_max:
        return "CONFIRMED" if has_view_diversity else "LIKELY"
    if trace <= likely_trace_max:
        return "LIKELY"
    return "BOUNDARY_UNCERTAIN"


def assemble_world_entity(
    observations: list[Observation],
    *,
    entity_id: str,
    entity_class: str,
    model_versions: dict[str, Any],
    calibration_profile_id: str,
    subclass: str | None = None,
    confirmed_trace_max: float = DEFAULT_CONFIRMED_TRACE_MAX,
    likely_trace_max: float = DEFAULT_LIKELY_TRACE_MAX,
) -> AssemblyResult:
    """같은 track의 관측들을 융합해 :class:`WorldEntity` 를 만든다.

    결정성: 관측 순서와 무관하게 같은 결과를 낸다 — 융합은 geo-core가 id 정렬로
    정규화하고, timestamp는 관측 중 **가장 늦은 관측 시각**(가장 최근 정보 반영
    시점)을 쓰며, ``observation_ids`` 는 정렬된 목록이다.

    예외를 던지지 않는다 — 모든 실패는 :class:`AssemblyStatus` 로 반환된다.
    """
    if not observations:
        return AssemblyResult(status=AssemblyStatus.NO_OBSERVATIONS)

    # 문턱값 검증 — 순서가 역전되면(confirmed > likely) 더 느슨한 기준이 먼저 적용돼
    # 잘못된 CONFIRMED 를 만든다. 주입 가능하게 열어 둔 만큼 검증도 필요하다.
    if not (math.isfinite(confirmed_trace_max) and confirmed_trace_max >= 0):
        return AssemblyResult(
            status=AssemblyStatus.INVALID_THRESHOLDS,
            detail=f"confirmed_trace_max 는 finite한 0 이상이어야 한다 ({confirmed_trace_max!r})",
        )
    if not (math.isfinite(likely_trace_max) and likely_trace_max >= confirmed_trace_max):
        return AssemblyResult(
            status=AssemblyStatus.INVALID_THRESHOLDS,
            detail=(
                "likely_trace_max 는 finite하고 confirmed_trace_max 이상이어야 한다 "
                f"({likely_trace_max!r} < {confirmed_trace_max!r})"
            ),
        )

    track_ids = {o.track_id for o in observations}
    if None in track_ids:
        return AssemblyResult(
            status=AssemblyStatus.MISSING_TRACK_ID,
            detail="track_id 없는 관측은 WorldEntity로 승격할 수 없다(연관 미확정)",
        )
    if len(track_ids) > 1:
        return AssemblyResult(
            status=AssemblyStatus.TRACK_ID_MISMATCH,
            detail=f"서로 다른 track을 한 Entity로 합칠 수 없다: {sorted(map(str, track_ids))}",
        )
    track_id = next(iter(track_ids))
    assert track_id is not None  # None 검사를 위에서 통과했다

    fusion_input = [
        FusionObservation(
            observation_id=o.observation_id,
            site_frame=o.site_frame,
            position=(o.position[0], o.position[1], o.position[2]),
            position_covariance=(
                o.position_covariance[0],
                o.position_covariance[1],
                o.position_covariance[2],
                o.position_covariance[3],
                o.position_covariance[4],
                o.position_covariance[5],
                o.position_covariance[6],
                o.position_covariance[7],
                o.position_covariance[8],
            ),
        )
        for o in observations
    ]
    fusion = fuse_observations(fusion_input)
    if not fusion.ok:
        return AssemblyResult(
            status=AssemblyStatus.FUSION_FAILED,
            fusion_status=fusion.status,
            detail=fusion.detail,
        )

    assert fusion.position is not None
    assert fusion.position_covariance is not None
    assert fusion.site_frame is not None

    # 시점 다양성: 하나라도 viewpoint_id 가 없으면 다양성을 "모른다"로 둔다(None) —
    # 일부만 있는 상태에서 개수를 세면 없는 관측을 서로 다른 시점으로 착각한다.
    viewpoint_ids = [o.viewpoint_id for o in observations]
    distinct_viewpoints = (
        len({v for v in viewpoint_ids if v is not None})
        if all(v is not None for v in viewpoint_ids)
        else None
    )

    trace = covariance_trace(fusion.position_covariance)
    state = _localization_state(
        trace,
        confirmed_trace_max=confirmed_trace_max,
        likely_trace_max=likely_trace_max,
        observation_count=len(observations),
        distinct_viewpoints=distinct_viewpoints,
    )

    # 분류 신뢰도는 관측들의 최솟값을 취한다(낙관적 병합 금지 — P0-2의 품질 병합과
    # 같은 원칙). 하나라도 신뢰도가 없으면 결과도 없음으로 둔다.
    confidences = [o.detection_confidence for o in observations]
    classification_confidence = (
        min(c for c in confidences if c is not None)
        if all(c is not None for c in confidences)
        else None
    )

    # 생성자 대신 model_validate 를 쓰는 이유: 스키마의 ``class`` 필드는 Python
    # 예약어라 키워드 인자로 넘길 수 없다(WorldEntity가 Field(alias="class") 사용).
    # dict 경로는 그 제약을 우회하면서 스키마 표현과 1:1로 대응한다.
    entity = WorldEntity.model_validate(
        {
            "schemaVersion": "1.0",
            "entityId": entity_id,
            "class": entity_class,
            "subclass": subclass,
            "timestamp": max(o.observed_at for o in observations),
            "siteFrame": fusion.site_frame,
            "pose": {"position": list(fusion.position)},
            "uncertainty": {
                "positionCovariance": list(fusion.position_covariance),
                "classificationConfidence": classification_confidence,
                "localizationState": state,
            },
            "lineage": {
                "trackId": track_id,
                "modelVersions": model_versions,
                "calibrationProfileId": calibration_profile_id,
                "observationIds": list(fusion.observation_ids),
            },
        }
    )
    return AssemblyResult(status=AssemblyStatus.OK, entity=entity, fusion_status=fusion.status)


def world_entity_fingerprint(entity: WorldEntity) -> str:
    """WorldEntity의 결정적 fingerprint — replay 재현 검증용.

    P0-6 규약과 같은 이유로 **entity_id를 포함하지 않는다**: id는 실행마다 달라도
    무방한 값이라 동일성 기준에 넣으면 시험이 구현을 왜곡시킨다. 대신 관측 계보·
    좌표계·융합 위치·불확실성 상태처럼 "같은 입력이면 같아야 하는" 것만 넣는다.
    """
    position = ",".join(f"{v:.9f}" for v in entity.pose.position)
    covariance = ",".join(f"{v:.12f}" for v in entity.uncertainty.position_covariance)
    observation_ids = ",".join(entity.lineage.observation_ids or [])
    canonical = "|".join(
        [
            entity.entity_class,
            entity.site_frame,
            entity.lineage.track_id,
            position,
            covariance,
            str(entity.uncertainty.localization_state),
            observation_ids,
            entity.timestamp.isoformat(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
