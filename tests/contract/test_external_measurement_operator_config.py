"""Strict V2 measurement operator configuration and local preflight coverage."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _write_private(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def measurement_operator_config(tmp_path: Path, *, listener_path: Path | None = None) -> Path:
    """Build one local, signed V2-only config fixture without a live runtime."""

    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
    )
    from test_external_measurement_protocol import measurement_manifest_request

    manifest, _request = measurement_manifest_request()
    private_key = Ed25519PrivateKey.generate()
    body = manifest.body
    signature_bytes = private_key.sign(body.canonical_body_bytes())
    signed_manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="measurement-fixture",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(signature_bytes).decode("ascii"),
        ),
    )
    manifest_path = tmp_path / "measurement-manifest.json"
    _write_private(
        manifest_path,
        json.dumps(
            signed_manifest.model_dump(by_alias=True, mode="json"), separators=(",", ":")
        ).encode(),
    )
    revocations = json.dumps(
        {"version": "external-inspector-revocations.v1", "revokedManifestDigests": []},
        separators=(",", ":"),
    ).encode()
    revocation_path = tmp_path / "measurement-revocations.json"
    _write_private(revocation_path, revocations)
    oci_pairs = json.dumps(
        {
            "version": "external-inspector-oci-pairs.v1",
            "pairs": [
                {
                    "ociManifestDigest": body.image_identity.oci_manifest_digest,
                    "ociConfigDigest": body.image_identity.oci_config_digest,
                    "dockerImageId": body.image_identity.oci_config_digest,
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    pairs_path = tmp_path / "measurement-oci-pairs.json"
    _write_private(pairs_path, oci_pairs)
    uid_map = tmp_path / "uid-map"
    gid_map = tmp_path / "gid-map"
    _write_private(uid_map, b"0 1001 1\n")
    _write_private(gid_map, b"0 1001 1\n")
    launcher_uid = os.geteuid()
    launcher_gid = os.getegid()
    worker_uid = launcher_uid + 10_000
    selected_listener = listener_path if listener_path is not None else tmp_path / "listener.sock"
    public_key = base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")
    payload = {
        "version": "external-measurement-operator-config.v2",
        "production": {
            "requiredWorkerUid": worker_uid,
            "listener": {
                "socketPath": os.fspath(selected_listener),
                "expectedOwnerUid": launcher_uid,
            },
            "catalog": {
                "manifestPath": os.fspath(manifest_path),
                "revocationPath": os.fspath(revocation_path),
                "expectedRevocationSha256": "sha256:" + hashlib.sha256(revocations).hexdigest(),
            },
            "trustRoot": {"publicKeys": {"measurement-fixture": public_key}},
            "inputRoot": os.fspath(tmp_path / "primary-input"),
            "readerMapping": {
                "uidMapPath": os.fspath(uid_map),
                "gidMapPath": os.fspath(gid_map),
                "maximumMapBytes": 4096,
            },
            "journalPath": os.fspath(tmp_path / "attempts.jsonl"),
            "dockerSocket": {
                "socketPath": os.fspath(tmp_path / "rootless-docker.sock"),
                "expectedOwnerUid": launcher_uid,
                "expectedMode": 0o600,
                "maximumResponseBytes": 4096,
            },
            "ociPairs": {
                "proofPath": os.fspath(pairs_path),
                "expectedSha256": "sha256:" + hashlib.sha256(oci_pairs).hexdigest(),
            },
            "cgroupRoot": {
                "root": os.fspath(tmp_path / "cgroup"),
                "baseControlGroup": "/base.slice/ksi-measurement.slice",
                "maximumControlBytes": 4096,
            },
            "systemdBus": {
                "busKind": "SESSION_BUS",
                "socketPath": os.fspath(tmp_path / "bus.sock"),
                "expectedOwnerUid": launcher_uid,
                "expectedMode": 0o600,
                "timeoutMicros": 1_000,
            },
            "systemdBaseSlice": "ksi-measurement.slice",
            "recoveryTimeoutMillis": 1_000,
            "admissionCapacity": {
                "maximumRequestUnits": 1,
                "maximumConcurrencyUnits": 1,
                "maximumPrimaryStagingBytes": 1_024,
            },
            "protocolLimits": {
                "maxHeaderBytes": 128 * 1024,
                "maxChunkBytes": 1024,
                "maxInputBytes": 2_048,
                "maxOutputBytes": 128 * 1024,
                "maxWireDurationMillis": 1_000,
            },
            "frameLimits": {"maximumFrameBytes": 128 * 1024},
            "cgroupMeasurement": {
                "monitorIntervalMillis": 1,
                "stableFinalSamples": 2,
                "cleanupTimeoutMillis": 1_000,
            },
        },
        "hostProof": {
            "launcherUid": launcher_uid,
            "launcherGid": launcher_gid,
            "workerUid": worker_uid,
            "rootlessDaemonPidPath": os.fspath(tmp_path / "rootless-docker.pid"),
            "daemonUidMapSha256": "sha256:" + "a" * 64,
            "daemonGidMapSha256": "sha256:" + "b" * 64,
            "launcherCgroupPath": "/base.slice/ksi-measurement.slice",
            "daemonCgroupPath": "/base.slice/ksi-measurement.slice/daemon.scope",
            "systemdBaseSlice": "ksi-measurement.slice",
            "dockerSocketPath": os.fspath(tmp_path / "rootless-docker.sock"),
            "retainedInputMode": 0o600,
        },
    }
    config_path = tmp_path / "measurement-operator.json"
    _write_private(config_path, json.dumps(payload, separators=(",", ":")).encode())
    return config_path


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite(path: Path, payload: dict[str, object]) -> None:
    _write_private(path, json.dumps(payload, separators=(",", ":")).encode())


def test_v2_config_preflights_signed_measurement_profiles_and_exact_oci_pair(
    tmp_path: Path,
) -> None:
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
        validate_measurement_operator_startup_artifacts,
    )

    config = load_external_measurement_operator_config(measurement_operator_config(tmp_path))
    validate_measurement_operator_startup_artifacts(config)
    assert config.production.systemd_base_slice == "ksi-measurement.slice"
    assert config.production.admission_capacity.maximum_primary_staging_bytes == 1_024


@pytest.mark.parametrize(
    "field",
    ["inspector_protocol_digest", "backend_profile_digest", "security_profile_digest"],
)
def test_v2_preflight_rejects_validly_signed_nonmeasurement_profile(
    tmp_path: Path, field: str
) -> None:
    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
        parse_inspector_execution_manifest_wire,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        MeasurementOperatorConfigBlockedCode,
        MeasurementOperatorConfigUnavailable,
        load_external_measurement_operator_config,
        validate_measurement_operator_startup_artifacts,
    )

    config_path = measurement_operator_config(tmp_path)
    manifest_path = tmp_path / "measurement-manifest.json"
    original = parse_inspector_execution_manifest_wire(json.loads(manifest_path.read_bytes()))
    private_key = Ed25519PrivateKey.generate()
    body = original.body.model_copy(update={field: "sha256:" + "0" * 64})
    rewritten = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="measurement-replacement",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(private_key.sign(body.canonical_body_bytes())).decode(
                "ascii"
            ),
        ),
    )
    _write_private(
        manifest_path,
        json.dumps(
            rewritten.model_dump(by_alias=True, mode="json"), separators=(",", ":")
        ).encode(),
    )
    payload: dict[str, Any] = _payload(config_path)
    payload["production"]["trustRoot"] = {
        "publicKeys": {
            "measurement-replacement": base64.b64encode(
                private_key.public_key().public_bytes_raw()
            ).decode("ascii")
        }
    }
    _rewrite(config_path, payload)

    config = load_external_measurement_operator_config(config_path)
    with pytest.raises(MeasurementOperatorConfigUnavailable) as blocked:
        validate_measurement_operator_startup_artifacts(config)
    assert blocked.value.code is MeasurementOperatorConfigBlockedCode.CATALOG


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["production"].update(outputRoot="/forbidden"),
        lambda payload: payload["production"]["frameLimits"].update(maximumStderrBytes=1),
        lambda payload: payload["production"]["admissionCapacity"].update(
            maximumConcurrencyUnits=2
        ),
        lambda payload: payload["production"].update(systemdBaseSlice="ksi-inspector.slice"),
        lambda payload: payload.update(version="external-inspector-operator-config.v1"),
    ],
)
def test_v2_config_rejects_v1_shape_and_fixed_runtime_widening(tmp_path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    from ksi_processing_controller.external_measurement_operator_config import (
        MeasurementOperatorConfigUnavailable,
        load_external_measurement_operator_config,
    )

    config_path = measurement_operator_config(tmp_path)
    payload = _payload(config_path)
    mutate(payload)
    _rewrite(config_path, payload)
    with pytest.raises(MeasurementOperatorConfigUnavailable):
        load_external_measurement_operator_config(config_path)


@pytest.mark.parametrize(
    "contents",
    [b'{"version":"external-measurement-operator-config.v2","version":"dup"}', b'{"value":NaN}'],
)
def test_v2_config_rejects_duplicate_and_nonfinite_json(tmp_path: Path, contents: bytes) -> None:
    from ksi_processing_controller.external_measurement_operator_config import (
        MeasurementOperatorConfigBlockedCode,
        MeasurementOperatorConfigUnavailable,
        load_external_measurement_operator_config,
    )

    path = tmp_path / "config.json"
    _write_private(path, contents)
    with pytest.raises(MeasurementOperatorConfigUnavailable) as blocked:
        load_external_measurement_operator_config(path)
    assert blocked.value.code is MeasurementOperatorConfigBlockedCode.CONFIG_SYNTAX


def test_v2_config_rejects_symlink_and_nonprivate_mode(tmp_path: Path) -> None:
    from ksi_processing_controller.external_measurement_operator_config import (
        MeasurementOperatorConfigBlockedCode,
        MeasurementOperatorConfigUnavailable,
        load_external_measurement_operator_config,
    )

    path = measurement_operator_config(tmp_path)
    path.chmod(0o640)
    with pytest.raises(MeasurementOperatorConfigUnavailable) as unsafe_mode:
        load_external_measurement_operator_config(path)
    assert unsafe_mode.value.code is MeasurementOperatorConfigBlockedCode.CONFIG_FILE
    path.chmod(0o600)
    link = tmp_path / "linked-config.json"
    link.symlink_to(path)
    with pytest.raises(MeasurementOperatorConfigUnavailable) as linked:
        load_external_measurement_operator_config(link)
    assert linked.value.code is MeasurementOperatorConfigBlockedCode.CONFIG_FILE
