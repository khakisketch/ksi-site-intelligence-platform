"""Private immutable-object port and strict SDK metadata/TTL checks; no storage I/O here."""

from __future__ import annotations

import base64
import binascii
import math
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol

from ksi_event_contracts._spatial_data import require_utc
from ksi_event_contracts.spatial_data import SpatialDataAttemptV1, SpatialDataSourceV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
)

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
    _immutable_version,
    _positive_size,
)


class SpatialDataStoragePort(Protocol):
    """Private exact owned versions/capabilities; never an EvidenceStorage get_bytes fallback."""

    def observe_owned_output(
        self, target: SpatialDataOutputTarget
    ) -> SpatialDataObjectObservation: ...

    def open_version(
        self, observation: SpatialDataObjectObservation, *, chunk_bytes: int, deadline: datetime
    ) -> AbstractContextManager[Iterator[bytes]]: ...

    def issue_source_get(
        self, source: SpatialDataSourceV1, attempt: SpatialDataAttemptV1, *, expires_at: datetime
    ) -> SpatialDataSourceCapabilityV1: ...

    def issue_output_put(
        self,
        target: SpatialDataOutputTarget,
        *,
        sha256: str,
        size_bytes: int,
        content_type: str,
        expires_at: datetime,
    ) -> SpatialDataUploadCapabilityV1: ...

    def list_owned_versions(
        self, target: SpatialDataOutputTarget, *, limit: int
    ) -> tuple[SpatialDataObjectObservation, ...]: ...

    def delete_owned_version(self, target: SpatialDataOutputTarget, version_id: str) -> None: ...


def versioned_head_identity(
    response: Mapping[str, Any], *, expected_version: str | None
) -> tuple[str, int, str]:
    """Exact byte identity only; does not infer source/output media type or owned cleanup rights."""
    try:
        if response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 200:
            raise ValueError("not an exact successful SDK object response")
        if response.get("ChecksumType") != "FULL_OBJECT":
            raise ValueError("full-object checksum type is mandatory")
        encoded = response["ChecksumSHA256"]
        if type(encoded) is not str or len(encoded) != 44:
            raise ValueError("bounded SHA-256 base64 is mandatory")
        checksum = base64.b64decode(encoded, validate=True)
        if len(checksum) != 32 or base64.b64encode(checksum).decode("ascii") != encoded:
            raise ValueError("invalid full SHA-256 checksum representation")
        version = _immutable_version(response["VersionId"])
        size = _positive_size(response["ContentLength"])
        if expected_version is not None and version != expected_version:
            raise ValueError("SDK substituted pinned object version")
        return version, size, "sha256:" + checksum.hex()
    except (KeyError, AttributeError, TypeError, ValueError, binascii.Error) as exc:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503) from exc


def observation_from_head(
    target: SpatialDataOutputTarget, response: Mapping[str, Any], *, expected_version: str | None
) -> SpatialDataObjectObservation:
    """Observed owned output adds exact image/tiff to the checked full-object byte identity."""
    version, size, checksum = versioned_head_identity(response, expected_version=expected_version)
    try:
        return SpatialDataObjectObservation(
            target.object_key, version, size, checksum, response["ContentType"]
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503) from exc


def capability_ttl_seconds(*, expires_at: datetime, now: datetime, upper_bound: datetime) -> int:
    """Floor the SDK integer TTL, never round up or extend a previously reserved write target."""
    require_utc(expires_at)
    require_utc(now)
    require_utc(upper_bound)
    if not now < expires_at <= upper_bound:
        raise SpatialDataDomainError("LEASE_EXPIRED", 409)
    seconds = math.floor((expires_at - now).total_seconds())
    if seconds < 1:
        raise SpatialDataDomainError("LEASE_EXPIRED", 409)
    return seconds
