"""Concrete inspector trust-root verifier conformance."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestSignatureV1,
    SignatureVerificationVerdict,
)
from ksi_processing_controller.external_inspector_catalog import (
    Ed25519InspectorManifestVerifier,
    InspectorTrustRootV1,
)


def test_ed25519_inspector_verifier_accepts_only_the_exact_key_payload_and_digest() -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    payload = b"canonical-body"
    import base64
    import hashlib

    signature = InspectorExecutionManifestSignatureV1(
        algorithm="Ed25519",
        key_id="catalog-key-1",
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
        signature=base64.b64encode(private.sign(payload)).decode("ascii"),
    )
    verifier = Ed25519InspectorManifestVerifier(InspectorTrustRootV1({"catalog-key-1": public}))

    assert verifier.verify(payload, signature) is SignatureVerificationVerdict.VALID
    assert verifier.verify(payload + b"x", signature) is SignatureVerificationVerdict.INVALID
