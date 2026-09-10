"""Measurement admission resolves exact fixed catalog authority on every check."""

import time
from pathlib import Path
from typing import Any

import pytest
from ksi_event_contracts.inspector_execution_manifest import SignatureVerificationVerdict
from ksi_processing_controller.external_inspector_launcher import CatalogStartupStatusV1
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_admission import admit_measurement_request
from test_external_measurement_protocol import limits, measurement_manifest_request


class Catalog:
    def __init__(self, manifest: Any) -> None:
        self.manifest = manifest
        self.revoked = False
        self.lookups: list[dict[str, Any]] = []

    def startup_status(self) -> CatalogStartupStatusV1:
        return CatalogStartupStatusV1(
            readable=True, trust_root_configured=True, catalog_identity_verified=True
        )

    def resolve_manifest_exact(self, **selection: Any) -> Any:
        self.lookups.append(selection)
        return self.manifest

    def is_revoked(self, manifest: Any) -> bool:
        return self.revoked


class Verifier:
    def verify(self, payload: bytes, signature: Any) -> SignatureVerificationVerdict:
        return SignatureVerificationVerdict.VALID


def test_catalog_admission_resolves_manifest_identity_and_clamps_limits() -> None:
    manifest, request = measurement_manifest_request()
    catalog = Catalog(manifest)
    admitted = admit_measurement_request(
        request,
        catalog=catalog,
        verifier=Verifier(),
        limits=limits(),
        deadline=ProtocolDeadline(1000, time.monotonic),
    )
    assert catalog.lookups == [
        {
            "execution_manifest_digest": request.execution_manifest_digest,
            "resource_envelope_digest": request.validation_policy.resource_envelope_digest,
        }
    ]
    assert admitted.manifest == manifest
    hard = manifest.body.hard_ceilings
    envelope = request.validation_policy.resource_envelope
    assert envelope is not None
    assert admitted.effective_limits.max_memory_bytes == min(
        hard.max_memory_bytes, envelope.max_memory_bytes
    )
    assert admitted.effective_limits.max_workspace_bytes == min(
        hard.max_tmpfs_bytes, envelope.max_workspace_bytes
    )
    assert admitted.effective_limits.max_wall_time_millis == min(
        hard.max_wall_time_millis,
        int(envelope.max_deadline_seconds * 1000),
        limits().max_wire_duration_millis,
    )
    catalog.revoked = True
    with pytest.raises(ProtocolViolation):
        admit_measurement_request(
            request,
            catalog=catalog,
            verifier=Verifier(),
            limits=limits(),
            deadline=ProtocolDeadline(1000, time.monotonic),
        )


@pytest.mark.parametrize("changed", ["unavailable", "wrong", "expired"])
def test_catalog_failure_or_changed_authority_never_returns_admission(changed: str) -> None:
    manifest, request = measurement_manifest_request()
    catalog = Catalog(manifest)
    if changed == "unavailable":
        catalog.manifest = None
    if changed == "wrong":
        other, _ = measurement_manifest_request()
        catalog.manifest = other.model_copy(
            update={
                "body": other.body.model_copy(update={"runtime_uid": other.body.runtime_uid + 1})
            }
        )
    clock = [0.0]
    deadline = ProtocolDeadline(1000, lambda: clock[0])
    if changed == "expired":
        clock[0] = 1.0
    with pytest.raises(ProtocolViolation):
        admit_measurement_request(
            request, catalog=catalog, verifier=Verifier(), limits=limits(), deadline=deadline
        )


def test_real_fixed_catalog_and_ed25519_verifier_admit_only_signed_measurement(
    tmp_path: Path,
) -> None:
    import base64
    import hashlib
    import json

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionManifestSignatureV1,
    )
    from ksi_processing_controller.external_inspector_catalog import (
        Ed25519InspectorManifestVerifier,
        FileInspectorCatalogConfigV1,
        FileInspectorManifestCatalog,
        InspectorTrustRootV1,
    )

    manifest, request = measurement_manifest_request()
    private = Ed25519PrivateKey.generate()
    manifest = manifest.model_copy(
        update={
            "signature": InspectorExecutionManifestSignatureV1(
                algorithm="Ed25519",
                key_id="synthetic-local-key",
                digest=manifest.canonical_body_digest(),
                signature=base64.b64encode(private.sign(manifest.canonical_body_bytes())).decode(),
            )
        }
    )
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(by_alias=True))
    path.chmod(0o600)
    revocation_path = tmp_path / "revocations.json"
    raw = json.dumps(
        {"version": "external-inspector-revocations.v1", "revokedManifestDigests": []}
    ).encode()
    revocation_path.write_bytes(raw)
    revocation_path.chmod(0o600)
    catalog = FileInspectorManifestCatalog(
        FileInspectorCatalogConfigV1(
            manifest_path=path,
            revocation_path=revocation_path,
            expected_revocation_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        )
    )
    verifier = Ed25519InspectorManifestVerifier(
        InspectorTrustRootV1({"synthetic-local-key": private.public_key().public_bytes_raw()})
    )
    assert (
        admit_measurement_request(
            request,
            catalog=catalog,
            verifier=verifier,
            limits=limits(),
            deadline=ProtocolDeadline(1000, time.monotonic),
        ).manifest
        == manifest
    )
    unknown_key = Ed25519InspectorManifestVerifier(
        InspectorTrustRootV1({"different-key": private.public_key().public_bytes_raw()})
    )
    with pytest.raises(ProtocolViolation):
        admit_measurement_request(
            request,
            catalog=catalog,
            verifier=unknown_key,
            limits=limits(),
            deadline=ProtocolDeadline(1000, time.monotonic),
        )
