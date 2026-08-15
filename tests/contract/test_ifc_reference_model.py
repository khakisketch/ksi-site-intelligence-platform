"""IFC as-designed 모델 추출 (Phase 4, PRD §5.1.4) — georeferencing 변환·지오메트리
추출이 실제로 맞는지 실물 IFC 파일(ifcopenshell 로 직접 조립)로 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.georeference
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import numpy as np
import pytest
from ksi_bim_integration.ifc_reference_model import (
    IfcReferenceModelError,
    has_georeferencing,
    read_georeference,
    sample_points_from_ifc,
)


def _build_ifc(
    tmp_path: Path,
    *,
    name: str,
    georeference: dict[str, float] | None = None,
    add_element: bool = True,
    length_prefix: str | None = None,
    assign_units: bool = True,
    assign_map_unit: bool = True,
    scale_override: float | None = None,
) -> Path:
    """최소 IFC4 파일을 조립한다 — Project+Site+Building(+선택적 요소 지오메트리).

    ``length_prefix="MILLI"`` 면 프로젝트 길이 단위가 mm 가 된다(건축 IFC 의 흔한
    기본값). ``assign_units=False`` 면 단위 선언 자체를 넣지 않는다.
    """
    f = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Test Project")
    if assign_units:
        # **명시적 METRE 가 기본이다.** ifcopenshell 의 assign_unit() 기본은 밀리미터라
        # (2026-08-08 실측: calculate_unit_scale=0.001), 예전 픽스처는 mm 프로젝트를
        # 만들어놓고 그 좌표를 미터로 읽고 있었다 — 단위 정규화가 없으니 숫자가 맞아
        # 보였을 뿐이다. 기본을 미터로 못박아 테스트가 어느 단위를 말하는지 분명히 한다.
        length_unit = ifcopenshell.api.unit.add_si_unit(
            f, unit_type="LENGTHUNIT", prefix=length_prefix
        )
        ifcopenshell.api.unit.assign_unit(f, units=[length_unit])
    model_context = ifcopenshell.api.context.add_context(f, context_type="Model")
    body_context = ifcopenshell.api.context.add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")

    if georeference is not None:
        ifcopenshell.api.georeference.add_georeferencing(f)
        projected_crs: dict[str, object] = {"Name": "EPSG:5186"}
        if assign_map_unit:
            # EPSG:5186 좌표는 m다. 이름만으로 단위를 추론하지 않고 IFC에 명시한다.
            projected_crs["MapUnit"] = ifcopenshell.api.unit.add_si_unit(
                f, unit_type="LENGTHUNIT"
            )
        ifcopenshell.api.georeference.edit_georeferencing(
            f,
            projected_crs=projected_crs,
            coordinate_operation={
                "Eastings": georeference["eastings"],
                "Northings": georeference["northings"],
                "OrthogonalHeight": georeference["orthogonal_height"],
                "XAxisAbscissa": 1.0,
                "XAxisOrdinate": 0.0,
                # IfcMapConversion.Scale 은 project unit → map unit 배율이다. map CRS
                # (EPSG:5186)는 m이므로 mm 프로젝트는 0.001, m 프로젝트는 1.0.
                # scale_override 는 이 자동계산을 대체한다 — 잘못된 값(0 이하)이나
                # 단위비가 아닌 실측량(측량 결합축척)을 직접 시험할 때 쓴다.
                "Scale": (
                    scale_override
                    if scale_override is not None
                    else (0.001 if length_prefix == "MILLI" and assign_map_unit else 1.0)
                ),
            },
        )

    if add_element:
        element = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcBuildingElementProxy", name="TestElement"
        )
        verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        faces = [[[0, 1, 2]]]
        rep = ifcopenshell.api.geometry.add_mesh_representation(
            f, body_context, vertices=[verts], faces=faces
        )
        ifcopenshell.api.geometry.assign_representation(f, element, rep)

    path = tmp_path / f"{name}.ifc"
    f.write(str(path))
    return path


# ── georeferencing ────────────────────────────────────────────────────────────


def test_has_georeferencing_true_when_map_conversion_present(tmp_path: Path) -> None:
    path = _build_ifc(
        tmp_path,
        name="georef",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 50.0},
    )
    f = ifcopenshell.open(str(path))
    assert has_georeferencing(f) is True


def test_has_georeferencing_false_when_absent(tmp_path: Path) -> None:
    path = _build_ifc(tmp_path, name="no_georef", georeference=None)
    f = ifcopenshell.open(str(path))
    assert has_georeferencing(f) is False


def test_has_georeferencing_true_when_projected_crs_absent_half_set(tmp_path: Path) -> None:
    """[핵심] half-set: IfcMapConversion 만 있고 IfcProjectedCRS 는 없어도 True 여야
    한다 — auto_local2global(→get_helmert_transformation_parameters)은
    IfcProjectedCRS 를 전혀 참조하지 않고 IfcMapConversion 만으로 변환을 적용하므로
    (ifcopenshell 소스 실측), has_georeferencing() 이 여기서 False 를 반환하면
    sample_points_from_ifc() 는 여전히 변환을 적용하는데 호출자는 "로컬 좌표"라고
    오판하게 된다(2026-08-06 reviewer 반증으로 실제 재현됨 — 이전 구현은 두 엔티티를
    AND 로 요구해 이 케이스에서 False 를 반환했다)."""
    path = _build_ifc(
        tmp_path,
        name="half_set",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
    )
    f = ifcopenshell.open(str(path))
    crs = f.by_type("IfcProjectedCRS")[0]
    f.remove(crs)
    assert f.by_type("IfcProjectedCRS") == []
    assert f.by_type("IfcMapConversion") != []
    assert has_georeferencing(f) is True


def test_sample_points_applies_transform_when_projected_crs_absent(tmp_path: Path) -> None:
    """[핵심] half-set 에서도 sample_points_from_ifc 가 여전히 map 변환을 적용한다 —
    위 test_has_georeferencing_true_when_projected_crs_absent_half_set 이 True 를
    반환하는 것과 짝을 이뤄 "has_georeferencing()==True ⇒ 실제로 변환된 좌표"
    계약을 고정한다."""
    path = _build_ifc(
        tmp_path,
        name="half_set_sample",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
    )
    f = ifcopenshell.open(str(path))
    crs = f.by_type("IfcProjectedCRS")[0]
    f.remove(crs)
    f.write(str(path))

    assert has_georeferencing(ifcopenshell.open(str(path))) is True
    points = sample_points_from_ifc(path)
    expected = {(1000.0, 2000.0, 0.0), (1001.0, 2000.0, 0.0), (1000.0, 2001.0, 0.0)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_read_georeference_returns_none_when_absent(tmp_path: Path) -> None:
    path = _build_ifc(tmp_path, name="no_georef2", georeference=None)
    f = ifcopenshell.open(str(path))
    assert read_georeference(f) is None


def test_read_georeference_matches_written_parameters(tmp_path: Path) -> None:
    path = _build_ifc(
        tmp_path,
        name="georef2",
        georeference={"eastings": 335087.17, "northings": 6251635.41, "orthogonal_height": 12.5},
    )
    f = ifcopenshell.open(str(path))
    result = read_georeference(f)
    assert result is not None
    assert result.eastings == pytest.approx(335087.17)
    assert result.northings == pytest.approx(6251635.41)
    assert result.orthogonal_height == pytest.approx(12.5)
    assert result.projected_crs_name == "EPSG:5186"


# ── sample_points_from_ifc ──────────────────────────────────────────────────


def test_sample_points_applies_georeference_translation(tmp_path: Path) -> None:
    """[핵심] 손계산: georeference Eastings=1000·Northings=2000 이면 로컬 삼각형
    (0,0,0),(1,0,0),(0,1,0) 의 정점이 (1000,2000,H),(1001,2000,H),(1000,2001,H)
    로 이동해야 한다 — 실물 IFC 파일 왕복으로 확인(2026-08-06 스크립트 검증과 동일)."""
    path = _build_ifc(
        tmp_path,
        name="sample1",
        georeference={"eastings": 1000.0, "northings": 2000.0, "orthogonal_height": 0.0},
    )
    points = sample_points_from_ifc(path)
    assert points.shape == (3, 3)
    expected = {(1000.0, 2000.0, 0.0), (1001.0, 2000.0, 0.0), (1000.0, 2001.0, 0.0)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_sample_points_without_georeference_returns_local_coordinates(tmp_path: Path) -> None:
    path = _build_ifc(tmp_path, name="sample2", georeference=None)
    points = sample_points_from_ifc(path)
    expected = {(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_sample_points_rejects_file_with_no_geometry(tmp_path: Path) -> None:
    path = _build_ifc(tmp_path, name="empty", georeference=None, add_element=False)
    with pytest.raises(IfcReferenceModelError, match="지오메트리를 가진"):
        sample_points_from_ifc(path)


def test_sample_points_rejects_unopenable_file(tmp_path: Path) -> None:
    bad_path = tmp_path / "not_ifc.ifc"
    bad_path.write_text("this is not a valid IFC file", encoding="utf-8")
    with pytest.raises(IfcReferenceModelError, match="열 수 없다"):
        sample_points_from_ifc(bad_path)


def test_sample_points_feed_directly_into_change_detection(tmp_path: Path) -> None:
    """[통합] as-designed(IFC) 점군이 change-detection baseline 으로 그대로 쓰인다
    (PRD §5.1.4 "BIM/as-designed 대비 as-built 변화")."""
    from ksi_change_detection.point_cloud_diff import detect_change_candidates

    path = _build_ifc(
        tmp_path,
        name="sample3",
        georeference={"eastings": 0.0, "northings": 0.0, "orthogonal_height": 0.0},
    )
    baseline = sample_points_from_ifc(path)  # as-designed
    current = baseline.copy()
    current[0] += [10.0, 0.0, 0.0]  # as-built 쪽 한 점이 시공 중 이동(예: 자재 반입)

    result = detect_change_candidates(baseline=baseline, current=current, distance_threshold_m=1.0)
    assert result.candidate_count == 1
    assert bool(result.is_candidate[0]) is True


def test_georeference_rotation_matches_hand_derivation(tmp_path: Path) -> None:
    """[핵심] XAxisOrdinate=1(90도 회전) 이면 로컬 x축이 site_frame y축으로
    간다 — 로컬 (1,0,0) 은 Eastings 변화 없이 Northings 만 +1 되어야 한다."""
    f = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f)
    ifcopenshell.api.context.add_context(f, context_type="Model")
    ifcopenshell.api.georeference.add_georeferencing(f)
    ifcopenshell.api.georeference.edit_georeferencing(
        f,
        projected_crs={"Name": "EPSG:5186"},
        coordinate_operation={
            "Eastings": 1000.0,
            "Northings": 2000.0,
            "OrthogonalHeight": 0.0,
            "XAxisAbscissa": 0.0,
            "XAxisOrdinate": 1.0,
            "Scale": 1.0,
        },
    )
    import ifcopenshell.util.geolocation as geo

    local = np.eye(4)
    local[0, 3] = 1.0  # 로컬 x=1
    global_matrix = geo.auto_local2global(f, local)
    assert global_matrix[:3, 3] == pytest.approx([1000.0, 2001.0, 0.0])


# ── IfcRigidOperation(IFC4X3_ADD2) — IfcMapConversion 의 형제 서브타입 ─────────
# 2026-08-07 reviewer 2라운드 반증: has_georeferencing() 가 IfcMapConversion 만
# 확인해 IfcRigidOperation 이 있는 파일에서 다시 False 오판(1라운드의 같은
# 결함 클래스가 다른 서브타입으로 재발) — IfcCoordinateOperation(공통 상위타입)
# 검사로 정정.


def _build_ifc_with_rigid_operation(
    tmp_path: Path,
    *,
    length_prefix: str | None = None,
    assign_map_unit: bool = False,
    map_unit_prefix: str | None = None,
) -> Path:
    """IfcRigidOperation 은 edit_georeferencing() 의 coordinate_operation 딕셔너리로
    못 채운다 — FirstCoordinate/SecondCoordinate 가 IfcMeasureValue(SELECT) 타입이라
    맨 float 대입이 거부된다(ifcopenshell 실측). 저수준 속성 대입으로 직접 채운다.

    ``assign_map_unit=True`` 면 TargetCRS 에 명시적 MapUnit 을 붙인다 —
    IfcRigidOperation 은 Scale 필드가 없어 project/target 단위가 다르면 다리를
    놓을 방법이 없다(``map_unit_prefix`` 로 그 불일치를 만든다).
    """
    # ifcopenshell 의 create_file 타입 스텁은 "IFC4X3_ADD2" 를 선언하지 않지만
    # (IFC2X3/IFC4/IFC4X3 셋만 나열) 런타임은 실제로 받는다(직접 실측 확인,
    # 결과 f.schema 는 "IFC4X3" 로 보고됨) — IfcRigidOperation 자체가 이 애드온
    # 버전에서만 정의돼 있어 이 값이 필요하다.
    f = ifcopenshell.api.project.create_file(version="IFC4X3_ADD2")  # type: ignore[arg-type]
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    # _build_ifc 와 같은 이유로 METRE 를 명시한다 — assign_unit() 기본은 mm 다.
    ifcopenshell.api.unit.assign_unit(
        f,
        units=[
            ifcopenshell.api.unit.add_si_unit(
                f,
                unit_type="LENGTHUNIT",
                prefix=length_prefix,
            )
        ],
    )
    ifcopenshell.api.context.add_context(f, context_type="Model")
    ifcopenshell.api.georeference.add_georeferencing(f, ifc_class="IfcRigidOperation")
    op = f.by_type("IfcRigidOperation")[0]
    op.FirstCoordinate = f.createIfcLengthMeasure(1000.0)
    op.SecondCoordinate = f.createIfcLengthMeasure(2000.0)
    op.Height = 50.0
    if assign_map_unit:
        target_crs = op.TargetCRS
        target_crs.MapUnit = ifcopenshell.api.unit.add_si_unit(
            f, unit_type="LENGTHUNIT", prefix=map_unit_prefix
        )
    path = tmp_path / "rigid_operation.ifc"
    f.write(str(path))
    return path


def test_has_georeferencing_true_for_ifc_rigid_operation(tmp_path: Path) -> None:
    """[핵심, 회귀] IfcRigidOperation 은 IfcMapConversion 의 하위타입이 **아니라**
    형제 서브타입이다(ifcopenshell 스키마 선언 실측: 둘 다 IfcCoordinateOperation
    의 직계 서브타입) — IfcMapConversion 만 확인하면 다시 오판한다."""
    path = _build_ifc_with_rigid_operation(tmp_path)
    f = ifcopenshell.open(str(path))
    assert f.by_type("IfcMapConversion") == []  # IfcMapConversion 관점에선 없음
    assert f.by_type("IfcRigidOperation") != []
    assert has_georeferencing(f) is True


def test_sample_points_applies_transform_for_ifc_rigid_operation(tmp_path: Path) -> None:
    """[핵심] auto_local2global 은 IfcRigidOperation 도 정확히 처리한다(손계산:
    FirstCoordinate=1000·SecondCoordinate=2000·Height=50 이면 로컬 원점이
    정확히 (1000,2000,50)로 이동) — sample_points_from_ifc 가 이 변환을 그대로
    쓰므로 지오메트리도 정확히 이동해야 한다."""
    path = _build_ifc_with_rigid_operation(tmp_path)
    # 지오메트리를 가진 요소를 추가해야 sample_points_from_ifc 가 빈 결과로
    # 거부하지 않는다 — 별도 헬퍼로 조립(georeference 파라미터가 다른 형태라
    # _build_ifc 를 재사용할 수 없다).
    f = ifcopenshell.open(str(path))
    model_context = f.by_type("IfcGeometricRepresentationContext")[0]
    element = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingElementProxy", name="E"
    )
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    faces = [[[0, 1, 2]]]
    rep = ifcopenshell.api.geometry.add_mesh_representation(
        f, model_context, vertices=[verts], faces=faces
    )
    ifcopenshell.api.geometry.assign_representation(f, element, rep)
    path2 = tmp_path / "rigid_operation_with_geom.ifc"
    f.write(str(path2))

    assert has_georeferencing(ifcopenshell.open(str(path2))) is True
    points = sample_points_from_ifc(path2)
    expected = {(1000.0, 2000.0, 50.0), (1001.0, 2000.0, 50.0), (1000.0, 2001.0, 50.0)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_millimetre_ifc_rigid_operation_output_is_normalized_to_metres(
    tmp_path: Path,
) -> None:
    """[high-risk regression] RigidOperation은 Scale이 없고 MapUnit도 생략된다.

    좌표는 project unit인 mm이므로 FirstCoordinate=1000은 최종 1m다. geometry
    engine의 1m 정점을 1000mm로 복원해 rigid 변환한 뒤, 출력을 다시 m로 바꾼다.
    """
    path = _build_ifc_with_rigid_operation(tmp_path, length_prefix="MILLI")
    f = ifcopenshell.open(str(path))
    model_context = f.by_type("IfcGeometricRepresentationContext")[0]
    element = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingElementProxy", name="E-mm"
    )
    rep = ifcopenshell.api.geometry.add_mesh_representation(
        f,
        model_context,
        vertices=[[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]],
        faces=[[[0, 1, 2]]],
    )
    ifcopenshell.api.geometry.assign_representation(f, element, rep)
    path2 = tmp_path / "rigid_operation_mm_with_geom.ifc"
    f.write(str(path2))

    points = sample_points_from_ifc(path2)
    expected = {(1.0, 2.0, 0.05), (2.0, 2.0, 0.05), (1.0, 3.0, 0.05)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_read_georeference_rejects_ifc_rigid_operation(tmp_path: Path) -> None:
    """read_georeference() 는 IfcMapConversion 계열만 지원 — IfcRigidOperation 은
    필드명이 달라(FirstCoordinate 대 Eastings) typed 로 거부한다(크래시 아님)."""
    path = _build_ifc_with_rigid_operation(tmp_path)
    f = ifcopenshell.open(str(path))
    with pytest.raises(IfcReferenceModelError, match="IfcRigidOperation"):
        read_georeference(f)


def test_rigid_operation_rejects_source_target_unit_mismatch(tmp_path: Path) -> None:
    """IfcRigidOperation에는 Scale이 없으므로 mm source를 m target으로 옮길 수 없다."""
    path = _build_ifc_with_rigid_operation(
        tmp_path,
        length_prefix="MILLI",
        assign_map_unit=True,
        map_unit_prefix=None,
    )
    with pytest.raises(IfcReferenceModelError, match="source/target 길이 단위"):
        sample_points_from_ifc(path)


def test_rigid_operation_rejects_geographic_angle_target(tmp_path: Path) -> None:
    """geographic longitude/latitude를 metre geometry로 가장하지 않는다."""
    path = _build_ifc_with_rigid_operation(tmp_path)
    f = ifcopenshell.open(str(path))
    angle_unit = ifcopenshell.api.unit.add_si_unit(f, unit_type="PLANEANGLEUNIT")
    height_unit = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
    geographic = f.create_entity(
        "IfcGeographicCRS",
        Name="EPSG:4326",
        GeodeticDatum="World Geodetic System 1984",
        PrimeMeridian="Greenwich",
        AngleUnit=angle_unit,
        HeightUnit=height_unit,
    )
    f.by_type("IfcRigidOperation")[0].TargetCRS = geographic
    f.write(str(path))

    with pytest.raises(IfcReferenceModelError, match="projected length 좌표"):
        sample_points_from_ifc(path)


def test_has_georeferencing_rejects_ifc2x3() -> None:
    """[핵심, 회귀] IFC2X3 는 IfcCoordinateOperation 엔티티 자체가 스키마에 없다
    (``file.by_type()`` 가 미정의 타입에 RuntimeError 를 던진다는 것을 ifcopenshell
    실측으로 확인) — 조용히 False 나 크래시가 아니라 typed 로 거부한다.

    ``has_georeferencing()`` 은 ``ifc_file.schema`` 만 보고 판정하므로 유효한
    IfcProject 조립 없이(IFC2X3 는 OwnerHistory 용 User 조립이 별도로 필요해
    이 테스트 목적과 무관한 복잡도를 더한다) 빈 IFC2X3 파일로도 충분하다.
    """
    f = ifcopenshell.api.project.create_file(version="IFC2X3")
    with pytest.raises(IfcReferenceModelError, match="IFC2X3"):
        has_georeferencing(f)


# ── 길이 단위 정규화 (risk bim-unit-of-measurement-untested) ──────────────────
#
# IFC 는 프로젝트 길이 단위를 파일 안에 선언하고 건축 IFC 는 mm 가 흔하다. 그 좌표를
# 그대로 넘기면 detect_change_candidates(distance_threshold_m=...) 가 1000배 어긋난
# 공간에서 비교한다 — 0.05m 문턱이 사실상 50m 문턱이 되어 어떤 변화도 안 잡힌다.
# 값은 전부 유한하고 형상도 멀쩡해서 그 결과는 "변화 없음"이라는 정직한 답처럼 보인다.


def test_millimetre_project_is_returned_in_metres(tmp_path: Path) -> None:
    """[핵심] mm IFC에 저장된 1000mm 정점이 1.0m 로 나온다.

    ifcopenshell ``add_mesh_representation`` 입력은 파일 단위와 무관하게 SI(m)다.
    따라서 이 픽스처의 입력 1.0은 mm 파일 안에 1000.0으로 저장되고 geometry
    engine은 다시 1.0m로 반환한다. 예전 기대값 0.001은 이 API 계약을 거꾸로 읽어
    단위 이중 적용 결함을 정답으로 고정하고 있었다.
    """
    metres = _build_ifc(tmp_path, name="unit_m")
    millis = _build_ifc(tmp_path, name="unit_mm", length_prefix="MILLI")

    m_points = sample_points_from_ifc(metres)
    mm_points = sample_points_from_ifc(millis)

    raw_mm = ifcopenshell.open(str(millis)).by_type("IfcCartesianPointList3D")[0].CoordList
    assert np.abs(np.asarray(raw_mm)).max() == pytest.approx(1000.0)
    assert np.isclose(np.abs(m_points).max(), 1.0)
    assert np.isclose(np.abs(mm_points).max(), 1.0)


def test_millimetre_georeference_applies_length_scale_exactly_once(tmp_path: Path) -> None:
    """[high-risk regression] geometry engine은 mm IFC 정점을 이미 m로 반환한다.

    그 값에 0.001을 다시 곱하고 MapConversion.Scale까지 적용하면 1m 변이 1µm가
    된다. 표준 변환에는 원래 project unit(1000mm)을 넣어 map offset 1m를 얻는다.
    """
    origin = np.array([1000.0, 2000.0, 50.0])
    path = _build_ifc(
        tmp_path,
        name="unit_mm_georeferenced",
        length_prefix="MILLI",
        georeference={
            "eastings": origin[0],
            "northings": origin[1],
            "orthogonal_height": origin[2],
        },
    )

    points = sample_points_from_ifc(path)
    offsets = points - origin
    assert np.abs(offsets).max() == pytest.approx(1.0)
    assert any(np.allclose(offset, [1.0, 0.0, 0.0]) for offset in offsets)
    assert any(np.allclose(offset, [0.0, 1.0, 0.0]) for offset in offsets)


def test_millimetre_georeference_without_map_unit_uses_project_unit(
    tmp_path: Path,
) -> None:
    """[high-risk regression] TargetCRS는 있지만 MapUnit이 없으면 project unit 폴백이다.

    mm 프로젝트에서 map translation 1000/2000/50과 Scale=1은 각각
    1m/2m/0.05m다. 변환 결과를 그대로 미터로 읽으면 반대로 1000배 커진다.
    """
    path = _build_ifc(
        tmp_path,
        name="unit_mm_georeferenced_without_map_unit",
        length_prefix="MILLI",
        assign_map_unit=False,
        georeference={
            "eastings": 1000.0,
            "northings": 2000.0,
            "orthogonal_height": 50.0,
        },
    )
    f = ifcopenshell.open(str(path))
    assert f.by_type("IfcProjectedCRS")[0].MapUnit is None
    assert f.by_type("IfcMapConversion")[0].Scale == pytest.approx(1.0)

    points = sample_points_from_ifc(path)
    expected = {(1.0, 2.0, 0.05), (2.0, 2.0, 0.05), (1.0, 3.0, 0.05)}
    actual = {tuple(round(v, 6) for v in row) for row in points}
    assert actual == expected


def test_map_conversion_rejects_non_positive_scale(tmp_path: Path) -> None:
    """ifcopenshell의 ``Scale or 1`` fallback이 잘못된 0을 정상값으로 숨기지 못한다."""
    path = _build_ifc(
        tmp_path,
        name="invalid_scale",
        georeference={
            "eastings": 0.0,
            "northings": 0.0,
            "orthogonal_height": 0.0,
        },
        scale_override=0.0,
    )
    with pytest.raises(IfcReferenceModelError, match="유효한 양수"):
        sample_points_from_ifc(path)


def test_map_conversion_preserves_non_unit_survey_scale(tmp_path: Path) -> None:
    """Scale은 단위비만이 아니라 측량 결합 축척도 포함할 수 있어 원값을 존중한다."""
    path = _build_ifc(
        tmp_path,
        name="survey_scale",
        georeference={
            "eastings": 1000.0,
            "northings": 2000.0,
            "orthogonal_height": 0.0,
        },
        scale_override=0.9996,
    )
    points = sample_points_from_ifc(path)
    assert any(np.allclose(point, [1000.9996, 2000.0, 0.0]) for point in points)


def test_metre_project_is_unchanged(tmp_path: Path) -> None:
    """미터 파일이면 배율이 1.0 이라 값이 그대로다 — 정규화가 기존 동작을 바꾸지 않는다."""
    path = _build_ifc(tmp_path, name="unit_identity")
    points = sample_points_from_ifc(path)
    assert np.isclose(np.abs(points).max(), 1.0)


def test_missing_length_unit_is_rejected(tmp_path: Path) -> None:
    """'단위 선언 없음'을 미터로 가정하지 않는다 — 그러면 mm 파일이 선언만 빠뜨려도
    1000배 틀린 좌표로 조용히 통과한다."""
    path = _build_ifc(tmp_path, name="unit_missing", assign_units=False)
    with pytest.raises(IfcReferenceModelError, match="LENGTHUNIT"):
        sample_points_from_ifc(path)


def test_threshold_comparison_is_meaningful_after_normalisation(tmp_path: Path) -> None:
    """[소비자 관점] 같은 물리 형상의 mm/m 파일은 같은 문턱에서 같게 판정된다.

    이 테스트가 없으면 "미터로 돌려준다"가 이 함수 안에서만 참이고, 실제 소비자인
    변화탐지가 그 값을 어떻게 쓰는지는 아무도 확인하지 않는다.
    """
    from ksi_change_detection.point_cloud_diff import detect_change_candidates

    baseline = sample_points_from_ifc(_build_ifc(tmp_path, name="cmp_m"))
    # 같은 1m 형상을 mm 프로젝트에 저장하면 raw IFC 좌표는 1000이지만 반환은 1m다.
    scaled = sample_points_from_ifc(_build_ifc(tmp_path, name="cmp_mm", length_prefix="MILLI"))

    # 같은 물리 형상끼리는 당연히 후보가 없어야 한다.
    near = detect_change_candidates(
        baseline=baseline, current=baseline, distance_threshold_m=0.5
    )
    assert near.candidate_count == 0

    cross_unit = detect_change_candidates(
        baseline=scaled, current=baseline, distance_threshold_m=0.5
    )
    assert cross_unit.candidate_count == 0


# ── IFC2X3 대칭 (risk bim-sample-points-ifc2x3-asymmetry) ─────────────────────


def test_sample_points_rejects_ifc2x3_like_has_georeferencing(tmp_path: Path) -> None:
    """판정 함수는 거부하는데 변환 함수는 좌표를 내놓으면, 판정을 건너뛴 호출
    경로에서만 다르게 동작한다 — 같은 스키마 커버리지를 갖는다."""
    f = ifcopenshell.api.project.create_file(version="IFC2X3")
    path = tmp_path / "legacy.ifc"
    f.write(str(path))
    with pytest.raises(IfcReferenceModelError, match="IFC2X3"):
        sample_points_from_ifc(path)
