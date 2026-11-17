"""단면 일꾼의 명시적 상시 실행: 서명된 설정, 호출마다 현재 권한 재확인, 환경 자격 거부.

Core 소유자는 단위 시험용 대역이고 OS 격리는 없다. 실제 객체 서버와 Core 라우터는 쓴다.
"""

from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from surface_profile_job_fixture import write_raster
from test_surface_profile_runner import (
    TOKEN,
    _Bridge,
    issue,
    lane,
    object_server,
    view,
)


def write_config(tmp_path: Path, graph: Any, origin: str, **changes: Any) -> Path:
    key = Ed25519PrivateKey.generate()
    body: dict[str, Any] = {
        "version": "surface-profile-worker-config.v1",
        "coreOrigin": "https://core.invalid",
        "maximumResponseBytes": 1_000_000,
        "maximumRequestBytes": 500_000,
        "requestTimeoutSeconds": 2.0,
        "pollIntervalSeconds": 0.05,
        "heartbeatIntervalMillis": 100,
        "workspaceRoot": str(graph.workspace),
        "policy": graph.lane.policy.model_dump(by_alias=True, mode="json"),
        "runtime": graph.lane.runtime.model_dump(by_alias=True, mode="json"),
        "activation": graph.activation.model_dump(by_alias=True, mode="json"),
        "activationSignature": base64.b64encode(
            key.sign(graph.activation.signing_bytes())
        ).decode(),
        "trustedPublicKey": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
        "revokedActivationDigests": [],
        "objectTransport": {
            "endpoints": [{"origin": origin, "addresses": ["127.0.0.1"]}],
            "maxHeaderBytes": 4096,
            "maxObjectBytes": 4096,
            "maxChunkBytes": 4096,
        },
    }
    body.update(changes)
    path = tmp_path / "worker-config.json"
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    return path


def write_token(tmp_path: Path, value: str = TOKEN) -> Path:
    path = tmp_path / "core-token"
    path.write_text(value + "\n")
    path.chmod(0o600)
    return path


def serve(
    graph: Any, config: Path, token: Path, transport: httpx.BaseTransport, *, once: bool
) -> int:
    from ksi_processing_controller.surface_profile_service import run_worker

    return run_worker(
        config_path=config,
        token_path=token,
        stop=threading.Event(),
        clock=lambda: graph.now,
        once=once,
        transport=transport,
    )


def test_service_polls_with_signed_config_and_completes_a_job(tmp_path: Path) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        config = write_config(tmp_path, graph, origin)
        assert serve(graph, config, write_token(tmp_path), _Bridge(graph.http), once=True) == 0
        assert view(graph, job_id)["executionState"] == "COMPLETED"


def test_revocation_after_start_stops_core_calls_before_a_lease_is_taken(tmp_path: Path) -> None:
    from ksi_processing_controller.surface_profile_core_client import SurfaceProfileCoreClientError

    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        config = write_config(tmp_path, graph, origin)
        calls: list[str] = []

        class Revoking(_Bridge):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                calls.append(request.method + " " + request.url.path)
                response = super().handle_request(request)
                body = json.loads(config.read_text())
                body["revokedActivationDigests"] = [body["activation"]["activationDigest"]]
                config.write_text(json.dumps(body))
                return response

        with pytest.raises(SurfaceProfileCoreClientError) as error:
            serve(graph, config, write_token(tmp_path), Revoking(graph.http), once=True)
        assert error.value.reason == "ACTIVATION_UNAVAILABLE"
        assert len(calls) == 1 and calls[0].startswith("GET ")  # pending 뒤에는 어떤 호출도 없다
        assert view(graph, job_id)["executionState"] == "QUEUED"


def test_an_unreadable_token_stops_core_calls_and_leaves_the_job_queued(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.surface_profile_core_client import SurfaceProfileCoreClientError

    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        config = write_config(tmp_path, graph, origin)
        token = write_token(tmp_path)

        class DropToken(_Bridge):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                token.chmod(0o644)  # 소유자 전용이 아니게 되면 자격은 쓸 수 없다
                return super().handle_request(request)

        with pytest.raises(SurfaceProfileCoreClientError) as error:
            serve(graph, config, token, DropToken(graph.http), once=True)
        assert error.value.reason == "ACTIVATION_UNAVAILABLE"
        assert view(graph, job_id)["executionState"] == "QUEUED"


def test_cli_requires_explicit_config_and_token_and_ignores_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ksi_processing_controller.surface_profile_service import main

    monkeypatch.setenv("CORE_TOKEN", "from-environment")
    with pytest.raises(SystemExit) as exited:
        main(["--config", str(tmp_path / "missing.json")])
    assert exited.value.code == 2
    assert main(["--config", str(tmp_path / "missing.json"), "--core-token-file", "/x"]) == 2
    assert "from-environment" not in capsys.readouterr().err
