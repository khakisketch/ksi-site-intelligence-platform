"""Closed operational entrypoint for the separate external validation worker."""

from __future__ import annotations

import argparse
import signal
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalInspectorUdsClient,
    FileSystemSanitizedOutputSink,
)
from ksi_processing_controller.external_measurement_client import (
    ExternalMeasurementUdsClient,
    FixedMeasurementUdsConnector,
    MeasurementSocketIdentityV2,
)
from ksi_processing_controller.external_measurement_core_client import ExternalMeasurementCoreClient
from ksi_processing_controller.external_validation_core_client import ExternalValidationCoreClient
from ksi_processing_controller.external_validation_lanes import (
    InspectionLaneDependencies,
    InspectionValidationLane,
    MeasurementLaneDependencies,
    MeasurementValidationLane,
)
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    ExternalValidationRunner,
)
from ksi_processing_controller.external_validation_worker_config import (
    ExternalValidationWorkerConfigBlocked,
    ExternalValidationWorkerConfigV1,
    FixedInspectionUdsConnector,
    load_external_validation_worker_config,
    load_pinned_measurement_manifest,
    read_external_validation_core_token,
)


@dataclass(slots=True)
class _ValidationWorkerGraph:
    """Own the shared bearer transport exactly once after runner lanes have stopped."""

    runner: ExternalValidationRunner
    measurement_core: ExternalMeasurementCoreClient
    validation_core: ExternalValidationCoreClient

    def close(self) -> None:
        first_error: BaseException | None = None
        for close in (self.runner.close, self.measurement_core.close, self.validation_core.close):
            try:
                close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def build_validation_worker_graph(
    config: ExternalValidationWorkerConfigV1,
    *,
    core_token: str,
) -> _ValidationWorkerGraph:
    """Assemble exactly the three reviewed external lanes; start no listener or host service."""

    manifest = load_pinned_measurement_manifest(config.measurement)
    validation_core = ExternalValidationCoreClient(
        base_url=config.core.base_url,
        bearer_token=core_token,
        maximum_response_bytes=config.core.maximum_response_bytes,
        request_timeout_seconds=config.core.request_timeout_seconds,
    )
    measurement_core: ExternalMeasurementCoreClient | None = None
    try:
        measurement_core = ExternalMeasurementCoreClient(core_client=validation_core)
        inspection_sink = FileSystemSanitizedOutputSink(
            private_root=config.inspection.private_output_root
        )
        inspection = InspectionValidationLane(
            core=validation_core,
            worker_instance_id=config.worker_instance_id,
            dependencies=InspectionLaneDependencies(
                launcher=ExternalInspectorUdsClient(
                    connect=FixedInspectionUdsConnector(config.inspection.socket),
                    protocol_limits=config.inspection.protocol_limits,
                    sanitized_output_sink=inspection_sink,
                    heartbeat_interval_millis=config.inspection.worker_limits.heartbeat_interval_millis,
                ),
                operation_profile=config.inspection.profile,
                candidate_sink=inspection_sink,
                object_policy=config.object_policy,
                worker_limits=config.inspection.worker_limits,
            ),
        )
        measurement_socket = MeasurementSocketIdentityV2(
            path=config.measurement.socket.path,
            owner_uid=config.measurement.socket.owner_uid,
            owner_gid=config.measurement.socket.owner_gid,
            mode=config.measurement.socket.mode,
            launcher_uid=config.measurement.socket.peer_uid,
        )
        measurement_uds = ExternalMeasurementUdsClient(
            connector=FixedMeasurementUdsConnector(measurement_socket),
            protocol_limits=config.measurement.protocol_limits,
            heartbeat_interval_millis=config.measurement.heartbeat_interval_millis,
        )
        measurement_dependencies = MeasurementLaneDependencies(
            manifest=manifest,
            uds_client=measurement_uds,
            protocol_limits=config.measurement.protocol_limits,
            heartbeat_interval_millis=config.measurement.heartbeat_interval_millis,
            object_policy=config.object_policy,
        )
        checkpoint = MeasurementValidationLane(
            lane=ExternalLane.CHECKPOINT,
            operation="CHECKPOINT_VALIDATION",
            core=measurement_core,
            worker_instance_id=config.worker_instance_id,
            dependencies=measurement_dependencies,
        )
        relative_volume = MeasurementValidationLane(
            lane=ExternalLane.RELATIVE_VOLUME,
            operation="RELATIVE_VOLUME",
            core=measurement_core,
            worker_instance_id=config.worker_instance_id,
            dependencies=measurement_dependencies,
        )
        return _ValidationWorkerGraph(
            runner=ExternalValidationRunner(
                lanes=(inspection, checkpoint, relative_volume), policy=config.runner_policy
            ),
            measurement_core=measurement_core,
            validation_core=validation_core,
        )
    except BaseException:
        if measurement_core is not None:
            with suppress(BaseException):
                measurement_core.close()
        with suppress(BaseException):
            validation_core.close()
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Require explicit trusted configuration and a separately supplied Core secret."""
    parser = argparse.ArgumentParser(prog="ksi-external-validation-worker", add_help=False)
    parser.add_argument("--config")
    parser.add_argument("--core-token-file")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not isinstance(args.config, str) or not isinstance(args.core_token_file, str):
        return 2
    config_path, token_path = Path(args.config), Path(args.core_token_file)
    if not config_path.is_absolute() or not token_path.is_absolute():
        return 2
    try:
        config = load_external_validation_worker_config(config_path)
        token = read_external_validation_core_token(token_path)
        graph = build_validation_worker_graph(config, core_token=token)
    except (ExternalValidationWorkerConfigBlocked, OSError, TypeError, ValueError):
        return 2
    previous_handlers: list[tuple[int, Any]] = []

    def request_stop(_signal_number: int, _frame: object) -> None:
        graph.runner.request_stop()

    result = 2
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers.append((number, signal.signal(number, request_stop)))
        graph.runner.run_forever()
        result = 0
    except KeyboardInterrupt:
        graph.runner.request_stop()
        result = 130
    except Exception:
        result = 2
    finally:
        for restore_number, handler in reversed(previous_handlers):
            with suppress(Exception):
                signal.signal(restore_number, handler)
        try:
            graph.close()
        except BaseException:
            if result == 0:
                result = 2
    return result


__all__ = ["build_validation_worker_graph", "main"]
