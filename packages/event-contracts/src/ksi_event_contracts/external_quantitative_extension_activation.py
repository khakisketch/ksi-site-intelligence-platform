"""Signed, purpose-separated authority for quantitative extension lanes.

This module is strictly additive. It does not modify, reinterpret, or extend
the frozen V1/V2 contracts, the ``AnalysisActivationV1`` model, or its
``ksi.analysis-activation.v1`` signing domain.

Validity versus authority, read carefully:

- These models establish contract *validity* only: closed shapes, UTC
  timestamps, exact digest bindings, and a detached canonical Ed25519
  signature. A sealed record is *evidence*, never permission.
- The ``purpose`` field domain-separates the two quantitative extension lanes:
  ``MASKED_ANALYSIS_V3`` (P2 masked execution) and ``DELTA_PUBLICATION_V1``
  (separated delta output). A signed ``AnalysisActivationV1`` record — which
  carries no purpose — is never sufficient for either new purpose: the loader
  in :mod:`ksi_core.domains.external.quantity.external_quantitative_extension_activation`
  validates this model only, so a V2 activation file fails closed as a shape
  error before any signature or binding check.
- The signing domain ``ksi.quantitative-extension-activation.v1`` is distinct
  from ``ksi.analysis-activation.v1``. A signature minted for one domain never
  verifies under the other, so cross-purpose signature replay fails closed.
- No model here grants execution admission, publication currency, revocation
  state, read rights, or scope/egress approval. Core checks currentness,
  revocation, scope, and AI-egress separately before any use.
"""

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

#: Explicit signing domain for the new purpose-separated activation.
#: Deliberately distinct from ``ksi.analysis-activation.v1`` so that a
#: signature minted for the old V2 activation (or for the other purpose)
#: cannot verify here.
_SIGNING_DOMAIN = "ksi.quantitative-extension-activation.v1"

#: The only purposes this activation may authorize. No other value — and no
#: missing purpose, as in the old V2 activation — is accepted.
QuantitativeExtensionPurpose = Literal["MASKED_ANALYSIS_V3", "DELTA_PUBLICATION_V1"]

MASKED_ANALYSIS_PURPOSE: QuantitativeExtensionPurpose = "MASKED_ANALYSIS_V3"
DELTA_PUBLICATION_PURPOSE: QuantitativeExtensionPurpose = "DELTA_PUBLICATION_V1"


class QuantitativeExtensionActivationV1(_CamelModel):
    """Signed activation binding one exact organization, purpose, and graph."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    version: Literal[1] = 1
    activation_id: _Text
    organization_id: _Text
    purpose: QuantitativeExtensionPurpose
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
    def _validity_interval_is_positive(self) -> QuantitativeExtensionActivationV1:
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


__all__ = [
    "DELTA_PUBLICATION_PURPOSE",
    "MASKED_ANALYSIS_PURPOSE",
    "QuantitativeExtensionActivationV1",
    "QuantitativeExtensionPurpose",
]
