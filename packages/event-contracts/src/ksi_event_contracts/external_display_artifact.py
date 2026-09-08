"""Immutable sanitized-display declaration and receipt contracts.

The public wire contains only an opaque display reference.  Storage keys and
URLs are deliberately excluded from both declaration and receipt payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StringConstraints, field_validator, model_validator

from ksi_event_contracts.external_artifact_validation import (
    Digest,
    _BoundedText,
    _digest,
    _FrozenExternalModel,
    _require_aware,
    _require_aware_datetime_wire_value,
)

_SanitizedDisplayRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=255,
        pattern=r"^sda-v1-[A-Za-z0-9][A-Za-z0-9_-]{0,247}$",
    ),
]


class SanitizedDisplayDeclarationV1(_FrozenExternalModel):
    """Worker declaration of an opaque derivative; no object key or URL is journaled."""

    contract_version: Literal["external-sanitized-display-artifact.v1"] = (
        "external-sanitized-display-artifact.v1"
    )
    record_type: Literal["SANITIZED_DISPLAY_DECLARATION"] = "SANITIZED_DISPLAY_DECLARATION"
    display_id: _BoundedText
    request_id: _BoundedText
    source_subject_digest: Digest
    source_report_digest: Digest
    policy_digest: Digest
    inspector_build_digest: Digest
    declared_derivative_sha256: Digest
    declared_derivative_size_bytes: StrictInt = Field(gt=0)
    declared_derivative_content_type: _BoundedText
    declaration_digest: Digest | None = None

    @model_validator(mode="after")
    def _digest_matches(self) -> SanitizedDisplayDeclarationV1:
        if (
            self.declaration_digest is not None
            and self.declaration_digest != self.canonical_digest()
        ):
            raise ValueError("declarationDigest does not match canonical display declaration")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"declaration_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> SanitizedDisplayDeclarationV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"declaration_digest": validated.canonical_digest()}, deep=True
        )


class SanitizedDisplayReceiptV1(_FrozenExternalModel):
    """Core-observed derivative receipt with an opaque display reference only."""

    contract_version: Literal["external-sanitized-display-artifact.v1"] = (
        "external-sanitized-display-artifact.v1"
    )
    record_type: Literal["SANITIZED_DISPLAY_RECEIPT"] = "SANITIZED_DISPLAY_RECEIPT"
    display_id: _BoundedText
    request_id: _BoundedText
    declaration_digest: Digest
    source_subject_digest: Digest
    source_report_digest: Digest
    policy_digest: Digest
    inspector_build_digest: Digest
    observed_derivative_sha256: Digest
    observed_derivative_size_bytes: StrictInt = Field(gt=0)
    observed_derivative_content_type: _BoundedText
    sanitized_display_ref: _SanitizedDisplayRef
    sealed_at: datetime
    receipt_digest: Digest | None = None

    @field_validator("sealed_at", mode="before")
    @classmethod
    def _sealed_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "sealedAt")

    @field_validator("sealed_at")
    @classmethod
    def _sealed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "sealedAt")

    @model_validator(mode="after")
    def _digest_matches(self) -> SanitizedDisplayReceiptV1:
        if self.receipt_digest is not None and self.receipt_digest != self.canonical_digest():
            raise ValueError("receiptDigest does not match canonical display receipt")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"receipt_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> SanitizedDisplayReceiptV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"receipt_digest": validated.canonical_digest()}, deep=True
        )


def sanitized_display_declaration_wire_dict(
    declaration: SanitizedDisplayDeclarationV1,
) -> dict[str, Any]:
    return declaration.sealed().model_dump(by_alias=True, mode="json", exclude_none=False)


def sanitized_display_receipt_wire_dict(receipt: SanitizedDisplayReceiptV1) -> dict[str, Any]:
    return receipt.sealed().model_dump(by_alias=True, mode="json", exclude_none=False)


__all__ = [
    "SanitizedDisplayDeclarationV1",
    "SanitizedDisplayReceiptV1",
    "sanitized_display_declaration_wire_dict",
    "sanitized_display_receipt_wire_dict",
]
