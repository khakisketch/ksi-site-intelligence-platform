"""Explicit data-lane polling, no environment credentials or production fallback."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ksi_processing_controller.spatial_data_core_client import (
    SpatialDataCoreClient,
    SpatialDataCoreClientError,
)
from ksi_processing_controller.spatial_data_sandbox import (
    PinnedSpatialDataLauncher,
    SpatialDataSandbox,
)
from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError, run_once
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    load_spatial_data_worker_config,
    read_spatial_data_core_token,
)


def run_worker(
    *,
    config_path: Path,
    token_path: Path,
    stop: threading.Event,
    clock: Callable[[], datetime],
    once: bool = False,
) -> int:
    config = load_spatial_data_worker_config(config_path, now=clock())
    token = read_spatial_data_core_token(token_path)
    launcher = PinnedSpatialDataLauncher(config.sandbox, clock=clock)
    launcher.verify_material(policy=config.policy, runtime=config.runtime)
    sandbox = SpatialDataSandbox(
        launcher=launcher,
        clock=clock,
        wall_timeout_seconds=config.policy.resource_envelope.max_deadline_seconds,
        heartbeat_interval_millis=config.heartbeat_interval_millis,
    )

    def current_authority() -> bool:
        if stop.is_set():
            return False
        launcher.verify_material(policy=config.policy, runtime=config.runtime)
        return load_spatial_data_worker_config(config_path, now=clock()) == config

    try:
        with SpatialDataCoreClient(
            base_url=config.core_origin,
            token=token,
            activation=config.activation,
            policy=config.policy,
            runtime=config.runtime,
            clock=clock,
            maximum_response_bytes=config.maximum_response_bytes,
            request_timeout_seconds=config.request_timeout_seconds,
            refresh_credentials=lambda: read_spatial_data_core_token(token_path),
            authority_is_current=current_authority,
        ) as core:
            while not stop.is_set():
                try:
                    run_once(
                        core=core,
                        sandbox=sandbox,
                        transport_policy=config.object_policy,
                        worker_instance_id=config.worker_instance_id,
                        clock=clock,
                        workspace_root=Path(config.workspace_root),
                        heartbeat_interval_millis=config.heartbeat_interval_millis,
                    )
                except SpatialDataCoreClientError:
                    if once:
                        raise
                    stop.wait(
                        min(
                            config.policy.max_retry_backoff_seconds,
                            config.policy.resource_envelope.max_deadline_seconds,
                        )
                    )
                # Retain the same ownership authority across turns. A failed reap or
                # pending late launch stops polling rather than replacing the owner.
                sandbox.close()
                if once:
                    break
                stop.wait(config.poll_interval_seconds)
    finally:
        sandbox.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit activated spatial-data worker")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--core-token-file", required=True, type=Path)
    parser.add_argument("--once", action="store_true", help="Attempt one bounded poll then close")
    args = parser.parse_args(argv)
    stop = threading.Event()
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stop.set())
        return run_worker(
            config_path=args.config,
            token_path=args.core_token_file,
            stop=stop,
            clock=lambda: datetime.now(UTC),
            once=args.once,
        )
    except (
        SpatialDataWorkerConfigError,
        SpatialDataWorkerError,
        SpatialDataCoreClientError,
    ) as exc:
        print(exc.reason, file=sys.stderr)
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
