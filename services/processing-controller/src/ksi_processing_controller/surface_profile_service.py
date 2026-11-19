"""단면 일꾼의 명시적 상시 실행. 환경 변수 자격이나 운영 대체 경로는 없다.

부모가 Core 세션과 원본 전송을 소유하고 계산은 고정된 Linux 격리 실행기에 맡긴다.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ksi_processing_controller.spatial_data_sandbox import (
    PinnedSpatialDataLauncher,
    SpatialDataSandbox,
)
from ksi_processing_controller.spatial_data_worker import SpatialDataWorkerError
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    read_spatial_data_core_token,
)
from ksi_processing_controller.surface_profile_core_client import (
    SurfaceProfileCoreClient,
    SurfaceProfileCoreClientError,
)
from ksi_processing_controller.surface_profile_runner import run_once
from ksi_processing_controller.surface_profile_worker_config import (
    SurfaceProfileWorkerConfigError,
    load_surface_profile_worker_config,
)


def _token(path: Path) -> str:
    try:
        return read_spatial_data_core_token(path)
    except SpatialDataWorkerConfigError as exc:
        raise SurfaceProfileWorkerConfigError("TOKEN_UNAVAILABLE") from exc


@contextmanager
def _hold_workspace_slot(path: Path) -> Iterator[None]:
    """One service per private spool, including overlapping restarts and --once runs."""
    try:
        directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise SurfaceProfileWorkerConfigError("WORKSPACE_UNAVAILABLE") from exc
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise SurfaceProfileWorkerConfigError("WORKSPACE_UNAVAILABLE")
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SurfaceProfileWorkerConfigError("WORKSPACE_IN_USE") from exc
        except OSError as exc:
            raise SurfaceProfileWorkerConfigError("WORKSPACE_UNAVAILABLE") from exc
        yield
    finally:
        os.close(directory)


def run_worker(
    *,
    config_path: Path,
    token_path: Path,
    stop: threading.Event,
    clock: Callable[[], datetime],
    once: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> int:
    config = load_surface_profile_worker_config(config_path, now=clock())
    if config.sandbox is None:
        raise SurfaceProfileWorkerConfigError("CONTAINMENT_REQUIRED")
    if sys.platform != "linux" or not Path("/proc/self/ns/mnt").exists():
        raise SurfaceProfileWorkerConfigError("LINUX_CONTAINMENT_UNAVAILABLE")
    launcher = PinnedSpatialDataLauncher(config.sandbox, clock=clock)
    try:
        launcher.verify_material(policy=config.policy, runtime=config.runtime)
    except SpatialDataWorkerError as exc:
        raise SurfaceProfileWorkerConfigError("CONTAINMENT_UNAVAILABLE") from exc
    token = _token(token_path)
    sandbox = SpatialDataSandbox(
        launcher=launcher,
        clock=clock,
        wall_timeout_seconds=config.policy.resource_envelope.max_deadline_seconds,
        heartbeat_interval_millis=config.heartbeat_interval_millis,
    )

    def current_authority() -> bool:
        if stop.is_set():
            return False
        # 호출마다 설정을 다시 읽어 철회·만료·교체를 반영한다. 같지 않으면 현재 권한이 아니다.
        launcher.verify_material(policy=config.policy, runtime=config.runtime)
        return load_surface_profile_worker_config(config_path, now=clock()) == config

    with ExitStack() as resources:
        resources.enter_context(_hold_workspace_slot(Path(config.workspace_root)))
        resources.callback(sandbox.close)
        core = resources.enter_context(
            SurfaceProfileCoreClient(
                base_url=config.core_origin,
                token=token,
                activation=config.activation,
                policy=config.policy,
                runtime=config.runtime,
                clock=clock,
                maximum_response_bytes=config.maximum_response_bytes,
                maximum_request_bytes=config.maximum_request_bytes,
                request_timeout_seconds=config.request_timeout_seconds,
                transport=transport,
                refresh_credentials=lambda: _token(token_path),
                authority_is_current=current_authority,
            )
        )
        while not stop.is_set():
            try:
                # A timed-out launch can finish asynchronously. Keep the next job in Core
                # until the preceding process group has been accounted for.
                sandbox.require_idle()
                run_once(
                    core=core,
                    transport_policy=config.object_policy,
                    clock=clock,
                    workspace_root=Path(config.workspace_root),
                    heartbeat_millis=config.heartbeat_interval_millis,
                    compute=sandbox.compute_surface_profile,
                )
            except (
                SurfaceProfileCoreClientError,
                SurfaceProfileWorkerConfigError,
                SpatialDataWorkerError,
            ):
                if once:
                    raise
                stop.wait(
                    min(
                        config.policy.max_retry_backoff_seconds,
                        config.policy.resource_envelope.max_deadline_seconds,
                    )
                )
            if once:
                break
            stop.wait(config.poll_interval_seconds)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="명시적으로 활성화된 단면 일꾼")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--core-token-file", required=True, type=Path)
    parser.add_argument("--once", action="store_true", help="한 번 폴링하고 종료한다")
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
        SurfaceProfileWorkerConfigError,
        SurfaceProfileCoreClientError,
        SpatialDataWorkerError,
    ) as exc:
        print(exc.reason, file=sys.stderr)
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
