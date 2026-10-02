"""Signed Analysis activation is an explicit, time-bounded Core authority."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from ksi_core.domains.external.quantity.analysis_activation_authority import (
    load_analysis_activation,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.identity.auth import Principal, PrincipalKind
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2

_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
_KEY_ID = "analysis-activation-key-1"
_SIGNATURE_ROLE = "ANALYSIS_ACTIVATION_VERIFY"


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _policy() -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id="activation-policy",
        version=2,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("profile"),
        algorithm_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def _runtime() -> AnalysisRuntimeIdentityV2:
    return AnalysisRuntimeIdentityV2(
        worker_executable_digest=_digest("worker-executable"),
        worker_build_digest=_digest("worker-build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("runtime-image"),
        dependency_lock_digest=_digest("dependency-lock"),
    )


def _resource_envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1000,
        max_streamed_bytes=2000,
        max_tiff_directories=10,
        max_tiff_entries=100,
        max_pixels=10000,
        max_bands=1,
        max_blocks=100,
        max_decompressed_bytes=40000,
        max_sample_bytes=1000,
        max_geometry_vertices=100,
        max_cpu_seconds=10.0,
        max_memory_bytes=100000,
        max_workspace_bytes=100000,
        max_output_bytes=10000,
        max_tenant_concurrency=1,
        max_queue_depth=10,
        max_deadline_seconds=600.0,
        lease_duration_seconds=30.0,
        max_retry_attempts=2,
    ).sealed()


def _worker() -> Principal:
    return Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )


class ActivationBindings(TypedDict):
    organization_id: str
    policy: AnalysisPolicyV2
    runtime: AnalysisRuntimeIdentityV2
    resource_envelope: ResourceEnvelopeV1
    worker_principal: Principal


def _bindings() -> ActivationBindings:
    return {
        "organization_id": "org-a",
        "policy": _policy(),
        "runtime": _runtime(),
        "resource_envelope": _resource_envelope(),
        "worker_principal": _worker(),
    }


def _write_activation(
    root: Path,
    *,
    bindings: ActivationBindings | None = None,
    activation_fields: dict[str, object] | None = None,
    key_role: str = _SIGNATURE_ROLE,
) -> tuple[Path, Path, AnalysisActivationV1]:
    supplied = bindings or _bindings()
    policy = supplied["policy"]
    runtime = supplied["runtime"]
    envelope = supplied["resource_envelope"]
    assert isinstance(policy, AnalysisPolicyV2)
    assert isinstance(runtime, AnalysisRuntimeIdentityV2)
    assert isinstance(envelope, ResourceEnvelopeV1)
    runtime_payload = {
        "workerExecutableDigest": runtime.worker_executable_digest,
        "workerBuildDigest": runtime.worker_build_digest,
        "runtimeImageVersion": runtime.runtime_image_version,
        "runtimeImageOciDigest": runtime.runtime_image_oci_digest,
        "dependencyLockDigest": runtime.dependency_lock_digest,
    }
    runtime_digest = "sha256:" + hashlib.sha256(
        canonical_json_bytes(runtime_payload)
    ).hexdigest()
    unsigned: dict[str, object] = {
        "version": 1,
        "activationId": "activation-test-1",
        "organizationId": supplied["organization_id"],
        "policyDigest": policy.canonical_digest(),
        "runtimeDigest": runtime_digest,
        "resourceEnvelopeDigest": envelope.canonical_digest(),
        "workerPrincipalId": supplied["worker_principal"].principal_id,
        "issuedAt": _NOW.isoformat().replace("+00:00", "Z"),
        "validUntil": (_NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "keyId": _KEY_ID,
    }
    if activation_fields:
        unsigned.update(activation_fields)
    signing_model = AnalysisActivationV1.model_validate(
        {**unsigned, "signature": base64.b64encode(b"x" * 64).decode("ascii")}
    )
    private_key = Ed25519PrivateKey.generate()
    signature = base64.b64encode(private_key.sign(signing_model.signing_bytes())).decode("ascii")
    activation = AnalysisActivationV1.model_validate({**unsigned, "signature": signature})

    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    activation_path = root / "analysis-activation.json"
    activation_path.write_text(
        json.dumps(activation.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )
    activation_path.chmod(0o600)
    registry_path = root / "verification-keys.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": "analysis-activation-key-registry.v1",
                "keys": [
                    {
                        "keyId": _KEY_ID,
                        "role": key_role,
                        "algorithm": "Ed25519",
                        "status": "ACTIVE",
                        "publicKeyFile": "analysis-activation-key-1.public.pem",
                        "notBefore": "2026-09-01T00:00:00Z",
                        "notAfter": "2027-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry_path.chmod(0o600)
    public_path = root / "analysis-activation-key-1.public.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o644)
    return activation_path, registry_path, activation


def _activation() -> AnalysisActivationV1:
    return AnalysisActivationV1(
        version=1,
        activation_id="activation-test-1",
        organization_id="org-a",
        policy_digest="sha256:" + "a" * 64,
        runtime_digest="sha256:" + "b" * 64,
        resource_envelope_digest="sha256:" + "c" * 64,
        worker_principal_id="analysis-worker-a",
        issued_at=datetime(2026, 9, 29, tzinfo=UTC),
        valid_until=datetime(2026, 9, 30, tzinfo=UTC),
        key_id="analysis-activation-key-1",
        signature=base64.b64encode(b"s" * 64).decode("ascii"),
    )


def test_activation_signing_bytes_are_domain_separated_and_time_window_is_half_open() -> None:
    activation = _activation()
    payload = {
        "activationId": "activation-test-1",
        "issuedAt": "2026-09-29T00:00:00Z",
        "keyId": "analysis-activation-key-1",
        "organizationId": "org-a",
        "policyDigest": "sha256:" + "a" * 64,
        "resourceEnvelopeDigest": "sha256:" + "c" * 64,
        "runtimeDigest": "sha256:" + "b" * 64,
        "validUntil": "2026-09-30T00:00:00Z",
        "version": 1,
        "workerPrincipalId": "analysis-worker-a",
    }

    assert activation.signing_bytes() == canonical_json_bytes(
        {"domain": "ksi.analysis-activation.v1", "payload": payload}
    )
    assert activation.is_current_at(datetime(2026, 9, 29, tzinfo=UTC))
    assert activation.is_current_at(datetime(2026, 9, 29, 23, 59, tzinfo=UTC))
    assert not activation.is_current_at(datetime(2026, 9, 30, tzinfo=UTC))
    assert not activation.is_current_at(datetime(2026, 9, 28, 23, 59, tzinfo=UTC))


def test_loader_verifies_signed_activation_against_exact_runtime_graph(tmp_path: Path) -> None:
    bindings = _bindings()
    activation_path, registry_path, activation = _write_activation(tmp_path, bindings=bindings)

    loaded = load_analysis_activation(
        activation_path,
        registry_path,
        organization_id=bindings["organization_id"],
        policy=bindings["policy"],
        runtime=bindings["runtime"],
        resource_envelope=bindings["resource_envelope"],
        worker_principal=bindings["worker_principal"],
        now=_NOW,
    )

    assert loaded == activation
    assert loaded.is_current_at(_NOW)
    assert loaded.runtime_digest == (
        "sha256:5e176f8dfc8a0d596bfbcbbdb2797f651b2c3fd6ef8d5b604c0d3a72c9eced16"
    )
    schema = json.loads(
        Path("contracts/schemas/external-analysis-activation.v1.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(loaded.model_dump(by_alias=True, mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("organizationId", "org-b"),
        ("policyDigest", _digest("other-policy")),
        ("runtimeDigest", _digest("other-runtime")),
        ("resourceEnvelopeDigest", _digest("other-envelope")),
        ("workerPrincipalId", "other-analysis-worker"),
    ],
)
def test_loader_rejects_validly_signed_activation_with_substituted_binding(
    tmp_path: Path, field: str, value: str
) -> None:
    bindings = _bindings()
    activation_path, registry_path, _ = _write_activation(
        tmp_path, bindings=bindings, activation_fields={field: value}
    )

    with pytest.raises(ValueError):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )


def test_loader_rejects_generic_processing_worker_and_wrong_key_role(tmp_path: Path) -> None:
    bindings = _bindings()
    processing_worker = Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    activation_path, registry_path, _ = _write_activation(
        tmp_path, bindings=bindings, key_role="EXTERNAL_AUTHORITY_VERIFY"
    )

    with pytest.raises(ValueError):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=processing_worker,
            now=_NOW,
        )
    with pytest.raises(ValueError):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )


def test_loader_rejects_expired_activation_but_retains_signed_record(tmp_path: Path) -> None:
    bindings = _bindings()
    activation_path, registry_path, activation = _write_activation(tmp_path, bindings=bindings)
    assert activation.activation_id == "activation-test-1"

    with pytest.raises(ValueError, match="not current"):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW + timedelta(hours=1),
        )


def test_loader_can_verify_expired_activation_for_read_only_history_replay(
    tmp_path: Path,
) -> None:
    bindings = _bindings()
    activation_path, registry_path, activation = _write_activation(tmp_path, bindings=bindings)

    loaded = load_analysis_activation(
        activation_path,
        registry_path,
        organization_id=bindings["organization_id"],
        policy=bindings["policy"],
        runtime=bindings["runtime"],
        resource_envelope=bindings["resource_envelope"],
        worker_principal=bindings["worker_principal"],
        now=_NOW + timedelta(hours=1),
        allow_expired=True,
    )

    assert loaded == activation
    assert not loaded.is_current_at(_NOW + timedelta(hours=1))


def test_loader_rejects_future_activation(tmp_path: Path) -> None:
    bindings = _bindings()
    issued_at = _NOW + timedelta(minutes=1)
    activation_path, registry_path, _ = _write_activation(
        tmp_path,
        bindings=bindings,
        activation_fields={
            "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
            "validUntil": (issued_at + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
    )

    with pytest.raises(ValueError, match="not current"):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )


def test_loader_rejects_signature_tampering(tmp_path: Path) -> None:
    bindings = _bindings()
    activation_path, registry_path, activation = _write_activation(tmp_path, bindings=bindings)
    record = json.loads(activation_path.read_text())
    replacement = "A" if activation.signature[0] != "A" else "B"
    record["signature"] = replacement + activation.signature[1:]
    activation_path.write_text(json.dumps(record))

    with pytest.raises(ValueError, match="signature"):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )


def test_loader_rejects_duplicate_fields_and_unknown_registry_key_id(tmp_path: Path) -> None:
    bindings = _bindings()
    activation_path, registry_path, _ = _write_activation(tmp_path, bindings=bindings)
    registry = json.loads(registry_path.read_text())
    registry["keys"][0]["keyId"] = "different-key-id"
    registry_path.write_text(json.dumps(registry))

    with pytest.raises(ValueError, match="missing or ambiguous"):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )

    activation_path.write_text('{"version":1,"version":1}')
    with pytest.raises(ValueError, match="strict protected JSON"):
        load_analysis_activation(
            activation_path,
            registry_path,
            organization_id=bindings["organization_id"],
            policy=bindings["policy"],
            runtime=bindings["runtime"],
            resource_envelope=bindings["resource_envelope"],
            worker_principal=bindings["worker_principal"],
            now=_NOW,
        )
