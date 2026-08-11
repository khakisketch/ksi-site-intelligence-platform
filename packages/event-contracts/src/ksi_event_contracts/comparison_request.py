"""ComparisonRequest — "이 두 작업을 비교하라"는 지시 계약 (ADR-KSI-016 D3, W2).

## 결과 계약이 아니라 지시 계약이다

``ChangeDetectionResult``/``VolumeChangeReport``는 이미 계산된 **결과**를 나른다.
이 계약은 그 계산을 **해 달라**는 요청을 나른다 — 형태가 다르다. 결과 계약
둘은 이 요청이 가리키는 산출물이 실제로 계산 가능한지(``changeDetectionEligible``/
``volumeChangeEligible``)를 요청 생성 시점에 미리 판정해 함께 싣는다 — 그래야
"이 조합은 체적 비교가 안 된다"를 워커가 돌기 전에, 화면이 먼저 보여줄 수 있다.

## 구역(zones)은 참조가 아니라 값이다 (대표자 확정, 2026-08-10)

``zones``는 현장(site) AOI를 가리키는 foreign key가 아니라 **그 순간 확정한
폴리곤 값 자체**를 담는다 — 나중에 현장 경계가 바뀌어도 이미 만든 요청은
그대로 유지되는 불변 스냅샷이다. 이 파일이 그 스냅샷의 wire 표현이다.

## ArtifactRef 는 새로 만들지 않는다

:mod:`ksi_event_contracts.change_detection_result` 의 ``ArtifactRef`` 를 그대로
가져다 쓴다 — ``VolumeChangeReport`` 도 같은 클래스를 재사용한다(그쪽 모듈이
이미 이 패턴이다). "jobId 없이는 artifactId 를 해석할 수 없다"는 이유가
바뀌지 않았으므로 여기서 다시 정의하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.processing_job import ProcessingJobStatus


class ComparisonRequest(_CamelModel):
    """contracts/schemas/comparison-request.v1.json 왕복 대상.

    ``pointCloud*``/``dsm*`` 넷 중 어느 것이 채워지는지는 요청 생성 시점에
    Core 가 baseline/current 작업의 등록된 산출물을 조회해 판정한다(요청 쪽이
    스스로 주장하지 않는다) — ``changeDetectionEligible``/``volumeChangeEligible``
    이 그 판정 결과다. 이 값 이후 두 산출물이 어느 쪽도 없으면 요청 자체가
    거부된다(NOTHING_TO_COMPARE) — 아무것도 계산할 수 없는 요청을 원장에
    남기지 않는다.
    """

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    baseline_job_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)

    point_cloud_baseline: ArtifactRef | None = None
    point_cloud_current: ArtifactRef | None = None
    change_detection_eligible: bool
    # 둘 중 하나라도 없으면 왜 없는지 — "변화 없음"과 "비교 불가"를 화면이
    # 구분해 보여줄 수 있게 한다.
    change_detection_ineligible_reason: str | None = None

    dsm_baseline: ArtifactRef | None = None
    dsm_current: ArtifactRef | None = None
    volume_change_eligible: bool
    volume_change_ineligible_reason: str | None = None

    # zoneId -> GeoJSON Polygon. None 이면 사용자가 구역을 확정하지 않은 것이라
    # 체적 비교를 아예 시도하지 않는다(zones 부재도 비활성 사유 중 하나).
    zones: dict[str, dict[str, Any]] | None = None
    zone_crs: str | None = None

    # 이 요청이 **실제로 쓸/쓴** 기준값 — 생성 시점의 시스템 고정값을 zones 와
    # 같은 이유로 값 복사해 굳힌다(참조가 아니다). 워커는 함수 기본값이 아니라
    # 이 값을 써서 계산하고, 화면은 제출·결과 양쪽에서 이 값을 읽기 전용으로
    # 표시한다(대표자 확정: 고정값이라고 숨기지 않는다).
    policy: ComparisonPolicy

    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str = Field(min_length=1)
    updated_at: datetime
    # 종료 상태에서만 채워진다 — 왜 그렇게 끝났는지(FAILED 사유).
    detail: str | None = None

    @model_validator(mode="after")
    def _check_self_consistency(self) -> ComparisonRequest:
        if self.requested_at.tzinfo is None:
            raise ValueError("requestedAt 은 tz-aware(offset 포함) 여야 한다")
        if self.updated_at.tzinfo is None:
            raise ValueError("updatedAt 은 tz-aware(offset 포함) 여야 한다")
        if self.baseline_job_id == self.current_job_id:
            raise ValueError(
                "baselineJobId 와 currentJobId 가 같다 — 자기 자신과의 비교는 "
                "언제나 '변화 없음'으로 읽히지만 아무것도 비교하지 않은 것이다"
            )
        if not self.change_detection_eligible and not self.volume_change_eligible:
            raise ValueError(
                "changeDetectionEligible·volumeChangeEligible 이 둘 다 false 다 — "
                "아무것도 계산할 수 없는 요청은 원장에 남기지 않는다(NOTHING_TO_COMPARE)"
            )
        if self.change_detection_eligible and (
            self.point_cloud_baseline is None or self.point_cloud_current is None
        ):
            raise ValueError(
                "changeDetectionEligible=true 인데 pointCloudBaseline/Current 가 "
                "비어 있다 — eligible 판정과 실제 참조가 어긋난다"
            )
        if self.volume_change_eligible and (
            self.dsm_baseline is None
            or self.dsm_current is None
            or not self.zones
            or not self.zone_crs
        ):
            raise ValueError(
                "volumeChangeEligible=true 인데 dsmBaseline/Current·zones·zoneCrs 중 "
                "일부가 비어 있다 — eligible 판정과 실제 참조가 어긋난다"
            )
        return self


__all__ = ["ComparisonRequest"]
