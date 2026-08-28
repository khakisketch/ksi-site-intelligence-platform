"""Deterministic TIN-to-GeoTIFF normalisation shared by IFC and LandXML.

The normaliser deliberately does not invent values outside an input triangle.
It samples each triangle at output-cell centres and retains the upper surface
when overlapping triangles cover a cell.  This is the same semantic used by a
DSM and makes a design surface suitable for cut/fill comparison.

This module is intentionally independent of IFC and LandXML.  Parsers own
format-specific validation; this module owns the one canonical 0.5 m raster
rule so two import paths cannot silently produce different design surfaces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from rasterio.transform import Affine, from_origin

DEFAULT_CELL_SIZE_M: Final = 0.5
"""KSI v1 canonical design-surface cell size in metres."""

CANONICAL_TIN_NORMALIZATION_PROFILE: Final = "ksi-tin-raster-v1-cell-0.5m"

DESIGN_SURFACE_RASTER_PROFILE: Final[dict[str, Any]] = {
    "driver": "GTiff",
    "dtype": "float32",
    "count": 1,
    "nodata": float("nan"),
    "tiled": True,
    "blockxsize": 256,
    "blockysize": 256,
    "compress": "deflate",
    "zlevel": 6,
    "predictor": 3,
}

MAX_GRID_CELLS: Final = 50_000_000
_BARYCENTRIC_EPS: Final = 1e-9
_DEGENERATE_XY_AREA_EPS: Final = 1e-9


class TinSurfaceError(ValueError):
    """A TIN cannot safely be normalised to KSI's canonical raster."""


@dataclass(frozen=True, slots=True)
class TinSurface:
    """A validated triangulated surface using zero-based face indices."""

    vertices: NDArray[np.float64]
    faces: NDArray[np.int64]

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices, dtype=np.float64)
        faces = np.asarray(self.faces, dtype=np.int64)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
            raise TinSurfaceError("TIN vertices must have shape (n>=3, 3)")
        if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 1:
            raise TinSurfaceError("TIN faces must have shape (n>=1, 3)")
        if not np.isfinite(vertices).all():
            raise TinSurfaceError("TIN vertices must be finite")
        if np.any(faces < 0) or np.any(faces >= len(vertices)):
            raise TinSurfaceError("TIN face refers to an unknown vertex")
        if np.any(faces[:, 0] == faces[:, 1]) or np.any(faces[:, 1] == faces[:, 2]) or np.any(
            faces[:, 0] == faces[:, 2]
        ):
            raise TinSurfaceError("TIN face repeats a vertex")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "faces", faces)


def _grid_definition(
    vertices: NDArray[np.float64], cell_size: float
) -> tuple[float, float, int, int]:
    if not (math.isfinite(cell_size) and cell_size > 0.0):
        raise TinSurfaceError(
            f"cell size must be a finite positive metre value (got {cell_size!r})"
        )
    min_x = float(vertices[:, 0].min())
    max_x = float(vertices[:, 0].max())
    min_y = float(vertices[:, 1].min())
    max_y = float(vertices[:, 1].max())
    west = math.floor(min_x / cell_size) * cell_size
    north = math.ceil(max_y / cell_size) * cell_size
    cols = max(1, math.ceil((max_x - west) / cell_size - 1e-9))
    rows = max(1, math.ceil((north - min_y) / cell_size - 1e-9))
    if rows * cols > MAX_GRID_CELLS:
        raise TinSurfaceError(
            f"normalised grid {rows}x{cols}={rows * cols} cells exceeds "
            f"the {MAX_GRID_CELLS} cell limit"
        )
    return west, north, rows, cols


def _bake_faces(
    acc: NDArray[np.float64],
    surface: TinSurface,
    west: float,
    north: float,
    cell_size: float,
) -> None:
    rows, cols = acc.shape
    xs = west + (np.arange(cols) + 0.5) * cell_size
    ys = north - (np.arange(rows) + 0.5) * cell_size
    for face in surface.faces:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = (
            surface.vertices[int(index)] for index in face
        )
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < _DEGENERATE_XY_AREA_EPS:
            continue
        j0 = max(0, math.ceil((min(x0, x1, x2) - west) / cell_size - 0.5))
        j1 = min(cols - 1, math.floor((max(x0, x1, x2) - west) / cell_size - 0.5))
        i0 = max(0, math.ceil((north - max(y0, y1, y2)) / cell_size - 0.5))
        i1 = min(rows - 1, math.floor((north - min(y0, y1, y2)) / cell_size - 0.5))
        if j1 < j0 or i1 < i0:
            continue
        cx = xs[j0 : j1 + 1][None, :]
        cy = ys[i0 : i1 + 1][:, None]
        lam0 = ((y1 - y2) * (cx - x2) + (x2 - x1) * (cy - y2)) / denom
        lam1 = ((y2 - y0) * (cx - x2) + (x0 - x2) * (cy - y2)) / denom
        lam2 = 1.0 - lam0 - lam1
        inside = (
            (lam0 >= -_BARYCENTRIC_EPS)
            & (lam1 >= -_BARYCENTRIC_EPS)
            & (lam2 >= -_BARYCENTRIC_EPS)
        )
        z = lam0 * z0 + lam1 * z1 + lam2 * z2
        block = acc[i0 : i1 + 1, j0 : j1 + 1]
        np.copyto(block, np.maximum(block, z), where=inside)


def _splat_vertices(
    acc: NDArray[np.float64],
    vertices: NDArray[np.float64],
    west: float,
    north: float,
    cell_size: float,
) -> None:
    rows, cols = acc.shape
    col_idx = np.clip(
        np.floor((vertices[:, 0] - west) / cell_size).astype(np.int64), 0, cols - 1
    )
    row_idx = np.clip(
        np.floor((north - vertices[:, 1]) / cell_size).astype(np.int64), 0, rows - 1
    )
    np.maximum.at(acc, (row_idx, col_idx), vertices[:, 2])


def rasterize_top_surface(
    surface: TinSurface, *, cell_size_m: float = DEFAULT_CELL_SIZE_M
) -> tuple[NDArray[np.float32], Affine]:
    """Return a canonical top-surface raster and its fixed affine transform."""
    west, north, rows, cols = _grid_definition(surface.vertices, cell_size_m)
    values = np.full((rows, cols), -np.inf, dtype=np.float64)
    _bake_faces(values, surface, west, north, cell_size_m)
    _splat_vertices(values, surface.vertices, west, north, cell_size_m)
    return (
        np.where(np.isfinite(values), values, np.nan).astype(np.float32),
        from_origin(west, north, cell_size_m, cell_size_m),
    )


__all__ = [
    "CANONICAL_TIN_NORMALIZATION_PROFILE",
    "DEFAULT_CELL_SIZE_M",
    "DESIGN_SURFACE_RASTER_PROFILE",
    "MAX_GRID_CELLS",
    "TinSurface",
    "TinSurfaceError",
    "rasterize_top_surface",
]
