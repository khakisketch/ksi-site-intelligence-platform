"""단면 일꾼의 명시적 상시 실행. 환경 변수 자격이나 운영 대체 경로는 없다.

이 서비스는 OS 수준 격리를 제공하지 않는다. 계산은 이 프로세스 안에서 `run_once`가 한다.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

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
    token = _token(token_path)

    def current_authority() -> bool:
        if stop.is_set():
            return False
        # 호출마다 설정을 다시 읽어 철회·만료·교체를 반영한다. 같지 않으면 현재 권한이 아니다.
        return load_surface_profile_worker_config(config_path, now=clock()) == config

    with SurfaceProfileCoreClient(
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
    ) as core:
        while not stop.is_set():
            try:
                run_once(
                    core=core,
                    transport_policy=config.object_policy,
                    clock=clock,
                    workspace_root=Path(config.workspace_root),
                    heartbeat_millis=config.heartbeat_interval_millis,
                )
            except (SurfaceProfileCoreClientError, SurfaceProfileWorkerConfigError):
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
    except (SurfaceProfileWorkerConfigError, SurfaceProfileCoreClientError) as exc:
        print(exc.reason, file=sys.stderr)
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
