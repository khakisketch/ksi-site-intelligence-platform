"""Separate derived-output callable; the existing V2 worker protocol is unchanged.

Only this opt-in path retains the exact native-measured delta array. It does not
publish bytes or authorize execution. New runtime identity/containment evidence
and Core publication authority are required before mounting it in a worker.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import rasterio
from ksi_change_detection.dsm_diff import DiffResult
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
    RelativeVolumeNumericResultV2,
)

from ksi_processing_controller.external_analysis_measurement import (
    _measure_external_relative_volume_v2,
)
from ksi_processing_controller.external_delta_raster import (
    DeltaRasterMeasurementError,
    MeasuredDeltaRasterV1,
    prepare_external_delta_raster_v2,
)
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementWatchdogV2,
    maximum_fixed_profile_zone_grid_cells,
)


@dataclass(frozen=True, slots=True)
class RelativeVolumeDeltaMeasurementV1:
    report: RelativeVolumeCalculationReportV2 | RelativeVolumeCalculationFailureV2
    delta: MeasuredDeltaRasterV1 | None
    delta_failure_code: str | None


@contextmanager
def measure_external_relative_volume_with_delta_v2(
    *,
    attempt: AnalysisExecutionAttemptV2,
    calculation_identity: CalculationIdentityV2,
    baseline_path: Path,
    current_path: Path,
    report_id: str,
    computed_at: datetime,
    reported_at: datetime,
    maximum_delta_output_bytes: int,
    check_current: Callable[[], None],
    maximum_wall_seconds: float | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Iterator[RelativeVolumeDeltaMeasurementV1]:
    """Measure original inputs once and privately emit their actual delta bytes.

    A derived-output size/encoding failure is separate from the unchanged V2
    numeric report. Cancellation/currentness failures never expose bytes. The
    output fd lives only inside this context and must not be journaled as a path.
    """
    if not callable(check_current):
        raise ValueError("an explicit currentness guard is required")
    if (
        isinstance(maximum_delta_output_bytes, bool)
        or not isinstance(maximum_delta_output_bytes, int)
        or not 0
        < maximum_delta_output_bytes
        <= attempt.authorization.resource_envelope.max_output_bytes
    ):
        raise ValueError("delta byte cap must fit the Core-authorized output envelope")
    check_current()
    with ExitStack() as retained:
        delta: MeasuredDeltaRasterV1 | None = None
        failure: str | None = None

        def consume(
            diff: DiffResult,
            numeric: RelativeVolumeNumericResultV2,
            watchdog: MeasurementWatchdogV2,
        ) -> None:
            nonlocal delta, failure

            def guard() -> None:
                watchdog.check()
                check_current()

            try:
                delta = retained.enter_context(
                    prepare_external_delta_raster_v2(
                        diff=diff,
                        numeric_result=numeric,
                        maximum_output_bytes=maximum_delta_output_bytes,
                        maximum_grid_cells=maximum_fixed_profile_zone_grid_cells(
                            envelope=attempt.authorization.resource_envelope,
                            baseline_cell_count=diff.diff_m.size,
                        ),
                        check_current=guard,
                    )
                )
            except (DeltaRasterMeasurementError, rasterio.errors.RasterioError):
                failure = "DELTA_RASTER_OUTPUT_UNAVAILABLE"

        report = _measure_external_relative_volume_v2(
            attempt=attempt,
            calculation_identity=calculation_identity,
            baseline_path=baseline_path,
            current_path=current_path,
            report_id=report_id,
            computed_at=computed_at,
            reported_at=reported_at,
            maximum_wall_seconds=maximum_wall_seconds,
            is_cancelled=is_cancelled,
            _consume_delta=consume,
        )
        check_current()
        if isinstance(report, RelativeVolumeCalculationFailureV2):
            delta = None
        yield RelativeVolumeDeltaMeasurementV1(
            report=report, delta=delta, delta_failure_code=failure
        )
