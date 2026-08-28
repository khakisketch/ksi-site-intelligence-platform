"""LandXML TIN ingress — selected surface only, hostile XML fails closed."""

from __future__ import annotations

import hashlib
from pathlib import Path

import ksi_processing_controller.landxml as landxml_module
import numpy as np
import pytest
import rasterio
from ksi_processing_controller.landxml import (
    CANONICAL_TIN_NORMALIZATION_PROFILE,
    LandXmlError,
    normalise_landxml_to_geotiff,
    parse_landxml_tin,
)


def _landxml(*, second: bool = False, unit: str = "meter") -> bytes:
    other = "" if not second else """
    <Surface name=\"Existing\"><Definition surfType=\"TIN\"><Pnts>
      <P id=\"1\">0 0 1</P><P id=\"2\">0 1 1</P><P id=\"3\">1 0 1</P>
    </Pnts><Faces><F>1 2 3</F></Faces></Definition></Surface>"""
    return f"""<?xml version=\"1.0\"?>
    <LandXML xmlns=\"http://www.landxml.org/schema/LandXML-1.2\">
      <Units><Metric linearUnit=\"{unit}\"/></Units>
      <Surfaces><Surface name=\"Plan\"><Definition surfType=\"TIN\"><Pnts>
        <P id=\"a\">0 0 10</P><P id=\"b\">0 2 12</P><P id=\"c\">2 0 14</P>
      </Pnts><Faces><F>a b c</F></Faces></Definition></Surface>{other}</Surfaces>
    </LandXML>""".encode()


def test_landxml_normalises_selected_tin_deterministically(tmp_path: Path) -> None:
    raw = _landxml()
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    one = normalise_landxml_to_geotiff(
        raw, surface_selector="Plan", crs="EPSG:5186", output_path=first
    )
    two = normalise_landxml_to_geotiff(
        raw, surface_selector="Plan", crs="EPSG:5186", output_path=second
    )

    assert one.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert one.canonical_sha256 == two.canonical_sha256
    assert one.normalization_profile == CANONICAL_TIN_NORMALIZATION_PROFILE
    with rasterio.open(first) as dataset:
        assert str(dataset.crs) == "EPSG:5186"
        assert dataset.transform.a == pytest.approx(0.5)
        band = dataset.read(1)
        assert band.shape == (4, 4)
        # LandXML is Northing/Easting/Elevation while the rasterizer consumes
        # x/y/z.  This non-vertex sample proves the order conversion and TIN
        # interpolation together: z = 10 + x + 2y at x=.75, y=1.25.
        assert band[1, 1] == pytest.approx(13.25)
        assert np.isfinite(band).any()


def test_multiple_surface_requires_explicit_selector() -> None:
    with pytest.raises(LandXmlError, match="select one"):
        parse_landxml_tin(_landxml(second=True), surface_selector=None)
    selected = parse_landxml_tin(_landxml(second=True), surface_selector="Existing")
    assert selected.surface_name == "Existing"


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_supported_landxml_namespaces_are_explicit(version: str) -> None:
    raw = _landxml().replace(b"LandXML-1.2", f"LandXML-{version}".encode())
    assert parse_landxml_tin(raw, surface_selector="Plan").surface_name == "Plan"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'<!DOCTYPE LandXML [<!ENTITY x "boom">]><LandXML/>', "DTD_OR_ENTITY_FORBIDDEN"),
        (_landxml(unit="foot"), "NON_METER_UNIT"),
        (_landxml().replace(b"LandXML-1.2", b"LandXML-1.3"), "UNSUPPORTED_NAMESPACE"),
        (_landxml().replace(b'<P id="a">', b'<P xmlns="" id="a">'), "UNSUPPORTED_NAMESPACE"),
        (_landxml().replace(b'<P id="b">', b'<P id="a">'), "DUPLICATE_POINT_ID"),
        (_landxml().replace(b"<F>a b c</F>", b"<F>a b missing</F>"), "UNKNOWN_FACE_REFERENCE"),
        (_landxml().replace(b"<F>a b c</F>", b"<F>a a c</F>"), "DEGENERATE_FACE"),
        (_landxml().replace(b"0 2 12", b"0 1 12").replace(b"2 0 14", b"0 2 14"), "DEGENERATE_FACE"),
        (_landxml().replace(b"0 0 10", b"0 0 NaN"), "NONFINITE_COORDINATE"),
        (_landxml()[:-20], "MALFORMED_XML"),
    ],
)
def test_hostile_or_invalid_landxml_is_rejected(raw: bytes, code: str) -> None:
    with pytest.raises(LandXmlError) as exc_info:
        parse_landxml_tin(raw, surface_selector="Plan")
    assert exc_info.value.code == code


def test_duplicate_surface_names_and_unknown_selector_are_rejected() -> None:
    duplicate = _landxml(second=True).replace(b'name="Existing"', b'name="Plan"')
    with pytest.raises(LandXmlError) as duplicate_error:
        parse_landxml_tin(duplicate, surface_selector="Plan")
    assert duplicate_error.value.code == "DUPLICATE_SURFACE_NAME"

    with pytest.raises(LandXmlError) as selector_error:
        parse_landxml_tin(_landxml(), surface_selector="Missing")
    assert selector_error.value.code == "SURFACE_SELECTOR_NOT_FOUND"


def test_document_size_depth_and_element_limits_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(landxml_module, "MAX_LANDXML_BYTES", 32)
    with pytest.raises(LandXmlError) as size_error:
        parse_landxml_tin(_landxml(), surface_selector="Plan")
    assert size_error.value.code == "DOCUMENT_TOO_LARGE"

    monkeypatch.setattr(landxml_module, "MAX_LANDXML_BYTES", 25 * 1024 * 1024)
    deep = _landxml().replace(
        b"<Surfaces>", b"<Surfaces>" + b"<Nested>" * 65
    ).replace(b"</Surfaces>", b"</Nested>" * 65 + b"</Surfaces>")
    with pytest.raises(LandXmlError) as depth_error:
        parse_landxml_tin(deep, surface_selector="Plan")
    assert depth_error.value.code == "XML_DEPTH_EXCEEDED"

    monkeypatch.setattr(landxml_module, "MAX_XML_DEPTH", 100)
    monkeypatch.setattr(landxml_module, "MAX_XML_ELEMENTS", 5)
    with pytest.raises(LandXmlError) as count_error:
        parse_landxml_tin(_landxml(), surface_selector="Plan")
    assert count_error.value.code == "XML_ELEMENT_LIMIT_EXCEEDED"


def test_canonical_grid_limit_is_a_typed_rejection(tmp_path: Path) -> None:
    huge = _landxml().replace(b"0 2 12", b"0 10000 12").replace(
        b"2 0 14", b"10000 0 14"
    )
    with pytest.raises(LandXmlError) as exc_info:
        normalise_landxml_to_geotiff(
            huge,
            surface_selector="Plan",
            crs="EPSG:5186",
            output_path=tmp_path / "too-large.tif",
        )
    assert exc_info.value.code == "GRID_LIMIT_EXCEEDED"
    assert not (tmp_path / "too-large.tif").exists()
