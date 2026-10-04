"""Issue a representative external-runtime deployment set (Step 3a, test scope).

Builds task-private inspector + measurement operator artifacts -- signed
manifests, revocation records, OCI pair proofs, trust roots, and strict
operator configs -- then proves them with the real startup loaders and
validators used by the daemons.  All host-proof values are explicit CLI
inputs; nothing is sniffed from ambient state.  Private keys never leave the
output directory; the receipt records only key IDs and public-key hashes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class IssuanceError(RuntimeError):
    """A deployment input is malformed or a produced artifact failed verification."""


@dataclass(frozen=True, slots=True)
class LaneInputs:
    key_id: str
    oci_manifest_digest: str
    oci_config_digest: str
    listener_socket_path: str
    launcher_cgroup_path: str
    systemd_base_slice: str


@dataclass(frozen=True, slots=True)
class SharedInputs:
    launcher_uid: int
    launcher_gid: int
    worker_uid: int
    docker_socket_path: str
    systemd_bus_socket_path: str
    daemon_pid_path: str
    daemon_uid_map_sha256: str
    daemon_gid_map_sha256: str
    daemon_cgroup_path: str
    runtime_uid: int
    runtime_gid: int
    subordinate_base: int
    subordinate_count: int
    retained_input_mode: int


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _write_private_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _write_private_json(path: Path, payload: dict[str, Any], *, compact: bool = False) -> None:
    raw = (
        json.dumps(payload, separators=(",", ":"))
        if compact
        else json.dumps(payload, indent=2, sort_keys=True)
    ).encode("utf-8")
    _write_private_file(path, raw)


def _marker(kind: str, key_id: str) -> str:
    return (
        "sha256:" + hashlib.sha256(f"step3a-test-deployment:{key_id}:{kind}".encode()).hexdigest()
    )


def _build_envelope_digest() -> str:
    from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

    envelope = ResourceEnvelopeV1(
        max_input_bytes=20_000_000,
        max_streamed_bytes=20_000_000,
        max_tiff_directories=32,
        max_tiff_entries=2_048,
        max_pixels=2_000_000,
        max_bands=4,
        max_blocks=2_048,
        max_decompressed_bytes=40_000_000,
        max_sample_bytes=40_000_000,
        max_geometry_vertices=8,
        max_cpu_seconds=1.0,
        max_memory_bytes=40_000_000,
        max_workspace_bytes=40_000_000,
        max_output_bytes=20_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=1.0,
        lease_duration_seconds=1.0,
        max_retry_attempts=1,
    ).sealed()
    digest = envelope.resource_envelope_digest
    assert isinstance(digest, str)
    return digest


def _build_signed_manifest(
    *,
    key_id: str,
    private_key: Any,
    oci_manifest_digest: str,
    oci_config_digest: str,
    inspector_protocol_digest: str,
    backend_profile_digest: str,
    security_profile_digest: str,
    resource_envelope_digest: str,
    runtime_uid: int,
    runtime_gid: int,
    source_tree_digest: str,
    build_provenance_digest: str,
    sbom_digest: str,
) -> dict[str, Any]:
    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionHardCeilingsV1,
        InspectorExecutionManifestBodyV1,
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
        InspectorImageIdentityV1,
        InspectorSecurityProfileV1,
    )

    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=oci_manifest_digest,
            oci_config_digest=oci_config_digest,
        ),
        source_tree_digest=source_tree_digest,
        build_provenance_digest=build_provenance_digest,
        sbom_digest=sbom_digest,
        inspector_protocol_digest=inspector_protocol_digest,
        backend_profile_digest=backend_profile_digest,
        security_profile_digest=security_profile_digest,
        resource_envelope_digest=resource_envelope_digest,
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=20_000_000,
            max_memory_bytes=40_000_000,
            max_tmpfs_bytes=40_000_000,
            max_pids=16,
            cpu_period_micros=100_000,
            cpu_quota_micros=50_000,
            max_wall_time_millis=1_000,
            max_log_bytes=2_048,
            max_output_bytes=20_000_000,
        ),
    )
    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id=key_id,
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(private_key.sign(body.canonical_body_bytes())).decode(
                "ascii"
            ),
        ),
    )
    return manifest.model_dump(by_alias=True, mode="json")


def _issue_lane(
    *,
    lane_dir: Path,
    lane: LaneInputs,
    shared: SharedInputs,
    private_key: Any,
    public_b64: str,
    inspector_protocol_digest: str,
    backend_profile_digest: str,
    security_profile_digest: str,
    resource_envelope_digest: str,
    source_tree_digest: str,
    build_provenance_digest: str,
    sbom_digest: str,
    staging_root: Path,
    private_label: str,
) -> dict[str, str]:
    _ensure_dir(lane_dir)
    manifest_wire = _build_signed_manifest(
        key_id=lane.key_id,
        private_key=private_key,
        oci_manifest_digest=lane.oci_manifest_digest,
        oci_config_digest=lane.oci_config_digest,
        inspector_protocol_digest=inspector_protocol_digest,
        backend_profile_digest=backend_profile_digest,
        security_profile_digest=security_profile_digest,
        resource_envelope_digest=resource_envelope_digest,
        runtime_uid=shared.runtime_uid,
        runtime_gid=shared.runtime_gid,
        source_tree_digest=source_tree_digest,
        build_provenance_digest=build_provenance_digest,
        sbom_digest=sbom_digest,
    )
    manifest_path = lane_dir / "manifest.json"
    _write_private_json(manifest_path, manifest_wire, compact=True)

    revocations = {
        "version": "external-inspector-revocations.v1",
        "revokedManifestDigests": [],
    }
    revocation_path = lane_dir / "revocations.json"
    _write_private_json(revocation_path, revocations, compact=True)

    pairs = {
        "version": "external-inspector-oci-pairs.v1",
        "pairs": [
            {
                "ociManifestDigest": lane.oci_manifest_digest,
                "ociConfigDigest": lane.oci_config_digest,
                "dockerImageId": lane.oci_config_digest,
            }
        ],
    }
    pairs_path = lane_dir / "oci-pairs.json"
    _write_private_json(pairs_path, pairs, compact=True)

    trust_path = lane_dir / "trust-public-keys.json"
    _write_private_json(trust_path, {"publicKeys": {lane.key_id: public_b64}})

    if lane.systemd_base_slice == "ksi-measurement.slice":
        cgroup_base = lane.launcher_cgroup_path
    else:
        cgroup_base = os.path.dirname(lane.launcher_cgroup_path)
        if cgroup_base != lane.launcher_cgroup_path and not cgroup_base.endswith(
            "/" + lane.systemd_base_slice
        ):
            msg = f"cgroup base {cgroup_base!r} does not end with {lane.systemd_base_slice!r}"
            raise IssuanceError(msg)

    input_root = staging_root / f"{private_label}-input"
    _ensure_dir(input_root)
    uid_map_path = staging_root / f"{private_label}-reader-uid-map"
    gid_map_path = staging_root / f"{private_label}-reader-gid-map"
    map_text = (
        f"0 {shared.worker_uid} 1\n1 {shared.subordinate_base} {shared.subordinate_count}\n"
    ).encode()
    _write_private_file(uid_map_path, map_text)
    _write_private_file(gid_map_path, map_text)
    host_proof = {
        "launcherUid": shared.launcher_uid,
        "launcherGid": shared.launcher_gid,
        "workerUid": shared.worker_uid,
        "rootlessDaemonPidPath": shared.daemon_pid_path,
        "daemonUidMapSha256": shared.daemon_uid_map_sha256,
        "daemonGidMapSha256": shared.daemon_gid_map_sha256,
        "launcherCgroupPath": lane.launcher_cgroup_path,
        "daemonCgroupPath": shared.daemon_cgroup_path,
        "systemdBaseSlice": lane.systemd_base_slice,
        "dockerSocketPath": shared.docker_socket_path,
        "retainedInputMode": shared.retained_input_mode,
    }
    production: dict[str, Any] = {
        "requiredWorkerUid": shared.worker_uid,
        "listener": {
            "socketPath": lane.listener_socket_path,
            "expectedOwnerUid": shared.launcher_uid,
        },
        "catalog": {
            "manifestPath": os.fspath(manifest_path),
            "revocationPath": os.fspath(revocation_path),
            "expectedRevocationSha256": _sha256_file(revocation_path),
        },
        "trustRoot": {"publicKeys": {lane.key_id: public_b64}},
        "inputRoot": os.fspath(input_root),
        "readerMapping": {
            "uidMapPath": os.fspath(uid_map_path),
            "gidMapPath": os.fspath(gid_map_path),
            "maximumMapBytes": 4096,
        },
        "journalPath": os.fspath(staging_root / f"{private_label}-attempts.jsonl"),
        "dockerSocket": {
            "socketPath": shared.docker_socket_path,
            "expectedOwnerUid": shared.launcher_uid,
            "expectedMode": 0o600,
            "maximumResponseBytes": 4096,
        },
        "ociPairs": {
            "proofPath": os.fspath(pairs_path),
            "expectedSha256": _sha256_file(pairs_path),
        },
        "cgroupRoot": {
            "root": os.fspath(staging_root / f"{private_label}-cgroup"),
            "baseControlGroup": cgroup_base,
            "maximumControlBytes": 4096,
        },
        "systemdBus": {
            "busKind": "SESSION_BUS",
            "socketPath": shared.systemd_bus_socket_path,
            "expectedOwnerUid": shared.launcher_uid,
            "expectedMode": 0o600,
            "timeoutMicros": 1_000,
        },
        "systemdBaseSlice": lane.systemd_base_slice,
        "recoveryTimeoutMillis": 1_000,
        "protocolLimits": {
            "maxHeaderBytes": 128 * 1024,
            "maxChunkBytes": 1024,
            "maxInputBytes": 2_048,
            "maxOutputBytes": 128 * 1024,
            "maxWireDurationMillis": 1_000,
        },
        "cgroupMeasurement": {
            "monitorIntervalMillis": 1,
            "stableFinalSamples": 2,
            "cleanupTimeoutMillis": 1_000,
        },
    }
    if lane.systemd_base_slice == "ksi-measurement.slice":
        production["admissionCapacity"] = {
            "maximumRequestUnits": 1,
            "maximumConcurrencyUnits": 1,
            "maximumPrimaryStagingBytes": 1_024,
        }
        production["frameLimits"] = {"maximumFrameBytes": 128 * 1024}
        version = "external-measurement-operator-config.v2"
    else:
        production["outputRoot"] = os.fspath(staging_root / f"{private_label}-output")
        _ensure_dir(Path(production["outputRoot"]))
        production["admissionCapacity"] = {
            "maximumRequestUnits": 1,
            "maximumConcurrencyUnits": 1,
            "maximumSpoolBytes": 10,
        }
        production["frameLimits"] = {"maximumFrameBytes": 10, "maximumStderrBytes": 0}
        version = "external-inspector-operator-config.v1"
    config_path = lane_dir / "operator-config.json"
    _write_private_json(
        config_path, {"version": version, "production": production, "hostProof": host_proof}
    )
    return {
        "manifest": _sha256_file(manifest_path),
        "revocations": _sha256_file(revocation_path),
        "ociPairs": _sha256_file(pairs_path),
        "trustPublicKeys": _sha256_file(trust_path),
        "operatorConfig": _sha256_file(config_path),
        "version": version,
    }


def _self_verify(out: Path) -> dict[str, str]:
    from ksi_processing_controller.external_inspector_operator_config import (
        load_external_inspector_operator_config,
        validate_operator_startup_artifacts,
    )
    from ksi_processing_controller.external_measurement_operator_config import (
        load_external_measurement_operator_config,
        validate_measurement_operator_startup_artifacts,
    )

    validate_operator_startup_artifacts(
        load_external_inspector_operator_config(out / "inspector" / "operator-config.json")
    )
    validate_measurement_operator_startup_artifacts(
        load_external_measurement_operator_config(out / "measurement" / "operator-config.json")
    )
    return {"inspector": "ACCEPTED", "measurement": "ACCEPTED"}


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise IssuanceError(f"{name} must be a base-10 integer") from exc
    if value <= 0:
        raise IssuanceError(f"{name} must be positive")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="fresh output directory to create")
    parser.add_argument("--inspector-key-id", default="step3a-inspector-20261004")
    parser.add_argument("--measurement-key-id", default="step3a-measurement-20261004")
    for lane in ("inspector", "measurement"):
        parser.add_argument(f"--{lane}-oci-manifest-digest", required=True)
        parser.add_argument(f"--{lane}-oci-config-digest", required=True)
        parser.add_argument(f"--{lane}-listener-socket-path", required=True)
        parser.add_argument(f"--{lane}-launcher-cgroup-path", required=True)
    parser.add_argument("--launcher-uid", required=True)
    parser.add_argument("--launcher-gid", required=True)
    parser.add_argument("--worker-uid", required=True)
    parser.add_argument("--docker-socket-path", required=True)
    parser.add_argument("--systemd-bus-socket-path", required=True)
    parser.add_argument("--daemon-pid-path", required=True)
    parser.add_argument("--daemon-uid-map-sha256", required=True)
    parser.add_argument("--daemon-gid-map-sha256", required=True)
    parser.add_argument("--daemon-cgroup-path", required=True)
    parser.add_argument("--runtime-uid", default="10001")
    parser.add_argument("--runtime-gid", default="10001")
    parser.add_argument("--subordinate-base", default="196608")
    parser.add_argument("--subordinate-count", default="65536")
    parser.add_argument("--provenance-note", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_processing_controller.external_inspector_container_protocol import (
        compiled_inner_protocol_digest_v1,
        compiled_security_profile_digest_v1,
    )
    from ksi_processing_controller.external_measurement_protocol import (
        compiled_measurement_backend_profile_digest_v2,
        compiled_measurement_protocol_digest_v2,
    )

    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if not out.is_absolute():
        raise IssuanceError("--out must be an absolute path")
    if out.exists():
        raise IssuanceError("--out already exists; refuse to mix issuance sets")

    shared = SharedInputs(
        launcher_uid=_positive_int(args.launcher_uid, "launcher-uid"),
        launcher_gid=_positive_int(args.launcher_gid, "launcher-gid"),
        worker_uid=_positive_int(args.worker_uid, "worker-uid"),
        docker_socket_path=args.docker_socket_path,
        systemd_bus_socket_path=args.systemd_bus_socket_path,
        daemon_pid_path=args.daemon_pid_path,
        daemon_uid_map_sha256=args.daemon_uid_map_sha256,
        daemon_gid_map_sha256=args.daemon_gid_map_sha256,
        daemon_cgroup_path=args.daemon_cgroup_path,
        runtime_uid=_positive_int(args.runtime_uid, "runtime-uid"),
        runtime_gid=_positive_int(args.runtime_gid, "runtime-gid"),
        subordinate_base=_positive_int(args.subordinate_base, "subordinate-base"),
        subordinate_count=_positive_int(args.subordinate_count, "subordinate-count"),
        retained_input_mode=0o600,
    )
    if shared.worker_uid == shared.launcher_uid:
        raise IssuanceError("worker UID must differ from launcher UID")
    lanes = {
        "inspector": LaneInputs(
            key_id=args.inspector_key_id,
            oci_manifest_digest=args.inspector_oci_manifest_digest,
            oci_config_digest=args.inspector_oci_config_digest,
            listener_socket_path=args.inspector_listener_socket_path,
            launcher_cgroup_path=args.inspector_launcher_cgroup_path,
            systemd_base_slice="ksi-inspector.slice",
        ),
        "measurement": LaneInputs(
            key_id=args.measurement_key_id,
            oci_manifest_digest=args.measurement_oci_manifest_digest,
            oci_config_digest=args.measurement_oci_config_digest,
            listener_socket_path=args.measurement_listener_socket_path,
            launcher_cgroup_path=args.measurement_launcher_cgroup_path,
            systemd_base_slice="ksi-measurement.slice",
        ),
    }
    if lanes["inspector"].key_id == lanes["measurement"].key_id:
        raise IssuanceError("inspector and measurement key IDs must differ")

    _ensure_dir(out)
    keys_dir = out / "keys"
    _ensure_dir(keys_dir)
    staging_root = out / "staging"
    _ensure_dir(staging_root)

    inspector_protocol = compiled_inner_protocol_digest_v1()
    measurement_protocol = compiled_measurement_protocol_digest_v2()
    measurement_backend = compiled_measurement_backend_profile_digest_v2()
    security_profile = compiled_security_profile_digest_v1()
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )

    inspector_backend = external_geotiff_profile_digest_v1()
    resource_envelope_digest = _build_envelope_digest()

    artifact_hashes: dict[str, dict[str, str]] = {}
    key_records: dict[str, dict[str, str]] = {}
    for label, lane in lanes.items():
        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes_raw()
        public_b64 = base64.b64encode(public_raw).decode("ascii")
        _write_private_file(keys_dir / f"{lane.key_id}.private", private_key.private_bytes_raw())
        key_records[label] = {
            "keyId": lane.key_id,
            "publicKeySha256": "sha256:" + hashlib.sha256(public_raw).hexdigest(),
        }
        if label == "inspector":
            protocol_digest, backend_digest = inspector_protocol, inspector_backend
        else:
            protocol_digest, backend_digest = measurement_protocol, measurement_backend
        artifact_hashes[label] = _issue_lane(
            lane_dir=out / label,
            lane=lane,
            shared=shared,
            private_key=private_key,
            public_b64=public_b64,
            inspector_protocol_digest=protocol_digest,
            backend_profile_digest=backend_digest,
            security_profile_digest=security_profile,
            resource_envelope_digest=resource_envelope_digest,
            source_tree_digest=_marker("source-tree", lane.key_id),
            build_provenance_digest=_marker("provenance", lane.key_id),
            sbom_digest=_marker("sbom", lane.key_id),
            staging_root=staging_root,
            private_label=label,
        )

    validation = _self_verify(out)
    receipt: dict[str, Any] = {
        "version": "step3a-issuance-receipt.v1",
        "scope": "test-deployment-only",
        "inspectorKeyId": key_records["inspector"]["keyId"],
        "measurementKeyId": key_records["measurement"]["keyId"],
        "inspectorPublicKeySha256": key_records["inspector"]["publicKeySha256"],
        "measurementPublicKeySha256": key_records["measurement"]["publicKeySha256"],
        "compiledDigests": {
            "inspectorProtocolDigest": inspector_protocol,
            "inspectorBackendProfileDigest": inspector_backend,
            "measurementProtocolDigest": measurement_protocol,
            "measurementBackendProfileDigest": measurement_backend,
            "securityProfileDigest": security_profile,
            "resourceEnvelopeDigest": resource_envelope_digest,
        },
        "artifactHashes": artifact_hashes,
        "observedHostValues": {
            "launcherUid": shared.launcher_uid,
            "launcherGid": shared.launcher_gid,
            "workerUid": shared.worker_uid,
            "dockerSocketPath": shared.docker_socket_path,
            "systemdBusSocketPath": shared.systemd_bus_socket_path,
            "daemonPidPath": shared.daemon_pid_path,
            "daemonUidMapSha256": shared.daemon_uid_map_sha256,
            "daemonGidMapSha256": shared.daemon_gid_map_sha256,
            "daemonCgroupPath": shared.daemon_cgroup_path,
            "inspectorLauncherCgroupPath": lanes["inspector"].launcher_cgroup_path,
            "measurementLauncherCgroupPath": lanes["measurement"].launcher_cgroup_path,
            "inspectorListenerSocketPath": lanes["inspector"].listener_socket_path,
            "measurementListenerSocketPath": lanes["measurement"].listener_socket_path,
        },
        "syntheticMarkers": "sourceTreeDigest/buildProvenanceDigest/sbomDigest are "
        "test-deployment markers, not release evidence",
        "validation": validation,
        "provenanceNote": args.provenance_note,
    }
    receipt_path = out / "step3a-receipt.json"
    _write_private_json(receipt_path, receipt)
    node = receipt_path.stat()
    assert stat.S_ISREG(node.st_mode) and node.st_nlink == 1
    print(json.dumps({"out": os.fspath(out), "validation": validation}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IssuanceError as exc:
        print(f"issuance refused: {exc}", flush=True)
        raise SystemExit(2) from exc
