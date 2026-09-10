"""The operational external worker has no implicit configuration or credential source."""

from __future__ import annotations

import base64
import hashlib
import json

import ksi_processing_controller.external_validation_worker as worker
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
)
from ksi_processing_controller.external_validation_lanes import (
    InspectionValidationLane,
    MeasurementValidationLane,
)
from ksi_processing_controller.external_validation_runner import ExternalLane
from ksi_processing_controller.external_validation_worker import (
    build_validation_worker_graph,
    main,
)
from ksi_processing_controller.external_validation_worker_config import (
    load_external_validation_worker_config,
)
from test_external_validation_worker_config import _body, _write_secure_json


def test_external_worker_cli_fails_closed_without_explicit_config_and_token() -> None:
    assert main([]) == 2


def test_external_worker_cli_runs_one_trusted_graph_then_closes_it(tmp_path, monkeypatch) -> None:
    config = _valid_config(tmp_path)
    token_path = tmp_path / "core.token"
    token_path.write_text("private-worker-token\n", encoding="ascii")
    token_path.chmod(0o600)
    calls: list[str] = []

    class Runner:
        def request_stop(self) -> None:
            calls.append("stop")

        def run_forever(self) -> None:
            calls.append("run")

    class Graph:
        runner = Runner()

        def close(self) -> None:
            calls.append("close")

    def build(received, *, core_token: str) -> Graph:
        assert received == config
        assert core_token == "private-worker-token"
        calls.append("build")
        return Graph()

    monkeypatch.setattr(worker, "build_validation_worker_graph", build)

    assert (
        main(
            [
                "--config",
                str(tmp_path / "runner.json"),
                "--core-token-file",
                str(token_path),
            ]
        )
        == 0
    )
    assert calls == ["build", "run", "close"]


def test_external_worker_cli_returns_safe_error_when_normal_shutdown_cleanup_fails(
    tmp_path, monkeypatch
) -> None:
    _valid_config(tmp_path)
    token_path = tmp_path / "core.token"
    token_path.write_text("private-worker-token\n", encoding="ascii")
    token_path.chmod(0o600)

    class Runner:
        def request_stop(self) -> None:
            pass

        def run_forever(self) -> None:
            pass

    class Graph:
        runner = Runner()

        def close(self) -> None:
            raise RuntimeError("synthetic cleanup failure")

    monkeypatch.setattr(worker, "build_validation_worker_graph", lambda *_args, **_kwargs: Graph())

    assert (
        main(
            [
                "--config",
                str(tmp_path / "runner.json"),
                "--core-token-file",
                str(token_path),
            ]
        )
        == 2
    )


def _valid_config(tmp_path):
    from test_external_measurement_protocol import measurement_manifest_request

    unsigned, _launch = measurement_manifest_request()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    manifest = InspectorExecutionManifestV1(
        body=unsigned.body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="measurement-key",
            digest=unsigned.canonical_body_digest(),
            signature=base64.b64encode(private.sign(unsigned.canonical_body_bytes())).decode(
                "ascii"
            ),
        ),
    )
    manifest_path = tmp_path / "measurement-manifest.json"
    manifest_path.write_text(json.dumps(manifest.model_dump(by_alias=True, mode="json")), "utf-8")
    revocations = b'{"version":"external-inspector-revocations.v1","revokedManifestDigests":[]}'
    revocation_path = tmp_path / "measurement-revocations.json"
    revocation_path.write_bytes(revocations)
    body = _body(tmp_path)
    body["measurement"]["manifest"] = {
        "path": str(manifest_path),
        "expectedSha256": "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "expectedBodyDigest": manifest.canonical_body_digest(),
        "revocationPath": str(revocation_path),
        "expectedRevocationSha256": "sha256:" + hashlib.sha256(revocations).hexdigest(),
        "trustedPublicKeys": {"measurement-key": base64.b64encode(public).decode("ascii")},
    }
    config_path = tmp_path / "runner.json"
    _write_secure_json(config_path, body)
    return load_external_validation_worker_config(config_path)


def test_graph_assembles_one_real_adapter_for_each_fixed_lane_after_manifest_preflight(
    tmp_path,
) -> None:
    graph = build_validation_worker_graph(
        _valid_config(tmp_path), core_token="private-worker-token"
    )
    try:
        lanes = graph.runner._lanes
        assert tuple(lane.lane for lane in lanes) == tuple(ExternalLane)
        assert isinstance(lanes[0], InspectionValidationLane)
        assert all(isinstance(lane, MeasurementValidationLane) for lane in lanes[1:])
    finally:
        graph.close()


def test_graph_failure_closes_measurement_adapter_then_shared_core_on_base_exception(
    monkeypatch, tmp_path
) -> None:
    closed: list[str] = []

    class ValidationCore:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            closed.append("validation")

    class MeasurementCore:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:
            closed.append("measurement")

    def interrupt_assembly(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "load_pinned_measurement_manifest", lambda _settings: object())
    monkeypatch.setattr(worker, "ExternalValidationCoreClient", ValidationCore)
    monkeypatch.setattr(worker, "ExternalMeasurementCoreClient", MeasurementCore)
    monkeypatch.setattr(worker, "InspectionValidationLane", interrupt_assembly)

    with pytest.raises(KeyboardInterrupt):
        worker.build_validation_worker_graph(
            _valid_config(tmp_path), core_token="private-worker-token"
        )

    assert closed == ["measurement", "validation"]
