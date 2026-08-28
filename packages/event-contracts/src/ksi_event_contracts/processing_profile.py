"""Immutable reconstruction processing profiles (ADR-KSI-030, INV-050).

An issued ProcessingJob stores the profile identifier *and* this canonical
snapshot digest.  The identifier is useful to people; the digest is the
reproducibility anchor.  A profile is never edited in place: changing an
engine, OCI image, preprocessing policy, or output set requires a new id.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.processing_job import ExecutionLocus, LicenseBasis, ProcessingProvider

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ProcessingPreprocessingPolicy(_CamelModel):
    """All input mutations that can change a quantitative result.

    ``dynamic_object_masking`` is explicit instead of being inferred from a
    worker environment variable.  That prevents two jobs with the same
    profile digest from silently using different pixels.
    """

    dynamic_object_masking: bool
    policy_version: str = Field(min_length=1)


class ProcessingProfileV1(_CamelModel):
    """A complete, immutable recipe for one reproducible processing run."""

    processing_profile_id: str = Field(min_length=1)
    profile_version: str = Field(default="v1", min_length=1)
    provider: ProcessingProvider
    engine_version: str = Field(min_length=1)
    node_odm_version: str | None = Field(default=None, min_length=1)
    oci_image: str = Field(min_length=1)
    oci_image_digest: str = Field(pattern=_DIGEST_PATTERN)
    execution_locus: ExecutionLocus
    processing_params: dict[str, Any] = Field(default_factory=dict)
    preprocessing: ProcessingPreprocessingPolicy
    required_artifacts: tuple[str, ...] = Field(min_length=1)
    license_basis: LicenseBasis
    agpl_boundary: str = Field(min_length=1)
    profile_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _validate_declared_digest(self) -> ProcessingProfileV1:
        if self.profile_digest is not None and self.profile_digest != self.canonical_digest():
            raise ValueError("processingProfileDigest가 canonical profile snapshot과 다르다")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        """Wire-shaped profile content, deliberately excluding its own digest."""
        payload = self.model_dump(by_alias=True, mode="json", exclude={"profile_digest"})
        return payload

    def canonical_digest(self) -> str:
        canonical = canonical_json_bytes(self.canonical_payload())
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    def sealed(self) -> ProcessingProfileV1:
        """Return the same immutable content with its independently checkable digest."""
        return self.model_copy(
            update={"profile_digest": self.canonical_digest()},
            deep=True,
        )


def processing_profile_wire_dict(profile: ProcessingProfileV1) -> dict[str, Any]:
    """Serialize a sealed immutable snapshot for API and journal use."""
    return profile.sealed().model_dump(by_alias=True, mode="json", exclude_none=True)


__all__ = [
    "ProcessingPreprocessingPolicy",
    "ProcessingProfileV1",
    "processing_profile_wire_dict",
]
