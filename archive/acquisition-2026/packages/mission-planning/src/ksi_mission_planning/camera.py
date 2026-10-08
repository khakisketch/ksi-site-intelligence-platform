"""카메라 스펙 → 지상 촬영범위 → 격자 간격 (사진측량 표준 산식).

## 왜 이 모듈이 필요한가

이 모듈 이전에는 격자 간격(``spacing_m``)과 진행방향 촬영 간격
(``capture_interval_m``)을 **요청자가 직접 적었다.** 그러면 서버는 그 값이 맞는지
판단할 근거가 없어서, 커버리지 실측이 "각 스캔선이 ±spacing/2 를 덮는다"는 가정을
요청자가 준 값으로 세우게 된다 — **요청이 자기 커버리지 증명서를 스스로 쓰는**
구조였다. 실측으로 40ha 구역이 사진 10장에 계획 커버 1.0 으로 발급됐고, 상한을
네 번 고쳐도 다른 축으로 우회됐다(ADR-KSI-011 D2 경위 참조).

겹침은 카메라 촬영폭 없이는 원리적으로 계산할 수 없다. 그래서 상한을 추측하는
대신 **카메라를 받아 서버가 간격을 계산한다.**

## 이식 출처와 범위 (ADOPT/PORT)

산식은 `references/repos/ksi-terra` 의 `flightplan/{gsd.py,grid.py}` 가 구현한
표준 사진측량 격자비행 모델과 같다 — 핀홀 카메라 GSD, footprint, 중복도→간격.
참고 저장소에서 **직접 import 하지 않고**(00_READ_FIRST 구현 금지) 필요한 산식만
KSI 소유 모듈로 옮겼다. 옮기지 않은 것: 그쪽의 bbox 격자 생성·좌표 변환 —
이 저장소는 볼록 AOI 스캔선 생성기(`coverage.py`)를 이미 갖고 있고 그게 커버
실측까지 하므로, 여기서는 **간격만** 공급한다.

## 이 모듈이 보증하는 것 / 하지 않는 것

- 보증: 주어진 카메라·고도·중복도에 대해 간격이 **그 중복도를 실제로 만든다**.
- 보증하지 않음: 카메라 값 자체의 정확성. Matrice 4D 실측 스펙은 아직 확정되지
  않았고(H4), 값은 호출자가 준다. 틀린 카메라를 주면 틀린 간격이 나온다 —
  다만 그때는 **어디가 틀렸는지가 명시적**이다(전에는 간격이 어디서 왔는지조차
  기록에 없었다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 사진측량 표준 최소 중복도. 이보다 낮으면 정합점이 부족해 재구성이 실패한다 —
# "느슨하게 잡아도 여기까지"의 하한이고, 표준 권장은 전방 0.8·측면 0.7 이다.
MIN_FRONT_OVERLAP = 0.6
MIN_SIDE_OVERLAP = 0.5
# 권장 기본값 — 호출자가 중복도를 정하지 않았을 때 쓰는 표준 매핑 구성.
DEFAULT_FRONT_OVERLAP = 0.8
DEFAULT_SIDE_OVERLAP = 0.7


class CameraSpecError(ValueError):
    """카메라 스펙·중복도 입력 위반 — typed 실패(계산을 시도하지 않는다)."""


@dataclass(frozen=True, slots=True)
class CameraSpec:
    """매핑 카메라 스펙.

    ``image_width_px`` 는 across-track(비행 라인에 **수직**, 라인 간격을 결정),
    ``image_height_px`` 는 along-track(비행 방향, 사진 간격을 결정)에 대응한다 —
    nadir 촬영·landscape 프레임이라는 표준 격자 매핑 배치 가정이다. 짐벌이 세로로
    돌아가는 구성을 쓰면 두 값을 바꿔 주어야 한다.
    """

    sensor_width_mm: float
    focal_length_mm: float
    image_width_px: int
    image_height_px: int

    def __post_init__(self) -> None:
        for name in ("sensor_width_mm", "focal_length_mm"):
            value = float(getattr(self, name))
            if not (math.isfinite(value) and value > 0):
                raise CameraSpecError(f"{name} 는 양의 finite 여야 한다 ({value!r})")
        for name in ("image_width_px", "image_height_px"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise CameraSpecError(f"{name} 는 양의 정수여야 한다 ({value!r})")


@dataclass(frozen=True, slots=True)
class GridSpacing:
    """카메라·고도·중복도가 결정한 격자 간격 + 그 근거값.

    ``gsd_m``·``footprint`` 를 함께 내는 이유는 **왜 이 간격이 나왔는지**를 발급
    기록과 화면이 보여줄 수 있어야 하기 때문이다 — 숫자만 남으면 다음 사람이
    그 값을 다시 못 검증한다.
    """

    spacing_m: float  # 스캔선 간격(across-track) — 측면 중복도가 결정
    capture_interval_m: float  # 진행방향 촬영 간격 — 전방 중복도가 결정
    gsd_m: float  # 지상표본거리(m/px)
    footprint_across_m: float
    footprint_along_m: float


def compute_gsd_m(camera: CameraSpec, altitude_m: float) -> float:
    """GSD(m/px) = (센서폭_m × 고도_m) / (초점거리_m × 이미지폭_px)."""
    if not (math.isfinite(altitude_m) and altitude_m > 0):
        raise CameraSpecError(f"altitude_m 는 양의 finite 여야 한다 ({altitude_m!r})")
    sensor_w_m = camera.sensor_width_mm / 1000.0
    focal_m = camera.focal_length_mm / 1000.0
    denominator = focal_m * camera.image_width_px
    # 초점거리가 subnormal(예: 5e-324)이면 ``/1000`` 에서 0.0 으로 언더플로해 분모가
    # 0 이 된다 — CameraSpec 의 ``gt=0`` 은 5e-324 를 통과시키므로 여기까지 온다.
    # ZeroDivisionError 는 typed 실패가 아니라 호출자를 지나쳐 500 으로 샌다
    # (2026-08-18 실측: 임무 발급 라우트가 500). fail-closed 로 거부한다.
    if denominator <= 0 or not math.isfinite(denominator):
        raise CameraSpecError(
            "focal_length_mm × image_width_px 가 0 으로 언더플로했다 — "
            f"GSD 를 계산할 수 없다 (focal_length_mm={camera.focal_length_mm!r})"
        )
    return (sensor_w_m * altitude_m) / denominator


def footprint_m(camera: CameraSpec, gsd_m: float) -> tuple[float, float]:
    """사진 1장의 지상 촬영범위 ``(across_track_m, along_track_m)``."""
    return camera.image_width_px * gsd_m, camera.image_height_px * gsd_m


def compute_grid_spacing(
    camera: CameraSpec,
    *,
    altitude_m: float,
    front_overlap: float = DEFAULT_FRONT_OVERLAP,
    side_overlap: float = DEFAULT_SIDE_OVERLAP,
) -> GridSpacing:
    """카메라·고도·중복도 → 격자 간격.

        line_spacing  = footprint_across × (1 − side_overlap)
        photo_spacing = footprint_along  × (1 − front_overlap)

    Args:
        front_overlap: 진행방향(라인 내부) 중복도. ``MIN_FRONT_OVERLAP`` 미만은
            거부한다 — 그 아래는 정합점이 부족해 재구성이 실패한다.
        side_overlap: 라인 간 중복도. ``MIN_SIDE_OVERLAP`` 미만은 거부한다.

    Raises:
        CameraSpecError: 중복도가 허용 범위 밖이거나 고도·스펙이 유효하지 않을 때.
    """
    for name, value, minimum in (
        ("front_overlap", front_overlap, MIN_FRONT_OVERLAP),
        ("side_overlap", side_overlap, MIN_SIDE_OVERLAP),
    ):
        if not math.isfinite(value):
            raise CameraSpecError(f"{name} 는 finite 여야 한다 ({value!r})")
        if not (minimum <= value < 1.0):
            # 상한이 1.0 **미만**인 이유: 1.0 이면 간격이 0 이 되어 같은 자리에서
            # 무한히 촬영한다. 하한은 사진측량이 성립하는 경계다.
            raise CameraSpecError(
                f"{name}({value}) 는 [{minimum}, 1.0) 이어야 한다 — "
                "그 아래는 정합점이 부족해 재구성이 실패하고, 1.0 은 간격 0 이다"
            )

    gsd = compute_gsd_m(camera, altitude_m)
    across, along = footprint_m(camera, gsd)
    return GridSpacing(
        spacing_m=across * (1.0 - side_overlap),
        capture_interval_m=along * (1.0 - front_overlap),
        gsd_m=gsd,
        footprint_across_m=across,
        footprint_along_m=along,
    )
