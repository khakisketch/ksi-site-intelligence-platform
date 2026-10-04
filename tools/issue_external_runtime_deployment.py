"""Issue a representative external-runtime deployment set (Steps 3a+3b, test scope).

Builds task-private inspector + measurement operator artifacts -- signed
manifests, revocation records, OCI pair proofs, trust roots, and strict
operator configs -- then proves them with the real startup loaders and
validators used by the daemons.  All host-proof values are explicit CLI
inputs; nothing is sniffed from ambient state.  Private keys never leave the
output directory; the receipt records only key IDs and public-key hashes.

Step 3b extends the same deployment directory with representative Core
operator records (authority provider config, key registry, signed provider
snapshot, result workflow config, quantitative catalog, secrets, signing key
set) plus a validation worker config, worker bearer token, and principal
tokens, all proven with the real Core/worker loaders.  ``--extend-existing``
adds Step 3b to a directory that already holds validated Step-3a artifacts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


def _write_private_json(path: Path, payload: object, *, compact: bool = False) -> None:
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


FIXED_AUTHORITY_JOURNAL_PATH = "/var/lib/ksi/data/external-quantitative-authority.jsonl"


@dataclass(frozen=True, slots=True)
class Step3bInputs:
    organization_id: str
    authority_key_id: str
    core_signing_key_id: str
    core_base_url: str
    worker_principal_id: str
    catalog_admin_actor_id: str


@dataclass(frozen=True, slots=True)
class LaneMaterial:
    launcher_uid: int
    launcher_gid: int
    worker_uid: int
    inspector_socket_path: str
    measurement_socket_path: str
    measurement_key_id: str
    measurement_public_b64: str
    measurement_manifest_path: str
    measurement_revocation_path: str


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _marker_hex(kind: str, key_id: str) -> str:
    material = f"step3b-test-deployment:{key_id}:{kind}".encode()
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _lane_material_from_existing(out: Path) -> LaneMaterial:
    for name in (
        "inspector/operator-config.json",
        "measurement/operator-config.json",
        "measurement/trust-public-keys.json",
        "measurement/manifest.json",
        "measurement/revocations.json",
        "step3a-receipt.json",
    ):
        if not (out / name).is_file():
            raise IssuanceError(f"--extend-existing needs an issued Step-3a file: {name}")
    for name in ("core", "worker", "step3b-receipt.json"):
        if (out / name).exists():
            raise IssuanceError(f"--extend-existing refuses to mix with existing {name}")
    inspector_config = json.loads((out / "inspector" / "operator-config.json").read_text())
    measurement_config = json.loads((out / "measurement" / "operator-config.json").read_text())
    trust = json.loads((out / "measurement" / "trust-public-keys.json").read_text())
    host_proof = measurement_config["hostProof"]
    public_keys = trust["publicKeys"]
    if len(public_keys) != 1:
        raise IssuanceError("measurement trust root must pin exactly one key")
    measurement_key_id = next(iter(public_keys))
    if host_proof["workerUid"] != inspector_config["hostProof"]["workerUid"]:
        raise IssuanceError("lane worker UIDs disagree; refuse to extend")
    return LaneMaterial(
        launcher_uid=host_proof["launcherUid"],
        launcher_gid=host_proof["launcherGid"],
        worker_uid=host_proof["workerUid"],
        inspector_socket_path=inspector_config["production"]["listener"]["socketPath"],
        measurement_socket_path=measurement_config["production"]["listener"]["socketPath"],
        measurement_key_id=measurement_key_id,
        measurement_public_b64=public_keys[measurement_key_id],
        measurement_manifest_path=os.fspath(out / "measurement" / "manifest.json"),
        measurement_revocation_path=os.fspath(out / "measurement" / "revocations.json"),
    )


def _build_catalog_record(
    *, organization_id: str, admin_actor_id: str
) -> tuple[Any, dict[str, Any]]:
    """Build one sealed non-synthetic catalog authority record and its catalog file body."""
    from ksi_core.external_quantitative_authority import (
        ExternalQuantitativeCatalogAuthorityRecord,
    )
    from ksi_domain.canonical_json import canonical_json_bytes
    from ksi_event_contracts.external_relative_volume import (
        ExternalRelativeVolumeExecutionPolicyV1,
    )

    now = datetime.now(UTC).replace(microsecond=0)
    valid_from = _iso_z(now - timedelta(hours=1))
    valid_until = _iso_z(now + timedelta(days=7))
    template_fields: dict[str, Any] = {
        "authorizedActorIds": ["operator-a"],
        "validFrom": valid_from,
        "validUntil": valid_until,
        "maximumZoneCellCount": 1000,
        "maximumZoneAreaM2": 1000.0,
    }
    placeholder = ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="step3b-execution-policy",
        version=1,
        algorithm_build_digest=_marker_hex("algorithm", organization_id),
        config_digest=_marker_hex("config", organization_id),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_marker_hex("resource-envelope", organization_id),
        authority_record_digest="sha256:" + "0" * 64,
        synthetic_test_only=False,
    ).sealed()
    placeholder_body = placeholder.model_dump(by_alias=True, mode="json")
    placeholder_body.pop("policyDigest")
    admission = {
        "organizationId": organization_id,
        "executionTemplates": [
            {
                **template_fields,
                "executionPolicy": {
                    key: value
                    for key, value in placeholder_body.items()
                    if key != "authorityRecordDigest"
                },
            }
        ],
    }
    body_digest = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {"domain": "ksi.external-quantitative-catalog.v1", "catalog": admission}
            )
        ).hexdigest()
    )
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id=organization_id,
        catalog_body_digest=body_digest,
        authorized_administration_actor_ids=(admin_actor_id,),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(days=7),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    policy = ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="step3b-execution-policy",
        version=1,
        algorithm_build_digest=_marker_hex("algorithm", organization_id),
        config_digest=_marker_hex("config", organization_id),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_marker_hex("resource-envelope", organization_id),
        authority_record_digest=record.digest,
        synthetic_test_only=False,
    ).sealed()
    policy_body = policy.model_dump(by_alias=True, mode="json")
    policy_body.pop("policyDigest")
    catalog = {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": record.digest,
        "body": {
            "organizationId": organization_id,
            "executionTemplates": [{**template_fields, "executionPolicy": policy_body}],
        },
    }
    return record, catalog


def _issue_step3b(
    *, out: Path, lanes: LaneMaterial, inputs: Step3bInputs, staging_root: Path
) -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_domain.canonical_json import canonical_json_bytes

    for socket_path in (lanes.inspector_socket_path, lanes.measurement_socket_path):
        if len(socket_path.encode("utf-8")) > 107:
            raise IssuanceError(f"worker UDS path exceeds 107 bytes: {socket_path!r}")

    now = datetime.now(UTC).replace(microsecond=0)
    issued_at = _iso_z(now)
    valid_until = _iso_z(now + timedelta(days=7))
    key_not_before = _iso_z(now - timedelta(hours=1))
    key_not_after = _iso_z(now + timedelta(days=30))

    operator_dir = out / "core" / "operator"
    for directory in (
        out / "core",
        operator_dir,
        operator_dir / "secrets",
        operator_dir / "signing",
    ):
        _ensure_dir(directory)
    worker_dir = out / "worker"
    _ensure_dir(worker_dir)
    worker_output = staging_root / "worker-private-output"
    _ensure_dir(worker_output)

    authority_private = Ed25519PrivateKey.generate()
    authority_public_pem = authority_private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    authority_public_raw = authority_private.public_key().public_bytes_raw()
    authority_pem_name = f"{inputs.authority_key_id}.public.pem"
    registry_path = operator_dir / "authority-key-registry.json"
    _write_private_json(
        registry_path,
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": inputs.authority_key_id,
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": authority_pem_name,
                    "notBefore": key_not_before,
                    "notAfter": key_not_after,
                }
            ],
        },
    )
    _write_private_file(operator_dir / authority_pem_name, authority_public_pem)

    catalog_record, catalog = _build_catalog_record(
        organization_id=inputs.organization_id, admin_actor_id=inputs.catalog_admin_actor_id
    )
    catalog_path = operator_dir / "quantitative-catalog.json"
    _write_private_json(catalog_path, catalog)
    unsigned: dict[str, Any] = {
        "version": "external-authority-provider-snapshot.v1",
        "organizationId": inputs.organization_id,
        "sequence": 1,
        "previousSnapshotDigest": None,
        "issuedAt": issued_at,
        "validUntil": valid_until,
        "keyId": inputs.authority_key_id,
        "catalogAuthorities": {
            "records": [catalog_record.event_payload()],
            "currentDigests": [catalog_record.digest],
        },
        "policyAuthorities": {"records": [], "currentDigests": []},
        "evidenceContexts": {"records": [], "currentDigests": []},
        "quantitativeAdministration": {"actions": []},
    }
    signed_bytes = canonical_json_bytes(
        {"domain": "ksi.external-authority-provider-snapshot.v1", "snapshot": unsigned}
    )
    snapshot_path = operator_dir / "authority-snapshot.json"
    _write_private_json(
        snapshot_path,
        {
            **unsigned,
            "signature": base64.b64encode(authority_private.sign(signed_bytes)).decode("ascii"),
        },
    )
    provider_path = operator_dir / "provider.json"
    _write_private_json(
        provider_path,
        {
            "version": "external-authority-provider-config.v1",
            "organizationId": inputs.organization_id,
            "keyRegistryPath": os.fspath(registry_path),
            "snapshotPath": os.fspath(snapshot_path),
            "catalogAdministrationActorId": inputs.catalog_admin_actor_id,
            "leaseTtlSeconds": 60,
            "deadlineAfterIssueSeconds": 120,
            "maxAttempts": 3,
            "maxActiveRequestsPerOrganization": 2,
        },
    )
    workflow_path = operator_dir / "workflow.json"
    _write_private_json(
        workflow_path,
        {
            "version": "external-result-workflow-config.v1",
            "authorityJournalPath": FIXED_AUTHORITY_JOURNAL_PATH,
            "catalogPath": os.fspath(catalog_path),
        },
    )

    core_private = Ed25519PrivateKey.generate()
    core_public_pem = core_private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    core_public_raw = core_private.public_key().public_bytes_raw()
    signing_dir = operator_dir / "signing"
    _write_private_json(
        signing_dir / "keys.json",
        {
            "active": inputs.core_signing_key_id,
            "keys": [{"keyId": inputs.core_signing_key_id, "status": "ACTIVE"}],
        },
    )
    _write_private_file(signing_dir / f"{inputs.core_signing_key_id}.public.pem", core_public_pem)
    _write_private_file(
        signing_dir / f"{inputs.core_signing_key_id}.private.pem",
        core_private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )

    secrets_dir = operator_dir / "secrets"
    _write_private_file(
        secrets_dir / "dashboard-session.secret", secrets.token_urlsafe(48).encode("utf-8")
    )
    _write_private_file(
        secrets_dir / "oidc-client.secret", secrets.token_urlsafe(48).encode("utf-8")
    )

    worker_token = secrets.token_urlsafe(48)
    _write_private_file(worker_dir / "core.token", (worker_token + "\n").encode("ascii"))
    principal_tokens_path = out / "core" / "principal-tokens.json"
    _write_private_json(
        principal_tokens_path,
        [
            {
                "tokenSha256": hashlib.sha256(worker_token.encode("ascii")).hexdigest(),
                "principalId": inputs.worker_principal_id,
                "kind": "PROCESSING_WORKER",
                "organizationId": inputs.organization_id,
            }
        ],
    )

    from ksi_event_contracts.inspector_execution_manifest import (
        parse_inspector_execution_manifest_wire,
    )
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )

    measurement_manifest_raw = Path(lanes.measurement_manifest_path).read_bytes()
    measurement_manifest = parse_inspector_execution_manifest_wire(
        json.loads(measurement_manifest_raw.decode("utf-8"))
    )
    measurement_revocation_raw = Path(lanes.measurement_revocation_path).read_bytes()

    def _uds(socket_path: str) -> dict[str, Any]:
        return {
            "socketPath": socket_path,
            "ownerUid": lanes.launcher_uid,
            "ownerGid": lanes.launcher_gid,
            "socketMode": 0o600,
            "peerUid": lanes.worker_uid,
        }

    protocol_limits = {
        "maxHeaderBytes": 1024,
        "maxChunkBytes": 256,
        "maxInputBytes": 4096,
        "maxOutputBytes": 4096,
        "maxWireDurationMillis": 500,
    }
    worker_config_path = worker_dir / "config.json"
    _write_private_json(
        worker_config_path,
        {
            "version": "external-validation-worker-config.v1",
            "core": {
                "baseUrl": inputs.core_base_url,
                "maximumResponseBytes": 4096,
                "requestTimeoutMillis": 500,
            },
            "worker": {"instanceId": str(uuid.uuid4())},
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
                "uds": _uds(lanes.inspector_socket_path),
                "privateOutputRoot": os.fspath(worker_output),
                "protocolLimits": protocol_limits,
                "workerLimits": {
                    "heartbeatIntervalMillis": 10,
                    "maxAuthorityWaitMillis": 500,
                },
                "pinnedProfile": {
                    "parserBuildDigest": _marker_hex("parser-build", lanes.measurement_key_id),
                    "grammarDigest": external_geotiff_profile_digest_v1(),
                },
            },
            "measurement": {
                "uds": _uds(lanes.measurement_socket_path),
                "protocolLimits": protocol_limits,
                "heartbeatIntervalMillis": 10,
                "manifest": {
                    "path": lanes.measurement_manifest_path,
                    "expectedSha256": "sha256:"
                    + hashlib.sha256(measurement_manifest_raw).hexdigest(),
                    "expectedBodyDigest": measurement_manifest.canonical_body_digest(),
                    "revocationPath": lanes.measurement_revocation_path,
                    "expectedRevocationSha256": "sha256:"
                    + hashlib.sha256(measurement_revocation_raw).hexdigest(),
                    "trustedPublicKeys": {lanes.measurement_key_id: lanes.measurement_public_b64},
                },
            },
        },
    )

    validation = _self_verify_step3b(out, staging_root=staging_root)
    produced = [
        registry_path,
        operator_dir / authority_pem_name,
        snapshot_path,
        provider_path,
        workflow_path,
        catalog_path,
        secrets_dir / "dashboard-session.secret",
        secrets_dir / "oidc-client.secret",
        signing_dir / "keys.json",
        signing_dir / f"{inputs.core_signing_key_id}.public.pem",
        signing_dir / f"{inputs.core_signing_key_id}.private.pem",
        worker_config_path,
        worker_dir / "core.token",
        principal_tokens_path,
    ]
    receipt: dict[str, Any] = {
        "version": "step3b-issuance-receipt.v1",
        "scope": "test-deployment-only",
        "organizationId": inputs.organization_id,
        "authorityKeyId": inputs.authority_key_id,
        "authorityPublicKeySha256": "sha256:" + hashlib.sha256(authority_public_raw).hexdigest(),
        "coreSigningKeyId": inputs.core_signing_key_id,
        "coreSigningPublicKeySha256": "sha256:" + hashlib.sha256(core_public_raw).hexdigest(),
        "catalogRecordDigest": catalog_record.digest,
        "artifactHashes": {path.name: _sha256_file(path) for path in produced},
        "observedInputs": {
            "organizationId": inputs.organization_id,
            "catalogAdministrationActorId": inputs.catalog_admin_actor_id,
            "coreBaseUrl": inputs.core_base_url,
            "workerPrincipalId": inputs.worker_principal_id,
            "workerInstanceId": json.loads(worker_config_path.read_text())["worker"]["instanceId"],
            "inspectorSocketPath": lanes.inspector_socket_path,
            "measurementSocketPath": lanes.measurement_socket_path,
            "authorityJournalPath": FIXED_AUTHORITY_JOURNAL_PATH,
            "snapshotValidity": {"issuedAt": issued_at, "validUntil": valid_until},
            "authorityKeyValidity": {"notBefore": key_not_before, "notAfter": key_not_after},
        },
        "syntheticMarkers": "catalog policy algorithm/config/resource-envelope digests and "
        "the worker parser-build digest are test-deployment markers, not release evidence",
        "workflowVerifyMethod": "workflow.json carries the fixed durable data journal path, "
        "whose parents cannot exist in a checkout; acceptance was proven on a scratch copy "
        "differing only in authorityJournalPath, plus an exact fixed-path value assertion",
        "validation": validation,
    }
    receipt_path = out / "step3b-receipt.json"
    _write_private_json(receipt_path, receipt)
    return receipt


def _self_verify_step3b(out: Path, *, staging_root: Path) -> dict[str, str]:
    from ksi_core.composition.production_config import _parse_principal_tokens
    from ksi_core.external_authority_provider import load_external_authority_provider
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config
    from ksi_core.signing_keys import load_signing_keys
    from ksi_processing_controller.external_validation_worker_config import (
        load_external_validation_worker_config,
        load_pinned_measurement_manifest,
        read_external_validation_core_token,
    )

    operator_dir = out / "core" / "operator"
    provider = load_external_authority_provider(
        operator_dir / "provider.json", clock=lambda: datetime.now(UTC)
    )
    if provider.status()["status"] != "CONFIG_VALIDATED":
        raise IssuanceError("issued authority provider is not configuration-validated")

    produced_workflow = json.loads((operator_dir / "workflow.json").read_text(encoding="utf-8"))
    if set(produced_workflow) != {"version", "authorityJournalPath", "catalogPath"}:
        raise IssuanceError("issued workflow.json has inexact keys")
    if produced_workflow["authorityJournalPath"] != FIXED_AUTHORITY_JOURNAL_PATH:
        raise IssuanceError("issued workflow.json must use the fixed authority journal path")
    scratch = staging_root / "workflow-verify-copy.json"
    scratch_journal = staging_root / "authority-verify.jsonl"
    _write_private_json(
        scratch,
        {**produced_workflow, "authorityJournalPath": os.fspath(scratch_journal)},
    )
    try:
        workflow = load_external_result_workflow_config(
            scratch,
            participants=provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )
    finally:
        scratch.unlink(missing_ok=True)
    if not callable(workflow.build_mapping):
        raise IssuanceError("issued workflow did not assemble")

    load_signing_keys(operator_dir / "signing")

    worker_config = load_external_validation_worker_config(out / "worker" / "config.json")
    worker_token = read_external_validation_core_token(out / "worker" / "core.token")
    load_pinned_measurement_manifest(worker_config.measurement)

    rows = _parse_principal_tokens(
        (out / "core" / "principal-tokens.json").read_text(encoding="utf-8")
    )
    if (
        len(rows) != 1
        or rows[0].token_sha256 != hashlib.sha256(worker_token.encode("ascii")).hexdigest()
    ):
        raise IssuanceError("issued principal tokens do not match the worker bearer token")
    return {
        "provider": "ACCEPTED",
        "workflow": "ACCEPTED",
        "signingKeys": "ACCEPTED",
        "worker": "ACCEPTED",
        "principalTokens": "ACCEPTED",
    }


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
    parser.add_argument("--organization-id", default="org-a")
    parser.add_argument("--authority-key-id", default="step3b-authority-20261004")
    parser.add_argument("--core-signing-key-id", default="step3b-core-20261004")
    parser.add_argument("--core-base-url", default="https://core.example")
    parser.add_argument("--worker-principal-id", default="external-validation-worker")
    parser.add_argument("--catalog-administration-actor-id", default="catalog-admin")
    parser.add_argument(
        "--extend-existing",
        action="store_true",
        help="add Step-3b records to a directory that already holds Step-3a artifacts",
    )
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
    inputs3b = Step3bInputs(
        organization_id=args.organization_id,
        authority_key_id=args.authority_key_id,
        core_signing_key_id=args.core_signing_key_id,
        core_base_url=args.core_base_url,
        worker_principal_id=args.worker_principal_id,
        catalog_admin_actor_id=args.catalog_administration_actor_id,
    )
    if not inputs3b.organization_id or inputs3b.organization_id != inputs3b.organization_id.strip():
        raise IssuanceError("organization-id must be a non-blank identifier")

    if args.extend_existing:
        lanes_material = _lane_material_from_existing(out)
        staging_root = out / "staging"
        if not staging_root.is_dir():
            raise IssuanceError("--extend-existing needs the Step-3a staging directory")
        receipt3b = _issue_step3b(
            out=out, lanes=lanes_material, inputs=inputs3b, staging_root=staging_root
        )
        print(json.dumps({"out": os.fspath(out), "validation": receipt3b["validation"]}, indent=2))
        return 0

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
    lane_public: dict[str, str] = {}
    for label, lane in lanes.items():
        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes_raw()
        public_b64 = base64.b64encode(public_raw).decode("ascii")
        _write_private_file(keys_dir / f"{lane.key_id}.private", private_key.private_bytes_raw())
        lane_public[label] = public_b64
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

    if inputs3b.authority_key_id in {
        lanes["inspector"].key_id,
        lanes["measurement"].key_id,
    }:
        raise IssuanceError("authority key ID must differ from lane key IDs")

    lanes_material = LaneMaterial(
        launcher_uid=shared.launcher_uid,
        launcher_gid=shared.launcher_gid,
        worker_uid=shared.worker_uid,
        inspector_socket_path=lanes["inspector"].listener_socket_path,
        measurement_socket_path=lanes["measurement"].listener_socket_path,
        measurement_key_id=lanes["measurement"].key_id,
        measurement_public_b64=lane_public["measurement"],
        measurement_manifest_path=os.fspath(out / "measurement" / "manifest.json"),
        measurement_revocation_path=os.fspath(out / "measurement" / "revocations.json"),
    )
    receipt3b = _issue_step3b(
        out=out, lanes=lanes_material, inputs=inputs3b, staging_root=staging_root
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
    print(
        json.dumps(
            {"out": os.fspath(out), "validation": validation, "step3b": receipt3b["validation"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IssuanceError as exc:
        print(f"issuance refused: {exc}", flush=True)
        raise SystemExit(2) from exc
