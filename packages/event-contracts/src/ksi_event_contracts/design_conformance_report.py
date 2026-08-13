"""DesignConformanceReport — "설계대로 되고 있나, 얼마나 더 깎고 더 쌓아야 하나".

## VolumeChangeReport 의 형제이되 묻는 질문이 다르다

``VolumeChangeReport`` 는 **두 시점**을 뺀다("지난달 대비 얼마나 움직였나").
이 리포트는 **설계면과 현재**를 뺀다("설계까지 얼마나 남았나"). 계산 엔진은 같고
(``align_and_diff`` → ``volume_delta_in_polygon``) 구역 결과 모양도 같아서
:class:`~ksi_event_contracts.volume_change_report.ZoneVolumeDelta` 를 **그대로
재사용한다** — cut/fill/net 자기정합 검증(``_net_matches_cut_and_fill``)도 함께
따라온다. 같은 뜻의 값을 두 벌 정의하면 한쪽만 고쳐지는 날이 온다.

**부호 규약은 그 클래스의 것을 그대로 쓴다**: ``cut`` = 깎아야 할 양, ``fill`` =
쌓아야 할 양, ``net = fill - cut`` = 순 성토 필요량. 계산 쪽이
``align_and_diff(baseline=현재DSM, current=설계면)`` 순서로 불러 ``delta = 설계 −
현재`` 를 만들기 때문에 이 뜻이 성립한다(그 순서 뒤집기는 계산 래퍼 안에서만
일어나고 호출부에 노출되지 않는다).

## 지도와 숫자가 갈라지지 않게 — ``diffRaster`` 는 참조가 아니라 사실이다

이전 설계에는 히트맵의 데이터 출처가 없었다. 브라우저가 원본 두 장을 받아 다시
차분하면 **두 번째 진실**이 생기고, 지도와 표가 조용히 갈릴 수 있다. 그래서
체적 집계에 실제로 쓴 **그 격자**를 GeoTIFF 로 영속하고, 이 리포트가 그 파일을
:class:`DiffRasterRef` 로 들고 다닌다.

``coreVerifiedDigestAt`` 이 그 참조를 "주장"에서 "사실"로 올리는 자리다 — 워커가
"올렸다"고 말한 시각이 아니라 **Core 가 업로드된 바이트를 직접 다시 해싱해
``digest`` 와 같음을 확인한 시각**이다. 값이 실려 있다는 것은 그 확인이 있었다는
뜻이고, 확인 없이 이 리포트를 만들 수는 없다(필수 필드).

이 계약은 그 사실을 **표현**할 뿐 강제하지는 못한다 — 실제로 재해싱하는 것은
Core 의 제출 경로(7단계)의 책임이다. ``DesignSurface.observed`` 가 "누가 쟀는지"를
담고 판정은 Core 가 하는 것과 같은 분업이다.

## 세 기준값이 하나라는 것을 계약이 본다

``policy.volumeThresholdM`` · 각 구역의 ``thresholdM`` · ``diffRaster.thresholdM``
은 같은 값이어야 한다. 셋이 갈라지면 화면 범례("이 값 미만은 집계 제외")가
표의 숫자와 다른 기준을 말하게 되고, 그 거짓말은 어느 화면에서도 보이지 않는다.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.design_surface import SHA256_HEX_PATTERN
from ksi_event_contracts.vertical_reference import VerticalReference, VerticalReferenceSource
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta

#: 산출물 참조 digest 표기 — ``ProcessingArtifact.digest`` 와 같은 접두사 규약.
_PREFIXED_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: 세 곳에 실리는 문턱값이 같은 값인지 볼 때의 허용 오차. 같은 상수에서 복사된
#: 값들이라 원래 비트까지 같지만, JSON 왕복·float32 경유 가능성을 감안해 아주
#: 좁은 절대 오차만 허용한다(``VOLUME_TOLERANCE_M3`` 와 같은 정신, 더 엄격).
_THRESHOLD_TOLERANCE_M = 1e-12


class DesignSurfaceRef(_CamelModel):
    """어느 설계면과 비교했는가 — **요청 시점 VERIFIED 스냅샷**.

    ``sha256`` 은 :class:`~ksi_event_contracts.design_surface.DesignSurface` 의
    ``declared.sha256``/``observed.sha256`` 과 **바이트 그대로 같은 문자열**이다
    (VERIFIED 설계면은 그 둘이 같다). 접두사 붙은 ``digest`` 표기를 쓰지 않는 이유가
    이것이다 — 같은 사실을 두 가지로 적으면 대조가 문자열 비교로 끝나지 않고,
    변환을 잊은 한쪽이 조용히 "다르다"고 말한다.

    설계면 id 만으로는 부족하다: 같은 id 의 자산이 나중에 새 revision 으로 다시
    등록될 수 있고, 그때 이 리포트가 **무엇을 기준으로 낸 숫자였는지**는 해시로만
    되짚어진다.
    """

    design_surface_id: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_HEX_PATTERN)


class DiffRasterRef(_CamelModel):
    """체적 집계에 실제로 쓴 높이차 격자 — 지도가 읽는 **단 하나의** 데이터 출처.

    값 규약은 ``설계 표고 − 현재 표고`` 다: 양수 = 쌓아야 함, 음수 = 깎아야 함.
    :class:`~ksi_event_contracts.volume_change_report.ZoneVolumeDelta` 의
    ``fill``/``cut`` 과 같은 방향이라, 지도의 색과 표의 숫자가 같은 말을 한다.
    """

    diff_raster_id: str = Field(min_length=1)
    #: 업로드된 GeoTIFF 바이트의 해시(``sha256:`` 접두사) — 산출물 참조 관습.
    digest: str = Field(pattern=_PREFIXED_DIGEST_PATTERN)
    format: Literal["geotiff"] = "geotiff"
    crs: str = Field(min_length=1)
    #: 이 높이차가 **어느 기준의** 높이차인가. 우리 계산이 만든 값이므로 귀속은
    #: 파이프라인이다(아래 validator) — 사용자가 주장할 수 있는 값이 아니다.
    vertical_reference: VerticalReference
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    pixel_size_x_m: float = Field(gt=0.0)
    pixel_size_y_m: float = Field(gt=0.0)
    #: rasterio ``Affine`` 순서 ``(a, b, c, d, e, f)`` — ``DesignSurfaceObserved.transform``
    #: 과 같은 규약.
    transform: tuple[float, float, float, float, float, float]
    #: 무효 셀(측정 불가)의 표현. **0 이 아니라 NaN 이다** — 0 은 "차이가 없다"는
    #: 뜻이 있는 값이라, 모르는 곳을 0 으로 칠하면 지도가 "설계대로 됐다"고
    #: 거짓말한다. 화면은 이 셀을 "모름"으로 따로 그린다(3상태 범례).
    nodata_encoding: Literal["nan"] = "nan"
    #: 이 값 미만의 |높이차| 는 체적 집계에서 제외됐다. 래스터에는 실제 값이 그대로
    #: 남아 있으므로, 화면이 "집계 제외" 구간을 중립색으로 드러내려면 이 값이 필요하다.
    threshold_m: float = Field(ge=0.0)
    size_bytes: int = Field(ge=1)
    #: **Core 가 업로드된 바이트를 직접 다시 해싱해 ``digest`` 와 같음을 확인한 시각.**
    #: 워커의 자기보고("올렸다")가 아니다 — 모듈 docstring 참조.
    core_verified_digest_at: datetime

    @model_validator(mode="after")
    def _check_self_consistency(self) -> DiffRasterRef:
        if self.vertical_reference.source is not VerticalReferenceSource.PIPELINE_DECLARED:
            raise ValueError(
                "diffRaster.verticalReference.source 는 pipeline_declared 여야 한다 "
                f"(got {self.vertical_reference.source.value}) — 이 격자는 우리 계산이 "
                "만든 값이고, 그 수직기준은 사용자가 주장하는 것이 아니다"
            )
        for name, value in (
            ("pixelSizeXM", self.pixel_size_x_m),
            ("pixelSizeYM", self.pixel_size_y_m),
            ("thresholdM", self.threshold_m),
            *((f"transform[{i}]", v) for i, v in enumerate(self.transform)),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} 은 finite 여야 한다 (got {value!r})")
        if self.core_verified_digest_at.tzinfo is None:
            raise ValueError("coreVerifiedDigestAt 은 tz-aware(offset 포함) 여야 한다")
        return self


class DesignConformanceReport(_CamelModel):
    """contracts/schemas/design-conformance-report.v1.json 왕복 대상."""

    schema_version: Literal["1.0"] = "1.0"
    design_conformance_id: str = Field(min_length=1)
    design_surface_ref: DesignSurfaceRef
    #: 비교한 현재 지형 산출물(DSM). ``ArtifactRef`` 를 재사용한다 — jobId 없이는
    #: artifactId 를 해석할 수 없다는 이유가 여기서도 그대로다.
    current: ArtifactRef
    #: 설계면과 현재 DSM 이 공유하는 수평 좌표계. 다르면 계산 자체가 거부된다(INV-020).
    crs: str = Field(min_length=1)
    #: 이 잔량이 어느 수직기준의 높이차인가. 두 입력의 수직기준 **계열**이 같을
    #: 때만 계산이 성립하며(``assert_comparable_vertical``), 그 판정은 요청 생성
    #: 시점에 이미 끝나 있다. 귀속(source)은 어느 쪽에서 왔는지에 따라 다를 수
    #: 있어 여기서 고정하지 않는다 — 다만 ``diffRaster`` 와 datum 은 같아야 한다.
    vertical_reference: VerticalReference
    zones: list[ZoneVolumeDelta] = Field(min_length=1)
    #: 이 계산이 실제로 쓴 기준값 스냅샷(참조가 아니라 값) — 화면은 결과 옆에
    #: 이 값을 읽기 전용으로 표시한다(대표자 확정: 고정값이라고 숨기지 않는다).
    policy: ComparisonPolicy
    diff_raster: DiffRasterRef
    computed_at: datetime

    @model_validator(mode="after")
    def _check_self_consistency(self) -> DesignConformanceReport:
        """숫자·지도·기준값이 **서로를 뒷받침하는가**.

        여기서 막는 셋은 전부 "화면에서는 그럴듯한" 모순이다: 같은 구역이 두 번
        집계돼 총합이 조용히 두 배가 되는 것, 지도와 표가 다른 좌표계·수직기준을
        말하는 것, 범례의 문턱과 집계의 문턱이 다른 것.
        """
        if self.computed_at.tzinfo is None:
            raise ValueError("computedAt 은 tz-aware(offset 포함) 여야 한다")

        zone_ids = [zone.zone_id for zone in self.zones]
        if len(set(zone_ids)) != len(zone_ids):
            raise ValueError(f"zoneId 가 중복된다: {zone_ids} — 같은 구역이 두 번 집계된다")

        if self.diff_raster.crs != self.crs:
            raise ValueError(
                f"diffRaster.crs({self.diff_raster.crs}) 가 리포트의 crs({self.crs}) 와 "
                "다르다 — 지도와 표가 다른 좌표계를 말한다"
            )
        if self.diff_raster.vertical_reference.datum is not self.vertical_reference.datum:
            raise ValueError(
                f"diffRaster 의 수직기준({self.diff_raster.vertical_reference.datum.value}) 이 "
                f"리포트의 수직기준({self.vertical_reference.datum.value}) 과 다르다"
            )

        thresholds = {
            "policy.volumeThresholdM": self.policy.volume_threshold_m,
            "diffRaster.thresholdM": self.diff_raster.threshold_m,
            **{f"zones[{i}].thresholdM": z.threshold_m for i, z in enumerate(self.zones)},
        }
        reference = self.policy.volume_threshold_m
        divergent = {
            name: value
            for name, value in thresholds.items()
            if not math.isclose(value, reference, abs_tol=_THRESHOLD_TOLERANCE_M)
        }
        if divergent:
            raise ValueError(
                f"문턱값이 한 값이 아니다: {divergent} (기준 {reference}) — 범례가 "
                "말하는 기준과 집계에 쓴 기준이 다르면 지도와 표가 조용히 갈린다"
            )
        return self

    @property
    def total_net_m3(self) -> float:
        """전 구역 순 성토 필요량 — 화면 요약이 이 값을 스스로 계산하지 않게."""
        return sum(zone.net_m3 for zone in self.zones)


__all__ = [
    "DesignConformanceReport",
    "DesignSurfaceRef",
    "DiffRasterRef",
]
