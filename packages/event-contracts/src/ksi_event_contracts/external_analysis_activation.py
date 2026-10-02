"""Signed, time-bounded authority for one exact Core Analysis execution graph."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_SIGNING_DOMAIN = "ksi.analysis-activation.v1"


class AnalysisActivationV1(_CamelModel):
    """Signed activation binding the exact organization, policy, runtime and worker."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    version: Literal[1] = 1
    activation_id: _Text
    organization_id: _Text
    policy_digest: Digest
    runtime_digest: Digest
    resource_envelope_digest: Digest
    worker_principal_id: _Text
    issued_at: datetime
    valid_until: datetime
    key_id: _Text
    signature: str = Field(min_length=88, max_length=88)

    @field_validator("issued_at", "valid_until")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("activation timestamps must be UTC")
        return value

    @field_validator("signature")
    @classmethod
    def _signature_is_canonical_ed25519_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("activation signature must be canonical base64") from exc
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("activation signature must encode 64 Ed25519 bytes")
        return value

    @model_validator(mode="after")
    def _validity_interval_is_positive(self) -> AnalysisActivationV1:
        if self.valid_until <= self.issued_at:
            raise ValueError("activation validUntil must be after issuedAt")
        return self

    def canonical_payload(self) -> dict[str, object]:
        """Return all signed fields except the detached signature."""
        return self.model_dump(by_alias=True, mode="json", exclude={"signature"})

    def signing_bytes(self) -> bytes:
        """Serialize a domain-tagged canonical payload for Ed25519 verification."""
        return canonical_json_bytes(
            {"domain": _SIGNING_DOMAIN, "payload": self.canonical_payload()}
        )

    def is_current_at(self, now: datetime) -> bool:
        """Check the half-open signed validity window; this does not verify a signature."""
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("activation currentness requires a UTC-aware time")
        return self.issued_at <= now < self.valid_until

