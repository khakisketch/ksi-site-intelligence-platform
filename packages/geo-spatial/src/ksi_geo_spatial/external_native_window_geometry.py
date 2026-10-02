"""Pure native-grid planning; no byte decoding, transforms or access authority."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ksi_event_contracts.external_artifact_validation import RasterMeasurementsV1
from pydantic import ValidationError

type Bounds = tuple[float, float, float, float]
# Preserve NativeWindowReceiptV1: half-open columns, then half-open rows (not xyxy).
type PixelWindow = tuple[int, int, int, int]
type Transform = tuple[float, float, float, float, float, float]


class NativeWindowError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class NativeWindowGeometryV1:
    pixel_window: PixelWindow
    actual_bounds: Bounds
    transform: Transform


def plan_external_native_window(
    *, requested_bounds: Bounds, measurements: RasterMeasurementsV1, requested_crs_digest: str
) -> NativeWindowGeometryV1:
    """Expand to exact native cell edges; grants must authorize the expanded bounds."""
    if (
        not isinstance(requested_bounds, tuple | list)
        or len(requested_bounds) != 4
        or any(type(value) not in {int, float} for value in requested_bounds)
    ):
        raise NativeWindowError("INVALID_REQUEST_BOUNDS", "bounds must be four finite numbers")
    try:
        bounds = tuple(float(value) for value in requested_bounds)
    except (OverflowError, ValueError) as exc:
        raise NativeWindowError("INVALID_REQUEST_BOUNDS", "bounds must be finite") from exc
    if not all(math.isfinite(value) for value in bounds) or not (
        bounds[0] < bounds[2] and bounds[1] < bounds[3]
    ):
        raise NativeWindowError("INVALID_REQUEST_BOUNDS", "bounds must have positive finite extent")
    try:
        measured = RasterMeasurementsV1.model_validate(measurements)
    except ValidationError as exc:
        raise NativeWindowError("INVALID_SOURCE_GEOMETRY", "measured geometry is invalid") from exc
    if requested_crs_digest != measured.observed_crs_digest:
        raise NativeWindowError("CRS_MISMATCH", "request must match the observed CRS digest")
    try:
        return _plan((bounds[0], bounds[1], bounds[2], bounds[3]), measured)
    except OverflowError as exc:
        raise NativeWindowError("INVALID_SOURCE_GEOMETRY", "measured grid is not finite") from exc


def _plan(request: Bounds, measurements: RasterMeasurementsV1) -> NativeWindowGeometryV1:
    a, b, c, d, e, f = measurements.transform
    if b != 0.0 or d != 0.0 or a <= 0.0 or e >= 0.0:
        raise NativeWindowError("UNSUPPORTED_GRID", "only a north-up native grid is supported")
    xmin, ymin, xmax, ymax = request
    left, right = c, c + a * measurements.width
    bottom, top = f + e * measurements.height, f
    if not all(math.isfinite(value) for value in (left, right, bottom, top)):
        raise NativeWindowError("INVALID_SOURCE_GEOMETRY", "source extent is not finite")
    if xmin < left or xmax > right or ymin < bottom or ymax > top:
        raise NativeWindowError(
            "REQUEST_OUTSIDE_SOURCE", "request must be fully inside the source footprint"
        )
    col_start = _stable_pixel_index(xmin, c, a, measurements.width, rounding="floor")
    col_stop = _stable_pixel_index(xmax, c, a, measurements.width, rounding="ceil")
    row_start = _stable_pixel_index(ymax, f, e, measurements.height, rounding="floor")
    row_stop = _stable_pixel_index(ymin, f, e, measurements.height, rounding="ceil")
    if (
        col_start < 0
        or row_start < 0
        or col_stop > measurements.width
        or row_stop > measurements.height
    ):
        raise NativeWindowError(
            "REQUEST_OUTSIDE_SOURCE", "pixel window falls outside the source footprint"
        )
    if col_start >= col_stop or row_start >= row_stop:
        raise NativeWindowError("EMPTY_PIXEL_WINDOW", "request contains no source pixel")
    actual_bounds = (c + a * col_start, f + e * row_stop, c + a * col_stop, f + e * row_start)
    transform = (a, 0.0, actual_bounds[0], 0.0, e, actual_bounds[3])
    if not all(math.isfinite(value) for value in (*actual_bounds, *transform)):
        raise NativeWindowError("INVALID_SOURCE_GEOMETRY", "computed output geometry is non-finite")
    return NativeWindowGeometryV1(
        (col_start, col_stop, row_start, row_stop), actual_bounds, transform
    )


def _stable_pixel_index(
    coordinate: float, origin: float, step: float, dimension: int, *, rounding: str
) -> int:
    """Binary search the original primitive's actual representable affine edges."""
    if rounding not in {"floor", "ceil"}:
        raise ValueError("rounding must be floor or ceil")
    if dimension <= 0 or step == 0.0:
        raise NativeWindowError(
            "INVALID_SOURCE_GEOMETRY", "grid dimensions and pixel step must be nonzero"
        )
    final_edge = origin + step * dimension
    extent = step * dimension
    precision_floor = max(math.ulp(origin), math.ulp(final_edge), math.ulp(extent))
    if not math.isfinite(final_edge) or abs(step) < precision_floor:
        raise NativeWindowError(
            "UNREPRESENTABLE_GRID", "adjacent pixel boundaries are not distinct in floating point"
        )
    direction = 1.0 if step > 0.0 else -1.0
    target = coordinate * direction
    low, high = 0, dimension
    while low < high:
        middle = (low + high) // 2
        edge = origin + step * middle
        if not math.isfinite(edge):
            raise NativeWindowError(
                "INVALID_SOURCE_GEOMETRY", "computed pixel boundary is non-finite"
            )
        if edge * direction < target:
            low = middle + 1
        else:
            high = middle
    edge = origin + step * low
    if edge == coordinate:
        return low
    return low - 1 if rounding == "floor" else low
