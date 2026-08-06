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
) -> Path:
    """최소 IFC4 파일을 조립한다 — Project+Site+Building(+선택적 요소 지오메트리)."""
    f = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Test Project")
    ifcopenshell.api.unit.assign_unit(f)
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
        ifcopenshell.api.georeference.edit_georeferencing(
            f,
            projected_crs={"Name": "EPSG:5186"},
            coordinate_operation={
                "Eastings": georeference["eastings"],
                "Northings": georeference["northings"],
                "OrthogonalHeight": georeference["orthogonal_height"],
                "XAxisAbscissa": 1.0,
                "XAxisOrdinate": 0.0,
                "Scale": 1.0,
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


def _build_ifc_with_rigid_operation(tmp_path: Path) -> Path:
    """IfcRigidOperation 은 edit_georeferencing() 의 coordinate_operation 딕셔너리로
    못 채운다 — FirstCoordinate/SecondCoordinate 가 IfcMeasureValue(SELECT) 타입이라
    맨 float 대입이 거부된다(ifcopenshell 실측). 저수준 속성 대입으로 직접 채운다."""
    # ifcopenshell 의 create_file 타입 스텁은 "IFC4X3_ADD2" 를 선언하지 않지만
    # (IFC2X3/IFC4/IFC4X3 셋만 나열) 런타임은 실제로 받는다(직접 실측 확인,
    # 결과 f.schema 는 "IFC4X3" 로 보고됨) — IfcRigidOperation 자체가 이 애드온
    # 버전에서만 정의돼 있어 이 값이 필요하다.
    f = ifcopenshell.api.project.create_file(version="IFC4X3_ADD2")  # type: ignore[arg-type]
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f)
    ifcopenshell.api.context.add_context(f, context_type="Model")
    ifcopenshell.api.georeference.add_georeferencing(f, ifc_class="IfcRigidOperation")
    op = f.by_type("IfcRigidOperation")[0]
    op.FirstCoordinate = f.createIfcLengthMeasure(1000.0)
    op.SecondCoordinate = f.createIfcLengthMeasure(2000.0)
    op.Height = 50.0
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


def test_read_georeference_rejects_ifc_rigid_operation(tmp_path: Path) -> None:
    """read_georeference() 는 IfcMapConversion 계열만 지원 — IfcRigidOperation 은
    필드명이 달라(FirstCoordinate 대 Eastings) typed 로 거부한다(크래시 아님)."""
    path = _build_ifc_with_rigid_operation(tmp_path)
    f = ifcopenshell.open(str(path))
    with pytest.raises(IfcReferenceModelError, match="IfcRigidOperation"):
        read_georeference(f)


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
