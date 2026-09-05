"""VolumeChangeReport — 두 시점 DSM 차분으로 잰 구역별 절토·성토 (ADR-KSI-016 D3).

## 왜 ChangeDetectionResult 옆에 따로 사는가

``ChangeDetectionResult`` 는 point cloud C2C 의 요약이라 형태가 근본적으로
다르다(``candidateRatio``·``pointCount``). 체적은 "몇 퍼센트의 점이 움직였나"가
아니라 "이 구역에서 몇 m³ 가 깎이고 쌓였나"다. 억지로 한 계약에 얹으면 두
클래스의 조건분기가 섞이고, 소비자가 어느 필드가 언제 유효한지 알 수 없다.

계산은 ``packages/change-detection``(rasterio) 이 하고 수신·조회는
``services/core`` 가 한다 — 계약이 여기 사는 이유는 그쪽 모듈 docstring 과
같다(Core 에 rasterio 가 딸려오지 않게).

## 오차한계는 근거가 있을 때만 값이다 (INV-024)

절대 정확도는 **양쪽 epoch 모두** 독립 검사점으로 검증된 RMSE 를 가질 때만
말할 수 있다. 하나라도 없으면 ``uncertaintyM3`` 는 ``null`` 이고, 그때
``uncertaintyNote`` 가 **왜 없는지**를 사람 말로 적는다. 숫자만 크게 보여주고
한계를 비워두면 화면이 "이 값은 믿을 만하다"고 말하는 것과 같다.

M1 의 기본 경로인 ODM 자체에는 구조화된 GCP/RMSE 리포트가 없다
(ADR-KSI-012 D3). 다만 봉인된 독립 검사점 CSV와 DSM을 KSI 서버 워커가 직접
대조한 두 epoch에는 이 필드가 채워진다. 그런 외부 검증 증거가 없으면 계속
``null``이며, 값을 지어내지 않는다.

## verticalDatum 을 반드시 싣는다

두 DSM 을 뺄 때 그 값이 타원체고인지 정표고인지가 결과의 의미를 바꾼다.
M1 은 지오이드 격자가 없어 ``ellipsoidal_native``(엔진이 낸 타원체고를 변환
없이 그대로) 하나뿐이고, 이 값이 남아 있는 리포트가 곧 나중에 정표고로 다시
계산할 대상 목록이 된다(``ksi_geo_spatial.vertical.VerticalDatum``).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.change_detection_result import ArtifactRef

# net = fill - cut 대조 허용 오차. 셀 단위 합산을 float 로 하므로 비트 일치를
# 요구하면 정직한 결과가 거부된다(``RATIO_TOLERANCE`` 와 같은 이유). 체적은
# m³ 단위 실수라 상대 오차로 본다.
VOLUME_TOLERANCE_M3 = 1e-6


class ZoneVolumeDelta(_CamelModel):
    """구역 하나의 절토·성토 — 부호 규약이 이 클래스의 핵심이다.

    ``cut`` 은 **깎인 양**(현재가 기준보다 낮아진 부분의 부피), ``fill`` 은
    **쌓인 양**이다. 둘 다 양수로 싣고, 방향은 ``net = fill - cut`` 하나로만
    말한다 — 부호가 두 곳에 있으면 한쪽만 뒤집혀도 화면에서는 그럴듯하다.
    """

    zone_id: str = Field(min_length=1)
    cut_m3: float = Field(ge=0.0)
    fill_m3: float = Field(ge=0.0)
    net_m3: float
    area_m2: float = Field(gt=0.0)
    # 기준면 대비 이 값보다 작은 표고차는 변화로 세지 않는다(재구성 노이즈).
    threshold_m: float = Field(ge=0.0)
    # 양쪽 epoch 모두 검증된 RMSE 를 가질 때만 값. 그 외에는 null.
    uncertainty_m3: float | None = Field(default=None, ge=0.0)
    # null 인 이유(또는 값이 있을 때 그 근거). **비워둘 수 없다.**
    uncertainty_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _net_matches_cut_and_fill(self) -> ZoneVolumeDelta:
        """세 값이 서로를 뒷받침하는가 — 계약이 스스로 볼 수 있는 모순.

        ``cut``·``fill``·``net`` 은 독립된 세 값이 아니라 둘이 셋째를 정한다.
        셋을 그대로 받아 적으면 "깎기만 했는데 순증가"처럼 어느 화면에서도
        이상해 보이지 않는 결과가 원장에 남는다
        (``ChangeDetectionResult._check_self_consistency`` 와 같은 자리).
        """
        for name, value in (
            ("cutM3", self.cut_m3),
            ("fillM3", self.fill_m3),
            ("netM3", self.net_m3),
            ("areaM2", self.area_m2),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} 은 finite 여야 한다 (got {value!r})")

        expected = self.fill_m3 - self.cut_m3
        tolerance = VOLUME_TOLERANCE_M3 * max(1.0, abs(expected))
        if not math.isclose(self.net_m3, expected, abs_tol=tolerance):
            raise ValueError(
                f"netM3({self.net_m3}) 가 fillM3-cutM3({expected}) 와 다르다 — "
                "세 값이 서로를 뒷받침하지 않는다"
            )
        if self.uncertainty_m3 is not None and not math.isfinite(self.uncertainty_m3):
            raise ValueError("uncertaintyM3 는 finite 이거나 null 이어야 한다")
        return self


class VolumeChangeReport(_CamelModel):
    """contracts/schemas/volume-change-report.v1.json 왕복 대상."""

    schema_version: Literal["1.0"] = "1.0"
    volume_change_id: str = Field(min_length=1)
    baseline: ArtifactRef
    current: ArtifactRef
    crs: str = Field(min_length=1)
    # ksi_geo_spatial.vertical.VerticalDatum 의 값. M1 은 ellipsoidal_native 뿐.
    vertical_datum: str = Field(min_length=1)
    zones: list[ZoneVolumeDelta] = Field(min_length=1)
    computed_at: datetime

    @model_validator(mode="after")
    def _check_self_consistency(self) -> VolumeChangeReport:
        """비교 대상이 서로 다른가, 시각이 복원 가능한가, 구역이 겹치지 않는가."""
        if self.computed_at.tzinfo is None:
            raise ValueError("computedAt 은 tz-aware(offset 포함) 여야 한다")
        if (self.baseline.job_id, self.baseline.artifact_id) == (
            self.current.job_id,
            self.current.artifact_id,
        ):
            raise ValueError(
                "baseline 과 current 가 같은 산출물이다 — 자기 자신과의 차분은 "
                "언제나 0 이고, 그 0 이 '변화 없음'으로 읽힌다"
            )
        zone_ids = [zone.zone_id for zone in self.zones]
        if len(set(zone_ids)) != len(zone_ids):
            raise ValueError(f"zoneId 가 중복된다: {zone_ids} — 같은 구역이 두 번 집계된다")
        return self

    @property
    def total_net_m3(self) -> float:
        """전 구역 순변화 — 화면 요약이 이 값을 스스로 계산하지 않게."""
        return sum(zone.net_m3 for zone in self.zones)


__all__ = [
    "VOLUME_TOLERANCE_M3",
    "VolumeChangeReport",
    "ZoneVolumeDelta",
]
