"""Closed separate worker HTTP caps for the masked first-execution lane (P2, additive).

Additive only. This module names the exact server-issued DSM capabilities a
first-execution masked worker consumes for ONE live masked attempt. It is the
only worker input for the new first-execution job:

- Two ordered server-issued DSM capabilities (baseline then current) bound to
  the exact sealed source V2 identity embedded in the live masked attempt,
  never to client-supplied URLs. The mask itself travels the existing
  Core-bearer ``EXCLUSION_MASK`` byte window (``/inputs/EXCLUSION_MASK/bytes``)
  behind the same live masked fence; no Core bearer ever goes to object-storage
  origins.
- The exact masked/attempt binding (request, masked digest, source digest,
  attempt digest, worker instance, generation, expiries) so the worker can
  cross-check the DSM caps against its ``/input`` fetch before any download.

Discovery uses the Lead-owned pendings (``external_masked_api``):
``GET /v1/internal/mask-inspection-jobs/pending`` and
``GET /v1/internal/masked-calculations/pending``. No duplicate discovery
contract lives here.

No model here grants authority: Core rechecks lease liveness, source
currentness, policy/runtime currency, expiry, cancel/failure and scope before
issuing these caps and again after the presigning I/O; the worker rechecks the
same fence after every I/O before dispatch. The old two-input V2 worker
protocol is untouched and never widened here.

Software proof and limits: local generated tests prove the real software
handshake (Core HTTP lease/input/DSM-caps/mask-bytes plus pinned object
downloads plus native dispatch) over loopback servers. That proves the bytes
and protocol only: it claims no OS sandbox, no host provisioning, and no
deployment containment. The separately verified contained runtime remains
operator-owned; the direct native helper runs inside it only when explicitly
configured.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Opaque = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
_Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16384)]
_HeaderName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$",
    ),
]
_HeaderValue = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=8192)
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _require_opaque(value: str, name: str) -> str:
    lowered = value.lower()
    if (
        "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(f"{name} must be an opaque identifier, never a URL, path, or capability")
    return value


class _WorkerModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class MaskedWorkflowDsmCapabilityV1(_WorkerModel):
    """One short-lived server-issued DSM GET bound to the live masked attempt.

    The URL comes only from Core's presigned object storage (never a client
    URL, path, or Core-bearer fetch); the Core bearer is never sent to this
    origin. The worker must verify hash/size against the sealed source
    identity before any decode.
    """

    role: Literal["BASELINE_DSM", "CURRENT_DSM"]
    artifact_id: _Text
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    download_url: _Url
    required_headers: dict[_HeaderName, _HeaderValue] = Field(max_length=32)
    expires_at: datetime

    @field_validator("artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "artifactId")

    @field_validator("download_url")
    @classmethod
    def _capability_url_is_http(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("downloadUrl must be a credential-free HTTP(S) URL")
        return value

    @field_validator("expires_at")
    @classmethod
    def _expires_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class MaskedWorkflowDsmInputViewV1(_WorkerModel):
    """Exact server-issued DSM leg for one live masked attempt.

    The worker must cross-check this against its ``/input`` fetch (opaque
    baseline/current artifact/sha/size plus masked/source digests) and against
    its pinned lane seals (five-pin execution runtime, resource envelope,
    signed activation) before any object download; any mismatch fails closed.
    Capabilities never outlive the live masked lease. The digests are bound by
    Core from the fresh witness/admission and the live attempt authorization,
    never from caller hashes.
    """

    request_id: _Opaque
    masked_calculation_identity_digest: Digest
    source_calculation_identity_digest: Digest
    attempt_digest: Digest
    worker_instance_id: _Text
    lease_generation: StrictInt = Field(ge=1)
    lease_expires_at: datetime
    execution_runtime_digest: Digest
    resource_envelope_digest: Digest
    activation_digest: Digest
    capabilities: tuple[MaskedWorkflowDsmCapabilityV1, MaskedWorkflowDsmCapabilityV1]

    @field_validator("request_id")
    @classmethod
    def _request_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "requestId")

    @field_validator("lease_expires_at")
    @classmethod
    def _expiry_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _binds_ordered_dsm_and_fence(self) -> Self:
        baseline, current = self.capabilities
        if (baseline.role, current.role) != ("BASELINE_DSM", "CURRENT_DSM"):
            raise ValueError("DSM capabilities must be ordered baseline then current")
        if any(item.expires_at > self.lease_expires_at for item in self.capabilities):
            raise ValueError("DSM capability outlives its masked lease")
        return self


__all__ = [
    "MaskedWorkflowDsmCapabilityV1",
    "MaskedWorkflowDsmInputViewV1",
]
