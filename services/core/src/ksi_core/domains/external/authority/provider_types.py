"""Private immutable authority-provider records and pure validation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.domains.external.ingress.external_validation_policy import PolicyAuthorityRecord
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
)

_CONFIG_VERSION = "external-authority-provider-config.v1"
_REGISTRY_VERSION = "external-authority-key-registry.v1"
_SNAPSHOT_VERSION = "external-authority-provider-snapshot.v1"
_SNAPSHOT_DOMAIN = "ksi.external-authority-provider-snapshot.v1"
_RECEIPT_NAME = "external-authority-provider-receipts.jsonl"
_MAX_FILE_BYTES = 1024 * 1024
_MAX_REGISTRY_KEYS = 128
_MAX_COLLECTION_RECORDS = 4_096
_MAX_ADMINISTRATION_ACTIONS = 4_096
_RECEIPT_KIND = "external-authority-provider-receipt"
_RECEIPT_VERSION = 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")
_SNAPSHOT_UNSIGNED_FIELDS = frozenset(
    {
        "version",
        "organizationId",
        "sequence",
        "previousSnapshotDigest",
        "issuedAt",
        "validUntil",
        "keyId",
        "catalogAuthorities",
        "policyAuthorities",
        "evidenceContexts",
        "quantitativeAdministration",
    }
)


class ExternalAuthorityProviderError(RuntimeError):
    """External authority input cannot be used safely."""


def _utc(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_RFC3339.fullmatch(value) is None:
        raise ValueError(f"{name} must be a UTC RFC3339 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{name} must be UTC-aware")
    return parsed


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty trimmed text")
    return value


def _exact_mapping(raw: object, fields: frozenset[str], *, name: str) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != fields or any(type(key) is not str for key in raw):
        raise ValueError(f"{name} has an invalid object shape")
    return cast(dict[str, object], raw)


def _no_constant(value: str) -> object:
    raise ValueError(f"JSON constant {value!r} is not permitted")


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class _VerifiedSnapshot:
    organization_id: str
    sequence: int
    digest: str
    issued_at: datetime
    valid_until: datetime
    key_id: str
    public_key_digest: str
    key_not_before: datetime
    key_not_after: datetime
    raw: dict[str, object]
    catalog_records: dict[str, ExternalQuantitativeCatalogAuthorityRecord]
    current_catalog_digests: frozenset[str]
    policy_records: dict[str, PolicyAuthorityRecord]
    current_policy_digests: frozenset[str]
    context_records: dict[str, ExternalEvidenceMeasurementContextV1]
    current_context_digests: frozenset[str]
    actions: tuple[_AdministrationAction, ...]


@dataclass(frozen=True, slots=True)
class _ActiveKey:
    """The key material and validity interval verified during the file read."""

    public_key: Ed25519PublicKey
    public_key_digest: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True, slots=True)
class _AuthorityGeneration:
    """One immutable, receipt-backed authority publication generation."""

    snapshot: _VerifiedSnapshot
    counter: int
    receipt_sequence: int
    receipt_history_digest: str


def _copy_snapshot(snapshot: _VerifiedSnapshot) -> _VerifiedSnapshot:
    """Copy every mutable container before handing a candidate to live ports."""
    raw = cast(dict[str, object], json.loads(canonical_json_bytes(snapshot.raw)))
    actions = tuple(
        _AdministrationAction(
            action_id=action.action_id,
            kind=action.kind,
            effective_at=action.effective_at,
            actor_id=action.actor_id,
            payload=cast(dict[str, object], json.loads(canonical_json_bytes(action.payload))),
        )
        for action in snapshot.actions
    )
    return _VerifiedSnapshot(
        organization_id=snapshot.organization_id,
        sequence=snapshot.sequence,
        digest=snapshot.digest,
        issued_at=snapshot.issued_at,
        valid_until=snapshot.valid_until,
        key_id=snapshot.key_id,
        public_key_digest=snapshot.public_key_digest,
        key_not_before=snapshot.key_not_before,
        key_not_after=snapshot.key_not_after,
        raw=raw,
        catalog_records=dict(snapshot.catalog_records),
        current_catalog_digests=frozenset(snapshot.current_catalog_digests),
        policy_records=dict(snapshot.policy_records),
        current_policy_digests=frozenset(snapshot.current_policy_digests),
        context_records=dict(snapshot.context_records),
        current_context_digests=frozenset(snapshot.current_context_digests),
        actions=actions,
    )


@dataclass(frozen=True, slots=True)
class _ProviderConfig:
    organization_id: str
    key_registry_path: Path
    snapshot_path: Path
    catalog_administration_actor_id: str
    queue_policy: ExternalRelativeVolumeQueuePolicy


@dataclass(frozen=True, slots=True)
class _AdministrationAction:
    action_id: str
    kind: str
    effective_at: datetime
    actor_id: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Receipt:
    sequence: int
    snapshot_digest: str
    previous_snapshot_digest: str | None
    key_id: str
    public_key_digest: str
    history_digest: str
    snapshot: dict[str, object]
