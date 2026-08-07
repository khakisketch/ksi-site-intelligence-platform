"""IFC as-designed 모델 → change-detection baseline point cloud 추출
(Phase 4, PRD §5.1.4 "BIM/as-designed 대비 as-built 변화").

## 방향 — export 가 아니라 import

BIM 연계는 KSI 가 만든 데이터를 IFC 로 **내보내는** 것이 아니다. PRD §5.1.4 는
"BIM/as-designed 대비 as-built 변화"를 요구한다 — 고객이 이미 갖고 있는 설계
모델(as-designed, IFC)을 **읽어서** 재구성 파이프라인의 point cloud(as-built)와
비교하는 것이 방향이다(§5.1.4 "BIM/도면/기존 모델 가져오기"). 이 모듈은 그
읽기 쪽만 담당하고, 산출물(:func:`sample_points_from_ifc`)은
``ksi_change_detection.detect_change_candidates`` 의 ``baseline`` 인자로 그대로
들어간다.

## georeferencing — IfcCoordinateOperation(IfcMapConversion/IfcRigidOperation)

IFC 파일의 로컬 좌표계를 이 프로젝트의 site_frame(세계좌표)으로 변환하려면
IFC4 이상의 IfcCoordinateOperation(IfcMapConversion·IfcMapConversionScaled·
IfcRigidOperation)이 필요하다. ``ifcopenshell.util.geolocation.auto_local2global``
이 이 변환을 표준으로 수행한다 — 이 모듈이 변환 수식을 재구현하지 않는다(실물
왕복 확인 2026-08-06: Eastings/Northings/OrthogonalHeight 평행이동 +
XAxisAbscissa/XAxisOrdinate 회전이 기대한 그대로 동작함을 스크립트로 직접
확인 — 예: Eastings=1000·Northings=2000 설정 후 로컬 원점이 정확히
(1000, 2000, 0)으로 변환됨).

georeferencing 이 없는 IFC 파일은 로컬 좌표를 그대로 반환한다(ifcopenshell
자체 동작 — "If no map conversion is present, then the matrix is returned
unchanged"). :func:`has_georeferencing` 로 이 상태를 먼저 확인하고 호출자가
site_frame 정합 여부를 판단해야 한다 — 조용히 잘못된 좌표계로 비교하지 않는다.
**이 판정은 ``auto_local2global`` 이 실제로 검사하는 조건과 일치해야만 성립한다
— 2026-08-06 reviewer 2라운드가 두 번 이 정합이 깨진 것을 재현했다(1라운드:
IfcProjectedCRS 를 잘못 요구, 2라운드: IfcRigidOperation 을 놓침 — 상세는
:func:`has_georeferencing` docstring). IFC2X3 는 이 판정 자체가 typed 로
거부된다(별도 pset 메커니즘, 이 모듈 범위 밖).**
``sample_points_from_ifc`` 는 ``auto_local2global`` 을 직접 쓰므로 georeferencing
종류(IfcMapConversion 계열이든 IfcRigidOperation 이든)와 무관하게 변환이
정확하다 — 다만 :func:`read_georeference` 로 그 파라미터 값을 "읽는" 것은
IfcMapConversion 계열만 지원한다(IfcRigidOperation 은 필드명 자체가 다르다).

## 지오메트리 샘플링 방식 — 알려진 한계

IfcElement 마다 ``ifcopenshell.geom`` 으로 삼각형 메쉬를 만들고 그 정점(vertex)을
그대로 point cloud 로 쓴다 — 표면 균등 샘플링이 아니라 **메쉬 정점**이라, 큰
평면(정점이 적은 대형 삼각형)은 점 밀도가 낮게 나온다. change-detection 의 C2C
비교는 point-to-point 최근접 거리라 baseline 쪽 밀도에 민감하므로, 이 성긴
샘플링이 결과를 왜곡할 수 있다 — 균등 표면 샘플링(삼각형 내부 리샘플링)은 이
모듈의 범위 밖이다(필요해지면 추가한다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.geolocation as ifc_geolocation
import ifcopenshell.util.unit
import numpy as np
from numpy.typing import NDArray


class IfcReferenceModelError(ValueError):
    """IFC 파일을 열 수 없거나, 추출 가능한 지오메트리가 하나도 없을 때."""


@dataclass(frozen=True, slots=True)
class IfcGeoreference:
    """IFC 파일의 georeferencing 파라미터(IfcMapConversion + IfcProjectedCRS)."""

    projected_crs_name: str
    eastings: float
    northings: float
    orthogonal_height: float


def has_georeferencing(ifc_file: ifcopenshell.file) -> bool:
    """``IfcCoordinateOperation``(IfcMapConversion·IfcMapConversionScaled·
    IfcRigidOperation 의 상위타입) 존재만으로 판정한다 — ``IfcProjectedCRS`` 는
    요구하지 않는다.

    **반드시 ``auto_local2global`` 이 실제로 검사하는 조건과 일치해야 한다** —
    아니면 "georeferencing 없음 ⇒ 로컬 좌표 그대로"라는 계약이 깨진다(2026-08-06
    reviewer 2라운드가 두 번 재현). 이력:

    1라운드: ``IfcMapConversion`` **AND** ``IfcProjectedCRS`` 둘 다 요구 —
    ``IfcProjectedCRS`` 가 없는 half-set 파일에서 ``False`` 를 반환하는데
    ``auto_local2global``(→ ``get_helmert_transformation_parameters``)은
    ``IfcProjectedCRS`` 를 전혀 참조하지 않아 여전히 변환을 적용했다.

    2라운드: ``IfcMapConversion`` 하나만 확인 — ``IfcRigidOperation``(IFC4X3_ADD2,
    ``IfcCoordinateOperation`` 의 **형제** 서브타입이지 ``IfcMapConversion`` 의
    하위타입이 아님, ifcopenshell 스키마 선언 실측 확인)이 있는 파일에서 다시
    ``False`` 를 반환하는데 라이브러리는 여전히 변환을 적용했다. 지금은
    ``IfcCoordinateOperation``(공통 상위타입)으로 검사해 두 서브타입 모두 잡는다.

    IFC2X3 는 ``IfcCoordinateOperation`` 엔티티 자체가 스키마에 없다(ePSet 기반
    별도 메커니즘, ``get_helmert_transformation_parameters`` 의 IFC2X3 분기 참고)
    — ``file.by_type()`` 가 미정의 타입에 ``RuntimeError`` 를 던지므로(ifcopenshell
    실측 확인) 여기서 먼저 typed 로 거부한다. IFC2X3 pset 기반 georeferencing
    지원은 이 모듈의 범위 밖이다(필요해지면 추가한다).

    Raises:
        IfcReferenceModelError: ``ifc_file.schema == "IFC2X3"`` 일 때.
    """
    if ifc_file.schema == "IFC2X3":
        raise IfcReferenceModelError(
            "IFC2X3 스키마는 이 함수가 지원하지 않는다 — IfcCoordinateOperation "
            "엔티티 자체가 없고(ePSet_MapConversion 기반 별도 메커니즘), 이 모듈은 "
            "아직 그 경로를 구현하지 않았다. IFC4 이상 파일로 다시 시도하라"
        )
    return bool(ifc_file.by_type("IfcCoordinateOperation"))


def read_georeference(ifc_file: ifcopenshell.file) -> IfcGeoreference | None:
    """georeferencing 파라미터를 읽는다 — 없으면 ``None``(지어내지 않는다).

    ``IfcMapConversion``·``IfcMapConversionScaled`` 계열만 지원한다(``Eastings``/
    ``Northings``/``OrthogonalHeight`` 필드가 있는 계열) — ``IfcRigidOperation``
    은 ``FirstCoordinate``/``SecondCoordinate``/``Height`` 로 필드명이 달라
    :class:`IfcGeoreference` 로 그대로 옮길 수 없으므로 typed 로 거부한다.
    ``sample_points_from_ifc`` 는 이 함수를 거치지 않고
    ``ifcopenshell.util.geolocation.auto_local2global`` 을 직접 쓰므로
    ``IfcRigidOperation`` 파일에서도 변환 자체는 정확하다 — 이 함수만 파라미터
    "읽기"를 못 한다.

    ``IfcProjectedCRS`` 는 있으면 이름을 채우고, 없으면(half-set) 빈 문자열로
    둔다 — 변환 적용 여부와는 무관한 부가 정보다.

    Raises:
        IfcReferenceModelError: ``ifc_file.schema == "IFC2X3"``(has_georeferencing
            경유) 이거나, coordinate operation 이 ``IfcMapConversion`` 계열이
            아닐 때(예: ``IfcRigidOperation``).
    """
    if not has_georeferencing(ifc_file):
        return None
    conversion = ifc_file.by_type("IfcCoordinateOperation")[0]
    if not conversion.is_a("IfcMapConversion"):
        raise IfcReferenceModelError(
            f"{conversion.is_a()} 기반 georeferencing 은 read_georeference() 가 "
            "아직 지원하지 않는다(IfcMapConversion 계열만 지원) — "
            "sample_points_from_ifc() 의 좌표 변환 자체는 auto_local2global 이 "
            "내부적으로 처리하므로 영향받지 않는다"
        )
    crs_candidates = ifc_file.by_type("IfcProjectedCRS")
    crs_name = (crs_candidates[0].Name or "") if crs_candidates else ""
    return IfcGeoreference(
        projected_crs_name=crs_name,
        eastings=float(conversion.Eastings),
        northings=float(conversion.Northings),
        orthogonal_height=float(conversion.OrthogonalHeight or 0.0),
    )


def _length_unit_scale_to_meters(ifc_file: ifcopenshell.file, ifc_path: Path) -> float:
    """프로젝트 길이 단위 → SI 미터 배율. mm 파일이면 0.001, m 파일이면 1.0.

    ``calculate_unit_scale`` 은 단위 선언이 없으면 1.0 을 돌려준다 — 그건 "미터"가
    아니라 **"모른다"**이고, 그 둘을 같게 취급하면 mm 파일이 단위 선언만 빠뜨려도
    조용히 1000배 틀린 좌표가 된다. 그래서 IfcUnitAssignment 의 LENGTHUNIT 존재를
    직접 확인하고, 없으면 거부한다.
    """
    assignment = ifcopenshell.util.unit.get_unit_assignment(ifc_file)
    has_length_unit = assignment is not None and any(
        getattr(unit, "UnitType", None) == "LENGTHUNIT" for unit in (assignment.Units or ())
    )
    if not has_length_unit:
        raise IfcReferenceModelError(
            f"{ifc_path}: 길이 단위(LENGTHUNIT)가 선언돼 있지 않다 — 좌표를 미터로 "
            "환산할 수 없다. '선언 없음'을 미터로 가정하면 mm 파일이 1000배 틀린 "
            "좌표로 조용히 통과한다"
        )
    scale = float(ifcopenshell.util.unit.calculate_unit_scale(ifc_file))
    if not math.isfinite(scale) or scale <= 0:
        raise IfcReferenceModelError(
            f"{ifc_path}: 길이 단위 배율이 유효하지 않다 (got {scale!r})"
        )
    return scale


def sample_points_from_ifc(ifc_path: Path) -> NDArray[np.float64]:
    """IFC 파일의 모든 IfcElement 지오메트리 정점을 site_frame(map) 좌표로 **미터**
    단위로 추출한다.

    ## 단위를 미터로 정규화한다 — 이 함수의 반환 계약이다

    IFC 는 프로젝트 길이 단위를 파일 안에 선언하고, 건축 IFC 는 **밀리미터가 흔하다**.
    그 좌표를 그대로 돌려주면 소비자인
    :func:`~ksi_change_detection.point_cloud_diff.detect_change_candidates` 의
    ``distance_threshold_m`` 가 1000배 어긋난 공간에서 비교하게 된다 — 0.05m 문턱이
    사실상 50m 문턱이 되어 **어떤 변화도 후보로 잡히지 않는다.** 값은 전부 유한하고
    형상도 멀쩡해서, 그 결과는 "변화 없음"이라는 정직한 답처럼 보인다
    (risk ``bim-unit-of-measurement-untested``).

    그래서 ``ifcopenshell.util.unit.calculate_unit_scale`` 로 프로젝트 단위 → SI 미터
    배율을 읽어 곱한다. 이 변환은 근사가 아니라 파일이 선언한 값에 따른 정확한 환산이고,
    미터 파일이면 배율이 1.0 이라 아무것도 바뀌지 않는다.

    **곱하는 시점이 중요하다 — georeference 변환 *전*이다.** ``auto_local2global`` 의
    출력은 두 부분이 섞여 있다: map 변환(IfcMapConversion 의 Eastings/Northings, map
    CRS 단위 = 미터)과 로컬 지오메트리(프로젝트 단위). 변환 *후*에 한 번 곱하면 이미
    미터인 map 변환까지 같이 줄어들어 좌표가 통째로 어긋난다 — mm 프로젝트에서
    실측하면 (1000, 2000, 50) 이 (1, 2, 0.05) 가 된다. 변환 전에 로컬 정점만 미터로
    바꾸면 두 분기 모두 일관되게 미터가 된다(2026-08-08 실측:
    georeference 없음 → 0.001, 있음 → 1000.001).

    georeferencing 이 없으면 로컬 좌표를 (미터로 환산해) 그대로 반환한다 —
    호출자가 :func:`has_georeferencing` 로 미리 확인해야 한다.

    IFC2X3 는 :func:`has_georeferencing` 과 같은 이유로 거부한다 — 판정 함수는
    거부하는데 변환 함수는 조용히 좌표를 내놓으면, 호출자가 판정을 건너뛴 경로에서만
    다른 동작을 보게 된다(risk ``bim-sample-points-ifc2x3-asymmetry``).

    Raises:
        IfcReferenceModelError: 파일을 열 수 없거나(``ifcopenshell.open`` 실패),
            IFC2X3 스키마이거나, 길이 단위를 읽을 수 없거나, 지오메트리를 가진 요소가
            하나도 없을 때.
    """
    try:
        ifc_file = ifcopenshell.open(str(ifc_path))
    except Exception as exc:  # noqa: BLE001 — ifcopenshell 이 다양한 파서 예외를 던진다
        raise IfcReferenceModelError(f"IFC 파일을 열 수 없다: {ifc_path} ({exc})") from exc

    if ifc_file.schema == "IFC2X3":
        raise IfcReferenceModelError(
            "IFC2X3 스키마는 이 함수가 지원하지 않는다 — has_georeferencing() 이 같은 "
            "이유로 거부하는데 여기서만 좌표를 내놓으면, 판정을 건너뛴 호출 경로에서만 "
            f"다르게 동작한다 ({ifc_path})"
        )

    unit_scale = _length_unit_scale_to_meters(ifc_file, ifc_path)

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)

    world_points: list[list[float]] = []
    for element in ifc_file.by_type("IfcElement"):
        if not element.Representation:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
        except RuntimeError:
            # 이 요소 하나의 지오메트리 생성 실패로 전체를 죽이지 않는다 —
            # 프레임 1장 실패가 배치를 안 죽이는 원칙(dfine.py)과 동형.
            continue
        # ifcopenshell.geom.create_shape 의 반환 타입은 백엔드별 Union 이라 정적으로
        # 좁혀지지 않는다 — settings 기본값(triangulation 백엔드)에서는 항상
        # .geometry.verts 를 갖는 실측 동작이다(2026-08-06 왕복 스크립트 확인).
        geometry = shape.geometry  # type: ignore[union-attr]
        verts = np.array(geometry.verts, dtype=np.float64).reshape(-1, 3)  # type: ignore[union-attr]
        for vertex in verts:
            local_matrix = np.eye(4)
            # 미터 환산은 여기서 — auto_local2global 이 map 변환을 얹기 **전**이다
            # (docstring "곱하는 시점이 중요하다").
            local_matrix[:3, 3] = vertex * unit_scale
            global_matrix = ifc_geolocation.auto_local2global(ifc_file, local_matrix)
            world_points.append(global_matrix[:3, 3].tolist())

    if not world_points:
        raise IfcReferenceModelError(
            f"{ifc_path}: 지오메트리를 가진 IfcElement 가 하나도 없다 — "
            "빈 as-designed 모델로는 비교 baseline 을 만들 수 없다"
        )
    return np.array(world_points, dtype=np.float64)


__all__ = [
    "IfcGeoreference",
    "IfcReferenceModelError",
    "has_georeferencing",
    "read_georeference",
    "sample_points_from_ifc",
]
