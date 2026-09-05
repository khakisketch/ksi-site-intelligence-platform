"""DefectCandidate 계약 — contracts/schemas/defect-candidate.v1.json 의 Python 대응
(Phase 4 "표면 점검·결함 후보", MODEL-P4-001).

## 왜 탐지 서비스가 아니라 계약 패키지에 사는가

R3에서 모델 검증·추론 adapter·후처리 구현은 ``services/defect-detection`` 에서
import-only ``packages/defect-detection`` 으로 이동했다. 이 패키지는
optional/model-gated 이며 독립 운영 서비스가 아니다. 계약은 여기
``packages/event-contracts`` 에 남는다. 계약까지 탐지 구현에 두면 이를 소비하는
``services/core``(결함 후보 수신·조회 API)가 **optional model package에 의존**하게 되고,
그 패키지의 base 의존인 ``opencv-python-headless`` 가 control plane 으로 딸려온다 —
mmcv/mmengine 이 순정 ``opencv-python`` 을 강제해 같은 ``cv2`` 네임스페이스를
깨뜨리는 알려진 취약점(risk ``defect-detection-opencv-namespace-conflict``)이
그대로 Core 의 기동 조건이 된다. ``CoverageReport``·``ProcessingArtifact``·
``WorldEntity`` 가 전부 이 패키지에 사는 것과 같은 이유다: **wire 계약은 그것을
만드는 쪽이 아니라 주고받는 양쪽이 공유하는 곳에 둔다.**

모델 검증·추론 adapter·후처리(``ksi_defect_detection.mixercseg_adapter`` /
``ksi_defect_detection.postprocess``)는 optional/model-gated
``packages/defect-detection`` 이 담당한다. 이 모듈은 계약만 제공한다.

## 왜 bbox 가 아니라 polygon 인가

균열 세그멘테이션 모델(MixerCSeg 등)의 원출력은 픽셀 단위 마스크다. 이를 기존
``ksi_domain.detection`` 의 bbox 기반 Detection 계약에 억지로 맞추면 길이·폭·면적
같은 균열 고유의 형상 정보가 사라진다 — 점검 용도에서는 "탐지 여부"보다 이 형상
정보가 실사용 가치다. 그래서 RiskField(``ksi_equipment_intelligence.risk_field``)와
같은 방식으로 전용 계약을 새로 둔다: bbox 대신 이미지 픽셀 좌표계의 polygon
윤곽(``IMAGE_POLYGON_2D``)을 payload 로 나른다 — 원본 마스크 래스터 전체를 wire 에
싣지 않으면서(용량) 면적·길이 같은 계산 가능한 형상 요약은 보존한다.

## 이 모듈이 하지 않는 것

- Detection/Observation·WorldEntity 융합으로의 편입, BIM(IfcSurfaceFeature) 되먹임은
  후속 결정 사안이다(``docs/models/DEFECT_MODEL_CANDIDATES.md`` "BIM 연계" 절).

실제 세그멘테이션 추론·adapter 는 :mod:`ksi_defect_detection.mixercseg_adapter` +
:mod:`ksi_defect_detection.postprocess` 가 담당한다(이 모듈은 계약만).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ksi_event_contracts._base import _CamelModel

DefectType = Literal["CRACK"]  # MODEL-P4-001 scope — 균열만. 확장은 CiF 파인튜닝 후 별도 결정.
GeometryFormat = Literal["IMAGE_POLYGON_2D"]

# [[x, y], ...] 픽셀 좌표 목록(윤곽 1개, 최소 3점 — 다각형 최소 조건). None 은
# "형상 없음"(예: 결함 존재만 알고 윤곽은 못 낸 경로)을 뜻하는 명시적 값이다.
GeometryPayload = list[tuple[float, float]] | None


# 다섯 모델 모두 `_CamelModel` 을 상속한다(2026-08-18). 이전에는 각자 동일한
# ConfigDict 를 재정의했는데, 그 사본에는 베이스의 ``allow_inf_nan=False`` 가
# 없어서 measurements 의 ``+inf`` 가 검증을 통과해 durable 원장을 봉인시켰다
# (재조사 F1 — ``ge=0.0`` 은 대체재가 아니다: ``inf >= 0`` 이 참이라 +inf 만
# 통과한다). 바깥 래퍼의 설정은 중첩 모델로 전파되지 않으므로(실측) 각 모델이
# 직접 베이스를 상속해야 한다.
class ImageSize(_CamelModel):
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class DefectGeometry(_CamelModel):
    """``payload`` 는 ``IMAGE_POLYGON_2D`` 일 때 ``[[x, y], ...]`` 픽셀 좌표 목록
    (윤곽 1개) 이다 — 원본 마스크 래스터가 아니라 ``cv2.findContours`` 류의 요약.

    ``format`` 이 항상 단일 리터럴이라(RiskField 와 달리 이 계약은 포맷을
    분기하지 않는다) ``payload`` 를 ``Any`` 로 열어두지 않고 실제 모양으로
    좁힌다 — 그렇지 않으면 임의 문자열·스칼라도 "왕복 검증 통과"로 잘못
    읽힌다(reviewer 지적 F6, 2026-08-07).

    최소 3점(다각형 최소 조건)은 스키마(``minItems: 3``)와 여기 둘 다 강제한다
    — 처음엔 스키마에만 있었고 pydantic 쪽은 길이 무검증이라 "두 정본이
    갈라지지 않는다"는 계약 자체가 깨져 있었다(reviewer 재검토 잔여 지적).
    """

    format: GeometryFormat
    payload: GeometryPayload = Field(default=None, min_length=3)


class DefectMeasurements(_CamelModel):
    """``meanWidthPx`` 는 면적/길이로 역산한 **평균** 폭이다 — 최댓값이 아니다
    (필드명이 예전엔 ``maxWidthPx`` 였다가 계산 내용과 안 맞아 개명함, reviewer
    지적 F4). 최댓값이 필요한 소비자는 이 근사치를 그대로 신뢰하면 안 된다."""

    area_px2: float | None = Field(default=None, ge=0.0)
    length_px: float | None = Field(default=None, ge=0.0)
    mean_width_px: float | None = Field(default=None, ge=0.0)


class DefectModelRef(_CamelModel):
    """계보 앵커 — ``ksi_perception.registry.ModelEntry`` 와 동형(모델 신원 +
    원본 artifact digest). 어떤 모델이 이 후보를 냈는지 wire 에 항상 싣는다."""

    model_id: str = Field(min_length=1)
    source_digests: dict[str, str] = Field(default_factory=dict)


class DefectCandidate(_CamelModel):
    """contracts/schemas/defect-candidate.v1.json 왕복 대상 — required 필드는 스키마와 동일."""

    schema_version: Literal["1.0"] = "1.0"
    defect_candidate_id: str = Field(min_length=1)
    defect_type: DefectType
    source_media_id: str = Field(min_length=1)
    image_size: ImageSize
    geometry: DefectGeometry
    model: DefectModelRef
    confidence: float = Field(ge=0.0, le=1.0)
    measurements: DefectMeasurements | None = None


def defect_candidate_wire_dict(candidate: DefectCandidate) -> dict[str, Any]:
    """계약 스키마와 정확히 대조 가능한 wire 표현(왕복 검증 대상).

    ``geometry.payload`` 는 값이 없어도(``None``) 키가 남아야 한다(스키마
    required=["format","payload"]) — RiskField 의 동일 함정(F2)을 여기서도 그대로
    피한다. ``measurements`` 는 선택 필드라 값이 없으면 키째 뺀다.
    """
    wire = candidate.model_dump(by_alias=True, mode="json", exclude_none=False)
    if wire.get("measurements") is None:
        wire.pop("measurements", None)
    else:
        measurements = wire["measurements"]
        for key in ("areaPx2", "lengthPx", "meanWidthPx"):
            if measurements.get(key) is None:
                measurements.pop(key, None)
    return wire


def defect_candidate_from_wire(wire: dict[str, Any]) -> DefectCandidate:
    """wire → model 역방향 검증(round-trip). ``pydantic`` alias 파싱을 그대로 쓴다
    — RiskField 가 model→wire 단방향만 갖고 있던 잔여 리스크
    (``risk-field-round-trip-one-direction-only``)를 이 계약에서는 처음부터 만들지
    않는다."""
    return DefectCandidate.model_validate(wire)


__all__ = [
    "DefectCandidate",
    "DefectGeometry",
    "DefectMeasurements",
    "DefectModelRef",
    "DefectType",
    "GeometryFormat",
    "ImageSize",
    "defect_candidate_from_wire",
    "defect_candidate_wire_dict",
]
