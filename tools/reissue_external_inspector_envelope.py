#!/usr/bin/env python3
"""Re-issue the inspector execution manifest with a realistic resource envelope.

Deployment scope (step 4).  Keeps the signed manifest identity (same inspector
key/keyId and all image/profile digests) and raises only the pinned resource
envelope and the hard ceilings, so a real customer DSM can be inspected within a
finite but realistic budget.  The inspector private key must be the raw 32-byte
Ed25519 seed that signed the current manifest.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/event-contracts/src", "packages/domain/src"):
    sys.path.insert(0, str(REPO_ROOT / _p))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1  # noqa: E402
from ksi_event_contracts.inspector_execution_manifest import (  # noqa: E402
    InspectorExecutionHardCeilingsV1,
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
)

REALISTIC_ENVELOPE: dict[str, object] = {
    "max_input_bytes": 200_000_000,
    "max_streamed_bytes": 200_000_000,
    "max_tiff_directories": 32,
    "max_tiff_entries": 4096,
    "max_pixels": 60_000_000,
    "max_bands": 4,
    "max_blocks": 4096,
    "max_decompressed_bytes": 400_000_000,
    "max_sample_bytes": 400_000_000,
    "max_geometry_vertices": 8,
    "max_cpu_seconds": 120.0,
    "max_memory_bytes": 512_000_000,
    "max_workspace_bytes": 512_000_000,
    "max_output_bytes": 64_000_000,
    "max_tenant_concurrency": 1,
    "max_queue_depth": 1,
    "max_deadline_seconds": 300.0,
    "lease_duration_seconds": 600.0,
    "max_retry_attempts": 2,
}

REALISTIC_CEILINGS: dict[str, object] = {
    "max_input_bytes": 200_000_000,
    "max_memory_bytes": 512_000_000,
    "max_tmpfs_bytes": 512_000_000,
    "max_pids": 32,
    "cpu_period_micros": 100_000,
    "cpu_quota_micros": 100_000,
    "max_wall_time_millis": 300_000,
    "max_log_bytes": 4096,
    "max_output_bytes": 64_000_000,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-manifest", required=True)
    parser.add_argument("--private-key", default=None,
                        help="raw 32-byte Ed25519 seed; omit to generate a new key")
    parser.add_argument("--seed-out", default=None,
                        help="where to write a newly generated seed (0600)")
    parser.add_argument("--key-id", default=None,
                        help="signature key id (defaults to the current manifest's)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--envelope-json", default=None)
    args = parser.parse_args()

    if args.private_key is None:
        if not args.seed_out or not args.key_id:
            print("generating a new key requires --seed-out and --key-id", file=sys.stderr)
            return 2
        seed = os.urandom(32)
        seed_path = Path(args.seed_out)
        seed_path.write_bytes(seed)
        seed_path.chmod(0o600)
        signer = Ed25519PrivateKey.from_private_bytes(seed)
    else:
        seed = Path(args.private_key).read_bytes()
        if len(seed) != 32:
            print("private key must be a raw 32-byte Ed25519 seed", file=sys.stderr)
            return 2
        signer = Ed25519PrivateKey.from_private_bytes(seed)

    current = json.loads(Path(args.current_manifest).read_text())
    key_id = args.key_id or current["signature"]["keyId"]

    envelope_kwargs = (
        REALISTIC_ENVELOPE
        if args.envelope_json is None
        else json.loads(Path(args.envelope_json).read_text())
    )
    envelope = ResourceEnvelopeV1(**envelope_kwargs).sealed()
    ceilings = InspectorExecutionHardCeilingsV1(**REALISTIC_CEILINGS)

    body_document = dict(current["body"])
    body_document["resourceEnvelopeDigest"] = envelope.resource_envelope_digest
    body_document["hardCeilings"] = ceilings.model_dump(by_alias=True, mode="json")
    body = InspectorExecutionManifestBodyV1.model_validate(body_document)

    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id=key_id,
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(signer.sign(body.canonical_body_bytes())).decode("ascii"),
        ),
    )
    out_path = Path(args.out)
    payload = json.dumps(manifest.model_dump(by_alias=True, mode="json"), indent=1) + "\n"
    out_path.write_text(payload)
    out_path.chmod(0o600)
    raw_public = signer.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print(json.dumps({
        "keyId": key_id,
        "publicKeyBase64": base64.b64encode(raw_public).decode("ascii"),
        "manifestSha256": "sha256:" + hashlib.sha256(payload.encode()).hexdigest(),
        "bodyDigest": body.canonical_body_digest(),
        "resourceEnvelopeDigest": envelope.resource_envelope_digest,
        "maxInputBytes": envelope.max_input_bytes,
        "maxPixels": envelope.max_pixels,
        "maxDeadlineSeconds": envelope.max_deadline_seconds,
        "leaseDurationSeconds": envelope.lease_duration_seconds,
        "out": str(out_path),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
