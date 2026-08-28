"""Strict LandXML 1.0--1.2 TIN reader and KSI canonical GeoTIFF normaliser.

Only the tiny, auditable subset needed for civil design surfaces is accepted:
metric point coordinates plus triangular faces in a named TIN ``Surface``.
Alignment, corridor, pipe and any entity-bearing XML are intentionally not a
fallback path.  A rejected source must be exported as LandXML TIN or GeoTIFF
by the design author; this parser never guesses a surface.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from ksi_event_contracts.design_surface import KSI_LANDXML_TIN_PARSER_VERSION
from ksi_geo_spatial.tin_surface import (
    CANONICAL_TIN_NORMALIZATION_PROFILE,
    DEFAULT_CELL_SIZE_M,
    DESIGN_SURFACE_RASTER_PROFILE,
    TinSurface,
    TinSurfaceError,
    rasterize_top_surface,
)

LANDXML_PARSER_VERSION = KSI_LANDXML_TIN_PARSER_VERSION
MAX_LANDXML_BYTES = 25 * 1024 * 1024
MAX_XML_DEPTH = 64
MAX_XML_ELEMENTS = 300_000
MAX_TIN_POINTS = 1_000_000
MAX_TIN_FACES = 2_000_000
_DTD_OR_ENTITY = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_SUPPORTED_NAMESPACE = re.compile(r"^http://www\.landxml\.org/schema/LandXML-1\.[0-2]$")
_METER_UNITS = frozenset({"meter", "metre", "meters", "metres", "m"})
_LANDXML_CORE_ELEMENTS = frozenset(
    {"LandXML", "Units", "Metric", "Surfaces", "Surface", "Definition", "Pnts", "P", "Faces", "F"}
)
_DEGENERATE_AREA_EPS = 1e-9


class LandXmlError(ValueError):
    """Typed, safe rejection of unsupported or malformed LandXML."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class LandXmlTin:
    surface_name: str
    surface: TinSurface
    source_sha256: str


@dataclass(frozen=True, slots=True)
class NormalizedLandXmlSurface:
    source_sha256: str
    canonical_sha256: str
    surface_selector: str
    parser_version: str
    normalization_profile: str

    def source_lineage(self) -> dict[str, str]:
        return {
            "sourceFormat": "landxml",
            "sourceSha256": self.source_sha256,
            "surfaceSelector": self.surface_selector,
            "parserVersion": self.parser_version,
            "normalizationProfile": self.normalization_profile,
            "canonicalSha256": self.canonical_sha256,
        }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str | None:
    if not tag.startswith("{"):
        return None
    return tag[1:].split("}", 1)[0]


def _parse_triplet(raw: str | None, *, what: str) -> tuple[float, float, float]:
    if raw is None:
        raise LandXmlError("MALFORMED_POINT", f"{what} has no coordinate text")
    values = raw.split()
    if len(values) != 3:
        raise LandXmlError("MALFORMED_POINT", f"{what} must contain exactly three coordinates")
    try:
        parsed = tuple(float(value) for value in values)
    except ValueError as exc:
        raise LandXmlError("MALFORMED_POINT", f"{what} has a non-numeric coordinate") from exc
    if not all(math.isfinite(value) for value in parsed):
        raise LandXmlError("NONFINITE_COORDINATE", f"{what} has NaN or infinity")
    # LandXML P coordinates are Northing Easting Elevation; KSI's rasterizer
    # consumes x=easting, y=northing, z=elevation.
    northing, easting, elevation = parsed
    return (easting, northing, elevation)


def _require_metric_units(root: ET.Element) -> None:
    unit_values: list[str] = []
    if root.attrib.get("linearUnit"):
        unit_values.append(root.attrib["linearUnit"])
    for element in root.iter():
        if _local_name(element.tag) in {"Metric", "Units"}:
            for key in ("linearUnit", "linearunit"):
                if element.attrib.get(key):
                    unit_values.append(element.attrib[key])
    if not unit_values or any(value.strip().lower() not in _METER_UNITS for value in unit_values):
        raise LandXmlError("NON_METER_UNIT", "LandXML TIN must declare metre linear units")


def _collect_surface(surface_element: ET.Element, source_sha256: str) -> LandXmlTin:
    name = (surface_element.attrib.get("name") or "").strip()
    if not name:
        raise LandXmlError("SURFACE_NAME_MISSING", "a TIN Surface needs a non-empty name")
    definition = next(
        (child for child in surface_element if _local_name(child.tag) == "Definition"), None
    )
    if definition is None or (definition.attrib.get("surfType") or "").upper() != "TIN":
        raise LandXmlError("UNSUPPORTED_SURFACE", f"Surface {name!r} is not a TIN Definition")
    points_element = next(
        (child for child in definition if _local_name(child.tag) == "Pnts"), None
    )
    faces_element = next(
        (child for child in definition if _local_name(child.tag) == "Faces"), None
    )
    if points_element is None or faces_element is None:
        raise LandXmlError("TIN_STRUCTURE_MISSING", f"Surface {name!r} needs Pnts and Faces")
    point_index: dict[str, int] = {}
    vertices: list[tuple[float, float, float]] = []
    for point in points_element:
        if _local_name(point.tag) != "P":
            continue
        point_id = (point.attrib.get("id") or "").strip()
        if not point_id:
            raise LandXmlError("POINT_ID_MISSING", f"Surface {name!r} has a point without id")
        if point_id in point_index:
            raise LandXmlError(
                "DUPLICATE_POINT_ID", f"Surface {name!r} repeats point id {point_id!r}"
            )
        if len(vertices) >= MAX_TIN_POINTS:
            raise LandXmlError(
                "POINT_LIMIT_EXCEEDED", "LandXML TIN point count exceeds the safety limit"
            )
        point_index[point_id] = len(vertices)
        vertices.append(_parse_triplet(point.text, what=f"point {point_id!r}"))
    if len(vertices) < 3:
        raise LandXmlError(
            "TIN_POINTS_INSUFFICIENT", f"Surface {name!r} has fewer than three points"
        )
    faces: list[tuple[int, int, int]] = []
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for face in faces_element:
        if _local_name(face.tag) != "F":
            continue
        references = (face.text or "").split()
        if len(references) != 3:
            raise LandXmlError(
                "MALFORMED_FACE", f"Surface {name!r} face must reference exactly three points"
            )
        if len(faces) >= MAX_TIN_FACES:
            raise LandXmlError(
                "FACE_LIMIT_EXCEEDED", "LandXML TIN face count exceeds the safety limit"
            )
        try:
            indices = (
                point_index[references[0]],
                point_index[references[1]],
                point_index[references[2]],
            )
        except KeyError as exc:
            raise LandXmlError(
                "UNKNOWN_FACE_REFERENCE",
                f"Surface {name!r} face references unknown point {exc.args[0]!r}",
            ) from exc
        if len(set(indices)) != 3:
            raise LandXmlError("DEGENERATE_FACE", f"Surface {name!r} face repeats a point")
        a, b, c = (vertices_array[index] for index in indices)
        signed_double_area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(float(signed_double_area)) < _DEGENERATE_AREA_EPS:
            raise LandXmlError("DEGENERATE_FACE", f"Surface {name!r} face has zero XY area")
        faces.append(indices)
    if not faces:
        raise LandXmlError("TIN_FACES_INSUFFICIENT", f"Surface {name!r} has no triangular faces")
    try:
        tin = TinSurface(vertices=vertices_array, faces=np.asarray(faces, dtype=np.int64))
    except TinSurfaceError as exc:
        raise LandXmlError("INVALID_TIN", str(exc)) from exc
    return LandXmlTin(surface_name=name, surface=tin, source_sha256=source_sha256)


def parse_landxml_tin(raw: bytes, *, surface_selector: str | None) -> LandXmlTin:
    """Parse the selected, metric TIN Surface without resolving XML entities."""
    if not raw:
        raise LandXmlError("EMPTY_DOCUMENT", "LandXML input is empty")
    if len(raw) > MAX_LANDXML_BYTES:
        raise LandXmlError("DOCUMENT_TOO_LARGE", "LandXML input exceeds the safety byte limit")
    if _DTD_OR_ENTITY.search(raw):
        raise LandXmlError(
            "DTD_OR_ENTITY_FORBIDDEN", "LandXML DTD and entity declarations are forbidden"
        )
    depth = 0
    element_count = 0
    root: ET.Element | None = None
    try:
        parser = ET.iterparse(io.BytesIO(raw), events=("start", "end"))
        for event, element in parser:
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                element_count += 1
                if depth > MAX_XML_DEPTH:
                    raise LandXmlError(
                        "XML_DEPTH_EXCEEDED", "LandXML nesting exceeds the safety limit"
                    )
                if element_count > MAX_XML_ELEMENTS:
                    raise LandXmlError(
                        "XML_ELEMENT_LIMIT_EXCEEDED",
                        "LandXML element count exceeds the safety limit",
                    )
            else:
                depth -= 1
    except ET.ParseError as exc:
        raise LandXmlError("MALFORMED_XML", f"LandXML cannot be parsed: {exc}") from exc
    if root is None:
        raise LandXmlError("MALFORMED_XML", "LandXML document has no root element")
    namespace = _namespace(root.tag)
    if (
        _local_name(root.tag) != "LandXML"
        or namespace is None
        or not _SUPPORTED_NAMESPACE.fullmatch(namespace)
    ):
        raise LandXmlError(
            "UNSUPPORTED_NAMESPACE", "only LandXML 1.0, 1.1, and 1.2 namespaces are supported"
        )
    for element in root.iter():
        if (
            _local_name(element.tag) in _LANDXML_CORE_ELEMENTS
            and _namespace(element.tag) != namespace
        ):
            raise LandXmlError(
                "UNSUPPORTED_NAMESPACE",
                "LandXML core TIN elements must use the document namespace",
            )
    _require_metric_units(root)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    surfaces = [element for element in root.iter() if _local_name(element.tag) == "Surface"]
    if not surfaces:
        raise LandXmlError("TIN_SURFACE_MISSING", "LandXML contains no Surface")
    parsed = [_collect_surface(surface, source_sha256) for surface in surfaces]
    names = [surface.surface_name for surface in parsed]
    if len(set(names)) != len(names):
        raise LandXmlError(
            "DUPLICATE_SURFACE_NAME", "LandXML Surface names must be unique for explicit selection"
        )
    if surface_selector is None:
        if len(parsed) != 1:
            raise LandXmlError("SURFACE_SELECTOR_REQUIRED", "select one named TIN Surface")
        return parsed[0]
    selected = next(
        (surface for surface in parsed if surface.surface_name == surface_selector), None
    )
    if selected is None:
        raise LandXmlError(
            "SURFACE_SELECTOR_NOT_FOUND", f"selected Surface {surface_selector!r} does not exist"
        )
    return selected


def normalise_landxml_to_geotiff(
    raw: bytes, *, surface_selector: str | None, crs: str, output_path: Path
) -> NormalizedLandXmlSurface:
    """Parse one selected TIN, write the fixed 0.5 m GeoTIFF, and return lineage."""
    selected = parse_landxml_tin(raw, surface_selector=surface_selector)
    try:
        values, transform = rasterize_top_surface(
            selected.surface, cell_size_m=DEFAULT_CELL_SIZE_M
        )
    except TinSurfaceError as exc:
        raise LandXmlError(
            "GRID_LIMIT_EXCEEDED",
            f"LandXML TIN cannot fit the canonical 0.5 m grid: {exc}",
        ) from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        height=values.shape[0],
        width=values.shape[1],
        crs=crs,
        transform=transform,
        **DESIGN_SURFACE_RASTER_PROFILE,
    ) as dataset:
        dataset.write(values, 1)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return NormalizedLandXmlSurface(
        source_sha256=selected.source_sha256,
        canonical_sha256=digest,
        surface_selector=selected.surface_name,
        parser_version=LANDXML_PARSER_VERSION,
        normalization_profile=CANONICAL_TIN_NORMALIZATION_PROFILE,
    )


__all__ = [
    "CANONICAL_TIN_NORMALIZATION_PROFILE",
    "LANDXML_PARSER_VERSION",
    "LandXmlError",
    "LandXmlTin",
    "NormalizedLandXmlSurface",
    "normalise_landxml_to_geotiff",
    "parse_landxml_tin",
]
