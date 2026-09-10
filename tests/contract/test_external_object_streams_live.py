"""Opt-in real S3 interoperability for the bounded external object transport.

Uses only the explicitly configured synthetic local object-store fixture. This
is storage interoperability, not contained measurement or deployment acceptance.
"""

import hashlib
import io
import time
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import ExternalArtifactInputV1
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedBytesReader,
    ProtocolDeadline,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportPolicyV1,
    SealedObjectByteSourceV1,
    TrustedObjectEndpointV1,
)
from test_evidence_s3_live import _ENDPOINT, _KEY, _SECRET, s3_client, storage  # noqa: F401

pytestmark = pytest.mark.skipif(
    not (_ENDPOINT and _KEY and _SECRET),
    reason="Explicit synthetic S3 fixture absent; real stream interoperability NOT_VERIFIED",
)


def test_bounded_transport_round_trips_real_digest_signed_put_and_get(storage: Any) -> None:  # noqa: F811
    payload = b"II synthetic opaque external TIFF bytes " * 2048
    artifact = ExternalArtifactInputV1(
        entry_id="synthetic-ortho",
        kind=ProcessingArtifactKind.ORTHO,
        observed_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        observed_size_bytes=len(payload),
        content_type="image/tiff",
    )
    policy = ExternalObjectTransportPolicyV1(
        endpoints=(TrustedObjectEndpointV1(_ENDPOINT, ("127.0.0.1",)),),
        max_header_bytes=32768,
        max_object_bytes=len(payload),
        max_chunk_bytes=1024,
    )
    key = "synthetic-external-streams/" + uuid4().hex + ".tif"
    try:
        signed = storage.presigned_put_bound_digest(
            key,
            content_type=artifact.content_type,
            content_digest=artifact.observed_sha256,
            ttl=timedelta(minutes=1),
        )
        put_capability = ExternalObjectCapabilityV1(
            artifact, signed.upload_url, signed.required_headers
        )
        source = DeadlineBoundedBytesReader(io.BytesIO(payload))
        try:
            receipt = ExternalObjectHttpByteSource(
                (put_capability,), policy=policy
            ).put_bound_bytes(
                put_capability,
                SealedObjectByteSourceV1(artifact, source),
                deadline=ProtocolDeadline(5000, time.monotonic),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=10,
            )
        finally:
            source.close()
        assert receipt.observed_sha256 == artifact.observed_sha256
        assert receipt.observed_size_bytes == len(payload)
        get_capability = ExternalObjectCapabilityV1(
            artifact, storage.presigned_get(key, ttl=timedelta(minutes=1)), {}
        )
        deadline = ProtocolDeadline(5000, time.monotonic)
        reader = ExternalObjectHttpByteSource((get_capability,), policy=policy).open_bound_bytes(
            artifact, deadline=deadline, wait_is_current=lambda: True, heartbeat_interval_millis=10
        )
        received = bytearray()
        try:
            while chunk := reader.read_chunk(
                777, deadline=deadline, wait_is_current=lambda: True, heartbeat_interval_millis=10
            ):
                received.extend(chunk)
        finally:
            reader.close()
        assert bytes(received) == payload
    finally:
        storage.delete(key)
