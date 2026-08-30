"""Immutable Processing Resource Policy snapshots (Civil Pilot R1).

This policy is a Core-issued operational protection envelope, not a pricing,
accuracy, or customer entitlement statement.  An issued processing job records
the complete sealed policy snapshot and its digest so a later configuration
change cannot make a historical admission decision ambiguous.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ConfigDict, Field, model_validator

from ksi_event_contracts._base import _CamelModel

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_POLICY_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class ProcessingResourcePolicyV1(_CamelModel):
    """One immutable processing-admission envelope.

    The limits protect a single-customer Civil Pilot deployment from accidental
    or hostile resource exhaustion.  They intentionally do **not** express
    photogrammetry accuracy, a commercial price, or a promised service quota.
    A changed value requires a new ``resource_policy_id``; policy records are
    never edited in place.
    """

    # _CamelModel owns aliases/extra/finite-number defaults.  This contract is
    # a snapshot, so assignment must fail rather than leaving a cached digest
    # attached to changed content.
    model_config = ConfigDict(frozen=True)

    resource_policy_id: str = Field(
        min_length=1, max_length=128, pattern=_POLICY_IDENTIFIER_PATTERN
    )
    policy_version: str = Field(
        default="v1", min_length=1, max_length=128, pattern=_POLICY_IDENTIFIER_PATTERN
    )
    max_source_media_files: int = Field(ge=1)
    max_source_media_file_bytes: int = Field(ge=1)
    max_source_bundle_bytes: int = Field(ge=1)
    max_total_megapixels: float = Field(gt=0, allow_inf_nan=False)
    max_active_processing_jobs_per_organization: int = Field(ge=1)
    resource_policy_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _bundle_limit_cannot_be_smaller_than_one_file(self) -> ProcessingResourcePolicyV1:
        if self.max_source_bundle_bytes < self.max_source_media_file_bytes:
            raise ValueError("maxSourceBundleBytes는 maxSourceMediaFileBytes보다 작을 수 없다")
        if (
            self.resource_policy_digest is not None
            and self.resource_policy_digest != self.canonical_digest()
        ):
            raise ValueError("resourcePolicyDigest가 canonical resource policy snapshot과 다르다")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        """Wire-shaped policy content, deliberately excluding its own digest."""
        return self.model_dump(by_alias=True, mode="json", exclude={"resource_policy_digest"})

    def canonical_digest(self) -> str:
        canonical = canonical_json_bytes(self.canonical_payload())
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    def sealed(self) -> ProcessingResourcePolicyV1:
        return self.model_copy(
            update={"resource_policy_digest": self.canonical_digest()}, deep=True
        )


def processing_resource_policy_wire_dict(
    policy: ProcessingResourcePolicyV1,
) -> dict[str, Any]:
    """Serialize a sealed immutable snapshot for discovery and journal use."""
    return policy.sealed().model_dump(by_alias=True, mode="json", exclude_none=True)


__all__ = ["ProcessingResourcePolicyV1", "processing_resource_policy_wire_dict"]
