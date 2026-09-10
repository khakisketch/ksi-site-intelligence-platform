"""Strict external-runner operator configuration; no ambient runtime inputs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import InspectorOperation
from ksi_processing_controller.external_validation_worker_config import (
    ExternalValidationWorkerConfigBlocked,
    ExternalValidationWorkerConfigBlockedCode,
    FixedInspectionUdsConnector,
    LocalWorkerSocketIdentityV1,
    load_external_validation_worker_config,
    load_pinned_measurement_manifest,
    read_external_validation_core_token,
)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _body(tmp_path) -> dict[str, object]:
    identity = {
        "socketPath": str(tmp_path / "inspector.sock"),
        "ownerUid": os.geteuid(),
        "ownerGid": os.getegid(),
        "socketMode": 384,
        "peerUid": os.geteuid(),
    }
    return {
        "version": "external-validation-worker-config.v1",
        "core": {
            "baseUrl": "https://core.example",
            "maximumResponseBytes": 4096,
            "requestTimeoutMillis": 500,
        },
        "worker": {"instanceId": "123e4567-e89b-42d3-a456-426614174000"},
        "runner": {
            "turnBudgetMillis": 1000,
            "claimRetryMillis": 500,
            "idleBackoffMillis": 100,
            "failureBackoffMillis": 200,
        },
        "objectTransport": {
            "endpoints": [{"origin": "http://127.0.0.1:8080", "addresses": ["127.0.0.1"]}],
            "maxHeaderBytes": 1024,
            "maxObjectBytes": 4096,
            "maxChunkBytes": 256,
        },
        "inspection": {
            "uds": identity,
            "privateOutputRoot": str(tmp_path / "private-output"),
            "protocolLimits": {
                "maxHeaderBytes": 1024,
                "maxChunkBytes": 256,
                "maxInputBytes": 4096,
                "maxOutputBytes": 4096,
                "maxWireDurationMillis": 500,
            },
            "workerLimits": {
                "heartbeatIntervalMillis": 10,
                "maxAuthorityWaitMillis": 500,
            },
            "pinnedProfile": {
                "parserBuildDigest": _digest("a"),
                "grammarDigest": external_geotiff_profile_digest_v1(),
            },
        },
        "measurement": {
            "uds": {
                **identity,
                "socketPath": str(tmp_path / "measurement.sock"),
            },
            "protocolLimits": {
                "maxHeaderBytes": 1024,
                "maxChunkBytes": 256,
                "maxInputBytes": 4096,
                "maxOutputBytes": 4096,
                "maxWireDurationMillis": 500,
            },
            "heartbeatIntervalMillis": 10,
            "manifest": {
                "path": str(tmp_path / "measurement-manifest.json"),
                "expectedSha256": _digest("b"),
                "expectedBodyDigest": _digest("c"),
                "revocationPath": str(tmp_path / "measurement-revocations.json"),
                "expectedRevocationSha256": _digest("d"),
                "trustedPublicKeys": {
                    "measurement-key": base64.b64encode(b"k" * 32).decode("ascii")
                },
            },
        },
    }


def _write_secure_json(path, body: object) -> None:
    path.write_text(json.dumps(body), encoding="utf-8")
    path.chmod(0o600)


def test_strict_runner_config_requires_every_explicit_external_boundary(tmp_path) -> None:
    path = tmp_path / "runner.json"
    _write_secure_json(path, _body(tmp_path))

    config = load_external_validation_worker_config(path)

    assert config.worker_instance_id == "123e4567-e89b-42d3-a456-426614174000"
    assert config.runner_policy.failure_backoff_seconds == 0.2
    assert config.inspection.profile.parser_build_digest == _digest("a")
    assert config.measurement.manifest.expected_sha256 == _digest("b")
    assert config.object_policy.endpoints[0].addresses == ("127.0.0.1",)


@pytest.mark.parametrize(
    ("backend_profile_digest", "accepted"),
    [(None, True), ("sha256:" + "e" * 64, False)],
)
def test_measurement_manifest_requires_exact_v2_profile_file_body_signature_and_revocation_proofs(
    tmp_path, backend_profile_digest, accepted
) -> None:
    from test_external_measurement_protocol import measurement_manifest_request

    unsigned, _launch = measurement_manifest_request()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    manifest_body = unsigned.body
    if backend_profile_digest is not None:
        manifest_body = manifest_body.model_copy(
            update={"backend_profile_digest": backend_profile_digest}
        )
    signature = InspectorExecutionManifestSignatureV1(
        algorithm="Ed25519",
        key_id="measurement-key",
        digest=manifest_body.canonical_body_digest(),
        signature=base64.b64encode(private.sign(manifest_body.canonical_body_bytes())).decode(
            "ascii"
        ),
    )
    manifest = InspectorExecutionManifestV1(body=manifest_body, signature=signature)
    manifest_path = tmp_path / "measurement-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )
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

    settings = load_external_validation_worker_config(config_path).measurement
    if accepted:
        assert load_pinned_measurement_manifest(settings) == manifest
    else:
        with pytest.raises(ExternalValidationWorkerConfigBlocked) as exc:
            load_pinned_measurement_manifest(settings)
        assert exc.value.code is ExternalValidationWorkerConfigBlockedCode.CONFIG_VALUE


@pytest.mark.parametrize("mutation", ["unknown", "missing", "mode", "duplicate", "nonfinite"])
def test_runner_config_rejects_unsafe_or_ambiguous_input_before_graph_assembly(
    tmp_path, mutation
) -> None:
    path = tmp_path / "runner.json"
    body = _body(tmp_path)
    if mutation == "unknown":
        body["unexpected"] = True
    elif mutation == "missing":
        del body["measurement"]
    elif mutation == "mode":
        _write_secure_json(path, body)
        path.chmod(0o644)
    elif mutation == "duplicate":
        path.write_text('{"version":"x","version":"x"}', encoding="utf-8")
        path.chmod(0o600)
    elif mutation == "nonfinite":
        path.write_text('{"version":NaN}', encoding="utf-8")
        path.chmod(0o600)
    if mutation not in {"mode", "duplicate", "nonfinite"}:
        _write_secure_json(path, body)

    with pytest.raises(ExternalValidationWorkerConfigBlocked) as exc:
        load_external_validation_worker_config(path)

    assert exc.value.code in {
        ExternalValidationWorkerConfigBlockedCode.CONFIG_FILE,
        ExternalValidationWorkerConfigBlockedCode.CONFIG_SYNTAX,
        ExternalValidationWorkerConfigBlockedCode.CONFIG_VALUE,
        ExternalValidationWorkerConfigBlockedCode.UNKNOWN_FIELD,
    }


def test_core_token_is_an_explicit_private_regular_file_and_never_a_config_value(tmp_path) -> None:
    token = tmp_path / "core.token"
    token.write_text("private-worker-token\n", encoding="ascii")
    token.chmod(0o600)

    assert read_external_validation_core_token(token) == "private-worker-token"

    token.chmod(0o644)
    with pytest.raises(ExternalValidationWorkerConfigBlocked) as exc:
        read_external_validation_core_token(token)
    assert exc.value.code is ExternalValidationWorkerConfigBlockedCode.TOKEN_FILE


def test_fixed_inspector_connector_accepts_only_the_preprovisioned_owned_uds_peer(tmp_path) -> None:
    path = tmp_path / "inspector.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(1)
    accepted: list[socket.socket] = []

    def accept_once() -> None:
        connection, _address = listener.accept()
        accepted.append(connection)

    thread = threading.Thread(target=accept_once)
    thread.start()
    connector = FixedInspectionUdsConnector(
        LocalWorkerSocketIdentityV1(
            path=path,
            owner_uid=os.geteuid(),
            owner_gid=os.getegid(),
            mode=0o600,
            peer_uid=os.geteuid(),
        )
    )
    try:
        connection = connector(
            time.monotonic() + 1,
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
        connection.close()
    finally:
        thread.join(timeout=1)
        for connection in accepted:
            connection.close()
        listener.close()
    assert not thread.is_alive()


def test_fixed_inspector_connector_stops_while_a_real_uds_backlog_is_saturated(tmp_path) -> None:
    """A stopped runner cannot wait for the rest of its turn in connect()."""

    path = tmp_path / "inspector.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(1)
    saturated: list[socket.socket] = []
    for _ in range(2):
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.setblocking(False)
        assert peer.connect_ex(str(path)) == 0
        saturated.append(peer)
    connector = FixedInspectionUdsConnector(
        LocalWorkerSocketIdentityV1(
            path=path,
            owner_uid=os.geteuid(),
            owner_gid=os.getegid(),
            mode=0o600,
            peer_uid=os.geteuid(),
        )
    )
    calls = 0

    def current() -> bool:
        nonlocal calls
        calls += 1
        return calls < 3

    started = time.monotonic()
    try:
        with pytest.raises(ConnectionAbortedError, match="authority changed"):
            connector(
                time.monotonic() + 1,
                wait_is_current=current,
                heartbeat_interval_millis=5,
            )
    finally:
        for peer in saturated:
            peer.close()
        listener.close()
    assert calls >= 3
    assert time.monotonic() - started < 0.25


def test_pinned_inspection_profile_allows_permitted_source_mimes_but_rejects_wrong_build(
    tmp_path,
) -> None:
    path = tmp_path / "runner.json"
    _write_secure_json(path, _body(tmp_path))
    profile = load_external_validation_worker_config(path).inspection.profile

    assert (
        profile.allows(
            parser_build_digest=_digest("a"),
            grammar_digest=external_geotiff_profile_digest_v1(),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            operation=InspectorOperation.INSPECT,
            deadline_monotonic=time.monotonic() + 1,
        )
        is InspectorOperationProfileDecision.ALLOW
    )
    assert (
        profile.allows(
            parser_build_digest=_digest("a"),
            grammar_digest=external_geotiff_profile_digest_v1(),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="application/octet-stream",
            operation=InspectorOperation.INSPECT,
            deadline_monotonic=time.monotonic() + 1,
        )
        is InspectorOperationProfileDecision.ALLOW
    )
    assert (
        profile.allows(
            parser_build_digest=_digest("c"),
            grammar_digest=external_geotiff_profile_digest_v1(),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="application/octet-stream",
            operation=InspectorOperation.INSPECT,
            deadline_monotonic=time.monotonic() + 1,
        )
        is InspectorOperationProfileDecision.DENY
    )
